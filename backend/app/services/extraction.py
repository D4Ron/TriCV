from __future__ import annotations

import asyncio
import io
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOC_MIME = "application/msword"

ALLOWED_MIME_TYPES = {PDF_MIME, DOCX_MIME, DOC_MIME}

# Below this, the file is almost certainly a scan or an image-only export.
MIN_USEFUL_CHARS = 200

_MAGIC = (
    (b"%PDF-", PDF_MIME),
    (b"PK\x03\x04", DOCX_MIME),  # any OOXML/zip; refined below
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", DOC_MIME),  # OLE2 compound file
)


class UnreadableDocument(Exception):
    """The file cannot be turned into text locally. Message is shown to HR."""


@dataclass(slots=True)
class ExtractedDocument:
    text: str
    page_count: int
    mime_type: str


def sniff_mime(data: bytes, filename: str = "") -> str | None:
    """Identify the format from its magic bytes. The extension is not trusted."""
    for magic, mime in _MAGIC:
        if data.startswith(magic):
            if mime == DOCX_MIME:
                # A .docx is a zip containing word/document.xml. An .xlsx or a
                # plain zip is not a CV.
                head = data[:4096]
                if b"word/" not in head and not filename.lower().endswith(".docx"):
                    return None
            return mime
    return None


_WS = re.compile(r"[ \t ]+")
_BLANK_RUN = re.compile(r"\n{3,}")


def normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ch >= " ")
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANK_RUN.sub("\n\n", text).strip()


def _extract_pdf(data: bytes) -> ExtractedDocument:
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # corrupt or password-protected
        raise UnreadableDocument(f"The PDF could not be opened ({exc}).") from exc

    try:
        if doc.needs_pass:
            raise UnreadableDocument("The PDF is password-protected and cannot be read.")
        pages = [page.get_text("text") for page in doc]
        return ExtractedDocument(normalise("\n\n".join(pages)), doc.page_count, PDF_MIME)
    finally:
        doc.close()


def _extract_docx(data: bytes) -> ExtractedDocument:
    import docx

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise UnreadableDocument(f"The Word document could not be opened ({exc}).") from exc

    parts = [p.text for p in document.paragraphs]
    # Two-column CV layouts are very often tables; skipping them loses half the CV.
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append("  ".join(dict.fromkeys(cells)))

    return ExtractedDocument(normalise("\n".join(parts)), 1, DOCX_MIME)


def extract_sync(
    data: bytes, mime_type: str, filename: str = "", min_chars: int = MIN_USEFUL_CHARS
) -> ExtractedDocument:
    """`min_chars` à 0 laisse l'appelant juger : le seuil et son message
    d'erreur sont écrits pour un CV, pas pour une fiche de poste."""
    if mime_type == PDF_MIME:
        doc = _extract_pdf(data)
    elif mime_type == DOCX_MIME:
        doc = _extract_docx(data)
    elif mime_type == DOC_MIME:
        raise UnreadableDocument(
            "Legacy .doc files cannot be read. Please re-save the CV as PDF or .docx "
            "and upload it again."
        )
    else:
        raise UnreadableDocument(f"Unsupported file type: {mime_type}")

    if len(doc.text) < min_chars:
        raise UnreadableDocument(
            "This CV is not machine-readable — it looks like a scan or an image-only "
            "export, so no text could be extracted. Ask the candidate for a text-based "
            "PDF, or re-analyse with the full document so the model reads the file directly."
        )
    return doc


async def extract(
    data: bytes, mime_type: str, filename: str = "", min_chars: int = MIN_USEFUL_CHARS
) -> ExtractedDocument:
    """PyMuPDF and python-docx are CPU-bound and synchronous — run off-loop."""
    return await asyncio.to_thread(extract_sync, data, mime_type, filename, min_chars)
