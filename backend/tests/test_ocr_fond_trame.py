"""OCR des diplômes à fond tramé, guilloché ou coloré : la lecture la plus sûre l'emporte."""

from __future__ import annotations

import io

import pytest

from app.services import ocr

TSV = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t95.0\tDIPLOME\n"
    "5\t1\t1\t1\t1\t2\t0\t0\t10\t10\t91.0\tDE\n"
    "5\t1\t1\t1\t1\t3\t0\t0\t10\t10\t93.0\tLICENCE\n"
    "5\t1\t1\t1\t2\t1\t0\t0\t10\t10\t30.0\t~:#\n"
    "5\t1\t1\t2\t1\t1\t0\t0\t10\t10\t88.0\tSession\n"
    "5\t1\t1\t2\t1\t2\t0\t0\t10\t10\t89.0\t2019\n"
)


def test_le_tsv_redonne_lignes_et_paragraphes_et_compte_ce_qui_est_sur():
    lecture = ocr._depuis_tsv(TSV)

    assert lecture.texte == "DIPLOME DE LICENCE\n~:#\n\nSession 2019"
    # DIPLOME, DE, LICENCE, Session : 7 + 2 + 7 + 7 lettres sûres ; « ~:# » ne compte pas.
    assert lecture.sures == 23


def test_la_lecture_la_plus_sure_l_emporte(monkeypatch):
    monkeypatch.setattr(ocr, "disponible", lambda: True)
    lectures = iter(
        [
            ocr._Lecture("bouillie", sures=10, lettres=400),
            ocr._Lecture("moins bien", sures=50, lettres=200),
            ocr._Lecture("DIPLOME DE LICENCE", sures=250, lettres=260),
        ]
    )
    monkeypatch.setattr(ocr, "_lire", lambda png, adaptatif: next(lectures))
    monkeypatch.setattr(ocr, "_variantes", lambda png: [(b"a", True), (b"b", False)])

    assert ocr.lire_image(b"png") == "DIPLOME DE LICENCE"


def test_une_page_sans_rien_de_sur_ne_rend_pas_de_bruit(monkeypatch):
    monkeypatch.setattr(ocr, "disponible", lambda: True)
    monkeypatch.setattr(ocr, "_lire", lambda png, adaptatif: ocr._Lecture("~:# lI1 ;;", sures=4, lettres=300))
    monkeypatch.setattr(ocr, "_variantes", lambda png: [(b"a", True)])

    assert ocr.lire_image(b"png") == ""


def test_une_page_nette_ne_paie_pas_d_autre_passe(monkeypatch):
    monkeypatch.setattr(ocr, "disponible", lambda: True)
    appels = []

    def lire(png, adaptatif):
        appels.append(png)
        return ocr._Lecture("texte net " * 30, sures=280, lettres=300)

    monkeypatch.setattr(ocr, "_lire", lire)
    monkeypatch.setattr(ocr, "_variantes", lambda png: pytest.fail("aucune autre passe attendue"))

    ocr.lire_image(b"png")

    assert appels == [b"png"]


@pytest.mark.ocr
def test_un_diplome_sur_fond_guilloche_de_couleur_se_lit():
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1800, 700), (255, 255, 255))
    dessin = ImageDraw.Draw(image)
    # Un guilloché bleu et orange, dense, sur toute la page.
    for x in range(-700, 1800, 9):
        dessin.line([(x, 0), (x + 700, 700)], fill=(120, 150, 235), width=3)
        dessin.line([(x + 700, 0), (x, 700)], fill=(240, 170, 90), width=2)
    try:
        police = ImageFont.truetype("arial.ttf", 64)
    except OSError:
        police = ImageFont.load_default(size=64)
    for rang, ligne in enumerate(("DIPLOME DE LICENCE", "GENIE MECANIQUE", "SESSION DE JUIN")):
        dessin.text((120, 120 + rang * 170), ligne, fill=(15, 15, 15), font=police)
    tampon = io.BytesIO()
    image.save(tampon, "PNG")

    texte = ocr.lire_image(tampon.getvalue()).upper()

    assert "LICENCE" in texte
    assert "MECANIQUE" in texte
