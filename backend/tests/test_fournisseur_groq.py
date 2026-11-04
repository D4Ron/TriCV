"""Groq en dernier secours : sa clé l'ajoute à la file, sans rien y déplacer.

Sans réseau : l'appel HTTP est remplacé. Ce qui compte ici, c'est la place qu'il
prend, la forme de sa requête, et ce qui se passe quand il refuse un envoi.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import settings
from app.llm import factory, http
from app.llm.base import (
    BaseLLMProvider,
    LLMConfigError,
    LLMIndisponible,
    LLMQuotaError,
    LLMRequeteTropGrande,
)
from app.llm.chaine import ChaineFournisseurs
from app.llm.groq import JETONS_DE_REPONSE, MODELE_PAR_DEFAUT, GroqProvider
from app.services import parametres

pytestmark = pytest.mark.anyio


@pytest.fixture
def config(monkeypatch):
    def poser(**valeurs):
        defauts = dict(
            llm_provider="gemini",
            llm_model="",
            llm_fallback="",
            llm_prose_provider="",
            gemini_api_key="une-cle-gemini",
            gemini_model="",
            groq_api_key="",
            groq_model="",
        )
        for cle, valeur in {**defauts, **valeurs}.items():
            monkeypatch.setattr(settings, cle, valeur)

    return poser


def test_sans_cle_groq_ne_rejoint_pas_la_file(config):
    config()
    assert factory.build_chain().name == "gemini"


def test_sa_cle_l_ajoute_en_dernier(config):
    config(
        llm_provider="openai",
        llm_base_url="https://api.mistral.ai/v1",
        llm_api_key="une-cle",
        llm_model="ministral-14b-latest",
        llm_fallback="gemini",
        groq_api_key="une-cle-groq",
    )
    assert factory.build_chain().name == "openai → gemini → groq"


def test_llm_fallback_peut_le_placer_ailleurs(config):
    config(
        llm_provider="openai",
        llm_base_url="https://api.mistral.ai/v1",
        llm_api_key="une-cle",
        llm_model="ministral-14b-latest",
        llm_fallback="groq,gemini",
        groq_api_key="une-cle-groq",
    )
    assert factory.build_chain().name == "openai → groq → gemini"


def test_sans_cle_le_fournisseur_se_refuse_en_francais(config):
    config()
    with pytest.raises(LLMConfigError, match="Aucune clé Groq"):
        GroqProvider()


async def test_la_requete_tient_dans_sa_limite_par_minute(config, monkeypatch):
    config(groq_api_key="une-cle-groq")
    corps = {}

    async def faux_post(url, *, json, headers, provider):
        corps.update(json, url=url)
        return {"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]}

    monkeypatch.setattr(http, "post_json", faux_post)
    await GroqProvider().complete("systeme", "texte", json_mode=False)

    assert corps["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert corps["model"] == MODELE_PAR_DEFAUT
    assert corps["max_tokens"] == JETONS_DE_REPONSE
    assert corps["reasoning_effort"] == "low"


async def test_un_autre_modele_ne_recoit_pas_l_option_de_gpt_oss(config, monkeypatch):
    config(groq_api_key="une-cle-groq", groq_model="qwen/qwen3.8-27b")
    corps = {}

    async def faux_post(url, *, json, headers, provider):
        corps.update(json)
        return {"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]}

    monkeypatch.setattr(http, "post_json", faux_post)
    await GroqProvider().complete("systeme", "texte", json_mode=False)

    assert corps["model"] == "qwen/qwen3.8-27b"
    assert "reasoning_effort" not in corps


async def test_le_413_n_est_pas_retente(monkeypatch):
    appels = []

    def repondre(requete):
        appels.append(requete)
        return httpx.Response(413, text="Request too large")

    transport = httpx.MockTransport(repondre)
    client = httpx.AsyncClient

    monkeypatch.setattr(
        http.httpx, "AsyncClient", lambda **kw: client(transport=transport, **kw)
    )
    with pytest.raises(LLMRequeteTropGrande):
        await http.post_json("https://exemple.test/v1", json={}, provider="groq")
    assert len(appels) == 1


class Faux(BaseLLMProvider):
    """Un fournisseur dont la réponse à `complete` est écrite d'avance."""

    def __init__(self, name, *reponses):
        self.name = name
        self.reponses = list(reponses)
        self.appels = 0

    async def complete(self, system, user, attachment=None, *, json_mode=True):
        self.appels += 1
        reponse = self.reponses.pop(0)
        if isinstance(reponse, Exception):
            raise reponse
        return reponse


async def test_un_envoi_trop_long_passe_au_suivant_sans_mettre_au_repos():
    groq = Faux("groq", LLMRequeteTropGrande("413"), "pour le dossier court")
    suivant = Faux("suivant", "pour le dossier long")
    chaine = ChaineFournisseurs([groq, suivant])

    assert await chaine.rediger("consigne", "long") == "pour le dossier long"
    # Le dossier d'après, plus court, repasse par Groq.
    assert await chaine.rediger("consigne", "court") == "pour le dossier court"
    assert groq.appels == 2


async def test_un_quota_epuise_met_toujours_au_repos():
    groq = Faux("groq", LLMQuotaError("429"))
    suivant = Faux("suivant", "un", "deux")
    chaine = ChaineFournisseurs([groq, suivant])

    await chaine.rediger("consigne", "a")
    await chaine.rediger("consigne", "b")
    assert groq.appels == 1


async def test_seul_et_trop_long_le_refus_reste_une_indisponibilite():
    chaine = ChaineFournisseurs([Faux("groq", LLMRequeteTropGrande("413"))])
    with pytest.raises(LLMIndisponible):
        await chaine.rediger("consigne", "long")


def test_coller_sa_cle_ne_change_pas_le_fournisseur_en_service():
    reglages = parametres.Reglages(
        redact_demographics=True,
        allow_self_registration=False,
        candidatures_spontanees=True,
        groq_api_key="une-cle-groq",
    )
    assert parametres.fournisseur_ecran(reglages) == ""


def test_la_cle_est_un_secret():
    assert parametres.CLE_GROQ in parametres.SECRETS
    # Revenir au réglage du serveur ne l'efface pas.
    assert parametres.CLE_GROQ not in parametres.CLES_IA
