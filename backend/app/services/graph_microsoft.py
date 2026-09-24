"""La boîte de recrutement sur Microsoft 365, par Microsoft Graph.

**Pourquoi Graph plutôt qu'IMAP/SMTP.** Les deux voies passent par un jeton
OAuth — Microsoft n'accepte plus aucun mot de passe. Mais la voie IMAP/SMTP
exige, en plus de l'application déclarée dans Entra, deux gestes côté Exchange
qu'un administrateur de petite structure ne connaît pas : inscrire le principal
de service de l'application en PowerShell (`New-ServicePrincipal`,
`Add-MailboxPermission`), et rouvrir SMTP AUTH sur la boîte, que les réglages
de sécurité par défaut ferment. Graph n'en demande aucun : deux permissions
d'application (`Mail.ReadWrite`, `Mail.Send`) et le consentement de
l'administrateur, dans le même écran d'Entra.

**Ce que fait le module.** Exactement ce que fait `BoiteImap`, avec la même
interface — `verifier`, `relever`, `marquer_traite`, `fermer` — pour que le
relevé ne sache pas quelle voie il emprunte. Le message est récupéré au format
MIME brut (`/$value`) et passe par le même `depuis_message` que l'IMAP : une
candidature reçue par Graph est lue par exactement le même code qu'une
candidature reçue par IMAP.

S'y ajoute l'envoi, par `sendMail`.

**Restreindre l'accès à une seule boîte.** Une permission d'application vaut
pour toutes les boîtes de l'organisation. Le guide recommande de la limiter à
la boîte de recrutement (« RBAC for Applications » d'Exchange, ou l'ancienne
« Application Access Policy ») ; ce n'est pas un prérequis au fonctionnement,
c'est une précaution que l'administrateur doit connaître.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from app.services import oauth_microsoft
from app.services.courriel import ErreurBoite, MessageEntrant, depuis_message
from app.services.oauth_microsoft import ConfigOAuth

logger = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
PORTEE_GRAPH = "https://graph.microsoft.com/.default"

# Les dossiers que Graph connaît par leur nom, quelle que soit la langue de la
# boîte. « INBOX » est le nom IMAP de la boîte de réception : on l'accepte, les
# réglages existants l'emploient.
_DOSSIERS_CONNUS = {
    "inbox": "inbox",
    "boîte de réception": "inbox",
    "boite de reception": "inbox",
    "junkemail": "junkemail",
    "courrier indésirable": "junkemail",
    "archive": "archive",
}


class ErreurGraph(ErreurBoite):
    """Microsoft Graph a refusé. Le message est écrit pour être lu par les RH."""


def config_graph(tenant: str, client_id: str, client_secret: str) -> ConfigOAuth:
    # Pas de jeton de rafraîchissement : Graph se joint par le flux
    # application, sans personne pour consentir à chaque relevé.
    return ConfigOAuth(
        tenant=tenant.strip(), client_id=client_id.strip(), client_secret=client_secret.strip()
    )


def _expliquer(reponse: httpx.Response, boite: str) -> str:
    """Traduit un refus de Graph en ce qu'il faut faire."""
    try:
        erreur = reponse.json().get("error", {})
    except ValueError:
        erreur = {}
    code = str(erreur.get("code") or "")
    detail = str(erreur.get("message") or reponse.text[:200])

    if reponse.status_code == 401 or code in ("InvalidAuthenticationToken",):
        return (
            "Microsoft a refusé le jeton de l'application. Vérifiez le tenant, "
            "l'identifiant et le secret dans Paramètres › Courriel."
        )
    if reponse.status_code == 403 or code in ("ErrorAccessDenied", "Authorization_RequestDenied"):
        return (
            f"L'application n'a pas accès à la boîte {boite}. Dans Entra › "
            "Inscriptions d'applications › Autorisations de l'API, les permissions "
            "d'application « Mail.ReadWrite » et « Mail.Send » doivent être "
            "ajoutées **et** avoir reçu le consentement de l'administrateur. Si "
            "l'accès a été restreint à certaines boîtes, celle-ci doit en faire partie."
        )
    if reponse.status_code == 404 or code in (
        "ErrorInvalidUser",
        "ResourceNotFound",
        "MailboxNotEnabledForRESTAPI",
        "ErrorItemNotFound",
    ):
        if code == "MailboxNotEnabledForRESTAPI":
            return (
                f"La boîte {boite} n'est pas une boîte Exchange Online active — "
                "elle n'a peut-être pas de licence Microsoft 365 qui inclut Exchange."
            )
        return (
            f"Microsoft ne trouve pas la boîte {boite}. Vérifiez l'adresse : ce doit "
            "être une boîte de l'organisation, pas un alias ni un groupe."
        )
    if reponse.status_code == 429:
        return "Microsoft limite temporairement les appels. Réessayez dans une minute."
    return f"Microsoft Graph a refusé la demande (HTTP {reponse.status_code}) : {detail}"


