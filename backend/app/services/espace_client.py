"""L'espace de suivi du promoteur : ouverture, activation, fermeture.

Le principe tient en une phrase : **l'accès naît avec le mandat et meurt avec
lui**. Le cabinet n'a pas de comptes clients à administrer ; il a des dossiers,
et chaque dossier ouvre une porte le temps qu'il dure.

Trois décisions structurent ce module.

*Le cabinet ne choisit jamais le mot de passe.* Il envoie un lien à usage
unique ; le destinataire pose son mot de passe lui-même. Un mot de passe
attribué par un tiers serait connu de ce tiers, ce qui vide la trace de sa
valeur : « le client a validé » ne veut plus rien dire si quelqu'un d'autre
pouvait se connecter à sa place.

*Le lien expire.* Un courriel reste des années dans une boîte. Sans expiration,
un lien retrouvé longtemps après rouvrirait un dossier clos.

*La révocation est immédiate et vérifiée à chaque requête.* Le jeton porte le
mandat, mais l'accès est relu en base : clore un mandat ferme la porte tout de
suite, sans attendre l'expiration des jetons déjà distribués.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AccesClient, EtapeMandat, Mandat, StatutMandat
from app.models.base import utcnow
from app.models.collaboration import nouveau_jeton
from app.security import hash_password, verify_password

# Durée de validité du lien d'activation. Assez large pour traverser un
# week-end et une absence, assez courte pour qu'un lien oublié ne serve plus.
VALIDITE_ACTIVATION = timedelta(days=14)

# Longueur minimale du mot de passe choisi par le client. Le même seuil que
# pour les comptes internes : il n'y a pas de raison qu'un tiers protège moins
# bien un accès qui montre des noms de candidats.
LONGUEUR_MOT_DE_PASSE = 8


class ErreurAcces(RuntimeError):
    """Refus explicite, formulé pour être montré au destinataire."""


# --- chronogramme par défaut ------------------------------------------------
#
# Volontairement grossier. Le client doit pouvoir répondre à « où en est mon
# recrutement » sans rien apprendre du contenu des dossiers : ni combien de
# candidats, ni lesquels, ni sur quoi ils ont été écartés. Ces cinq étapes
# suffisent, et le cabinet peut les remplacer mandat par mandat.
ETAPES_PAR_DEFAUT: tuple[str, ...] = (
    "Cadrage du besoin",
    "Publication de l'avis",
    "Réception des candidatures",
    "Présélection des dossiers",
    "Entretiens et rapport final",
)


def etapes_initiales(mandat_id: str) -> list[EtapeMandat]:
    return [
        EtapeMandat(mandat_id=mandat_id, ordre=i, libelle=libelle)
        for i, libelle in enumerate(ETAPES_PAR_DEFAUT)
    ]


# --- ouverture --------------------------------------------------------------


@dataclass(slots=True)
class Invitation:
    """Ce qu'il faut pour écrire au promoteur. Le jeton n'existe qu'ici."""

    acces: AccesClient
    lien: str
    expire_le: str


def _lien(url_publique: str, jeton: str) -> str:
    base = (url_publique or "").rstrip("/")
    if not base:
        # Sans adresse publique configurée, un lien vers « localhost » serait
        # inutilisable chez le destinataire. Mieux vaut le dire à l'appelant.
        return ""
    return f"{base}/espace-client/activation/{jeton}"


async def ouvrir(
    db: AsyncSession,
    mandat: Mandat,
    email: str,
    nom: str,
    fonction: str | None = None,
    url_publique: str = "",
) -> Invitation:
    """Crée — ou renouvelle — l'accès d'un interlocuteur sur un mandat.

    Renouveler plutôt que refuser : si le premier courriel s'est perdu ou si le
    lien a expiré, réouvrir doit simplement produire un nouveau lien. Un accès
    déjà activé, lui, n'est pas réinitialisé en silence — cela reviendrait à
    couper un client de son espace parce que quelqu'un a recliqué sur un bouton.
    """
    adresse = email.strip().lower()
    if not adresse:
        raise ErreurAcces("Une adresse électronique est nécessaire.")

    existant = (
        await db.execute(
            select(AccesClient).where(
                AccesClient.mandat_id == mandat.id, AccesClient.email == adresse
            )
        )
    ).scalar_one_or_none()

    if existant is not None and existant.active:
        raise ErreurAcces(
            f"{adresse} dispose déjà d'un accès actif à ce mandat. Révoquez-le "
            "d'abord si vous voulez en ouvrir un nouveau."
        )

    acces = existant or AccesClient(mandat_id=mandat.id, email=adresse, nom=nom.strip())
    acces.nom = nom.strip() or acces.nom
    acces.fonction = (fonction or "").strip() or acces.fonction
    acces.jeton_activation = nouveau_jeton()
    acces.jeton_expire_le = utcnow() + VALIDITE_ACTIVATION
    acces.revoque_le = None
    acces.motif_revocation = None
    if existant is None:
        db.add(acces)
    await db.flush()

    return Invitation(
        acces=acces,
        lien=_lien(url_publique, acces.jeton_activation),
        expire_le=acces.jeton_expire_le.strftime("%d/%m/%Y"),
    )


