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
#
# La coercition doit se faire ici et non par `default_factory` : celui-ci ne
# joue que si la clé est absente, alors qu'une ligne écrite avant l'ajout de la
# colonne présente bel et bien la clé, à None. Une fiche ancienne rendait donc
# l'écran des postes inaccessible.
ListeTexte = Annotated[list[str], BeforeValidator(lambda v: v or [])]
DictionnaireListes = Annotated[dict[str, list[str]], BeforeValidator(lambda v: v or {})]


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


class GroupePiecesIn(BaseModel):
    """Un ensemble de pièces et la règle qui les lie.

    « Au moins une » sert aux équivalents — carte d'identité ou passeport ;
    « toutes » sert aux pièces indissociables — diplôme et attestation.
    """

    codes: list[str] = Field(min_length=1)
    mode: str = Field(default="TOUTES", pattern="^(TOUTES|AU_MOINS_UNE)$")
    libelle: str = Field(default="", max_length=255)

    @model_validator(mode="after")
    def _un_groupe_a_du_sens(self) -> GroupePiecesIn:
        if self.mode == "AU_MOINS_UNE" and len(set(self.codes)) < 2:
            raise ValueError(
                "Un groupe « au moins une » a besoin d'au moins deux pièces : "
                "avec une seule, exigez-la simplement."
            )
        return self


class ExperienceSpecifiqueIn(BaseModel):
    """Une expérience spécifique attendue.

    `poids` répartit les points du critère entre les exigences. Deux exigences
    de poids 1 et 2 se partagent les quinze points en cinq et dix.
    """

    libelle: str = Field(default="", max_length=255)
    domaines: ListeTexte = Field(default_factory=list)
    annees_min: int = Field(default=0, ge=0, le=60)
    poids: float = Field(default=1.0, gt=0, le=10)

    @model_validator(mode="after")
    def _nommable(self) -> ExperienceSpecifiqueIn:
        if not self.libelle.strip() and not self.domaines:
            raise ValueError(
                "Une expérience spécifique doit porter un libellé ou des domaines : "
                "sans l'un des deux, ni la grille ni le candidat ne savent de quoi "
                "il s'agit."
            )
        return self


