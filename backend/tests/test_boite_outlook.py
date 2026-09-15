"""La boîte de candidatures chez Microsoft.

Microsoft a supprimé l'authentification par mot de passe sur IMAP, POP et SMTP.
Sa documentation ne laisse pas de marge : « Basic authentication is now disabled
in all tenants », et personne — pas même le support Microsoft — ne peut la
réactiver. Les « mots de passe d'application » en dépendaient et ne
fonctionnent plus non plus ; côté comptes personnels, la bascule a eu lieu le
16 septembre 2024.

Une boîte Outlook ne se relève donc pas avec un mot de passe, quel qu'il soit.
Ce qui est vérifié ici : qu'on sait présenter un jeton à la place, et qu'un
refus dit la vraie cause au lieu d'envoyer chercher un meilleur mot de passe
pendant une heure.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from app.services import courriel, oauth_microsoft
from app.services.oauth_microsoft import ConfigOAuth, ErreurOAuth


@pytest.fixture(autouse=True)
def _cache_propre():
    oauth_microsoft.oublier_cache()
    yield
    oauth_microsoft.oublier_cache()


# --- la chaîne présentée au serveur -----------------------------------------


def test_la_chaine_xoauth2_suit_le_format_impose():
    """`user=…^Aauth=Bearer …^A^A`, où ^A est l'octet 0x01.

    Format imposé par Microsoft et Google. Une virgule à la place d'un 0x01 et
    le serveur refuse sans rien expliquer.
    """
    chaine = oauth_microsoft.chaine_xoauth2("boite@kapi.tg", "JETON")
    assert chaine == "user=boite@kapi.tg\x01auth=Bearer JETON\x01\x01"
    # Elle voyage en base64 sur SMTP : elle doit survivre à l'encodage.
    assert base64.b64decode(base64.b64encode(chaine.encode())).decode() == chaine


# --- les deux flux -----------------------------------------------------------


def test_un_secret_designe_le_flux_application():
    """Compte professionnel : l'application s'authentifie seule, sans humain."""
    config = ConfigOAuth(tenant="un-tenant", client_id="id", client_secret="secret")
    assert config.utilisable and not config.delegue


def test_un_jeton_de_rafraichissement_designe_le_flux_delegue():
    """Compte personnel outlook.com : Microsoft n'autorise que celui-là."""
    config = ConfigOAuth(client_id="id", refresh_token="r")
    assert config.utilisable and config.delegue


def test_une_configuration_vide_n_est_pas_utilisable():
    assert not ConfigOAuth().utilisable
    assert not ConfigOAuth(client_id="id").utilisable


