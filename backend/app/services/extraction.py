"""Le texte d'une pièce : PDF, Word, ou image.

Ce qui a changé après les essais sur des dossiers réels :

- **Page par page.** Un candidat fusionne souvent tout son dossier en un seul
  PDF : CV, lettre, diplômes, pièce d'identité. Le découpage (`decoupage`) a
  besoin du texte de chaque page, pas d'un bloc.
- **OCR des pages sans texte.** Une page scannée, ou dont la couche texte est
  illisible (police mal encodée), passe par Tesseract (`ocr`). Sans cela, un
  diplôme scanné n'existait pas.
- **Images acceptées.** Les photos de diplômes ou de pièces d'identité prises
  au téléphone arrivent en JPEG ; elles étaient ignorées.
- **Word lu en entier.** Les zones de texte et l'en-tête de page — là où les
  modèles de CV placent souvent le nom — échappaient à la lecture des seuls
  paragraphes.
- **La ligne la plus grande.** Le nom est presque toujours la ligne en plus
  gros caractères de la première page : c'est l'indice principal du parseur
  d'OpenResume. On le relève ici, où la taille des polices est connue.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import zipfile
from dataclasses import dataclass, field

from app.config import settings
from app.services import ocr

logger = logging.getLogger(__name__)

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOC_MIME = "application/msword"
JPEG_MIME = "image/jpeg"
PNG_MIME = "image/png"
TIFF_MIME = "image/tiff"
WEBP_MIME = "image/webp"

IMAGE_MIME_TYPES = {JPEG_MIME, PNG_MIME, TIFF_MIME, WEBP_MIME}
ALLOWED_MIME_TYPES = {PDF_MIME, DOCX_MIME, DOC_MIME} | IMAGE_MIME_TYPES

# Below this, the file is almost certainly a scan or an image-only export.
MIN_USEFUL_CHARS = 200
# Une page qui a moins que cela en couche texte est traitée comme un scan.
TEXTE_MIN_PAR_PAGE = 40

_MAGIC = (
    (b"%PDF-", PDF_MIME),
    (b"PK\x03\x04", DOCX_MIME),  # any OOXML/zip; refined below
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", DOC_MIME),  # OLE2 compound file
    (b"\xff\xd8\xff", JPEG_MIME),
    (b"\x89PNG\r\n\x1a\n", PNG_MIME),
    (b"II*\x00", TIFF_MIME),
    (b"MM\x00*", TIFF_MIME),
)


class UnreadableDocument(Exception):
    """The file cannot be turned into text locally. Message is shown to HR."""


@dataclass(slots=True)
class ExtractedDocument:
    text: str
    page_count: int
    mime_type: str
    # Le texte de chaque page, dans l'ordre. Un document Word compte pour une.
    pages: list[str] = field(default_factory=list)
    # Les pages lues par OCR — à signaler : leur texte est moins sûr.
    pages_ocr: list[int] = field(default_factory=list)
    # La ligne en plus gros caractères de la première page, si elle se
    # détache nettement du reste : presque toujours le nom.
    titre: str | None = None
    # Largeur et hauteur de chaque page : un changement de format trahit un
    # autre document dans un PDF fusionné.
    formats: list[tuple[int, int]] = field(default_factory=list)


def sniff_mime(data: bytes, filename: str = "") -> str | None:
    """Identify the format from its magic bytes. The extension is not trusted."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return WEBP_MIME
    # Un PDF peut commencer par quelques octets parasites : les lecteurs les
    # tolèrent, et les candidats ne savent pas qu'ils sont là.
    if b"%PDF-" in data[:1024] and not data.startswith(b"%PDF-"):
        return PDF_MIME
    for magic, mime in _MAGIC:
        if data.startswith(magic):
            if mime == DOCX_MIME:
                # A .docx is a zip containing word/document.xml. An .xlsx or a
                # plain zip is not a CV.
                if not _est_docx(data, filename):
                    return None
            return mime
    return None


def _est_docx(data: bytes, filename: str) -> bool:
    if b"word/" in data[:4096]:
        return True
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return "word/document.xml" in archive.namelist()
    except (zipfile.BadZipFile, OSError):
        return filename.lower().endswith(".docx")


def image_lisible(data: bytes) -> bool:
    import fitz

    try:
        pixmap = fitz.Pixmap(data)
    except Exception:  # noqa: BLE001
        return False
    return pixmap.width > 0 and pixmap.height > 0


