from __future__ import annotations

import io
import logging
import zipfile
from collections.abc import AsyncIterator

from app.services.exports.data import ExportData, safe_filename
from app.services.storage import get_storage

logger = logging.getLogger(__name__)

EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
}


class _StreamSink(io.RawIOBase):
    """A write-only, non-seekable sink.

    `zipfile` detects the missing `tell()` and switches to data descriptors, so
    the archive can be emitted chunk by chunk instead of assembled in memory.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

    def write(self, data) -> int:
        self._buffer += data
        return len(data)

    def tell(self) -> int:
        raise OSError("stream is not seekable")

    def drain(self) -> bytes:
        chunk = bytes(self._buffer)
        self._buffer.clear()
        return chunk


def cv_filename(candidate, mime_type: str | None) -> str:
    """`01_KOSSI_Amevi.pdf` — sorts by rank and reads as a name."""
    last, first = candidate.last_first
    parts = [f"{candidate.rank:02d}", safe_filename(last)]
    if first:
        parts.append(safe_filename(first))
    return "_".join(parts) + EXTENSIONS.get(mime_type or "", ".pdf")


async def stream_zip(
    data: ExportData, report_bytes: bytes, report_name: str
) -> AsyncIterator[bytes]:
    """The report plus a `CVs/` folder. Each CV is flushed as it is written."""
    sink = _StreamSink()
    storage = get_storage()
    used: set[str] = set()

    with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(report_name, report_bytes)
        if chunk := sink.drain():
            yield chunk

        for candidate in data.candidates:
            if not candidate.cv_storage_path:
                continue
            try:
                blob = await storage.read(candidate.cv_storage_path)
            except Exception:
                logger.warning(
                    "bundle: skipping missing CV for candidate rank %d", candidate.rank
                )
                continue

            name = cv_filename(candidate, candidate.cv_mime_type)
            stem, _, suffix = name.rpartition(".")
            counter = 2
            while name in used:  # two candidates can share a name
                name = f"{stem}_{counter}.{suffix}"
                counter += 1
            used.add(name)

            archive.writestr(f"CVs/{name}", blob)
            if chunk := sink.drain():
                yield chunk

    if chunk := sink.drain():
        yield chunk
