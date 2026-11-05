"""Lire les dossiers ailleurs que sur le serveur, et en verser le résultat.

Trois chemins, un seul format : un fichier traité à la main (`result.json`), le
lecteur local qui fait tourner Ollama sur un poste du cabinet, et une lecture
faite dans Claude Code. Tout ce qui revient passe ici, donc par les mêmes
contrôles et par la même protection du travail humain que la lecture du serveur.

Ce qui sort est le texte **expurgé**, identifié par la seule candidature : aucun
nom, aucun fichier. Ce qui revient est ce qui a été **lu**, jamais une note : le
barème reste calculé ici, de la même façon pour tout le monde. Une note jointe au
résultat est ignorée, et le compte rendu le dit.

Une empreinte accompagne chaque dossier : si ses pièces ont changé entre l'envoi
et le retour, le résultat est refusé plutôt que versé sur un dossier qu'il n'a
pas vu.
"""

from __future__ import annotations

import hashlib
import json
import logging

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import prompts
from app.llm.base import DiplomeExtrait, DossierExtrait, ExperienceExtraite
from app.models.base import utcnow
from app.models.recrutement import Candidat, Candidature, Poste
from app.models.travail import ATTENTE, LECTURE_IA, Travail
from app.services import depouillement, lecture_locale, parametres, redaction
from app.services.preselection import charger_candidature

logger = logging.getLogger(__name__)

FORMAT = "tricv-lecture/1"
# Ce qu'un fichier de lecture peut prétendre et qu'on refuse de croire.
_CHAMPS_DE_NOTE = frozenset(
    {"note", "notes", "score", "scores", "rating", "ratings", "points", "classement", "rang", "total"}
)

SCHEMA_DE_REPONSE = (
    "Pour chaque dossier, rendez : candidature_id et empreinte recopiés tels quels, diplomes, "
    "experiences, langues, certifications, et remarques (ce qu'un recruteur doit savoir, sans avis "
    "sur la personne). Ne rendez aucune note : le barème est calculé par la plateforme."
)


class ResultatDossier(BaseModel):
    """Ce qu'un lecteur rend pour un dossier."""

    model_config = ConfigDict(extra="ignore")

    candidature_id: str = Field(min_length=1, max_length=64)
    empreinte: str = Field(min_length=1, max_length=64)
    diplomes: list[DiplomeExtrait] = Field(default_factory=list)
    experiences: list[ExperienceExtraite] = Field(default_factory=list)
    langues: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    remarques: str = Field(default="", max_length=2000)


def empreinte_du_dossier(candidature: Candidature) -> str:
    """Change dès qu'une pièce arrive, part ou change de contenu."""
    morceaux = sorted(
        f"{p.id}:{p.empreinte or len(p.texte_extrait or '')}:{p.type_piece}"
        for p in candidature.pieces
    )
    return hashlib.sha256("|".join(morceaux).encode()).hexdigest()[:32]


async def preparer(db: AsyncSession, candidature: Candidature) -> dict | None:
    """Le dossier tel qu'il sort : expurgé, sans nom ni fichier. None s'il n'a pas de texte."""
    lus, _ = await depouillement.textes_des_pieces(candidature)
    parcours = [(p, t) for p, t in lus if p.type_piece not in depouillement._ETAT_CIVIL]
    texte = "\n\n".join(t for _, t in parcours)
    if len(texte.strip()) < depouillement.MIN_CARACTERES:
        return None
    cv = "\n\n".join(t for p, t in parcours if p.type_piece == depouillement.PieceDossier.CV.value)
    poste = candidature.poste
    vocabulaire = depouillement.vocabulaire_du_poste(poste)
    locale = lecture_locale.lire(cv or texte, vocabulaire, lexique=(poste.lexique if poste else None) or {})
    candidat = candidature.candidat
    reglages = await parametres.lire(db)
    expurge = await redaction.redact(
        depouillement.composer_pour_ia([(p.type_piece, t) for p, t in parcours], locale),
        redaction.KnownValues(
            full_name=f"{candidat.nom} {candidat.prenom}".strip(),
            email=candidat.email,
            phone=candidat.telephone,
        ),
        redact_demographics=reglages.redact_demographics,
    )
    return {
        "candidature_id": candidature.id,
        "empreinte": empreinte_du_dossier(candidature),
        "domaines": vocabulaire,
        "texte": prompts.extraction_user_prompt(expurge.text),
    }


def consigne(domaines: list[str]) -> str:
    return prompts.extraction_system_prompt(domaines)


