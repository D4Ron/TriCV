"""La boîte de recrutement sur Microsoft 365, par Microsoft Graph.

**Pourquoi Graph.** C'est la seule voie : Microsoft n'accepte plus aucun mot
de passe, et Graph ne demande que deux permissions d'application
(`Mail.ReadWrite`, `Mail.Send`) et le consentement de l'administrateur, dans
le même écran d'Entra — rien à régler côté Exchange.

**Ce que fait le module.** La boîte — `verifier`, `relever`, `marquer_traite`,
`fermer` — telle que le relevé l'attend (`courriel.SourceCourriel`). Le
message est récupéré au format MIME brut (`/$value`) et passe par
`depuis_message`, qui en tire l'expéditeur, l'objet et les pièces jointes.

S'y ajoute l'envoi, par `sendMail`.

**Restreindre l'accès à une seule boîte.** Une permission d'application vaut
pour toutes les boîtes de l'organisation. Le guide recommande de la limiter à
la boîte de recrutement (« RBAC for Applications » d'Exchange, ou l'ancienne
« Application Access Policy ») ; ce n'est pas un prérequis au fonctionnement,
c'est une précaution que l'administrateur doit connaître.
"""

from __future__ import annotations

import base64
import logging
from urllib.parse import quote

import httpx

from app.services import oauth_microsoft
from app.services.courriel import ErreurBoite, MessageEntrant, depuis_message
from app.services.oauth_microsoft import PORTEE_GRAPH, ConfigOAuth

logger = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"

# Les dossiers que Graph connaît par leur nom, quelle que soit la langue de la
# boîte. « INBOX », l'ancien nom de la boîte de réception, reste accepté : des
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
    """Les appels à Graph pour une boîte donnée. Synchrone : appelé dans un fil."""

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

    def appeler(
        self, methode: str, chemin: str, *, entetes: dict[str, str] | None = None, **options
    ) -> httpx.Response:
        url = chemin if chemin.startswith(f"{GRAPH}/") else f"{GRAPH}/users/{quote(self.boite)}{chemin}"
        try:
            reponse = self._http.request(
                methode, url, headers={**self._entetes(), **(entetes or {})}, **options
            )
        except httpx.HTTPError as exc:
            raise ErreurGraph(f"Impossible de joindre Microsoft Graph ({exc}).") from exc
        if reponse.status_code >= 400:
            raise ErreurGraph(_expliquer(reponse, self.boite))
        return reponse

    def fermer(self) -> None:
        self._http.close()


