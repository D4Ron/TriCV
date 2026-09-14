from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# « client » désigne le jeton d'un promoteur sur son espace de suivi. Le type
# est vérifié au décodage, donc un jeton client ne peut pas ouvrir une route
# interne même si la signature est la bonne : c'est la séparation des deux
# portes, exprimée là où elle se vérifie.
TokenType = Literal["access", "refresh", "client"]


def hash_password(password: str) -> str:
    # bcrypt silently truncates past 72 bytes; refuse rather than accept a
    # password whose tail is ignored.
    if len(password.encode()) > 72:
        raise ValueError("password must be at most 72 bytes")
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        return False


def _create_token(subject: str, token_type: TokenType, expires: timedelta, **claims: Any) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires,
        **claims,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str, role: str) -> str:
    return _create_token(
        user_id, "access", timedelta(minutes=settings.access_token_minutes), role=role
    )


def create_client_token(acces_id: str, mandat_id: str) -> str:
    """Le jeton d'un promoteur, portant le mandat auquel il donne accès.

    Le mandat figure dans le jeton pour que le périmètre soit lisible dès le
    décodage ; il est malgré tout revérifié en base à chaque requête, un accès
    pouvant être révoqué au milieu d'une session.
    """
    return _create_token(
        acces_id,
        "client",
        timedelta(minutes=max(settings.access_token_minutes, 120)),
        mandat=mandat_id,
    )


def create_refresh_token(user_id: str) -> str:
    return _create_token(user_id, "refresh", timedelta(days=settings.refresh_token_days))


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """Raises jwt.PyJWTError on anything wrong — expiry, signature, or type."""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected a {expected_type} token")
    return payload
