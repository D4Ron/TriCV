"""Réception des candidatures par email.

C'est la voie d'arrivée réelle : les avis publiés demandent d'envoyer un
dossier à une adresse, pas de remplir un formulaire. Un message entrant devient
donc une candidature, ses pièces jointes deviennent des pièces du dossier, et
l'état civil est *deviné* depuis l'en-tête — donc marqué EXTRAIT_IA, ce qui
suffit à empêcher toute élimination automatique tant qu'un humain n'a pas relu.

La boîte est derrière un protocole (`SourceCourriel`) : le relevé se teste avec
une fausse boîte, sans serveur IMAP ni réseau.
"""

from __future__ import annotations

import email
import hashlib
import imaplib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.referentiel import PieceDossier
from app.models import (
    AccesClient,
    AuteurEchange,
    EchangeClient,
    TypeEchange,
    Avis,
    Candidat,
    Candidature,
    PieceCandidature,
    Poste,
    Provenance,
    SourceCandidature,
)
from app.services import doublons, extraction, storage
from app.services.preselection import charger_candidature, evaluer_candidature

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PieceJointe:
    nom: str
    donnees: bytes


@dataclass(slots=True)
class MessageEntrant:
    message_id: str
    expediteur: str
    nom_expediteur: str
    sujet: str
    recu_le: datetime
    corps: str = ""
    pieces: list[PieceJointe] = field(default_factory=list)


class SourceCourriel(Protocol):
    """Une boîte dont on peut relever les messages non traités."""

    def relever(self, limite: int = 50) -> list[MessageEntrant]: ...

    def marquer_traite(self, message_id: str) -> None: ...


def _decoder(valeur: str | None) -> str:
    if not valeur:
        return ""
    try:
        return str(make_header(decode_header(valeur)))
    except (UnicodeDecodeError, LookupError, ValueError):
        # Un en-tête mal encodé ne doit pas faire échouer tout le relevé.
        return valeur


def _corps_texte(message: Message) -> str:
    for partie in message.walk():
        if partie.get_content_type() == "text/plain" and not partie.get_filename():
            charge = partie.get_payload(decode=True)
            if charge:
                return charge.decode(partie.get_content_charset() or "utf-8", errors="replace")
    return ""


def depuis_message(brut: bytes) -> MessageEntrant:
    """Traduit un message RFC822 en objet du domaine."""
    message = email.message_from_bytes(brut)
    nom, adresse = parseaddr(message.get("From", ""))

    try:
        recu = parsedate_to_datetime(message.get("Date", "")) or datetime.utcnow()
    except (TypeError, ValueError):
        recu = datetime.utcnow()
    if recu.tzinfo is not None:
        recu = recu.astimezone(tz=None).replace(tzinfo=None)

    pieces: list[PieceJointe] = []
    for partie in message.walk():
        nom_fichier = partie.get_filename()
        if not nom_fichier:
            continue
        donnees = partie.get_payload(decode=True)
        if donnees:
            pieces.append(PieceJointe(nom=_decoder(nom_fichier), donnees=donnees))

    return MessageEntrant(
        message_id=message.get("Message-ID", "").strip() or f"sans-id-{recu.isoformat()}",
        expediteur=adresse.lower(),
        nom_expediteur=_decoder(nom),
        sujet=_decoder(message.get("Subject")),
        recu_le=recu,
        corps=_corps_texte(message),
        pieces=pieces,
    )


class ErreurBoite(Exception):
    """Un problème de boîte, formulé pour être lisible par les RH."""


@dataclass(slots=True)
class ConfigBoite:
    """Les coordonnées de la boîte, telles que réglées dans l'application.

    Passées en argument plutôt que lues dans la configuration globale : c'est
    ce qui permet de changer d'adresse depuis l'écran des paramètres, sans
    redémarrer le serveur ni éditer un fichier sur la machine.
    """

    hote: str
    port: int = 993
    utilisateur: str = ""
    mot_de_passe: str = ""
    dossier: str = "INBOX"


