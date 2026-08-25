"""Schémas de la chaîne de recrutement.

Les noms de champs suivent le vocabulaire métier français, comme les modèles et
les moteurs de calcul : une seule terminologie du formulaire jusqu'à la grille.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, EmailStr, Field, model_validator

from app.domain.referentiel import MotifElimination, Sexe, TypeAvis
from app.models.enums import (
    Provenance,
    SourceCandidature,
    StatutAvis,
    StatutCandidature,
    StatutMandat,
)

Lecture = ConfigDict(from_attributes=True)

# Les colonnes JSON sont nullables en base — une liste vide et « pas de valeur »
# n'ont pas à être distinguées ici, donc NULL se lit comme [].
ListeTexte = Annotated[list[str], BeforeValidator(lambda v: v or [])]


# --- client -----------------------------------------------------------------


class ClientBase(BaseModel):
    nom: str = Field(min_length=1, max_length=255)
    secteur: str | None = Field(default=None, max_length=255)
    contact_nom: str | None = Field(default=None, max_length=255)
    contact_email: EmailStr | None = None
    notes: str | None = None


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    nom: str | None = Field(default=None, min_length=1, max_length=255)
    secteur: str | None = None
    contact_nom: str | None = None
    contact_email: EmailStr | None = None
    notes: str | None = None


class ClientOut(ClientBase):
    model_config = Lecture

    id: str
    created_at: datetime
    archive_le: datetime | None = None
    nombre_mandats: int = 0


# --- mandat -----------------------------------------------------------------


class MandatBase(BaseModel):
    intitule: str = Field(min_length=1, max_length=512)
    reference: str | None = Field(default=None, max_length=128)
    statut: StatutMandat = StatutMandat.PROSPECT
    type_attribution: TypeAvis | None = None
    date_ami: date | None = None
    date_offre: date | None = None
    date_attribution: date | None = None
    notes: str | None = None


class MandatCreate(MandatBase):
    client_id: str


class MandatUpdate(BaseModel):
    intitule: str | None = Field(default=None, min_length=1, max_length=512)
    reference: str | None = None
    statut: StatutMandat | None = None
    type_attribution: TypeAvis | None = None
    date_ami: date | None = None
    date_offre: date | None = None
    date_attribution: date | None = None
    notes: str | None = None


class MandatOut(MandatBase):
    model_config = Lecture

    id: str
    client_id: str
    client_nom: str | None = None
    created_at: datetime
    archive_le: datetime | None = None
    nombre_postes: int = 0


# --- poste ------------------------------------------------------------------


class RestrictionIn(BaseModel):
    """Conditions restrictives. La justification devient obligatoire dès
    qu'une borne est posée — la même règle qu'en base et dans le moteur."""

    age_min: int | None = Field(default=None, ge=0, le=120)
    age_max: int | None = Field(default=None, ge=0, le=120)
    sexe: Sexe | None = None
    nationalites: ListeTexte = Field(default_factory=list)
    justification: str = ""

    @model_validator(mode="after")
    def _exiger_justification(self) -> RestrictionIn:
        active = any(
            (
                self.age_min is not None,
                self.age_max is not None,
                self.sexe is not None,
                bool(self.nationalites),
            )
        )
        if active and not self.justification.strip():
            raise ValueError(
                "Une condition d'âge, de sexe ou de nationalité doit être justifiée."
            )
        if self.age_min is not None and self.age_max is not None and self.age_min > self.age_max:
            raise ValueError("L'âge minimum ne peut pas dépasser l'âge maximum.")
        return self


class PosteBase(BaseModel):
    intitule: str = Field(min_length=1, max_length=512)
    departement: str | None = Field(default=None, max_length=255)
    description: str | None = None
    missions: ListeTexte = Field(default_factory=list)
    nombre_a_pourvoir: int = Field(default=1, ge=1)

    niveau_min: int = Field(default=3, ge=0, le=8)
    domaines_acceptes: ListeTexte = Field(default_factory=list)
    annees_experience_min: int = Field(default=0, ge=0, le=60)
    annees_experience_specifique_min: int = Field(default=0, ge=0, le=60)
    domaines_experience: ListeTexte = Field(default_factory=list)
    pieces_requises: ListeTexte = Field(default_factory=list)
    pieces_facultatives: ListeTexte = Field(default_factory=list)
    langues_requises: ListeTexte = Field(default_factory=list)
    nombre_a_retenir: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _pieces_distinctes(self) -> PosteBase:
        doublons = set(self.pieces_requises) & set(self.pieces_facultatives)
        if doublons:
            raise ValueError(
                "Une pièce ne peut pas être à la fois exigée et facultative : "
                + ", ".join(sorted(doublons))
            )
        return self

    @model_validator(mode="after")
    def _coherence_experience(self) -> PosteBase:
        if self.annees_experience_specifique_min > self.annees_experience_min:
            raise ValueError(
                "L'expérience spécifique demandée ne peut pas dépasser l'expérience "
                "générale : une expérience spécifique est aussi une expérience."
            )
        return self


class PosteCreate(PosteBase):
    restriction: RestrictionIn = Field(default_factory=RestrictionIn)


class PosteUpdate(BaseModel):
    intitule: str | None = Field(default=None, min_length=1, max_length=512)
    departement: str | None = None
    description: str | None = None
    missions: list[str] | None = None
    nombre_a_pourvoir: int | None = Field(default=None, ge=1)
    niveau_min: int | None = Field(default=None, ge=0, le=8)
    domaines_acceptes: list[str] | None = None
    annees_experience_min: int | None = Field(default=None, ge=0, le=60)
    annees_experience_specifique_min: int | None = Field(default=None, ge=0, le=60)
    domaines_experience: list[str] | None = None
    pieces_requises: list[str] | None = None
    pieces_facultatives: list[str] | None = None
    langues_requises: list[str] | None = None
    nombre_a_retenir: int | None = Field(default=None, ge=1)
    restriction: RestrictionIn | None = None


class PosteOut(PosteBase):
    model_config = Lecture

    id: str
    mandat_id: str
    created_at: datetime
    restriction: RestrictionIn = Field(default_factory=RestrictionIn)
    seuil_preselection: float
    seuil_nominal: float
    seuil_justification: str | None = None
    bareme: dict | None = None
    nombre_candidatures: int = 0


class SeuilIn(BaseModel):
    """Abaisser le seuil exige une justification ; le relever non."""

    seuil: float = Field(ge=0, le=100)
    justification: str = ""


class BaremeIn(BaseModel):
    bareme: dict


# --- avis -------------------------------------------------------------------


class AvisBase(BaseModel):
    reference: str | None = Field(default=None, max_length=128)
    type_avis: TypeAvis = TypeAvis.NATIONAL
    texte: str | None = None
    date_publication: date | None = None
    date_cloture: date | None = None
    canaux: ListeTexte = Field(default_factory=list)
    accepte_candidatures: bool = True


class AvisCreate(AvisBase):
    pass


class AvisUpdate(BaseModel):
    reference: str | None = None
    type_avis: TypeAvis | None = None
    texte: str | None = None
    date_publication: date | None = None
    date_cloture: date | None = None
    canaux: list[str] | None = None
    accepte_candidatures: bool | None = None


class AvisOut(AvisBase):
    model_config = Lecture

    id: str
    poste_id: str
    statut: StatutAvis
    cle_publique: str
    created_at: datetime


# --- candidature ------------------------------------------------------------


class DiplomeIn(BaseModel):
    intitule: str = Field(min_length=1, max_length=512)
    niveau: int = Field(ge=0, le=8)
    domaine: str = Field(min_length=1, max_length=255)
    etablissement: str | None = None
    annee: int | None = Field(default=None, ge=1900, le=2100)


class DiplomeOut(DiplomeIn):
    model_config = Lecture

    id: str
    provenance: Provenance


class ExperienceIn(BaseModel):
    poste: str = Field(min_length=1, max_length=512)
    employeur: str = Field(min_length=1, max_length=512)
    debut: date
    fin: date | None = None
    domaines: ListeTexte = Field(default_factory=list)
    pays: str | None = None

    @model_validator(mode="after")
    def _ordre_des_dates(self) -> ExperienceIn:
        if self.fin is not None and self.fin < self.debut:
            raise ValueError("La date de fin précède la date de début.")
        return self


class ExperienceOut(ExperienceIn):
    model_config = Lecture

    id: str
    provenance: Provenance


class CandidatIn(BaseModel):
    nom: str = Field(min_length=1, max_length=255)
    prenom: str = Field(min_length=1, max_length=255)
    email: EmailStr | None = None
    telephone: str | None = Field(default=None, max_length=64)
    adresse: str | None = Field(default=None, max_length=512)
    date_naissance: date | None = None
    sexe: Sexe | None = None
    nationalites: ListeTexte = Field(default_factory=list)
    langues: ListeTexte = Field(default_factory=list)
    certifications: ListeTexte = Field(default_factory=list)
    diplomes: list[DiplomeIn] = Field(default_factory=list)
    experiences: list[ExperienceIn] = Field(default_factory=list)


class CandidatOut(BaseModel):
    model_config = Lecture

    id: str
    nom: str
    prenom: str
    email: str | None = None
    telephone: str | None = None
    adresse: str | None = None
    date_naissance: date | None = None
    sexe: Sexe | None = None
    nationalites: ListeTexte = Field(default_factory=list)
    langues: ListeTexte = Field(default_factory=list)
    certifications: ListeTexte = Field(default_factory=list)
    provenance: Provenance
    verifie_le: datetime | None = None
    diplomes: list[DiplomeOut] = Field(default_factory=list)
    experiences: list[ExperienceOut] = Field(default_factory=list)


class CandidatureCreate(BaseModel):
    candidat: CandidatIn
    source: SourceCandidature = SourceCandidature.IMPORT_MANUEL
    recue_le: datetime | None = None
    # Codes des pièces effectivement reçues, cochées par les RH. Le fichier
    # peut être joint plus tard : la complétude se juge sur la réception.
    pieces_fournies: ListeTexte = Field(default_factory=list)


class LigneNotationOut(BaseModel):
    model_config = Lecture

    code: str
    libelle: str
    points: float
    points_max: float
    detail: str | None = None


class NotationOut(BaseModel):
    model_config = Lecture

    total: float
    total_max: float
    seuil: float
    atteint_le_seuil: bool
    note_manuelle: float | None = None
    note_manuelle_motif: str | None = None
    calcule_le: datetime
    lignes: list[LigneNotationOut] = Field(default_factory=list)


class EliminationOut(BaseModel):
    model_config = Lecture

    id: str
    motif: MotifElimination
    libelle: str = ""
    attendu: str | None = None
    constate: str | None = None
    justification_poste: str | None = None
    sur_donnee_non_verifiee: bool
    leve_le: datetime | None = None
    leve_motif: str | None = None


class DoublonOut(BaseModel):
    """Une autre candidature du même poste qui ressemble à celle-ci.

    Signalée, jamais bloquante : un CV renvoyé en version corrigée n'est pas
    une fraude, et c'est aux RH de trancher.
    """

    candidature_id: str
    nom_complet: str
    libelle: str


class PieceOut(BaseModel):
    model_config = Lecture

    id: str
    type_piece: str
    # Absent tant que la pièce est constatée reçue sans être encore classée.
    nom_fichier: str | None = None
    taille_octets: int | None = None


class CandidatureListItem(BaseModel):
    model_config = Lecture

    id: str
    statut: StatutCandidature
    source: SourceCandidature
    recue_le: datetime
    nom: str
    prenom: str
    note: float | None = None
    total_max: float | None = None
    atteint_le_seuil: bool | None = None
    motifs: list[MotifElimination] = Field(default_factory=list)
    a_verifier: bool = False
    doublons: int = 0


class CandidatureOut(BaseModel):
    model_config = Lecture

    id: str
    poste_id: str
    statut: StatutCandidature
    source: SourceCandidature
    recue_le: datetime
    notes_rh: str | None = None
    candidat: CandidatOut
    notation: NotationOut | None = None
    eliminations: list[EliminationOut] = Field(default_factory=list)
    pieces: list[PieceOut] = Field(default_factory=list)
    doublons: list[DoublonOut] = Field(default_factory=list)


class CandidaturesPage(BaseModel):
    items: list[CandidatureListItem]
    total: int
    page: int
    page_size: int


class NoteManuelleIn(BaseModel):
    note: float | None = Field(default=None, ge=0, le=100)
    motif: str = ""

    @model_validator(mode="after")
    def _motif_obligatoire(self) -> NoteManuelleIn:
        if self.note is not None and not self.motif.strip():
            raise ValueError("Une note saisie manuellement doit être motivée.")
        return self


class LeveeIn(BaseModel):
    motif: str = Field(min_length=1)


class VerificationIn(BaseModel):
    """Confirme les données du dossier après relecture d'un humain.

    C'est l'acte qui fait passer une donnée d'EXTRAIT_IA à VERIFIE_RH, et donc
    qui rend opposables les motifs qui en dépendent.
    """

    etat_civil: bool = False
    diplomes: bool = False
    experiences: bool = False


# --- grille de présélection -------------------------------------------------


class LigneGrille(BaseModel):
    """Une ligne de la grille, avec les colonnes du fichier de travail."""

    candidature_id: str
    nom: str
    prenom: str
    age: int | None = None
    nationalite: str | None = None
    dernier_diplome: str | None = None
    structure_employeur: str | None = None
    ecole_universite: str | None = None
    adresse: str | None = None
    note: float | None = None
    total_max: float | None = None
    preselectionne: bool = False
    elimine: bool = False
    motifs: ListeTexte = Field(default_factory=list)
    doublons: int = 0


class GroupeElimination(BaseModel):
    motif: MotifElimination
    libelle: str
    lignes: list[LigneGrille] = Field(default_factory=list)


class GrilleOut(BaseModel):
    """La grille de présélection et le tableau d'élimination, ensemble.

    Les deux sortent du même calcul : les produire séparément laisserait
    dériver les totaux annoncés au client.
    """

    poste_id: str
    poste_intitule: str
    client_nom: str | None = None
    mandat_intitule: str | None = None
    reference_avis: str | None = None
    type_avis: TypeAvis | None = None
    date_reference: date | None = None
    seuil: float
    total_max: float
    nombre_candidatures: int
    nombre_preselectionnes: int
    nombre_elimines: int
    nombre_a_verifier: int
    preselectionnes: list[LigneGrille] = Field(default_factory=list)
    non_retenus: list[LigneGrille] = Field(default_factory=list)
    elimines: list[GroupeElimination] = Field(default_factory=list)
