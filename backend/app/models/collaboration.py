"""Ce qui sort du cabinet : courriels, espace client, rapports, modèles imposés.

Le noyau du logiciel instruit des dossiers. Ce module porte tout ce qui
s'adresse à quelqu'un d'extérieur — un candidat qu'on convoque, un promoteur
qui suit son recrutement, un rapport qu'on livre. Ces objets ont en commun
d'être **des traces** : un message envoyé, un accès accordé, une version
validée. Ils ne se recalculent pas, ils s'écrivent une fois et se relisent.

L'accès client vit dans sa propre table plutôt que dans `user`. Un promoteur
n'est pas un utilisateur restreint du cabinet : c'est un tiers, qui ne voit
qu'un mandat et ne doit à aucun moment pouvoir emprunter un chemin
d'authentification interne. Deux tables, deux portes.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import JsonB, TimestampMixin, utcnow, uuid_pk
from app.models.enums import (
    AuteurEchange,
    EtatEtape,
    StatutEnvoi,
    StatutRapport,
    TypeEchange,
    UsageModele,
)


def nouveau_jeton() -> str:
    """Un jeton d'activation. Assez long pour être inattaquable par essais."""
    return secrets.token_urlsafe(32)


class AccesClient(Base, TimestampMixin):
    """L'espace de suivi ouvert au promoteur, le temps d'un mandat.

    Créé avec le mandat, activé par le destinataire via un lien à usage unique,
    fermé quand le mandat se clôt. Le compte n'est jamais « supprimé » : le
    fermer suffit, et l'historique des échanges reste attaché au dossier.
    """

    __tablename__ = "acces_client"

    id: Mapped[str] = uuid_pk()
    mandat_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("mandat.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    email: Mapped[str] = mapped_column(sa.String(255), index=True, nullable=False)
    nom: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    fonction: Mapped[str | None] = mapped_column(sa.String(255))

    # Nul tant que l'accès n'a pas été activé : le cabinet ne choisit jamais le
    # mot de passe du client, sinon il le connaîtrait.
    password_hash: Mapped[str | None] = mapped_column(sa.String(255))

    # Jeton d'activation, à usage unique. Effacé dès qu'il a servi, pour qu'un
    # lien retrouvé dans une boîte courriel ne rouvre rien.
    jeton_activation: Mapped[str | None] = mapped_column(
        sa.String(64), unique=True, index=True, default=nouveau_jeton
    )
    jeton_expire_le: Mapped[datetime | None] = mapped_column(sa.DateTime)

    active_le: Mapped[datetime | None] = mapped_column(sa.DateTime)
    dernier_acces_le: Mapped[datetime | None] = mapped_column(sa.DateTime)
    # Fermeture : expiration à la clôture du mandat, ou révocation manuelle.
    revoque_le: Mapped[datetime | None] = mapped_column(sa.DateTime, index=True)
    motif_revocation: Mapped[str | None] = mapped_column(sa.String(512))

    mandat = relationship("Mandat")

    __table_args__ = (
        # Un mandat, un interlocuteur. Un second contact chez le client passe
        # par un second accès sur le même mandat, d'où l'unicité par couple.
        sa.UniqueConstraint("mandat_id", "email", name="uq_acces_client_mandat_email"),
    )

    @property
    def actif(self) -> bool:
        return self.revoque_le is None

    @property
    def active(self) -> bool:
        return self.active_le is not None and self.revoque_le is None


class EchangeClient(Base):
    """Un message entre le cabinet et le promoteur, sur un mandat.

    Remplace le fil de courriels : la discussion vit à côté du dossier qu'elle
    concerne, et une demande de modification y est identifiée comme telle
    plutôt que noyée dans une phrase de politesse.
    """

    __tablename__ = "echange_client"

    id: Mapped[str] = uuid_pk()
    mandat_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("mandat.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Facultatif : un message peut viser un poste précis du mandat.
    poste_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("poste.id", ondelete="SET NULL"), index=True
    )
    auteur: Mapped[AuteurEchange] = mapped_column(
        sa.Enum(AuteurEchange, name="auteur_echange"), nullable=False
    )
    auteur_nom: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    type_echange: Mapped[TypeEchange] = mapped_column(
        sa.Enum(TypeEchange, name="type_echange"),
        default=TypeEchange.MESSAGE,
        nullable=False,
        index=True,
    )
    objet: Mapped[str | None] = mapped_column(sa.String(512))
    corps: Mapped[str] = mapped_column(sa.Text, nullable=False)

    # Un message arrivé par la boîte de candidatures et rattaché ici : on garde
    # l'identifiant du courriel pour ne pas le rattacher deux fois.
    message_id: Mapped[str | None] = mapped_column(sa.String(512), index=True)

    envoye_le: Mapped[datetime] = mapped_column(
        sa.DateTime, default=utcnow, nullable=False, index=True
    )
    lu_le: Mapped[datetime | None] = mapped_column(sa.DateTime)
    # Pour une demande de modification : quand le cabinet l'a traitée.
    traite_le: Mapped[datetime | None] = mapped_column(sa.DateTime)
    traite_par_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("user.id", ondelete="SET NULL")
    )


