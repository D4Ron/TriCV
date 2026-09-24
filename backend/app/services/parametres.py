"""Réglages modifiables depuis l'application.

Le fichier `.env` reste la valeur de départ ; ce module ne fait que la
surcharger quand quelqu'un a réglé la valeur dans l'interface. Ce partage est
délibéré : ce qui touche à l'infrastructure — fournisseur de modèle, stockage,
stockage — appartient au déploiement et n'a rien à faire dans un écran ; ce qui
relève de la pratique de recrutement — expurgation des données sensibles,
inscription libre, candidatures spontanées, boîtes de courriel — change avec
l'usage et doit pouvoir se régler sans redémarrage ni accès au serveur.

Les boîtes de courriel font exception à la règle « les secrets restent au
déploiement » : mots de passe d'application comme secrets Microsoft sont
réglables ici. Le motif est pratique et assumé — l'adresse de recrutement
change avec les campagnes, un secret d'application Entra expire à date fixe, et
un mot de passe d'application se révoque sans prévenir. Aucun de ces secrets
n'est renvoyé par l'API ; l'interface sait seulement s'il est renseigné.

Le **fournisseur** de courriel se règle ici aussi. Une installation neuve part
sur Microsoft 365 — la messagerie du cabinet, atteinte par Graph — et une
installation qui portait déjà un hôte IMAP ou SMTP dans son `.env` reste sur ce
chemin : personne ne doit voir sa boîte basculer à la faveur d'une mise à jour.

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
from app.services.oauth_microsoft import ConfigOAuth


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

# Accès Microsoft. Une boîte Outlook — professionnelle ou personnelle — ne se
# relève plus avec un mot de passe : Microsoft a supprimé l'authentification de
# base sur IMAP, POP et SMTP, y compris les « mots de passe d'application ».
# Ces quatre réglages portent de quoi obtenir un jeton à la place.
#
# Un seul jeu sert à la réception et à l'envoi : c'est la même boîte et la même
# application déclarée, et en demander deux fois inviterait à les désaccorder.
OAUTH_TENANT = "oauth_tenant"
OAUTH_CLIENT_ID = "oauth_client_id"
OAUTH_CLIENT_SECRET = "oauth_client_secret"
# Flux délégué seulement (adresse outlook.com personnelle) : le jeton obtenu au
# consentement initial, que l'application échange ensuite contre des accès.
OAUTH_REFRESH_TOKEN = "oauth_refresh_token"

# L'adresse à laquelle l'application est jointe depuis l'extérieur. Elle sert à
# construire les liens envoyés par courriel ; elle n'est pas devinable depuis le
# serveur, qui ne connaît que sa propre adresse d'écoute.
URL_PUBLIQUE = "url_publique"

# Le fournisseur de la boîte. Deux voies, qui ne se configurent pas pareil :
#
# - « microsoft365 » : une boîte Microsoft 365 (Exchange Online), lue et
#   utilisée pour l'envoi par Microsoft Graph. C'est la voie du cabinet : un
#   abonnement professionnel, une application déclarée dans Entra, et rien à
#   régler côté Exchange — ni principal de service à inscrire en PowerShell, ni
#   SMTP AUTH à rouvrir sur la boîte, deux prérequis de la voie IMAP/SMTP
#   auxquels un administrateur de petite structure se heurte.
# - « imap » : tout autre fournisseur, par IMAP et SMTP.
FOURNISSEUR_COURRIEL = "fournisseur_courriel"
FOURNISSEUR_MICROSOFT365 = "microsoft365"
FOURNISSEUR_IMAP = "imap"
FOURNISSEURS = frozenset({FOURNISSEUR_MICROSOFT365, FOURNISSEUR_IMAP})

# L'adresse que les candidats écrivent en cas de difficulté. Elle figure dans
# l'avis, sur la page de candidature et dans l'aide. Vide, c'est l'adresse de
# la boîte de recrutement qui sert : c'est elle que l'avis donne déjà.
CONTACT_CANDIDATS = "contact_candidats"

# Ce que l'API ne renvoie jamais en clair.
SECRETS = frozenset(
    {
        IMAP_MOT_DE_PASSE,
        SMTP_MOT_DE_PASSE,
        # Jamais réaffichés au formulaire, donc « vide » y veut dire
        # « inchangé » : sans cela, ouvrir puis enregistrer l'écran des
        # paramètres déconnecterait la boîte.
        OAUTH_CLIENT_SECRET,
        OAUTH_REFRESH_TOKEN,
    }
)


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
    oauth_tenant: str = ""
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    oauth_refresh_token: str = ""
    fournisseur_courriel: str = FOURNISSEUR_IMAP
    contact_candidats: str = ""

    @property
    def microsoft365(self) -> bool:
        return self.fournisseur_courriel == FOURNISSEUR_MICROSOFT365

    @property
    def graph_utilisable(self) -> bool:
        """De quoi obtenir un jeton d'application pour Microsoft Graph.

        Le flux application exige un tenant réel : « consumers » ou « common »
        ne désignent aucune organisation, et Microsoft y refuse ce flux.
        """
        tenant = self.oauth_tenant.strip().lower()
        return bool(
            tenant
            and tenant not in ("consumers", "common", "organizations")
            and self.oauth_client_id.strip()
            and self.oauth_client_secret.strip()
        )

    @property
    def boite(self) -> str:
        """L'adresse de la boîte de recrutement, quel que soit le fournisseur."""
        return self.imap_user.strip()

    @property
    def contact(self) -> str:
        """L'adresse que les candidats écrivent en cas de difficulté."""
        return (
            self.contact_candidats.strip()
            or self.smtp_expediteur.strip()
            or self.boite
        )

    @property
    def config_oauth(self) -> ConfigOAuth:
        return ConfigOAuth(
            tenant=self.oauth_tenant or "consumers",
            client_id=self.oauth_client_id,
            client_secret=self.oauth_client_secret,
            refresh_token=self.oauth_refresh_token,
        )

    @property
    def oauth_utilisable(self) -> bool:
        return self.config_oauth.utilisable

    @property
    def courriel_utilisable(self) -> bool:
        """Relevable : activé, et avec de quoi ouvrir une session.

        « De quoi » veut dire un mot de passe *ou* un accès OAuth : une boîte
        Microsoft n'a pas de mot de passe qui fonctionne, et exiger les deux
        rendrait la fonction inatteignable pour elle.
        """
        if self.microsoft365:
            return bool(self.courriel_actif and self.boite and self.graph_utilisable)
        return bool(
            self.courriel_actif
            and self.imap_host
            and self.imap_user
            and (self.imap_password or self.oauth_utilisable)
        )

    @property
    def envoi_utilisable(self) -> bool:
        """Expédiable : activé, avec un serveur et une adresse d'expéditeur."""
        if self.microsoft365:
            return bool(self.smtp_actif and self.expediteur and self.graph_utilisable)
        return bool(self.smtp_actif and self.smtp_host and self.expediteur)

    @property
    def expediteur(self) -> str:
        """L'adresse « De : ». À défaut d'être réglée, le compte d'envoi.

        Chez Microsoft 365, il n'y a pas de compte d'envoi distinct : on écrit
        depuis la boîte de recrutement, sauf si une autre adresse est réglée —
        l'application doit alors avoir le droit d'envoyer en son nom.
        """
        if self.microsoft365:
            return self.smtp_expediteur.strip() or self.boite
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
        # L'accès Microsoft se pose au déploiement, comme le reste de la
        # configuration serveur. L'écran Paramètres peut le corriger ensuite
        # sans rouvrir un accès à la machine, et ce qu'il enregistre prime.
        oauth_tenant=settings.oauth_tenant,
        oauth_client_id=settings.oauth_client_id,
        oauth_client_secret=settings.oauth_client_secret,
        oauth_refresh_token=settings.oauth_refresh_token,
        # Une installation déjà réglée en IMAP le reste ; une installation
        # neuve part sur Microsoft 365, la messagerie du cabinet.
        fournisseur_courriel=(
            FOURNISSEUR_IMAP
            if settings.imap_host or settings.smtp_host
            else FOURNISSEUR_MICROSOFT365
        ),
        contact_candidats="",
    )


