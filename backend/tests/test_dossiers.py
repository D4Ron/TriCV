"""Les dossiers hors de la grille : les emporter en lot, rattacher ceux sans poste.

Deux demandes des RH. Emporter plusieurs dossiers d'un coup — pour imprimer,
ou sur une clé USB — sans ouvrir chaque candidat. Et ranger sous un poste un
dossier arrivé par courriel sans que l'objet nomme d'avis : il devenait une
candidature spontanée dont personne ne pouvait ouvrir les pièces.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime

import pytest

from app.db import SessionLocal
from app.services import courriel

pytestmark = pytest.mark.anyio

API = "/api/v1"
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def pdf(marque: bytes) -> bytes:
    return PDF + marque


async def monter_poste(client, auth, intitule: str = "Directeur") -> str:
    client_id = (
        await client.post(f"{API}/clients", json={"nom": "Dogta"}, headers=auth)
    ).json()["id"]
    mandat_id = (
        await client.post(
            f"{API}/mandats", json={"client_id": client_id, "intitule": "M"}, headers=auth
        )
    ).json()["id"]
    return (
        await client.post(
            f"{API}/mandats/{mandat_id}/postes",
            json={"intitule": intitule, "pieces_requises": ["CV"]},
            headers=auth,
        )
    ).json()["id"]


async def deposer(client, auth, poste_id: str, fichiers: list[tuple[str, bytes]]) -> dict:
    reponse = await client.post(
        f"{API}/postes/{poste_id}/candidatures/depot-multiple",
        data={"depouiller_aussitot": "false"},
        files=[("fichiers", (nom, donnees, "application/pdf")) for nom, donnees in fichiers],
        headers=auth,
    )
    assert reponse.status_code == 201, reponse.text
    return reponse.json()


async def spontanee(expediteur: str = "kwami@example.tg", nom: str = "Kwami Dogbe") -> str:
    """Un courriel sans référence d'avis, tel que le relevé le range."""
    message = courriel.MessageEntrant(
        message_id=f"<{expediteur}>",
        expediteur=expediteur,
        nom_expediteur=nom,
        sujet="Candidature",
        recu_le=datetime(2026, 10, 20, 9, 0),
        pieces=[courriel.PieceJointe(nom="CV Kwami.pdf", donnees=pdf(b"k"))],
    )
    async with SessionLocal() as db:
        candidature = await courriel.creer_depuis_message(db, message, None)
        await db.commit()
        return candidature.id


# --- l'export en lot ----------------------------------------------------------


async def test_les_dossiers_d_un_poste_se_listent_par_portee(client, auth):
    poste_id = await monter_poste(client, auth)
    await deposer(
        client, auth, poste_id,
        [("KODJO_Amina_CV.pdf", pdf(b"a")), ("MENSAH_Afiwa_CV.pdf", pdf(b"b"))],
    )
    lignes = (
        await client.get(f"{API}/postes/{poste_id}/dossiers?portee=tous", headers=auth)
    ).json()
    assert len(lignes) == 2
    assert all(l["pieces_disponibles"] == 1 for l in lignes)

    refus = await client.get(f"{API}/postes/{poste_id}/dossiers?portee=nimporte", headers=auth)
    assert refus.status_code == 422


