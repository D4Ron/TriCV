"""L'état de l'application, tel que l'administrateur le lit.

Avant cet écran, une installation incomplète ne se découvrait qu'en relisant
la configuration du serveur : la clé du modèle absente, la boîte de courriel
jamais branchée, un serveur frontal qui refusait les dossiers. Ces tests
figent ce que l'écran doit dire de chacun, et ce qu'il ne doit jamais faire —
exposer un secret, ou laisser un visiteur gonfler les compteurs à volonté.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from app.config import settings
from app.db import SessionLocal
from app.models import Frequentation, User
from app.security import hash_password
from app.services import sante
from tests.test_declaration_candidat import dossier, monter_poste

API = "/api/v1"
pytestmark = pytest.mark.anyio


def _par_code(etat: dict) -> dict:
    return {v["code"]: v for v in etat["verifications"]}


# --- les vérifications -----------------------------------------------------------


async def test_l_etat_est_reserve_aux_administrateurs(client):
    reponse = await client.get(f"{API}/sante")
    assert reponse.status_code in (401, 403)


async def test_une_boite_non_branchee_le_dit_et_dit_quoi(client, auth):
    """Le cas exact de la production : rien de configuré, tout désactivé."""
    etat = (await client.get(f"{API}/sante", headers=auth)).json()
    verifs = _par_code(etat)

    assert verifs["releve"]["etat"] == "a_regler"
    assert "désactivé" in verifs["releve"]["detail"]
    assert verifs["releve"]["ou"] == "courriel"

    assert verifs["envoi"]["etat"] == "a_regler"
    assert verifs["base"]["etat"] == "ok"
    # La limite du frontal ne se voit que depuis le navigateur : l'écran la
    # mesure, le serveur ne prétend pas la connaître.
    assert verifs["depot"]["etat"] == "a_verifier"


async def test_une_boite_microsoft_incomplete_nomme_les_champs(client, auth):
    await client.patch(
        f"{API}/settings",
        json={
            "courriel_actif": True,
            "adresse_boite": "recrutement@kapiconsult.tg",
        },
        headers=auth,
    )
    releve = _par_code((await client.get(f"{API}/sante", headers=auth)).json())["releve"]
    assert releve["etat"] == "a_regler"
    assert "tenant" in releve["detail"]
    assert "secret" in releve["detail"]


async def test_le_mot_de_passe_d_origine_de_l_administrateur_est_signale(client, auth):
    """Il figure dans le code source : tant qu'il tient, n'importe qui entre."""
    sans = _par_code((await client.get(f"{API}/sante", headers=auth)).json())
    assert "admin_defaut" not in sans

    async with SessionLocal() as db:
        await db.execute(
            update(User)
            .where(User.email == settings.seed_admin_email.lower())
            .values(password_hash=hash_password(settings.seed_admin_password))
        )
        await db.commit()

    avec = _par_code((await client.get(f"{API}/sante", headers=auth)).json())
    assert avec["admin_defaut"]["etat"] == "a_regler"
    assert avec["admin_defaut"]["ou"] == "comptes"
    # Le mot de passe lui-même n'est jamais affiché.
    assert settings.seed_admin_password not in avec["admin_defaut"]["detail"]


async def test_un_avis_ouvert_est_compte(client, auth):
    sans = _par_code((await client.get(f"{API}/sante", headers=auth)).json())
    assert sans["avis"]["etat"] == "info"

    await monter_poste(client, auth)
    avec = _par_code((await client.get(f"{API}/sante", headers=auth)).json())
    assert avec["avis"]["etat"] == "ok"
    assert "1 avis" in avec["avis"]["detail"]


def test_une_cle_ne_s_affiche_jamais_dans_un_message_d_erreur():
    """Certains fournisseurs passent la clé dans l'adresse ; l'erreur la recopie."""
    brut = (
        "HTTPStatusError: 400 for url "
        "https://generativelanguage.googleapis.com/v1/models?key=AIzaSyD-une-vraie-cle-123"
    )
    nettoye = sante._masquer(brut)
    assert "AIzaSyD" not in nettoye
    assert "key=…" in nettoye


# --- la sonde de dépôt -----------------------------------------------------------


async def test_la_sonde_recoit_sans_rien_enregistrer(client, auth):
    corps = b"0" * (3 * 1024 * 1024)
    reponse = await client.post(f"{API}/sante/sonde-depot", content=corps, headers=auth)
    assert reponse.status_code == 200
    assert reponse.json()["octets_recus"] == len(corps)


async def test_la_sonde_est_reservee_aux_administrateurs(client):
    reponse = await client.post(f"{API}/sante/sonde-depot", content=b"0" * 10)
    assert reponse.status_code in (401, 403)


# --- la fréquentation ------------------------------------------------------------


async def test_une_visite_signalee_est_comptee(client, auth):
    for _ in range(3):
        reponse = await client.post(
            f"{API}/public/evenement", json={"evenement": "visite_postes"}
        )
        assert reponse.status_code == 204

    totaux = (await client.get(f"{API}/sante", headers=auth)).json()["frequentation"]["totaux"]
    assert totaux["visites"] == 3


async def test_un_evenement_inconnu_est_refuse(client):
    """La liste est fermée : la route est publique."""
    reponse = await client.post(
        f"{API}/public/evenement", json={"evenement": "n_importe_quoi"}
    )
    assert reponse.status_code == 422
    async with SessionLocal() as db:
        assert (await db.execute(select(Frequentation))).first() is None


async def test_un_depot_refuse_est_rattache_a_son_poste(client, auth):
    """Le serveur ne voit jamais ces refus : seul le navigateur peut les dire."""
    cle = await monter_poste(client, auth)
    await client.post(
        f"{API}/public/evenement", json={"evenement": "visite_avis", "cle": cle}
    )
    await client.post(
        f"{API}/public/evenement", json={"evenement": "depot_refuse_taille", "cle": cle}
    )

    frequentation = (await client.get(f"{API}/sante", headers=auth)).json()["frequentation"]
    assert frequentation["totaux"]["refus_taille"] == 1
    ligne = frequentation["par_poste"][0]
    assert ligne["intitule"] == "Chef comptable"
    assert ligne["visites"] == 1
    assert ligne["refus_taille"] == 1


async def test_les_candidatures_du_site_se_lisent_en_base(client, auth):
    cle = await monter_poste(client, auth)
    await client.post(
        f"{API}/public/avis/{cle}/candidater",
        data=dossier(),
        files={"fichiers": ("cv.pdf", b"%PDF-1.4 un CV", "application/pdf")},
    )
    frequentation = (await client.get(f"{API}/sante", headers=auth)).json()["frequentation"]
    assert frequentation["totaux"]["candidatures"] == 1
    assert frequentation["par_poste"][0]["candidatures"] == 1
    # Trente jours, du plus ancien au plus récent.
    assert len(frequentation["jours"]) == 30


async def test_rien_n_identifie_un_visiteur():
    """Le compteur n'a que quatre colonnes utiles : jour, événement, poste, nombre."""
    colonnes = {c.name for c in Frequentation.__table__.columns}
    assert colonnes == {"id", "jour", "evenement", "poste_id", "compte"}