class BoiteGraph:
    """La boîte de recrutement Microsoft 365."""

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

    def relever(
        self, limite: int = 50, exclure: frozenset[str] | set[str] = frozenset()
    ) -> list[MessageEntrant]:
        """Les messages non lus, des plus anciens aux plus récents, sans limite de nombre.

        Le relevé ne s'arrêtait qu'aux cinquante premiers : une boîte de deux
        cents non lus n'était jamais vidée, et les messages laissés non lus faute
        de pièce lisible occupaient indéfiniment ces cinquante places. On
        parcourt donc toutes les pages, et les messages déjà traités — `exclure`,
        par identifiant Internet — sont sautés sans être téléchargés. `limite`
        borne le nombre de messages *nouveaux* rendus ; `reste` dit s'il y en a
        d'autres derrière, pour que l'appelant enchaîne.
        """
        self.reste = False
        params = {
            # Le tri exige que sa propriété ouvre le filtre (règle de Graph).
            "$filter": "receivedDateTime ge 1900-01-01T00:00:00Z and isRead eq false",
            "$orderby": "receivedDateTime asc",
            "$top": "50",
            "$select": "id,internetMessageId",
        }
        page = self.client.appeler("GET", f"{self._dossier()}/messages", params=params).json()
        messages: list[MessageEntrant] = []
        while True:
            for element in page.get("value") or []:
                if (element.get("internetMessageId") or "").strip() in exclure:
                    continue
                if len(messages) >= limite:
                    self.reste = True
                    return messages
                identifiant = element["id"]
                # Le message entier, au format MIME : ce que `depuis_message`
                # sait lire, pièces jointes comprises.
                brut = self.client.appeler("GET", f"/messages/{quote(identifiant)}/$value").content
                message = depuis_message(brut)
                self._identifiants[message.message_id] = identifiant
                messages.append(message)
            suite = page.get("@odata.nextLink")
            if not suite:
                return messages
            page = self.client.appeler("GET", _lien_graph(suite)).json()

    # --- la boîte, telle qu'un client de messagerie la montre --------------

    def lister(
        self, *, filtre: str = "tous", recherche: str = "", taille: int = 50, suite: str = ""
    ) -> dict:
        """Une page de messages, les plus récents d'abord, et le lien de la suivante."""
        if suite:
            page = self.client.appeler("GET", _lien_graph(suite)).json()
        else:
            params = {"$select": _CHAMPS_LISTE, "$top": str(max(1, min(taille, 100)))}
            if recherche.strip():
                # $search ne se combine pas avec un tri : Graph rend par pertinence.
                params["$search"] = '"' + recherche.strip().replace('"', '') + '"'
            else:
                params["$orderby"] = "receivedDateTime desc"
                conditions = []
                if filtre == "non_lus":
                    conditions.append("isRead eq false")
                elif filtre == "avec_pj":
                    conditions.append("hasAttachments eq true")
                if conditions:
                    params["$filter"] = " and ".join(
                        ["receivedDateTime ge 1900-01-01T00:00:00Z", *conditions]
                    )
            page = self.client.appeler(
                "GET", f"{self._dossier()}/messages", params=params
            ).json()
        return {
            "messages": [_resume(m) for m in page.get("value") or []],
            "suite": page.get("@odata.nextLink") or "",
        }

    def lire(self, identifiant: str) -> dict:
        """Un message en entier : corps en texte, destinataires, pièces jointes."""
        m = self.client.appeler(
            "GET",
            f"/messages/{quote(identifiant)}",
            params={"$select": _CHAMPS_LISTE + ",body,toRecipients,ccRecipients"},
            # Le corps en texte : du HTML d'un inconnu n'a rien à faire dans l'écran.
            entetes={"Prefer": 'outlook.body-content-type="text"'},
        ).json()
        pieces = self.client.appeler(
            "GET",
            f"/messages/{quote(identifiant)}/attachments",
            params={"$select": "id,name,contentType,size,isInline"},
        ).json()
        resume = _resume(m)
        resume["corps"] = ((m.get("body") or {}).get("content") or "")[:50_000]
        resume["destinataires"] = [
            (d.get("emailAddress") or {}).get("address", "")
            for d in (m.get("toRecipients") or []) + (m.get("ccRecipients") or [])
        ]
        resume["pieces"] = [
            {
                "id": a["id"],
                "nom": a.get("name") or "pièce jointe",
                "type": a.get("contentType") or "",
                "octets": int(a.get("size") or 0),
                "en_ligne": bool(a.get("isInline")),
            }
            for a in pieces.get("value") or []
        ]
        return resume

    def piece_jointe(self, identifiant: str, piece: str) -> tuple[bytes, str, str]:
        """Le contenu d'une pièce jointe : (octets, nom, type)."""
        a = self.client.appeler(
            "GET", f"/messages/{quote(identifiant)}/attachments/{quote(piece)}"
        ).json()
        contenu = a.get("contentBytes")
        if not contenu:
            raise ErreurGraph("Cette pièce jointe n'est pas un fichier (message joint ou lien).")
        return base64.b64decode(contenu), a.get("name") or "piece", a.get("contentType") or ""

    def message_complet(self, identifiant: str) -> MessageEntrant:
        """Le message au format MIME, lu comme le relevé le lit."""
        brut = self.client.appeler("GET", f"/messages/{quote(identifiant)}/$value").content
        message = depuis_message(brut)
        self._identifiants[message.message_id] = identifiant
        return message

    def du_meme_expediteur(self, adresse: str, taille: int = 25) -> list[dict]:
        """Les autres messages de cette adresse, dans toute la boîte.

        Un candidat envoie souvent son dossier en deux ou trois courriels — le CV,
        puis les diplômes, puis « j'ai oublié la lettre ». Les voir ensemble
        évite d'en faire trois dossiers.
        """
        adresse = adresse.strip().replace("'", "''")
        if not adresse:
            return []
        page = self.client.appeler(
            "GET",
            "/messages",
            params={
                "$filter": f"from/emailAddress/address eq '{adresse}'",
                "$select": _CHAMPS_LISTE,
                "$top": str(taille),
            },
        ).json()
        messages = [_resume(m) for m in page.get("value") or []]
        return sorted(messages, key=lambda m: m["recu_le"], reverse=True)

    def marquer_lu(self, identifiant: str, lu: bool = True) -> None:
        self.client.appeler("PATCH", f"/messages/{quote(identifiant)}", json={"isRead": lu})

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


_CHAMPS_LISTE = (
    "id,internetMessageId,subject,from,receivedDateTime,isRead,hasAttachments,"
    "bodyPreview,conversationId"
)


def _lien_graph(lien: str) -> str:
    """Un lien de page suivante, accepté seulement s'il mène bien à Graph.

    Il revient de l'écran : sans ce contrôle, n'importe quelle adresse
    recevrait le jeton de la boîte.
    """
    if not lien.startswith(f"{GRAPH}/"):
        raise ErreurGraph("Lien de page invalide.")
    return lien


def _resume(m: dict) -> dict:
    expediteur = (m.get("from") or {}).get("emailAddress") or {}
    return {
        "id": m.get("id", ""),
        "message_id": (m.get("internetMessageId") or "").strip(),
        "sujet": m.get("subject") or "",
        "expediteur": (expediteur.get("address") or "").lower(),
        "nom_expediteur": expediteur.get("name") or "",
        "recu_le": m.get("receivedDateTime") or "",
        "lu": bool(m.get("isRead")),
        "avec_pieces": bool(m.get("hasAttachments")),
        "apercu": (m.get("bodyPreview") or "")[:300],
        "conversation": m.get("conversationId") or "",
    }


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

    Graph n'a pas d'équivalent à « ouvrir une session » : on lit les
    propriétés de la boîte d'envoi, ce qui valide le jeton, l'adresse et la
    permission de lecture. `Mail.Send` lui-même ne se vérifie qu'en envoyant.
    """
    client = ClientGraph(config, expediteur)
    try:
        client.appeler("GET", "/mailFolders/sentitems", params={"$select": "id"})
    finally:
        client.fermer()
