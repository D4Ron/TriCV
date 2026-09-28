from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models import User, UserRole
from app.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if creds is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(creds.credentials, "access")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired") from None
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from None

    user = await db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator role required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def client_ip(request: Request) -> str:
    """L'adresse du visiteur, telle que la voit le proxy de confiance le plus proche.

    X-Forwarded-For se lit **par la droite** : chaque proxy ajoute en fin de
    liste l'adresse qui s'est présentée à lui. La première entrée, elle, vient
    du client et se fabrique à volonté — la prendre, comme autrefois, laissait
    quiconque changer d'adresse à chaque requête et passer sous toutes les
    limites (connexion, formulaire public).
    """
    sauts = settings.trusted_proxy_hops
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and sauts > 0:
        adresses = [a.strip() for a in forwarded.split(",") if a.strip()]
        if adresses:
            return adresses[max(len(adresses) - sauts, 0)]
    return request.client.host if request.client else "unknown"