async def test_l_archive_rend_les_pieces_telles_que_recues(client, auth):
    poste_id = await monter_poste(client, auth)
    await deposer(
        client, auth, poste_id,
        [
            ("KODJO_Amina_CV.pdf", pdf(b"cv-a")),
            ("KODJO_Amina_lettre.pdf", pdf(b"lm-a")),
            ("MENSAH_Afiwa_CV.pdf", pdf(b"cv-b")),
        ],
    )
    ids = [
        l["candidature_id"]
        for l in (await client.get(f"{API}/postes/{poste_id}/dossiers", headers=auth)).json()
    ]

    reponse = await client.post(
        f"{API}/postes/{poste_id}/dossiers.zip", json={"candidature_ids": ids}, headers=auth
    )
    assert reponse.status_code == 200, reponse.text
    assert reponse.headers["content-type"] == "application/zip"
    assert ".zip" in reponse.headers["content-disposition"]

    archive = zipfile.ZipFile(io.BytesIO(reponse.content))
    noms = archive.namelist()
    # Un dossier par candidat, dans l'ordre alphabétique, plus le sommaire.
    assert "000 - Sommaire.csv" in noms
    dossiers = sorted({n.split("/")[0] for n in noms if "/" in n})
    assert len(dossiers) == 2
    assert dossiers[0].startswith("001 - KODJO")
    assert dossiers[1].startswith("002 - MENSAH")
    # Les octets reçus, pas une version remise en forme.
    contenus = {archive.read(n) for n in noms if "/" in n}
    assert pdf(b"cv-a") in contenus and pdf(b"lm-a") in contenus and pdf(b"cv-b") in contenus

    sommaire = archive.read("000 - Sommaire.csv").decode("utf-8-sig")
    assert "KODJO" in sommaire and "MENSAH" in sommaire


async def test_une_selection_partielle_n_emporte_qu_elle(client, auth):
    poste_id = await monter_poste(client, auth)
    await deposer(
        client, auth, poste_id,
        [("KODJO_Amina_CV.pdf", pdf(b"a")), ("MENSAH_Afiwa_CV.pdf", pdf(b"b"))],
    )
    lignes = (await client.get(f"{API}/postes/{poste_id}/dossiers", headers=auth)).json()
    un = [lignes[0]["candidature_id"]]

    archive = zipfile.ZipFile(
        io.BytesIO(
            (
                await client.post(
                    f"{API}/postes/{poste_id}/dossiers.zip",
                    json={"candidature_ids": un},
                    headers=auth,
                )
            ).content
        )
    )
    assert len({n.split("/")[0] for n in archive.namelist() if "/" in n}) == 1


async def test_un_dossier_d_un_autre_poste_est_refuse(client, auth):
    poste_a = await monter_poste(client, auth, "Directeur")
    poste_b = await monter_poste(client, auth, "Comptable")
    await deposer(client, auth, poste_b, [("MENSAH_Afiwa_CV.pdf", pdf(b"b"))])
    autre = (await client.get(f"{API}/postes/{poste_b}/dossiers", headers=auth)).json()

    refus = await client.post(
        f"{API}/postes/{poste_a}/dossiers.zip",
        json={"candidature_ids": [autre[0]["candidature_id"]]},
        headers=auth,
    )
    assert refus.status_code == 404


async def test_l_export_passe_au_journal(client, auth):
    from sqlalchemy import select

    from app.models import AuditLog

    poste_id = await monter_poste(client, auth)
    await deposer(client, auth, poste_id, [("KODJO_Amina_CV.pdf", pdf(b"a"))])
    ids = [l["candidature_id"] for l in (await client.get(f"{API}/postes/{poste_id}/dossiers", headers=auth)).json()]
    await client.post(f"{API}/postes/{poste_id}/dossiers.zip", json={"candidature_ids": ids}, headers=auth)

    async with SessionLocal() as db:
        actions = (await db.execute(select(AuditLog.action))).scalars().all()
    assert "poste.export_dossiers" in actions


# --- les dossiers sans poste ---------------------------------------------------


async def test_un_courriel_sans_avis_se_retrouve_avec_ses_pieces(client, auth):
    candidature_id = await spontanee()

    liste = (await client.get(f"{API}/dossiers/sans-poste", headers=auth)).json()
    assert [c["id"] for c in liste] == [candidature_id]
    dossier = liste[0]
    assert dossier["email"] == "kwami@example.tg"
    assert dossier["pieces"][0]["nom_fichier"] == "CV Kwami.pdf"
    assert dossier["pieces"][0]["disponible"] is True

    # Et la pièce s'ouvre.
    piece = await client.get(
        f"{API}/candidatures/{candidature_id}/pieces/{dossier['pieces'][0]['id']}", headers=auth
    )
    assert piece.status_code == 200
    assert piece.content == pdf(b"k")