class PosteBase(BaseModel):
    intitule: str = Field(min_length=1, max_length=512)
    departement: str | None = Field(default=None, max_length=255)
    description: str | None = None
    missions: ListeTexte = Field(default_factory=list)
    nombre_a_pourvoir: int = Field(default=1, ge=1)

    # Présentation : reprise par l'avis, jamais notée.
    localisation: str | None = Field(default=None, max_length=255)
    rattachement: str | None = Field(default=None, max_length=255)
    responsabilites: ListeTexte = Field(default_factory=list)
    competences_techniques: ListeTexte = Field(default_factory=list)
    competences_comportementales: ListeTexte = Field(default_factory=list)
    # Poste créé avec son seul intitulé : ses exigences sont des valeurs par
    # défaut, pas une décision. Voir `Poste.a_completer`.
    a_completer: Annotated[bool, BeforeValidator(lambda v: bool(v))] = False

    niveau_min: int = Field(default=3, ge=0, le=8)
    domaines_acceptes: ListeTexte = Field(default_factory=list)
    annees_experience_min: int = Field(default=0, ge=0, le=60)
    annees_experience_specifique_min: int = Field(default=0, ge=0, le=60)
    domaines_experience: ListeTexte = Field(default_factory=list)
    experiences_specifiques: Annotated[
        list[ExperienceSpecifiqueIn], BeforeValidator(lambda v: v or [])
    ] = Field(default_factory=list)
    pieces_requises: ListeTexte = Field(default_factory=list)
    pieces_facultatives: ListeTexte = Field(default_factory=list)
    groupes_pieces: Annotated[
        list[GroupePiecesIn], BeforeValidator(lambda v: v or [])
    ] = Field(default_factory=list)
    # Formats imposés par code de pièce : {"CV": ["pdf"]}.
    formats_pieces: DictionnaireListes = Field(default_factory=dict)
    pieces_libres_autorisees: Annotated[bool, BeforeValidator(lambda v: True if v is None else v)] = True
    langues_requises: ListeTexte = Field(default_factory=list)
    formation_complementaire_souhaitee: str | None = Field(default=None, max_length=512)
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
        seuils = [self.annees_experience_specifique_min] + [
            e.annees_min for e in self.experiences_specifiques
        ]
        if max(seuils) > self.annees_experience_min:
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
    localisation: str | None = Field(default=None, max_length=255)
    rattachement: str | None = Field(default=None, max_length=255)
    responsabilites: list[str] | None = None
    competences_techniques: list[str] | None = None
    competences_comportementales: list[str] | None = None
    a_completer: bool | None = None
    niveau_min: int | None = Field(default=None, ge=0, le=8)
    domaines_acceptes: list[str] | None = None
    annees_experience_min: int | None = Field(default=None, ge=0, le=60)
    annees_experience_specifique_min: int | None = Field(default=None, ge=0, le=60)
    domaines_experience: list[str] | None = None
    experiences_specifiques: list[ExperienceSpecifiqueIn] | None = None
    pieces_requises: list[str] | None = None
    pieces_facultatives: list[str] | None = None
    groupes_pieces: list[GroupePiecesIn] | None = None
    formats_pieces: dict[str, list[str]] | None = None
    pieces_libres_autorisees: bool | None = None
    langues_requises: list[str] | None = None
    formation_complementaire_souhaitee: str | None = None
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
    # La fiche fournie par le client. Le chemin de stockage ne sort pas : le
    # fichier se télécharge par sa route, sous authentification.
    fiche_nom_fichier: str | None = None
    fiche_deposee_le: datetime | None = None
    # Vrai quand l'avis peut être rédigé à partir du texte de la fiche — un
    # document déposé, ou un texte collé.
    fiche_a_texte: bool = False


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
    # Exigée : c'est par là qu'on accuse réception, qu'on réclame une pièce et
    # qu'on convoque, et elle figure en colonne dans le tableau des
    # préqualifiés remis au client. Un dossier saisi sans adresse est un
    # dossier qu'on ne pourra pas traiter jusqu'au bout.
    #
    # Cette contrainte porte sur la **saisie** : un dossier déposé en lot
    # arrive sans rien, et c'est le dépouillement qui lit l'adresse dans le CV
    # (voir `depouillement._appliquer_contacts`). Rendre la colonne obligatoire
    # en base refuserait ces dépôts-là, qui sont le cas le plus courant.
    email: EmailStr
    telephone: str | None = Field(default=None, max_length=64)
    adresse: str | None = Field(default=None, max_length=512)
    date_naissance: date | None = None
    sexe: Sexe | None = None
    nationalites: ListeTexte = Field(default_factory=list)
    langues: ListeTexte = Field(default_factory=list)
    certifications: ListeTexte = Field(default_factory=list)
    # Séminaires, certificats, cycles courts. Enregistrés et montrés aux
    # RH ; aucune grille du cabinet ne leur attribue de points, donc
    # l'application ne leur en invente pas.
    formations_complementaires: ListeTexte = Field(default_factory=list)
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
    formations_complementaires: ListeTexte = Field(default_factory=list)
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
    # Le nom donné par le candidat à une pièce hors nomenclature — une lettre de
    # recommandation, une attestation. Vide sur une pièce codifiée, où le
    # libellé du référentiel fait foi.
    intitule_libre: str | None = None
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
    # Part humaine de la consistance du dossier. Nulle tant que personne n'a lu.
    appreciation_consistance: float | None = None
    appreciation_motif: str | None = None
    # Catégorie remise au client, calculée puis réinscriptible.
    qualification: str | None = None
    qualification_libelle: str | None = None
    qualification_manuelle: str | None = None
    qualification_motif: str | None = None
    # Plafond de l'appréciation pour ce poste. Annoncé plutôt que déduit :
    # l'écran ne doit pas recalculer la décomposition du barème.
    appreciation_max: float = 1.0
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


class AppreciationIn(BaseModel):
    """La part humaine de la consistance du dossier.

    Motivation et expression écrite ne se calculent pas : elles se lisent. La
    note est bornée par le barème du poste, et l'appréciation écrite est
    obligatoire — un point attribué sans justification ne serait pas opposable
    à un candidat qui conteste.
    """

    note: float | None = Field(default=None, ge=0, le=10)
    motif: str = ""

    @model_validator(mode="after")
    def _motif_obligatoire(self) -> AppreciationIn:
        if self.note is not None and not self.motif.strip():
            raise ValueError("Une appréciation du dossier doit être motivée.")
        return self


# --- entretien structuré ------------------------------------------------------


class LigneEntretienIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    points: float | None = Field(default=None, ge=0, le=100)
    commentaire: str = ""


