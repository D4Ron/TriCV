from __future__ import annotations

from statistics import median

from fastapi import APIRouter, Query
from sqlalchemy import desc, select

from app.api.sessions import get_session_or_404
from app.config import settings
from app.deps import AdminUser, CurrentUser, DbSession
from app.models import AuditLog, Candidate
from app.schemas.stats import (
    AuditLogOut,
    ReglagesIn,
    ScoreBucket,
    SessionStats,
    SettingsOut,
)
from app.services import audit, oauth_microsoft, parametres, uploads
from app.services.redaction import loaded_ner_models

router = APIRouter(tags=["stats"])

BUCKETS = ((0, 19), (20, 39), (40, 59), (60, 79), (80, 100))


@router.get("/sessions/{session_id}/stats", response_model=SessionStats)
async def session_stats(session_id: str, db: DbSession, _: CurrentUser) -> SessionStats:
    session = await get_session_or_404(db, session_id)
    candidates = list(
        (await db.execute(select(Candidate).where(Candidate.session_id == session_id))).scalars()
    )

    stats = SessionStats(
        total_candidates=len(candidates), score_threshold=session.score_threshold
    )
    scores: list[float] = []

    for candidate in candidates:
        stats.by_analysis_status[candidate.analysis_status.value] = (
            stats.by_analysis_status.get(candidate.analysis_status.value, 0) + 1
        )
        stats.by_hr_status[candidate.hr_status.value] = (
            stats.by_hr_status.get(candidate.hr_status.value, 0) + 1
        )
        stats.by_source[candidate.source.value] = (
            stats.by_source.get(candidate.source.value, 0) + 1
        )
        if candidate.ai_recommendation is not None:
            key = candidate.ai_recommendation.value
            stats.by_recommendation[key] = stats.by_recommendation.get(key, 0) + 1

        score = candidate.effective_score
        if score is not None:
            scores.append(score)

    if scores:
        stats.average_score = round(sum(scores) / len(scores), 1)
        stats.median_score = round(median(scores), 1)
        stats.above_threshold = sum(1 for s in scores if s >= session.score_threshold)

    stats.distribution = [
        ScoreBucket(
            label=f"{low}-{high}",
            count=sum(1 for s in scores if low <= s <= high),
        )
        for low, high in BUCKETS
    ]
    return stats


@router.get("/sessions/{session_id}/audit", response_model=list[AuditLogOut])
async def session_audit(
    session_id: str,
    db: DbSession,
    _: CurrentUser,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AuditLogOut]:
    """Everything that happened to this session and its candidates.

    Candidate-scoped entries are matched by id, so overrides and full-document
    re-analyses show up here alongside session-level events.
    """
    candidate_ids = list(
        (await db.execute(select(Candidate.id).where(Candidate.session_id == session_id))).scalars()
    )
    entries = list(
        (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.entity_id.in_([session_id, *candidate_ids]))
                .order_by(desc(AuditLog.created_at))
                .limit(limit)
            )
        ).scalars()
    )
    return [
        AuditLogOut(
            id=entry.id,
            action=entry.action,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            user_id=entry.user_id,
            user_name=entry.user.full_name if entry.user else None,
            details=entry.details,
            created_at=entry.created_at,
        )
        for entry in entries
    ]


@router.get("/settings", response_model=SettingsOut)
async def deployment_settings(db: DbSession, _: CurrentUser) -> SettingsOut:
    """L'état du déploiement, réglages modifiables compris.

    L'expurgation des données démographiques y figure explicitement : la
    désactiver doit être une décision visible, pas un réglage oublié.
    """
    reglages = await parametres.lire(db)
    return SettingsOut(
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model or "(défaut du fournisseur)",
        pii_redaction=settings.pii_redaction,
        redact_demographics=reglages.redact_demographics,
        max_upload_mb=uploads.PLAFOND_ABSOLU_MO,
        storage_backend=settings.storage_backend,
        spacy_models_loaded=loaded_ner_models(),
        allow_self_registration=reglages.allow_self_registration,
        candidatures_spontanees=reglages.candidatures_spontanees,
        courriel_actif=reglages.courriel_actif,
        adresse_boite=reglages.adresse_boite,
        dossier_boite=reglages.dossier_boite,
        courriel_utilisable=reglages.courriel_utilisable,
        envoi_actif=reglages.envoi_actif,
        adresse_expediteur=reglages.adresse_expediteur,
        envoi_utilisable=reglages.envoi_utilisable,
        url_publique=reglages.url_publique,
        oauth_tenant=reglages.oauth_tenant,
        oauth_client_id=reglages.oauth_client_id,
        # Les secrets eux-mêmes ne sortent jamais de la machine.
        oauth_client_secret_defini=bool(reglages.oauth_client_secret),
        ia_fournisseur_ecran=reglages.llm_provider,
        ia_modele_ecran=reglages.llm_model,
        ia_adresse_openai=reglages.llm_base_url,
        ia_adresse_ollama=reglages.ollama_base_url,
        ia_cles={
            nom: parametres.source_cle(reglages, cle)
            for nom, cle in parametres.CLE_DU_FOURNISSEUR.items()
        },
        ia_regle_ecran=any(
            getattr(reglages, cle) for cle in parametres.CLES_IA
        ),
        contact_candidats=reglages.contact_candidats,
        contact_effectif=reglages.contact,
    )


@router.patch("/settings", response_model=SettingsOut)
async def modifier_reglages(
    payload: ReglagesIn, db: DbSession, user: AdminUser
) -> SettingsOut:
    """Réservé aux administrateurs : ces réglages valent pour tout le cabinet.

    Le stockage reste hors de portée — il appartient au déploiement, pas à
    l'écran. Le modèle d'IA, lui, se choisit ici, clés comprises : c'est le
    réglage qu'on change le plus souvent, et le seul qui demandait jusqu'ici
    un accès au serveur. Ce qui est réglé ici prime sur le .env.
    """
    changees = await parametres.ecrire(db, payload.model_dump(exclude_unset=True))
    if any(cle.startswith("oauth_") for cle in changees):
        # Un jeton obtenu avec l'ancien secret resterait servi jusqu'à son
        # échéance : le test qui suit un changement d'accès ne prouverait rien.
        oauth_microsoft.oublier_cache()
    if changees:
        await audit.record(
            db,
            action="parametres.update",
            entity_type="parametres",
            entity_id=None,
            user_id=user.id,
            details={"reglages": sorted(changees)},
        )
    await db.commit()
    # Après l'enregistrement, pas avant : une clé mise en service puis
    # perdue par un enregistrement qui échoue servirait sans être réglée.
    if set(changees) & set(parametres.CLES_IA):
        parametres.appliquer_ia(await parametres.lire(db))
    return await deployment_settings(db, user)


@router.delete("/settings/ia", response_model=SettingsOut)
async def revenir_au_serveur(db: DbSession, user: AdminUser) -> SettingsOut:
    """Oublie le modèle réglé à l'écran : le .env reprend la main."""
    retirees = await parametres.effacer(db, parametres.CLES_IA)
    if retirees:
        await audit.record(
            db,
            action="parametres.update",
            entity_type="parametres",
            entity_id=None,
            user_id=user.id,
            details={"reglages": sorted(retirees), "retire": True},
        )
    await db.commit()
    if retirees:
        parametres.appliquer_ia(await parametres.lire(db))
    return await deployment_settings(db, user)