async def test_rattacher_range_le_dossier_sous_le_poste_et_le_note(client, auth):
    poste_id = await monter_poste(client, auth)
    candidature_id = await spontanee()

    postes = (await client.get(f"{API}/postes-actifs", headers=auth)).json()
    assert poste_id in [p["id"] for p in postes]

    reponse = await client.post(
        f"{API}/candidatures/{candidature_id}/rattacher", json={"poste_id": poste_id}, headers=auth
    )
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["poste_id"] == poste_id

    # Il quitte la liste des sans-poste et rejoint celle du poste.
    assert (await client.get(f"{API}/dossiers/sans-poste", headers=auth)).json() == []
    page = (await client.get(f"{API}/postes/{poste_id}/candidatures", headers=auth)).json()
    assert page["total"] == 1


async def test_un_dossier_mal_range_change_de_poste(client, auth):
    poste_a = await monter_poste(client, auth, "Directeur")
    poste_b = await monter_poste(client, auth, "Comptable")
    await deposer(client, auth, poste_a, [("KODJO_Amina_CV.pdf", pdf(b"a"))])
    candidature_id = (await client.get(f"{API}/postes/{poste_a}/dossiers", headers=auth)).json()[0]["candidature_id"]

    reponse = await client.post(
        f"{API}/candidatures/{candidature_id}/rattacher", json={"poste_id": poste_b}, headers=auth
    )
    assert reponse.status_code == 200, reponse.text
    assert (await client.get(f"{API}/postes/{poste_a}/candidatures", headers=auth)).json()["total"] == 0
    assert (await client.get(f"{API}/postes/{poste_b}/candidatures", headers=auth)).json()["total"] == 1


async def test_rattacher_sous_le_meme_poste_est_refuse(client, auth):
    poste_id = await monter_poste(client, auth)
    candidature_id = await spontanee()
    await client.post(
        f"{API}/candidatures/{candidature_id}/rattacher", json={"poste_id": poste_id}, headers=auth
    )
    refus = await client.post(
        f"{API}/candidatures/{candidature_id}/rattacher", json={"poste_id": poste_id}, headers=auth
    )
    assert refus.status_code == 409


async def test_deux_dossiers_de_la_meme_personne_ne_se_confondent_pas(client, auth):
    """Le même candidat déjà présent sous ce poste : la base l'interdit, l'écran le dit."""
    poste_id = await monter_poste(client, auth)
    premier = await spontanee()
    await client.post(
        f"{API}/candidatures/{premier}/rattacher", json={"poste_id": poste_id}, headers=auth
    )
    async with SessionLocal() as db:
        from app.models import Candidature

        candidat_id = (await db.get(Candidature, premier)).candidat_id
        from app.models import Candidature as C

        second = C(candidat_id=candidat_id, poste_id=None, spontanee=True)
        db.add(second)
        await db.commit()
        second_id = second.id

    refus = await client.post(
        f"{API}/candidatures/{second_id}/rattacher", json={"poste_id": poste_id}, headers=auth
    )
    assert refus.status_code == 409
    assert "déjà un dossier" in refus.json()["detail"]


async def test_un_poste_inconnu_est_refuse(client, auth):
    candidature_id = await spontanee()
    refus = await client.post(
        f"{API}/candidatures/{candidature_id}/rattacher", json={"poste_id": "inconnu"}, headers=auth
    )
    assert refus.status_code == 404


async def test_le_rattachement_passe_au_journal(client, auth):
    from sqlalchemy import select

    from app.models import AuditLog

    poste_id = await monter_poste(client, auth)
    candidature_id = await spontanee()
    await client.post(
        f"{API}/candidatures/{candidature_id}/rattacher", json={"poste_id": poste_id}, headers=auth
    )
    async with SessionLocal() as db:
        entrees = (
            await db.execute(select(AuditLog).where(AuditLog.action == "candidature.rattachement"))
        ).scalars().all()
    assert entrees and entrees[0].details == {"de": None, "vers": poste_id}
