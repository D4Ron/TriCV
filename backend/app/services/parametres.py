"""Réglages modifiables depuis l'application.

Le fichier `.env` reste la valeur de départ ; ce module ne fait que la
surcharger quand quelqu'un a réglé la valeur dans l'interface. Ce partage est
délibéré : ce qui touche à l'infrastructure — fournisseur de modèle, stockage,
stockage — appartient au déploiement et n'a rien à faire dans un écran ; ce qui
relève de la pratique de recrutement — expurgation des données sensibles,
inscription libre, candidatures spontanées, boîtes de courriel — change avec
l'usage et doit pouvoir se régler sans redémarrage ni accès au serveur.

Les boîtes de courriel font exception à la règle « les secrets restent au
déploiement » : leurs mots de passe sont réglables ici. Le motif est pratique et
assumé — l'adresse de recrutement change avec les campagnes, et un mot de passe
d'application Gmail se révoque et se recrée. Le secret n'est jamais renvoyé par
l'API ; l'interface sait seulement s'il est renseigné.

Chaque écriture passe au journal d'audit par l'appelant : l'expurgation des
données démographiques ou l'ouverture des candidatures spontanées sont des
décisions, pas des préférences. Les valeurs des secrets n'y figurent pas,
seulement leur nom.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.db import Base


class Parametre(Base):
    """Une surcharge du fichier de configuration, réglée depuis l'interface."""

    __tablename__ = "parametre"

    cle: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    valeur: Mapped[str] = mapped_column(sa.String(512), nullable=False)


# Clés reconnues, avec leur valeur par défaut lue dans .env.
#
# Le seuil de présélection n'en fait plus partie. Il variait trop d'un mandat à
# l'autre pour qu'une valeur d'établissement ait un sens, et le fixer avant
# d'avoir vu la distribution des notes revenait à décider à l'aveugle. Il se
# décide désormais sur la grille du poste, une fois les dossiers notés, et
# c'est ce premier geste qui devient la référence à justifier si on l'abaisse.
REDACTION_DEMOGRAPHIQUE = "redact_demographics"
INSCRIPTION_LIBRE = "allow_self_registration"

# Les candidatures reçues hors de tout avis. Le cabinet peut vouloir les
# accueillir en permanence — un profil rare vaut d'être connu avant qu'un mandat
# ne le demande — ou fermer la porte pendant une campagne chargée.
CANDIDATURES_SPONTANEES = "candidatures_spontanees"

# Boîte de candidatures. Elle se règle depuis l'interface parce que l'adresse
# de recrutement change avec les campagnes et les mots de passe d'application
# se renouvellent : demander un accès au serveur à chaque fois condamnerait la
# fonction à ne jamais être utilisée.
COURRIEL_ACTIF = "courriel_actif"
IMAP_HOTE = "imap_host"
IMAP_PORT = "imap_port"
IMAP_UTILISATEUR = "imap_user"
IMAP_MOT_DE_PASSE = "imap_password"
IMAP_DOSSIER = "imap_folder"

# Envoi. Séparé de la réception parce que les deux n'ont pas les mêmes
# serveurs ni forcément le même compte : on relève sur la boîte de candidatures
# et on peut vouloir écrire depuis l'adresse générale du cabinet.
SMTP_ACTIF = "smtp_actif"
SMTP_HOTE = "smtp_host"
SMTP_PORT = "smtp_port"
SMTP_UTILISATEUR = "smtp_user"
SMTP_MOT_DE_PASSE = "smtp_password"
SMTP_TLS = "smtp_tls"
SMTP_EXPEDITEUR = "smtp_expediteur"

# L'adresse à laquelle l'application est jointe depuis l'extérieur. Elle sert à
# construire les liens envoyés par courriel ; elle n'est pas devinable depuis le
# serveur, qui ne connaît que sa propre adresse d'écoute.
URL_PUBLIQUE = "url_publique"

# Ce que l'API ne renvoie jamais en clair.
SECRETS = frozenset({IMAP_MOT_DE_PASSE, SMTP_MOT_DE_PASSE})


@dataclass(slots=True)
class Reglages:
    redact_demographics: bool
    allow_self_registration: bool
    candidatures_spontanees: bool
    courriel_actif: bool
    imap_host: str
    imap_port: int
    imap_user: str
    imap_password: str
    imap_folder: str
    smtp_actif: bool
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_tls: bool
    smtp_expediteur: str
    url_publique: str

    @property
    def courriel_utilisable(self) -> bool:
        """Relevable : activé, et avec de quoi ouvrir une session."""
        return bool(
            self.courriel_actif and self.imap_host and self.imap_user and self.imap_password
        )

    @property
    def envoi_utilisable(self) -> bool:
        """Expédiable : activé, avec un serveur et une adresse d'expéditeur."""
        return bool(self.smtp_actif and self.smtp_host and self.expediteur)

    @property
    def expediteur(self) -> str:
        """L'adresse « De : ». À défaut d'être réglée, le compte d'envoi."""
        return self.smtp_expediteur.strip() or self.smtp_user.strip()


