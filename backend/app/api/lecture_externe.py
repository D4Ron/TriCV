"""Lire ailleurs : le fichier à traiter, le résultat à verser, le lecteur local.

Le lecteur local ne reçoit jamais de connexion : c'est lui qui appelle. Une
machine du cabinet derrière une box n'a donc rien à ouvrir, et elle n'a accès
qu'à deux adresses, avec une clé qui ne vaut rien d'autre.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.api.postes import get_poste_or_404
from app.deps import AdminUser, CurrentUser, DbSession
from app.models.base import utcnow
from app.models.travail import ATTENTE, EN_COURS, ECHEC, FAIT, LECTURE_IA, Travail
from app.services import audit, lecture_externe, parametres, travaux
from app.services.preselection import charger_candidature

router = APIRouter(tags=["lecture externe"])

# Un dossier lu localement prend moins d'une minute : passé ce délai, le lecteur
# est tombé en route et le dossier retourne dans la file.
DUREE_DE_RESERVATION = timedelta(minutes=10)
FICHIER_MAX_OCTETS = 30 * 1024 * 1024


@router.get("/postes/{poste_id}/lecture-externe")
async def exporter(
    poste_id: str, db: DbSession, user: CurrentUser, tous: bool = Query(default=False)
) -> Response:
    """Le lot à lire ailleurs : texte expurgé, sans nom ni fichier."""
    poste = await get_poste_or_404(db, poste_id)
    lot = await lecture_externe.exporter(db, poste, tous=tous)
    await audit.record(
        db,
        action="poste.lecture_exportee",
        entity_type="poste",
        entity_id=poste.id,
        user_id=user.id,
        details={"dossiers": len(lot["dossiers"])},
    )
    await db.commit()
    return Response(
        json.dumps(lot, ensure_ascii=False, indent=1),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="lecture.json"'},
    )


@router.post("/postes/{poste_id}/lecture-externe")
async def importer(
    poste_id: str, db: DbSession, user: CurrentUser, fichier: UploadFile = File(...)
) -> dict:
    """Verse un `result.json`. Rien de ce qu'un humain a décidé ne bouge."""
    poste = await get_poste_or_404(db, poste_id)
    contenu = await fichier.read(FICHIER_MAX_OCTETS + 1)
    if len(contenu) > FICHIER_MAX_OCTETS:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Fichier trop volumineux.")
    try:
        compte = await lecture_externe.verser_fichier(db, contenu, "fichier importé", poste.id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await audit.record(
        db,
        action="poste.lecture_importee",
        entity_type="poste",
        entity_id=poste.id,
        user_id=user.id,
        details={"lecteur": compte["lecteur"], "comptes": compte["comptes"]},
    )
    await db.commit()
    return compte


# --- la clé du lecteur -------------------------------------------------------


def _empreinte(cle: str) -> str:
    return hashlib.sha256(cle.encode()).hexdigest()


@router.post("/settings/lecteur/cle")
async def creer_cle(db: DbSession, user: AdminUser) -> dict:
    """Crée la clé, et la montre cette seule fois : seule son empreinte est gardée."""
    cle = f"tricv-lecteur-{secrets.token_urlsafe(32)}"
    await parametres.ecrire(db, {parametres.LECTEUR_CLE: _empreinte(cle)})
    await audit.record(
        db, action="parametres.lecteur_cle", entity_type="parametres", entity_id=None,
        user_id=user.id, details={},
    )
    await db.commit()
    return {"cle": cle}


@router.delete("/settings/lecteur/cle", status_code=status.HTTP_204_NO_CONTENT)
async def retirer_cle(db: DbSession, user: AdminUser) -> Response:
    await parametres.effacer(db, [parametres.LECTEUR_CLE])
    travaux.lecteur_oublie()
    await audit.record(
        db, action="parametres.lecteur_cle", entity_type="parametres", entity_id=None,
        user_id=user.id, details={"retire": True},
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/settings/lecteur")
async def etat_du_lecteur(db: DbSession, _: CurrentUser) -> dict:
    existante = await db.get(parametres.Parametre, parametres.LECTEUR_CLE)
    return {
        "configure": existante is not None,
        "actif": travaux.lecteur_actif(),
        "vu_il_y_a": travaux.lecteur_vu_il_y_a(),
        "modele": travaux.lecteur_modele(),
    }


async def lecteur_autorise(
    db: DbSession, x_cle_lecteur: Annotated[str | None, Header()] = None
) -> None:
    existante = await db.get(parametres.Parametre, parametres.LECTEUR_CLE)
    if (
        existante is None
        or not x_cle_lecteur
        or not hmac.compare_digest(existante.valeur, _empreinte(x_cle_lecteur))
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Clé de lecteur refusée.")


Lecteur = Annotated[None, Depends(lecteur_autorise)]


# --- ce que le lecteur appelle -----------------------------------------------


@router.get("/lecteur/travaux")
async def prendre_des_travaux(
    db: DbSession,
    _: Lecteur,
    limite: int = Query(default=1, ge=1, le=5),
    modele: str = Query(default="", max_length=120),
) -> dict:
    """Réserve des dossiers à lire. Appeler ici, c'est aussi dire qu'on est là.

    Un dossier en attente de quota est pris quand même : c'est le jour où le
    lecteur local sert le plus.
    """
    travaux.lecteur_vu(modele)
    maintenant = utcnow()
    # Ce qu'un lecteur tombé en route avait réservé retourne dans la file.
    await db.execute(
        update(Travail)
        .where(
            Travail.etat == EN_COURS,
            Travail.nature == LECTURE_IA,
            Travail.pas_avant.is_not(None),
            Travail.pas_avant < maintenant,
        )
        .values(etat=ATTENTE, pas_avant=None)
    )
    pris = (
        await db.execute(
            select(Travail)
            .where(Travail.etat == ATTENTE, Travail.nature == LECTURE_IA)
            .order_by(Travail.created_at)
            .limit(limite)
        )
    ).scalars().all()

    dossiers = []
    for travail in pris:
        candidature = await charger_candidature(db, travail.candidature_id)
        prepare = await lecture_externe.preparer(db, candidature) if candidature else None
        if prepare is None:
            travail.etat = FAIT
            continue
        travail.etat = EN_COURS
        travail.pas_avant = maintenant + DUREE_DE_RESERVATION
        dossiers.append(
            {
                "travail_id": travail.id,
                "consigne": lecture_externe.consigne(prepare.pop("domaines")),
                **prepare,
            }
        )
    await db.commit()
    return {"format": lecture_externe.FORMAT, "dossiers": dossiers}


class ResultatLecteur(BaseModel):
    travail_id: str = Field(max_length=64)
    lecteur: str = Field(default="lecteur local", max_length=120)
    secondes: float | None = Field(default=None, ge=0)
    jetons: int | None = Field(default=None, ge=0)
    resultat: dict | None = None
    # Sans résultat : le lecteur n'a pas pu, le dossier retourne dans la file.
    erreur: str | None = Field(default=None, max_length=500)


@router.post("/lecteur/resultats")
async def rendre_un_resultat(payload: ResultatLecteur, db: DbSession, _: Lecteur) -> dict:
    travaux.lecteur_vu(payload.lecteur)
    travail = await db.get(Travail, payload.travail_id)
    if travail is None or travail.etat != EN_COURS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ce travail n'est plus réservé.")

    if payload.resultat is None:
        travail.essais += 1
        travail.erreur = (payload.erreur or "lecture impossible")[:500]
        if travail.essais >= travaux.ESSAIS_MAX:
            travail.etat = ECHEC
        else:
            travail.etat = ATTENTE
            travail.pas_avant = None
        await db.commit()
        return {"etat": "rendu"}

    debut = time.monotonic()
    compte = await lecture_externe.verser(db, payload.resultat, payload.lecteur)
    if compte["etat"] == "lu":
        travail.etat = FAIT
        travail.erreur = None
    elif compte["etat"] == "perime":
        # Une pièce est arrivée entre-temps : il faut relire ce qu'elle a changé.
        travail.etat = ATTENTE
    else:
        travail.etat = ECHEC
        travail.erreur = f"Résultat refusé : {compte['etat']}"
    travail.pas_avant = None
    travail.secondes = payload.secondes if payload.secondes is not None else time.monotonic() - debut
    travail.jetons = payload.jetons
    travail.fournisseur = payload.lecteur
    await db.commit()
    return compte
