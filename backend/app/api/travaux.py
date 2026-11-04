"""Lire tous les dossiers d'un poste, sans bloquer l'écran."""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import select

from fastapi import APIRouter, HTTPException, status

from app.api.postes import get_poste_or_404
from app.deps import CurrentUser, DbSession
from app.llm.base import LLMError
from app.llm.factory import get_provider
from app.models.recrutement import Candidat, Candidature
from app.models.travail import LECTURE_IA, LECTURE_LOCALE
from app.services import audit, travaux

router = APIRouter(tags=["travaux"])

CONSIGNE_LEXIQUE = (
    "Pour un poste de recrutement au Togo, proposez pour chaque domaine donné les mots qu'un CV "
    "emploie pour désigner ce domaine sans le nommer : synonymes, métiers, activités, et "
    "employeurs connus du secteur en Afrique de l'Ouest. Quelques mots chacun, rien de vague. "
    'Répondez uniquement en JSON : {"lexique": {"domaine": ["mot", "mot"]}}, avec au plus '
    "huit entrées par domaine."
)


class LectureIn(BaseModel):
    ia: bool = False


@router.post("/postes/{poste_id}/lectures")
async def lancer_la_lecture(
    poste_id: str, payload: LectureIn, db: DbSession, user: CurrentUser
) -> dict:
    """Met en file les dossiers du poste que personne n'a encore confirmés.

    Un dossier confirmé a été relu : il ne se relit pas tout seul.
    """
    poste = await get_poste_or_404(db, poste_id)
    resultat = await db.execute(
        select(Candidature.id)
        .join(Candidat, Candidat.id == Candidature.candidat_id)
        .where(Candidature.poste_id == poste.id, Candidat.verifie_le.is_(None))
    )
    identifiants = [(c, poste.id) for c in resultat.scalars()]
    await travaux.oublier_le_termine(db, poste.id)
    nature = LECTURE_IA if payload.ia else LECTURE_LOCALE
    ajoutes = await travaux.ajouter(db, identifiants, nature)
    await audit.record(
        db,
        action="poste.lecture_lancee",
        entity_type="poste",
        entity_id=poste.id,
        user_id=user.id,
        details={"dossiers": ajoutes, "ia": payload.ia},
    )
    await db.commit()
    return {"ajoutes": ajoutes, **await travaux.etat_du_poste(db, poste.id)}


@router.get("/postes/{poste_id}/lectures")
async def suivre_la_lecture(poste_id: str, db: DbSession, _: CurrentUser) -> dict:
    await get_poste_or_404(db, poste_id)
    return await travaux.etat_du_poste(db, poste_id)


@router.delete("/postes/{poste_id}/lectures")
async def annuler_la_lecture(poste_id: str, db: DbSession, _: CurrentUser) -> dict:
    await get_poste_or_404(db, poste_id)
    retires = await travaux.annuler(db, poste_id)
    await db.commit()
    return {"retires": retires, **await travaux.etat_du_poste(db, poste_id)}


@router.post("/postes/{poste_id}/lexique/proposer")
async def proposer_un_lexique(poste_id: str, db: DbSession, _: CurrentUser) -> dict:
    """Une proposition à relire, faite une fois pour le poste.

    Seuls l'intitulé et les domaines du poste partent au modèle : aucune donnée
    de candidat. Rien n'est enregistré : les RH gardent ce qu'ils veulent.
    """
    poste = await get_poste_or_404(db, poste_id)
    domaines = [
        *(poste.domaines_acceptes or ()),
        *(poste.domaines_experience or ()),
        *(d for e in poste.experiences_specifiques or () for d in e.get("domaines") or ()),
    ]
    domaines = list(dict.fromkeys(domaines))
    if not domaines:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Ce poste ne déclare encore aucun domaine."
        )
    contexte = f"Poste : {poste.intitule}\nDomaines : {', '.join(domaines)}"
    try:
        reponse = await get_provider().repondre_json(CONSIGNE_LEXIQUE, contexte)
    except LLMError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"IA indisponible : {exc}") from exc
    proposes = reponse.get("lexique") if isinstance(reponse, dict) else None
    lexique: dict[str, list[str]] = {}
    for domaine in domaines:
        mots = (proposes or {}).get(domaine) or []
        lexique[domaine] = [str(m).strip() for m in mots if str(m).strip()][:8]
    return {"lexique": lexique}