class EtapeMandat(Base):
    """Une étape du chronogramme, telle que le client la voit.

    Volontairement pauvre : un libellé, un état, une date indicative. Le
    promoteur doit savoir où en est son recrutement, pas combien de dossiers
    ont été écartés ni sur quels critères.
    """

    __tablename__ = "etape_mandat"

    id: Mapped[str] = uuid_pk()
    mandat_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("mandat.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    ordre: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    libelle: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    etat: Mapped[EtatEtape] = mapped_column(
        sa.Enum(EtatEtape, name="etat_etape"), default=EtatEtape.A_VENIR, nullable=False
    )
    date_prevue: Mapped[date | None] = mapped_column(sa.Date)
    date_reelle: Mapped[date | None] = mapped_column(sa.Date)
    # Une étape peut rester interne : le cabinet suit des jalons que le client
    # n'a pas à voir.
    visible_client: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)


class MessageEnvoye(Base):
    """Trace d'un courriel parti de l'application.

    Vaut preuve d'envoi. Le corps est conservé tel qu'expédié : reconstituer un
    message à partir de son modèle après coup donnerait un texte différent si le
    modèle a changé entre-temps.
    """

    __tablename__ = "message_envoye"

    id: Mapped[str] = uuid_pk()
    candidature_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("candidature.id", ondelete="CASCADE"), index=True
    )
    mandat_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("mandat.id", ondelete="CASCADE"), index=True
    )
    modele: Mapped[str | None] = mapped_column(sa.String(64))
    destinataire: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    sujet: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    corps: Mapped[str] = mapped_column(sa.Text, nullable=False)
    statut: Mapped[StatutEnvoi] = mapped_column(
        sa.Enum(StatutEnvoi, name="statut_envoi"),
        default=StatutEnvoi.ENVOYE,
        nullable=False,
        index=True,
    )
    erreur: Mapped[str | None] = mapped_column(sa.Text)
    envoye_le: Mapped[datetime] = mapped_column(
        sa.DateTime, default=utcnow, nullable=False, index=True
    )
    envoye_par_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("user.id", ondelete="SET NULL")
    )


class ModeleDocument(Base, TimestampMixin):
    """Un gabarit imposé par un client : trame d'avis, de rapport, format de CV.

    Certains commanditaires exigent leur propre présentation. Plutôt que de
    recoder un format par client, on stocke le fichier fourni et la
    correspondance entre ses repères et les champs du dossier ; la production
    consiste alors à remplir, pas à réinventer.

    `structure` porte cette correspondance, sous une forme volontairement
    ouverte : la variété des trames reçues ne se laisse pas mettre en colonnes.
    """

    __tablename__ = "modele_document"

    id: Mapped[str] = uuid_pk()
    # Rattaché au client, ou au mandat quand la trame ne vaut que pour lui.
    client_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("client.id", ondelete="CASCADE"), index=True
    )
    mandat_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("mandat.id", ondelete="CASCADE"), index=True
    )
    libelle: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    usage: Mapped[UsageModele] = mapped_column(
        sa.Enum(UsageModele, name="usage_modele"), nullable=False, index=True
    )
    nom_fichier: Mapped[str | None] = mapped_column(sa.String(512))
    chemin_stockage: Mapped[str | None] = mapped_column(sa.String(1024))
    type_mime: Mapped[str | None] = mapped_column(sa.String(255))
    empreinte: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    # Le texte extrait du gabarit, quand il s'en extrait : c'est sur lui que la
    # correspondance des champs se construit, et il évite de rouvrir le fichier
    # à chaque production.
    texte_source: Mapped[str | None] = mapped_column(sa.Text)
    structure: Mapped[dict | None] = mapped_column(JsonB)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    actif: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)


class Rapport(Base, TimestampMixin):
    """Le rapport de recrutement livré au client.

    Rédigé section par section : l'assistance propose un texte, une personne le
    corrige, une personne le valide. `sections` garde pour chacune son origine
    — proposée ou écrite — afin qu'on sache toujours ce qui a été relu.

    Le rapport n'est jamais généré « à la volée » au moment de l'export : il est
    enregistré, donc réexportable à l'identique dans six mois, quel que soit
    l'état des dossiers entre-temps.
    """

    __tablename__ = "rapport"

    id: Mapped[str] = uuid_pk()
    mandat_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("mandat.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    poste_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("poste.id", ondelete="CASCADE"), index=True
    )
    modele_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("modele_document.id", ondelete="SET NULL")
    )
    titre: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    # PRESELECTION | ENTRETIENS | FINAL — ce que le cabinet remet, et à quel
    # moment. Décide des sections produites. Stocké en texte plutôt qu'en enum
    # SQL : la liste des types s'allonge au rythme des demandes d'un client, et
    # aucune de ces valeurs n'est comparée en base.
    type_rapport: Mapped[str | None] = mapped_column(sa.String(32), index=True)
    statut: Mapped[StatutRapport] = mapped_column(
        sa.Enum(StatutRapport, name="statut_rapport"),
        default=StatutRapport.BROUILLON,
        nullable=False,
        index=True,
    )
    # [{"code", "titre", "contenu", "origine", "verrouillee"}]
    sections: Mapped[list | None] = mapped_column(JsonB)
    # Les données chiffrées au moment de la rédaction : effectifs, notes,
    # répartition. Figées pour que le texte et ses tableaux restent cohérents.
    donnees: Mapped[dict | None] = mapped_column(JsonB)
    redige_par_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("user.id", ondelete="SET NULL")
    )
    valide_le: Mapped[datetime | None] = mapped_column(sa.DateTime)
    valide_par_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("user.id", ondelete="SET NULL")
    )
    # Publié dans l'espace client : le promoteur peut le lire et le télécharger.
    partage_le: Mapped[datetime | None] = mapped_column(sa.DateTime)
