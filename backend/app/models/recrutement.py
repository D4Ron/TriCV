"""La chaîne de recrutement persistée : Client → Mandat → Poste → Avis → Candidature.

Le vocabulaire (niveaux, motifs, sexes, pièces) vient de `app.domain.referentiel`
et n'est pas redéclaré ici : les tables et les moteurs de calcul partagent les
mêmes énumérations, donc une valeur en base ne peut pas dériver du code métier.

`NiveauDiplome` est stocké en entier plutôt qu'en énumération nommée, pour que
la comparaison ordonnée reste disponible en SQL (`WHERE niveau_min <= 5`) et
pas seulement en Python.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.domain.referentiel import MotifElimination, Sexe, TypeAvis
from app.models.base import JsonB, TimestampMixin, uuid_pk, utcnow
from app.models.enums import (
    Provenance,
    SourceCandidature,
    StatutAvis,
    StatutCandidature,
    StatutMandat,
)


def nouvelle_cle_publique() -> str:
    return secrets.token_urlsafe(24)


class Client(Base, TimestampMixin):
    """L'organisation pour laquelle le cabinet recrute."""

    __tablename__ = "client"

    id: Mapped[str] = uuid_pk()
    nom: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    secteur: Mapped[str | None] = mapped_column(sa.String(255))
    contact_nom: Mapped[str | None] = mapped_column(sa.String(255))
    contact_email: Mapped[str | None] = mapped_column(sa.String(255))
    notes: Mapped[str | None] = mapped_column(sa.Text)
    # Archivé plutôt que supprimé : un dossier clos garde sa valeur de preuve.
    archive_le: Mapped[datetime | None] = mapped_column(sa.DateTime, index=True)

    mandats: Mapped[list["Mandat"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )


class Mandat(Base, TimestampMixin):
    """L'engagement décroché auprès d'un client.

    Porte aussi l'amont commercial (AMI, appel d'offre) : c'est le même objet
    avant et après l'attribution, ce qui évite de ressaisir le dossier une fois
    le marché gagné.
    """

    __tablename__ = "mandat"

    id: Mapped[str] = uuid_pk()
    client_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("client.id", ondelete="CASCADE"), index=True, nullable=False
    )
    reference: Mapped[str | None] = mapped_column(sa.String(128), index=True)
    intitule: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    statut: Mapped[StatutMandat] = mapped_column(
        sa.Enum(StatutMandat, name="statut_mandat"),
        default=StatutMandat.PROSPECT,
        nullable=False,
        index=True,
    )
    # Mode d'attribution du marché au cabinet : national, international, ou
    # gré à gré (attribution directe, sans mise en concurrence).
    type_attribution: Mapped[TypeAvis | None] = mapped_column(
        sa.Enum(TypeAvis, name="type_avis")
    )
    date_ami: Mapped[date | None] = mapped_column(sa.Date)
    date_offre: Mapped[date | None] = mapped_column(sa.Date)
    date_attribution: Mapped[date | None] = mapped_column(sa.Date)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    # Un mandat terminé ou abandonné s'archive : ses avis, ses grilles et ses
    # dossiers restent consultables, ils sortent simplement des listes.
    archive_le: Mapped[datetime | None] = mapped_column(sa.DateTime, index=True)

    client: Mapped[Client] = relationship(back_populates="mandats")
    postes: Mapped[list["Poste"]] = relationship(
        back_populates="mandat", cascade="all, delete-orphan"
    )