def test_le_flux_application_demande_les_bons_parametres(monkeypatch):
    envoye = {}

    def faux_post(url, data=None, timeout=None):
        envoye["url"] = url
        envoye["data"] = data
        return httpx.Response(
            200, json={"access_token": "JETON", "expires_in": 3600},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(oauth_microsoft.httpx, "post", faux_post)
    config = ConfigOAuth(tenant="le-tenant", client_id="id", client_secret="secret")

    assert oauth_microsoft.jeton(config, "boite@kapi.tg") == "JETON"
    assert "le-tenant" in envoye["url"]
    assert envoye["data"]["grant_type"] == "client_credentials"
    assert envoye["data"]["scope"] == oauth_microsoft.PORTEE_APPLICATION


def test_le_flux_delegue_echange_le_jeton_de_rafraichissement(monkeypatch):
    envoye = {}

    def faux_post(url, data=None, timeout=None):
        envoye["data"] = data
        return httpx.Response(
            200, json={"access_token": "JETON", "expires_in": 3600},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(oauth_microsoft.httpx, "post", faux_post)
    config = ConfigOAuth(client_id="id", refresh_token="RAFRAICHIR")

    assert oauth_microsoft.jeton(config, "boite@outlook.com") == "JETON"
    assert envoye["data"]["grant_type"] == "refresh_token"
    assert envoye["data"]["refresh_token"] == "RAFRAICHIR"
    assert "offline_access" in envoye["data"]["scope"]


def test_le_jeton_est_garde_jusqu_a_son_echeance(monkeypatch):
    """Un jeton par relevé userait le quota d'authentification pour rien."""
    appels = []

    def faux_post(url, data=None, timeout=None):
        appels.append(1)
        return httpx.Response(
            200, json={"access_token": "JETON", "expires_in": 3600},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(oauth_microsoft.httpx, "post", faux_post)
    config = ConfigOAuth(tenant="t", client_id="id", client_secret="s")

    for _ in range(4):
        oauth_microsoft.jeton(config, "boite@kapi.tg")
    assert len(appels) == 1


def test_deux_boites_ne_se_pretent_pas_un_jeton(monkeypatch):
    appels = []

    def faux_post(url, data=None, timeout=None):
        appels.append(1)
        return httpx.Response(
            200, json={"access_token": "JETON", "expires_in": 3600},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(oauth_microsoft.httpx, "post", faux_post)
    config = ConfigOAuth(tenant="t", client_id="id", client_secret="s")

    oauth_microsoft.jeton(config, "une@kapi.tg")
    oauth_microsoft.jeton(config, "autre@kapi.tg")
    assert len(appels) == 2


# --- les refus, traduits ------------------------------------------------------


@pytest.mark.parametrize(
    ("corps", "attendu"),
    [
        ("AADSTS7000215: invalid client secret", "valeur"),
        ("AADSTS700016: application not found", "Client ID"),
        ("AADSTS70011: scope not valid", "IMAP.AccessAsApp"),
        ("invalid_grant", "consentement"),
    ],
)
def test_un_refus_dit_quoi_corriger(monkeypatch, corps, attendu):
    """« AADSTS70011 » ne dit rien à personne ; la cause, si."""

    def faux_post(url, data=None, timeout=None):
        return httpx.Response(400, text=corps, request=httpx.Request("POST", url))

    monkeypatch.setattr(oauth_microsoft.httpx, "post", faux_post)
    config = ConfigOAuth(tenant="t", client_id="id", client_secret="s")

    with pytest.raises(ErreurOAuth, match=attendu):
        oauth_microsoft.jeton(config, "boite@kapi.tg")


def test_le_flux_application_sur_un_compte_personnel_est_expliqué(monkeypatch):
    """Microsoft n'autorise pas ce flux pour outlook.com, et le dit mal."""

    def faux_post(url, data=None, timeout=None):
        return httpx.Response(400, text="unsupported", request=httpx.Request("POST", url))

    monkeypatch.setattr(oauth_microsoft.httpx, "post", faux_post)
    config = ConfigOAuth(tenant="consumers", client_id="id", client_secret="s")

    with pytest.raises(ErreurOAuth, match="consentement humain"):
        oauth_microsoft.jeton(config, "boite@outlook.com")


# --- le diagnostic côté boîte ------------------------------------------------


def test_un_mot_de_passe_sur_une_boite_microsoft_dit_la_vraie_cause():
    """Le message qui fait perdre le plus de temps s'il est générique.

    Il n'existe aucun mot de passe qui marcherait : envoyer quelqu'un en
    chercher un meilleur lui coûte une heure pour rien.
    """
    config = courriel.ConfigBoite(
        hote="outlook.office365.com", utilisateur="boite@kapi.tg", mot_de_passe="x"
    )
    erreur = courriel._diagnostiquer(
        courriel.imaplib.IMAP4.error("AUTHENTICATIONFAILED"), config
    )
    message = str(erreur)
    assert "n'accepte plus aucun mot de passe" in message
    assert "mots de passe d'application" in message
    assert "OAuth" in message


def test_un_jeton_refuse_renvoie_vers_les_permissions():
    config = courriel.ConfigBoite(
        hote="outlook.office365.com",
        utilisateur="boite@kapi.tg",
        oauth=ConfigOAuth(tenant="t", client_id="id", client_secret="s"),
    )
    erreur = courriel._diagnostiquer(
        courriel.imaplib.IMAP4.error("AUTHENTICATIONFAILED"), config
    )
    assert "IMAP.AccessAsApp" in str(erreur)


def test_gmail_garde_son_message():
    """Chez Gmail le mot de passe d'application marche toujours."""
    config = courriel.ConfigBoite(
        hote="imap.gmail.com", utilisateur="boite@gmail.com", mot_de_passe="x"
    )
    erreur = courriel._diagnostiquer(
        courriel.imaplib.IMAP4.error("AUTHENTICATIONFAILED"), config
    )
    assert "mot de passe d'application" in str(erreur)


@pytest.mark.parametrize(
    "hote",
    ["outlook.office365.com", "smtp-mail.outlook.com", "imap-mail.outlook.com"],
)
def test_les_serveurs_microsoft_sont_reconnus(hote):
    assert courriel._est_microsoft(hote)


def test_un_serveur_quelconque_n_est_pas_pris_pour_microsoft():
    assert not courriel._est_microsoft("mail.kapiconsult.tg")
    assert not courriel._est_microsoft("imap.gmail.com")
