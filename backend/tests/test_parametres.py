from __future__ import annotations

import pytest

from app.db import SessionLocal
from app.security import hash_password
from app.services import parametres

pytestmark = pytest.mark.anyio

API = "/api/v1"


async def creer_recruteur(client) -> dict[str, str]:
    """Un compte non administrateur, pour vérifier la limite de droits."""
    from app.models import User, UserRole

    async with SessionLocal() as db:
        db.add(
            User(
                email="recruteur@tricv.example",
                password_hash=hash_password("password123"),
                full_name="Recruteur",
                role=UserRole.RECRUITER,
            )
        )
        await db.commit()

    jeton = (
        await client.post(
            f"{API}/auth/login",
            json={"email": "recruteur@tricv.example", "password": "password123"},
        )
    ).json()["access_token"]
    return {"Authorization": f"Bearer {jeton}"}


async def test_les_reglages_par_defaut_viennent_du_fichier(client, auth):
    reponse = await client.get(f"{API}/settings", headers=auth)
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["seuil_preselection_defaut"] == 20.0
    assert corps["redact_demographics"] is True
    # Les champs de déploiement restent exposés, en lecture.
    assert corps["llm_provider"]
    assert "storage_backend" in corps


async def test_modifier_un_reglage_le_rend_effectif(client, auth):
    reponse = await client.patch(
        f"{API}/settings",
        json={"seuil_preselection_defaut": 18.5},
        headers=auth,
    )
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["seuil_preselection_defaut"] == 18.5

    # Persisté : une relecture le retrouve.
    relu = (await client.get(f"{API}/settings", headers=auth)).json()
    assert relu["seuil_preselection_defaut"] == 18.5


async def test_le_seuil_par_defaut_s_applique_aux_nouveaux_postes(client, auth):
    """Le réglage n'est pas décoratif : il change ce que produit l'application."""
    await client.patch(
        f"{API}/settings", json={"seuil_preselection_defaut": 15.0}, headers=auth
    )

    client_id = (
        await client.post(f"{API}/clients", json={"nom": "C"}, headers=auth)
    ).json()["id"]
    mandat_id = (
        await client.post(
            f"{API}/mandats", json={"client_id": client_id, "intitule": "M"}, headers=auth
        )
    ).json()["id"]
    poste = (
        await client.post(
            f"{API}/mandats/{mandat_id}/postes", json={"intitule": "P"}, headers=auth
        )
    ).json()

    assert poste["seuil_preselection"] == 15.0
    assert poste["seuil_nominal"] == 15.0


async def test_aucun_plafond_de_taille_n_est_reglable(client, auth):
    """La taille des pièces n'est plus une politique du cabinet.

    Le stockage se maîtrise en purgeant les mandats archivés, pas en refusant
    des dossiers à l'arrivée. Ce qui reste exposé est le garde-fou anti-abus
    du formulaire public, en lecture seule : un ancien réglage envoyé par
    mégarde ne doit pas pouvoir l'abaisser.
    """
    from app.services import uploads

    avant = (await client.get(f"{API}/settings", headers=auth)).json()["max_upload_mb"]
    assert avant == uploads.PLAFOND_ABSOLU_MO

    await client.patch(f"{API}/settings", json={"taille_max_mo_defaut": 3}, headers=auth)

    apres = (await client.get(f"{API}/settings", headers=auth)).json()["max_upload_mb"]
    assert apres == uploads.PLAFOND_ABSOLU_MO


async def test_l_inscription_libre_se_pilote_depuis_les_reglages(client, auth):
    avant = (await client.get(f"{API}/auth/signup-config")).json()
    assert avant["enabled"] is False

    await client.patch(f"{API}/settings", json={"allow_self_registration": True}, headers=auth)
    apres = (await client.get(f"{API}/auth/signup-config")).json()
    assert apres["enabled"] is True

    # Et le dépôt d'inscription suit le même réglage.
    inscription = await client.post(
        f"{API}/auth/signup",
        json={
            "email": "nouveau@example.com",
            "password": "un-bon-mot-de-passe",
            "full_name": "Nouveau",
        },
    )
    assert inscription.status_code == 201, inscription.text


async def test_un_recruteur_ne_peut_pas_modifier_les_reglages(client, auth):
    """Ces réglages valent pour tout le cabinet : ils restent aux admins."""
    entetes = await creer_recruteur(client)

    lecture = await client.get(f"{API}/settings", headers=entetes)
    assert lecture.status_code == 200

    ecriture = await client.patch(
        f"{API}/settings", json={"seuil_preselection_defaut": 5}, headers=entetes
    )
    assert ecriture.status_code == 403


async def test_un_reglage_hors_bornes_est_refuse(client, auth):
    assert (
        await client.patch(
            f"{API}/settings", json={"seuil_preselection_defaut": 500}, headers=auth
        )
    ).status_code == 422
    assert (
        await client.patch(
            f"{API}/settings", json={"seuil_preselection_defaut": -3}, headers=auth
        )
    ).status_code == 422


async def test_une_valeur_illisible_en_base_retombe_sur_le_defaut(client, auth):
    """Une base abîmée ne doit pas empêcher l'application de fonctionner."""
    async with SessionLocal() as db:
        db.add(parametres.Parametre(cle=parametres.SEUIL_DEFAUT, valeur="pas un nombre"))
        await db.commit()

        reglages = await parametres.lire(db)
        assert reglages.seuil_preselection_defaut == 20.0


async def test_la_modification_est_journalisee(client, auth):
    from sqlalchemy import select

    from app.models import AuditLog

    await client.patch(
        f"{API}/settings", json={"seuil_preselection_defaut": 22}, headers=auth
    )

    async with SessionLocal() as db:
        actions = [a.action for a in (await db.execute(select(AuditLog))).scalars()]
        assert "parametres.update" in actions
