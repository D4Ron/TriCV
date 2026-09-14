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
    # Le seuil de présélection n'est plus un réglage d'établissement : il
    # variait trop d'un mandat à l'autre, et le fixer avant d'avoir vu la
    # distribution des notes revenait à décider à l'aveugle. Il se pose
    # désormais sur la grille du poste, une fois les dossiers notés.
    allow_self_registration: bool = False
    # Les candidatures reçues hors de tout avis — par la boîte de candidatures
    # ou par le formulaire du site — rejoignent-elles le vivier ?
    candidatures_spontanees: bool = True
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

    # --- envoi -------------------------------------------------------------
    smtp_actif: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_tls: bool = True
    smtp_expediteur: str = ""
    smtp_password_defini: bool = False
    envoi_utilisable: bool = False
    # Adresse à laquelle l'application est jointe de l'extérieur : elle sert à
    # construire les liens envoyés par courriel, que le serveur ne peut pas
    # deviner depuis sa propre adresse d'écoute.
    url_publique: str = ""


class ReglagesIn(BaseModel):
    """Les seuls réglages modifiables sans toucher au serveur."""

    redact_demographics: bool | None = None
    allow_self_registration: bool | None = None
    candidatures_spontanees: bool | None = None

    # Boîte de candidatures. Un mot de passe vide vaut « inchangé » : le
    # formulaire ne peut pas réafficher le secret, donc enregistrer sans y
    # toucher ne doit pas déconnecter la boîte.
    courriel_actif: bool | None = None
    imap_host: str | None = Field(default=None, max_length=255)
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    imap_user: str | None = Field(default=None, max_length=255)
    imap_password: str | None = Field(default=None, max_length=255)
    imap_folder: str | None = Field(default=None, max_length=255)

    # Envoi. Même règle pour le mot de passe : vide vaut « inchangé ».
    smtp_actif: bool | None = None
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_user: str | None = Field(default=None, max_length=255)
    smtp_password: str | None = Field(default=None, max_length=255)
    smtp_tls: bool | None = None
    smtp_expediteur: str | None = Field(default=None, max_length=255)
    url_publique: str | None = Field(default=None, max_length=512)
