"""Dépouillement assisté d'un dossier reçu par email.

Une candidature arrivée par message n'a aucun champ structuré : personne n'a
rempli de formulaire. Ce module lit les pièces et propose un parcours, pour que
les RH corrigent au lieu de tout saisir.

Le partage du travail est délibéré :

- **Localement, sans modèle.** Le texte est expurgé par `redaction`, qui
  détecte au passage la date de naissance, le sexe et la nationalité. Ces
  attributs servent aux conditions restrictives du poste ; ils ne quittent
  jamais la machine.
- **Par le modèle.** Seul le parcours professionnel — diplômes, expériences,
  langues, certifications — part à l'extérieur, et seulement sous forme
  expurgée. Le modèle ne voit ni nom, ni email, ni âge, ni nationalité.

Tout ce qui en sort porte la provenance EXTRAIT_IA. Rien ne peut donc éliminer
un candidat avant qu'un humain n'ait confirmé.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.referentiel import NiveauDiplome, Sexe, normaliser_domaine
from app.llm.base import DossierExtrait, LLMError
from app.llm.factory import get_provider
from app.models import (
    Candidat,
    Candidature,
    DiplomeCandidat,
    ExperienceCandidat,
    Provenance,
)
from app.services import extraction, parametres, redaction, storage
from app.services.preselection import charger_candidature, evaluer_candidature

logger = logging.getLogger(__name__)

# En deçà, le document est une image ou un scan : rien à dépouiller.
MIN_CARACTERES = extraction.MIN_USEFUL_CHARS


@dataclass(slots=True)
class ResultatDepouillement:
    diplomes: int = 0
    experiences: int = 0
    langues: int = 0
    certifications: int = 0
    demographiques: dict[str, str] = field(default_factory=dict)
    pieces_lues: int = 0
    avertissements: list[str] = field(default_factory=list)

    @property
    def a_produit_quelque_chose(self) -> bool:
        return bool(self.diplomes or self.experiences or self.langues or self.certifications)


def _mois_vers_date(valeur: str | None) -> date | None:
    """« 2015-03 », « 2015 », « 2015-03-14 » → une date. Sinon None."""
    if not valeur:
        return None
    morceaux = str(valeur).strip().split("-")
    try:
        annee = int(morceaux[0])
        mois = int(morceaux[1]) if len(morceaux) > 1 else 1
        jour = int(morceaux[2]) if len(morceaux) > 2 else 1
    except (ValueError, IndexError):
        return None
    if not 1900 <= annee <= 2100 or not 1 <= mois <= 12:
        return None
    try:
        return date(annee, mois, min(jour, 28))
    except ValueError:
        return None


async def texte_du_dossier(candidature: Candidature) -> tuple[str, list[str]]:
    """Concatène le texte lisible des pièces. Renvoie aussi les avertissements."""
    depot = storage.get_storage()
    morceaux: list[str] = []
    avertissements: list[str] = []

    for piece in candidature.pieces:
        if not piece.chemin_stockage:
            continue
        try:
            donnees = await depot.read(piece.chemin_stockage)
            document = await extraction.extract(
                donnees, piece.type_mime or "", piece.nom_fichier or ""
            )
        except (extraction.UnreadableDocument, OSError, ValueError) as exc:
            avertissements.append(f"{piece.nom_fichier or piece.type_piece} : {exc}")
            continue

        if len(document.text.strip()) < MIN_CARACTERES:
            avertissements.append(
                f"{piece.nom_fichier or piece.type_piece} : trop peu de texte "
                "(document scanné ?)"
            )
            continue
        morceaux.append(document.text)

    return "\n\n".join(morceaux), avertissements


def _date_francaise(valeur: str | None) -> date | None:
    """« 03/09/1984 », « 3-9-1984 », « 1984-09-03 » → une date.

    Les CV d'ici écrivent le jour en premier ; `_mois_vers_date` ne lit que
    l'ordre ISO et rendrait None sur la forme la plus courante.
    """
    if not valeur:
        return None
    morceaux = [m for m in re.split(r"[/.\-\s]+", str(valeur).strip()) if m.isdigit()]
    if len(morceaux) < 3:
        return _mois_vers_date(valeur)
    a, b, c = (int(x) for x in morceaux[:3])
    jour, mois, annee = (c, b, a) if a > 31 else (a, b, c)
    if annee < 100:
        annee += 1900 if annee > 30 else 2000
    if not (1 <= mois <= 12 and 1 <= jour <= 31 and 1900 <= annee <= 2100):
        return None
    try:
        return date(annee, mois, jour)
    except ValueError:
        return None


def _nettoyer_nationalite(valeur: str) -> str:
    """Isole l'adjectif de nationalité.

    L'expression régulière capture jusqu'au séparateur suivant et ramasse
    parfois la suite de la ligne — « Togolaise - Sexe : Feminin ». Seule la
    tête nous intéresse.
    """
    tete = re.split(r"[-–—,;|]|\bsexe\b|\bgenre\b", valeur, maxsplit=1, flags=re.IGNORECASE)[0]
    return " ".join(tete.split())[:64]


def _sexe_depuis(valeur: str) -> Sexe | None:
    brut = valeur.strip().lower()
    if brut.startswith(("f", "féminin", "feminin", "femme")):
        return Sexe.FEMININ
    if brut.startswith(("m", "masculin", "homme")):
        return Sexe.MASCULIN
    return None


def _appliquer_demographiques(candidat: Candidat, demographiques: dict[str, str]) -> None:
    """Reporte ce que la détection locale a trouvé, sans jamais écraser une
    valeur déjà confirmée par un humain.

    Les clés viennent de `RedactionResult.demographics` : date_of_birth,
    gender, nationality, age, marital_status.
    """
    if candidat.provenance in (Provenance.VERIFIE_RH, Provenance.SAISI_RH):
        return

    naissance = _date_francaise(demographiques.get("date_of_birth"))
    if naissance and candidat.date_naissance is None:
        candidat.date_naissance = naissance

    brut_nationalite = (demographiques.get("nationality") or "").strip()
    if candidat.sexe is None:
        # Le sexe se trouve parfois avalé par la capture de nationalité,
        # les deux étant souvent sur la même ligne du CV.
        source = demographiques.get("gender") or ""
        if not source and "sexe" in brut_nationalite.lower():
            source = re.split(r"\bsexe\b\s*[:\-]?\s*", brut_nationalite, flags=re.IGNORECASE)[-1]
        candidat.sexe = _sexe_depuis(source) if source else None

    if brut_nationalite and not candidat.nationalites:
        nationalite = _nettoyer_nationalite(brut_nationalite)
        if nationalite:
            candidat.nationalites = [nationalite]


def _appliquer_parcours(
    candidat: Candidat, dossier: DossierExtrait, resultat: ResultatDepouillement
) -> list[object]:
    """Construit les diplômes et expériences proposés.

    Ne touche pas à ce qui existe déjà : un dépouillement ne doit jamais
    effacer une saisie humaine, même s'il est relancé.
    """
    nouveaux: list[object] = []
    if candidat.diplomes or candidat.experiences:
        resultat.avertissements.append(
            "Le dossier contenait déjà des données saisies : elles ont été conservées."
        )
        return nouveaux

    for diplome in dossier.diplomes:
        if diplome.niveau is None or not diplome.intitule.strip():
            # Sans niveau, le diplôme ne peut pas être comparé à l'exigence :
            # mieux vaut ne rien proposer que proposer un niveau inventé.
            resultat.avertissements.append(
                f"Diplôme ignoré, niveau indéterminable : {diplome.intitule or 'sans intitulé'}"
            )
            continue
        nouveaux.append(
            DiplomeCandidat(
                candidat_id=candidat.id,
                intitule=diplome.intitule.strip()[:512],
                niveau=int(NiveauDiplome(diplome.niveau)),
                domaine=normaliser_domaine(diplome.domaine or diplome.intitule)[:255],
                etablissement=(diplome.etablissement or None),
                annee=diplome.annee,
                provenance=Provenance.EXTRAIT_IA,
            )
        )
        resultat.diplomes += 1

    for experience in dossier.experiences:
        debut = _mois_vers_date(experience.debut)
        if debut is None or not experience.employeur.strip():
            resultat.avertissements.append(
                f"Expérience ignorée, date de début illisible : "
                f"{experience.poste or experience.employeur or 'sans intitulé'}"
            )
            continue
        nouveaux.append(
            ExperienceCandidat(
                candidat_id=candidat.id,
                poste=(experience.poste or "poste non précisé")[:512],
                employeur=experience.employeur.strip()[:512],
                debut=debut,
                fin=_mois_vers_date(experience.fin),
                domaines=[normaliser_domaine(d) for d in experience.domaines] or None,
                pays=(experience.pays or None),
                provenance=Provenance.EXTRAIT_IA,
            )
        )
        resultat.experiences += 1

    return nouveaux


async def depouiller(db: AsyncSession, candidature: Candidature) -> ResultatDepouillement:
    """Lit les pièces, propose un parcours, réévalue. Ne commit pas."""
    resultat = ResultatDepouillement()
    candidat = candidature.candidat

    texte, avertissements = await texte_du_dossier(candidature)
    resultat.avertissements.extend(avertissements)
    resultat.pieces_lues = sum(1 for p in candidature.pieces if p.chemin_stockage)

    if len(texte.strip()) < MIN_CARACTERES:
        resultat.avertissements.append(
            "Aucun texte exploitable dans le dossier. Saisie manuelle nécessaire."
        )
        return resultat

    # 1. Expurgation locale. Les attributs sensibles sont détectés ici et
    #    n'iront pas plus loin.
    reglages = await parametres.lire(db)
    expurge = await redaction.redact(
        texte,
        redaction.KnownValues(
            full_name=f"{candidat.nom} {candidat.prenom}".strip(),
            email=candidat.email,
            phone=candidat.telephone,
        ),
        redact_demographics=reglages.redact_demographics,
    )
    resultat.demographiques = dict(expurge.demographics)
    _appliquer_demographiques(candidat, expurge.demographics)

    # 2. Le modèle ne reçoit que le texte expurgé.
    try:
        dossier = await get_provider().extraire_dossier(expurge.text)
    except (LLMError, OSError) as exc:
        logger.warning("dépouillement impossible pour %s : %s", candidature.id, exc)
        resultat.avertissements.append(f"Extraction indisponible : {exc}")
        return resultat

    for objet in _appliquer_parcours(candidat, dossier, resultat):
        db.add(objet)

    if dossier.langues and not candidat.langues:
        candidat.langues = [x.strip() for x in dossier.langues if x.strip()]
        resultat.langues = len(candidat.langues)
    if dossier.certifications and not candidat.certifications:
        candidat.certifications = [x.strip() for x in dossier.certifications if x.strip()]
        resultat.certifications = len(candidat.certifications)

    await db.flush()

    # 3. Nouvelle évaluation. Le statut restera A_VERIFIER : tout ce qui vient
    #    d'être écrit porte la provenance EXTRAIT_IA.
    rechargee = await charger_candidature(db, candidature.id)
    await evaluer_candidature(db, rechargee)
    return resultat
