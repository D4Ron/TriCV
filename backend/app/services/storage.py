from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings

_EXT_BY_MIME = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
}


def build_key(mime_type: str) -> str:
    """`2026/08/<uuid>.pdf`. The user-supplied filename never reaches the disk."""
    now = datetime.now(timezone.utc)
    ext = _EXT_BY_MIME.get(mime_type, ".bin")
    return f"{now:%Y/%m}/{uuid.uuid4().hex}{ext}"


class StorageBackend(ABC):
    @abstractmethod
    async def save(self, key: str, data: bytes) -> str: ...

    @abstractmethod
    async def read(self, key: str) -> bytes: ...

    @abstractmethod
    async def stream(self, key: str, chunk_size: int = 64 * 1024) -> AsyncIterator[bytes]: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...


class LocalStorage(StorageBackend):
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        # Refuse anything that escapes the root, whatever the key looks like.
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError(f"storage key escapes the storage root: {key!r}")
        return path

    async def save(self, key: str, data: bytes) -> str:
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(_write)
        return key

    async def read(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def stream(self, key: str, chunk_size: int = 64 * 1024) -> AsyncIterator[bytes]:
        path = self._path(key)
        handle = await asyncio.to_thread(path.open, "rb")
        try:
            while chunk := await asyncio.to_thread(handle.read, chunk_size):
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, True)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).exists)


class S3Storage(StorageBackend):
    """Any S3-compatible endpoint (AWS, MinIO, Scaleway, ...).

    boto3 is synchronous, so every call is pushed to a worker thread to keep
    the event loop free.
    """

    def __init__(self) -> None:
        import boto3

        self.bucket = settings.s3_bucket
        if not self.bucket:
            raise ValueError("STORAGE_BACKEND=s3 requires S3_BUCKET")
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key or None,
            aws_secret_access_key=settings.s3_secret_key or None,
        )

    async def save(self, key: str, data: bytes) -> str:
        await asyncio.to_thread(self.client.put_object, Bucket=self.bucket, Key=key, Body=data)
        return key

    async def read(self, key: str) -> bytes:
        obj = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=key)
        return await asyncio.to_thread(obj["Body"].read)

    async def stream(self, key: str, chunk_size: int = 64 * 1024) -> AsyncIterator[bytes]:
        obj = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=key)
        body = obj["Body"]
        try:
            while chunk := await asyncio.to_thread(body.read, chunk_size):
                yield chunk
        finally:
            await asyncio.to_thread(body.close)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)

    async def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            await asyncio.to_thread(self.client.head_object, Bucket=self.bucket, Key=key)
        except ClientError:
            return False
        return True


_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _backend
    if _backend is None:
        _backend = S3Storage() if settings.storage_backend == "s3" else LocalStorage(
            settings.storage_path
        )
    return _backend