def image_utile(data: bytes) -> bool:
    """Une image assez grande pour être un document, pas un logo de signature.

    Les courriels portent des images en ligne — logos, icônes de réseaux
    sociaux, bannières de signature. Une photo de diplôme fait au moins
    quelques centaines de pixels de côté.
    """
    import fitz

    try:
        pixmap = fitz.Pixmap(data)
    except Exception:  # noqa: BLE001 — image illisible : pas un document
        return False
    return min(pixmap.width, pixmap.height) >= 400 and len(data) >= 25_000


def piece_retenue(data: bytes, filename: str = "") -> str | None:
    """Le type d'une pièce jointe à garder, ou None : un logo de signature, un
    fichier Excel ou une page HTML ne sont pas des pièces de dossier."""
    mime = sniff_mime(data, filename)
    if mime not in ALLOWED_MIME_TYPES:
        return None
    if mime in IMAGE_MIME_TYPES and not image_utile(data):
        return None
    return mime


_WS = re.compile(r"[ \t ]+")
_BLANK_RUN = re.compile(r"\n{3,}")


def normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ch >= " ")
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANK_RUN.sub("\n\n", text).strip()


def texte_douteux(texte: str) -> bool:
    """Une couche texte qui ne veut rien dire : police mal encodée, glyphes perdus.

    Certains PDF exportés affichent un texte lisible mais rendent, à la copie,
    des « ������ » ou des suites de symboles. Lire l'image de la page vaut
    alors mieux que lire ce texte-là.
    """
    visibles = [c for c in texte if not c.isspace()]
    if len(visibles) < TEXTE_MIN_PAR_PAGE:
        return True
    remplacement = sum(1 for c in visibles if c == "�")
    lettres = sum(1 for c in visibles if c.isalpha())
    return remplacement / len(visibles) > 0.05 or lettres / len(visibles) < 0.45


