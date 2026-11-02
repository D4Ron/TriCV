"""Gemini passe au modèle suivant quand le sien ne répond pas.

Constaté en production : gemini-2.0-flash puis 2.5-flash refusés aux nouveaux
comptes (404), et gemini-3.8-flash — celui que Google désignait à leur place —
saturé (503) ou répondant en plus d'une minute. L'application retentait le même
modèle quatre fois et l'écran attendait pour rien, alors que d'autres modèles de
la même clé répondaient en deux secondes.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.llm import gemini, http
from app.llm.base import LLMError, LLMIndisponible, LLMQuotaError

pytestmark = pytest.mark.anyio

REPONSE = {"candidates": [{"content": {"parts": [{"text": "OK"}]}, "finishReason": "STOP"}]}


@pytest.fixture
def fournisseur(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "cle-de-test")
    monkeypatch.setattr(settings, "gemini_model", "")
    monkeypatch.setattr(settings, "llm_model", "gemini-3.8-flash")
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(gemini, "dernier_modele_servi", None)
    return gemini.GeminiProvider()


def _brancher(monkeypatch, issues: dict[str, Exception | dict]) -> list[str]:
    """Chaque modèle rend ce qu'on lui a dit ; on note l'ordre des appels."""
    appels: list[str] = []

    async def faux_post(url, *, json, headers=None, provider="", max_attempts=4, timeout=None):
        modele = url.split("/models/")[1].split(":")[0]
        appels.append(modele)
        # Un seul essai par modèle : les autres modèles sont le repli.
        assert max_attempts == 1
        issue = issues.get(modele, REPONSE)
        if isinstance(issue, Exception):
            raise issue
        return issue

    monkeypatch.setattr(http, "post_json", faux_post)
    return appels


async def test_un_modele_sature_passe_la_main_au_suivant(monkeypatch, fournisseur):
    appels = _brancher(
        monkeypatch, {"gemini-3.8-flash": LLMIndisponible("HTTP 503: high demand")}
    )
    assert await fournisseur.complete("s", "u", json_mode=False) == "OK"
    assert appels == ["gemini-3.8-flash", "gemini-3.6-flash"]
    assert gemini.dernier_modele_servi == "gemini-3.6-flash"


async def test_le_modele_qui_repond_est_retenu(monkeypatch, fournisseur):
    """Le suivant appel ne repasse pas par le modèle saturé."""
    appels = _brancher(
        monkeypatch, {"gemini-3.8-flash": LLMIndisponible("HTTP 503: high demand")}
    )
    await fournisseur.complete("s", "u", json_mode=False)
    appels.clear()
    await fournisseur.complete("s", "u", json_mode=False)
    assert appels == ["gemini-3.6-flash"]


async def test_un_modele_retire_passe_la_main_au_suivant(monkeypatch, fournisseur):
    appels = _brancher(
        monkeypatch,
        {
            "gemini-3.8-flash": LLMError(
                "gemini returned HTTP 404: This model is no longer available to new users"
            ),
            "gemini-3.6-flash": LLMError("gemini returned HTTP 404: not found"),
        },
    )
    assert await fournisseur.complete("s", "u", json_mode=False) == "OK"
    assert appels[-1] == "gemini-3.5-flash"


async def test_une_cle_refusee_ne_fait_pas_le_tour_des_modeles(monkeypatch, fournisseur):
    """Elle échouerait pareil partout : la dire tout de suite."""
    appels = _brancher(
        monkeypatch, {"gemini-3.8-flash": LLMError("gemini returned HTTP 400: API key not valid")}
    )
    with pytest.raises(LLMError, match="API key not valid"):
        await fournisseur.complete("s", "u", json_mode=False)
    assert appels == ["gemini-3.8-flash"]


async def test_aucun_modele_ne_repond(monkeypatch, fournisseur):
    tous = {m: LLMIndisponible("HTTP 503") for m in ("gemini-3.8-flash", *gemini.MODELES_DE_REPLI)}
    _brancher(monkeypatch, tous)
    with pytest.raises(LLMIndisponible, match="Aucun modèle Gemini"):
        await fournisseur.complete("s", "u", json_mode=False)


async def test_quota_epuise_partout_se_dit_quota(monkeypatch, fournisseur):
    """La chaîne de fournisseurs doit savoir qu'il faut passer à un autre."""
    tous = {m: LLMQuotaError("HTTP 429") for m in ("gemini-3.8-flash", *gemini.MODELES_DE_REPLI)}
    _brancher(monkeypatch, tous)
    with pytest.raises(LLMQuotaError):
        await fournisseur.complete("s", "u", json_mode=False)


def test_le_modele_par_defaut_est_celui_qui_repond_vite():
    assert gemini.DEFAULT_MODEL == "gemini-3.6-flash"
