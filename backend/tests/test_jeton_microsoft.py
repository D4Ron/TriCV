"""Le jeton d'application Microsoft, qui ouvre la boîte de recrutement.

La boîte est une boîte Microsoft 365, lue et utilisée pour l'envoi par
Microsoft Graph. L'application s'authentifie seule, avec un identifiant et un
secret déclarés dans Entra : ce qui est vérifié ici, c'est qu'elle demande le
bon jeton, qu'elle le garde jusqu'à son échéance, et qu'un refus dit la vraie
cause au lieu d'un code AADSTS.
"""

from __future__ import annotations

import httpx
import pytest

from app.services import oauth_microsoft
from app.services.oauth_microsoft import ConfigOAuth, ErreurOAuth


@pytest.fixture(autouse=True)
def _cache_propre():
    oauth_microsoft.oublier_cache()
    yield
    oauth_microsoft.oublier_cache()


def _repondre(appels: list | None = None, envoye: dict | None = None):
    def faux_post(url, data=None, timeout=None):
        if appels is not None:
            appels.append(1)
        if envoye is not None:
            envoye["url"] = url
            envoye["data"] = data
        return httpx.Response(
            200, json={"access_token": "JETON", "expires_in": 3600},
            request=httpx.Request("POST", url),
        )

    return faux_post


def test_il_faut_le_tenant_l_application_et_le_secret():
    assert ConfigOAuth(tenant="t", client_id="id", client_secret="s").utilisable
    assert not ConfigOAuth().utilisable
    assert not ConfigOAuth(client_id="id", client_secret="s").utilisable
    assert not ConfigOAuth(tenant="t", client_id="id").utilisable


def test_le_jeton_est_demande_pour_graph_en_flux_application(monkeypatch):
    envoye: dict = {}
    monkeypatch.setattr(oauth_microsoft.httpx, "post", _repondre(envoye=envoye))
    config = ConfigOAuth(tenant="le-tenant", client_id="id", client_secret="secret")

    assert oauth_microsoft.jeton(config, "boite@kapi.tg") == "JETON"
    assert "le-tenant" in envoye["url"]
    assert envoye["data"]["grant_type"] == "client_credentials"
    assert envoye["data"]["scope"] == oauth_microsoft.PORTEE_GRAPH


def test_une_configuration_incomplete_est_refusee_sans_appel(monkeypatch):
    appels: list = []
    monkeypatch.setattr(oauth_microsoft.httpx, "post", _repondre(appels=appels))
    with pytest.raises(ErreurOAuth, match="incomplet"):
        oauth_microsoft.jeton(ConfigOAuth(client_id="id"), "boite@kapi.tg")
    assert appels == []


def test_le_jeton_est_garde_jusqu_a_son_echeance(monkeypatch):
    """Un jeton par relevé userait le quota d'authentification pour rien."""
    appels: list = []
    monkeypatch.setattr(oauth_microsoft.httpx, "post", _repondre(appels=appels))
    config = ConfigOAuth(tenant="t", client_id="id", client_secret="s")

    for _ in range(4):
        oauth_microsoft.jeton(config, "boite@kapi.tg")
    assert len(appels) == 1


def test_deux_boites_ne_se_pretent_pas_un_jeton(monkeypatch):
    appels: list = []
    monkeypatch.setattr(oauth_microsoft.httpx, "post", _repondre(appels=appels))
    config = ConfigOAuth(tenant="t", client_id="id", client_secret="s")

    oauth_microsoft.jeton(config, "une@kapi.tg")
    oauth_microsoft.jeton(config, "autre@kapi.tg")
    assert len(appels) == 2


@pytest.mark.parametrize(
    ("corps", "attendu"),
    [
        ("AADSTS7000215: invalid client secret", "valeur"),
        ("AADSTS7000222: client secret expired", "expiré"),
        ("AADSTS700016: application not found", "ID de l'application"),
        ("AADSTS90002: tenant not found", "locataire"),
        ("AADSTS70011: scope not valid", "Mail.ReadWrite"),
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


def test_microsoft_injoignable_est_dit(monkeypatch):
    def faux_post(url, data=None, timeout=None):
        raise httpx.ConnectError("refusé", request=httpx.Request("POST", url))

    monkeypatch.setattr(oauth_microsoft.httpx, "post", faux_post)
    config = ConfigOAuth(tenant="t", client_id="id", client_secret="s")
    with pytest.raises(ErreurOAuth, match="Impossible de joindre Microsoft"):
        oauth_microsoft.jeton(config, "boite@kapi.tg")