def _titre_de_page(page) -> str | None:
    """La ligne en plus gros caractères, si elle dépasse nettement les autres."""
    try:
        donnees = page.get_text("dict")
    except Exception:  # noqa: BLE001
        return None
    lignes: list[tuple[float, str, float]] = []
    for bloc in donnees.get("blocks", []):
        for ligne in bloc.get("lines", []):
            spans = [s for s in ligne.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            texte = " ".join(s["text"].strip() for s in spans)
            taille = max(s.get("size", 0) for s in spans)
            lignes.append((taille, texte, ligne.get("bbox", (0, 0, 0, 0))[1]))
    if len(lignes) < 3:
        return None
    tailles = sorted(t for t, _, _ in lignes)
    mediane = tailles[len(tailles) // 2]
    plus_grande = max(t for t, _, _ in lignes)
    if plus_grande < mediane * 1.3:
        return None
    # Les lignes de cette taille, de haut en bas : un nom sur deux lignes
    # (« Afi » / « DOSSOU ») se recompose.
    morceaux = [t for taille, t, _ in sorted(lignes, key=lambda x: x[2]) if taille >= plus_grande - 0.5]
    titre = " ".join(morceaux[:2]).strip()
    return titre[:120] or None


def _rendre(page) -> bytes:
    import fitz

    matrice = fitz.Matrix(ocr.RESOLUTION / 72, ocr.RESOLUTION / 72)
    return page.get_pixmap(matrix=matrice, colorspace=fitz.csGRAY).tobytes("png")


def _extract_pdf(data: bytes) -> ExtractedDocument:
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # corrupt or password-protected
        raise UnreadableDocument(f"Le PDF ne s'ouvre pas ({exc}).") from exc

    try:
        if doc.needs_pass:
            raise UnreadableDocument("Le PDF est protégé par un mot de passe et ne peut pas être lu.")
        pages: list[str] = []
        pages_ocr: list[int] = []
        formats: list[tuple[int, int]] = []
        for numero, page in enumerate(doc):
            formats.append((round(page.rect.width), round(page.rect.height)))
            texte = page.get_text("text")
            if texte_douteux(texte) and len(pages_ocr) < settings.ocr_pages_max and ocr.disponible():
                lu = ocr.lire_image(_rendre(page))
                if lu.strip():
                    texte = lu
                    pages_ocr.append(numero)
            pages.append(normalise(texte))
        titre = _titre_de_page(doc[0]) if doc.page_count and 0 not in pages_ocr else None
        return ExtractedDocument(
            normalise("\n\n".join(pages)),
            doc.page_count,
            PDF_MIME,
            pages,
            pages_ocr,
            titre,
            formats=formats,
        )
    finally:
        doc.close()


def _extract_image(data: bytes, mime_type: str) -> ExtractedDocument:
    import fitz

    try:
        pixmap = fitz.Pixmap(data)
        if pixmap.alpha or pixmap.colorspace is None or pixmap.colorspace.n not in (1, 3):
            pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
        png = pixmap.tobytes("png")
    except Exception as exc:  # noqa: BLE001
        raise UnreadableDocument(f"L'image ne s'ouvre pas ({exc}).") from exc
    texte = normalise(ocr.lire_image(png)) if ocr.disponible() else ""
    return ExtractedDocument(texte, 1, mime_type, [texte], [0] if texte else [], None)


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


def _paragraphes(element) -> list[str]:
    """Le texte de chaque paragraphe, zones de texte et tableaux compris.

    Une zone de texte figure deux fois dans le fichier — sa forme moderne et
    une forme de repli pour les anciens Word : seule la première est lue.
    """
    lignes: list[str] = []
    for paragraphe in element.iter(f"{_W}p"):
        parent, repli = paragraphe.getparent(), False
        while parent is not None:
            if parent.tag == _MC_FALLBACK:
                repli = True
                break
            parent = parent.getparent()
        if repli:
            continue
        morceaux = []
        for noeud in paragraphe.iter(f"{_W}t", f"{_W}tab", f"{_W}br"):
            morceaux.append(noeud.text or "" if noeud.tag == f"{_W}t" else " ")
        texte = "".join(morceaux).strip()
        if texte:
            lignes.append(texte)
    return lignes


def _extract_docx(data: bytes) -> ExtractedDocument:
    import docx

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise UnreadableDocument(f"Le document Word ne s'ouvre pas ({exc}).") from exc

    parts: list[str] = []
    # L'en-tête de page porte souvent le nom et les coordonnées.
    vus: set[int] = set()
    for section in document.sections:
        for entete in (section.first_page_header, section.header):
            try:
                cle = id(entete._element)
                if entete.is_linked_to_previous or cle in vus:
                    continue
                vus.add(cle)
                parts.extend(_paragraphes(entete._element))
            except Exception:  # noqa: BLE001 — en-tête absent ou mal formé
                continue
    parts.extend(_paragraphes(document.element.body))
    texte = normalise("\n".join(parts))
    return ExtractedDocument(texte, 1, DOCX_MIME, [texte], [], None)


def extract_sync(
    data: bytes, mime_type: str, filename: str = "", min_chars: int = MIN_USEFUL_CHARS
) -> ExtractedDocument:
    """`min_chars` à 0 laisse l'appelant juger : le seuil et son message
    d'erreur sont écrits pour un CV, pas pour une fiche de poste."""
    if mime_type == PDF_MIME:
        doc = _extract_pdf(data)
    elif mime_type == DOCX_MIME:
        doc = _extract_docx(data)
    elif mime_type in IMAGE_MIME_TYPES:
        doc = _extract_image(data, mime_type)
    elif mime_type == DOC_MIME:
        raise UnreadableDocument(
            "Les anciens fichiers Word (.doc) ne peuvent pas être lus. Demandez le "
            "document en PDF ou en .docx."
        )
    else:
        raise UnreadableDocument(f"Format non pris en charge : {mime_type}")

    if len(doc.text) < min_chars:
        if not ocr.disponible() and mime_type != DOCX_MIME:
            raise UnreadableDocument(
                "Ce document n'a pas de texte lisible — c'est un scan ou une image, et la "
                "lecture des scans (Tesseract) n'est pas installée sur le serveur."
            )
        raise UnreadableDocument(
            "Ce document n'a presque pas de texte lisible, même après lecture de "
            "l'image : scan trop flou, photo de travers ou page blanche."
        )
    return doc


async def extract(
    data: bytes, mime_type: str, filename: str = "", min_chars: int = MIN_USEFUL_CHARS
) -> ExtractedDocument:
    """PyMuPDF, python-docx et Tesseract sont synchrones — hors de la boucle."""
    return await asyncio.to_thread(extract_sync, data, mime_type, filename, min_chars)