class Poste(Base, TimestampMixin):
    """La fiche de poste : ce que l'avis exigera, sous forme calculable."""

    __tablename__ = "poste"

    id: Mapped[str] = uuid_pk()
    mandat_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("mandat.id", ondelete="CASCADE"), index=True, nullable=False
    )
    intitule: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    departement: Mapped[str | None] = mapped_column(sa.String(255))
    description: Mapped[str | None] = mapped_column(sa.Text)
    missions: Mapped[list | None] = mapped_column(JsonB)
    nombre_a_pourvoir: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)

    # --- exigences ---------------------------------------------------------
    niveau_min: Mapped[int] = mapped_column(sa.Integer, default=3, nullable=False, index=True)
    domaines_acceptes: Mapped[list | None] = mapped_column(JsonB)
    annees_experience_min: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    annees_experience_specifique_min: Mapped[int] = mapped_column(
        sa.Integer, default=0, nullable=False
    )
    domaines_experience: Mapped[list | None] = mapped_column(JsonB)
    # Plusieurs expériences spécifiques attendues, chacune avec ses domaines,
    # son seuil d'années et son poids :
    #   [{"libelle": "passation des marchés", "domaines": [...],
    #     "annees_min": 5, "poids": 2}]
    # Vide ou absent = l'exigence unique portée par les deux champs ci-dessus,
    # qui reste la forme courante et la seule qu'écrivaient les avis jusqu'ici.
    experiences_specifiques: Mapped[list | None] = mapped_column(JsonB)
    pieces_requises: Mapped[list | None] = mapped_column(JsonB)
    # Acceptées sans être exigées : leur absence n'a jamais éliminé personne.
    pieces_facultatives: Mapped[list | None] = mapped_column(JsonB)
    # Groupes de pièces liées : « la CNI ou le passeport », « le diplôme et
    # l'attestation ». Une pièce exigée seule reste dans `pieces_requises`.
    groupes_pieces: Mapped[list | None] = mapped_column(JsonB)
    # Formats imposés, par code de pièce : {"CV": ["pdf"]}. Absent = tout
    # format accepté par le contrôle général (PDF, DOC, DOCX).
    formats_pieces: Mapped[dict | None] = mapped_column(JsonB)
    # Le candidat peut-il joindre des documents de son choix — une lettre de
    # recommandation, une attestation qu'il juge utile ?
    pieces_libres_autorisees: Mapped[bool] = mapped_column(
        sa.Boolean, default=True, nullable=False
    )
    # Vestige : il n'y a plus de limite de taille réglable. La colonne reste
    # pour ne pas imposer de migration aux bases existantes, mais rien ne la
    # lit — le stockage se maîtrise par la purge des mandats archivés.
    taille_max_mo: Mapped[int | None] = mapped_column(sa.Integer)
    langues_requises: Mapped[list | None] = mapped_column(JsonB)
    # Formation complémentaire souhaitée : information portée par l'avis et
    # comparée à la main. Aucune grille du cabinet ne la note.
    formation_complementaire_souhaitee: Mapped[str | None] = mapped_column(sa.String(512))

    # --- conditions restrictives -------------------------------------------
    # Données sensibles : elles ne quittent jamais l'installation locale, et
    # `restriction_justification` est obligatoire dès qu'une borne est posée
    # (contrainte appliquée par `RestrictionPoste` à la construction).
    restriction_age_min: Mapped[int | None] = mapped_column(sa.Integer)
    restriction_age_max: Mapped[int | None] = mapped_column(sa.Integer)
    restriction_sexe: Mapped[Sexe | None] = mapped_column(sa.Enum(Sexe, name="sexe"))
    restriction_nationalites: Mapped[list | None] = mapped_column(JsonB)
    restriction_justification: Mapped[str | None] = mapped_column(sa.Text)

    # --- barème ------------------------------------------------------------
    # Sérialisé : la répartition des points se règle par poste sans migration.
    bareme: Mapped[dict | None] = mapped_column(JsonB)
    # Grille des entretiens structurés, négociée avec le client mandat par
    # mandat : l'offre technique la présente comme « indicative », à valider.
    # NULL = la grille type du cabinet.
    bareme_entretien: Mapped[list | None] = mapped_column(JsonB)
    seuil_preselection: Mapped[float] = mapped_column(
        sa.Numeric(5, 2), default=20.0, nullable=False
    )
    seuil_nominal: Mapped[float] = mapped_column(sa.Numeric(5, 2), default=20.0, nullable=False)
    seuil_justification: Mapped[str | None] = mapped_column(sa.Text)
    nombre_a_retenir: Mapped[int | None] = mapped_column(sa.Integer)

    mandat: Mapped[Mandat] = relationship(back_populates="postes")
    avis: Mapped[list["Avis"]] = relationship(
        back_populates="poste", cascade="all, delete-orphan"
    )
    candidatures: Mapped[list["Candidature"]] = relationship(
        back_populates="poste", cascade="all, delete-orphan"
    )


