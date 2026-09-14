"""Distinguer « plus d'allocation » de « en panne ».

C'est sur cette distinction que repose la chaîne de secours. Se tromper dans un
sens fait basculer de fournisseur pour une panne passagère — et disperse la
lecture d'un mandat sur deux modèles sans raison. Se tromper dans l'autre laisse
la seconde clé inutilisée pendant qu'on affiche « Extraction indisponible ».

La règle : un 429 qui survit aux quatre tentatives n'est plus une limite par
minute, c'est l'allocation du jour. Les quatre tentatives sont ce qui fait la
différence, et c'est pourquoi elles passent en premier.
"""

from __future__ import annotations

import httpx
import pytest

from app.llm import http
from app.llm.base import LLMError, LLMQuotaError

pytestmark = pytest.mark.anyio


class FauxClient:
    """Rend les réponses préparées, l'une après l'autre."""

    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.appels = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def post(self, url, json=None, headers=None):
        self.appels += 1
        suite = self.reponses.pop(0) if self.reponses else self.reponses[-1]
        if isinstance(suite, Exception):
            raise suite
        code, corps = suite
        return httpx.Response(code, text=corps, request=httpx.Request("POST", url))


@pytest.fixture
def sans_attente(monkeypatch):
    """Les quatre tentatives, sans les quinze secondes de pause."""

    async def tout_de_suite(_):
        return None

    monkeypatch.setattr(http.asyncio, "sleep", tout_de_suite)


def poser(monkeypatch, reponses) -> FauxClient:
    client = FauxClient(reponses)
    monkeypatch.setattr(http.httpx, "AsyncClient", lambda **_: client)
    return client


async def test_un_429_persistant_est_un_quota(monkeypatch, sans_attente):
    client = poser(monkeypatch, [(429, "rate limit exceeded")] * 4)

    with pytest.raises(LLMQuotaError):
        await http.post_json("https://exemple/v1", json={})

    assert client.appels == 4, "les quatre tentatives d'abord : la minute peut passer"


async def test_un_429_qui_se_resout_ne_leve_rien(monkeypatch, sans_attente):
    """Une limite par minute se rattrape : c'est le cas courant."""
    poser(monkeypatch, [(429, "slow down"), (200, '{"ok": true}')])

    assert await http.post_json("https://exemple/v1", json={}) == {"ok": True}


async def test_une_panne_serveur_persistante_reste_une_panne(monkeypatch, sans_attente):
    """503 quatre fois : le fournisseur est cassé, pas épuisé.

    Basculer ici changerait de lecteur pour une raison qui n'a rien à voir
    avec l'allocation.
    """
    poser(monkeypatch, [(503, "unavailable")] * 4)

    with pytest.raises(LLMError) as echec:
        await http.post_json("https://exemple/v1", json={})
    assert not isinstance(echec.value, LLMQuotaError)


async def test_un_403_qui_parle_de_quota_est_un_quota(monkeypatch, sans_attente):
    """Certains fournisseurs disent « plus de crédit » avec un code d'accès."""
    poser(monkeypatch, [(403, '{"error": "quota exceeded for this project"}')])

    with pytest.raises(LLMQuotaError):
        await http.post_json("https://exemple/v1", json={})


async def test_un_403_d_acces_refuse_reste_une_erreur(monkeypatch, sans_attente):
    """Une clé invalide doit se voir, pas se contourner chez le voisin."""
    poser(monkeypatch, [(403, '{"error": "permission denied"}')])

    with pytest.raises(LLMError) as echec:
        await http.post_json("https://exemple/v1", json={})
    assert not isinstance(echec.value, LLMQuotaError)


async def test_un_401_n_est_jamais_un_quota(monkeypatch, sans_attente):
    poser(monkeypatch, [(401, "invalid api key")])

    with pytest.raises(LLMError) as echec:
        await http.post_json("https://exemple/v1", json={})
    assert not isinstance(echec.value, LLMQuotaError)


async def test_une_panne_reseau_persistante_n_est_pas_un_quota(monkeypatch, sans_attente):
    poser(monkeypatch, [httpx.ConnectError("injoignable")] * 4)

    with pytest.raises(LLMError) as echec:
        await http.post_json("https://exemple/v1", json={})
    assert not isinstance(echec.value, LLMQuotaError)


async def test_un_429_suivi_d_une_panne_reseau_n_est_pas_un_quota(monkeypatch, sans_attente):
    """Le verdict porte sur la *dernière* tentative, pas sur la pire."""
    poser(
        monkeypatch,
        [(429, "slow down"), (429, "slow down"), httpx.ConnectError("coupure"),
         httpx.ConnectError("coupure")],
    )

    with pytest.raises(LLMError) as echec:
        await http.post_json("https://exemple/v1", json={})
    assert not isinstance(echec.value, LLMQuotaError)
