"""Ce que les RH doivent regarder, et seulement cela.

Relire seize dossiers pour en corriger trois, c'est le travail que la
plateforme devait leur épargner. Sur les dossiers réels, chaque erreur de
lecture notable s'annonçait par un signe visible : un PDF qui mêle CV, lettre
et attestations ; un CV de deux pages dont on n'a tiré aucune expérience ; un
master « en cours » compté comme obtenu ; une pièce restée illisible. Et une
erreur ne pèse que si elle change quelque chose : quatre ans et dix mois pour
cinq demandés, ou une note à un point du seuil.

Chaque dossier reçoit donc une voie :

- **RELIRE** : un signe d'erreur grave — le dossier entier est à rouvrir ;
- **QUESTION** : un ou deux points précis à trancher, rien d'autre ;
- **SUR** : rien ne signale d'erreur ni d'enjeu — vérifié automatiquement ;
- **ECARTE** : un motif net (deux ans pour dix demandés, une licence pour un
  master exigé, une candidature hors délai) et aucun doute sur la lecture —
  l'élimination reste à confirmer, mais d'un geste pour tous ;
- **FAIT** : un relecteur a déjà confirmé les données.

Le danger d'un motif « net », c'est la lecture qui l'a fondé : un CV dont on
n'a lu qu'un emploi sur quatre paraît très en dessous du seuil. Quand les dates
écrites dans le CV couvrent bien plus que ce que la lecture compte, le dossier
est à relire, jamais écarté.

Un dossier sur dix de la voie sûre remonte tout de même, tiré au hasard mais
toujours le même : c'est ce qui permet de voir si la plateforme se trompe avec
assurance. Et aucune voie n'élimine personne : un motif reste à confirmer par
un humain, il devient seulement une question au lieu d'une relecture entière.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date

from app.domain import familles
from app.domain.referentiel import PieceDossier as P
from app.models.recrutement import Candidature
from app.services import decoupage
from app.services.lecture_locale import plages, plat, rubriques
from app.services.preselection import construire_exigences, construire_profil
from app.services.synthese import duree_en_lettres

RELIRE = "RELIRE"
QUESTION = "QUESTION"
SUR = "SUR"
ECARTE = "ECARTE"
FAIT = "FAIT"
# Un motif d'élimination net : une décision à confirmer, pas un doute.
DECISION = "DECISION"

# Un dossier sûr sur dix remonte pour contrôle.
PART_CONTROLEE = 10
# En deçà d'autant de mois autour d'un seuil d'ancienneté, une date mal lue
# fait basculer la note.
MARGE_MOIS = 6
# Autour du seuil de présélection.
MARGE_POINTS = 1.0
# Un CV qui fait au moins cela et dont on ne tire rien a été mal lu.
CV_CONSISTANT = 1200
_SANS_TEXTE = 40

_ETAT_CIVIL = {
    P.PIECE_IDENTITE.value, P.PASSEPORT.value, P.CERTIFICAT_NATIONALITE.value,
    P.CASIER_JUDICIAIRE.value, P.CERTIFICAT_MEDICAL.value, P.PHOTO.value,
}
_LIBELLES = {
    P.LETTRE_MOTIVATION.value: "une lettre de motivation",
    P.ATTESTATIONS_TRAVAIL.value: "des attestations de travail",
    P.COPIE_DIPLOMES.value: "des diplômes",
}
_PAS_OBTENU = re.compile(r"\b(?:en cours|in progress|ongoing|admissibilite|admissible)\b")


@dataclass(frozen=True, slots=True)
class Signal:
    code: str
    gravite: str  # RELIRE, QUESTION ou DECISION
    texte: str


@dataclass(slots=True)
class Confiance:
    voie: str
    signaux: list[Signal] = field(default_factory=list)
    controle: bool = False


def evaluer(candidature: Candidature, reference: date | None = None) -> Confiance:
    """La voie d'une candidature chargée (pièces, parcours, motifs, note)."""
    candidat = candidature.candidat
    if candidat.verifie_le is not None:
        return Confiance(FAIT)

    signaux: list[Signal] = []
    signaux += _lecture(candidature)
    signaux += _pieces(candidature)
    signaux += _diplomes(candidature, reference or date.today())
    signaux += _enjeux(candidature)
    signaux += _decisions(candidature)

    if any(s.gravite == RELIRE for s in signaux):
        return Confiance(RELIRE, signaux)
    if any(s.gravite == QUESTION for s in signaux):
        return Confiance(QUESTION, signaux)
    if signaux:
        return Confiance(ECARTE, signaux)
    if _tire_au_sort(candidature.id):
        return Confiance(
            QUESTION,
            [Signal("controle", QUESTION, "Contrôle au hasard : un coup d'œil pour vérifier que la lecture tient.")],
            controle=True,
        )
    return Confiance(SUR)


