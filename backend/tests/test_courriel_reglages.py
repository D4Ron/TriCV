"""La boîte de candidatures, et la clé du modèle, se règlent depuis l'application.

Deux propriétés tiennent ce module : un secret ne ressort jamais du serveur, et
un enregistrement sans secret ne l'efface pas. La seconde n'est pas un détail
de confort — le formulaire ne pouvant pas réafficher le secret, l'oublier
casserait le relevé à chaque fois qu'on change le dossier ou l'adresse.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.db import SessionLocal
from app.llm import factory
from app.security import hash_password
from app.services import parametres

pytestmark = pytest.mark.anyio

API = "/api/v1"
SECRET = "valeur-du-secret-entra"
BOITE = {
    "courriel_actif": True,
    "adresse_boite": "recrutement@kapiconsult.tg",
    "dossier_boite": "inbox",
    "oauth_tenant": "11111111-2222-3333-4444-555555555555",
    "oauth_client_id": "app-de-recrutement",
    "oauth_client_secret": SECRET,
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


# --- la boîte -----------------------------------------------------------------


async def test_sans_configuration_le_releve_est_desactive(client, auth):
    etat = (await client.get(f"{API}/courriel/etat", headers=auth)).json()
    assert etat["actif"] is False

    refus = await client.post(f"{API}/courriel/tester", headers=auth)
    assert refus.status_code == 409
    assert "désactivé" in refus.json()["detail"]


async def test_une_boite_incomplete_nomme_les_champs_entra(client, auth):
    """Le nom du champ manquant, plutôt qu'une erreur Microsoft à décoder."""
    await client.patch(
        f"{API}/settings",
        json={"courriel_actif": True, "adresse_boite": "recrutement@kapiconsult.tg"},
        headers=auth,
    )

    refus = await client.post(f"{API}/courriel/tester", headers=auth)
    assert refus.status_code == 409
    detail = refus.json()["detail"]
    assert "tenant" in detail and "secret" in detail
    assert "Paramètres" in detail
    # Aucun mot de passe n'existe chez Microsoft : il n'a pas à être réclamé.
    assert "mot de passe" not in detail


async def test_l_etat_dit_pourquoi_le_releve_n_est_pas_possible(client, auth):
    """Le bouton de relevé à la main est celui qu'on cherche quand rien n'arrive."""
    etat = (await client.get(f"{API}/courriel/etat", headers=auth)).json()
    assert etat["actif"] is False
    assert etat["releve_desactive"] is True

    # Relevé activé, mais boîte incomplète : la raison change de nature.
    await client.patch(f"{API}/settings", json={"courriel_actif": True}, headers=auth)
    etat = (await client.get(f"{API}/courriel/etat", headers=auth)).json()
    assert etat["actif"] is False
    assert etat["releve_desactive"] is False
    assert "l'adresse de la boîte" in etat["manquants"]

    # Une fois complète, plus rien ne manque.
    await client.patch(f"{API}/settings", json=BOITE, headers=auth)
    etat = (await client.get(f"{API}/courriel/etat", headers=auth)).json()
    assert etat["actif"] is True
    assert etat["manquants"] == []
    assert etat["boite"] == "recrutement@kapiconsult.tg"


async def test_le_secret_ne_ressort_jamais(client, auth):
    await client.patch(f"{API}/settings", json=BOITE, headers=auth)

    corps = (await client.get(f"{API}/settings", headers=auth)).json()
    assert corps["oauth_client_secret_defini"] is True
    assert "oauth_client_secret" not in corps
    assert SECRET not in str(corps)


async def test_enregistrer_sans_secret_ne_le_supprime_pas(client, auth):
    """Le cas courant : on change le dossier, on ne retape pas le secret."""
    await client.patch(f"{API}/settings", json=BOITE, headers=auth)
    await client.patch(
        f"{API}/settings",
        json={**BOITE, "oauth_client_secret": "", "dossier_boite": "Candidatures"},
        headers=auth,
    )

    async with SessionLocal() as db:
        reglages = await parametres.lire(db)
    assert reglages.oauth_client_secret == SECRET
    assert reglages.dossier_boite == "Candidatures"
    assert reglages.courriel_utilisable is True