def _en_bool(valeur: str) -> bool:
    return valeur.strip().lower() in {"1", "true", "vrai", "oui", "on"}


async def lire(db: AsyncSession) -> Reglages:
    """Les réglages effectifs : .env, surchargé par ce qui a été réglé."""
    reglages = _defauts()
    fournisseur_choisi = False
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
            elif cle == OAUTH_TENANT:
                reglages.oauth_tenant = valeur.strip()
            elif cle == OAUTH_CLIENT_ID:
                reglages.oauth_client_id = valeur.strip()
            elif cle == OAUTH_CLIENT_SECRET:
                # Entra affiche le secret une seule fois, et il se recopie
                # souvent avec un espace en tête ou en queue.
                reglages.oauth_client_secret = valeur.strip()
            elif cle == OAUTH_REFRESH_TOKEN:
                reglages.oauth_refresh_token = valeur.strip()
            elif cle == FOURNISSEUR_COURRIEL:
                if valeur.strip() in FOURNISSEURS:
                    reglages.fournisseur_courriel = valeur.strip()
                    fournisseur_choisi = True
            elif cle == CONTACT_CANDIDATS:
                reglages.contact_candidats = valeur.strip()
        except (TypeError, ValueError):
            # Une valeur illisible en base ne doit pas empêcher l'application
            # de démarrer : on retombe sur le défaut du fichier.
            continue
    if not fournisseur_choisi:
        # Jamais choisi à l'écran : une boîte IMAP déjà réglée — par le
        # fichier ou par l'écran — reste en IMAP. Basculer d'office une
        # installation qui relève correctement la couperait sans prévenir.
        reglages.fournisseur_courriel = (
            FOURNISSEUR_IMAP
            if reglages.imap_host or reglages.smtp_host
            else FOURNISSEUR_MICROSOFT365
        )
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