def _diagnostiquer(exc: Exception, config: ConfigBoite) -> ErreurBoite:
    """Traduit l'échec IMAP en quelque chose d'actionnable.

    « AUTHENTICATIONFAILED » ne dit rien à personne, alors que la cause est
    presque toujours la même chez Gmail : un mot de passe de compte au lieu
    d'un mot de passe d'application.
    """
    message = str(exc)
    hote = config.hote
    if "AUTHENTICATIONFAILED" in message.upper() or "Invalid credentials" in message:
        if "gmail" in hote.lower():
            return ErreurBoite(
                f"Gmail a refusé la connexion pour {config.utilisateur}. Gmail n'accepte "
                "plus le mot de passe du compte en IMAP : activez la validation en deux "
                "étapes, puis créez un « mot de passe d'application » et collez-le dans "
                "le champ « Mot de passe » des paramètres."
            )
        return ErreurBoite(f"Identifiants refusés par {hote} pour {config.utilisateur}.")
    if "NONEXISTENT" in message.upper() or "does not exist" in message.lower():
        return ErreurBoite(
            f"Le dossier « {config.dossier} » n'existe pas sur {hote}. "
            "Chez Gmail, un libellé s'écrit tel quel ; la boîte principale est INBOX."
        )
    if isinstance(exc, OSError):
        return ErreurBoite(f"Impossible de joindre {hote}:{config.port} ({exc}).")
    return ErreurBoite(f"Erreur IMAP : {message}")


class BoiteImap:
    """Boîte IMAP réelle, sur une connexion unique.

    La connexion est ouverte une fois et réutilisée : marquer chaque message
    lu par une nouvelle session ouvrait autant de connexions que de dossiers,
    ce qu'un fournisseur comme Gmail finit par refuser.
    """

    def __init__(self, config: ConfigBoite) -> None:
        if not config.hote:
            raise ErreurBoite(
                "Renseignez le serveur de la boîte dans Paramètres › Boîte de candidatures."
            )
        self.config = config
        self.host = config.hote
        self.port = config.port
        self.utilisateur = config.utilisateur
        self.mot_de_passe = config.mot_de_passe
        self.dossier = config.dossier
        self._connexion: imaplib.IMAP4_SSL | None = None
        # message-id -> identifiant IMAP, pour marquer sans refaire de recherche.
        self._identifiants: dict[str, bytes] = {}

    # --- connexion ---------------------------------------------------------

    def _session(self) -> imaplib.IMAP4_SSL:
        if self._connexion is not None:
            return self._connexion
        try:
            connexion = imaplib.IMAP4_SSL(self.host, self.port)
            connexion.login(self.utilisateur, self.mot_de_passe)
            connexion.select(self.dossier)
        except (imaplib.IMAP4.error, OSError) as exc:
            raise _diagnostiquer(exc, self.config) from exc
        self._connexion = connexion
        return connexion

    def fermer(self) -> None:
        if self._connexion is None:
            return
        try:
            self._connexion.close()
            self._connexion.logout()
        except (imaplib.IMAP4.error, OSError):  # pragma: no cover - fermeture
            pass
        finally:
            self._connexion = None

    def __enter__(self) -> BoiteImap:
        self._session()
        return self

    def __exit__(self, *_exc) -> None:
        self.fermer()

    # --- lecture -----------------------------------------------------------

    def verifier(self) -> dict:
        """Teste la connexion et compte les messages, sans rien lire."""
        connexion = self._session()
        _, tous = connexion.search(None, "ALL")
        _, non_lus = connexion.search(None, "UNSEEN")
        return {
            "boite": self.utilisateur,
            "dossier": self.dossier,
            "messages": len(tous[0].split()) if tous and tous[0] else 0,
            "non_lus": len(non_lus[0].split()) if non_lus and non_lus[0] else 0,
        }

    def relever(self, limite: int = 50) -> list[MessageEntrant]:
        connexion = self._session()
        _, reponse = connexion.search(None, "UNSEEN")
        identifiants = reponse[0].split()[:limite] if reponse and reponse[0] else []

        messages: list[MessageEntrant] = []
        for identifiant in identifiants:
            # BODY.PEEK : ne pas marquer lu avant d'avoir réussi à traiter.
            _, donnees = connexion.fetch(identifiant, "(BODY.PEEK[])")
            for element in donnees:
                if isinstance(element, tuple):
                    message = depuis_message(element[1])
                    self._identifiants[message.message_id] = identifiant
                    messages.append(message)
        return messages

    def marquer_traite(self, message_id: str) -> None:
        identifiant = self._identifiants.get(message_id)
        if identifiant is None:
            return
        try:
            self._session().store(identifiant, "+FLAGS", "\\Seen")
        except (imaplib.IMAP4.error, OSError) as exc:  # pragma: no cover
            logger.warning("marquage impossible pour %s : %s", message_id, exc)