def _tire_au_sort(identifiant: str) -> bool:
    """Toujours le même tirage pour un dossier : il ne change pas d'une visite à l'autre."""
    return int(hashlib.sha256(identifiant.encode()).hexdigest()[:8], 16) % 100 < PART_CONTROLEE


def _texte_cv(candidature: Candidature) -> str:
    return "\n".join(p.texte_extrait or "" for p in candidature.pieces if p.type_piece == P.CV.value)


def _lecture(candidature: Candidature) -> list[Signal]:
    """Ce que la lecture a manqué, ou inventé."""
    signaux: list[Signal] = []
    candidat = candidature.candidat
    cv = _texte_cv(candidature)
    if len(cv.strip()) >= CV_CONSISTANT:
        if not candidat.experiences:
            signaux.append(Signal("parcours_vide", RELIRE, "Le CV est consistant mais aucune expérience n'en a été tirée."))
        if not candidat.diplomes:
            signaux.append(Signal("diplomes_vides", RELIRE, "Le CV est consistant mais aucun diplôme n'en a été tiré."))

    mois_ecrits = _mois_couverts_par_le_cv(cv, date.today())
    mois_lus = _mois_lus(candidature)
    # Une lecture incomplète ne compte que si elle change le sort du dossier :
    # sous l'ancienneté exigée, l'emploi oublié fait passer de zéro à des
    # points, ou d'éliminé à retenu. Au-dessus, il ne vaut qu'un dixième.
    exige = (candidature.poste.annees_experience_min or 0) * 12 if candidature.poste is not None else 0
    if mois_ecrits - mois_lus >= 24 and mois_lus < exige:
        signaux.append(
            Signal(
                "lecture_incomplete", RELIRE,
                f"Les dates du CV couvrent environ {duree_en_lettres(mois_ecrits)}, la lecture n'en compte que "
                f"{duree_en_lettres(mois_lus) if mois_lus else 'rien'} : des emplois ont pu être oubliés.",
            )
        )

    tout = "\n".join(p.texte_extrait or "" for p in candidature.pieces)
    if tout.strip():
        introuvables = [
            e for e in candidat.experiences
            if not any(familles.cite(tout, v) for v in (e.employeur, e.poste) if v and "non précisé" not in v)
        ]
        if introuvables:
            signaux.append(
                Signal(
                    "non_ancre", QUESTION,
                    f"{len(introuvables)} expérience(s) introuvable(s) telle(s) quelle(s) dans les pièces "
                    f"(« {introuvables[0].poste} ») : mal lue(s) ou inventée(s) ?",
                )
            )
    attente = (candidat.propositions_lecture or {}).get("attente") or []
    if attente:
        signaux.append(
            Signal("propositions", QUESTION, f"{len(attente)} proposition(s) de la dernière lecture à accepter ou écarter.")
        )
    return signaux


