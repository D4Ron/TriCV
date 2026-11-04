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
import time
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.domain.referentiel import PieceDossier
from app.llm import quotas
from app.llm.base import LLMError, LLMIndisponible
from app.llm.factory import get_provider
from app.models.base import utcnow
from app.models.recrutement import Candidat, Candidature, Mandat, PieceCandidature, Poste
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
from app.services import classement_ia, decoupage, depouillement, extraction, parametres, storage
from app.services.preselection import charger_candidature

logger = logging.getLogger(__name__)

# Le temps de repos d'un fournisseur épuisé dans la chaîne : repasser plus tôt
# ne servirait à rien.
ATTENTE_DE_QUOTA = timedelta(minutes=15)
# Quatre heures de quota épuisé : ce n'est plus une limite passagère.
ESSAIS_MAX = 16
# Entre deux appels au modèle. Les offres gratuites comptent à la seconde.
PAUSE_ENTRE_APPELS = 3
# À augmenter quand une version lit mieux les dossiers : au démarrage suivant,
# ils sont tous relus, une fois. Pas à chaque mise à jour : une correction
# d'écran ne vaut pas de dépenser le quota sur tout le vivier.
VERSION_DE_LECTURE = 1

# Tant que rien n'a été mesuré, de quoi donner un ordre de grandeur.
SECONDES_PAR_DEFAUT = {LECTURE_IA: 15.0, LECTURE_LOCALE: 2.0, DECOUPAGE: 8.0}
JETONS_PAR_DEFAUT = 6000
MESURES_RETENUES = 20
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


async def ia_disponible(db: AsyncSession) -> bool:
    """La lecture automatique est-elle voulue, et possible ?"""
    return (await parametres.lire(db)).lecture_ia_auto and bool(_fournisseurs())


async def apres_arrivee(db: AsyncSession, candidature_id: str, poste_id: str | None) -> None:
    """Une pièce vient d'arriver : la lecture par l'IA suit, en file.

    Ne fait jamais échouer ce qui l'appelle : le dossier est acquis.
    """
    try:
        if await ia_disponible(db):
            await ajouter(db, [(candidature_id, poste_id)], LECTURE_IA)
    except Exception:  # noqa: BLE001
        logger.exception("file : lecture de %s non programmée", candidature_id)


async def relancer_apres_mise_a_jour() -> int:
    """Une version qui lit mieux relit tout, une fois. Rend le nombre de dossiers.

    Les mandats archivés restent tels quels. Sans IA, seuls les dossiers non
    confirmés sont relus : une lecture locale n'a rien à proposer aux autres.
    Le travail humain ne risque rien : voir `propositions`.
    """
    async with SessionLocal() as db:
        version = await db.get(parametres.Parametre, parametres.VERSION_LECTURE)
        if version is not None and version.valeur == str(VERSION_DE_LECTURE):
            return 0
        ia = await ia_disponible(db)
        requete = (
            select(Candidature.id, Candidature.poste_id)
            .join(Candidat, Candidat.id == Candidature.candidat_id)
            .join(Poste, Poste.id == Candidature.poste_id)
            .join(Mandat, Mandat.id == Poste.mandat_id)
            .where(Mandat.archive_le.is_(None))
        )
        if not ia:
            requete = requete.where(Candidat.verifie_le.is_(None))
        dossiers = [(r[0], r[1]) for r in (await db.execute(requete)).all()]
        ajoutes = await ajouter(db, dossiers, LECTURE_IA if ia else LECTURE_LOCALE)
        await parametres.ecrire(db, {parametres.VERSION_LECTURE: str(VERSION_DE_LECTURE)})
        await db.commit()
    if ajoutes:
        logger.info("file : %d dossier(s) à relire après la mise à jour", ajoutes)
    return ajoutes


async def _mesures(db: AsyncSession, nature: str) -> tuple[float, int, int]:
    """Durée et jetons moyens des dernières lectures, et sur combien de lectures."""
    lignes = (
        await db.execute(
            select(Travail.secondes, Travail.jetons)
            .where(Travail.nature == nature, Travail.etat == FAIT, Travail.secondes.is_not(None))
            .order_by(Travail.created_at.desc())
            .limit(MESURES_RETENUES)
        )
    ).all()
    if not lignes:
        return SECONDES_PAR_DEFAUT[nature], JETONS_PAR_DEFAUT, 0
    jetons = [l.jetons for l in lignes if l.jetons]
    return (
        sum(l.secondes for l in lignes) / len(lignes),
        round(sum(jetons) / len(jetons)) if jetons else JETONS_PAR_DEFAUT,
        len(lignes),
    )


