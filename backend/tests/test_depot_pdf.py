"""Ce que les candidats envoient : le PDF, et rien d'autre.

Le formulaire public acceptait le PDF et le Word. Un document Word ne s'ouvre
pas à l'identique d'un poste à l'autre — polices substituées, mise en page
déplacée —, et c'est un PDF que le cabinet remet au client. Le format se règle
donc au dépôt, là où le candidat peut encore le corriger.

Le format se reconnaît au contenu, jamais à l'extension : un Word renommé en
« .pdf » est refusé comme un Word.

Ce que ces tests ne changent pas, et figent : les pièces ajoutées par le
cabinet et les dossiers reçus par courriel acceptent toujours le Word. Le
cabinet convertit ce qu'il reçoit ; refuser un courriel ne préviendrait
personne.
"""

from __future__ import annotations

import io

import docx
import pytest

from app.services import uploads
from tests.test_declaration_candidat import dossier, monter_poste

API = "/api/v1"
pytestmark = pytest.mark.anyio

PDF = b"%PDF-1.4 un CV"


def _word() -> bytes:
    document = docx.Document()
    document.add_paragraph("Curriculum vitae")
    tampon = io.BytesIO()
    document.save(tampon)
    return tampon.getvalue()


WORD_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# --- la règle elle-même ------------------------------------------------------


def test_un_pdf_passe():
    accepte = uploads.valider_octets(PDF, "cv.pdf", pdf_seulement=True)
    assert accepte.mime_type == "application/pdf"


def test_un_word_est_refuse_et_le_refus_dit_comment_convertir():
    with pytest.raises(uploads.RejectedUpload) as refus:
        uploads.valider_octets(_word(), "cv.docx", pdf_seulement=True)
    message = str(refus.value)
    assert "cv.docx" in message
    assert "document Word" in message
    assert "Seul le format PDF" in message
    # La marche à suivre, pas seulement le refus.
    assert "Enregistrer sous" in message


def test_un_word_renomme_en_pdf_est_refuse_aussi():
    """Le contenu fait foi : changer l'extension ne suffit pas."""
    with pytest.raises(uploads.RejectedUpload) as refus:
        uploads.valider_octets(_word(), "cv.pdf", pdf_seulement=True)
    assert "document Word" in str(refus.value)


def test_sans_la_regle_le_word_reste_admis():
    """Les dépôts du cabinet ne passent pas par la règle."""
    accepte = uploads.valider_octets(_word(), "cv.docx")
    assert accepte.mime_type == WORD_MIME


# --- le formulaire public ----------------------------------------------------


async def test_le_formulaire_refuse_un_word(client, auth):
    cle = await monter_poste(client, auth)
    reponse = await client.post(
        f"{API}/public/avis/{cle}/candidater",
        data=dossier(),
        files={"fichiers": ("cv.docx", _word(), WORD_MIME)},
    )
    assert reponse.status_code == 422
    assert "Seul le format PDF" in reponse.json()["detail"]


async def test_le_formulaire_accepte_un_pdf(client, auth):
    cle = await monter_poste(client, auth)
    reponse = await client.post(
        f"{API}/public/avis/{cle}/candidater",
        data=dossier(),
        files={"fichiers": ("cv.pdf", PDF, "application/pdf")},
    )
    assert reponse.status_code in (200, 201), reponse.text


async def test_la_page_publique_annonce_le_pdf_seul(client, auth):
    """Ce que l'avis affiche doit être ce que le dépôt accepte."""
    cle = await monter_poste(client, auth)
    avis = (await client.get(f"{API}/public/avis/{cle}")).json()
    assert avis["formats_acceptes"] == ["PDF"]


async def test_la_candidature_spontanee_refuse_un_word(client, auth):
    reponse = await client.post(
        f"{API}/public/candidature-spontanee",
        data={
            "nom": "ATTIOGBE",
            "prenom": "Sena",
            "email": "s.attiogbe@example.tg",
            "types_pieces": ["CV"],
        },
        files={"fichiers": ("cv.docx", _word(), WORD_MIME)},
    )
    assert reponse.status_code == 422
    assert "Seul le format PDF" in reponse.json()["detail"]
