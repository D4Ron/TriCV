"""L'état de l'application, et ce que le navigateur des visiteurs signale.

Trois routes pour l'administrateur — l'état, un essai réel du modèle, une
sonde de taille de dépôt — et une route publique, qui ne fait qu'incrémenter
un compteur.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.deps import AdminUser, DbSession, client_ip
from app.models import EVENEMENTS
from app.services import sante
from app.services.ratelimit import SlidingWindowLimiter

router = APIRouter(tags=["état de l'application"])

# Un budget à part : les signaux de fréquentation ne doivent ni consommer celui
# des dépôts, ni pouvoir gonfler les compteurs sans fin depuis une seule adresse.
_signaux = SlidingWindowLimiter(300)

# La sonde lit ce qu'elle reçoit et le jette ; au-delà, elle n'apprend rien de
# plus et occuperait la mémoire pour rien.
_SONDE_MAX_OCTETS = 25 * 1024 * 1024


class VerificationOut(BaseModel):
    code: str
    libelle: str
    etat: str
    detail: str
    ou: str = ""


class EtatOut(BaseModel):
    verifications: list[VerificationOut]
    frequentation: dict


@router.get("/sante", response_model=EtatOut)
async def etat_application(db: DbSession, _: AdminUser) -> EtatOut:
    verifications = await sante.verifications(db)
    return EtatOut(
        verifications=[VerificationOut(**sante.en_dict(v)) for v in verifications],
        frequentation=await sante.frequentation(db),
    )


@router.post("/sante/ia/tester")
async def tester_ia(_: AdminUser) -> dict:
    """Un appel réel au modèle, pour savoir si la clé est acceptée.

    Que le fournisseur se construise ne prouve rien : une clé mal recopiée ou
    révoquée passe la configuration et échoue au premier appel. Seul un essai
    le dit. Il coûte un appel, d'où le bouton plutôt qu'un essai à chaque
    affichage.
    """
    from app.llm.factory import get_provider

    debut = time.monotonic()
    try:
        fournisseur = get_provider()
        reponse = await asyncio.wait_for(
            fournisseur.rediger(
                "Répondez par le seul mot : OK.", "Essai de connexion.", titre="essai"
            ),
            timeout=45,
        )
    except asyncio.TimeoutError:
        return {"ok": False, "detail": "Pas de réponse en 45 secondes.", "secondes": 45}
    except Exception as exc:
        return {
            "ok": False,
            "detail": sante._masquer(f"{type(exc).__name__} : {exc}"),
            "secondes": round(time.monotonic() - debut, 1),
        }
    ok = bool((reponse or "").strip())
    return {
        "ok": ok,
        "detail": "Le modèle a répondu." if ok else "Le modèle a répondu vide.",
        "secondes": round(time.monotonic() - debut, 1),
    }


@router.post("/sante/sonde-depot")
async def sonde_depot(request: Request, _: AdminUser) -> dict:
    """Reçoit un envoi de test et le jette, sans rien enregistrer.

    L'écran y envoie quelques mégaoctets : si la réponse arrive, le serveur
    frontal les a laissés passer ; s'il répond 413, c'est lui qui bloque les
    candidats. La sonde ne touche pas au formulaire de candidature, et ne crée
    donc aucun dossier.
    """
    recus = 0
    async for morceau in request.stream():
        recus += len(morceau)
        if recus > _SONDE_MAX_OCTETS:
            break
    return {"octets_recus": recus}


class SignalIn(BaseModel):
    evenement: str = Field(max_length=40)
    # La clé publique ou le code court de l'avis, quand l'événement en concerne un.
    cle: str = Field(default="", max_length=64)


@router.post("/public/evenement", status_code=status.HTTP_204_NO_CONTENT)
async def signaler(signal: SignalIn, request: Request, db: DbSession) -> Response:
    """Ce que le navigateur d'un visiteur signale, et que le serveur ne voit pas.

    Une visite de page ; un dépôt refusé par le serveur frontal. Rien n'est
    conservé d'autre que le compteur du jour : ni l'adresse, ni le navigateur.
    """
    if signal.evenement not in EVENEMENTS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Événement inconnu.")
    _signaux.check(client_ip(request))
    poste_id = await sante.poste_de_la_cle(db, signal.cle) if signal.cle else ""
    await sante.compter(signal.evenement, poste_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
