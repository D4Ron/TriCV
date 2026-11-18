"""Un seul PDF à imprimer : sommaire, une fiche par candidat, ses pièces, un pied de page."""

from __future__ import annotations

import re

import fitz
import pytest

from app.domain.referentiel import PieceDossier as P
from app.services import impression


def pdf(pages: int, texte: str) -> bytes:
    doc = fitz.open()
    for n in range(pages):
        doc.new_page().insert_text((72, 72), f"{texte} {n + 1}")
    return doc.tobytes()


def png() -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), False)
    pix.clear_with(200)
    return pix.tobytes("png")


def dossier(rang: int, nom: str, pieces) -> impression.DossierAImprimer:
    return impression.DossierAImprimer(
        rang=rang, nom=nom, note="20/30", statut="Préqualifié",
        lignes=[("Formation académique", "5/7", ""), ("Expérience spécifique", "10/15", "Vérifié sur le document (le calcul donnait 9)")],
        profil="Profil logistique, Bac+5 (Master en logistique).",
        notes=["Certifications : PMP"], a_verifier=["« cv.pdf » contient aussi une lettre de motivation"],
        pieces=pieces,
    )


def texte_des_pages(contenu: bytes) -> list[str]:
    return [page.get_text() for page in fitz.open(stream=contenu, filetype="pdf")]


def test_chaque_dossier_a_sa_fiche_ses_pieces_et_son_pied_de_page():
    dossiers = [
        dossier(1, "DOSSOU Afi", [
            impression.PieceAImprimer("cv.pdf", P.CV.value, "application/pdf", pdf(2, "CV-AFI")),
            impression.PieceAImprimer("photo.png", P.COPIE_DIPLOMES.value, "image/png", png()),
        ]),
        dossier(2, "KOFFI Ama", [
            impression.PieceAImprimer("cv.pdf", P.CV.value, "application/pdf", pdf(1, "CV-AMA")),
        ]),
    ]

    pages = texte_des_pages(impression.composer(dossiers, "Responsable logistique", recto_verso=False))

    tout = "\n".join(pages)
    assert "CV-AFI 1" in tout and "CV-AFI 2" in tout and "CV-AMA 1" in tout
    assert "001 · DOSSOU Afi · p. 1/4" in tout
    assert "002 · KOFFI Ama · p. 2/2" in tout
    assert "Vérifié sur le document" in tout


def test_le_sommaire_renvoie_a_la_bonne_page():
    dossiers = [
        dossier(n, f"CANDIDAT{n:02d} Test", [impression.PieceAImprimer("cv.pdf", P.CV.value, "application/pdf", pdf(n % 3 + 1, f"CV{n}"))])
        for n in range(1, 61)
    ]

    pages = texte_des_pages(impression.composer(dossiers, "Poste", recto_verso=True))

    sommaire = "\n".join(p for p in pages[:4] if "dans l'ordre du classement" in p or "page " in p)
    for n in (1, 37, 60):
        numero = int(re.search(rf"{n:03d}\s+CANDIDAT{n:02d} Test .*?page (\d+)", sommaire).group(1))
        assert re.search(rf"{n:03d}\s+·\s+CANDIDAT{n:02d} Test", pages[numero - 1])
        # En recto-verso, chaque dossier commence sur un recto (page impaire).
        assert numero % 2 == 1


def test_l_etat_civil_ne_s_imprime_pas_et_un_fichier_absent_laisse_son_texte():
    dossiers = [
        dossier(1, "DOSSOU Afi", [
            impression.PieceAImprimer("cni.pdf", P.PIECE_IDENTITE.value, "application/pdf", pdf(1, "CARTE-IDENTITE")),
            impression.PieceAImprimer("lettre.docx", P.LETTRE_MOTIVATION.value, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", None, texte="Madame, je vous écris."),
        ]),
    ]

    tout = "\n".join(texte_des_pages(impression.composer(dossiers, "Poste")))

    assert "CARTE-IDENTITE" not in tout
    assert "Madame, je vous écris." in tout


def test_sans_les_pieces_il_ne_reste_que_les_fiches():
    dossiers = [dossier(1, "DOSSOU Afi", [impression.PieceAImprimer("cv.pdf", P.CV.value, "application/pdf", pdf(5, "CV-AFI"))])]

    tout = "\n".join(texte_des_pages(impression.composer(dossiers, "Poste", avec_pieces=False, recto_verso=False)))

    assert "CV-AFI" not in tout
    assert "DOSSOU Afi" in tout


@pytest.mark.anyio
async def test_le_poste_s_imprime_en_un_pdf_dans_l_ordre_du_classement(client, auth):
    from app.db import SessionLocal
    from tests.test_confiance import CV, LETTRE, dossier as creer, poste_de

    async with SessionLocal() as db:
        poste = await poste_de(db)
        un = await creer(db, poste, pieces=[(P.CV.value, CV), (P.LETTRE_MOTIVATION.value, LETTRE)])
        deux = await creer(db, poste, pieces=[(P.CV.value, CV)], experiences=())
        await db.commit()

    reponse = await client.post(
        f"/api/v1/postes/{poste}/dossiers.pdf",
        json={"candidature_ids": [deux, un], "avec_pieces": True, "recto_verso": True},
        headers=auth,
    )

    assert reponse.status_code == 200, reponse.text
    assert reponse.headers["content-type"] == "application/pdf"
    pages = texte_des_pages(reponse.content)
    assert "dans l'ordre du classement" in pages[0]
    assert len(pages) % 2 == 0