class EntretienIn(BaseModel):
    """Ce qu'un juré remet après un entretien structuré.

    Une saisie partielle est acceptée — on note au fil de la séance — mais la
    note sur 100 le signale tant qu'un critère manque.
    """

    lignes: list[LigneEntretienIn] = Field(default_factory=list)
    # Le membre du panel qui remplit la fiche. Le processus réel en fait siéger
    # plusieurs et publie leur moyenne.
    jure: str = Field(default="Jury", max_length=255)
    date_entretien: date | None = None
    jury: str = ""
    observations: str = ""


class CritereEntretienIn(BaseModel):
    """Un critère de la grille négociée avec le client."""

    code: str = Field(min_length=1, max_length=64)
    libelle: str = Field(min_length=1, max_length=255)
    points_max: float = Field(gt=0, le=100)
    section: str = Field(default="", max_length=255)


class GrilleEntretienIn(BaseModel):
    """La grille d'un poste. `criteres` vide remet celle du cabinet."""

    criteres: list[CritereEntretienIn] | None = None


class LigneEntretienOut(BaseModel):
    code: str
    libelle: str
    points: float | None = None
    points_max: float
    commentaire: str | None = None
    section: str = ""


class FicheJureOut(BaseModel):
    """La fiche d'un juré : ses notes, et rien de celles des autres."""

    jure: str
    date_entretien: date | None = None
    observations: str | None = None
    lignes: list[LigneEntretienOut] = Field(default_factory=list)
    total: float = 0.0
    complet: bool = False


class EntretienOut(BaseModel):
    """L'état des entretiens d'une candidature, panel compris.

    `grille` porte toujours tous les critères, notés ou non : l'écran présente
    la grille entière, sans quoi un juré ne saurait pas ce qu'il lui reste à
    faire. `fiches` porte ce que chacun a mis.
    """

    candidature_id: str
    existe: bool = False
    jury: str | None = None
    grille: list[LigneEntretienOut] = Field(default_factory=list)
    sections: list[dict] = Field(default_factory=list)
    fiches: list[FicheJureOut] = Field(default_factory=list)

    # Moyenne du panel, et sa dispersion.
    total: float = 0.0
    total_max: float = 70.0
    complet: bool = False
    ecart_jures: float = 0.0

    # Les deux étapes, et leur somme.
    preselection_sur_cent: float = 0.0
    entretien_sur_cent: float = 0.0
    note_finale_sur_cent: float = 0.0


class QualificationIn(BaseModel):
    """Réinscrire la catégorie d'un dossier, avec sa raison.

    Le calcul propose ; un recruteur peut corriger — mais pas en silence.
    """

    qualification: str | None = Field(default=None, max_length=32)
    motif: str = ""

    @model_validator(mode="after")
    def _motif_obligatoire(self) -> QualificationIn:
        if self.qualification is not None and not self.motif.strip():
            raise ValueError("Changer la catégorie d'un dossier doit être motivé.")
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
    # Ce que la présélection apporte à la note finale sur 100, les entretiens
    # portant le reste. Sert à rédiger le rapport sans refaire le calcul.
    note_sur_cent: float | None = None
    # Rang au classement, et proposition effective au client. Le processus
    # distingue les deux : un dossier peut être préqualifié sans figurer parmi
    # les N que le client reçoit.
    rang: int | None = None
    propose: bool = False
    # Seconde étape : ce que le jury a attribué, et la note finale sur 100.
    # `entretien_complet` distingue un acquis partiel d'un résultat.
    note_entretien_sur_cent: float | None = None
    note_finale_sur_cent: float | None = None
    entretien_complet: bool = False
    # Fortement / partiellement / non qualifié — le classement que le client
    # reçoit, distinct du statut interne de traitement.
    qualification: str | None = None
    qualification_libelle: str | None = None
    preselectionne: bool = False
    elimine: bool = False
    # Vrai tant que personne n'a apprécié la motivation et l'expression
    # écrite : des points de consistance restent alors à prendre.
    appreciation_attendue: bool = False
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
    # Part de la présélection dans la note finale sur 100.
    poids_preselection: float = 30.0
    # Nombre de dossiers que le client attend, quand il est fixé.
    nombre_a_proposer: int | None = None
    # Répartition des notes obtenues, pour que le seuil se décide sur ce qu'on
    # voit plutôt que sur un chiffre choisi d'avance.
    distribution: list[dict] = Field(default_factory=list)
    nombre_candidatures: int
    nombre_proposes: int = 0
    nombre_entretiens: int = 0
    nombre_preselectionnes: int
    nombre_elimines: int
    nombre_a_verifier: int
    preselectionnes: list[LigneGrille] = Field(default_factory=list)
    non_retenus: list[LigneGrille] = Field(default_factory=list)
    elimines: list[GroupeElimination] = Field(default_factory=list)
