from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import User, UserRole

pytestmark = pytest.mark.anyio

SIGNUP = "/api/v1/auth/signup"


@pytest.fixture
def open_signup(monkeypatch):
    """Registration open, no code required."""
    monkeypatch.setattr(settings, "allow_self_registration", True)
    monkeypatch.setattr(settings, "signup_code", "")


@pytest.fixture
def coded_signup(monkeypatch):
    monkeypatch.setattr(settings, "allow_self_registration", True)
    monkeypatch.setattr(settings, "signup_code", "LET-ME-IN")


def payload(**overrides) -> dict:
    return {
        "email": "hr@example.com",
        "password": "a-good-password",
        "full_name": "Amina Kodjo",
        **overrides,
    }


async def test_signup_config_reports_state(client, coded_signup):
    body = (await client.get("/api/v1/auth/signup-config")).json()
    assert body == {"enabled": True, "requires_code": True}


async def test_signup_is_refused_when_disabled(client, monkeypatch):
    """The shipped default: a public URL must not hand out HR accounts."""
    monkeypatch.setattr(settings, "allow_self_registration", False)

    assert (await client.get("/api/v1/auth/signup-config")).json()["enabled"] is False

    response = await client.post(SIGNUP, json=payload())
    assert response.status_code == 403

    async with SessionLocal() as db:
        assert (await db.execute(select(User))).scalars().all() == []


async def test_signup_creates_a_recruiter_and_signs_in(client, open_signup):
    response = await client.post(SIGNUP, json=payload())
    assert response.status_code == 201, response.text

    token = response.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "hr@example.com"
    assert me.json()["role"] == UserRole.RECRUITER.value


async def test_signup_cannot_grant_itself_admin(client, open_signup):
    """A caller who asks for ADMIN still gets RECRUITER, and stays locked out
    of the admin-only user endpoints."""
    response = await client.post(SIGNUP, json=payload(role="ADMIN"))
    assert response.status_code == 201

    async with SessionLocal() as db:
        user = (await db.execute(select(User))).scalar_one()
        assert user.role is UserRole.RECRUITER

    token = response.json()["access_token"]
    listed = await client.get("/api/v1/auth/users", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 403


async def test_signup_requires_the_code_when_one_is_set(client, coded_signup):
    wrong = await client.post(SIGNUP, json=payload(signup_code="nope"))
    assert wrong.status_code == 403

    missing = await client.post(SIGNUP, json=payload())
    assert missing.status_code == 403

    async with SessionLocal() as db:
        assert (await db.execute(select(User))).scalars().all() == []

    ok = await client.post(SIGNUP, json=payload(signup_code="LET-ME-IN"))
    assert ok.status_code == 201, ok.text


async def test_signup_rejects_a_duplicate_email(client, open_signup):
    assert (await client.post(SIGNUP, json=payload())).status_code == 201
    second = await client.post(SIGNUP, json=payload(full_name="Someone Else"))
    assert second.status_code == 409


async def test_signup_rejects_a_short_password(client, open_signup):
    response = await client.post(SIGNUP, json=payload(password="short"))
    assert response.status_code == 422


async def test_signup_is_rate_limited(client, open_signup, monkeypatch):
    from collections import defaultdict, deque

    from app.services import ratelimit

    monkeypatch.setattr(ratelimit.signup_limiter, "limit", 3)
    # Fresh window: the limiter is a module-level singleton shared by tests.
    monkeypatch.setattr(ratelimit.signup_limiter, "_hits", defaultdict(deque))

    codes = [
        (await client.post(SIGNUP, json=payload(email=f"hr{i}@example.com"))).status_code
        for i in range(5)
    ]
    assert codes[:3] == [201, 201, 201]
    assert codes[3:] == [429, 429]
