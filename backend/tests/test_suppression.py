from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Avis, Candidat, Candidature, Client, Mandat, Poste

pytestmark = pytest.mark.anyio

API = "/api/v1"
PDF = b"%PDF-1.4\n" + b"0" * 400


async def monter(client, auth, *, avec_candidature: bool = False) -> dict:
    ids = {}
    ids["client"] = (
        await client.post(f"{API}/clients", json={"nom": "Client à supprimer"}, headers=auth)
    ).json()["id"]
    ids["mandat"] = (
        await client.post(
            f"{API}/mandats", json={"client_id": ids["client"], "intitule": "Mandat"}, headers=auth
        )
    ).json()["id"]
    ids["poste"] = (
        await client.post(
            f"{API}/mandats/{ids['mandat']}/postes",
            json={"intitule": "Poste", "niveau_min": 3, "pieces_requises": ["CV"]},
            headers=auth,
        )
    ).json()["id"]
    ids["avis"] = (
        await client.post(
            f"{API}/postes/{ids['poste']}/avis",
            json={"date_cloture": "2026-12-31"},
            headers=auth,
        )
    ).json()["id"]

    if avec_candidature:
        reponse = await client.post(
            f"{API}/postes/{ids['poste']}/candidatures/depot-multiple",
            files=[("fichiers", ("cv.pdf", PDF, "application/pdf"))],
            headers=auth,
        )
        assert reponse.status_code == 201, reponse.text
    return ids


async def archiver_client(client, auth, client_id):
    reponse = await client.post(f"{API}/clients/{client_id}/archiver", headers=auth)
    assert reponse.status_code == 200, reponse.text


async def archiver_mandat(client, auth, mandat_id):
    reponse = await client.post(f"{API}/mandats/{mandat_id}/archiver", headers=auth)
    assert reponse.status_code == 200, reponse.text


async def test_supprimer_sans_archiver_est_refuse(client, auth):
    """Deux gestes pour une action irreversible : archiver, puis effacer."""
    ids = await monter(client, auth)

    refus = await client.request("DELETE", f"{API}/clients/{ids['client']}", headers=auth)
    assert refus.status_code == 409
    assert "archives" in refus.json()["detail"].lower()

    async with SessionLocal() as db:
        assert len((await db.execute(select(Client))).scalars().all()) == 1


async def test_supprimer_un_client_vide(client, auth):
    """Une erreur de saisie se corrige sans cérémonie."""
    ids = await monter(client, auth)
    await archiver_client(client, auth, ids["client"])

    reponse = await client.request("DELETE", f"{API}/clients/{ids['client']}", headers=auth)
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["candidatures"] == 0

    async with SessionLocal() as db:
        assert (await db.execute(select(Client))).scalars().all() == []
        # La cascade emporte tout le sous-arbre.
        assert (await db.execute(select(Mandat))).scalars().all() == []
        assert (await db.execute(select(Poste))).scalars().all() == []
        assert (await db.execute(select(Avis))).scalars().all() == []


async def test_un_client_avec_candidatures_demande_confirmation(client, auth):
    ids = await monter(client, auth, avec_candidature=True)
    await archiver_client(client, auth, ids["client"])

    refus = await client.request("DELETE", f"{API}/clients/{ids['client']}", headers=auth)
    assert refus.status_code == 409
    detail = refus.json()["detail"]
    # Le message dit ce qui serait perdu, pas seulement que c'est refusé.
    assert "1 candidature(s)" in detail
    assert "confirmer=true" in detail

    async with SessionLocal() as db:
        assert len((await db.execute(select(Candidature))).scalars().all()) == 1


async def test_la_confirmation_supprime_tout_le_sous_arbre(client, auth):
    ids = await monter(client, auth, avec_candidature=True)
    await archiver_client(client, auth, ids["client"])

    reponse = await client.request(
        "DELETE", f"{API}/clients/{ids['client']}?confirmer=true", headers=auth
    )
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["candidatures"] == 1

    # L'état civil ne survit pas sans candidature : le conserver serait une
    # rétention de données personnelles devenue sans objet.
    assert reponse.json()["candidats_supprimes"] == 1

    async with SessionLocal() as db:
        assert (await db.execute(select(Client))).scalars().all() == []
        assert (await db.execute(select(Candidature))).scalars().all() == []
        assert (await db.execute(select(Candidat))).scalars().all() == []