class Avis(Base, TimestampMixin):
    """L'avis de recrutement publié, dérivé de la fiche de poste."""

    __tablename__ = "avis"

    id: Mapped[str] = uuid_pk()
    poste_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("poste.id", ondelete="CASCADE"), index=True, nullable=False
    )
    reference: Mapped[str | None] = mapped_column(sa.String(128))
    type_avis: Mapped[TypeAvis] = mapped_column(
        sa.Enum(TypeAvis, name="type_avis"), default=TypeAvis.NATIONAL, nullable=False
    )
    statut: Mapped[StatutAvis] = mapped_column(
        sa.Enum(StatutAvis, name="statut_avis"),
        default=StatutAvis.BROUILLON,
        nullable=False,
        index=True,
    )
    texte: Mapped[str | None] = mapped_column(sa.Text)
    date_publication: Mapped[date | None] = mapped_column(sa.Date)
    # Sert de date de référence à l'âge comme à l'ancienneté : la grille reste
    # ainsi reproductible quelle que soit la date du recalcul.
    date_cloture: Mapped[date | None] = mapped_column(sa.Date, index=True)
    # Plateformes de diffusion, avec la date d'envoi.
    canaux: Mapped[list | None] = mapped_column(JsonB)
    cle_publique: Mapped[str] = mapped_column(
        sa.String(64), default=nouvelle_cle_publique, unique=True, index=True, nullable=False
    )
    accepte_candidatures: Mapped[bool] = mapped_column(
        sa.Boolean, default=True, nullable=False
    )

    poste: Mapped[Poste] = relationship(back_populates="avis")


class Candidat(Base, TimestampMixin):
    """L'état civil, indépendant de la candidature : une personne peut
    postuler à plusieurs postes."""

    __tablename__ = "candidat"

    id: Mapped[str] = uuid_pk()
    nom: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    prenom: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(sa.String(255), index=True)
    telephone: Mapped[str | None] = mapped_column(sa.String(64))
    adresse: Mapped[str | None] = mapped_column(sa.String(512))

    # Attributs sensibles : conservés localement, montrés aux RH, et utilisés
    # au calcul uniquement si le poste déclare une condition les concernant.
    date_naissance: Mapped[date | None] = mapped_column(sa.Date)
    sexe: Mapped[Sexe | None] = mapped_column(sa.Enum(Sexe, name="sexe"))
    nationalites: Mapped[list | None] = mapped_column(JsonB)

    langues: Mapped[list | None] = mapped_column(JsonB)
    certifications: Mapped[list | None] = mapped_column(JsonB)
    # Formations complémentaires : séminaires, certificats, cycles courts.
    # Enregistrées et affichées, sans points — aucune grille du cabinet ne leur
    # en attribue, et en inventer serait la faute déjà commise sur les
    # entretiens.
    formations_complementaires: Mapped[list | None] = mapped_column(JsonB)

    provenance: Mapped[Provenance] = mapped_column(
        sa.Enum(Provenance, name="provenance"), default=Provenance.DECLARE, nullable=False
    )
    verifie_le: Mapped[datetime | None] = mapped_column(sa.DateTime)
    verifie_par_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("user.id", ondelete="SET NULL")
    )

    diplomes: Mapped[list["DiplomeCandidat"]] = relationship(
        back_populates="candidat", cascade="all, delete-orphan", lazy="selectin"
    )
    experiences: Mapped[list["ExperienceCandidat"]] = relationship(
        back_populates="candidat", cascade="all, delete-orphan", lazy="selectin"
    )
    candidatures: Mapped[list["Candidature"]] = relationship(
        back_populates="candidat", cascade="all, delete-orphan"
    )


class DiplomeCandidat(Base, TimestampMixin):
    __tablename__ = "diplome_candidat"

    id: Mapped[str] = uuid_pk()
    candidat_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("candidat.id", ondelete="CASCADE"), index=True, nullable=False
    )
    intitule: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    niveau: Mapped[int] = mapped_column(sa.Integer, nullable=False, index=True)
    domaine: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    etablissement: Mapped[str | None] = mapped_column(sa.String(255))
    annee: Mapped[int | None] = mapped_column(sa.Integer)

    provenance: Mapped[Provenance] = mapped_column(
        sa.Enum(Provenance, name="provenance"), default=Provenance.DECLARE, nullable=False
    )

    candidat: Mapped[Candidat] = relationship(back_populates="diplomes")


