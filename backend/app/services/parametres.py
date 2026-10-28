"""Réglages modifiables depuis l'application.

Le fichier `.env` reste la valeur de départ ; ce module ne fait que la
surcharger quand quelqu'un a réglé la valeur dans l'interface. Ce partage est
délibéré : ce qui touche à l'infrastructure — fournisseur de modèle, stockage —
appartient au déploiement et n'a rien à faire dans un écran ; ce qui relève de
la pratique de recrutement — expurgation des données sensibles, inscription
libre, candidatures spontanées, boîte de courriel — change avec l'usage et doit
pouvoir se régler sans redémarrage ni accès au serveur.

Deux familles de secrets font exception à la règle « les secrets restent au
déploiement » : le secret de l'application Microsoft, et le modèle d'IA —
fournisseur et clés. Le motif est pratique et assumé — un secret Entra expire
à date fixe, une clé se renouvelle ou s'épuise, et demander un accès SSH à
chaque fois revenait à laisser l'application sans courriel ni rédaction.
Aucun secret n'est renvoyé par l'API ; l'interface sait seulement s'il est
renseigné.

La boîte est une boîte **Microsoft 365**, lue et utilisée pour l'envoi par
Microsoft Graph. Les voies IMAP et SMTP ont été retirées : le cabinet n'en a
pas l'usage, et leurs réglages encombraient l'écran de champs qui ne servaient
à rien chez Microsoft.

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
# de recrutement change avec les campagnes : demander un accès au serveur à
# chaque fois condamnerait la fonction à ne jamais être utilisée.
COURRIEL_ACTIF = "courriel_actif"
ADRESSE_BOITE = "adresse_boite"
DOSSIER_BOITE = "dossier_boite"

# Envoi. Séparé de la réception : on peut relever la boîte sans encore oser
# écrire aux candidats depuis l'application, et inversement.
ENVOI_ACTIF = "envoi_actif"
ADRESSE_EXPEDITEUR = "adresse_expediteur"

# Accès Microsoft : de quoi obtenir un jeton d'application pour Graph. Un seul
# jeu sert à la réception et à l'envoi : c'est la même boîte et la même
# application déclarée, et en demander deux fois inviterait à les désaccorder.
OAUTH_TENANT = "oauth_tenant"
OAUTH_CLIENT_ID = "oauth_client_id"
OAUTH_CLIENT_SECRET = "oauth_client_secret"

# L'adresse à laquelle l'application est jointe depuis l'extérieur. Elle sert à
# construire les liens envoyés par courriel ; elle n'est pas devinable depuis le
# serveur, qui ne connaît que sa propre adresse d'écoute.
URL_PUBLIQUE = "url_publique"

# L'adresse que les candidats écrivent en cas de difficulté. Elle figure dans
# l'avis, sur la page de candidature et dans l'aide. Vide, c'est l'adresse de
# la boîte de recrutement qui sert : c'est elle que l'avis donne déjà.
CONTACT_CANDIDATS = "contact_candidats"

# Le modèle d'IA. Ce qui est réglé ici prime sur le .env, quoi qu'il porte :
# c'est tout l'intérêt de pouvoir le régler sans toucher au serveur.
IA_FOURNISSEUR = "llm_provider"
IA_MODELE = "llm_model"
CLE_GEMINI = "gemini_api_key"
CLE_ANTHROPIC = "anthropic_api_key"
# `openai` : tout service qui parle le dialecte d'OpenAI — Groq, Mistral,
# OpenRouter… — avec son adresse et sa clé.
CLE_OPENAI = "llm_api_key"
ADRESSE_OPENAI = "llm_base_url"
ADRESSE_OLLAMA = "ollama_base_url"
FOURNISSEURS_IA = ("gemini", "anthropic", "openai", "ollama")
CLES_IA = (
    IA_FOURNISSEUR, IA_MODELE, CLE_GEMINI, CLE_ANTHROPIC, CLE_OPENAI,
    ADRESSE_OPENAI, ADRESSE_OLLAMA,
)
# La clé que chaque fournisseur lit, pour déduire le fournisseur d'une clé
# collée seule — Gemini d'abord, c'est celui du cabinet.
CLE_DU_FOURNISSEUR = {"gemini": CLE_GEMINI, "anthropic": CLE_ANTHROPIC, "openai": CLE_OPENAI}

# Ce que l'API ne renvoie jamais en clair. Jamais réaffichés au formulaire,
# donc « vide » y veut dire « inchangé » : sans cela, ouvrir puis enregistrer
# l'écran des paramètres déconnecterait la boîte ou effacerait une clé.
SECRETS = frozenset({OAUTH_CLIENT_SECRET, CLE_GEMINI, CLE_ANTHROPIC, CLE_OPENAI})

# Les noms de l'époque IMAP/SMTP, sous lesquels une base non migrée garde
# encore l'adresse de la boîte et le réglage d'envoi. Lus à défaut du nouveau
# nom ; la migration 0006 les renomme et supprime le reste.
ANCIENNES_CLES = {
    "imap_user": ADRESSE_BOITE,
    "imap_folder": DOSSIER_BOITE,
    "smtp_actif": ENVOI_ACTIF,
    "smtp_expediteur": ADRESSE_EXPEDITEUR,
}

# Le .env, tel que lu au démarrage : ce qui revient quand l'écran ne règle
# rien. `appliquer_ia` réécrit la configuration du processus ; sans cette
# copie, retirer un réglage de l'écran ne saurait plus à quoi revenir.
_IA_DU_FICHIER = {
    cle: getattr(settings, cle)
    for cle in (*CLES_IA, "llm_prose_provider")
}


@dataclass(slots=True)
class Reglages:
    redact_demographics: bool
    allow_self_registration: bool
    candidatures_spontanees: bool
    courriel_actif: bool = False
    adresse_boite: str = ""
    dossier_boite: str = "inbox"
    envoi_actif: bool = False
    adresse_expediteur: str = ""
    url_publique: str = ""
    oauth_tenant: str = ""
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    contact_candidats: str = ""
    # Le modèle d'IA réglé à l'écran ; vide = celui du .env.
    llm_provider: str = ""
    llm_model: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    ollama_base_url: str = ""

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
        """L'adresse de la boîte de recrutement."""
        return self.adresse_boite.strip()

    @property
    def contact(self) -> str:
        """L'adresse que les candidats écrivent en cas de difficulté."""
        return (
            self.contact_candidats.strip()
            or self.adresse_expediteur.strip()
            or self.boite
        )

    @property
    def config_oauth(self) -> ConfigOAuth:
        return ConfigOAuth(
            tenant=self.oauth_tenant.strip(),
            client_id=self.oauth_client_id.strip(),
            client_secret=self.oauth_client_secret.strip(),
        )

    @property
    def courriel_utilisable(self) -> bool:
        """Relevable : activé, avec une adresse et un accès Microsoft complet."""
        return bool(self.courriel_actif and self.boite and self.graph_utilisable)

    @property
    def envoi_utilisable(self) -> bool:
        """Expédiable : activé, avec une adresse d'expéditeur et un accès complet."""
        return bool(self.envoi_actif and self.expediteur and self.graph_utilisable)

    @property
    def expediteur(self) -> str:
        """L'adresse « De : ». À défaut d'être réglée, la boîte de recrutement.

        Une autre adresse que la boîte suppose que l'application ait le droit
        d'envoyer en son nom.
        """
        return self.adresse_expediteur.strip() or self.boite


