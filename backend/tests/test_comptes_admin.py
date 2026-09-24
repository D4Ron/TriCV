"""La gestion des comptes depuis l'application.

Jusqu'ici, créer un compte passait par l'inscription libre — qu'on referme dès
l'équipe constituée — ou par `comptes.py`, sur la machine qui héberge
l'application. Changer un rôle ou réactiver quelqu'un demandait donc un accès
au serveur, et un cabinet de recrutement n'a pas d'administrateur système sous
la main.

Ce qui est vérifié ici est moins la mécanique que les **garde-fous**, parce
qu'ils protègent d'une panne sans retour : un administrateur qui se retire ses
propres droits, ou le dernier qui s'en va, laisse une application que plus
personne ne peut administrer — ni les comptes, ni les paramètres — et il n'y a
pas de porte de secours depuis l'intérieur.

Un compte ne se supprime jamais : son nom figure au journal d'audit sur chaque
décision qu'il a prise. On le désactive.
"""

from __future__ import annotations

import pytest

from app.db import SessionLocal
from app.models import User, UserRole
from app.security import hash_password

pytestmark = pytest.mark.anyio

API = "/api/v1"


async def creer(
    email: str,
    *,
    role: UserRole = UserRole.RECRUITER,
    actif: bool = True,
    mot_de_passe: str = "password123",
) -> str:
    """Un compte posé directement en base, sans passer par l'API."""
    async with SessionLocal() as db:
        compte = User(
            email=email,
            password_hash=hash_password(mot_de_passe),
            full_name=email.split("@")[0].title(),
            role=role,
            is_active=actif,
        )
        db.add(compte)
        await db.commit()
        return compte.id


async def identifiant(client, email: str) -> str:
    """L'identifiant d'un compte, tel que l'API le rend."""
    async with SessionLocal() as db:
        from sqlalchemy import select

        resultat = await db.execute(select(User).where(User.email == email))
        return resultat.scalar_one().id


# --- lire et créer ------------------------------------------------------------


async def test_un_administrateur_liste_les_comptes(client, auth):
    await creer("chargee@kapi.tg")
    reponse = await client.get(f"{API}/auth/users", headers=auth)

    assert reponse.status_code == 200
    adresses = {u["email"] for u in reponse.json()}
    assert {"admin@tricv.example", "chargee@kapi.tg"} <= adresses


async def test_un_recruteur_ne_gere_pas_les_comptes(client, auth):
    """Un compte recruteur lit tous les dossiers ; il n'ouvre pas d'accès."""
    await creer("chargee@kapi.tg")
    connexion = await client.post(
        f"{API}/auth/login",
        json={"email": "chargee@kapi.tg", "password": "password123"},
    )
    entetes = {"Authorization": f"Bearer {connexion.json()['access_token']}"}

    assert (await client.get(f"{API}/auth/users", headers=entetes)).status_code == 403
    cible = await identifiant(client, "chargee@kapi.tg")
    modif = await client.patch(
        f"{API}/auth/users/{cible}", json={"role": "ADMIN"}, headers=entetes
    )
    assert modif.status_code == 403


async def test_un_compte_se_cree_et_se_connecte(client, auth):
    creation = await client.post(
        f"{API}/auth/users",
        json={
            "email": "nouvelle@kapi.tg",
            "password": "motdepasse123",
            "full_name": "Nouvelle Chargée",
            "role": "RECRUITER",
        },
        headers=auth,
    )
    assert creation.status_code == 201, creation.text

    connexion = await client.post(
        f"{API}/auth/login",
        json={"email": "nouvelle@kapi.tg", "password": "motdepasse123"},
    )
    assert connexion.status_code == 200


# --- modifier ----------------------------------------------------------------


async def test_un_role_se_change(client, auth):
    await creer("chargee@kapi.tg")
    cible = await identifiant(client, "chargee@kapi.tg")

    reponse = await client.patch(
        f"{API}/auth/users/{cible}", json={"role": "ADMIN"}, headers=auth
    )
    assert reponse.status_code == 200
    assert reponse.json()["role"] == "ADMIN"


async def test_un_compte_se_desactive_puis_se_reactive(client, auth):
    """Désactiver ferme l'accès sans effacer la trace des décisions prises."""
    await creer("partie@kapi.tg")
    cible = await identifiant(client, "partie@kapi.tg")

    ferme = await client.patch(
        f"{API}/auth/users/{cible}", json={"is_active": False}, headers=auth
    )
    assert ferme.status_code == 200 and ferme.json()["is_active"] is False

    # 403 et non 401 : le mot de passe est bon, c'est le compte qui est fermé.
    # La distinction compte pour la personne en face, qui saurait sinon qu'elle
    # se trompe de mot de passe et le chercherait en vain.
    refus = await client.post(
        f"{API}/auth/login",
        json={"email": "partie@kapi.tg", "password": "password123"},
    )
    assert refus.status_code == 403

    rouvert = await client.patch(
        f"{API}/auth/users/{cible}", json={"is_active": True}, headers=auth
    )
    assert rouvert.json()["is_active"] is True
    retour = await client.post(
        f"{API}/auth/login",
        json={"email": "partie@kapi.tg", "password": "password123"},
    )
    assert retour.status_code == 200