async def test_desactiver_ferme_le_releve_sans_perdre_la_configuration(client, auth):
    await client.patch(f"{API}/settings", json=BOITE, headers=auth)
    await client.patch(f"{API}/settings", json={"courriel_actif": False}, headers=auth)

    refus = await client.post(f"{API}/courriel/relever", headers=auth)
    assert refus.status_code == 409
    assert "désactivé" in refus.json()["detail"]

    # Les coordonnées sont toujours là : réactiver suffit.
    corps = (await client.get(f"{API}/settings", headers=auth)).json()
    assert corps["adresse_boite"] == BOITE["adresse_boite"]
    assert corps["oauth_client_secret_defini"] is True


async def test_l_envoi_part_de_la_boite_sans_adresse_d_expedition(client, auth):
    await client.patch(f"{API}/settings", json={**BOITE, "envoi_actif": True}, headers=auth)
    async with SessionLocal() as db:
        reglages = await parametres.lire(db)
    assert reglages.envoi_utilisable is True
    assert reglages.expediteur == BOITE["adresse_boite"]


async def test_les_anciens_noms_sont_encore_lus(client, auth):
    """Une base d'avant le retrait d'IMAP garde son adresse et son envoi.

    La migration 0006 renomme ces clés ; une base qui ne l'a pas encore passée
    ne doit pas pour autant perdre sa boîte.
    """
    async with SessionLocal() as db:
        db.add(parametres.Parametre(cle="imap_user", valeur="ancienne@kapiconsult.tg"))
        db.add(parametres.Parametre(cle="smtp_actif", valeur="true"))
        await db.commit()
        reglages = await parametres.lire(db)
    assert reglages.adresse_boite == "ancienne@kapiconsult.tg"
    assert reglages.envoi_actif is True

    # Le nouveau nom, une fois enregistré, l'emporte.
    await client.patch(
        f"{API}/settings", json={"adresse_boite": "neuve@kapiconsult.tg"}, headers=auth
    )
    async with SessionLocal() as db:
        assert (await parametres.lire(db)).adresse_boite == "neuve@kapiconsult.tg"


async def test_les_champs_imap_et_smtp_ne_sont_plus_acceptes(client, auth):
    """Ignorés sans bruit, ils feraient croire qu'un réglage a été pris."""
    await client.patch(
        f"{API}/settings",
        json={"imap_host": "imap.gmail.com", "smtp_password": "x"},
        headers=auth,
    )
    async with SessionLocal() as db:
        from sqlalchemy import select

        cles = set((await db.execute(select(parametres.Parametre.cle))).scalars())
    assert not cles & {"imap_host", "smtp_password"}


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
    assert "oauth_client_secret" in journal[0].details["reglages"]
    assert SECRET not in str(journal[0].details)


# --- le modèle d'IA -----------------------------------------------------------


@pytest.fixture
def serveur_ia(monkeypatch):
    """Un .env qui nomme un autre fournisseur, avec un rédacteur à lui.

    C'est le cas à couvrir : quoi que porte le serveur, ce que l'écran règle
    doit l'emporter. Tout est remis en place après le test.
    """
    du_fichier = {
        "llm_provider": "openai",
        "llm_model": "un-modele-openai",
        "gemini_api_key": "",
        "anthropic_api_key": "",
        "llm_api_key": "cle-openai-du-serveur",
        "llm_base_url": "https://api.exemple.test/v1",
        "ollama_base_url": "http://ollama:11434",
        "llm_prose_provider": "anthropic",
    }
    for cle, valeur in du_fichier.items():
        monkeypatch.setattr(settings, cle, valeur)
    monkeypatch.setattr(parametres, "_IA_DU_FICHIER", dict(du_fichier))
    yield du_fichier
    factory.reset_provider()