async def test_un_candidat_encore_rattache_ailleurs_est_conserve(client, auth):
    """Une même personne peut postuler à plusieurs postes : seul l'orphelin part."""
    premier = await monter(client, auth, avec_candidature=True)

    # Un second client, avec sa propre candidature.
    second_client = (
        await client.post(f"{API}/clients", json={"nom": "Autre client"}, headers=auth)
    ).json()["id"]
    second_mandat = (
        await client.post(
            f"{API}/mandats", json={"client_id": second_client, "intitule": "M2"}, headers=auth
        )
    ).json()["id"]
    second_poste = (
        await client.post(
            f"{API}/mandats/{second_mandat}/postes",
            json={"intitule": "P2", "niveau_min": 3},
            headers=auth,
        )
    ).json()["id"]
    await client.post(
        f"{API}/postes/{second_poste}/candidatures/depot-multiple",
        files=[("fichiers", ("autre.pdf", PDF, "application/pdf"))],
        headers=auth,
    )

    await archiver_client(client, auth, premier["client"])
    await client.request(
        "DELETE", f"{API}/clients/{premier['client']}?confirmer=true", headers=auth
    )

    async with SessionLocal() as db:
        restants = (await db.execute(select(Candidat))).scalars().all()
        assert len(restants) == 1
        assert len((await db.execute(select(Candidature))).scalars().all()) == 1


async def test_supprimer_un_mandat_laisse_le_client(client, auth):
    ids = await monter(client, auth)
    await archiver_mandat(client, auth, ids["mandat"])

    reponse = await client.request("DELETE", f"{API}/mandats/{ids['mandat']}", headers=auth)
    assert reponse.status_code == 200, reponse.text

    async with SessionLocal() as db:
        assert len((await db.execute(select(Client))).scalars().all()) == 1
        assert (await db.execute(select(Mandat))).scalars().all() == []


async def test_un_mandat_avec_candidatures_demande_confirmation(client, auth):
    ids = await monter(client, auth, avec_candidature=True)
    await archiver_mandat(client, auth, ids["mandat"])
    refus = await client.request("DELETE", f"{API}/mandats/{ids['mandat']}", headers=auth)
    assert refus.status_code == 409

    ok = await client.request(
        "DELETE", f"{API}/mandats/{ids['mandat']}?confirmer=true", headers=auth
    )
    assert ok.status_code == 200


async def test_supprimer_un_client_inexistant(client, auth):
    reponse = await client.request("DELETE", f"{API}/clients/inconnu", headers=auth)
    assert reponse.status_code == 404


async def test_la_suppression_est_journalisee(client, auth):
    from app.models import AuditLog

    ids = await monter(client, auth)
    await archiver_client(client, auth, ids["client"])
    await client.request("DELETE", f"{API}/clients/{ids['client']}", headers=auth)

    async with SessionLocal() as db:
        actions = [
            a.action for a in (await db.execute(select(AuditLog))).scalars() if "delete" in a.action
        ]
        assert "client.delete" in actions


async def test_archiver_sort_des_listes_sans_rien_effacer(client, auth):
    """L'action normale : le dossier disparaît des listes, pas de la base."""
    ids = await monter(client, auth, avec_candidature=True)

    reponse = await client.post(f"{API}/mandats/{ids['mandat']}/archiver", headers=auth)
    assert reponse.status_code == 200
    assert reponse.json()["archive"] is True

    # Absent de la liste par défaut...
    liste = (await client.get(f"{API}/mandats", headers=auth)).json()
    assert all(m["id"] != ids["mandat"] for m in liste)

    # ...mais présent quand on les demande, et toujours consultable par son lien.
    avec = (await client.get(f"{API}/mandats?archives=true", headers=auth)).json()
    assert any(m["id"] == ids["mandat"] for m in avec)
    detail = await client.get(f"{API}/mandats/{ids['mandat']}", headers=auth)
    assert detail.status_code == 200

    async with SessionLocal() as db:
        # Rien n'a été effacé : avis, poste et candidature sont intacts.
        assert len((await db.execute(select(Avis))).scalars().all()) == 1
        assert len((await db.execute(select(Poste))).scalars().all()) == 1
        assert len((await db.execute(select(Candidature))).scalars().all()) == 1


async def test_desarchiver_le_remet_dans_les_listes(client, auth):
    ids = await monter(client, auth)
    await client.post(f"{API}/mandats/{ids['mandat']}/archiver", headers=auth)
    await client.post(f"{API}/mandats/{ids['mandat']}/desarchiver", headers=auth)

    liste = (await client.get(f"{API}/mandats", headers=auth)).json()
    assert any(m["id"] == ids["mandat"] for m in liste)


async def test_archiver_un_client_le_masque_aussi(client, auth):
    ids = await monter(client, auth)
    await client.post(f"{API}/clients/{ids['client']}/archiver", headers=auth)

    assert all(c["id"] != ids["client"] for c in (await client.get(f"{API}/clients", headers=auth)).json())
    avec = (await client.get(f"{API}/clients?archives=true", headers=auth)).json()
    assert any(c["id"] == ids["client"] for c in avec)


async def test_le_refus_de_suppression_rappelle_l_archivage(client, auth):
    """Archive et portant des dossiers : la confirmation reste exigee,
    et le message rappelle que l'archivage suffit souvent."""
    ids = await monter(client, auth, avec_candidature=True)
    await archiver_mandat(client, auth, ids["mandat"])

    refus = await client.request("DELETE", f"{API}/mandats/{ids['mandat']}", headers=auth)
    assert refus.status_code == 409
    assert "archivage conserve" in refus.json()["detail"].lower()
