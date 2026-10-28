from __future__ import annotations

from datetime import datetime
from typing import Literal


from pydantic import BaseModel, Field, field_validator


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

    # --- boîte de candidatures (Microsoft 365) ------------------------------
    courriel_actif: bool = False
    adresse_boite: str = ""
    dossier_boite: str = "inbox"
    courriel_utilisable: bool = False

    # --- envoi -------------------------------------------------------------
    envoi_actif: bool = False
    adresse_expediteur: str = ""
    envoi_utilisable: bool = False
    # Adresse à laquelle l'application est jointe de l'extérieur : elle sert à
    # construire les liens envoyés par courriel, que le serveur ne peut pas
    # deviner depuis sa propre adresse d'écoute.
    url_publique: str = ""

    # --- accès Microsoft 365 -----------------------------------------------
    # Le secret n'est jamais renvoyé, même à un administrateur : l'écran a
    # seulement besoin de savoir s'il est renseigné pour afficher « défini »
    # plutôt qu'un champ vide qui laisserait croire à une boîte inconfigurée.
    oauth_tenant: str = ""
    oauth_client_id: str = ""
    oauth_client_secret_defini: bool = False

    # --- modèle d'IA -------------------------------------------------------
    # `llm_provider` et `llm_model` (plus haut) disent ce qui sert. Ceux-ci
    # disent ce que l'écran règle — vide : le .env décide.
    ia_fournisseur_ecran: str = ""
    ia_modele_ecran: str = ""
    ia_adresse_openai: str = ""
    ia_adresse_ollama: str = ""
    # Les clés ne sortent jamais. Pour chacune, d'où vient celle qui sert :
    # « ecran » (collée dans Paramètres), « serveur » (le .env), ou vide.
    ia_cles: dict[str, str] = Field(default_factory=dict)
    # Vrai quand l'écran impose quoi que ce soit : le bouton de retour au
    # réglage du serveur n'a de sens qu'alors.
    ia_regle_ecran: bool = False

    # --- aide aux candidats ------------------------------------------------
    # L'adresse réglée, et celle qui sera réellement affichée : vide, c'est la
    # boîte de recrutement qui sert, et l'écran doit le dire.
    contact_candidats: str = ""
    contact_effectif: str = ""


class ReglagesIn(BaseModel):
    """Les seuls réglages modifiables sans toucher au serveur."""

    redact_demographics: bool | None = None
    allow_self_registration: bool | None = None
    candidatures_spontanees: bool | None = None

    # Boîte de candidatures et envoi, sur Microsoft 365.
    courriel_actif: bool | None = None
    adresse_boite: str | None = Field(default=None, max_length=255)
    dossier_boite: str | None = Field(default=None, max_length=255)
    envoi_actif: bool | None = None
    adresse_expediteur: str | None = Field(default=None, max_length=255)
    url_publique: str | None = Field(default=None, max_length=512)

    oauth_tenant: str | None = Field(default=None, max_length=255)
    oauth_client_id: str | None = Field(default=None, max_length=255)
    # Vide vaut « inchangé » : le formulaire ne peut pas réafficher le secret,
    # donc enregistrer sans y toucher ne doit pas déconnecter la boîte.
    oauth_client_secret: str | None = Field(default=None, max_length=255)

    # Le modèle d'IA. Les clés suivent la même règle : vide vaut « inchangé ».
    # Le fournisseur vide laisse le .env décider.
    llm_provider: Literal["", "gemini", "anthropic", "openai", "ollama"] | None = None
    llm_model: str | None = Field(default=None, max_length=128)
    gemini_api_key: str | None = Field(default=None, max_length=255)
    anthropic_api_key: str | None = Field(default=None, max_length=255)
    llm_api_key: str | None = Field(default=None, max_length=255)
    llm_base_url: str | None = Field(default=None, max_length=255)
    ollama_base_url: str | None = Field(default=None, max_length=255)

    contact_candidats: str | None = Field(default=None, max_length=255)

    @field_validator("contact_candidats")
    @classmethod
    def _adresse_ou_vide(cls, valeur: str | None) -> str | None:
        """Vide est permis — la boîte de recrutement prend le relais."""
        if valeur is None or not valeur.strip():
            return valeur
        adresse = valeur.strip()
        if "@" not in adresse or " " in adresse or "." not in adresse.split("@")[-1]:
            raise ValueError("L'adresse de contact des candidats n'est pas une adresse email.")
        return adresse
