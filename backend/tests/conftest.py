from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Configure the environment before anything imports app.config.
#
# TRICV_IGNORE_ENV_FILE tells app.config not to read the repository's .env at
# all. Without it the suite inherits whatever the developer happens to have
# configured — a real mailbox, self-registration left open — and the result
# stops meaning anything. Everything the tests depend on is pinned here.
_TMP = Path(tempfile.mkdtemp(prefix="tricv-tests-"))
os.environ.update(
    TRICV_IGNORE_ENV_FILE="1",
    DATABASE_URL=f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}",
    JWT_SECRET="test-secret",
    STORAGE_BACKEND="local",
    STORAGE_PATH=str(_TMP / "cv"),
    LLM_PROVIDER="gemini",
    GEMINI_API_KEY="test-key",
    PII_REDACTION="true",
    REDACT_DEMOGRAPHICS="true",
    CORS_ORIGINS="http://localhost:5173",
    LLM_LOG_PAYLOAD="false",
    PUBLIC_RATE_LIMIT_PER_HOUR="1000",
    SIGNUP_RATE_LIMIT_PER_HOUR="1000",
    # Fermé par défaut : plusieurs tests vérifient qu'on l'ouvre explicitement.
    ALLOW_SELF_REGISTRATION="false",
    SIGNUP_CODE="",
    # Aucune boîte : un test ne doit jamais ouvrir de connexion IMAP réelle.
    IMAP_HOST="",
    IMAP_USER="",
    IMAP_PASSWORD="",
)

import httpx  # noqa: E402
from httpx import ASGITransport  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.llm import factory  # noqa: E402
from app.llm.base import AnalysisResult, CriterionDraft, CvPayload, FichePayload, LLMProvider  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User, UserRole  # noqa: E402
from app.security import hash_password  # noqa: E402


class StubProvider(LLMProvider):
    """Scores every criterion deterministically — no network, no key.

    `sent_payloads` is what the acceptance check inspects to prove that no
    candidate name, email, phone or address reaches a provider.
    """

    name = "stub"

    def __init__(self) -> None:
        self.sent_payloads: list[CvPayload] = []
        self.score_for = lambda criterion: 75.0

    async def analyze_cv(self, cv: CvPayload, fiche: FichePayload) -> AnalysisResult:
        self.sent_payloads.append(cv)
        return AnalysisResult.model_validate({
            "candidate": {
                "full_name": "Should Be Ignored",
                "email": "leak@example.com",
                "phone": "+22890000000",
                "years_experience": 6,
                "education_level": "Master en Informatique",
                "skills": ["Python", "FastAPI", "PostgreSQL"],
            },
            "criterion_scores": [
                {
                    "criterion_id": c.id,
                    "score": self.score_for(c),
                    "justification": f"Evidence found for {c.name}.",
                }
                for c in fiche.criteria
            ],
            "summary": "A solid backend profile.",
            "strengths": ["Production FastAPI experience"],
            "gaps": ["No Kubernetes experience mentioned"],
        })

    async def structure_fiche(self, raw_text: str, language: str = "fr") -> list[CriterionDraft]:
        return [
            CriterionDraft(name="Expérience Python", description="3+ ans", weight=9, is_must_have=True),
            CriterionDraft(name="PostgreSQL", description="Schémas et requêtes", weight=7),
        ]


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
async def database():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)


@pytest.fixture
def stub_provider(monkeypatch) -> StubProvider:
    provider = StubProvider()
    monkeypatch.setattr(factory, "get_provider", lambda: provider)
    monkeypatch.setattr("app.services.analysis.get_provider", lambda: provider)
    return provider


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
async def admin_token(client) -> str:
    from app.db import SessionLocal

    async with SessionLocal() as db:
        db.add(
            User(
                email="admin@tricv.example",
                password_hash=hash_password("password123"),
                full_name="Test Admin",
                role=UserRole.ADMIN,
            )
        )
        await db.commit()

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@tricv.example", "password": "password123"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
def auth(admin_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}