class ClientGraph:
    """Les appels à Graph pour une boîte donnée. Synchrone, comme `BoiteImap`."""

    def __init__(self, config: ConfigOAuth, boite: str) -> None:
        if not boite.strip():
            raise ErreurGraph(
                "Renseignez l'adresse de la boîte de recrutement dans Paramètres › Courriel."
            )
        if not config.utilisable:
            raise ErreurGraph(
                "L'accès Microsoft 365 est incomplet : il faut le tenant, "
                "l'identifiant de l'application et son secret."
            )
        self.config = config
        self.boite = boite.strip()
        self._http = httpx.Client(timeout=30)

    def _entetes(self) -> dict[str, str]:
        try:
            acces = oauth_microsoft.jeton(self.config, self.boite, PORTEE_GRAPH)
        except oauth_microsoft.ErreurOAuth as exc:
            raise ErreurGraph(str(exc)) from exc
        return {"Authorization": f"Bearer {acces}"}

    def appeler(self, methode: str, chemin: str, **options) -> httpx.Response:
        url = f"{GRAPH}/users/{quote(self.boite)}{chemin}"
        try:
            reponse = self._http.request(methode, url, headers=self._entetes(), **options)
        except httpx.HTTPError as exc:
            raise ErreurGraph(f"Impossible de joindre Microsoft Graph ({exc}).") from exc
        if reponse.status_code >= 400:
            raise ErreurGraph(_expliquer(reponse, self.boite))
        return reponse

    def fermer(self) -> None:
        self._http.close()