def _mois_couverts_par_le_cv(cv: str, reference: date) -> int:
    """Du plus ancien début d'emploi écrit dans le CV jusqu'à la fin la plus récente.

    Seule la rubrique « expérience » compte quand on la trouve : les années
    d'études s'écrivent aussi en plages.
    """
    sections = rubriques(cv)
    formation = set(sections.get("formation") or [])
    lignes = sections.get("experience") or [l for l in cv.splitlines() if l not in formation]
    debuts, fins = [], []
    for ligne in lignes:
        for plage in plages(ligne, reference):
            debuts.append(plage.debut)
            fins.append(plage.fin or f"{reference.year:04d}-{reference.month:02d}")
    par_plages = 0
    if debuts:
        d, f = min(debuts), max(fins)
        par_plages = max(0, (int(f[:4]) - int(d[:4])) * 12 + int(f[5:7]) - int(d[5:7]))
    # Filet : toutes les plages ne se lisent pas (« Fév. 2015 – Oct. 2018 » sur
    # deux colonnes). L'année la plus ancienne écrite dans la rubrique dit au
    # moins depuis quand le candidat travaille ; on retire un an de marge.
    # Sur deux colonnes, les rubriques se mêlent : on regarde aussi tout le CV,
    # hors des lignes d'études, de certificats ou d'état civil.
    candidates = [*lignes, *(l for l in cv.splitlines() if not _HORS_EMPLOI.search(plat(l)))]
    annees = [
        int(a) for l in candidates for a in _DEBUT_DE_PLAGE.findall(_sans_accents(l)) if 1960 <= int(a) <= reference.year
    ]
    par_annees = max(0, (reference.year - min(annees) - 1) * 12) if annees else 0
    return max(par_plages, par_annees)


def _sans_accents(texte: str) -> str:
    import unicodedata

    decompose = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def _mois_lus(candidature: Candidature) -> int:
    pieces = frozenset(p.type_piece for p in candidature.pieces)
    profil = construire_profil(candidature.candidat, pieces)
    return profil.mois_experience(date.today())


def _pieces(candidature: Candidature) -> list[Signal]:
    """Un fichier qui en contient plusieurs, une pièce sans texte."""
    signaux: list[Signal] = []
    presents = {p.type_piece for p in candidature.pieces}
    for piece in candidature.pieces:
        if piece.type_piece in _ETAT_CIVIL:
            continue
        nom = piece.nom_fichier or piece.type_piece
        texte = piece.texte_extrait or ""
        if len(texte.strip()) < _SANS_TEXTE:
            signaux.append(Signal("illisible", QUESTION, f"« {nom} » n'a pas de texte lisible : l'ouvrir pour voir ce qu'elle contient."))
            continue
        caches = {
            t for t, _ in decoupage.documents_du_texte(texte, piece.type_piece)
            if t in _LIBELLES and t != piece.type_piece and t not in presents
        }
        if caches:
            liste = ", ".join(_LIBELLES[t] for t in sorted(caches))
            signaux.append(
                Signal(
                    "fichier_compose", QUESTION,
                    f"« {nom} » contient aussi {liste} : vérifier que le dossier n'est pas jugé incomplet à tort.",
                )
            )
    return signaux


def _diplomes(candidature: Candidature, reference: date) -> list[Signal]:
    signaux: list[Signal] = []
    for diplome in candidature.candidat.diplomes:
        intitule = plat(diplome.intitule or "")
        futur = diplome.annee is not None and diplome.annee > reference.year
        if futur or _PAS_OBTENU.search(intitule) or intitule.split()[:1] == ["parcours"]:
            signaux.append(
                Signal("diplome_en_cours", QUESTION, f"« {diplome.intitule} » : obtenu, ou encore en cours ?")
            )
    return signaux


def _enjeux(candidature: Candidature) -> list[Signal]:
    """Là où quelques mois, ou un point, changent le sort du dossier."""
    poste = candidature.poste
    if poste is None:
        return []
    signaux: list[Signal] = []
    pieces = frozenset(p.type_piece for p in candidature.pieces)
    profil = construire_profil(candidature.candidat, pieces)
    exigences = construire_exigences(poste, None)
    reference = exigences.date_reference

    if exigences.annees_experience_min:
        mois = profil.mois_experience(reference)
        if abs(mois - exigences.annees_experience_min * 12) <= MARGE_MOIS:
            signaux.append(
                Signal(
                    "seuil_experience", QUESTION,
                    f"{duree_en_lettres(mois)} d'expérience pour {exigences.annees_experience_min} ans demandés : "
                    "vérifier les dates, quelques mois font basculer la note.",
                )
            )
    for exigence in exigences.specifiques:
        if not exigence.annees_min or not exigence.domaines:
            continue
        mois = profil.mois_experience_specifique(reference, exigence.domaines)
        if abs(mois - exigence.annees_min * 12) <= MARGE_MOIS:
            signaux.append(
                Signal(
                    "seuil_specifique", QUESTION,
                    f"{duree_en_lettres(mois)} en {exigence.nom} pour {exigence.annees_min} ans demandés : "
                    "vérifier quels postes comptent.",
                )
            )
    notation = candidature.notation
    seuil = float(poste.seuil_preselection or 0)
    if notation is not None and seuil > 0 and abs(float(notation.note_retenue) - seuil) <= MARGE_POINTS:
        signaux.append(
            Signal("seuil_note", QUESTION, f"Note à moins d'un point du seuil ({seuil:g}) : chaque ligne compte.")
        )
    return signaux


