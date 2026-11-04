"""La synthèse d'un dossier : qui est cette personne, et quoi vérifier.

Trois choses, dans l'ordre où un recruteur les cherche :

- **le profil** : deux phrases, « profil logistique et commerce, Master, plus de
  douze ans d'expérience dont six en énergie » ;
- **ce qui mérite d'être noté** : une certification, une langue, un poste
  d'encadrement, une expérience hors du Togo, une formation qui sort du lot ;
- **ce qu'il faut vérifier** : un motif que le dossier pourrait contredire, une
  attestation qui manque, un trou dans le parcours.

Tout est calculé sur ce qui a déjà été lu : aucun appel, rien d'inventé, et le
même dossier donne toujours le même texte. Ce sont des constats, jamais un avis
sur la personne : « à vérifier » dit où regarder, pas quoi décider. Rien ici ne
parle d'âge, de sexe, de nationalité, ni ne genre la personne.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from app.domain import familles
from app.domain.profil import Experience, ProfilCandidat
from app.domain.referentiel import NiveauDiplome, PieceDossier
from app.models.recrutement import Candidature
from app.services.preselection import construire_exigences, construire_profil

P = PieceDossier
_LOCAUX = frozenset({"togo", "tg"})
_MOTS_D_ENCADREMENT = (
    "directeur", "directrice", "chef", "responsable", "manager", "head", "coordonnateur",
    "coordinateur", "coordonnatrice", "coordinatrice", "superviseur", "superviseure",
)
# Une formation qui se remarque d'elle-même. Courte, et sujette à discussion :
# c'est une mention, jamais un point de plus.
_ETABLISSEMENTS_REMARQUES = (
    "hec", "essec", "escp", "edhec", "em lyon", "sciences po", "polytechnique", "centrale",
    "mines paris", "insead", "london school of economics", "harvard", "stanford", "mit",
    "oxford", "cambridge", "cesag", "esp dakar", "2ie",
)
# Un trou de moins d'un an n'a rien de remarquable.
_TROU_MINIMAL = 12
_MAX_NOTES = 6
_MAX_VERIFICATIONS = 6


@dataclass(slots=True)
class Synthese:
    profil: str = ""
    notes: list[str] = field(default_factory=list)
    a_verifier: list[str] = field(default_factory=list)
    # Les domaines qu'une expérience peut compter, pour le bouton du recruteur.
    domaines_specifiques: list[str] = field(default_factory=list)


def duree_en_lettres(mois: int) -> str:
    if mois < 12:
        return f"{mois} mois"
    annees = mois // 12
    return f"{annees} an{'s' if annees > 1 else ''}"


def _mois_entre(debut: date, fin: date) -> int:
    return max((fin.year - debut.year) * 12 + fin.month - debut.month, 0)


def _champs(profil: ProfilCandidat, reference: date) -> list[str]:
    """Les deux familles qui pèsent le plus dans le parcours."""
    poids: Counter[str] = Counter()
    for experience in profil.experiences:
        debut, fin = experience.intervalle(reference)
        texte = f"{experience.poste} {experience.employeur} {' '.join(experience.domaines)}"
        for famille in familles.familles_de(texte):
            poids[famille.libelle] += max(_mois_entre(debut, fin), 1)
    for diplome in profil.diplomes:
        for famille in familles.familles_de(f"{diplome.intitule} {diplome.domaine}"):
            # Un diplôme compte pour deux ans de pratique dans le champ.
            poids[famille.libelle] += 24
    return [libelle for libelle, _ in poids.most_common(2)]


def _liste(elements: list[str]) -> str:
    if len(elements) < 2:
        return "".join(elements)
    return f"{', '.join(elements[:-1])} et {elements[-1]}"


def _plus_recente(profil: ProfilCandidat) -> Experience | None:
    if not profil.experiences:
        return None
    return max(profil.experiences, key=lambda e: (e.fin is None, e.fin or e.debut, e.debut))


def _lisible(valeur: str) -> bool:
    return bool(valeur) and "non précisé" not in valeur


def _phrase_profil(profil: ProfilCandidat, specifiques: list[tuple[str, int]], reference: date) -> str:
    morceaux: list[str] = []
    champs = _champs(profil, reference)
    recente = _plus_recente(profil)
    if champs:
        morceaux.append(f"Profil {_liste(champs)}")
    elif recente is not None and _lisible(recente.poste):
        morceaux.append(f"Profil de {recente.poste}")

    principal = profil.diplome_principal
    if principal is not None:
        niveau = "Bac" if not principal.niveau else f"Bac+{int(principal.niveau)}"
        titre = principal.intitule.strip()
        morceaux.append(f"{niveau} ({titre})" if titre else niveau)

    total = profil.mois_experience(reference)
    if total:
        experience = (
            f"plus de {duree_en_lettres(total)} d'expérience"
            if total >= 12
            else f"{duree_en_lettres(total)} d'expérience"
        )
        details = [f"{duree_en_lettres(mois)} en {nom}" for nom, mois in specifiques if mois]
        if details:
            experience += f" dont {_liste(details)}"
        morceaux.append(experience)

    phrase = ", ".join(morceaux)
    if phrase:
        phrase = phrase[0].upper() + phrase[1:] + "."
    if recente is not None and _lisible(recente.poste):
        libelle = "Poste actuel" if recente.fin is None else "Dernier poste"
        chez = f" chez {recente.employeur}" if _lisible(recente.employeur) else ""
        phrase = f"{phrase} {libelle} : {recente.poste}{chez}.".strip()
    return phrase


def _notes(profil: ProfilCandidat, candidature: Candidature) -> list[str]:
    notes: list[str] = []
    for diplome in profil.diplomes:
        intitule = f" {diplome.intitule.lower()} "
        etablissement = f" {(diplome.etablissement or '').lower()} "
        remarque = next(
            (e for e in _ETABLISSEMENTS_REMARQUES if f" {e} " in etablissement or f" {e} " in intitule),
            None,
        )
        if remarque:
            notes.append(f"Formation : {diplome.intitule} ({diplome.etablissement or remarque.upper()})")
        elif diplome.niveau >= NiveauDiplome.BAC_PLUS_8 or " mba " in intitule:
            notes.append(f"Formation : {diplome.intitule}")
    if sum(1 for d in profil.diplomes if d.niveau >= NiveauDiplome.BAC_PLUS_5) >= 2:
        notes.append("Deux formations de niveau Bac+5 ou plus")

    if profil.certifications:
        notes.append("Certifications : " + ", ".join(profil.certifications[:3]))

    autres = sorted(x for x in profil.langues if x.casefold() not in ("français", "francais"))
    if autres:
        notes.append("Langues : " + ", ".join(autres[:4]))

    encadrement = [
        e.poste
        for e in sorted(profil.experiences, key=lambda e: e.debut, reverse=True)
        if any(m in e.poste.lower() for m in _MOTS_D_ENCADREMENT)
    ]
    if encadrement:
        notes.append(f"Encadrement : {encadrement[0]}")

    pays = sorted({e.pays for e in profil.experiences if e.pays and e.pays.casefold() not in _LOCAUX})
    if pays:
        notes.append("Expérience hors du Togo : " + ", ".join(pays[:3]))
    return list(dict.fromkeys(notes))[:_MAX_NOTES]


def _trous(profil: ProfilCandidat, reference: date) -> list[str]:
    periodes = sorted(e.intervalle(reference) for e in profil.experiences)
    trous: list[str] = []
    fin_courante: date | None = None
    for debut, fin in periodes:
        if fin_courante is not None and _mois_entre(fin_courante, debut) >= _TROU_MINIMAL:
            trous.append(
                f"Interruption de {duree_en_lettres(_mois_entre(fin_courante, debut))} "
                f"dans le parcours, de {fin_courante.year} à {debut.year}"
            )
        fin_courante = fin if fin_courante is None else max(fin_courante, fin)
    return trous


def _a_verifier(profil: ProfilCandidat, candidature: Candidature, reference: date) -> list[str]:
    points: list[str] = []
    for motif in candidature.eliminations:
        if motif.actif and motif.indice:
            points.append(f"{motif.motif.libelle} : {motif.indice}")

    types = Counter(p.type_piece for p in candidature.pieces)
    if profil.experiences and not types[P.ATTESTATIONS_TRAVAIL.value]:
        points.append("Aucune attestation de travail au dossier pour confirmer le parcours")
    elif len(profil.experiences) > types[P.ATTESTATIONS_TRAVAIL.value] > 0:
        points.append(
            f"{types[P.ATTESTATIONS_TRAVAIL.value]} attestation(s) pour "
            f"{len(profil.experiences)} expériences : voir lesquelles sont justifiées"
        )
    if profil.diplomes and not types[P.COPIE_DIPLOMES.value]:
        points.append("Diplôme cité sans copie jointe")
    if types[P.CV.value] > 1:
        points.append(f"{types[P.CV.value]} documents rangés comme CV : voir si l'un est autre chose")
    non_classes = [
        p for p in candidature.pieces if p.type_piece == P.AUTRE.value and not p.intitule_libre
    ]
    if non_classes:
        points.append(f"{len(non_classes)} document(s) non identifié(s) à ouvrir")
    points.extend(_trous(profil, reference))
    sans_employeur = sum(1 for e in profil.experiences if not _lisible(e.employeur))
    if sans_employeur:
        points.append(f"{sans_employeur} expérience(s) sans employeur lu")
    return list(dict.fromkeys(points))[:_MAX_VERIFICATIONS]


def rediger(candidature: Candidature, reference: date | None = None) -> Synthese:
    """La synthèse d'une candidature chargée. Ne touche pas à la base."""
    reference = reference or date.today()
    pieces = frozenset(p.type_piece for p in candidature.pieces)
    profil = construire_profil(candidature.candidat, pieces)

    specifiques: list[tuple[str, int]] = []
    domaines: list[str] = []
    if candidature.poste is not None:
        exigences = construire_exigences(candidature.poste, None)
        specifiques = [
            (e.nom, profil.mois_experience_specifique(reference, e.domaines))
            for e in exigences.specifiques
            if e.domaines
        ]
        domaines = sorted({d for e in exigences.specifiques for d in e.domaines})
    return Synthese(
        profil=_phrase_profil(profil, specifiques, reference),
        notes=_notes(profil, candidature),
        a_verifier=_a_verifier(profil, candidature, reference),
        domaines_specifiques=domaines,
    )
