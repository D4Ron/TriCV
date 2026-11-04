"""Réception des candidatures par email.

C'est la voie d'arrivée réelle : les avis publiés demandent d'envoyer un
dossier à une adresse, pas de remplir un formulaire. Un message entrant devient
donc une candidature, ses pièces jointes deviennent des pièces du dossier, et
l'état civil est *deviné* depuis l'en-tête — donc marqué EXTRAIT_IA, ce qui
suffit à empêcher toute élimination automatique tant qu'un humain n'a pas relu.

La boîte est derrière un protocole (`SourceCourriel`) : le relevé se teste avec
une fausse boîte, sans Microsoft ni réseau. La vraie est la boîte Microsoft
365 de `graph_microsoft`.
"""

from __future__ import annotations

import email
import hashlib
import logging
import re
import time
import unicodedata

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
    ExpediteurIgnore,
    MessageTraite,
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
    StatutAvis,
)
from app.models import boite as traces
from app.services import decoupage, doublons, extraction, identite, liens, lots, storage
from app.services.preselection import charger_candidature, evaluer_candidature

logger = logging.getLogger(__name__)

# Secondes de travail par relevé, au-delà desquelles on rend la main.
BUDGET_DU_RELEVE = 40


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
    # Les adresses lues dans le texte et dans le HTML : des pièces envoyées
    # en lien (Google Drive, OneDrive…) plutôt qu'en pièce jointe.
    liens: list[str] = field(default_factory=list)


class SourceCourriel(Protocol):
    """Une boîte dont on peut relever les messages non traités.

    `exclure` : les identifiants Internet des messages déjà traités, que la
    boîte saute sans les télécharger. `reste`, après l'appel : d'autres
    messages attendent derrière la limite.
    """

    reste: bool

    def relever(
        self, limite: int = 50, exclure: frozenset[str] = frozenset()
    ) -> list[MessageEntrant]: ...

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

    corps = _corps_texte(message)
    adresses = liens_du_message(message, corps)
    return MessageEntrant(
        message_id=message.get("Message-ID", "").strip() or f"sans-id-{recu.isoformat()}",
        expediteur=adresse.lower(),
        nom_expediteur=_decoder(nom),
        sujet=_decoder(message.get("Subject")),
        recu_le=recu,
        corps=corps,
        pieces=pieces,
        liens=adresses,
    )


_HREF = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)


def liens_du_message(message: Message, corps: str) -> list[str]:
    """Les adresses du texte et des liens HTML — un courriel HTML cache ses
    liens derrière un libellé (« mon CV »), absents de la version texte."""
    adresses = [l.url for l in liens.liens_de_documents(corps)]
    for partie in message.walk():
        if partie.get_content_type() == "text/html" and not partie.get_filename():
            charge = partie.get_payload(decode=True) or b""
            html = charge.decode(partie.get_content_charset() or "utf-8", errors="replace")
            adresses.extend(l.url for l in liens.liens_de_documents(" ".join(_HREF.findall(html))))
    return list(dict.fromkeys(adresses))


@dataclass(slots=True)
class LiensJoints:
    recuperes: int = 0
    # « Google Drive : le lien n'est pas public… » — à dire aux RH.
    inaccessibles: list[str] = field(default_factory=list)


async def joindre_les_liens(message: MessageEntrant) -> LiensJoints:
    """Télécharge les documents envoyés en lien et les ajoute aux pièces.

    Seuls les liens publics des services connus sont suivis (voir
    `app.services.liens`). Un lien privé ou WeTransfer est signalé, pas perdu.
    """
    resultat = LiensJoints()
    noms = {p.nom.lower() for p in message.pieces}
    for lien in liens.liens_de_documents(" ".join(message.liens)):
        try:
            nom, donnees = await liens.telecharger(lien)
        except liens.LienInaccessible as exc:
            resultat.inaccessibles.append(f"{lien.service} : {exc}")
            continue
        base, point, extension = nom.rpartition(".")
        unique, n = nom, 2
        while unique.lower() in noms:
            unique, n = f"{base} ({n}).{extension}" if point else f"{nom} ({n})", n + 1
        noms.add(unique.lower())
        message.pieces.append(PieceJointe(nom=unique, donnees=donnees))
        resultat.recuperes += 1
    return resultat


class ErreurBoite(Exception):
    """Un problème de boîte, formulé pour être lisible par les RH."""


# --- rattachement au poste --------------------------------------------------

# Référence d'avis citée dans l'objet, ex. « [AVIS-2026-014] Candidature ».
_REFERENCE = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9\-_/]{2,63})\]")


def references_du_sujet(sujet: str) -> list[str]:
    return _REFERENCE.findall(sujet or "")


