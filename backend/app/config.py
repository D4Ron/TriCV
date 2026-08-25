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

    llm_provider: Literal["gemini", "anthropic", "ollama"] = "gemini"
    llm_model: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://ollama:11434"
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
