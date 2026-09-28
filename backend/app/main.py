from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse

from app.api import (
    auth,
    candidates,
    candidatures,
    collaboration,
    exports,
    fiches,
    mandats,
    portail_client,
    postes,
    public,
    public_avis,
    rapports,
    sessions,
    stats,
    vivier,
)
from app.config import settings
from app.logging_config import configure_logging
from app.services.retention import run_retention_sweep

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"

# Les clés de signature livrées avec le dépôt. Elles sont publiques : quiconque
# les connaît fabrique un jeton d'administrateur valide, sans mot de passe.
_SECRETS_PUBLICS = {"dev-only-insecure-secret-change-me", "dev-only-secret", "change-me", "secret"}


def _refuser_secret_public() -> None:
    """Remplace une clé de signature connue de tous par une clé aléatoire.

    Plutôt que de refuser de démarrer — ce qui couperait le service à la
    mise à jour —, l'application signe avec une clé tirée au démarrage. Le
    prix : les sessions ne survivent pas à un redémarrage, et chacun se
    reconnecte. Le journal le dit en toutes lettres, pour que JWT_SECRET soit
    enfin réglé.
    """
    if settings.jwt_secret.strip() in _SECRETS_PUBLICS or len(settings.jwt_secret.strip()) < 16:
        settings.jwt_secret = secrets.token_urlsafe(48)
        logger.critical(
            "JWT_SECRET est absent ou vaut une valeur publique : une clé aléatoire "
            "est utilisée à sa place, et les sessions ne survivront pas au prochain "
            "redémarrage. Réglez JWT_SECRET dans .env (python -c \"import secrets; "
            "print(secrets.token_urlsafe(48))\")."
        )


_refuser_secret_public()


def _log_privacy_posture() -> None:
    """The deployment's privacy settings are stated at startup, not buried in env."""
    logger.info("LLM provider: %s (model=%s)", settings.llm_provider, settings.llm_model or "default")
    if settings.pii_redaction:
        logger.info("PII_REDACTION=true — CVs are redacted locally; only text leaves the system.")
    else:
        logger.warning(
            "PII_REDACTION=false — ORIGINAL CV FILES ARE SENT TO %s, including candidate "
            "names, emails and phone numbers.",
            settings.llm_provider.upper(),
        )
    if settings.redact_demographics:
        logger.info(
            "REDACT_DEMOGRAPHICS=true — gender, age, date of birth, marital status and "
            "nationality are stored and shown to HR but excluded from the scoring payload."
        )
    else:
        logger.warning(
            "REDACT_DEMOGRAPHICS=false — demographic attributes are included in the payload "
            "sent for scoring. This is a knowing choice by this deployment; scoring on these "
            "attributes is discriminatory in most jurisdictions."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging("DEBUG" if settings.debug else "INFO")
    _log_privacy_posture()
    try:
        deleted = await run_retention_sweep()
        if deleted:
            logger.info("retention sweep removed %d expired candidate record(s)", deleted)
    except Exception:
        logger.exception("retention sweep failed at startup")
    yield


app = FastAPI(
    title="TriCV — Kapi Consult",
    version="1.0.0",
    summary="AI-assisted CV screening. The tool ranks and recommends; HR decides.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Un navigateur ne laisse lire, sur une réponse d'une autre origine, que six
    # en-têtes standard — et `Content-Disposition` n'en fait pas partie. Sans
    # cette liste, l'interface ne voyait pas le nom du fichier renvoyé par les
    # exports et retombait sur un nom générique, ni le compte rendu que porte
    # l'export des CV.
    expose_headers=[
        "Content-Disposition",
        "X-TriCV-Inclus",
        "X-TriCV-Ecartes",
    ],
)


# En-têtes de sécurité sur toutes les réponses de l'API, et plafond des
# requêtes publiques vérifié avant lecture du corps : le formulaire de
# candidature lisait tout le fichier en mémoire avant d'en contrôler la taille.
_ENTETES_SECURITE = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cross-Origin-Resource-Policy": "cross-origin",
}


@app.middleware("http")
async def _garde_fous(request, call_next):
    if request.url.path.startswith(f"{API_PREFIX}/public"):
        taille = request.headers.get("content-length")
        plafond = settings.public_max_request_mb * 1024 * 1024
        if taille and taille.isdigit() and int(taille) > plafond:
            return PlainTextResponse(
                f"Envoi trop volumineux (plus de {settings.public_max_request_mb} Mo).",
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
    reponse = await call_next(request)
    for nom, valeur in _ENTETES_SECURITE.items():
        reponse.headers.setdefault(nom, valeur)
    return reponse


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok", "service": "tricv"}


# The embeddable widget is served from the API host, so the snippet a customer
# pastes into their site is a single <script src> against the same origin it
# will call. Built by the widget/ package; the Docker image bakes it in.
WIDGET_PATH = Path(__file__).resolve().parent.parent / "static" / "widget.js"


@app.get("/widget.js", include_in_schema=False)
async def widget() -> Response:
    if not WIDGET_PATH.exists():
        return PlainTextResponse(
            "// TriCV widget not built. Run `npm run build` in widget/.",
            status_code=status.HTTP_404_NOT_FOUND,
            media_type="application/javascript",
        )
    return FileResponse(
        WIDGET_PATH,
        media_type="application/javascript",
        headers={
            # Any site may embed it; it contains no secrets.
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=300",
        },
    )


@app.get("/", tags=["meta"])
async def root() -> dict:
    return {
        "service": "TriCV",
        "cabinet": "Kapi Consult",
        "docs": "/docs",
        "api": API_PREFIX,
        "note": "TriCV classe et recommande. Les RH de Kapi Consult décident.",
    }


for router in (
    auth.router,
    # Chaîne de recrutement : Client -> Mandat -> Poste -> Avis -> Candidature.
    mandats.router,
    postes.router,
    fiches.router,
    candidatures.router,
    collaboration.router,
    rapports.router,
    public_avis.router,
    # L'espace du promoteur : porte separee, jeton de type distinct.
    portail_client.router,
    vivier.router,
    # Ancien modèle (session/candidat), encore servi à l'interface le temps de
    # la bascule.
    sessions.router,
    candidates.router,
    exports.router,
    stats.router,
    public.router,
):
    app.include_router(router, prefix=API_PREFIX)