def _fournisseurs() -> list:
    """Les fournisseurs de la chaîne, dans l'ordre. Vide si aucun n'est utilisable."""
    try:
        fournisseur = get_provider()
    except LLMError:
        return []
    return list(getattr(fournisseur, "fournisseurs", [fournisseur]))


# Gemini n'annonce rien dans ses réponses, et ses limites varient par projet. Ce
# sont les ordres de grandeur de Google pour l'offre gratuite (novembre 2026) :
# 10 requêtes/minute et 250/jour en Flash, 15 et 1 000 en Flash-Lite. Le repli
# passe de l'un à l'autre : c'est le plus bas qui sert à prévoir.
GEMINI_INDICATIF = {"par_minute": 10, "par_jour": 250}


def _libelle(nom: str) -> str:
    if nom == "openai":
        adresse = settings.llm_base_url.lower()
        return next(
            (m.capitalize() for m in ("mistral", "groq", "cerebras", "openrouter") if m in adresse),
            "Compatible OpenAI",
        )
    return {"gemini": "Gemini", "groq": "Groq", "anthropic": "Anthropic", "ollama": "Ollama"}.get(nom, nom)


async def _etat_des_fournisseurs(db: AsyncSession) -> list[dict]:
    debut_du_jour = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    du_jour = (
        await db.execute(
            select(
                Travail.fournisseur, func.count(Travail.id), func.coalesce(func.sum(Travail.jetons), 0)
            )
            .where(Travail.fournisseur.is_not(None), Travail.created_at >= debut_du_jour)
            .group_by(Travail.fournisseur)
        )
    ).all()
    consommes = {nom: (appels, jetons) for nom, appels, jetons in du_jour}

    chaine = None
    try:
        chaine = get_provider()
    except LLMError:
        pass
    repos = getattr(chaine, "_au_repos", {})
    maintenant = time.monotonic()

    rendu = []
    for fournisseur in _fournisseurs():
        releve = quotas.releve(fournisseur.name)
        appels, jetons = consommes.get(fournisseur.name, (0, 0))
        attente = max(repos.get(fournisseur.name, 0.0) - maintenant, 0.0)
        rendu.append(
            {
                "nom": _libelle(fournisseur.name),
                "disponible": attente == 0,
                "repos_secondes": round(attente),
                # Faux tant qu'aucun appel n'a été fait : on ne sait pas encore.
                "quota_lu": releve is not None and releve.appels > 0,
                "requetes_limite": releve.requetes_limite if releve else None,
                "requetes_restantes": releve.requetes_restantes if releve else None,
                "periode_requetes": releve.periode_requetes if releve else None,
                "jetons_limite": releve.jetons_limite if releve else None,
                "jetons_restants": releve.jetons_restants if releve else None,
                "periode_jetons": releve.periode_jetons if releve else None,
                "lectures_du_jour": appels,
                "jetons_du_jour": int(jetons),
                "indicatif": GEMINI_INDICATIF if fournisseur.name == "gemini" else None,
            }
        )
    return rendu


def _rythme_ia(secondes: float, jetons: int, fournisseurs: list[dict]) -> tuple[float, str]:
    """L'écart entre deux lectures, et ce qui le fixe."""
    rythme, cause = secondes + PAUSE_ENTRE_APPELS, "lecture"
    actif = next((f for f in fournisseurs if f["disponible"]), None)
    if actif is None:
        return rythme, cause
    if actif.get("indicatif"):
        minimum = 60 / actif["indicatif"]["par_minute"]
        if minimum > rythme:
            rythme, cause = minimum, "quota"
    if actif["requetes_limite"] and actif["periode_requetes"] == "minute":
        minimum = 60 / actif["requetes_limite"]
        if minimum > rythme:
            rythme, cause = minimum, "quota"
    if actif["jetons_limite"] and actif["periode_jetons"] == "minute":
        minimum = jetons * 60 / actif["jetons_limite"]
        if minimum > rythme:
            rythme, cause = minimum, "quota"
    return rythme, cause