class ExperienceCandidat(Base, TimestampMixin):
    __tablename__ = "experience_candidat"

    id: Mapped[str] = uuid_pk()
    candidat_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("candidat.id", ondelete="CASCADE"), index=True, nullable=False
    )
    poste: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    employeur: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    debut: Mapped[date] = mapped_column(sa.Date, nullable=False)
    # NULL = poste toujours occupé ; la durée est arrêtée à la date de clôture.
    fin: Mapped[date | None] = mapped_column(sa.Date)
    domaines: Mapped[list | None] = mapped_column(JsonB)
    pays: Mapped[str | None] = mapped_column(sa.String(128))

    provenance: Mapped[Provenance] = mapped_column(
        sa.Enum(Provenance, name="provenance"), default=Provenance.DECLARE, nullable=False
    )

    candidat: Mapped[Candidat] = relationship(back_populates="experiences")


class Candidature(Base, TimestampMixin):
    __tablename__ = "candidature"
    __table_args__ = (
        sa.UniqueConstraint("poste_id", "candidat_id", name="uq_candidature_poste_candidat"),
        sa.Index("ix_candidature_poste_statut", "poste_id", "statut"),
        sa.Index("ix_candidature_spontanee", "spontanee"),
    )

    id: Mapped[str] = uuid_pk()
    # Nullable depuis les candidatures spontanées : quelqu'un peut adresser
    # son dossier sans qu'aucun avis ne soit ouvert. Le profil rejoint alors le
    # vivier, où il sera retrouvé le jour où un mandat lui correspond.
    poste_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("poste.id", ondelete="CASCADE"), index=True
    )
    candidat_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("candidat.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source: Mapped[SourceCandidature] = mapped_column(
        sa.Enum(SourceCandidature, name="source_candidature"),
        default=SourceCandidature.FORMULAIRE,
        nullable=False,
    )
    statut: Mapped[StatutCandidature] = mapped_column(
        sa.Enum(StatutCandidature, name="statut_candidature"),
        default=StatutCandidature.RECUE,
        nullable=False,
        index=True,
    )
    recue_le: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow, nullable=False)
    # Reçue hors de tout avis. Distinguée de `poste_id is None` seul, pour que
    # l'origine reste lisible même si le dossier est rattaché plus tard.
    spontanee: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    # Trace de l'arrivée par email, pour retrouver le message d'origine.
    message_id: Mapped[str | None] = mapped_column(sa.String(512), index=True)
    notes_rh: Mapped[str | None] = mapped_column(sa.Text)

    # Part humaine de la « consistance du dossier » : motivation et expression
    # écrite, qui ne se calculent pas. Porté par la candidature et non par la
    # notation, parce que la notation est effacée et recréée à chaque recalcul,
    # tandis qu'une lecture faite une fois n'a pas à être refaite.
    appreciation_consistance: Mapped[float | None] = mapped_column(sa.Numeric(4, 2))
    appreciation_motif: Mapped[str | None] = mapped_column(sa.Text)

    # Catégorie remise au client — fortement / partiellement / non qualifié.
    # Calculée à l'évaluation, mais réinscriptible : c'est un avis, et le
    # cabinet doit pouvoir le corriger sans toucher au barème.
    qualification: Mapped[str | None] = mapped_column(sa.String(32), index=True)
    qualification_manuelle: Mapped[str | None] = mapped_column(sa.String(32))
    qualification_motif: Mapped[str | None] = mapped_column(sa.Text)

    poste: Mapped[Poste] = relationship(back_populates="candidatures")
    candidat: Mapped[Candidat] = relationship(back_populates="candidatures")
    pieces: Mapped[list["PieceCandidature"]] = relationship(
        back_populates="candidature", cascade="all, delete-orphan", lazy="selectin"
    )
    notation: Mapped["Notation | None"] = relationship(
        back_populates="candidature", cascade="all, delete-orphan", uselist=False
    )
    entretiens: Mapped[list["Entretien"]] = relationship(
        back_populates="candidature", cascade="all, delete-orphan", lazy="selectin"
    )
    eliminations: Mapped[list["Elimination"]] = relationship(
        back_populates="candidature", cascade="all, delete-orphan", lazy="selectin"
    )


