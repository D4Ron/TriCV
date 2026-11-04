"""Groq, le dernier à répondre.

Il n'est jamais le fournisseur principal, et le README dit pourquoi : ce qui
décide ici n'est pas le nombre de requêtes mais le plafond de **jetons**. À
7 000 jetons le dossier complet, ses 200 000 jetons par jour en font une
vingtaine ; ses 8 000 par minute, un seul à la fois, et pas toujours.

Il garde pourtant sa place derrière les autres, pour trois raisons : il répond
aux travaux courts — une section de rapport, un avis — qui ne coûtent presque
rien ; il ne conserve pas par défaut ce qu'on lui envoie, là où l'offre gratuite
de Gemini se réserve de le faire relire ; et une troisième clé évite qu'un
mandat s'arrête le jour où les deux premières sont épuisées.

Sa clé suffit à l'ajouter à la chaîne, en dernier. Elle ne le met jamais devant
le fournisseur choisi : `LLM_FALLBACK` le place ailleurs pour qui le veut.
"""

from __future__ import annotations

from app.config import settings
from app.llm.base import LLMConfigError, modele_configure
from app.llm.openai_compatible import OpenAICompatibleProvider

ADRESSE = "https://api.groq.com/openai/v1"
# Le modèle généraliste que la documentation de Groq liste en novembre 2026 ;
# `llama-3.3-70b-versatile` n'y figure plus.
MODELE_PAR_DEFAUT = "openai/gpt-oss-120b"

# Le plafond de réponse pèse sur la limite par minute au même titre que
# l'envoi. Une extraction tient largement en 3 000 jetons, et il en reste ainsi
# environ 5 000 pour le dossier ; au-delà, Groq répond 413 et la chaîne passe.
JETONS_DE_REPONSE = 3000


class GroqProvider(OpenAICompatibleProvider):
    name = "groq"
    max_tokens = JETONS_DE_REPONSE

    def __init__(self) -> None:
        cle = settings.groq_api_key.strip()
        if not cle:
            raise LLMConfigError("Aucune clé Groq enregistrée.")
        self.base_url = ADRESSE
        self.api_key = cle
        self.model = modele_configure("groq", MODELE_PAR_DEFAUT)

    def _options(self) -> dict:
        # gpt-oss réfléchit avant de répondre, sur le même plafond que la
        # réponse : au réglage par défaut, il pourrait l'épuiser sans conclure.
        return {"reasoning_effort": "low"} if "gpt-oss" in self.model else {}
