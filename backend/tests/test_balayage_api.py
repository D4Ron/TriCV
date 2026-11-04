"""Ce que le balayage de toute l'API a trouvé : chaque panne reste corrigée."""

from __future__ import annotations

import pytest

from app.db import SessionLocal
from app.models.recrutement import Client, Mandat, Poste

pytestmark = pytest.mark.anyio

API = "/api/v1"


async def deux_mandats() -> tuple[str, str]:
    async with SessionLocal() as db:
        client = Client(nom="Client fictif")
        db.add(client)
        await db.flush()
        un = Mandat(client_id=client.id, intitule="Premier")
        autre = Mandat(client_id=client.id, intitule="Second")
        db.add_all([un, autre])
        await db.flush()
        poste = Poste(mandat_id=autre.id, intitule="Comptable", niveau_min=3)
        db.add(poste)
        await db.commit()
        return un.id, poste.id


async def test_une_session_sans_critere_se_cree(client, auth):
    reponse = await client.post(
        f"{API}/sessions",
        json={"title": "Essai", "position": "Comptable", "criteria": []},
        headers=auth,
    )
    assert reponse.status_code == 201, reponse.text


async def test_le_fil_d_un_client_refuse_le_poste_d_un_autre_mandat(client, auth):
    mandat, poste_ailleurs = await deux_mandats()
    corps = {"type_echange": "MESSAGE", "objet": "Essai", "corps": "Essai", "poste_id": poste_ailleurs}

    reponse = await client.post(f"{API}/mandats/{mandat}/echanges", json=corps, headers=auth)
    assert reponse.status_code == 404

    inconnu = await client.post(
        f"{API}/mandats/{mandat}/echanges", json={**corps, "poste_id": "inconnu"}, headers=auth
    )
    assert inconnu.status_code == 404


async def test_un_modele_rattache_a_rien_est_refuse_proprement(client, auth):
    reponse = await client.post(
        f"{API}/modeles-documents",
        data={"libelle": "Modèle", "usage": "RAPPORT", "mandat_id": "inconnu"},
        files={"fichier": ("modele.pdf", b"%PDF-1.4 essai", "application/pdf")},
        headers=auth,
    )
    assert reponse.status_code in (404, 422), reponse.text