class PieceCandidature(Base, TimestampMixin):
    __tablename__ = "piece_candidature"

    id: Mapped[str] = uuid_pk()
    candidature_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("candidature.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Code de `PieceDossier`, ou libellé libre pour une pièce hors nomenclature.
    type_piece: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    # Nom donné par le candidat quand il joint un document de son choix. Sans
    # lui, « AUTRE » ne dirait rien au recruteur qui ouvre le dossier.
    intitule_libre: Mapped[str | None] = mapped_column(sa.String(255))
    # Nullables : une pièce peut être constatée reçue avant d'être classée —
    # dossier arrivé par courrier, ou pièces jointes d'un email pas encore
    # rangées. La complétude porte sur ce qui est reçu, pas sur ce qui est
    # déjà stocké.
    nom_fichier: Mapped[str | None] = mapped_column(sa.String(512))
    chemin_stockage: Mapped[str | None] = mapped_column(sa.String(512))
    type_mime: Mapped[str | None] = mapped_column(sa.String(128))
    taille_octets: Mapped[int | None] = mapped_column(sa.Integer)
    empreinte: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    texte_extrait: Mapped[str | None] = mapped_column(sa.Text)
    # Fichier supprimé après archivage du mandat. La ligne subsiste : la
    # complétude se juge sur la pièce reçue, pas sur le fichier conservé.
    purge_le: Mapped[datetime | None] = mapped_column(sa.DateTime)

    candidature: Mapped[Candidature] = relationship(back_populates="pieces")


class Notation(Base, TimestampMixin):
    """Le résultat du barème pour une candidature.

    `bareme_utilise` est une copie du barème au moment du calcul. Sans elle,
    retoucher le barème d'un poste réécrirait rétroactivement des grilles déjà
    remises au client.
    """

    __tablename__ = "notation"

    id: Mapped[str] = uuid_pk()
    candidature_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("candidature.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    total: Mapped[float] = mapped_column(sa.Numeric(5, 2), nullable=False, index=True)
    total_max: Mapped[float] = mapped_column(sa.Numeric(5, 2), nullable=False)
    seuil: Mapped[float] = mapped_column(sa.Numeric(5, 2), nullable=False)
    atteint_le_seuil: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, index=True)
    bareme_utilise: Mapped[dict | None] = mapped_column(JsonB)
    calcule_le: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow, nullable=False)
    # Note saisie par les RH, qui prime sur le calcul quand elle existe.
    note_manuelle: Mapped[float | None] = mapped_column(sa.Numeric(5, 2))
    note_manuelle_motif: Mapped[str | None] = mapped_column(sa.Text)

    candidature: Mapped[Candidature] = relationship(back_populates="notation")
    lignes: Mapped[list["LigneNotation"]] = relationship(
        back_populates="notation", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def note_retenue(self) -> float:
        return float(self.note_manuelle if self.note_manuelle is not None else self.total)


class LigneNotation(Base):
    __tablename__ = "ligne_notation"
    __table_args__ = (
        sa.UniqueConstraint("notation_id", "code", name="uq_ligne_notation_code"),
    )

    id: Mapped[str] = uuid_pk()
    notation_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("notation.id", ondelete="CASCADE"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    libelle: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    points: Mapped[float] = mapped_column(sa.Numeric(5, 2), nullable=False)
    points_max: Mapped[float] = mapped_column(sa.Numeric(5, 2), nullable=False)
    detail: Mapped[str | None] = mapped_column(sa.Text)

    notation: Mapped[Notation] = relationship(back_populates="lignes")


class Entretien(Base, TimestampMixin):
    """L'entretien structuré, et les points que le jury a attribués.

    Seconde étape du processus : la présélection vaut 30 points, l'entretien 70,
    et la note finale sur 100 est la somme des deux. Rien ici n'est calculé —
    ces points sont un jugement humain, porté par un jury en séance. L'aide
    automatique n'y a aucune place, et n'y accède pas.

    `bareme_utilise` fige la grille au moment de la saisie, pour la même raison
    que `Notation.bareme_utilise` : retoucher la répartition des 70 points ne
    doit pas réécrire une évaluation déjà rendue.

    Une candidature n'a qu'un entretien : reconvoquer quelqu'un, c'est corriger
    la même fiche, pas en ouvrir une seconde qui ferait douter de la bonne.
    """

    __tablename__ = "entretien"
    __table_args__ = (
        # Un juré, une fiche. Deux fiches du même juré pour le même candidat
        # fausseraient la moyenne sans que personne ne s'en aperçoive.
        sa.UniqueConstraint("candidature_id", "jure", name="uq_entretien_jure"),
    )

    id: Mapped[str] = uuid_pk()
    candidature_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("candidature.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Le membre du jury qui a rempli cette fiche. Le processus réel fait siéger
    # plusieurs personnes — sept sur un mandat récent — et la note publiée est
    # leur moyenne. Une seule fiche par candidature aurait écrasé six avis.
    jure: Mapped[str] = mapped_column(sa.String(255), nullable=False, default="Jury")
    date_entretien: Mapped[date | None] = mapped_column(sa.Date)
    # Composition du panel, en clair : la grille remise au client doit dire qui
    # a jugé, pas seulement combien de points ont été mis.
    jury: Mapped[str | None] = mapped_column(sa.Text)
    observations: Mapped[str | None] = mapped_column(sa.Text)
    bareme_utilise: Mapped[list | None] = mapped_column(JsonB)

    conduit_par_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("user.id", ondelete="SET NULL")
    )

    candidature: Mapped["Candidature"] = relationship(back_populates="entretiens")
    lignes: Mapped[list["LigneEntretien"]] = relationship(
        back_populates="entretien", cascade="all, delete-orphan", lazy="selectin"
    )


class LigneEntretien(Base, TimestampMixin):
    """Les points d'un critère d'entretien, avec ce qui les motive.

    Le commentaire n'est pas décoratif : une note attribuée en séance se
    défend des mois plus tard par ce qui a été observé, pas par le chiffre.
    """

    __tablename__ = "ligne_entretien"
    __table_args__ = (
        sa.UniqueConstraint("entretien_id", "code", name="uq_ligne_entretien_code"),
    )

    id: Mapped[str] = uuid_pk()
    entretien_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("entretien.id", ondelete="CASCADE"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    libelle: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    points: Mapped[float] = mapped_column(sa.Numeric(5, 2), nullable=False)
    points_max: Mapped[float] = mapped_column(sa.Numeric(5, 2), nullable=False)
    commentaire: Mapped[str | None] = mapped_column(sa.Text)

    entretien: Mapped[Entretien] = relationship(back_populates="lignes")


class Elimination(Base, TimestampMixin):
    """Un motif retenu contre une candidature, avec son arithmétique.

    Conservé même après levée : `leve_le` documente qui a écarté le motif et
    pourquoi, plutôt que de faire disparaître la trace.
    """

    __tablename__ = "elimination"
    __table_args__ = (
        sa.UniqueConstraint("candidature_id", "motif", name="uq_elimination_motif"),
        sa.Index("ix_elimination_motif", "motif"),
    )

    id: Mapped[str] = uuid_pk()
    candidature_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("candidature.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    motif: Mapped[MotifElimination] = mapped_column(
        sa.Enum(MotifElimination, name="motif_elimination"), nullable=False
    )
    attendu: Mapped[str | None] = mapped_column(sa.Text)
    constate: Mapped[str | None] = mapped_column(sa.Text)
    justification_poste: Mapped[str | None] = mapped_column(sa.Text)
    # Vrai quand le motif repose sur une donnée seulement proposée par
    # l'assistance automatique : il attend confirmation et n'élimine pas encore.
    sur_donnee_non_verifiee: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, nullable=False
    )

    leve_le: Mapped[datetime | None] = mapped_column(sa.DateTime)
    leve_par_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("user.id", ondelete="SET NULL")
    )
    leve_motif: Mapped[str | None] = mapped_column(sa.Text)

    candidature: Mapped[Candidature] = relationship(back_populates="eliminations")

    @property
    def actif(self) -> bool:
        return self.leve_le is None