async def test_une_cle_gemini_collee_seule_fait_servir_gemini(client, auth, serveur_ia):
    """Le .env dit « openai » ; une clé Gemini collée à l'écran l'emporte."""
    reponse = await client.patch(
        f"{API}/settings", json={"gemini_api_key": "  AIza-cle-de-test  "}, headers=auth
    )
    assert reponse.status_code == 200, reponse.text
    # En service tout de suite, sans redémarrage, et sans les espaces recopiés.
    assert settings.llm_provider == "gemini"
    assert settings.gemini_api_key == "AIza-cle-de-test"
    # Le modèle du .env était nommé pour openai : il ne suit pas.
    assert settings.llm_model == ""
    # Le rédacteur du .env ne reprend pas les avis et les rapports.
    assert settings.llm_prose_provider == ""
    corps = reponse.json()
    assert corps["llm_provider"] == "gemini"
    assert corps["ia_cles"]["gemini"] == "ecran"
    assert corps["ia_regle_ecran"] is True
    # Jamais renvoyée.
    assert "AIza-cle-de-test" not in reponse.text


async def test_le_fournisseur_choisi_a_l_ecran_l_emporte(client, auth, serveur_ia):
    await client.patch(
        f"{API}/settings",
        json={"llm_provider": "anthropic", "anthropic_api_key": "sk-ant-test", "llm_model": "claude-x"},
        headers=auth,
    )
    assert settings.llm_provider == "anthropic"
    assert settings.anthropic_api_key == "sk-ant-test"
    assert settings.llm_model == "claude-x"
    assert settings.llm_prose_provider == ""


async def test_le_choix_explicite_prime_sur_une_cle_collee(client, auth, serveur_ia):
    """Une clé Gemini enregistrée ne doit pas reprendre la main sur un choix fait."""
    await client.patch(f"{API}/settings", json={"gemini_api_key": "AIza-1"}, headers=auth)
    await client.patch(
        f"{API}/settings",
        json={"llm_provider": "openai", "llm_api_key": "cle-ecran", "llm_model": "m"},
        headers=auth,
    )
    assert settings.llm_provider == "openai"
    assert settings.llm_api_key == "cle-ecran"


async def test_enregistrer_sans_cle_ne_l_efface_pas(client, auth, serveur_ia):
    await client.patch(f"{API}/settings", json={"gemini_api_key": "AIza-1"}, headers=auth)
    await client.patch(
        f"{API}/settings", json={"gemini_api_key": "", "candidatures_spontanees": False},
        headers=auth,
    )
    assert settings.gemini_api_key == "AIza-1"
    assert settings.llm_provider == "gemini"


async def test_revenir_au_serveur_rend_la_main_au_fichier(client, auth, serveur_ia):
    await client.patch(
        f"{API}/settings", json={"llm_provider": "gemini", "gemini_api_key": "AIza-ecran"},
        headers=auth,
    )
    assert settings.llm_provider == "gemini"

    reponse = await client.delete(f"{API}/settings/ia", headers=auth)
    assert reponse.status_code == 200
    for cle, valeur in serveur_ia.items():
        assert getattr(settings, cle) == valeur, cle
    corps = reponse.json()
    assert corps["ia_regle_ecran"] is False
    assert corps["ia_cles"]["openai"] == "serveur"
    assert corps["ia_cles"]["gemini"] == ""


async def test_un_fournisseur_inconnu_est_refuse(client, auth, serveur_ia):
    refus = await client.patch(f"{API}/settings", json={"llm_provider": "inconnu"}, headers=auth)
    assert refus.status_code == 422
    assert settings.llm_provider == "openai"


async def test_un_recruteur_ne_peut_pas_regler_le_modele(client, auth, serveur_ia):
    entetes = await creer_recruteur(client)
    refus = await client.patch(
        f"{API}/settings", json={"gemini_api_key": "AIza-x"}, headers=entetes
    )
    assert refus.status_code == 403
    assert (await client.delete(f"{API}/settings/ia", headers=entetes)).status_code == 403
    assert settings.gemini_api_key == ""
    assert settings.llm_provider == "openai"