async def exporter(db: AsyncSession, poste: Poste, *, tous: bool = False) -> dict:
    """Le lot d'un poste. Par défaut, les dossiers que personne n'a confirmés."""
    requete = (
        select(Candidature.id)
        .join(Candidat, Candidat.id == Candidature.candidat_id)
        .where(Candidature.poste_id == poste.id)
    )
    if not tous:
        requete = requete.where(Candidat.verifie_le.is_(None))
    dossiers = []
    for identifiant in (await db.execute(requete)).scalars():
        prepare = await preparer(db, await charger_candidature(db, identifiant))
        if prepare is not None:
            dossiers.append(prepare)
    vocabulaire = depouillement.vocabulaire_du_poste(poste)
    return {
        "format": FORMAT,
        "genere_le": utcnow().isoformat(timespec="seconds"),
        "poste": {"id": poste.id, "intitule": poste.intitule},
        "consigne": consigne(vocabulaire),
        "reponse_attendue": SCHEMA_DE_REPONSE,
        "dossiers": dossiers,
    }


async def verser(
    db: AsyncSession, brut: dict, lecteur: str, *, poste_id: str | None = None
) -> dict:
    """Verse un dossier lu ailleurs. Ne commit pas. Rend un compte rendu.

    `etat` : « lu », « inconnu », « autre_poste », « perime » ou « illisible ».
    """
    identifiant = str(brut.get("candidature_id", ""))[:64] if isinstance(brut, dict) else ""
    try:
        lu = ResultatDossier.model_validate(brut)
    except ValidationError as exc:
        return {"candidature_id": identifiant, "etat": "illisible", "detail": str(exc)[:300]}

    candidature = await charger_candidature(db, lu.candidature_id)
    if candidature is None:
        return {"candidature_id": identifiant, "etat": "inconnu"}
    if poste_id is not None and candidature.poste_id != poste_id:
        return {"candidature_id": identifiant, "etat": "autre_poste"}
    if lu.empreinte != empreinte_du_dossier(candidature):
        return {"candidature_id": identifiant, "etat": "perime"}

    notes_ignorees = sorted(_CHAMPS_DE_NOTE & set(brut))
    resultat = await depouillement.depouiller(
        db,
        candidature,
        lu=DossierExtrait(
            diplomes=lu.diplomes,
            experiences=lu.experiences,
            langues=lu.langues,
            certifications=lu.certifications,
        ),
    )
    rechargee = await charger_candidature(db, lu.candidature_id)
    rechargee.derniere_lecture = {
        "lecteur": lecteur[:120],
        "le": utcnow().isoformat(timespec="seconds"),
        "remarques": lu.remarques.strip() or None,
    }
    # Déjà lu : inutile de le relire dans la file.
    await db.execute(
        delete(Travail).where(
            Travail.candidature_id == lu.candidature_id,
            Travail.nature == LECTURE_IA,
            Travail.etat == ATTENTE,
        )
    )
    await db.flush()
    return {
        "candidature_id": identifiant,
        "etat": "lu",
        "diplomes": resultat.diplomes,
        "experiences": resultat.experiences,
        "propositions": resultat.propositions,
        "notes_ignorees": notes_ignorees,
    }


async def verser_fichier(
    db: AsyncSession, contenu: bytes, lecteur_par_defaut: str, poste_id: str
) -> dict:
    """Verse un `result.json`, dossier par dossier. Un dossier refusé n'arrête pas les autres."""
    try:
        document = json.loads(contenu.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Ce fichier n'est pas du JSON lisible : {exc}") from exc
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise ValueError(f"Ce fichier n'est pas un résultat de lecture ({FORMAT}).")
    dossiers = document.get("dossiers")
    if not isinstance(dossiers, list):
        raise ValueError("Ce fichier ne contient pas de liste « dossiers ».")

    lecteur = str(document.get("lecteur") or lecteur_par_defaut)
    comptes: dict[str, int] = {}
    details: list[dict] = []
    for brut in dossiers:
        try:
            compte = await verser(db, brut, lecteur, poste_id=poste_id)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - un dossier ne doit pas perdre le lot
            await db.rollback()
            logger.exception("lecture externe : dossier refusé")
            identifiant = brut.get("candidature_id", "") if isinstance(brut, dict) else ""
            compte = {"candidature_id": identifiant, "etat": "illisible", "detail": type(exc).__name__}
        comptes[compte["etat"]] = comptes.get(compte["etat"], 0) + 1
        details.append(compte)
    return {
        "lecteur": lecteur,
        "comptes": comptes,
        "propositions": sum(d.get("propositions", 0) for d in details),
        "notes_ignorees": sum(1 for d in details if d.get("notes_ignorees")),
        "details": details,
    }
