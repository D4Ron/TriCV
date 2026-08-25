"""Ce que le vivier expose.

`provenance` et `verifie` accompagnent chaque profil et chaque ligne de
parcours : un état civil deviné depuis un en-tête d'email ne vaut pas un état
civil relu par un humain, et l'écran doit pouvoir le dire. Sans cette
distinction, le vivier présenterait des suppositions de la même manière que des
faits établis.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.referentiel import Sexe
from app.models.enums import Provenance, SourceCandidature, StatutCandidature


class VivierItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    nom: str
    prenom: str
    email: str | None = None
    telephone: str | None = None

    # Attributs sensibles : conservés localement, montrés aux RH, jamais
    # transmis à un service externe.
    sexe: Sexe | None = None
    age: int | None = None
    nationalites: list[str] = Field(default_factory=list)

    provenance: Provenance
    verifie: bool = False

    niveau_max: int | None = None
    niveau_libelle: str | None = None
    diplome_principal: str | None = None
    domaine_principal: str | None = None
    annees_experience: float = 0.0
    dernier_poste: str | None = None
    dernier_employeur: str | None = None

    nombre_candidatures: int = 0
    derniere_candidature: date | None = None
    postes_vises: list[str] = Field(default_factory=list)

    # Ce qui reste du dossier physique. Zéro fichier conservé et des pièces
    # purgées n'est pas une perte : c'est la purge qui a fait son travail.
    pieces_conservees: int = 0
    pieces_purgees: int = 0


class VivierPage(BaseModel):
    items: list[VivierItem] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class DiplomeVivier(BaseModel):
    intitule: str
    niveau: int
    niveau_libelle: str | None = None
    domaine: str
    etablissement: str | None = None
    annee: int | None = None
    provenance: Provenance


class ExperienceVivier(BaseModel):
    poste: str
    employeur: str
    debut: date
    fin: date | None = None
    domaines: list[str] = Field(default_factory=list)
    pays: str | None = None
    provenance: Provenance


class HistoriqueVivier(BaseModel):
    """Une candidature passée, telle qu'elle apparaît sur le profil."""

    candidature_id: str
    poste_id: str
    poste: str
    mandat: str
    client: str
    recue_le: datetime
    statut: StatutCandidature
    source: SourceCandidature
    note: float | None = None
    note_max: float | None = None
    atteint_le_seuil: bool | None = None
    pieces_conservees: int = 0
    pieces_purgees: int = 0
    mandat_archive: bool = False


class ProfilVivier(VivierItem):
    adresse: str | None = None
    date_naissance: date | None = None
    langues: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    diplomes: list[DiplomeVivier] = Field(default_factory=list)
    experiences: list[ExperienceVivier] = Field(default_factory=list)
    historique: list[HistoriqueVivier] = Field(default_factory=list)