def _defauts() -> Reglages:
    return Reglages(
        redact_demographics=settings.redact_demographics,
        allow_self_registration=settings.allow_self_registration,
        # Ouvert par défaut : refuser un dossier qu'on a reçu coûte plus cher
        # que de le classer au vivier.
        candidatures_spontanees=True,
        # Le .env sert d'amorçage : une installation peut arriver préconfigurée,
        # et l'interface prend ensuite le relais.
        adresse_boite=settings.boite_recrutement,
        adresse_expediteur=settings.expediteur_courriel,
        url_publique=settings.url_publique,
        # L'accès Microsoft se pose au déploiement, comme le reste de la
        # configuration serveur. L'écran Paramètres peut le corriger ensuite
        # sans rouvrir un accès à la machine, et ce qu'il enregistre prime.
        oauth_tenant=settings.oauth_tenant,
        oauth_client_id=settings.oauth_client_id,
        oauth_client_secret=settings.oauth_client_secret,
    )


def _en_bool(valeur: str) -> bool:
    return valeur.strip().lower() in {"1", "true", "vrai", "oui", "on"}


async def lire(db: AsyncSession) -> Reglages:
    """Les réglages effectifs : .env, surchargé par ce qui a été réglé."""
    reglages = _defauts()
    valeurs = dict((await db.execute(select(Parametre.cle, Parametre.valeur))).all())
    for ancienne, nouvelle in ANCIENNES_CLES.items():
        if nouvelle not in valeurs and ancienne in valeurs:
            valeurs[nouvelle] = valeurs[ancienne]

    for cle, valeur in valeurs.items():
        try:
            if cle == REDACTION_DEMOGRAPHIQUE:
                reglages.redact_demographics = _en_bool(valeur)
            elif cle == INSCRIPTION_LIBRE:
                reglages.allow_self_registration = _en_bool(valeur)
            elif cle == CANDIDATURES_SPONTANEES:
                reglages.candidatures_spontanees = _en_bool(valeur)
            elif cle == COURRIEL_ACTIF:
                reglages.courriel_actif = _en_bool(valeur)
            elif cle == ADRESSE_BOITE:
                reglages.adresse_boite = valeur.strip()
            elif cle == DOSSIER_BOITE:
                reglages.dossier_boite = valeur.strip() or "inbox"
            elif cle == ENVOI_ACTIF:
                reglages.envoi_actif = _en_bool(valeur)
            elif cle == ADRESSE_EXPEDITEUR:
                reglages.adresse_expediteur = valeur.strip()
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
            elif cle == CONTACT_CANDIDATS:
                reglages.contact_candidats = valeur.strip()
            elif cle == IA_FOURNISSEUR:
                if valeur.strip() in FOURNISSEURS_IA:
                    reglages.llm_provider = valeur.strip()
            elif cle in (IA_MODELE, CLE_GEMINI, CLE_ANTHROPIC, CLE_OPENAI):
                # Même remarque : une clé recopiée emporte volontiers un espace.
                setattr(reglages, cle, valeur.strip())
            elif cle in (ADRESSE_OPENAI, ADRESSE_OLLAMA):
                setattr(reglages, cle, valeur.strip().rstrip("/"))
        except (TypeError, ValueError):
            # Une valeur illisible en base ne doit pas empêcher l'application
            # de démarrer : on retombe sur le défaut du fichier.
            continue
    return reglages


