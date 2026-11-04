"""La file des lectures : ce qui ne tient pas dans une requête.

Lire tout un poste par l'IA, c'est des dizaines d'appels à une offre gratuite
qui en refuse dès qu'on va trop vite. Fait dans une requête, le lot s'arrête au
premier quota épuisé et se perd au premier redémarrage. Ici chaque dossier est
une ligne en base : un seul travail à la fois, une pause entre deux appels, et
un quota épuisé **attend** au lieu d'échouer. Tout reprend seul, là où c'était.

Ce n'est pas l'API de lots d'un fournisseur : aucune n'est sûre sur une offre
gratuite, et une file à soi marche avec tous. Le serveur ne tourne qu'en un seul
processus (voir `parametres.appliquer_ia`) : un seul ouvrier suffit, sans verrou.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import case, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.domain.referentiel import PieceDossier
from app.llm.base import LLMIndisponible
from app.models.base import utcnow
from app.models.recrutement import Candidature, PieceCandidature
from app.models.travail import (
    ATTENTE,
    DECOUPAGE,
    ECHEC,
    EN_COURS,
    FAIT,
    LECTURE_IA,
    LECTURE_LOCALE,
    Travail,
)
from app.services import classement_ia, decoupage, depouillement, extraction, storage
from app.services.preselection import charger_candidature

logger = logging.getLogger(__name__)

# Le temps de repos d'un fournisseur épuisé dans la chaîne : repasser plus tôt
# ne servirait à rien.
ATTENTE_DE_QUOTA = timedelta(minutes=15)
# Quatre heures de quota épuisé : ce n'est plus une limite passagère.
ESSAIS_MAX = 16
# Entre deux appels au modèle. Les offres gratuites comptent à la seconde.
PAUSE_ENTRE_APPELS = 3
PAUSE_AU_REPOS = 5
CONSERVATION = timedelta(days=7)


async def ajouter(
    db: AsyncSession, candidatures: list[tuple[str, str | None]], nature: str
) -> int:
    """Met des dossiers en file, sauf ceux qui y sont déjà. Ne commit pas."""
    if not candidatures:
        return 0
    deja = set(
        (
            await db.execute(
                select(Travail.candidature_id).where(
                    Travail.nature == nature,
                    Travail.etat.in_((ATTENTE, EN_COURS)),
                    Travail.candidature_id.in_([c for c, _ in candidatures]),
                )
            )
        ).scalars()
    )
    ajoutes = 0
    for candidature_id, poste_id in candidatures:
        if candidature_id not in deja:
            db.add(Travail(nature=nature, candidature_id=candidature_id, poste_id=poste_id))
            ajoutes += 1
    await db.flush()
    return ajoutes


async def etat_du_poste(db: AsyncSession, poste_id: str) -> dict:
    lignes = (
        await db.execute(
            select(Travail.nature, Travail.etat, Travail.pas_avant, Travail.erreur).where(
                Travail.poste_id == poste_id
            )
        )
    ).all()
    compte = Counter(l.etat for l in lignes)
    maintenant = utcnow()
    reprises = [l.pas_avant for l in lignes if l.etat == ATTENTE and l.pas_avant and l.pas_avant > maintenant]
    echecs = [l.erreur for l in lignes if l.etat == ECHEC and l.erreur]
    return {
        "en_attente": compte[ATTENTE],
        "en_cours": compte[EN_COURS],
        "faits": compte[FAIT],
        "echecs": compte[ECHEC],
        # Vide tant que rien n'attend le retour d'un quota.
        "reprise_le": min(reprises).isoformat() if reprises else None,
        "derniere_erreur": echecs[-1] if echecs else None,
    }


async def annuler(db: AsyncSession, poste_id: str) -> int:
    """Retire ce qui n'a pas commencé. Rien de ce qui est fait n'est défait."""
    resultat = await db.execute(
        delete(Travail).where(Travail.poste_id == poste_id, Travail.etat == ATTENTE)
    )
    return resultat.rowcount or 0


async def oublier_le_termine(db: AsyncSession, poste_id: str) -> None:
    """Un nouveau lot repart de zéro : le suivi ne compte pas l'ancien."""
    await db.execute(
        delete(Travail).where(Travail.poste_id == poste_id, Travail.etat.in_((FAIT, ECHEC)))
    )


async def decouper_les_pieces(db: AsyncSession, candidature: Candidature) -> int:
    """Sépare les PDF fusionnés déposés par le formulaire public.

    Le candidat met tout son dossier dans le champ « CV » : le formulaire ne
    peut pas le voir, et lire un scan de douze pages ne tient pas dans sa
    requête. Le type du champ n'est gardé que si rien de mieux ne se reconnaît.
    Le même fichier déposé dans plusieurs champs ne donne ses pièces qu'une fois.
    """
    depot = storage.get_storage()
    connues = {p.empreinte for p in candidature.pieces if p.empreinte}
    decoupees = 0
    for piece in list(candidature.pieces):
        if piece.type_mime != extraction.PDF_MIME or not piece.chemin_stockage or piece.type_source:
            continue
        donnees = await depot.read(piece.chemin_stockage)
        morceaux = await decoupage.preparer(piece.nom_fichier or "dossier.pdf", donnees, extraction.PDF_MIME)
        if len(morceaux) < 2:
            continue
        if not any(m.type_piece == piece.type_piece for m in morceaux):
            inconnu = next((m for m in morceaux if m.type_piece is None), None)
            if inconnu is not None:
                inconnu.type_piece = piece.type_piece
        decoupage.completer_types(morceaux)
        for morceau in morceaux:
            empreinte = hashlib.sha256(morceau.donnees).hexdigest()
            if empreinte in connues:
                continue
            connues.add(empreinte)
            db.add(
                PieceCandidature(
                    candidature_id=candidature.id,
                    type_piece=morceau.type_piece or PieceDossier.AUTRE.value,
                    intitule_libre=morceau.intitule,
                    nom_fichier=morceau.nom[:255],
                    chemin_stockage=await depot.save(storage.build_key(morceau.type_mime), morceau.donnees),
                    type_mime=morceau.type_mime,
                    taille_octets=len(morceau.donnees),
                    empreinte=empreinte,
                    texte_extrait=morceau.texte or None,
                )
            )
        await depot.delete(piece.chemin_stockage)
        await db.delete(piece)
        decoupees += 1
    await db.flush()
    return decoupees