# --- rattachement au poste --------------------------------------------------

# Référence d'avis citée dans l'objet, ex. « [AVIS-2026-014] Candidature ».
_REFERENCE = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9\-_/]{2,63})\]")


def references_du_sujet(sujet: str) -> list[str]:
    return _REFERENCE.findall(sujet or "")


async def poste_du_message(db: AsyncSession, message: MessageEntrant) -> Poste | None:
    """Rattache un message à un poste via la référence citée dans l'objet.

    Sans référence exploitable, le message n'est pas rattaché au hasard : il
    revient aux RH de l'affecter, ce qui vaut mieux qu'une candidature classée
    sous le mauvais avis.
    """
    for reference in references_du_sujet(message.sujet):
        resultat = await db.execute(
            select(Poste)
            .join(Avis, Avis.poste_id == Poste.id)
            .where(Avis.reference == reference)
            .limit(1)
        )
        poste = resultat.scalar_one_or_none()
        if poste is not None:
            return poste
    return None


def nom_prenom(message: MessageEntrant) -> tuple[str, str]:
    """Devine un nom et un prénom depuis l'en-tête From.

    Purement indicatif : le résultat porte la provenance EXTRAIT_IA et sera
    corrigé à la relecture. En dernier recours, la partie locale de l'adresse
    sert de nom pour que le dossier reste identifiable dans la liste.
    """
    brut = message.nom_expediteur.strip()
    if not brut:
        brut = message.expediteur.split("@")[0].replace(".", " ").replace("_", " ")
    morceaux = [m for m in re.split(r"[\s,]+", brut) if m]
    if not morceaux:
        return "Inconnu", ""
    if len(morceaux) == 1:
        return morceaux[0].title(), ""
    return morceaux[0].title(), " ".join(morceaux[1:]).title()


def type_de_piece(nom_fichier: str) -> str:
    """Classe une pièce jointe d'après son nom, à défaut de mieux."""
    normalise = nom_fichier.lower()
    if any(mot in normalise for mot in ("motivation", "lm", "lettre")):
        return PieceDossier.LETTRE_MOTIVATION.value
    if any(mot in normalise for mot in ("diplome", "diplôme", "attestation")):
        return PieceDossier.COPIE_DIPLOMES.value
    if any(mot in normalise for mot in ("cv", "resume", "curriculum")):
        return PieceDossier.CV.value
    return PieceDossier.CV.value


@dataclass(slots=True)
class ResultatReleve:
    crees: int = 0
    ignores: int = 0
    spontanees: int = 0
    # Réponses de promoteurs versées au fil de leur mandat.
    echanges_client: int = 0
    non_rattaches: list[str] = field(default_factory=list)
    sans_piece: list[str] = field(default_factory=list)


async def _deja_recu(db: AsyncSession, message_id: str) -> bool:
    resultat = await db.execute(
        select(Candidature.id).where(Candidature.message_id == message_id).limit(1)
    )
    return resultat.scalar_one_or_none() is not None


