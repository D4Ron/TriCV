from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, uuid_pk
from app.models.enums import UserRole


class User(Base, TimestampMixin):
    __tablename__ = "user"

    id: Mapped[str] = uuid_pk()
    email: Mapped[str] = mapped_column(sa.String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        sa.Enum(UserRole, name="user_role"), default=UserRole.RECRUITER, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
