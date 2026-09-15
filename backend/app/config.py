from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


# Le fichier de configuration vit à la racine du dépôt, pas dans backend/.
# Le chercher par chemin relatif le rendait dépendant du répertoire courant :
# lancé depuis backend/, le serveur ne le lisait pas du tout et retombait
# silencieusement sur les valeurs par défaut — dont un secret de jeton connu.
# Les scripts de démarrage masquaient le problème en exportant les variables
# eux-mêmes ; tout autre point d'entrée ne le masquait pas.
RACINE = Path(__file__).resolve().parents[2]

# Les tests, eux, ne doivent lire aucun fichier de configuration : une suite
# dont le résultat dépend du .env de la machine ne prouve rien. Le conftest
# pose ce drapeau avant d'importer quoi que ce soit, et fixe lui-même les
# valeurs dont les tests dépendent.
_SANS_FICHIER = os.environ.get("TRICV_IGNORE_ENV_FILE") == "1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Ordre croissant de priorité : un .env propre à backend/ l'emporte.
        env_file=None if _SANS_FICHIER else (RACINE / ".env", ".env"),
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "TriCV"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://tricv:tricv@db:5432/tricv"

    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 7

    seed_admin_email: str = "admin@tricv.example"
    seed_admin_password: str = "admin1234"

    # Off by default: an HR account can read every candidate's CV and personal
    # details, so opening registration to the internet is an explicit decision.
    # When a signup code is set, callers must present it as well.
    allow_self_registration: bool = False
    signup_code: str = ""
    signup_rate_limit_per_hour: int = 10

    llm_provider: Literal["gemini", "anthropic", "ollama", "openai"] = "gemini"
    # Le modèle du fournisseur principal. Chaque fournisseur peut en déclarer
    # un à lui — `GEMINI_MODEL`, `OPENAI_MODEL` — ce qui devient nécessaire dès
    # qu'une chaîne de secours existe : « mistral-small-latest » n'a aucun sens
    # pour Gemini, et une chaîne qui partage un seul nom de modèle casse au
    # moment précis où elle devait sauver la mise.
    llm_model: str = ""
    gemini_model: str = ""
    anthropic_model: str = ""
    ollama_model: str = ""
    openai_model: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://ollama:11434"
    # `openai` : tout fournisseur parlant le dialecte d'OpenAI — Groq, Cerebras,
    # Mistral, OpenRouter, un vLLM local. L'adresse et la clé se posent ici,
    # `LLM_MODEL` désigne le modèle : aucun de ces fournisseurs n'en a par
    # défaut.
    llm_base_url: str = ""
    llm_api_key: str = ""

    # Les fournisseurs de secours, séparés par des virgules, essayés dans
    # l'ordre quand le principal n'a plus d'allocation — et seulement dans ce
    # cas. Vide : aucun secours, une panne de quota s'affiche comme telle.
    # Un fournisseur sans clé est simplement écarté de la chaîne.
    llm_fallback: str = ""

    # Le fournisseur qui **rédige** — sections de rapport et avis publiés —
    # quand ce n'est pas le même que celui qui dépouille.
    #
    # Les deux travaux n'ont ni le même volume ni le même risque. Dépouiller
    # coûte un appel par dossier : c'est ce qui épuise un quota, et une erreur
    # s'y voit à la relecture du parcours. Rédiger coûte sept appels par
    # rapport : le quota n'y est jamais en cause, mais le texte part au client
    # sous la signature du cabinet, et une phrase inventée y devient opposable.
    #
    # Séparer les deux permet de mettre chaque fournisseur là où il est bon :
    # le plus généreux en quota sur le dépouillement, le plus sobre en
    # invention sur la prose. Vide : le même pour tout.
    llm_prose_provider: str = ""
    llm_max_concurrency: int = 3
    llm_timeout_seconds: int = 120
    llm_log_payload: bool = True

    pii_redaction: bool = True
    redact_demographics: bool = True

    storage_backend: Literal["local", "s3"] = "local"
    storage_path: str = "/data/cv"
    s3_bucket: str = ""
    s3_endpoint_url: str = ""
    s3_region: str = "us-east-1"
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # NoDecode: CORS_ORIGINS is a plain comma-separated string in .env, not JSON.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    public_rate_limit_per_hour: int = 20

    # Boîte de candidatures : amorçage seulement.
    #
    # Ces valeurs servent de point de départ à une installation neuve. Le
    # réglage courant vit en base et se change depuis Paramètres › Boîte de
    # candidatures : l'adresse de recrutement change avec les campagnes, et un
    # mot de passe d'application se révoque sans prévenir. Modifier ce fichier
    # après le premier démarrage n'a plus d'effet.
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"

    # Accès Microsoft, pour la réception comme pour l'envoi. Microsoft a
    # supprimé l'authentification par mot de passe sur IMAP, POP et SMTP : une
    # boîte Outlook ne s'ouvre qu'avec un jeton, et ces trois valeurs servent à
    # l'obtenir.
    #
    # Elles se posent au déploiement, avec le reste de la configuration
    # serveur : contrairement à un mot de passe d'application, elles ne se
    # révoquent pas toutes seules et n'ont pas à être changées en cours
    # d'exploitation. L'écran Paramètres permet malgré tout de les corriger
    # sans rouvrir un accès à la machine — et ce qui y est enregistré prime.
    oauth_tenant: str = ""
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    # Comptes personnels outlook.com seulement : Microsoft n'y autorise pas le
    # flux application. Inutile avec une adresse Microsoft 365.
    oauth_refresh_token: str = ""

    # Envoi. Même logique d'amorçage que la réception : le réglage courant vit
    # en base. Vide par défaut, et un envoi sans configuration échoue de façon
    # explicite plutôt que d'être silencieusement perdu.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: bool = True
    smtp_expediteur: str = ""

    # Adresse publique de l'application, pour les liens envoyés par courriel
    # (activation d'un accès client, page d'un avis). Sans elle, les messages
    # partent sans lien plutôt qu'avec un lien vers « localhost ».
    url_publique: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
