"""Les pièces envoyées en lien plutôt qu'en pièce jointe.

Constaté en production : un candidat a envoyé ses documents un par un, en liens
de partage. Le relevé n'y voyait qu'un message sans pièce. Ce qui est vérifié :
les liens des services connus sont reconnus et récupérés quand ils sont publics,
un lien privé est signalé, et le serveur ne suit jamais un lien hors de ces
services — y compris par redirection.
"""

from __future__ import annotations

from datetime import datetime
from email.message import EmailMessage

import httpx
import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Candidature
from app.services import courriel, liens

pytestmark = pytest.mark.anyio

PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def test_seuls_les_services_de_partage_sont_reconnus():
    texte = (
        "Mon CV : https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=sharing.\n"
        "Lettre : https://docs.google.com/document/d/1ZyXwVuTsRqPoNm/edit\n"
        "Diplômes : https://www.dropbox.com/s/abc123/diplomes.pdf?dl=0\n"
        "https://1drv.ms/b/s!AbCdEf\n"
        "https://acme-my.sharepoint.com/:b:/g/personal/x/EaBc?e=1\n"
        "https://we.tl/t-AbCdEf\n"
        "Mon site : https://exemple.tg/portfolio et https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=sharing"
    )
    trouves = liens.liens_de_documents(texte)
    assert [l.service for l in trouves] == [
        "Google Drive", "Google Docs", "Dropbox", "OneDrive", "OneDrive / SharePoint", "WeTransfer",
    ]
    # La ponctuation finale ne fait pas partie du lien ; le doublon est vu une fois.
    assert trouves[0].url.endswith("usp=sharing")
    assert trouves[-1].telechargeable is False


@pytest.mark.parametrize(
    ("url", "attendu"),
    [
        (
            "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=sharing",
            "https://drive.usercontent.google.com/download?id=1AbCdEfGhIjKlMnOp&export=download&confirm=t",
        ),
        (
            "https://drive.google.com/open?id=1AbCdEfGhIjKlMnOp",
            "https://drive.usercontent.google.com/download?id=1AbCdEfGhIjKlMnOp&export=download&confirm=t",
        ),
        (
            "https://docs.google.com/document/d/1ZyXwVuTsRqPoNm/edit",
            "https://docs.google.com/document/d/1ZyXwVuTsRqPoNm/export?format=pdf",
        ),
        ("https://www.dropbox.com/s/abc123/diplomes.pdf?dl=0", "https://www.dropbox.com/s/abc123/diplomes.pdf?dl=1"),
    ],
)
def test_le_lien_de_partage_devient_un_telechargement(url, attendu):
    (lien,) = liens.liens_de_documents(url)
    assert liens.url_de_telechargement(lien) == attendu


def test_onedrive_passe_par_l_api_de_partage():
    (lien,) = liens.liens_de_documents("https://1drv.ms/b/s!AbCdEf")
    assert liens.url_de_telechargement(lien).startswith("https://api.onedrive.com/v1.0/shares/u!")


def _client(gestion) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(gestion), follow_redirects=False)


async def test_un_lien_public_rend_le_document():
    def gestion(requete: httpx.Request) -> httpx.Response:
        assert requete.url.host == "drive.usercontent.google.com"
        return httpx.Response(
            200, content=PDF, headers={"content-disposition": 'attachment; filename="CV Afi.pdf"'}
        )

    (lien,) = liens.liens_de_documents("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view")
    async with _client(gestion) as client:
        nom, donnees = await liens.telecharger(lien, client)
    assert nom == "CV Afi.pdf" and donnees == PDF


async def test_un_lien_prive_est_signale():
    """Google rend une page de connexion, pas le fichier."""

    def gestion(requete):
        return httpx.Response(200, content=b"<!DOCTYPE html><html>Connexion</html>")

    (lien,) = liens.liens_de_documents("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view")
    async with _client(gestion) as client:
        with pytest.raises(liens.LienInaccessible, match="lisible"):
            await liens.telecharger(lien, client)


