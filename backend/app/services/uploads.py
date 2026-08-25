from __future__ import annotations

import hashlib
from dataclasses import dataclass

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Candidate
from app.schemas.candidate import DuplicateFlag
from app.services import extraction, storage


class RejectedUpload(Exception):
    """A file we will not accept. The message is shown to the uploader."""


@dataclass(slots=True)
class AcceptedFile:
    data: bytes
    mime_type: str
    filename: str
    sha256: str


# Garde-fou, pas une politique de gestion.
#
# Il n'y a plus de limite de taille réglable : un scan de diplômes en couleur
# pèse ce qu'il pèse, et refuser un dossier valable pour cette raison n'a aucun
# sens. Le stockage se maîtrise en purgeant les fichiers des mandats archivés,
# pas en rabotant les dépôts.
#
# Ce plafond-ci subsiste pour une raison différente : `validate` lit le fichier
# entier en mémoire, et le formulaire public est ouvert à tout venant. Sans
# plafond, un seul envoi suffirait à saturer la mémoire du serveur. Il est donc
# volontairement très haut — aucun dossier légitime ne l'atteint — et ne
# s'applique qu'aux dépôts non authentifiés.
PLAFOND_ABSOLU_MO = 100


async def validate(file: UploadFile, max_mb: int | None = None) -> AcceptedFile:
    """Size, then magic bytes. The extension is never trusted.

    `max_mb` ne sert qu'au garde-fou anti-abus du formulaire public ; les
    dépôts authentifiés n'ont pas de limite de taille.
    """
    data = await file.read()
    await file.close()

    if not data:
        raise RejectedUpload("Le fichier est vide.")
    if max_mb is not None and len(data) > max_mb * 1024 * 1024:
        raise RejectedUpload(
            f"Le fichier « {(file.filename or 'sans nom')[:60]} » fait "
            f"{len(data) / 1_048_576:.0f} Mo, ce qui dépasse la limite de {max_mb} Mo "
            "applicable aux dépôts par le formulaire public."
        )

    filename = (file.filename or "cv").strip()[:255]
    mime_type = extraction.sniff_mime(data, filename)
    if mime_type is None or mime_type not in extraction.ALLOWED_MIME_TYPES:
        raise RejectedUpload(
            "Only PDF and Word (.docx) files are accepted. This file's contents do not "
            "match either format."
        )

    return AcceptedFile(
        data=data,
        mime_type=mime_type,
        filename=filename,
        sha256=hashlib.sha256(data).hexdigest(),
    )


async def store(accepted: AcceptedFile) -> str:
    key = storage.build_key(accepted.mime_type)
    return await storage.get_storage().save(key, accepted.data)


async def find_duplicates(
    db: AsyncSession, session_id: str, *, cv_hash: str | None, email: str | None,
    exclude_id: str | None = None,
) -> list[DuplicateFlag]:
    """Flag, never block — HR decides whether a repeat submission matters.

    Byte-identical files are a hard match; a repeated email within the session
    is a soft one (an updated CV from the same person).
    """
    clauses = []
    if cv_hash:
        clauses.append(Candidate.cv_hash == cv_hash)
    if email:
        clauses.append(Candidate.email == email.lower())
    if not clauses:
        return []

    query = select(Candidate).where(Candidate.session_id == session_id)
    query = query.where(clauses[0] if len(clauses) == 1 else clauses[0] | clauses[1])
    if exclude_id:
        query = query.where(Candidate.id != exclude_id)

    flags: list[DuplicateFlag] = []
    for other in (await db.execute(query.limit(10))).scalars():
        reason = "identical_file" if cv_hash and other.cv_hash == cv_hash else "same_email"
        flags.append(
            DuplicateFlag(candidate_id=other.id, full_name=other.full_name, reason=reason)
        )
    return flags
