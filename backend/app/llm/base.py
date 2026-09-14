from __future__ import annotations

import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import settings
from app.llm import prompts, prose

logger = logging.getLogger(__name__)

# Shared across every provider instance: free tiers rate-limit per key, not per
# object, so the cap has to be global to the process.
_semaphore = asyncio.Semaphore(settings.llm_max_concurrency)


def modele_configure(fournisseur: str, defaut: str = "") -> str:
    """Le modèle à employer pour ce fournisseur.

    Trois sources, par ordre de priorité : son propre réglage (`GEMINI_MODEL`),
    puis `LLM_MODEL` **s'il est le fournisseur principal**, puis son défaut.

    La condition du milieu est ce qui rend une chaîne de secours utilisable :
    `LLM_MODEL` nomme le modèle du principal, et le laisser déborder sur les
    suivants leur ferait demander un modèle qui n'existe pas chez eux.
    """
    propre = str(getattr(settings, f"{fournisseur}_model", "") or "").strip()
    if propre:
        return propre
    if fournisseur == settings.llm_provider and settings.llm_model.strip():
        return settings.llm_model.strip()
    return defaut


class LLMError(Exception):
    """Anything that stopped us getting a usable answer from the provider."""


class LLMConfigError(LLMError):
    """Missing key, unknown provider, unsupported payload — not worth retrying."""


class LLMIndisponible(LLMError):
    """Ce fournisseur ne peut pas servir maintenant : essayez-en un autre.

    Deux cas la lèvent, et un seul les réunit utilement — dans les deux,
    insister chez le même fournisseur ne donnera rien avant longtemps :

    - son allocation est épuisée (`LLMQuotaError`) ;
    - il est en panne, c'est-à-dire qu'il a rendu 5xx ou n'a pas répondu
      pendant les quatre tentatives.

    Ce qu'elle ne couvre pas, délibérément : une réponse illisible, qui ne dit
    rien de l'état du fournisseur, et une clé refusée, qui est une erreur de
    configuration à voir plutôt qu'à contourner chez le voisin.

    Toujours levée **après** l'échec des quatre tentatives. Un 503 « forte
    demande » se dissipe souvent dans les quinze secondes du repli ; celui qui
    y survit est une indisponibilité, et c'est exactement le jour où la seconde
    clé gagne son existence.
    """


class LLMQuotaError(LLMIndisponible):
    """Plus d'allocation chez ce fournisseur, et attendre n'y changera rien.

    Levée seulement après l'échec des quatre tentatives : une limite *par
    minute* se rattrape dans le temps du repli, une limite *par jour* non.
    """


# --- payloads ---------------------------------------------------------------


@dataclass(slots=True)
class CriterionSpec:
    id: str
    name: str
    description: str | None
    weight: int
    is_must_have: bool


@dataclass(slots=True)
class FichePayload:
    position: str
    description: str | None
    criteria: list[CriterionSpec]
    language: str = "fr"


@dataclass(slots=True)
class CvPayload:
    """Either redacted text (the default) or the original file bytes.

    Exactly one of `text` / `file_bytes` is set. Providers must handle both;
    `ollama` rejects the file form.
    """

    text: str | None = None
    file_bytes: bytes | None = None
    mime_type: str | None = None
    filename: str | None = None
    redacted: bool = True

    @property
    def is_document(self) -> bool:
        return self.file_bytes is not None


# --- validated provider output ---------------------------------------------


class ExtractedCandidate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    years_experience: int | None = Field(default=None, ge=0, le=70)
    education_level: str | None = None
    skills: list[str] = Field(default_factory=list)

    @field_validator("skills", mode="before")
    @classmethod
    def _coerce_skills(cls, v: object) -> object:
        if v is None:
            return []
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("years_experience", mode="before")
    @classmethod
    def _coerce_years(cls, v: object) -> object:
        if isinstance(v, str):
            digits = re.findall(r"\d+", v)
            return int(digits[0]) if digits else None
        if isinstance(v, float):
            return round(v)
        return v