async def creer_depuis_message(
    db: AsyncSession, message: MessageEntrant, poste: Poste | None
) -> Candidature:
    nom, prenom = nom_prenom(message)
    candidat = Candidat(
        nom=nom,
        prenom=prenom,
        email=message.expediteur,
        # Deviné depuis l'en-tête : rien ici ne peut éliminer sans relecture.
        provenance=Provenance.EXTRAIT_IA,
    )
    db.add(candidat)
    await db.flush()

    candidature = Candidature(
        poste_id=poste.id if poste is not None else None,
        candidat_id=candidat.id,
        source=SourceCandidature.EMAIL,
        recue_le=message.recu_le,
        message_id=message.message_id,
        spontanee=poste is None,
        notes_rh=(
            f"Reçu par email — objet : {message.sujet}"
            if poste is not None
            else f"Candidature spontanée reçue par email — objet : {message.sujet}"
        ),
    )
    db.add(candidature)
    await db.flush()

    depot = storage.get_storage()
    for piece in message.pieces:
        type_mime = extraction.sniff_mime(piece.donnees, piece.nom)
        if type_mime not in extraction.ALLOWED_MIME_TYPES:
            # Signatures, images inline : ignorées sans faire échouer le reste.
            logger.info("pièce jointe ignorée (%s) : %s", type_mime, piece.nom)
            continue
        cle = await depot.save(storage.build_key(type_mime), piece.donnees)
        db.add(
            PieceCandidature(
                candidature_id=candidature.id,
                type_piece=type_de_piece(piece.nom),
                nom_fichier=piece.nom[:255],
                chemin_stockage=cle,
                type_mime=type_mime,
                taille_octets=len(piece.donnees),
                empreinte=hashlib.sha256(piece.donnees).hexdigest(),
            )
        )
    await db.flush()

    chargee = await charger_candidature(db, candidature.id)
    await evaluer_candidature(db, chargee)
    return chargee


async def apercu(
    db: AsyncSession, source: SourceCourriel, limite: int = 50
) -> list[dict]:
    """Ce qu'un relevé ferait, sans rien écrire.

    Premier contact avec une boîte réelle : on veut voir comment les messages
    se présentent — encodages, pièces jointes, objets — avant de laisser le
    relevé créer quoi que ce soit.
    """
    lignes: list[dict] = []
    for message in source.relever(limite):
        poste = await poste_du_message(db, message)
        pieces = [
            {
                "nom": p.nom,
                "octets": len(p.donnees),
                "type": extraction.sniff_mime(p.donnees, p.nom) or "inconnu",
                "retenue": extraction.sniff_mime(p.donnees, p.nom)
                in extraction.ALLOWED_MIME_TYPES,
            }
            for p in message.pieces
        ]
        nom, prenom = nom_prenom(message)
        acces = await acces_de_l_expediteur(db, message)
        if await _deja_recu(db, message.message_id):
            action = "deja_recu"
        elif acces is not None:
            action = "reponse_du_promoteur"
        elif not any(p["retenue"] for p in pieces):
            action = "aucune_piece_exploitable"
        elif poste is None:
            action = "creerait_une_candidature_spontanee"
        else:
            action = "creerait_une_candidature"

        lignes.append(
            {
                "action": action,
                "expediteur": message.expediteur,
                "nom_devine": f"{nom} {prenom}".strip(),
                "sujet": message.sujet,
                "recu_le": message.recu_le.isoformat(),
                "references": references_du_sujet(message.sujet),
                "poste": poste.intitule if poste else None,
                "pieces": pieces,
            }
        )
    return lignes


