"""Les pièces envoyées en lien plutôt qu'en pièce jointe.

Constaté en production : des candidats envoient leurs documents un par un sous
forme de liens — Google Drive, OneDrive, Dropbox. Le relevé n'y voyait qu'un
message sans pièce, laissé non lu, et le dossier n'existait pas.

Ce module reconnaît ces liens et télécharge le document quand le lien est
public. Il ne contacte **que** les services connus, et seulement en HTTPS — y
compris après une redirection : un lien lu dans un courriel ne doit pas pouvoir
faire viser au serveur autre chose qu'un service de partage de fichiers. Un lien
qui demande une connexion, ou WeTransfer (qui ne permet pas le téléchargement
direct), est signalé « à ouvrir à la main » plutôt que perdu.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

import httpx

from app.services import extraction

# Un document de candidature dépasse rarement quelques mégaoctets ; au-delà,
# c'est autre chose qu'une pièce, ou une erreur.
MAX_OCTETS = 25 * 1024 * 1024
MAX_LIENS = 15
MAX_REDIRECTIONS = 5

# Les services dont on sait tirer le fichier d'un lien de partage.
_SERVICES = {
    "drive.google.com": "Google Drive",
    "docs.google.com": "Google Docs",
    "dropbox.com": "Dropbox",
    "www.dropbox.com": "Dropbox",
    "1drv.ms": "OneDrive",
    "onedrive.live.com": "OneDrive",
}
# Reconnus mais pas téléchargeables directement : on les montre seulement.
_SANS_TELECHARGEMENT = {"we.tl": "WeTransfer", "wetransfer.com": "WeTransfer"}

# Où une redirection de ces services peut mener.
_DESTINATIONS_PERMISES = (
    "drive.google.com",
    "docs.google.com",
    "drive.usercontent.google.com",
    ".googleusercontent.com",
    "dropbox.com",
    ".dropbox.com",
    ".dropboxusercontent.com",
    "1drv.ms",
    "onedrive.live.com",
    "api.onedrive.com",
    ".1drv.com",
    ".livefilestore.com",
    ".sharepoint.com",
)

_URL = re.compile(r"https?://[^\s<>\"'\]\)]+", re.IGNORECASE)


class LienInaccessible(Exception):
    """Le document n'a pas pu être récupéré. Le message est lisible par les RH."""


@dataclass(frozen=True, slots=True)
class LienDocument:
    url: str
    service: str
    # Faux pour WeTransfer & co : à ouvrir à la main.
    telechargeable: bool


def _service(hote: str) -> tuple[str, bool] | None:
    hote = hote.lower()
    if hote in _SERVICES:
        return _SERVICES[hote], True
    if hote.endswith(".sharepoint.com") or hote.endswith("-my.sharepoint.com"):
        return "OneDrive / SharePoint", True
    if hote in _SANS_TELECHARGEMENT:
        return _SANS_TELECHARGEMENT[hote], False
    return None


def liens_de_documents(texte: str) -> list[LienDocument]:
    """Les liens de partage de fichiers d'un texte, dans l'ordre, sans doublon."""
    vus: set[str] = set()
    liens: list[LienDocument] = []
    for brut in _URL.findall(texte or ""):
        url = brut.rstrip(".,;:!?»")
        if url in vus:
            continue
        hote = urlparse(url).hostname or ""
        reconnu = _service(hote)
        if reconnu is None:
            continue
        vus.add(url)
        liens.append(LienDocument(url=url, service=reconnu[0], telechargeable=reconnu[1]))
        if len(liens) >= MAX_LIENS:
            break
    return liens


def _id_google(url: str) -> str | None:
    morceaux = urlparse(url)
    trouve = re.search(r"/d/([A-Za-z0-9_-]{10,})", morceaux.path)
    if trouve:
        return trouve.group(1)
    ids = parse_qs(morceaux.query).get("id")
    return ids[0] if ids else None


def url_de_telechargement(lien: LienDocument) -> str | None:
    """L'adresse qui rend le fichier lui-même, et non la page qui le montre."""
    if not lien.telechargeable:
        return None
    morceaux = urlparse(lien.url)
    hote = (morceaux.hostname or "").lower()
    if hote == "docs.google.com":
        identifiant = _id_google(lien.url)
        if not identifiant:
            return None
        # Un document Google Docs s'exporte en PDF ; une feuille ou une
        # présentation aussi.
        for genre in ("document", "spreadsheets", "presentation"):
            if f"/{genre}/" in morceaux.path:
                return f"https://docs.google.com/{genre}/d/{identifiant}/export?format=pdf"
        return f"https://drive.usercontent.google.com/download?id={identifiant}&export=download&confirm=t"
    if hote == "drive.google.com":
        identifiant = _id_google(lien.url)
        if not identifiant:
            return None
        # `confirm=t` passe l'avertissement « fichier trop gros pour être analysé ».
        return f"https://drive.usercontent.google.com/download?id={identifiant}&export=download&confirm=t"
    if hote in ("dropbox.com", "www.dropbox.com"):
        requete = parse_qs(morceaux.query)
        requete["dl"] = ["1"]
        return urlunparse(morceaux._replace(query=urlencode(requete, doseq=True)))
    if hote in ("1drv.ms", "onedrive.live.com"):
        # L'API publique de OneDrive résout un lien de partage anonyme.
        jeton = base64.urlsafe_b64encode(lien.url.encode()).decode().rstrip("=")
        return f"https://api.onedrive.com/v1.0/shares/u!{jeton}/root/content"
    if hote.endswith(".sharepoint.com"):
        requete = parse_qs(morceaux.query)
        requete["download"] = ["1"]
        return urlunparse(morceaux._replace(query=urlencode(requete, doseq=True)))
    return None