async def etat_du_poste(db: AsyncSession, poste_id: str) -> dict:
    lignes = (
        await db.execute(
            select(Travail.nature, Travail.etat, Travail.pas_avant, Travail.erreur).where(
                Travail.poste_id == poste_id, Travail.clos.is_(False)
            )
        )
    ).all()
    compte = Counter(l.etat for l in lignes)
    maintenant = utcnow()
    reprises = [l.pas_avant for l in lignes if l.etat == ATTENTE and l.pas_avant and l.pas_avant > maintenant]
    echecs = [l.erreur for l in lignes if l.etat == ECHEC and l.erreur]
    a_faire = Counter(l.nature for l in lignes if l.etat in (ATTENTE, EN_COURS))

    secondes_ia, jetons_ia, mesures = await _mesures(db, LECTURE_IA)
    fournisseurs = await _etat_des_fournisseurs(db)
    rythme, cause = _rythme_ia(secondes_ia, jetons_ia, fournisseurs)
    restant = a_faire[LECTURE_IA] * rythme
    for nature in (LECTURE_LOCALE, DECOUPAGE):
        restant += a_faire[nature] * (await _mesures(db, nature))[0]
    attente_quota = 0
    if reprises:
        attente_quota = round((min(reprises) - maintenant).total_seconds())
        restant += attente_quota
        cause = "attente"

    total = len(lignes)
    termines = compte[FAIT] + compte[ECHEC]
    a_lire = (
        await db.execute(
            select(func.count(Candidature.id))
            .join(Candidat, Candidat.id == Candidature.candidat_id)
            .where(Candidature.poste_id == poste_id, Candidat.verifie_le.is_(None))
        )
    ).scalar_one()
    return {
        "en_attente": compte[ATTENTE],
        "en_cours": compte[EN_COURS],
        "faits": compte[FAIT],
        "echecs": compte[ECHEC],
        # Vide tant que rien n'attend le retour d'un quota.
        "reprise_le": min(reprises).isoformat() if reprises else None,
        "derniere_erreur": echecs[-1] if echecs else None,
        "total": total,
        "pourcentage": round(termines * 100 / total) if total else 0,
        "secondes_restantes": round(restant),
        # Ce qui fixe le temps restant : « lecture », « quota » ou « attente ».
        "cause": cause,
        # 0 : aucune lecture mesurée encore, le temps n'est qu'un ordre de grandeur.
        "mesures": mesures,
        "fournisseurs": fournisseurs,
        # Pour annoncer la durée avant de lancer.
        "dossiers_a_lire": a_lire,
        "secondes_par_dossier_ia": round(rythme, 1),
    }


async def annuler(db: AsyncSession, poste_id: str) -> int:
    """Retire ce qui n'a pas commencé. Rien de ce qui est fait n'est défait."""
    resultat = await db.execute(
        delete(Travail).where(Travail.poste_id == poste_id, Travail.etat == ATTENTE)
    )
    return resultat.rowcount or 0


async def oublier_le_termine(db: AsyncSession, poste_id: str) -> None:
    """Un nouveau lot repart de zéro : le suivi ne compte pas l'ancien.

    Les lignes restent : elles mesurent les lectures et comptent la journée.
    """
    await db.execute(
        update(Travail)
        .where(Travail.poste_id == poste_id, Travail.etat.in_((FAIT, ECHEC)))
        .values(clos=True)
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
        # Un fichier manquant ne doit pas priver le dossier du reste de sa lecture.
        if not await depot.exists(piece.chemin_stockage):
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
        await apres_arrivee(db, travail.candidature_id, travail.poste_id)
    elif travail.nature == LECTURE_LOCALE:
        await depouillement.depouiller(db, candidature, ia=False)
    elif travail.nature == LECTURE_IA:
        # Un dossier confirmé a été relu pièce par pièce : on n'y range plus rien.
        if candidature.candidat.verifie_le is None:
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

    debut = time.monotonic()
    avant = quotas.consommation()
    async with SessionLocal() as db:
        travail = await db.get(Travail, travail_id)
        try:
            await _executer(db, travail)
            travail.etat = FAIT
            travail.erreur = None
            travail.secondes = round(time.monotonic() - debut, 1)
            # Celui dont le compteur a bougé : c'est lui qui a répondu.
            ecarts = {
                nom: jetons - avant.get(nom, 0)
                for nom, jetons in quotas.consommation().items()
                if jetons > avant.get(nom, 0)
            }
            if ecarts:
                travail.fournisseur = max(ecarts, key=ecarts.get)
                travail.jetons = sum(ecarts.values())
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
    try:
        await relancer_apres_mise_a_jour()
    except Exception:  # noqa: BLE001 - la file doit tourner quand même
        logger.exception("file : relecture après mise à jour non programmée")
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