async def test_une_redirection_hors_des_services_est_refusee():
    """Un lien piégé ne doit pas faire viser au serveur une autre adresse."""

    def gestion(requete):
        return httpx.Response(302, headers={"location": "https://169.254.169.254/latest/meta-data"})

    (lien,) = liens.liens_de_documents("https://www.dropbox.com/s/abc/x.pdf")
    async with _client(gestion) as client:
        with pytest.raises(liens.LienInaccessible, match="pas public"):
            await liens.telecharger(lien, client)


async def test_un_acces_refuse_dit_quoi_demander_au_candidat():
    def gestion(requete):
        return httpx.Response(403)

    (lien,) = liens.liens_de_documents("https://www.dropbox.com/s/abc/x.pdf")
    async with _client(gestion) as client:
        with pytest.raises(liens.LienInaccessible, match="toute personne disposant du lien"):
            await liens.telecharger(lien, client)


async def test_wetransfer_est_a_ouvrir_a_la_main():
    (lien,) = liens.liens_de_documents("https://we.tl/t-AbCdEf")
    with pytest.raises(liens.LienInaccessible, match="à la main"):
        await liens.telecharger(lien)


async def test_un_document_trop_lourd_est_refuse(monkeypatch):
    monkeypatch.setattr(liens, "MAX_OCTETS", 10)

    def gestion(requete):
        return httpx.Response(200, content=PDF)

    (lien,) = liens.liens_de_documents("https://www.dropbox.com/s/abc/x.pdf")
    async with _client(gestion) as client:
        with pytest.raises(liens.LienInaccessible, match="volumineux"):
            await liens.telecharger(lien, client)


def test_les_liens_html_sont_lus_aussi():
    """Un courriel HTML cache l'adresse derrière « mon CV »."""
    message = EmailMessage()
    message["From"] = "Afi <afi@example.tg>"
    message["Subject"] = "Candidature"
    message["Message-ID"] = "<l1@example.tg>"
    message.set_content("Voir mon CV.")
    message.add_alternative(
        '<p>Voir <a href="https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view">mon CV</a>.</p>',
        subtype="html",
    )
    lu = courriel.depuis_message(message.as_bytes())
    assert lu.liens == ["https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view"]


async def test_un_message_fait_de_liens_devient_un_dossier(monkeypatch):
    """Le cas de production : aucune pièce jointe, des documents en lien."""

    async def telecharger(lien, client=None):
        if "PRIVE" in lien.url:
            raise liens.LienInaccessible("pas public")
        return f"{lien.url.rsplit('/', 2)[-2]}.pdf", PDF + lien.url.encode()

    monkeypatch.setattr(liens, "telecharger", telecharger)
    message = courriel.MessageEntrant(
        message_id="<liens@example.tg>",
        expediteur="afi@example.tg",
        nom_expediteur="Afi Dossou",
        sujet="Candidature",
        recu_le=datetime(2026, 11, 2, 9, 0),
        liens=[
            "https://drive.google.com/file/d/1CvAfiDossou00/view",
            "https://drive.google.com/file/d/1DiplomeAfi000/view",
            "https://drive.google.com/file/d/1PRIVEAfi00000/view",
        ],
    )

    class Boite:
        reste = False

        def relever(self, limite=50, exclure=frozenset()):
            return [message]

        def marquer_traite(self, message_id):
            pass

    async with SessionLocal() as db:
        resultat = await courriel.relever(db, Boite())
        await db.commit()
        dossiers = list((await db.execute(select(Candidature))).scalars())
        from app.services.preselection import charger_candidature

        pieces = (await charger_candidature(db, dossiers[0].id)).pieces
    assert resultat.spontanees == 1
    assert resultat.liens_recuperes == 2
    assert len(resultat.liens_inaccessibles) == 1
    assert len(pieces) == 2
