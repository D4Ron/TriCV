from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "TriCV"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://tricv:tricv@db:5432/tricv"

    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 7

    seed_admin_email: str = "admin@tricv.example"
    seed_admin_password: str = "admin1234"

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
    max_upload_mb: int = 10
    public_rate_limit_per_hour: int = 20

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
