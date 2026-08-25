from __future__ import annotations

import secrets

import jwt
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.config import settings
from app.deps import AdminUser, CurrentUser, DbSession, client_ip
from app.models import User, UserRole
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    SignupConfig,
    SignupRequest,
    TokenPair,
    UserCreate,
    UserOut,
)
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.services import audit, parametres
from app.services.ratelimit import signup_limiter

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_pair(user: User) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user.id, user.role.value),
        refresh_token=create_refresh_token(user.id),
        expires_in=settings.access_token_minutes * 60,
    )


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, db: DbSession) -> TokenPair:
    result = await db.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()
    # Same response whether the address is unknown or the password is wrong.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is disabled")
    return _token_pair(user)


@router.get("/signup-config", response_model=SignupConfig)
async def signup_config(db: DbSession) -> SignupConfig:
    """Public: the sign-in page needs this to decide whether to offer signup."""
    reglages = await parametres.lire(db)
    return SignupConfig(
        enabled=reglages.allow_self_registration,
        requires_code=bool(settings.signup_code),
    )


@router.post("/signup", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupRequest, request: Request, db: DbSession) -> TokenPair:
    reglages = await parametres.lire(db)
    if not reglages.allow_self_registration:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Self-registration is disabled. Ask an administrator for an account.",
        )

    signup_limiter.check(client_ip(request))

    # compare_digest so a wrong code cannot be found by timing the response.
    if settings.signup_code and not secrets.compare_digest(
        payload.signup_code, settings.signup_code
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That sign-up code is not valid")

    email = payload.email.lower()
    existing = await db.execute(select(User.id).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "That email address is already registered")

    # Always RECRUITER. ADMIN can create and list users, so letting anyone
    # grant themselves that role over the network would defeat the check.
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        role=UserRole.RECRUITER,
    )
    db.add(user)
    await db.flush()
    await audit.record(
        db,
        action="user.signup",
        entity_type="user",
        entity_id=user.id,
        user_id=user.id,
        details={"email": email, "ip": client_ip(request)},
    )
    await db.commit()
    await db.refresh(user)
    return _token_pair(user)


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, db: DbSession) -> TokenPair:
    try:
        claims = decode_token(payload.refresh_token, "refresh")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from None

    user = await db.get(User, claims["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return _token_pair(user)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user


@router.get("/users", response_model=list[UserOut])
async def list_users(db: DbSession, _: AdminUser) -> list[User]:
    result = await db.execute(select(User).order_by(User.created_at))
    return list(result.scalars())


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, db: DbSession, admin: AdminUser) -> User:
    email = payload.email.lower()
    existing = await db.execute(select(User.id).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "That email address is already registered")

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=UserRole(payload.role),
    )
    db.add(user)
    await db.flush()
    await audit.record(
        db,
        action="user.create",
        entity_type="user",
        entity_id=user.id,
        user_id=admin.id,
        details={"email": email, "role": user.role.value},
    )
    await db.commit()
    await db.refresh(user)
    return user