async def acces_de_l_expediteur(db: AsyncSession, message: MessageEntrant) -> AccesClient | None:
    """L'accès client correspondant à l'expéditeur, s'il y en a un d'ouvert.

    Un promoteur qui répond à un message du cabinet écrit depuis l'adresse à
    laquelle son accès a été ouvert. C'est un rattachement sûr — bien plus que
    la référence d'avis cherchée dans un objet — et il vaut d'être tenté en
    premier.
    """
    adresse = (message.expediteur or "").strip().lower()
    if not adresse:
        return None
    return (
        await db.execute(
            select(AccesClient)
            .where(AccesClient.email == adresse, AccesClient.revoque_le.is_(None))
            .order_by(AccesClient.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _deja_verse(db: AsyncSession, message_id: str) -> bool:
    """Ce message a-t-il déjà rejoint un fil ? Le relevé doit être rejouable."""
    if not message_id:
        return False
    return (
        await db.execute(
            select(EchangeClient.id).where(EchangeClient.message_id == message_id).limit(1)
        )
    ).scalar_one_or_none() is not None


async def verser_au_fil(
    db: AsyncSession, message: MessageEntrant, acces: AccesClient
) -> EchangeClient:
    """Range la réponse du promoteur dans le fil de son mandat.

    Le corps est repris tel quel, sans tentative de retirer la citation du
    message précédent : un découpage approximatif amputerait parfois la
    réponse elle-même, et une citation en trop se lit sans peine.
    """
    echange = EchangeClient(
        mandat_id=acces.mandat_id,
        auteur=AuteurEchange.CLIENT,
        auteur_nom=acces.nom,
        type_echange=TypeEchange.MESSAGE,
        objet=(message.sujet or None),
        corps=message.corps.strip() or "(message sans texte)",
        message_id=message.message_id,
        envoye_le=message.recu_le,
    )
    db.add(echange)
    await db.flush()
    return echange


async def relever(
    db: AsyncSession,
    source: SourceCourriel,
    limite: int = 50,
    accepter_spontanees: bool = True,
) -> ResultatReleve:
    """Relève la boîte et crée les candidatures.

    Un message déjà reçu est ignoré : le relevé peut donc être rejoué sans
    créer de doublons, ce qui compte si le marquage « lu » échoue.

    Un message sans référence d'avis mais porteur d'un CV lisible devient une
    **candidature spontanée** : le profil rejoint le vivier sans poste, prêt à
    ressortir le jour où un mandat lui correspond. Auparavant il était
    simplement signalé « non rattaché » et laissé de côté, ce qui revenait à
    jeter des candidatures que le cabinet avait bel et bien reçues.

    Un message venant d'un promoteur — reconnu à son adresse — rejoint le fil de
    son mandat plutôt que la file des candidatures. Sans quoi sa réponse restait
    dans la boîte, invisible de l'écran où le reste de l'échange se lit, et le
    fil « à côté du dossier » n'était vrai qu'à moitié.
    """
    resultat = ResultatReleve()

    for message in source.relever(limite):
        if await _deja_recu(db, message.message_id):
            resultat.ignores += 1
            source.marquer_traite(message.message_id)
            continue

        # Le promoteur d'abord : il écrit depuis une adresse connue, et sa
        # réponse n'est jamais une candidature — même si elle porte une pièce
        # jointe, qui serait alors un document de travail et non un CV.
        acces = await acces_de_l_expediteur(db, message)
        if acces is not None:
            if not await _deja_verse(db, message.message_id):
                await verser_au_fil(db, message, acces)
                resultat.echanges_client += 1
            else:
                resultat.ignores += 1
            source.marquer_traite(message.message_id)
            continue

        poste = await poste_du_message(db, message)

        # Un message sans pièce lisible — accusé de réception, question,
        # réponse automatique — n'est pas une candidature. Le créer polluerait
        # la grille d'un dossier vide que personne ne pourrait dépouiller.
        empreintes = [
            hashlib.sha256(p.donnees).hexdigest()
            for p in message.pieces
            if extraction.sniff_mime(p.donnees, p.nom) in extraction.ALLOWED_MIME_TYPES
        ]
        if not empreintes:
            # Sans référence *et* sans pièce, il n'y a rien à en tirer : le
            # message reste non lu pour qu'une personne le regarde.
            if poste is None:
                resultat.non_rattaches.append(message.sujet or message.expediteur)
            else:
                resultat.sans_piece.append(message.sujet or message.expediteur)
            continue

        if poste is None and not accepter_spontanees:
            resultat.non_rattaches.append(message.sujet or message.expediteur)
            continue

        if await doublons.trouver_identique(
            db, poste.id if poste is not None else None, empreintes
        ):
            resultat.ignores += 1
            source.marquer_traite(message.message_id)
            continue

        await creer_depuis_message(db, message, poste)
        if poste is None:
            resultat.spontanees += 1
        else:
            resultat.crees += 1
        source.marquer_traite(message.message_id)

    return resultat
