"""Ce qu'une relecture trouve, face à ce qu'un humain a déjà décidé.

La lecture se relance seule : à l'arrivée d'une pièce, après une mise à jour. Elle
ne doit donc jamais défaire le travail de quelqu'un. La règle tient en trois
points :

- **Ce qui vient d'un humain ne bouge pas** : une ligne confirmée, saisie,
  déclarée par le candidat, ou comptée à la main pour un domaine.
- **Un dossier confirmé est figé** : plus rien n'y entre sans accord.
- **Ce que la lecture voit autrement devient une proposition**, que le recruteur
  accepte ou écarte. Une proposition écartée ne revient pas.

Une proposition n'a aucun effet sur la note tant qu'elle n'est pas acceptée.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from app.domain import familles
from app.models.enums import Provenance
from app.models.recrutement import Candidat, DiplomeCandidat, ExperienceCandidat

_RECOUVREMENT_MINIMAL = 0.6
# Un mois d'écart sur une date n'est pas une divergence : c'est une façon de lire.
_ECART_DE_DATE_MOIS = 1


def protege(candidat: Candidat) -> bool:
    """Le dossier est-il figé, pour tout ce qu'il ne contient pas encore ?

    Confirmé par un humain, ou rempli par le candidat ou les RH eux-mêmes : ce
    qu'on y ajouterait serait compté sans que personne ne l'ait voulu.
    """
    lignes = [*candidat.diplomes, *candidat.experiences]
    return candidat.verifie_le is not None or any(
        l.provenance in (Provenance.DECLARE, Provenance.SAISI_RH) for l in lignes
    )


def _mois(valeur: date | None, defaut: int) -> int:
    return valeur.year * 12 + valeur.month if valeur else defaut


def _recouvrement(un: ExperienceCandidat, autre: ExperienceCandidat) -> float:
    aujourd_hui = date.today()
    maintenant = aujourd_hui.year * 12 + aujourd_hui.month
    d1, f1 = _mois(un.debut, maintenant), _mois(un.fin, maintenant)
    d2, f2 = _mois(autre.debut, maintenant), _mois(autre.fin, maintenant)
    return (min(f1, f2) - max(d1, d2)) / max(min(f1 - d1, f2 - d2), 1)


def _mots(texte: str | None) -> set[str]:
    return set(familles.mots(texte or ""))


def _se_rejoignent(un: str | None, autre: str | None) -> bool:
    """L'un dit-il la même chose que l'autre, en plus ou moins de mots ?"""
    a, b = _mots(un), _mots(autre)
    return not a or not b or a <= b or b <= a


def _meme_emploi(nouvelle: ExperienceCandidat, lignes: list) -> ExperienceCandidat | None:
    for ligne in lignes:
        if _recouvrement(ligne, nouvelle) < _RECOUVREMENT_MINIMAL:
            continue
        # Deux emplois menés de front se recouvrent aussi : il faut un mot commun.
        if _mots(ligne.employeur) & _mots(nouvelle.employeur) or _mots(ligne.poste) & _mots(nouvelle.poste):
            return ligne
    return None


def _meme_diplome(nouveau: DiplomeCandidat, lignes: list) -> DiplomeCandidat | None:
    for ligne in lignes:
        if ligne.niveau == nouveau.niveau and (
            not ligne.annee or not nouveau.annee or ligne.annee == nouveau.annee
        ):
            return ligne
        if ligne.annee == nouveau.annee and _se_rejoignent(ligne.intitule, nouveau.intitule):
            return ligne
    return None


def _periode(debut: date | None, fin: date | None) -> str:
    return f"{debut:%m/%Y} → {f'{fin:%m/%Y}' if fin else 'en cours'}" if debut else ""


def _vue_experience(e: ExperienceCandidat) -> str:
    return f"{e.poste} — {e.employeur} ({_periode(e.debut, e.fin)})"


def _vue_diplome(d: DiplomeCandidat) -> str:
    return f"{d.intitule} (BAC+{d.niveau}{f', {d.annee}' if d.annee else ''})"


def _valeurs_experience(e: ExperienceCandidat) -> dict:
    return {
        "poste": e.poste,
        "employeur": e.employeur,
        "debut": e.debut.isoformat(),
        "fin": e.fin.isoformat() if e.fin else None,
        "domaines": e.domaines,
        "pays": e.pays,
    }


def _valeurs_diplome(d: DiplomeCandidat) -> dict:
    return {
        "intitule": d.intitule,
        "niveau": d.niveau,
        "domaine": d.domaine,
        "etablissement": d.etablissement,
        "annee": d.annee,
    }


def _proposition(famille: str, action: str, libelle: str, valeurs: dict, cible=None, avant=None) -> dict:
    signature = hashlib.sha1(
        json.dumps([famille, action, cible, valeurs], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    return {
        "id": signature,
        "famille": famille,
        "action": action,
        "libelle": libelle,
        "avant": avant,
        "cible": cible,
        "valeurs": valeurs,
    }


def _dates_differentes(un: date | None, autre: date | None) -> bool:
    if (un is None) != (autre is None):
        return True
    return bool(un) and abs(_mois(un, 0) - _mois(autre, 0)) > _ECART_DE_DATE_MOIS


def _ecart_experience(ligne: ExperienceCandidat, lue: ExperienceCandidat) -> dict | None:
    if (
        _se_rejoignent(ligne.poste, lue.poste)
        and _se_rejoignent(ligne.employeur, lue.employeur)
        and not _dates_differentes(ligne.debut, lue.debut)
        and not _dates_differentes(ligne.fin, lue.fin)
    ):
        return None
    return _proposition(
        "experience", "modifier", _vue_experience(lue), _valeurs_experience(lue),
        cible=ligne.id, avant=_vue_experience(ligne),
    )


def _ecart_diplome(ligne: DiplomeCandidat, lu: DiplomeCandidat) -> dict | None:
    annee_nouvelle = lu.annee and lu.annee != ligne.annee
    if _se_rejoignent(ligne.intitule, lu.intitule) and not annee_nouvelle:
        return None
    return _proposition(
        "diplome", "modifier", _vue_diplome(lu), _valeurs_diplome(lu),
        cible=ligne.id, avant=_vue_diplome(ligne),
    )


def comparer(candidat: Candidat, nouveaux: list) -> tuple[list, list[dict]]:
    """Trie ce que la lecture a produit : (à enregistrer, à proposer).

    Rien de ce qui est gardé n'est touché ici. Sur un dossier figé, tout ce qui
    existe compte comme gardé, même ce qui attendait encore d'être confirmé.
    """
    fige = protege(candidat)
    gardes_e = [e for e in candidat.experiences if fige or e.provenance is not Provenance.EXTRAIT_IA]
    gardes_d = [d for d in candidat.diplomes if fige or d.provenance is not Provenance.EXTRAIT_IA]
    a_enregistrer: list = []
    a_proposer: list[dict] = []
    for objet in nouveaux:
        if isinstance(objet, ExperienceCandidat):
            ligne = _meme_emploi(objet, gardes_e)
            if ligne is not None:
                ecart = _ecart_experience(ligne, objet)
                if ecart:
                    a_proposer.append(ecart)
            elif fige:
                a_proposer.append(
                    _proposition("experience", "ajouter", _vue_experience(objet), _valeurs_experience(objet))
                )
            else:
                a_enregistrer.append(objet)
        else:
            ligne = _meme_diplome(objet, gardes_d)
            if ligne is not None:
                ecart = _ecart_diplome(ligne, objet)
                if ecart:
                    a_proposer.append(ecart)
            elif fige:
                a_proposer.append(
                    _proposition("diplome", "ajouter", _vue_diplome(objet), _valeurs_diplome(objet))
                )
            else:
                a_enregistrer.append(objet)
    return a_enregistrer, a_proposer


def proposer_listes(candidat: Candidat, langues: list[str], certifications: list[str]) -> list[dict]:
    """Langues et certifications que le dossier confirmé ne porte pas encore."""
    rendu: list[dict] = []
    for famille, lues, actuelles in (
        ("langue", langues, candidat.langues or []),
        ("certification", certifications, candidat.certifications or []),
    ):
        connues = {x.casefold() for x in actuelles}
        for valeur in lues:
            propre = valeur.strip()
            if propre and propre.casefold() not in connues:
                rendu.append(_proposition(famille, "ajouter", propre, {"valeur": propre}))
    return rendu


def enregistrer(candidat: Candidat, propositions: list[dict]) -> int:
    """Remplace celles en attente. Ce qui a été écarté ne revient pas."""
    etat = candidat.propositions_lecture or {}
    ecartees = etat.get("ecartees", [])
    attente = [p for p in propositions if p["id"] not in ecartees]
    # Une nouvelle valeur : SQLAlchemy ne voit pas un JSON modifié sur place.
    candidat.propositions_lecture = {"attente": attente, "ecartees": ecartees}
    return len(attente)


def _date(valeur: str | None) -> date | None:
    return date.fromisoformat(valeur) if valeur else None


def _appliquer(candidat: Candidat, proposition: dict) -> object | None:
    """Rend la ligne à ajouter, s'il y en a une. Ce qui est accepté vaut confirmé."""
    v = proposition["valeurs"]
    famille, cible = proposition["famille"], proposition.get("cible")
    if famille in ("langue", "certification"):
        attribut = "langues" if famille == "langue" else "certifications"
        setattr(candidat, attribut, [*(getattr(candidat, attribut) or []), v["valeur"]])
        return None
    if famille == "experience":
        if cible:
            ligne = next((e for e in candidat.experiences if e.id == cible), None)
            if ligne is None:
                return None
            ligne.poste, ligne.employeur = v["poste"], v["employeur"]
            ligne.debut, ligne.fin = _date(v["debut"]), _date(v["fin"])
            ligne.provenance = Provenance.VERIFIE_RH
            return None
        return ExperienceCandidat(
            candidat_id=candidat.id, poste=v["poste"], employeur=v["employeur"],
            debut=_date(v["debut"]), fin=_date(v["fin"]), domaines=v.get("domaines"),
            pays=v.get("pays"), provenance=Provenance.VERIFIE_RH,
        )
    if cible:
        ligne = next((d for d in candidat.diplomes if d.id == cible), None)
        if ligne is None:
            return None
        ligne.intitule, ligne.niveau, ligne.annee = v["intitule"], v["niveau"], v["annee"]
        ligne.domaine = v["domaine"]
        ligne.etablissement = v.get("etablissement") or ligne.etablissement
        ligne.provenance = Provenance.VERIFIE_RH
        return None
    return DiplomeCandidat(
        candidat_id=candidat.id, intitule=v["intitule"], niveau=v["niveau"], domaine=v["domaine"],
        etablissement=v.get("etablissement"), annee=v.get("annee"), provenance=Provenance.VERIFIE_RH,
    )


def trancher(candidat: Candidat, identifiants: list[str] | None, accepter: bool) -> tuple[list, int]:
    """Accepte ou écarte. Rend (lignes à ajouter, nombre traité).

    `identifiants` vide ou None : toutes celles en attente.
    """
    etat = candidat.propositions_lecture or {}
    attente = list(etat.get("attente", []))
    ecartees = list(etat.get("ecartees", []))
    visees = [p for p in attente if not identifiants or p["id"] in identifiants]
    nouvelles = []
    for proposition in visees:
        if accepter:
            ligne = _appliquer(candidat, proposition)
            if ligne is not None:
                nouvelles.append(ligne)
        else:
            ecartees.append(proposition["id"])
    ids = {p["id"] for p in visees}
    candidat.propositions_lecture = {
        "attente": [p for p in attente if p["id"] not in ids],
        "ecartees": ecartees,
    }
    return nouvelles, len(visees)
