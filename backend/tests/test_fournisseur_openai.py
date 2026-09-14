"""Le fournisseur qui parle le dialecte d'OpenAI.

Un seul fichier pour Groq, Cerebras, Mistral, OpenRouter et tout serveur vLLM
posé sur une machine du cabinet : ils exposent le même `/chat/completions`.
Ce qui se teste ici est donc la forme de la requête et la lecture de la
réponse, sans réseau — l'appel HTTP est remplacé.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.llm import http, openai_compatible
from app.llm.base import Attachment, LLMConfigError, LLMError
from app.llm.openai_compatible import OpenAICompatibleProvider

pytestmark = pytest.mark.anyio


def reponse(texte: str, finish: str = "stop") -> dict:
    return {"choices": [{"message": {"content": texte}, "finish_reason": finish}]}


@pytest.fixture
def configure(monkeypatch):
    # `llm_provider` compte : `LLM_MODEL` ne nomme le modèle que du fournisseur
    # *principal*. Un `openai` déclaré en secours doit déclarer `OPENAI_MODEL`,
    # sans quoi il demanderait le modèle d'un autre fournisseur — ce que le
    # test ci-dessous vérifie explicitement.
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_base_url", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(settings, "llm_api_key", "cle-de-test")
    monkeypatch.setattr(settings, "llm_model", "llama-3.3-70b-versatile")
    monkeypatch.setattr(settings, "openai_model", "")


@pytest.fixture
def appels(monkeypatch):
    """Note chaque requête et rend ce que le test a préparé."""
    envoyes: list[dict] = []
    rendus: list[dict | Exception] = []

    async def faux_post(url, *, json, headers=None, provider="llm"):
        # Une copie, pas la référence : le second essai retire `response_format`
        # du même dictionnaire, et garder la référence ferait mentir le premier
        # envoi enregistré.
        envoyes.append({"url": url, "corps": dict(json), "entetes": headers or {}})
        resultat = rendus.pop(0) if rendus else reponse("d'accord")
        if isinstance(resultat, Exception):
            raise resultat
        return resultat

    monkeypatch.setattr(http, "post_json", faux_post)
    monkeypatch.setattr(openai_compatible.http, "post_json", faux_post)
    return envoyes, rendus


# --- la configuration -------------------------------------------------------


def test_sans_adresse_le_refus_nomme_les_adresses_connues(monkeypatch):
    """Le message doit suffire : « openai » ne désigne pas une marque ici."""
    monkeypatch.setattr(settings, "llm_base_url", "")
    monkeypatch.setattr(settings, "llm_api_key", "cle")
    monkeypatch.setattr(settings, "llm_model", "un-modele")

    with pytest.raises(LLMConfigError, match="groq"):
        OpenAICompatibleProvider()


def test_sans_modele_le_refus_est_explicite(monkeypatch):
    """Aucun de ces fournisseurs n'a de modèle par défaut."""
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_base_url", "https://api.mistral.ai/v1")
    monkeypatch.setattr(settings, "llm_api_key", "cle")
    monkeypatch.setattr(settings, "llm_model", "")
    monkeypatch.setattr(settings, "openai_model", "")

    with pytest.raises(LLMConfigError, match="LLM_MODEL"):
        OpenAICompatibleProvider()


def test_l_adresse_perd_sa_barre_finale(monkeypatch, appels):
    """Sinon la requête part sur `…/v1//chat/completions`."""
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_base_url", "https://api.groq.com/openai/v1/")
    monkeypatch.setattr(settings, "llm_api_key", "cle")
    monkeypatch.setattr(settings, "llm_model", "un-modele")

    assert OpenAICompatibleProvider().base_url == "https://api.groq.com/openai/v1"