# Les motifs qu'un fait simple suffit à fonder.
_MOTIFS_NETS = {"FORMATION_INSUFFISANTE", "HORS_DELAI", "CONDITION_AGE", "CONDITION_NATIONALITE", "CONDITION_SEXE"}
_MOTIFS_D_ANCIENNETE = {"EXPERIENCE_INSUFFISANTE", "EXPERIENCE_SPECIFIQUE_INSUFFISANTE"}
# En deçà de cette part du seuil, une ancienneté insuffisante est nette.
_PART_NETTE = 0.75
# L'année qui ouvre une plage : « 2015 – 2018 », « Fév. 2015 – Oct. 2018 »,
# « 2019 à ce jour ». Une année seule — naissance, diplôme — n'en est pas une.
_DEBUT_DE_PLAGE = re.compile(
    r"\b((?:19|20)\d\d)\s*(?:[-–—]|\ba\b|\bau\b)\s*(?:[a-z]{3,9}\.?\s*)?"
    r"(?:(?:19|20)\d\d|present|aujourd|ce jour|nos jours|now|current|date)"
)
_HORS_EMPLOI = re.compile(
    r"\b(?:master|licence|maitrise|bts|dut|bac|baccalaureat|diplome|universite|ecole|institut|formation|"
    r"certifica\w*|attestation de reussite|mba|doctorat|ne le|nee le|naissance|age|session|promotion|lycee|college)\b"
)
_ANS = re.compile(r"(\d+)\s*an")
_MOIS = re.compile(r"(\d+)\s*mois")


def _decisions(candidature: Candidature) -> list[Signal]:
    """Un motif d'élimination n'est jamais tranché par la plateforme seule.

    Net — loin du seuil, ou fondé sur un fait simple —, il devient une décision
    à confirmer avec les autres ; discutable — un domaine jugé non conforme,
    une pièce peut-être rangée ailleurs —, il reste une question.
    """
    signaux = []
    for e in candidature.eliminations:
        if e.leve_le is not None or not e.sur_donnee_non_verifiee:
            continue
        code = e.motif.value
        net = code in _MOTIFS_NETS or (code in _MOTIFS_D_ANCIENNETE and _loin_du_seuil(e.attendu, e.constate))
        if net and code == "EXPERIENCE_SPECIFIQUE_INSUFFISANTE":
            # Peu ou pas de mois « dans le domaine » chez quelqu'un qui a
            # longtemps travaillé : c'est l'attribution des domaines qui est en
            # cause, un jugement — pas un manque. Net seulement si même toute
            # son expérience resterait loin du seuil.
            net = _loin_du_seuil(e.attendu, _en_lettres(_mois_lus(candidature)))
        signaux.append(
            Signal(
                f"motif_{code.lower()}", DECISION if net else QUESTION,
                f"{'Motif net' if net else 'Confirmer ou lever'} : {e.motif.libelle} "
                f"(attendu : {e.attendu} ; constaté : {e.constate}).",
            )
        )
    return signaux


def _en_lettres(mois: int) -> str:
    return f"{mois // 12} an(s) et {mois % 12} mois"


def _loin_du_seuil(attendu: str | None, constate: str | None) -> bool:
    """« 2 an(s) et 3 mois » pour « 10 an(s) » : loin. Faute de chiffres, on ne tranche pas."""
    a = _ANS.search(attendu or "")
    if not a:
        return False
    c = _ANS.search(constate or "")
    m = _MOIS.search(constate or "")
    constate_mois = (int(c.group(1)) if c else 0) * 12 + (int(m.group(1)) if m else 0)
    return constate_mois < int(a.group(1)) * 12 * _PART_NETTE