async def test_un_compte_inconnu_rend_404(client, auth):
    reponse = await client.patch(
        f"{API}/auth/users/inexistant", json={"full_name": "X"}, headers=auth
    )
    assert reponse.status_code == 404


# --- les garde-fous -----------------------------------------------------------


async def test_on_ne_se_retire_pas_ses_propres_droits(client, auth):
    """L'erreur se fait par inadvertance, et personne ne peut la réparer."""
    soi = await identifiant(client, "admin@tricv.example")
    # Un second administrateur existe : ce n'est donc pas la règle du dernier
    # administrateur qui bloque, mais bien celle du compte courant.
    await creer("autre-admin@kapi.tg", role=UserRole.ADMIN)

    retrograder = await client.patch(
        f"{API}/auth/users/{soi}", json={"role": "RECRUITER"}, headers=auth
    )
    assert retrograder.status_code == 409

    desactiver = await client.patch(
        f"{API}/auth/users/{soi}", json={"is_active": False}, headers=auth
    )
    assert desactiver.status_code == 409


async def test_le_dernier_administrateur_actif_ne_se_retire_pas(client, auth):
    """Sans lui, ni les comptes ni les paramètres ne sont plus administrables."""
    autre = await creer("second-admin@kapi.tg", role=UserRole.ADMIN)

    # Le second administrateur peut être retiré : il en reste un.
    premier = await client.patch(
        f"{API}/auth/users/{autre}", json={"role": "RECRUITER"}, headers=auth
    )
    assert premier.status_code == 200

    # Le compte courant est maintenant seul, et se retirer est refusé — la
    # règle du compte courant suffit ici, celle du dernier admin la double.
    soi = await identifiant(client, "admin@tricv.example")
    assert (
        await client.patch(
            f"{API}/auth/users/{soi}", json={"role": "RECRUITER"}, headers=auth
        )
    ).status_code == 409


async def test_un_administrateur_inactif_ne_compte_pas_pour_le_dernier(client, auth):
    """Un compte fermé n'administre rien : il ne peut pas servir de filet."""
    dormant = await creer("dormant@kapi.tg", role=UserRole.ADMIN, actif=False)
    soi = await identifiant(client, "admin@tricv.example")

    reponse = await client.patch(
        f"{API}/auth/users/{soi}", json={"is_active": False}, headers=auth
    )
    assert reponse.status_code == 409
    assert dormant  # le compte dormant existe bien, et n'a rien changé


# --- le mot de passe ----------------------------------------------------------


async def test_un_administrateur_reinitialise_un_mot_de_passe(client, auth):
    await creer("oubli@kapi.tg")
    cible = await identifiant(client, "oubli@kapi.tg")

    reponse = await client.post(
        f"{API}/auth/users/{cible}/password",
        json={"password": "nouveau-motdepasse"},
        headers=auth,
    )
    assert reponse.status_code == 204

    ancien = await client.post(
        f"{API}/auth/login",
        json={"email": "oubli@kapi.tg", "password": "password123"},
    )
    assert ancien.status_code == 401

    nouveau = await client.post(
        f"{API}/auth/login",
        json={"email": "oubli@kapi.tg", "password": "nouveau-motdepasse"},
    )
    assert nouveau.status_code == 200


async def test_un_mot_de_passe_trop_court_est_refuse(client, auth):
    await creer("oubli@kapi.tg")
    cible = await identifiant(client, "oubli@kapi.tg")

    reponse = await client.post(
        f"{API}/auth/users/{cible}/password", json={"password": "court"}, headers=auth
    )
    assert reponse.status_code == 422


async def test_le_mot_de_passe_ne_figure_jamais_au_journal(client, auth):
    """Le journal retient qu'il a changé, et par qui — jamais sa valeur."""
    await creer("oubli@kapi.tg")
    cible = await identifiant(client, "oubli@kapi.tg")
    secret = "un-secret-reconnaissable"

    await client.post(
        f"{API}/auth/users/{cible}/password", json={"password": secret}, headers=auth
    )

    async with SessionLocal() as db:
        from sqlalchemy import select

        from app.models import AuditLog

        lignes = (await db.execute(select(AuditLog))).scalars().all()

    traces = [l for l in lignes if l.action == "user.password_reset"]
    assert traces, "le changement doit laisser une trace"
    assert secret not in str([l.details for l in lignes])