def _normaliser(texte: str) -> str:
    """Minuscules, sans accents ni ponctuation : « Chargé(e) d'Études » = « charge e d etudes »."""
    sans_accents = unicodedata.normalize("NFKD", texte or "")
    sans_accents = "".join(c for c in sans_accents if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", sans_accents.lower()).split())


async def poste_du_message(db: AsyncSession, message: MessageEntrant) -> Poste | None:
    """Rattache un message à un poste, par l'objet du courriel.

    Deux formes sont reconnues :

    - l'**intitulé du poste**, que les avis demandent d'écrire dans l'objet
      (« Candidature au poste de Chargé d'études ») : un candidat retient un
      intitulé, pas une référence ;
    - la **référence** entre crochets (« [AVIS-2026-014] »), que demandaient
      les avis plus anciens — ceux déjà diffusés continuent de fonctionner.

    Sans correspondance certaine, le message n'est pas rattaché au hasard : il
    revient aux RH de l'affecter, ce qui vaut mieux qu'une candidature classée
    sous le mauvais avis. Deux postes ouverts portant le même intitulé sont
    dans ce cas.
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

    sujet = f" {_normaliser(message.sujet)} "
    if not sujet.strip():
        return None
    # Les postes dont un avis est publié, puis ceux dont l'avis vient d'être
    # clôturé : un dossier envoyé la veille de la clôture arrive parfois après.
    for statuts in ((StatutAvis.PUBLIE,), (StatutAvis.CLOTURE,)):
        postes = (
            await db.execute(
                select(Poste)
                .join(Avis, Avis.poste_id == Poste.id)
                .where(Avis.statut.in_(statuts))
                .distinct()
            )
        ).scalars().all()
        trouves: dict[str, list[Poste]] = {}
        for poste in postes:
            intitule = _normaliser(poste.intitule)
            if len(intitule) >= 3 and f" {intitule} " in sujet:
                trouves.setdefault(intitule, []).append(poste)
        if trouves:
            # L'intitulé le plus long l'emporte : « directeur administratif et
            # financier » plutôt que « directeur ».
            plus_long = max(trouves, key=len)
            candidats = trouves[plus_long]
            return candidats[0] if len(candidats) == 1 else None
    return None


def nom_prenom(message: MessageEntrant) -> tuple[str, str]:
    """Devine un nom et un prénom depuis l'en-tête From.

    Purement indicatif : le résultat porte la provenance EXTRAIT_IA, le CV le
    corrige dès qu'il est lu (`identite.proposer`), et la relecture tranche.
    Le libellé ne sert que s'il désigne une personne — « Yahoo! » n'en est pas
    une —, sinon l'adresse.
    """
    nom, prenom = identite.depuis_entete(message.nom_expediteur, message.expediteur)
    return (nom or "Inconnu")[:255], prenom[:255]


def type_de_piece(nom_fichier: str) -> str:
    """Le type qu'un nom de fichier laisse penser ; « autre document » sinon.

    Rangeait en « CV » tout ce qu'elle ne reconnaissait pas : un passeport, une
    carte d'identité, un certificat de travail devenaient des CV. L'import
    d'un message passe désormais par `enregistrer_pieces`, qui lit aussi le
    contenu ; cette fonction reste pour qui n'a que le nom.
    """
    return lots.type_devine(nom_fichier) or PieceDossier.AUTRE.value


@dataclass(slots=True)
class ResultatReleve:
    crees: int = 0
    ignores: int = 0
    spontanees: int = 0
    # Réponses de promoteurs versées au fil de leur mandat.
    echanges_client: int = 0
    non_rattaches: list[str] = field(default_factory=list)
    sans_piece: list[str] = field(default_factory=list)
    # Messages d'un expéditeur ignoré : ni dossier, ni place dans la liste.
    expediteurs_ignores: int = 0
    # Documents envoyés en lien : récupérés, ou à ouvrir à la main.
    liens_recuperes: int = 0
    liens_inaccessibles: list[str] = field(default_factory=list)
    # Messages d'un candidat qui avait déjà un dossier : versés à celui-ci.
    fusionnes: int = 0
    # D'autres messages attendent : l'appelant relance pour la suite.
    reste: bool = False


async def deja_traites(db: AsyncSession) -> frozenset[str]:
    """Les identifiants Internet des messages que le relevé n'a plus à lire.

    Ceux qui ont une trace, ceux qui ont donné une candidature avant que la
    trace existe, et les réponses de promoteurs déjà versées à leur fil.
    """
    ids: set[str] = set()
    for colonne in (MessageTraite.message_id, Candidature.message_id, EchangeClient.message_id):
        ids.update(v for v in (await db.execute(select(colonne))).scalars() if v)
    return frozenset(ids)


async def regles_d_ignorance(db: AsyncSession) -> set[str]:
    return set((await db.execute(select(ExpediteurIgnore.motif_adresse))).scalars())


async def tracer(
    db: AsyncSession,
    message: MessageEntrant,
    statut: str,
    *,
    candidature_id: str | None = None,
    motif: str | None = None,
    utilisateur: str | None = None,
) -> None:
    """Note ce qui a été fait d'un message ; une trace existante est mise à jour."""
    if not message.message_id:
        return
    existante = (
        await db.execute(select(MessageTraite).where(MessageTraite.message_id == message.message_id))
    ).scalar_one_or_none()
    if existante is None:
        existante = MessageTraite(message_id=message.message_id)
        db.add(existante)
    existante.statut = statut
    existante.expediteur = (message.expediteur or "")[:320]
    existante.sujet = (message.sujet or "")[:512]
    existante.recu_le = message.recu_le
    existante.candidature_id = candidature_id or existante.candidature_id
    existante.motif = motif
    existante.traite_par = utilisateur
    await db.flush()


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

    preparees = await ranger_pieces(db, candidature, message)

    # Le CV dit le nom mieux que l'en-tête du courriel.
    cv = next((p for p in preparees if p.type_piece == PieceDossier.CV.value and p.texte), None)
    if cv is not None:
        proposition = identite.proposer(nom, prenom, cv.texte, message.expediteur, cv.titre)
        if proposition is not None:
            candidat.nom, candidat.prenom = proposition.nom[:255], proposition.prenom[:255]
            if proposition.avertissement:
                candidature.notes_rh = f"{candidature.notes_rh}\n{proposition.avertissement}"

    chargee = await charger_candidature(db, candidature.id)
    await lire_sans_ia(db, chargee)
    return chargee


async def lire_sans_ia(db: AsyncSession, candidature: Candidature) -> None:
    """La lecture locale du dossier, aussitôt reçu : rien ne part au modèle.

    Le dossier n'arrive plus vide dans la grille : diplômes, expériences et
    langues lus par règles, à confirmer. La lecture par l'IA suit en file, sans
    faire attendre le relevé. Une erreur ici ne doit jamais coûter l'import.
    """
    from app.services import depouillement, travaux

    try:
        await depouillement.depouiller(db, candidature, ia=False)
    except Exception as exc:  # noqa: BLE001 — le dossier est acquis, la lecture est un plus
        logger.warning("lecture locale impossible pour %s : %s", candidature.id, exc)
        await evaluer_candidature(db, candidature)
    await travaux.apres_arrivee(db, candidature.id, candidature.poste_id)


async def enregistrer_pieces(
    db: AsyncSession, candidature: Candidature, message: MessageEntrant
) -> int:
    """Range les pièces lisibles d'un message dans un dossier. Rend leur nombre.

    Sert aussi à verser au même dossier le deuxième courriel d'un candidat —
    « j'ai oublié les diplômes ». Une pièce déjà présente, au même contenu,
    n'est pas ajoutée deux fois.
    """
    return len(await ranger_pieces(db, candidature, message))


async def ranger_pieces(
    db: AsyncSession, candidature: Candidature, message: MessageEntrant
) -> list[decoupage.PiecePreparee]:
    """Lit, découpe et classe les pièces d'un message, puis les enregistre.

    Un PDF qui réunit tout le dossier est découpé en pièces (`decoupage`) ; un
    scan ou une photo est lu par OCR ; le texte lu est gardé avec la pièce pour
    ne pas refaire ce travail à chaque lecture du dossier.
    """
    deja = {
        e for e in (await db.execute(
            select(PieceCandidature.empreinte).where(PieceCandidature.candidature_id == candidature.id)
        )).scalars() if e
    }
    preparees: list[decoupage.PiecePreparee] = []
    for piece in message.pieces:
        type_mime = extraction.piece_retenue(piece.donnees, piece.nom)
        if type_mime is None:
            # Signatures, logos, images en ligne : ignorés sans faire échouer le reste.
            logger.info("pièce jointe ignorée : %s", piece.nom)
            continue
        # Comparée à ce que le dossier avait *avant* ce message seulement : deux
        # pièces d'un même envoi sont deux pièces, même au contenu identique.
        if hashlib.sha256(piece.donnees).hexdigest() in deja:
            continue
        preparees.extend(await decoupage.preparer(piece.nom, piece.donnees, type_mime))
    decoupage.completer_types(preparees)

    # Le même dossier fusionné renvoyé : ses morceaux sont déjà là.
    preparees = [p for p in preparees if hashlib.sha256(p.donnees).hexdigest() not in deja]
    depot = storage.get_storage()
    for piece in preparees:
        cle = await depot.save(storage.build_key(piece.type_mime), piece.donnees)
        db.add(
            PieceCandidature(
                candidature_id=candidature.id,
                type_piece=piece.type_piece or PieceDossier.AUTRE.value,
                intitule_libre=piece.intitule,
                nom_fichier=piece.nom[:255],
                chemin_stockage=cle,
                type_mime=piece.type_mime,
                taille_octets=len(piece.donnees),
                empreinte=hashlib.sha256(piece.donnees).hexdigest(),
                texte_extrait=piece.texte or None,
            )
        )
    await db.flush()
    return preparees


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
                "retenue": extraction.piece_retenue(p.donnees, p.nom) is not None,
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
    utilisateur: str | None = None,
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
    regles = await regles_d_ignorance(db)

    messages = source.relever(limite, exclure=await deja_traites(db))
    resultat.reste = bool(getattr(source, "reste", False))
    debut = time.monotonic()
    for message in messages:
        # Lire un dossier scanné prend du temps (OCR) : passé le budget, on rend
        # la main avec « il en reste », et le relevé suivant reprend là. Une
        # requête de plusieurs minutes serait coupée par le proxy, au milieu.
        if time.monotonic() - debut > BUDGET_DU_RELEVE:
            resultat.reste = True
            break
        if await _deja_recu(db, message.message_id):
            resultat.ignores += 1
            source.marquer_traite(message.message_id)
            continue

        # Un expéditeur qu'on a décidé d'ignorer — une lettre d'information, un
        # rapport automatique — ne produit plus de dossier. Le message reste
        # dans la boîte, intact : on ne fait que ne plus le lire.
        if traces.est_ignore(message.expediteur, regles):
            await tracer(db, message, traces.IGNORE, motif="expéditeur ignoré", utilisateur=utilisateur)
            resultat.expediteurs_ignores += 1
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
            await tracer(db, message, traces.IMPORTE, motif="réponse du promoteur", utilisateur=utilisateur)
            source.marquer_traite(message.message_id)
            continue

        poste = await poste_du_message(db, message)

        # Des documents envoyés en lien plutôt qu'en pièce jointe : on les
        # récupère, ils deviennent des pièces comme les autres.
        if message.liens:
            joints = await joindre_les_liens(message)
            resultat.liens_recuperes += joints.recuperes
            resultat.liens_inaccessibles.extend(
                f"{message.sujet or message.expediteur} — {e}" for e in joints.inaccessibles
            )

        # Un message sans pièce lisible — accusé de réception, question,
        # réponse automatique — n'est pas une candidature. Le créer polluerait
        # la grille d'un dossier vide que personne ne pourrait dépouiller.
        empreintes = [
            hashlib.sha256(p.donnees).hexdigest()
            for p in message.pieces
            if extraction.piece_retenue(p.donnees, p.nom)
        ]
        if not empreintes:
            # Sans référence *et* sans pièce, il n'y a rien à en tirer : le
            # message reste non lu pour qu'une personne le regarde.
            if poste is None:
                resultat.non_rattaches.append(message.sujet or message.expediteur)
            else:
                resultat.sans_piece.append(message.sujet or message.expediteur)
            # Noté pour ne pas le retélécharger à chaque relevé ; il reste non lu
            # dans la boîte, et l'écran de la boîte permet de l'importer quand même.
            await tracer(db, message, traces.SANS_PIECE, utilisateur=utilisateur)
            continue

        if poste is None and not accepter_spontanees:
            resultat.non_rattaches.append(message.sujet or message.expediteur)
            await tracer(
                db, message, traces.IGNORE,
                motif="hors avis, candidatures spontanées fermées", utilisateur=utilisateur,
            )
            continue

        if await doublons.trouver_identique(
            db, poste.id if poste is not None else None, empreintes
        ):
            resultat.ignores += 1
            await tracer(db, message, traces.IGNORE, motif="pièces déjà reçues", utilisateur=utilisateur)
            source.marquer_traite(message.message_id)
            continue

        cree = await creer_depuis_message(db, message, poste)
        # Le même candidat a déjà un dossier — renvoi, pièce oubliée, CV
        # corrigé : ses pièces nouvelles y sont versées, aucun second dossier.
        absorbe = await doublons.absorber(db, cree)
        if absorbe is not None:
            gardee, _ = absorbe
            await tracer(db, message, traces.IMPORTE, candidature_id=gardee.id, utilisateur=utilisateur)
            resultat.fusionnes += 1
            source.marquer_traite(message.message_id)
            continue
        await tracer(db, message, traces.IMPORTE, candidature_id=cree.id, utilisateur=utilisateur)
        if poste is None:
            resultat.spontanees += 1
        else:
            resultat.crees += 1
        source.marquer_traite(message.message_id)

    return resultat