def _defauts() -> Reglages:
    return Reglages(
        redact_demographics=settings.redact_demographics,
        allow_self_registration=settings.allow_self_registration,
        # Ouvert par défaut : refuser un dossier qu'on a reçu coûte plus cher
        # que de le classer au vivier.
        candidatures_spontanees=True,
        # Le .env sert d'amorçage : une installation peut arriver préconfigurée,
        # et l'interface prend ensuite le relais.
        courriel_actif=bool(settings.imap_host and settings.imap_user),
        imap_host=settings.imap_host,
        imap_port=settings.imap_port,
        imap_user=settings.imap_user,
        imap_password=settings.imap_password,
        imap_folder=settings.imap_folder or "INBOX",
        smtp_actif=bool(settings.smtp_host and settings.smtp_user),
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_user=settings.smtp_user,
        smtp_password=settings.smtp_password,
        smtp_tls=settings.smtp_tls,
        smtp_expediteur=settings.smtp_expediteur,
        url_publique=settings.url_publique,
    )


def _en_bool(valeur: str) -> bool:
    return valeur.strip().lower() in {"1", "true", "vrai", "oui", "on"}


async def lire(db: AsyncSession) -> Reglages:
    """Les réglages effectifs : .env, surchargé par ce qui a été réglé."""
    reglages = _defauts()
    lignes = await db.execute(select(Parametre.cle, Parametre.valeur))
    for cle, valeur in lignes:
        try:
            if cle == REDACTION_DEMOGRAPHIQUE:
                reglages.redact_demographics = _en_bool(valeur)
            elif cle == INSCRIPTION_LIBRE:
                reglages.allow_self_registration = _en_bool(valeur)
            elif cle == CANDIDATURES_SPONTANEES:
                reglages.candidatures_spontanees = _en_bool(valeur)
            elif cle == COURRIEL_ACTIF:
                reglages.courriel_actif = _en_bool(valeur)
            elif cle == IMAP_HOTE:
                reglages.imap_host = valeur.strip()
            elif cle == IMAP_PORT:
                reglages.imap_port = int(valeur)
            elif cle == IMAP_UTILISATEUR:
                reglages.imap_user = valeur.strip()
            elif cle == IMAP_MOT_DE_PASSE:
                # Gmail affiche le mot de passe d'application par groupes de
                # quatre ; recopié tel quel, il est refusé. On retire donc les
                # espaces plutôt que de laisser les RH deviner.
                reglages.imap_password = valeur.replace(" ", "")
            elif cle == IMAP_DOSSIER:
                reglages.imap_folder = valeur.strip() or "INBOX"
            elif cle == SMTP_ACTIF:
                reglages.smtp_actif = _en_bool(valeur)
            elif cle == SMTP_HOTE:
                reglages.smtp_host = valeur.strip()
            elif cle == SMTP_PORT:
                reglages.smtp_port = int(valeur)
            elif cle == SMTP_UTILISATEUR:
                reglages.smtp_user = valeur.strip()
            elif cle == SMTP_MOT_DE_PASSE:
                # Même remarque que pour l'IMAP : Gmail affiche le mot de passe
                # d'application par groupes de quatre, recopié tel quel il est
                # refusé.
                reglages.smtp_password = valeur.replace(" ", "")
            elif cle == SMTP_TLS:
                reglages.smtp_tls = _en_bool(valeur)
            elif cle == SMTP_EXPEDITEUR:
                reglages.smtp_expediteur = valeur.strip()
            elif cle == URL_PUBLIQUE:
                reglages.url_publique = valeur.strip().rstrip("/")
        except (TypeError, ValueError):
            # Une valeur illisible en base ne doit pas empêcher l'application
            # de démarrer : on retombe sur le défaut du fichier.
            continue
    return reglages


async def ecrire(db: AsyncSession, modifications: dict[str, object]) -> list[str]:
    """Enregistre les surcharges. Renvoie les clés effectivement changées.

    Un secret vide vaut « inchangé », pas « effacé » : le formulaire ne peut pas
    réafficher le mot de passe, donc l'enregistrer sans y toucher ne doit pas
    déconnecter la boîte. Pour vraiment le retirer, on vide l'utilisateur ou on
    décoche l'activation.
    """
    changees: list[str] = []
    for cle, valeur in modifications.items():
        if valeur is None:
            continue
        if cle in SECRETS and not str(valeur).strip():
            continue
        texte = str(valeur).lower() if isinstance(valeur, bool) else str(valeur)
        existant = await db.get(Parametre, cle)
        if existant is None:
            db.add(Parametre(cle=cle, valeur=texte))
        elif existant.valeur == texte:
            continue
        else:
            existant.valeur = texte
        changees.append(cle)
    await db.flush()
    return changees