def _destination_permise(url: str) -> bool:
    morceaux = urlparse(url)
    if morceaux.scheme != "https" or not morceaux.hostname:
        return False
    hote = morceaux.hostname.lower()
    if re.fullmatch(r"[\d.]+|\[.*\]", hote):
        return False
    return any(
        hote == d or (d.startswith(".") and hote.endswith(d))
        for d in _DESTINATIONS_PERMISES
    )


def _nom_du_fichier(reponse: httpx.Response, url: str) -> str:
    disposition = reponse.headers.get("content-disposition", "")
    etoile = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", disposition, re.IGNORECASE)
    if etoile:
        return unquote(etoile.group(1).strip().strip('"'))
    simple = re.search(r'filename="?([^";]+)"?', disposition, re.IGNORECASE)
    if simple:
        return simple.group(1).strip()
    dernier = urlparse(url).path.rstrip("/").rpartition("/")[2]
    return unquote(dernier) or "document"


async def telecharger(lien: LienDocument, client: httpx.AsyncClient | None = None) -> tuple[str, bytes]:
    """Le document derrière un lien public : (nom, octets). Lève `LienInaccessible`."""
    adresse = url_de_telechargement(lien)
    if adresse is None:
        raise LienInaccessible(f"{lien.service} ne permet pas le téléchargement direct : à ouvrir à la main.")
    if not _destination_permise(adresse):
        raise LienInaccessible("Adresse refusée.")

    propre = client is None
    client = client or httpx.AsyncClient(timeout=30, follow_redirects=False)
    try:
        for _ in range(MAX_REDIRECTIONS + 1):
            async with client.stream("GET", adresse) as reponse:
                if reponse.status_code in (301, 302, 303, 307, 308):
                    suivante = reponse.headers.get("location", "")
                    suivante = str(httpx.URL(adresse).join(suivante))
                    if not _destination_permise(suivante):
                        raise LienInaccessible(
                            f"Le lien {lien.service} renvoie vers une page de connexion ou un "
                            "autre site : il n'est sans doute pas public."
                        )
                    adresse = suivante
                    continue
                if reponse.status_code in (401, 403, 404):
                    raise LienInaccessible(
                        f"Le lien {lien.service} n'est pas public (HTTP {reponse.status_code}) : "
                        "demander au candidat de le partager à « toute personne disposant du lien »."
                    )
                if reponse.status_code >= 400:
                    raise LienInaccessible(f"{lien.service} a refusé (HTTP {reponse.status_code}).")
                taille = int(reponse.headers.get("content-length") or 0)
                if taille > MAX_OCTETS:
                    raise LienInaccessible("Document trop volumineux pour une pièce de candidature.")
                morceaux: list[bytes] = []
                total = 0
                async for bloc in reponse.aiter_bytes():
                    total += len(bloc)
                    if total > MAX_OCTETS:
                        raise LienInaccessible("Document trop volumineux pour une pièce de candidature.")
                    morceaux.append(bloc)
                donnees = b"".join(morceaux)
                nom = _nom_du_fichier(reponse, adresse)
                break
        else:
            raise LienInaccessible("Trop de redirections.")
    except httpx.HTTPError as exc:
        raise LienInaccessible(f"{lien.service} injoignable ({type(exc).__name__}).") from exc
    finally:
        if propre:
            await client.aclose()

    # Une page HTML à la place du fichier : connexion demandée, ou fichier privé.
    if extraction.sniff_mime(donnees, nom) not in extraction.ALLOWED_MIME_TYPES:
        raise LienInaccessible(
            f"Le lien {lien.service} ne mène pas à un PDF ou un document Word lisible "
            "(lien privé, ou autre format)."
        )
    if "." not in nom:
        nom = f"{nom}.pdf" if donnees[:4] == b"%PDF" else f"{nom}.docx"
    return nom[:200], donnees


__all__ = [
    "LienDocument",
    "LienInaccessible",
    "liens_de_documents",
    "telecharger",
    "url_de_telechargement",
]
