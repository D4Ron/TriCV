"""Un travail en file d'attente : une lecture à faire sur un dossier."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, uuid_pk

# Ce qu'il y a à faire.
DECOUPAGE = "DECOUPAGE"
LECTURE_LOCALE = "LECTURE_LOCALE"
LECTURE_IA = "LECTURE_IA"

# Où il en est.
ATTENTE = "ATTENTE"
EN_COURS = "EN_COURS"
FAIT = "FAIT"
ECHEC = "ECHEC"


class Travail(Base, TimestampMixin):
    __tablename__ = "travail"

    id: Mapped[str] = uuid_pk()
    nature: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    candidature_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("candidature.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Vide pour une candidature spontanée. Sert à suivre un lot poste par poste.
    poste_id: Mapped[str | None] = mapped_column(sa.String(36), index=True)
    etat: Mapped[str] = mapped_column(sa.String(16), default=ATTENTE, nullable=False, index=True)
    essais: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    # Quota épuisé : on ne repasse pas avant cette heure.
    pas_avant: Mapped[datetime | None] = mapped_column(sa.DateTime)
    erreur: Mapped[str | None] = mapped_column(sa.Text)
    # Ce qu'a coûté la lecture : d'où se tire le temps restant.
    secondes: Mapped[float | None] = mapped_column(sa.Float)
    jetons: Mapped[int | None] = mapped_column(sa.Integer)
    fournisseur: Mapped[str | None] = mapped_column(sa.String(64))
    # Un lot terminé sort du suivi ; il reste pour mesurer et compter la journée.
    clos: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