class BoiteGraph:
    """La boîte de recrutement Microsoft 365. Même interface que `BoiteImap`."""

    def __init__(self, config: ConfigOAuth, boite: str, dossier: str = "inbox") -> None:
        self.client = ClientGraph(config, boite)
        self.utilisateur = self.client.boite
        self.dossier = (dossier or "inbox").strip()
        self._chemin_dossier: str | None = None
        # message-id Internet -> identifiant Graph, pour marquer sans chercher.
        self._identifiants: dict[str, str] = {}

    def __enter__(self) -> BoiteGraph:
        return self

    def __exit__(self, *_exc) -> None:
        self.fermer()

    def fermer(self) -> None:
        self.client.fermer()

    def _dossier(self) -> str:
        """Le chemin Graph du dossier à relever.

        Les dossiers standard ont un nom stable ; un dossier créé par
        l'utilisateur se cherche par son nom affiché, à la racine puis sous la
        boîte de réception — là où les règles de tri les rangent d'habitude.
        """
        if self._chemin_dossier is not None:
            return self._chemin_dossier
        connu = _DOSSIERS_CONNUS.get(self.dossier.lower())
        if connu:
            self._chemin_dossier = f"/mailFolders/{connu}"
            return self._chemin_dossier

        nom = self.dossier.replace("'", "''")
        for parent in ("/mailFolders", "/mailFolders/inbox/childFolders"):
            reponse = self.client.appeler(
                "GET", parent, params={"$filter": f"displayName eq '{nom}'", "$select": "id"}
            )
            trouves = reponse.json().get("value") or []
            if trouves:
                self._chemin_dossier = f"/mailFolders/{trouves[0]['id']}"
                return self._chemin_dossier
        raise ErreurGraph(
            f"Le dossier « {self.dossier} » n'existe pas dans la boîte {self.utilisateur}. "
            "Pour la boîte de réception, indiquez « INBOX »."
        )

    def verifier(self) -> dict:
        """Teste l'accès et compte les messages, sans rien lire."""
        infos = self.client.appeler(
            "GET",
            self._dossier(),
            params={"$select": "displayName,totalItemCount,unreadItemCount"},
        ).json()
        return {
            "boite": self.utilisateur,
            "dossier": infos.get("displayName") or self.dossier,
            "messages": int(infos.get("totalItemCount") or 0),
            "non_lus": int(infos.get("unreadItemCount") or 0),
        }

    def relever(self, limite: int = 50) -> list[MessageEntrant]:
        liste = self.client.appeler(
            "GET",
            f"{self._dossier()}/messages",
            params={
                "$filter": "isRead eq false",
                "$top": str(limite),
                "$select": "id,internetMessageId",
            },
        ).json()

        messages: list[MessageEntrant] = []
        for element in liste.get("value") or []:
            identifiant = element["id"]
            # Le message entier, au format MIME : c'est ce que l'IMAP rend, et
            # donc ce que `depuis_message` sait lire, pièces jointes comprises.
            brut = self.client.appeler("GET", f"/messages/{quote(identifiant)}/$value").content
            message = depuis_message(brut)
            self._identifiants[message.message_id] = identifiant
            messages.append(message)
        return messages

    def marquer_traite(self, message_id: str) -> None:
        identifiant = self._identifiants.get(message_id)
        if identifiant is None:
            return
        try:
            self.client.appeler(
                "PATCH", f"/messages/{quote(identifiant)}", json={"isRead": True}
            )
        except ErreurGraph as exc:  # pragma: no cover - dépend du réseau
            # Le relevé reste rejouable : un message non marqué sera reconnu
            # comme déjà reçu au passage suivant.
            logger.warning("marquage impossible pour %s : %s", message_id, exc)


def _destinataire(adresse: str, nom: str = "") -> dict:
    email = {"address": adresse}
    if nom:
        email["name"] = nom
    return {"emailAddress": email}


def envoyer(
    config: ConfigOAuth,
    expediteur: str,
    destinataire: str,
    sujet: str,
    corps: str,
    *,
    nom_destinataire: str = "",
    copie: list[str] | None = None,
    nom_expediteur: str = "",
) -> None:
    """Expédie un message depuis la boîte `expediteur`, par `sendMail`.

    Le message est enregistré dans les éléments envoyés de la boîte : c'est là
    que le cabinet le cherchera s'il doit prouver un envoi depuis Outlook.
    """
    client = ClientGraph(config, expediteur)
    message: dict = {
        "subject": sujet,
        "body": {"contentType": "Text", "content": corps},
        "toRecipients": [_destinataire(destinataire, nom_destinataire)],
    }
    if copie:
        message["ccRecipients"] = [_destinataire(a) for a in copie]
    if nom_expediteur:
        # Graph n'envoie que depuis la boîte de l'URL ; le nom affiché, lui,
        # peut être précisé.
        message["from"] = _destinataire(expediteur, nom_expediteur)
    try:
        client.appeler(
            "POST", "/sendMail", json={"message": message, "saveToSentItems": True}
        )
    finally:
        client.fermer()


def verifier_envoi(config: ConfigOAuth, expediteur: str) -> None:
    """S'assure qu'on peut obtenir un jeton et atteindre la boîte, sans rien envoyer.

    Graph n'a pas d'équivalent à « ouvrir une session SMTP » : on lit les
    propriétés de la boîte d'envoi, ce qui valide le jeton, l'adresse et la
    permission de lecture. `Mail.Send` lui-même ne se vérifie qu'en envoyant.
    """
    client = ClientGraph(config, expediteur)
    try:
        client.appeler("GET", "/mailFolders/sentitems", params={"$select": "id"})
    finally:
        client.fermer()
