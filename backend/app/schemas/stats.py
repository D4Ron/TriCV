from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, Field


class ScoreBucket(BaseModel):
    label: str  # "0-19", "20-39", ...
    count: int


class SessionStats(BaseModel):
    total_candidates: int = 0
    by_recommendation: dict[str, int] = Field(default_factory=dict)
    by_hr_status: dict[str, int] = Field(default_factory=dict)
    by_analysis_status: dict[str, int] = Field(default_factory=dict)
    by_source: dict[str, int] = Field(default_factory=dict)
    average_score: float | None = None
    median_score: float | None = None
    above_threshold: int = 0
    score_threshold: int = 60
    distribution: list[ScoreBucket] = Field(default_factory=list)


class AuditLogOut(BaseModel):
    id: str
    action: str
    entity_type: str
    entity_id: str | None
    user_id: str | None
    user_name: str | None = None
    details: dict | None = None
    created_at: datetime


class SettingsOut(BaseModel):
    """Surfaced in the dashboard so the deployment's privacy posture is visible."""

    llm_provider: str
    llm_model: str
    pii_redaction: bool
    redact_demographics: bool
    # Garde-fou anti-abus du formulaire public, pas une politique de gestion :
    # les dépôts authentifiés n'ont aucune limite de taille.
    max_upload_mb: int
    # Réglables depuis l'interface ; les autres champs décrivent le
    # déploiement et restent en lecture seule.
    seuil_preselection_defaut: float = 20.0
    allow_self_registration: bool = False
    storage_backend: str
    spacy_models_loaded: list[str] = Field(default_factory=list)

    # --- boîte de candidatures ---------------------------------------------
    # Le mot de passe n'est jamais renvoyé, même à un administrateur : l'écran
    # a seulement besoin de savoir s'il est renseigné pour afficher « défini »
    # plutôt qu'un champ vide qui laisserait croire à une boîte inconfigurée.
    courriel_actif: bool = False
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_folder: str = "INBOX"
    imap_password_defini: bool = False
    courriel_utilisable: bool = False


class ReglagesIn(BaseModel):
    """Les seuls réglages modifiables sans toucher au serveur."""

    seuil_preselection_defaut: float | None = Field(default=None, ge=0, le=100)
    redact_demographics: bool | None = None
    allow_self_registration: bool | None = None

    # Boîte de candidatures. Un mot de passe vide vaut « inchangé » : le
    # formulaire ne peut pas réafficher le secret, donc enregistrer sans y
    # toucher ne doit pas déconnecter la boîte.
    courriel_actif: bool | None = None
    imap_host: str | None = Field(default=None, max_length=255)
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    imap_user: str | None = Field(default=None, max_length=255)
    imap_password: str | None = Field(default=None, max_length=255)
    imap_folder: str | None = Field(default=None, max_length=255)