def test_en_secours_il_lui_faut_son_propre_modele(monkeypatch):
    """`LLM_MODEL` nomme le modèle du principal, et de lui seul.

    Déclaré en secours derrière Gemini, ce fournisseur ne peut pas hériter de
    « gemini-2.5-flash » : il doit nommer le sien. Le refus est explicite
    plutôt que silencieux, sans quoi la chaîne l'écarterait sans dire pourquoi.
    """
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "llm_model", "gemini-2.5-flash")
    monkeypatch.setattr(settings, "llm_base_url", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(settings, "llm_api_key", "cle")
    monkeypatch.setattr(settings, "openai_model", "")

    with pytest.raises(LLMConfigError, match="OPENAI_MODEL"):
        OpenAICompatibleProvider()

    monkeypatch.setattr(settings, "openai_model", "llama-3.3-70b-versatile")
    assert OpenAICompatibleProvider().model == "llama-3.3-70b-versatile"


# --- la requête -------------------------------------------------------------


async def test_une_demande_de_prose_n_impose_aucun_format(configure, appels):
    """La correction de fond, vérifiée sur ce fournisseur aussi."""
    envoyes, _ = appels
    await OpenAICompatibleProvider().complete("système", "consigne", json_mode=False)

    assert "response_format" not in envoyes[0]["corps"]


async def test_une_demande_de_json_impose_le_format(configure, appels):
    envoyes, _ = appels
    await OpenAICompatibleProvider().complete("système", "consigne", json_mode=True)

    assert envoyes[0]["corps"]["response_format"] == {"type": "json_object"}


async def test_la_requete_va_au_bon_endroit_avec_la_cle(configure, appels):
    envoyes, _ = appels
    await OpenAICompatibleProvider().complete("système", "consigne")

    envoi = envoyes[0]
    assert envoi["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert envoi["entetes"]["authorization"] == "Bearer cle-de-test"
    assert envoi["corps"]["messages"] == [
        {"role": "system", "content": "système"},
        {"role": "user", "content": "consigne"},
    ]


async def test_un_document_est_refuse_sans_ambiguite(configure, appels):
    """Aucun de ces fournisseurs ne lit un PDF. Le CV part en texte expurgé."""
    with pytest.raises(LLMConfigError, match="PII_REDACTION"):
        await OpenAICompatibleProvider().complete(
            "système", "consigne", Attachment(b"%PDF-", "application/pdf")
        )


async def test_un_modele_qui_refuse_response_format_est_reessaye_sans(configure, appels):
    """Tous les modèles ne l'acceptent pas, et le refus est un 400 sec.

    Sans ce rattrapage, un modèle sur trois du fournisseur choisi tombait en
    panne sans que rien n'explique pourquoi — alors que la consigne demande
    déjà du JSON en toutes lettres.
    """
    envoyes, rendus = appels
    rendus.append(LLMError("HTTP 400: 'response_format' is not supported"))
    rendus.append(reponse('{"diplomes": []}'))

    texte = await OpenAICompatibleProvider().complete("système", "consigne")

    assert texte == '{"diplomes": []}'
    assert "response_format" in envoyes[0]["corps"]
    assert "response_format" not in envoyes[1]["corps"]


async def test_une_autre_erreur_n_est_pas_reessayee(configure, appels):
    """Une clé refusée ne se répare pas en retirant un champ."""
    _, rendus = appels
    rendus.append(LLMError("HTTP 401: invalid api key"))

    with pytest.raises(LLMError, match="401"):
        await OpenAICompatibleProvider().complete("système", "consigne")


# --- la réponse -------------------------------------------------------------


async def test_une_reponse_tronquee_dit_qu_elle_l_est(configure, appels):
    """Sinon elle arrive comme un JSON illisible, sans cause nommée."""
    _, rendus = appels
    rendus.append(reponse('{"diplomes": [{"intitu', finish="length"))

    with pytest.raises(LLMError, match="cut short"):
        await OpenAICompatibleProvider().complete("système", "consigne")


async def test_une_reponse_vide_est_une_erreur(configure, appels):
    _, rendus = appels
    rendus.append(reponse("   "))

    with pytest.raises(LLMError, match="empty response"):
        await OpenAICompatibleProvider().complete("système", "consigne")


async def test_la_prose_traverse_le_fournisseur_puis_le_nettoyage(configure, appels):
    """Le chemin complet : réponse emballée par le modèle, prose rendue."""
    _, rendus = appels
    rendus.append(reponse('{"texte": "Douze dossiers ont été reçus."}'))

    fournisseur = OpenAICompatibleProvider()
    assert await fournisseur.rediger("Rédigez.", "…") == "Douze dossiers ont été reçus."