async def _executer(db: AsyncSession, travail: Travail) -> None:
    candidature = await charger_candidature(db, travail.candidature_id)
    if candidature is None:
        return
    if travail.nature == DECOUPAGE:
        await decouper_les_pieces(db, candidature)
        candidature = await charger_candidature(db, travail.candidature_id)
        await depouillement.depouiller(db, candidature, ia=False)
    elif travail.nature == LECTURE_LOCALE:
        await depouillement.depouiller(db, candidature, ia=False)
    elif travail.nature == LECTURE_IA:
        await classement_ia.classer(candidature)
        await db.flush()
        resultat = await depouillement.depouiller(
            db, await charger_candidature(db, travail.candidature_id)
        )
        if resultat.erreur_ia is not None:
            raise resultat.erreur_ia


async def _suivant(db: AsyncSession) -> Travail | None:
    maintenant = utcnow()
    resultat = await db.execute(
        select(Travail)
        .where(
            Travail.etat == ATTENTE,
            (Travail.pas_avant.is_(None)) | (Travail.pas_avant <= maintenant),
        )
        # Ce qui ne coûte aucun quota passe d'abord.
        .order_by(case((Travail.nature == LECTURE_IA, 1), else_=0), Travail.created_at)
        .limit(1)
    )
    return resultat.scalars().first()


async def _reporter_l_ia(db: AsyncSession, travail: Travail, exc: Exception) -> None:
    """Un quota épuisé vaut pour toute la file : inutile de frapper à chaque dossier."""
    reprise: datetime = utcnow() + ATTENTE_DE_QUOTA
    travail.essais += 1
    if travail.essais >= ESSAIS_MAX:
        travail.etat = ECHEC
        travail.erreur = f"Toujours indisponible après {ESSAIS_MAX} essais : {exc}"[:500]
    else:
        travail.etat = ATTENTE
        travail.erreur = str(exc)[:500]
        travail.pas_avant = reprise
    await db.execute(
        update(Travail)
        .where(Travail.etat == ATTENTE, Travail.nature == LECTURE_IA, Travail.id != travail.id)
        .values(pas_avant=reprise)
    )


async def traiter_un() -> str | None:
    """Fait un travail. Rend sa nature, ou None s'il n'y avait rien à faire."""
    async with SessionLocal() as db:
        travail = await _suivant(db)
        if travail is None:
            return None
        travail.etat = EN_COURS
        await db.commit()
        travail_id, nature = travail.id, travail.nature

    async with SessionLocal() as db:
        travail = await db.get(Travail, travail_id)
        try:
            await _executer(db, travail)
            travail.etat = FAIT
            travail.erreur = None
            await db.commit()
        except LLMIndisponible as exc:
            await db.rollback()
            travail = await db.get(Travail, travail_id)
            await _reporter_l_ia(db, travail, exc)
            await db.commit()
            logger.warning("file : IA indisponible, reprise dans 15 min (%s)", exc)
        except Exception as exc:  # noqa: BLE001 - un dossier ne doit pas arrêter la file
            await db.rollback()
            logger.exception("file : échec du travail %s", travail_id)
            travail = await db.get(Travail, travail_id)
            travail.etat = ECHEC
            travail.erreur = f"{type(exc).__name__} : {exc}"[:500]
            await db.commit()
    return nature


async def reprendre() -> None:
    """Au démarrage : ce qu'un arrêt a interrompu repart, le vieux s'efface."""
    async with SessionLocal() as db:
        await db.execute(update(Travail).where(Travail.etat == EN_COURS).values(etat=ATTENTE))
        await db.execute(
            delete(Travail).where(
                Travail.etat.in_((FAIT, ECHEC)), Travail.created_at < utcnow() - CONSERVATION
            )
        )
        await db.commit()


async def boucle() -> None:
    """L'ouvrier, lancé au démarrage et arrêté avec le serveur."""
    await reprendre()
    while True:
        try:
            nature = await traiter_un()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - base momentanément indisponible
            logger.exception("file : erreur de l'ouvrier")
            nature = None
        if nature == LECTURE_IA:
            await asyncio.sleep(PAUSE_ENTRE_APPELS)
        elif nature is None:
            await asyncio.sleep(PAUSE_AU_REPOS)


__all__ = ["DECOUPAGE", "LECTURE_IA", "LECTURE_LOCALE", "ajouter", "boucle", "traiter_un"]