async def ecrire(db: AsyncSession, modifications: dict[str, object]) -> list[str]:
    """Enregistre les surcharges. Renvoie les clés effectivement changées.

    Un secret vide vaut « inchangé », pas « effacé » : le formulaire ne peut pas
    le réafficher, donc enregistrer sans y toucher ne doit pas déconnecter la
    boîte ni retirer la clé.
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


async def effacer(db: AsyncSession, cles: tuple[str, ...] | list[str]) -> list[str]:
    """Retire des surcharges : le .env reprend la main. Rend celles retirées."""
    retirees = []
    for cle in cles:
        existant = await db.get(Parametre, cle)
        if existant is not None:
            await db.delete(existant)
            retirees.append(cle)
    await db.flush()
    return retirees


def fournisseur_ecran(reglages: Reglages) -> str:
    """Le fournisseur que l'écran impose, ou « » s'il laisse faire le .env.

    Choisi explicitement, c'est lui. Sinon, une clé collée seule désigne son
    fournisseur : qui colle une clé Gemini veut que Gemini serve, quel que
    soit le fournisseur que nomme le .env.
    """
    if reglages.llm_provider:
        return reglages.llm_provider
    for nom, cle in CLE_DU_FOURNISSEUR.items():
        if getattr(reglages, cle).strip():
            return nom
    return ""


def appliquer_ia(reglages: Reglages) -> None:
    """Met en service le modèle d'IA : ce que règle l'écran, sinon le .env.

    Les fournisseurs lisent leur configuration dans celle du processus ; on
    l'y pose, puis on oublie le fournisseur déjà construit pour qu'il soit
    rebâti. Appelé au démarrage et après chaque enregistrement — le serveur
    ne tourne qu'en un seul processus.

    Quand l'écran impose un fournisseur, il fait **tout** : le rédacteur que
    nommerait le .env (LLM_PROSE_PROVIDER) est écarté, sans quoi un autre
    fournisseur continuerait d'écrire les avis et les rapports. Les secours du
    .env restent, essayés seulement quand celui de l'écran ne répond plus.
    """
    from app.llm.factory import reset_provider

    impose = fournisseur_ecran(reglages)
    voulu = {
        cle: getattr(reglages, cle).strip() or _IA_DU_FICHIER[cle]
        for cle in (CLE_GEMINI, CLE_ANTHROPIC, CLE_OPENAI, ADRESSE_OPENAI, ADRESSE_OLLAMA)
    }
    if impose:
        voulu[IA_FOURNISSEUR] = impose
        # Un modèle du .env nommé pour un autre fournisseur n'aurait pas de sens.
        voulu[IA_MODELE] = reglages.llm_model.strip() or (
            _IA_DU_FICHIER[IA_MODELE] if impose == _IA_DU_FICHIER[IA_FOURNISSEUR] else ""
        )
        voulu["llm_prose_provider"] = ""
    else:
        voulu[IA_FOURNISSEUR] = _IA_DU_FICHIER[IA_FOURNISSEUR]
        voulu[IA_MODELE] = reglages.llm_model.strip() or _IA_DU_FICHIER[IA_MODELE]
        voulu["llm_prose_provider"] = _IA_DU_FICHIER["llm_prose_provider"]

    change = False
    for cle, valeur in voulu.items():
        if getattr(settings, cle) != valeur:
            setattr(settings, cle, valeur)
            change = True
    if change:
        reset_provider()


def source_cle(reglages: Reglages, cle: str) -> str:
    """D'où vient une clé : « ecran », « serveur », ou « » si aucune."""
    if getattr(reglages, cle).strip():
        return "ecran"
    return "serveur" if str(_IA_DU_FICHIER[cle]).strip() else ""


def ce_qui_manque(reglages: Reglages) -> list[str]:
    """Ce qu'il faut encore renseigner pour relever la boîte.

    Sert à l'état de la boîte, pour qu'il puisse le dire *avant* qu'on essaie :
    le relevé manuel — celui dont on a justement besoin quand quelque chose
    cloche — ne doit pas disparaître sans un mot sur ce qui manque.
    """
    manquants = [
        libelle
        for libelle, valeur in (
            ("l'adresse de la boîte", reglages.boite),
            ("l'identifiant du tenant", reglages.graph_utilisable or reglages.oauth_tenant),
            ("l'identifiant de l'application", reglages.oauth_client_id),
            ("le secret de l'application", reglages.oauth_client_secret),
        )
        if not valeur
    ]
    if not manquants and not reglages.graph_utilisable:
        manquants = ["un identifiant de tenant d'organisation (pas « common » ni « consumers »)"]
    return manquants
