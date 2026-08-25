"""La boîte de candidatures se règle depuis l'application.

Deux propriétés tiennent ce module : le mot de passe ne ressort jamais du
serveur, et un enregistrement sans mot de passe ne déconnecte pas la boîte. La
seconde n'est pas un détail de confort — le formulaire ne pouvant pas
réafficher le secret, l'oublier casserait le relevé à chaque fois qu'on change
le dossier ou l'adresse.
"""

from __future__ import annotations

import pytest

from app.db import SessionLocal
from app.security import hash_password
from app.services import parametres

pytestmark = pytest.mark.anyio

API = "/api/v1"
BOITE = {
    "courriel_actif": True,
    "imap_host": "imap.gmail.com",
    "imap_port": 993,
    "imap_user": "recrutement@kapiconsult.tg",
    "imap_password": "motdepasseapplication",
    "imap_folder": "INBOX",
}


async def creer_recruteur(client) -> dict[str, str]:
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


async def test_sans_configuration_le_releve_est_desactive(client, auth):
    etat = (await client.get(f"{API}/courriel/etat", headers=auth)).json()
    assert etat["actif"] is False

    refus = await client.post(f"{API}/courriel/tester", headers=auth)
    assert refus.status_code == 409
    assert "désactivé" in refus.json()["detail"]


async def test_une_boite_incomplete_dit_ce_qui_manque(client, auth):
    """« Erreur IMAP » n'aide personne ; le nom du champ manquant, si."""
    await client.patch(
        f"{API}/settings",
        json={"courriel_actif": True, "imap_host": "imap.gmail.com"},
        headers=auth,
    )

    refus = await client.post(f"{API}/courriel/tester", headers=auth)
    assert refus.status_code == 409
    detail = refus.json()["detail"]
    assert "l'adresse" in detail and "le mot de passe" in detail
    assert "Paramètres" in detail


async def test_la_boite_se_configure_depuis_l_application(client, auth):
    reponse = await client.patch(f"{API}/settings", json=BOITE, headers=auth)
    assert reponse.status_code == 200, reponse.text

    etat = (await client.get(f"{API}/courriel/etat", headers=auth)).json()
    assert etat["actif"] is True
    assert etat["boite"] == "recrutement@kapiconsult.tg"
    assert etat["dossier"] == "INBOX"


async def test_le_mot_de_passe_ne_ressort_jamais(client, auth):
    await client.patch(f"{API}/settings", json=BOITE, headers=auth)

    corps = (await client.get(f"{API}/settings", headers=auth)).json()
    assert corps["imap_password_defini"] is True
    assert "imap_password" not in corps
    # Ni ailleurs dans la réponse, sous un autre nom.
    assert BOITE["imap_password"] not in str(corps)


async def test_enregistrer_sans_mot_de_passe_ne_le_supprime_pas(client, auth):
    """Le cas courant : on change le dossier, on ne retape pas le secret."""
    await client.patch(f"{API}/settings", json=BOITE, headers=auth)

    await client.patch(
        f"{API}/settings",
        json={**BOITE, "imap_password": "", "imap_folder": "Candidatures"},
        headers=auth,
    )

    async with SessionLocal() as db:
        reglages = await parametres.lire(db)
    assert reglages.imap_password == BOITE["imap_password"]
    assert reglages.imap_folder == "Candidatures"
    assert reglages.courriel_utilisable is True


async def test_les_espaces_du_mot_de_passe_gmail_sont_retires(client, auth):
    """Gmail l'affiche par groupes de quatre ; recopié tel quel, il est refusé."""
    await client.patch(
        f"{API}/settings", json={**BOITE, "imap_password": "abcd efgh ijkl mnop"}, headers=auth
    )

    async with SessionLocal() as db:
        reglages = await parametres.lire(db)
    assert reglages.imap_password == "abcdefghijklmnop"


async def test_desactiver_ferme_le_releve_sans_perdre_la_configuration(client, auth):
    await client.patch(f"{API}/settings", json=BOITE, headers=auth)
    await client.patch(f"{API}/settings", json={"courriel_actif": False}, headers=auth)

    refus = await client.post(f"{API}/courriel/relever", headers=auth)
    assert refus.status_code == 409
    assert "désactivé" in refus.json()["detail"]

    # Les coordonnées sont toujours là : réactiver suffit.
    corps = (await client.get(f"{API}/settings", headers=auth)).json()
    assert corps["imap_user"] == BOITE["imap_user"]
    assert corps["imap_password_defini"] is True


async def test_un_recruteur_ne_peut_pas_changer_la_boite(client, auth):
    """La boîte donne accès à tous les dossiers reçus : réservé aux admins."""
    entetes = await creer_recruteur(client)

    refus = await client.patch(f"{API}/settings", json=BOITE, headers=entetes)
    assert refus.status_code == 403


async def test_la_modification_de_la_boite_est_journalisee_sans_le_secret(client, auth):
    from sqlalchemy import select

    from app.models import AuditLog

    await client.patch(f"{API}/settings", json=BOITE, headers=auth)

    async with SessionLocal() as db:
        entrees = (await db.execute(select(AuditLog))).scalars().all()
    journal = [e for e in entrees if e.action == "parametres.update"]
    assert journal, "la modification doit laisser une trace"
    # Les noms des clés changées, jamais leurs valeurs.
    assert "imap_password" in journal[0].details["reglages"]
    assert BOITE["imap_password"] not in str(journal[0].details)