async def par_jeton(db: AsyncSession, jeton: str) -> AccesClient:
    """L'accès désigné par un lien d'activation, s'il est encore valable."""
    acces = (
        await db.execute(
            select(AccesClient).where(AccesClient.jeton_activation == jeton)
        )
    ).scalar_one_or_none()
    if acces is None:
        raise ErreurAcces(
            "Ce lien d'activation n'est pas valide. Il a peut-être déjà été "
            "utilisé ; demandez-en un nouveau à votre interlocuteur."
        )
    if acces.revoque_le is not None:
        raise ErreurAcces("Cet accès a été fermé.")
    if acces.jeton_expire_le is not None and acces.jeton_expire_le < utcnow():
        raise ErreurAcces(
            "Ce lien d'activation a expiré. Demandez-en un nouveau à votre "
            "interlocuteur."
        )
    return acces


async def activer(db: AsyncSession, jeton: str, mot_de_passe: str) -> AccesClient:
    """Consomme le lien et pose le mot de passe choisi par le destinataire."""
    acces = await par_jeton(db, jeton)
    if len(mot_de_passe) < LONGUEUR_MOT_DE_PASSE:
        raise ErreurAcces(
            f"Le mot de passe doit comporter au moins {LONGUEUR_MOT_DE_PASSE} "
            "caractères."
        )
    acces.password_hash = hash_password(mot_de_passe)
    acces.active_le = utcnow()
    # Usage unique : le jeton disparaît, donc le lien resté dans la boîte du
    # destinataire — ou dans celle de qui a reçu le message en copie — ne
    # rouvrira rien.
    acces.jeton_activation = None
    acces.jeton_expire_le = None
    await db.flush()
    return acces


async def authentifier(db: AsyncSession, email: str, mot_de_passe: str) -> AccesClient:
    """Le contrôle d'entrée de l'espace client.

    Un accès non activé, révoqué ou dont le mandat est clos échoue avec le même
    message qu'un mot de passe faux : distinguer les cas renseignerait un tiers
    sur l'existence d'un dossier.
    """
    adresse = email.strip().lower()
    candidats = (
        await db.execute(select(AccesClient).where(AccesClient.email == adresse))
    ).scalars().all()

    for acces in candidats:
        if acces.password_hash is None or acces.revoque_le is not None:
            continue
        if verify_password(mot_de_passe, acces.password_hash):
            acces.dernier_acces_le = utcnow()
            await db.flush()
            return acces

    raise ErreurAcces("Adresse ou mot de passe incorrect.")


async def revoquer(db: AsyncSession, acces: AccesClient, motif: str = "") -> None:
    acces.revoque_le = utcnow()
    acces.motif_revocation = motif.strip() or None
    acces.jeton_activation = None
    acces.jeton_expire_le = None
    await db.flush()


async def fermer_ceux_du_mandat(db: AsyncSession, mandat: Mandat, motif: str) -> int:
    """Ferme tous les accès d'un mandat. Appelé à sa clôture.

    C'est la promesse tenue au client comme au cabinet : l'espace existe le
    temps du recrutement. Le laisser ouvert « au cas où » ferait de chaque
    mandat terminé une porte oubliée.
    """
    acces = (
        await db.execute(
            select(AccesClient).where(
                AccesClient.mandat_id == mandat.id, AccesClient.revoque_le.is_(None)
            )
        )
    ).scalars().all()
    for un in acces:
        await revoquer(db, un, motif)
    return len(acces)


def mandat_ouvert(mandat: Mandat) -> bool:
    """Le mandat autorise-t-il encore un accès client ?"""
    return mandat.archive_le is None and mandat.statut not in {
        StatutMandat.CLOTURE,
        StatutMandat.PERDU,
    }