class CriterionScoreResult(BaseModel):
    criterion_id: str
    score: float = Field(ge=0, le=100)
    justification: str = ""

    @field_validator("score", mode="before")
    @classmethod
    def _clamp(cls, v: object) -> object:
        try:
            return max(0.0, min(100.0, float(v)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise ValueError("score must be a number between 0 and 100") from None


class AnalysisResult(BaseModel):
    candidate: ExtractedCandidate = Field(default_factory=ExtractedCandidate)
    criterion_scores: list[CriterionScoreResult] = Field(default_factory=list)
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class CriterionDraft(BaseModel):
    name: str
    description: str | None = None
    weight: int = Field(default=5, ge=1, le=10)
    is_must_have: bool = False

    @field_validator("weight", mode="before")
    @classmethod
    def _clamp_weight(cls, v: object) -> object:
        try:
            return max(1, min(10, int(float(v))))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 5


class _CriterionDraftList(BaseModel):
    criteria: list[CriterionDraft] = Field(default_factory=list)


# --- JSON recovery ----------------------------------------------------------

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_json_object(raw: str) -> dict:
    """Models add fences and preambles despite being told not to. Recover anyway."""
    text = _FENCE.sub("", raw.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise LLMError(f"Provider did not return valid JSON. First 300 chars: {raw[:300]!r}")


# --- the interface ----------------------------------------------------------


# Un marqueur d'expurgation — [CANDIDATE_NAME], [ADDRESS_2] — n'est ni un
# employeur ni un intitulé de poste. Le modèle en recopie parfois un quand le
# texte expurgé lui en met un à la place d'un nom d'entreprise : la ligne
# rendue serait alors un employeur nommé « [ADDRESS_2] », affiché tel quel dans
# la grille remise au client.
_MARQUEUR = re.compile(r"\[[A-Z_]+(?:_\d+)?\]")


def _texte_propre(valeur: object) -> str:
    """None → "" et marqueurs retirés.

    Le modèle rend légitimement `null` là où le CV ne dit rien — le domaine
    d'un baccalauréat, par exemple. Refuser ce null invalidait l'objet entier,
    et `extraire_dossier` jetait alors **tout le dossier** : un diplôme sans
    domaine faisait perdre les six expériences qui l'accompagnaient.
    """
    if valeur is None:
        return ""
    return " ".join(_MARQUEUR.sub(" ", str(valeur)).split())


class DiplomeExtrait(BaseModel):
    """Un diplôme lu dans un dossier. `niveau` est le N de BAC+N."""

    intitule: str = ""
    niveau: int | None = None
    domaine: str = ""
    # Les mots du dossier, avant tout rapprochement avec le vocabulaire du
    # poste. Donner ce vocabulaire au modèle règle un vrai problème — « gestion
    # du personnel » et « ressources humaines » sont le même métier — mais le
    # pousse aussi à ranger sous l'intitulé attendu ce qui n'en est que voisin.
    # Garder les mots d'origine rend le rapprochement visible : le relecteur
    # voit qu'une « licence en mathématiques appliquées » a été comptée en
    # informatique, et peut le refuser.
    domaine_dossier: str = ""
    etablissement: str | None = None
    annee: int | None = None

    @field_validator("intitule", "domaine", "domaine_dossier", mode="before")
    @classmethod
    def _tolerer_null(cls, v: object) -> object:
        return _texte_propre(v)

    @field_validator("etablissement", mode="before")
    @classmethod
    def _nettoyer_etablissement(cls, v: object) -> object:
        return _texte_propre(v) or None

    @field_validator("niveau", mode="before")
    @classmethod
    def _borner_niveau(cls, v: object) -> object:
        if v in (None, ""):
            return None
        try:
            niveau = int(float(str(v).lower().replace("bac+", "").strip()))
        except (TypeError, ValueError):
            return None
        return niveau if 0 <= niveau <= 8 else None

    @field_validator("annee", mode="before")
    @classmethod
    def _borner_annee(cls, v: object) -> object:
        try:
            annee = int(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return annee if 1900 <= annee <= 2100 else None


class ExperienceExtraite(BaseModel):
    """Une expérience lue dans un dossier. Dates au format AAAA-MM."""

    poste: str = ""
    employeur: str = ""
    debut: str | None = None
    fin: str | None = None
    domaines: list[str] = Field(default_factory=list)
    pays: str | None = None

    @field_validator("poste", "employeur", mode="before")
    @classmethod
    def _tolerer_null(cls, v: object) -> object:
        return _texte_propre(v)

    @field_validator("pays", mode="before")
    @classmethod
    def _nettoyer_pays(cls, v: object) -> object:
        return _texte_propre(v) or None

    @field_validator("domaines", mode="before")
    @classmethod
    def _en_liste(cls, v: object) -> object:
        if isinstance(v, str):
            v = [x.strip() for x in v.split(",") if x.strip()]
        return [p for p in (_texte_propre(x) for x in (v or [])) if p]


class DossierExtrait(BaseModel):
    """Ce qu'un modèle peut proposer à partir d'un dossier.

    Volontairement dépourvu d'état civil : le nom, l'email, la date de
    naissance, le sexe et la nationalité sont retirés du texte avant l'envoi et
    détectés localement. Le modèle ne lit que le parcours professionnel.
    """

    diplomes: list[DiplomeExtrait] = Field(default_factory=list)
    experiences: list[ExperienceExtraite] = Field(default_factory=list)
    langues: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)

    @field_validator("langues", "certifications", mode="before")
    @classmethod
    def _en_liste(cls, v: object) -> object:
        if isinstance(v, str):
            v = [x.strip() for x in v.split(",") if x.strip()]
        return [p for p in (_texte_propre(x) for x in (v or [])) if p]


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def analyze_cv(self, cv: CvPayload, fiche: FichePayload) -> AnalysisResult: ...

    @abstractmethod
    async def structure_fiche(self, raw_text: str, language: str = "fr") -> list[CriterionDraft]: ...

    async def extraire_dossier(
        self, texte: str, domaines: Sequence[str] = ()
    ) -> DossierExtrait:
        """Propose le parcours lu dans un dossier déjà expurgé.

        `domaines` porte les intitulés que le poste emploie, pour que le
        parcours relevé soit nommé dans les termes que le barème compare.

        Non abstraite : un fournisseur qui ne sait pas le faire renvoie un
        dossier vide, ce qui laisse simplement le dépouillement à un humain.
        """
        return DossierExtrait()

    async def rediger(
        self, consigne: str, contexte: str, systeme: str = "", titre: str = ""
    ) -> str:
        """Propose un paragraphe à partir de données fournies.

        Sert aux avis et aux sections de rapport. Le retour est de la prose, non
        du JSON : il n'y a rien à valider automatiquement, et c'est justement
        pourquoi tout ce qui sort d'ici passe par une relecture avant d'exister
        ailleurs que dans un brouillon.

        `titre` est celui de la section, quand l'appelant le connaît : il sert
        au nettoyage à reconnaître un titre que le modèle aurait recopié.

        Un fournisseur qui n'en est pas capable renvoie une chaîne vide, et
        l'appelant présente alors un champ vierge à remplir à la main.
        """
        return ""

    async def repondre_json(
        self, consigne: str, contexte: str, systeme: str = ""
    ) -> dict:
        """Une question libre dont la réponse attendue est un objet JSON.

        Distincte de `rediger`, qui rend de la prose : les deux ne veulent pas
        le même mode chez le fournisseur, et les confondre revenait à demander
        du JSON en mode prose — ou l'inverse, ce qui remplissait les rapports
        d'accolades vides.
        """
        return {}


@dataclass(slots=True)
class Attachment:
    data: bytes
    mime_type: str
    filename: str = "cv.pdf"


class BaseLLMProvider(LLMProvider):
    """Prompting, validation and the one-shot repair retry, shared by all providers.

    Concrete providers implement `complete()` and nothing else, which is what
    keeps provider-specific code confined to this package.
    """

    supports_documents: bool = True

    @abstractmethod
    async def complete(
        self,
        system: str,
        user: str,
        attachment: Attachment | None = None,
        *,
        json_mode: bool = True,
    ) -> str: ...

    async def _guarded(
        self,
        system: str,
        user: str,
        attachment: Attachment | None,
        *,
        json_mode: bool = True,
    ) -> str:
        async with _semaphore:
            if settings.llm_log_payload:
                logger.info(
                    "[%s] payload -> provider (%s, %s):\n%s",
                    self.name,
                    "document attached" if attachment else "text only",
                    "json" if json_mode else "prose",
                    user,
                )
            return await self.complete(system, user, attachment, json_mode=json_mode)

    async def analyze_cv(self, cv: CvPayload, fiche: FichePayload) -> AnalysisResult:
        if cv.is_document and not self.supports_documents:
            raise LLMConfigError(
                f"The {self.name} provider cannot accept documents. Enable PII_REDACTION "
                f"so the CV is sent as text, or switch LLM_PROVIDER."
            )

        system = prompts.analysis_system_prompt(fiche.language)
        user = prompts.analysis_user_prompt(fiche, cv_text=cv.text)
        attachment = (
            Attachment(cv.file_bytes, cv.mime_type or "application/pdf", cv.filename or "cv.pdf")
            if cv.is_document and cv.file_bytes
            else None
        )

        raw = await self._guarded(system, user, attachment)
        try:
            return AnalysisResult.model_validate(parse_json_object(raw))
        except (ValidationError, LLMError) as exc:
            # Python unbinds the `as` name when the except block ends, so keep
            # the message before leaving it.
            first_error = str(exc)
            logger.warning("[%s] invalid analysis response, repairing: %s", self.name, first_error)

        repair = prompts.repair_prompt(user, raw, first_error)
        raw_retry = await self._guarded(system, repair, attachment)
        try:
            return AnalysisResult.model_validate(parse_json_object(raw_retry))
        except (ValidationError, LLMError) as second_error:
            raise LLMError(
                f"The model's response did not match the expected schema after a retry: "
                f"{second_error}"
            ) from second_error

    async def extraire_dossier(
        self, texte: str, domaines: Sequence[str] = ()
    ) -> DossierExtrait:
        raw = await self._guarded(
            prompts.extraction_system_prompt(domaines),
            prompts.extraction_user_prompt(texte),
            None,
        )
        try:
            return DossierExtrait.model_validate(parse_json_object(raw))
        except (ValidationError, LLMError) as exc:
            # Renvoyer un dossier vide en silence faisait passer une panne pour
            # un CV sans contenu : l'écran affichait « 0 diplôme, 0 expérience »
            # et rien n'indiquait qu'il fallait recommencer. Le dépouillement
            # attrape cette erreur et l'affiche ; la saisie manuelle reste
            # possible, mais on sait pourquoi.
            logger.warning("[%s] extraction illisible : %s", self.name, exc)
            raise LLMError(
                "La réponse du modèle n'a pas pu être lue. Relancez le dépouillement "
                "ou saisissez le parcours à la main."
            ) from exc

    async def rediger(
        self, consigne: str, contexte: str, systeme: str = "", titre: str = ""
    ) -> str:
        # `json_mode=False` : c'est de la prose qu'on demande ici. Le mode JSON
        # était armé sur tous les appels, y compris celui-ci — un modèle
        # contraint au JSON sans schéma à remplir rendait `{}` ou la phrase
        # emballée dans un objet, et c'est cela qui se retrouvait imprimé dans
        # les rapports.
        raw = await self._guarded(
            systeme or prompts.REDACTION_SYSTEM,
            prompts.redaction_user_prompt(consigne, contexte),
            None,
            json_mode=False,
        )
        # Seconde ligne : aucune consigne n'empêche complètement un modèle
        # d'encadrer sa prose. Voir `app.llm.prose`.
        return prose.nettoyer(raw, titre)

    async def repondre_json(
        self, consigne: str, contexte: str, systeme: str = ""
    ) -> dict:
        raw = await self._guarded(
            systeme or prompts.REDACTION_SYSTEM,
            prompts.redaction_user_prompt(consigne, contexte),
            None,
            json_mode=True,
        )
        return parse_json_object(raw)

    async def structure_fiche(self, raw_text: str, language: str = "fr") -> list[CriterionDraft]:
        system = prompts.fiche_system_prompt(language)
        user = prompts.fiche_user_prompt(raw_text, language)
        raw = await self._guarded(system, user, None)

        data = parse_json_object(raw)
        try:
            return _CriterionDraftList.model_validate(data).criteria
        except ValidationError as exc:
            raise LLMError(f"Could not read draft criteria from the model: {exc}") from exc


# Re-exported so callers never import a concrete provider module.
__all__ = [
    "AnalysisResult",
    "Attachment",
    "BaseLLMProvider",
    "CriterionDraft",
    "CriterionSpec",
    "CvPayload",
    "FichePayload",
    "LLMConfigError",
    "LLMError",
    "LLMIndisponible",
    "LLMProvider",
    "LLMQuotaError",
    "parse_json_object",
]
