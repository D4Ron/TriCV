"""Lire le texte d'une image : scans, photos de diplômes, pages sans texte.

Constaté sur les dossiers réels : une bonne part des pièces sont des scans ou
des photos prises au téléphone — diplômes, attestations, pièces d'identité,
parfois le CV lui-même. Sans OCR, ces pages n'avaient aucun texte : la pièce
restait sans type, le dossier sans diplôme, et le candidat paraissait n'avoir
rien fourni.

Tesseract, appelé en ligne de commande plutôt que par une bibliothèque : c'est
ce que font OCRmyPDF et paperless-ngx, l'image Docker l'installe en une ligne,
et rien n'est envoyé hors du serveur. Le mode de segmentation 1 détecte
l'orientation de la page — une photo prise de travers ou un scan à l'envers se
lit quand même.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache

from app.config import settings

logger = logging.getLogger(__name__)

# Une page A4 à 300 points par pouce : la résolution que recommande Tesseract.
RESOLUTION = 300
DELAI_PAR_PAGE = 90

_EMPLACEMENTS_WINDOWS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


@lru_cache(maxsize=1)
def commande() -> str | None:
    """Le chemin de Tesseract, ou None s'il n'est pas installé."""
    if settings.ocr_commande:
        return settings.ocr_commande if os.path.exists(settings.ocr_commande) or shutil.which(settings.ocr_commande) else None
    trouve = shutil.which("tesseract")
    if trouve:
        return trouve
    for chemin in _EMPLACEMENTS_WINDOWS:
        if os.path.exists(chemin):
            return chemin
    return None


def disponible() -> bool:
    return commande() is not None and bool(langues())


def _dossier() -> list[str]:
    return ["--tessdata-dir", settings.ocr_dossier_langues] if settings.ocr_dossier_langues else []


@lru_cache(maxsize=1)
def langues() -> str:
    """Les langues demandées qui sont installées : « fra+eng », ou ce qu'il en reste.

    Sans le français, Tesseract refuse tout l'appel : mieux vaut lire en
    anglais seul — les lettres sont les mêmes, seuls les accents souffrent —
    que ne rien lire.
    """
    tesseract = commande()
    if tesseract is None:
        return ""
    try:
        sortie = subprocess.run(
            [tesseract, *_dossier(), "--list-langs"], capture_output=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    installees = {l.strip() for l in sortie.stdout.decode("utf-8", "replace").splitlines()[1:]}
    voulues = [l for l in settings.ocr_langues.split("+") if l in installees]
    if not voulues:
        voulues = sorted(installees - {"osd", "equ"})[:1]
        if voulues:
            logger.warning("OCR : langues %s absentes, lecture en %s", settings.ocr_langues, voulues[0])
    return "+".join(voulues)


def _arguments(psm: int, adaptatif: bool = False) -> list[str]:
    tesseract = commande()
    assert tesseract is not None
    args = [tesseract, "stdin", "stdout", *_dossier(), "-l", langues(), "--psm", str(psm)]
    if adaptatif:
        args += ["-c", "thresholding_method=2"]
    return args


def _lettres(texte: str) -> int:
    return sum(1 for c in texte if c.isalpha())


# Un mot dont Tesseract est sûr à ce point est presque toujours juste ; sur un
# fond tramé ou guilloché, la plupart des « mots » lus sont du bruit et restent
# bien en dessous. La part de lettres sûres dit donc si la lecture tient.
_CONFIANCE_SURE = 80
# Au-delà, la première lecture suffit : on ne paie pas d'autres passes.
_PART_SUFFISANTE = 0.8
# En deçà, la page n'a rien donné d'exploitable : mieux vaut ne rien rendre
# que du bruit, que le modèle prendrait pour un diplôme ou un employeur.
_SURES_MINIMUM = 40


@dataclass(frozen=True, slots=True)
class _Lecture:
    texte: str
    sures: int  # lettres des mots lus avec assurance
    lettres: int

    @property
    def part(self) -> float:
        return self.sures / self.lettres if self.lettres else 0.0


_VIDE = _Lecture("", 0, 0)


def lire_image(png: bytes) -> str:
    """Le texte d'une image PNG. Chaîne vide si Tesseract est absent ou échoue.

    Constaté sur des dossiers réels : une page scannée au téléphone, au fond
    gris, ressortait vide — le seuillage global de Tesseract la noircissait ou
    la blanchissait en entier. Et les diplômes imprimés sur fond tramé ou
    guilloché, ou sur papier de couleur, ressortaient en bouillie : le motif se
    lisait comme des lettres. Aucun prétraitement ne vaut pour tous : selon la
    page, c'est le seuillage adaptatif, l'isolement de l'encre sombre ou le
    lissage du motif qui l'emporte.

    Quand la première lecture est peu sûre, on relit donc l'image sous
    plusieurs formes et on garde celle dont Tesseract est le plus sûr — c'est
    sa propre confiance, mot par mot, qui départage. Une page qui ne donne rien
    de sûr sous aucune forme rend une chaîne vide : la pièce est alors signalée
    comme illisible au lieu d'envoyer du bruit.

    Ne lève pas : une page illisible ne doit pas faire échouer la lecture du
    reste du dossier.
    """
    if not disponible():
        return ""
    lecture = _lire(png, adaptatif=False)
    if lecture.part < _PART_SUFFISANTE or lecture.lettres < 120:
        for image, adaptatif in _variantes(png):
            essai = _lire(image, adaptatif)
            if essai.sures > lecture.sures:
                lecture = essai
            if lecture.part >= 0.9 and lecture.sures >= 300:
                break
    if lecture.sures < _SURES_MINIMUM:
        return ""
    return lecture.texte


def _variantes(png: bytes):
    """Les autres formes sous lesquelles relire une page peu sûre.

    Pillow et numpy viennent avec les dépendances (reportlab, spaCy) ; s'ils
    manquaient, seul le seuillage adaptatif de Tesseract resterait.
    """
    yield png, True
    try:
        import io

        import numpy as np
        from PIL import Image, ImageFilter, ImageOps
    except ImportError:  # pragma: no cover - dépendances transitives
        return

    def en_png(image) -> bytes:
        tampon = io.BytesIO()
        image.save(tampon, "PNG")
        return tampon.getvalue()

    try:
        couleur = Image.open(io.BytesIO(png)).convert("RGB")
    except Exception:  # noqa: BLE001 - une image que Pillow ne lit pas : on s'arrête là
        return
    gris = couleur.convert("L")
    # L'encre est sombre sur les trois canaux ; un fond de couleur, un
    # guilloché bleu ou orange ne l'est pas sur tous.
    sombre = np.asarray(couleur).max(axis=2)
    for seuil in (150, 110):
        yield en_png(Image.fromarray(np.where(sombre < seuil, 0, 255).astype(np.uint8))), False
    # Un fond tramé ou guilloché : lisser le motif avant de seuiller.
    yield en_png(ImageOps.autocontrast(gris.filter(ImageFilter.MedianFilter(5)), cutoff=2)), True
    yield en_png(ImageOps.autocontrast(gris.filter(ImageFilter.GaussianBlur(2)), cutoff=1)), True


def _lire(png: bytes, adaptatif: bool) -> _Lecture:
    # PSM 1 (orientation détectée) a besoin du modèle « osd » ; s'il manque,
    # on retombe sur la segmentation automatique simple.
    for psm in (1, 3):
        try:
            sortie = subprocess.run(
                [*_arguments(psm, adaptatif), "-c", "tessedit_create_tsv=1"],
                input=png,
                capture_output=True,
                timeout=DELAI_PAR_PAGE,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("OCR impossible : %s", exc)
            return _VIDE
        if sortie.returncode == 0:
            return _depuis_tsv(sortie.stdout.decode("utf-8", errors="replace"))
        logger.info(
            "Tesseract (psm %s) a échoué : %s", psm, sortie.stderr.decode("utf-8", "replace")[:300]
        )
    return _VIDE


def _depuis_tsv(tsv: str) -> _Lecture:
    """Le texte, ligne par ligne et paragraphe par paragraphe, et sa part sûre."""
    lignes: list[str] = []
    courante: list[str] = []
    cle_ligne = cle_paragraphe = None
    sures = 0
    for brut in tsv.splitlines()[1:]:
        champs = brut.split("\t")
        if len(champs) != 12 or not champs[11].strip():
            continue
        mot = champs[11].strip()
        paragraphe = (champs[2], champs[3])
        ligne = (*paragraphe, champs[4])
        if ligne != cle_ligne:
            if courante:
                lignes.append(" ".join(courante))
            if cle_paragraphe is not None and paragraphe != cle_paragraphe:
                lignes.append("")
            courante, cle_ligne, cle_paragraphe = [], ligne, paragraphe
        courante.append(mot)
        try:
            confiance = float(champs[10])
        except ValueError:
            confiance = 0.0
        if confiance >= _CONFIANCE_SURE and _lettres(mot) >= 2:
            sures += _lettres(mot)
    if courante:
        lignes.append(" ".join(courante))
    texte = "\n".join(lignes)
    return _Lecture(texte, sures, _lettres(texte))
