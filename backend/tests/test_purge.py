"""Purge des fichiers d'un mandat archivé.

Le point à tenir : purger efface les documents et rien d'autre. Ce qui justifie
une décision des mois plus tard — le parcours saisi, la note et son détail, les
motifs d'élimination — ne dépend pas du PDF, et une grille recalculée après
purge doit donner exactement le même résultat.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import PieceCandidature

pytestmark = pytest.mark.anyio

API = "/api/v1"
PDF = b"%PDF-1.4\n" + b"0" * 4000


async def monter(client, auth) -> dict:
    """Un mandat avec un poste, un avis et un dossier déposé."""
    ids = {}
    ids["client"] = (
        await client.post(f"{API}/clients", json={"nom": "Client"}, headers=auth)
    ).json()["id"]
    ids["mandat"] = (
        await client.post(
            f"{API}/mandats",
            json={"client_id": ids["client"], "intitule": "Mandat"},
            headers=auth,
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

    depot = await client.post(
        f"{API}/postes/{ids['poste']}/candidatures/depot-multiple",
        files=[("fichiers", ("cv.pdf", PDF, "application/pdf"))],
        headers=auth,
    )
    assert depot.status_code == 201, depot.text
    return ids


async def test_purger_un_mandat_en_cours_est_refuse(client, auth):
    """Tant que le recrutement tourne, les pièces servent encore."""
    ids = await monter(client, auth)

    refus = await client.post(f"{API}/mandats/{ids['mandat']}/purge", headers=auth)
    assert refus.status_code == 409
    assert "archivez" in refus.json()["detail"].lower()

    # Rien n'a bougé.
    async with SessionLocal() as db:
        pieces = (await db.execute(select(PieceCandidature))).scalars().all()
        assert all(p.chemin_stockage is not None for p in pieces)


async def test_l_estimation_ne_supprime_rien(client, auth):
    ids = await monter(client, auth)

    estimation = (await client.get(f"{API}/mandats/{ids['mandat']}/purge", headers=auth)).json()
    assert estimation["fichiers"] == 1
    assert estimation["candidatures"] == 1

    async with SessionLocal() as db:
        pieces = (await db.execute(select(PieceCandidature))).scalars().all()
        assert all(p.chemin_stockage is not None for p in pieces)


async def test_la_purge_efface_les_fichiers_et_garde_les_dossiers(client, auth):
    ids = await monter(client, auth)
    await client.post(f"{API}/mandats/{ids['mandat']}/archiver", headers=auth)

    resultat = await client.post(f"{API}/mandats/{ids['mandat']}/purge", headers=auth)
    assert resultat.status_code == 200, resultat.text
    assert resultat.json()["fichiers"] == 1

    async with SessionLocal() as db:
        pieces = (await db.execute(select(PieceCandidature))).scalars().all()
        # La ligne survit : on sait toujours quelle pièce avait été reçue.
        assert len(pieces) == 1
        assert pieces[0].chemin_stockage is None
        assert pieces[0].purge_le is not None
        assert pieces[0].taille_octets == len(PDF)

    # Le dossier reste consultable.
    candidatures = await client.get(
        f"{API}/postes/{ids['poste']}/candidatures", headers=auth
    )
    assert candidatures.status_code == 200
    assert candidatures.json()["total"] == 1


async def test_la_grille_est_identique_avant_et_apres_purge(client, auth):
    """La complétude se juge sur la pièce reçue, pas sur le fichier conservé."""
    ids = await monter(client, auth)

    await client.post(f"{API}/postes/{ids['poste']}/evaluer", headers=auth)
    avant = (await client.get(f"{API}/postes/{ids['poste']}/grille", headers=auth)).json()

    await client.post(f"{API}/mandats/{ids['mandat']}/archiver", headers=auth)
    await client.post(f"{API}/mandats/{ids['mandat']}/purge", headers=auth)

    await client.post(f"{API}/postes/{ids['poste']}/evaluer", headers=auth)
    apres = (await client.get(f"{API}/postes/{ids['poste']}/grille", headers=auth)).json()

    for champ in (
        "nombre_candidatures",
        "nombre_preselectionnes",
        "nombre_elimines",
        "nombre_a_verifier",
        "total_max",
        "seuil",
    ):
        assert avant[champ] == apres[champ], champ


async def test_purger_deux_fois_ne_compte_pas_deux_fois(client, auth):
    ids = await monter(client, auth)
    await client.post(f"{API}/mandats/{ids['mandat']}/archiver", headers=auth)

    premier = (await client.post(f"{API}/mandats/{ids['mandat']}/purge", headers=auth)).json()
    second = (await client.post(f"{API}/mandats/{ids['mandat']}/purge", headers=auth)).json()

    assert premier["fichiers"] == 1
    assert second["fichiers"] == 0


async def test_la_purge_est_journalisee(client, auth):
    from app.models import AuditLog

    ids = await monter(client, auth)
    await client.post(f"{API}/mandats/{ids['mandat']}/archiver", headers=auth)
    await client.post(f"{API}/mandats/{ids['mandat']}/purge", headers=auth)

    async with SessionLocal() as db:
        actions = [a.action for a in (await db.execute(select(AuditLog))).scalars()]
        assert "mandat.purge" in actions
