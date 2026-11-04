"""Candidatures : dépôt, consultation, vérification, arbitrage.

Trois actions sont réservées à un humain et ne peuvent pas être déduites :
confirmer des données extraites, lever un motif d'élimination, saisir une note
manuelle. Toutes les trois exigent un motif écrit et passent au journal.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict, dataclass

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.postes import get_poste_or_404
from app.domain import Qualification, sections_entretien
from app.deps import CurrentUser, DbSession
from app.domain.referentiel import PieceDossier
from app.models import (
    Candidat,
    Candidature,
    DiplomeCandidat,
    Elimination,
    ExperienceCandidat,
    MessageEnvoye,
    Notation,
    PieceCandidature,
    Provenance,
    SourceCandidature,
    StatutCandidature,
)
from app.models.base import utcnow
from app.models.boite import SUPPRIME as MessageTraite_SUPPRIME
from app.models.boite import MessageTraite
from app.schemas.recrutement import (
    ExperienceCompteeIn,
    SyntheseOut,
    AppreciationIn,
    CandidatureCreate,
    EntretienIn,
    EntretienOut,
    FicheJureOut,
    LigneEntretienOut,
    QualificationIn,
    DoublonOut,
    CandidatureListItem,
    CandidatureOut,
    CandidaturesPage,
    EliminationOut,
    LeveeIn,
    NoteManuelleIn,
    VerificationIn,
)
from app.services import (
    lots,
    audit,
    decoupage,
    extraction,
    identite,
    courriel,
    depouillement,
    doublons,
    entretiens,
    graph_microsoft,
    parametres,
    storage,
    synthese,
    uploads,
)
from app.services.preselection import (
    charger_candidature,
    construire_bareme,
    evaluer_candidature,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["candidatures"])

PAGE_MAX = 200


async def get_candidature_or_404(db: AsyncSession, candidature_id: str) -> Candidature:
    candidature = await charger_candidature(db, candidature_id)
    if candidature is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidature introuvable")
    return candidature


def _vers_sortie(candidature: Candidature) -> CandidatureOut:
    sortie = CandidatureOut.model_validate(candidature)
    for motif in sortie.eliminations:
        motif.libelle = motif.motif.libelle
    if candidature.poste is not None:
        sortie.appreciation_max = construire_bareme(
            candidature.poste
        ).consistance.points_appreciation
    retenue = candidature.qualification_manuelle or candidature.qualification
    if retenue:
        sortie.qualification = retenue
        try:
            sortie.qualification_libelle = Qualification(retenue).libelle
        except ValueError:
            sortie.qualification_libelle = retenue
    sortie.synthese = SyntheseOut(**asdict(synthese.rediger(candidature)))
    return sortie


@router.post(
    "/postes/{poste_id}/candidatures",
    response_model=CandidatureOut,
    status_code=status.HTTP_201_CREATED,
)
async def deposer_candidature(
    poste_id: str, payload: CandidatureCreate, db: DbSession, user: CurrentUser
) -> CandidatureOut:
    """Saisie d'un dossier par les RH, puis évaluation immédiate.

    Le calcul est synchrone : il est purement arithmétique et ne sort pas de
    la machine, donc il n'y a rien à mettre en file d'attente.
    """
    poste = await get_poste_or_404(db, poste_id)
    entree = payload.candidat

    candidat = Candidat(
        **entree.model_dump(exclude={"diplomes", "experiences"}),
        provenance=Provenance.SAISI_RH,
    )
    db.add(candidat)
    await db.flush()

    for diplome in entree.diplomes:
        db.add(
            DiplomeCandidat(
                candidat_id=candidat.id, provenance=Provenance.SAISI_RH, **diplome.model_dump()
            )
        )
    for experience in entree.experiences:
        db.add(
            ExperienceCandidat(
                candidat_id=candidat.id,
                provenance=Provenance.SAISI_RH,
                **experience.model_dump(),
            )
        )

    candidature = Candidature(
        poste_id=poste.id,
        candidat_id=candidat.id,
        source=payload.source,
        recue_le=payload.recue_le or utcnow(),
    )
    db.add(candidature)
    await db.flush()

    # Pièces cochées comme reçues, sans fichier pour l'instant : c'est la
    # réception qui détermine la complétude, pas le classement.
    for code in dict.fromkeys(payload.pieces_fournies):
        db.add(PieceCandidature(candidature_id=candidature.id, type_piece=code))
    await db.flush()

    chargee = await charger_candidature(db, candidature.id)
    await evaluer_candidature(db, chargee)
    await audit.record(
        db,
        action="candidature.create",
        entity_type="candidature",
        entity_id=chargee.id,
        user_id=user.id,
        details={"poste": poste.intitule, "source": payload.source.value},
    )
    await db.commit()

    return _vers_sortie(await get_candidature_or_404(db, chargee.id))


@dataclass(slots=True)
class _FichierRecu:
    """Un fichier prêt à être classé : contenu lu, origine connue."""

    nom: str
    donnees: bytes
    # Le chemin relatif d'où il vient, quand il en a un — sélection de
    # répertoire, ou arborescence interne d'une archive.
    chemin: str = ""
    # Le groupe imposé par l'appelant. Prime sur toute déduction.
    groupe: str | None = None
    type_piece: str | None = None


async def _lire_lot(
    fichiers: list[UploadFile],
    chemins: list[str],
    groupes: list[str],
    types: list[str],
) -> tuple[list[_FichierRecu], list[dict]]:
    """Lit les fichiers reçus, en dépliant les archives.

    Une archive n'est pas un dossier de candidature : c'est un contenant. On
    l'ouvre ici pour que la suite ne voie que des pièces, et pour que les
    limites de sécurité soient posées à un seul endroit.
    """
    recus: list[_FichierRecu] = []
    refuses: list[dict] = []

    for index, fichier in enumerate(fichiers):
        nom = (fichier.filename or "dossier").strip()
        chemin = chemins[index] if index < len(chemins) else ""
        groupe = groupes[index] if index < len(groupes) else ""
        type_impose = types[index] if index < len(types) else ""
        donnees = await fichier.read()

        if lots.est_archive(nom, donnees):
            try:
                extraits = lots.extraire(nom, donnees)
            except lots.ArchiveRefusee as exc:
                refuses.append({"fichier": nom, "accepte": False, "erreur": str(exc)})
                continue
            # Tout ce qu'une archive contient appartient au même dossier, sauf
            # si elle est elle-même rangée par sous-dossiers.
            defaut = groupe or Path(nom).stem
            for extrait in extraits:
                recus.append(
                    _FichierRecu(
                        nom=extrait.nom,
                        donnees=extrait.donnees,
                        chemin=f"{extrait.dossier}/{extrait.nom}" if extrait.dossier else "",
                        groupe=extrait.dossier or defaut,
                    )
                )
            continue

        recus.append(
            _FichierRecu(
                nom=nom,
                donnees=donnees,
                chemin=chemin,
                groupe=groupe or None,
                type_piece=type_impose or None,
            )
        )
    return recus, refuses


def _regrouper(recus: list[_FichierRecu]) -> list[tuple[str, list[_FichierRecu]]]:
    """Classe les fichiers par candidat.

    Le groupe imposé par l'appelant l'emporte : l'interface a montré le
    découpage et quelqu'un l'a validé. À défaut, on retombe sur la proposition
    automatique — le chemin d'abord, le nom du fichier ensuite.
    """
    imposes = [f for f in recus if f.groupe]
    devines = [f for f in recus if not f.groupe]

    groupes: dict[str, list[_FichierRecu]] = {}
    for fichier in imposes:
        groupes.setdefault(fichier.groupe or "", []).append(fichier)

    if devines:
        proposition = lots.proposer(
            [f.nom for f in devines], [f.chemin for f in devines]
        )
        for dossier in proposition:
            groupes.setdefault(dossier.libelle or dossier.cle, []).extend(
                devines[p.index] for p in dossier.pieces
            )
    return list(groupes.items())


@router.post("/postes/{poste_id}/candidatures/depot-multiple/apercu")
async def apercu_depot_multiple(
    poste_id: str,
    db: DbSession,
    _: CurrentUser,
    noms: list[str] = Form(...),
    chemins: list[str] | None = Form(default=None),
) -> dict:
    """Le découpage proposé pour un lot, sans rien envoyer ni écrire.

    Seuls les *noms* circulent : l'écran a besoin de montrer le regroupement
    avant qu'on téléverse cent fichiers, et faire monter les contenus pour un
    aperçu serait long pour rien.
    """
    await get_poste_or_404(db, poste_id)
    proposition = lots.proposer(noms, chemins or [])
    return {
        "dossiers": [
            {
                "cle": d.cle,
                "libelle": d.libelle,
                "depuis_arborescence": d.depuis_arborescence,
                "pieces": [
                    {"nom": p.nom, "type_piece": p.type_piece, "index": p.index}
                    for p in d.pieces
                ],
            }
            for d in proposition
        ]
    }


@router.post(
    "/postes/{poste_id}/candidatures/depot-multiple",
    status_code=status.HTTP_201_CREATED,
)
async def depot_multiple(
    poste_id: str,
    db: DbSession,
    user: CurrentUser,
    fichiers: list[UploadFile] = File(...),
    type_piece: str = Form(default="CV"),
    depouiller_aussitot: bool = Form(default=False),
    chemins: list[str] | None = Form(default=None),
    groupes: list[str] | None = Form(default=None),
    types_pieces: list[str] | None = Form(default=None),
) -> dict:
    """Dépôt en lot de dossiers déjà en main — typiquement une boîte email
    vidée à la main.

    Un candidat envoie rarement un seul fichier : il joint son CV, sa lettre,
    ses diplômes, ses attestations. Ces fichiers forment **un** dossier, et
    `groupes[i]` dit auquel appartient `fichiers[i]`. Sans regroupement fourni,
    il est déduit du chemin d'origine puis du nom du fichier — et un `.zip` par
    candidat est déplié comme un dossier à lui seul.

    Personne n'ayant rien saisi, l'état civil se réduit au nom du fichier et
    porte la provenance EXTRAIT_IA : les dossiers atterrissent en A_VERIFIER,
    jamais éliminés ni présélectionnés d'office.

    Un fichier refusé n'interrompt pas le lot : le compte rendu dit lequel et
    pourquoi.
    """
    poste = await get_poste_or_404(db, poste_id)
    recus, resultats = await _lire_lot(
        fichiers, chemins or [], groupes or [], types_pieces or []
    )

    for libelle, pieces in _regrouper(recus):
        acceptees: list[tuple[_FichierRecu, uploads.AcceptedFile]] = []
        for recu in pieces:
            try:
                # Dépôt authentifié : aucune limite de taille.
                accepte = uploads.valider_octets(recu.donnees, recu.nom)
            except uploads.RejectedUpload as exc:
                resultats.append({"fichier": recu.nom, "accepte": False, "erreur": str(exc)})
                continue
            if accepte.mime_type in extraction.IMAGE_MIME_TYPES and not extraction.image_utile(accepte.data):
                # Logo de signature, icône : une archive de courriels en est pleine.
                resultats.append(
                    {
                        "fichier": recu.nom,
                        "accepte": False,
                        "erreur": "Image trop petite pour être un document (logo, icône) : ignorée.",
                    }
                )
                continue
            acceptees.append((recu, accepte))

        if not acceptees:
            continue

        # Dossier déjà reçu pour ce poste : rien à en tirer, on n'en ouvre pas
        # un second. Le compte rendu dit lequel il duplique.
        identique = await doublons.trouver_identique(
            db, poste.id, [a.sha256 for _, a in acceptees]
        )
        if identique is not None:
            for recu, _ in acceptees:
                resultats.append(
                    {
                        "fichier": recu.nom,
                        "accepte": False,
                        "doublon_de": identique[1],
                        "erreur": (
                            f"Doublon du dossier de {identique[1]} — fichier identique, ignoré."
                        ),
                    }
                )
            continue

        # Le regroupement est le seul indice disponible ; il sera corrigé au
        # dépouillement ou à la relecture. La lecture assistée, elle, ne rendra
        # pas l'état civil : la rédaction retire noms et coordonnées du texte
        # avant qu'il ne parte au modèle. Ce nom-là est donc celui qui restera
        # dans la grille, et le laisser d'un bloc dans `nom` vidait la colonne
        # « prénom » de tout dossier arrivé en lot.
        nom, prenom = lots.separer_identite(
            libelle or Path(acceptees[0][0].nom).stem
        )
        candidat = Candidat(
            nom=nom or "Dossier",
            prenom=prenom,
            provenance=Provenance.EXTRAIT_IA,
        )
        db.add(candidat)
        await db.flush()

        origines = ", ".join(recu.nom for recu, _ in acceptees)
        candidature = Candidature(
            poste_id=poste.id,
            candidat_id=candidat.id,
            source=SourceCandidature.IMPORT_MANUEL,
            recue_le=utcnow(),
            notes_rh=f"Déposé en lot — fichier(s) d'origine : {origines}",
        )
        db.add(candidature)
        await db.flush()

        # Le type imposé prime ; sinon le nom, puis le contenu — page par page
        # pour un PDF qui réunit tout le dossier, qui est alors découpé.
        preparees: list[decoupage.PiecePreparee] = []
        for recu, accepte in acceptees:
            preparees.extend(
                await decoupage.preparer(
                    accepte.filename, accepte.data, accepte.mime_type, recu.type_piece or None
                )
            )
        if len(preparees) == 1 and preparees[0].type_piece is None:
            preparees[0].type_piece = type_piece
        decoupage.completer_types(preparees)
        depot = storage.get_storage()
        for piece in preparees:
            db.add(
                PieceCandidature(
                    candidature_id=candidature.id,
                    type_piece=piece.type_piece or PieceDossier.AUTRE.value,
                    nom_fichier=piece.nom[:255],
                    chemin_stockage=await depot.save(storage.build_key(piece.type_mime), piece.donnees),
                    type_mime=piece.type_mime,
                    taille_octets=len(piece.donnees),
                    empreinte=hashlib.sha256(piece.donnees).hexdigest(),
                    intitule_libre=piece.intitule,
                    texte_extrait=piece.texte or None,
                )
            )
        await db.flush()

        # Le nom lu dans le CV — avec la ligne en plus gros caractères, connue
        # ici seulement — vaut mieux que celui du fichier ou du dossier.
        cv = next((p for p in preparees if p.type_piece == PieceDossier.CV.value and p.texte), None)
        if cv is not None:
            proposition = identite.proposer(candidat.nom, candidat.prenom, cv.texte, "", cv.titre)
            if proposition is not None and not proposition.avertissement:
                candidat.nom, candidat.prenom = proposition.nom[:255], proposition.prenom[:255]
                await db.flush()

        chargee = await charger_candidature(db, candidature.id)
        # Lecture locale toujours — elle ne coûte rien et corrige le nom tiré
        # du fichier ; l'IA seulement si on l'a demandée.
        lecture: str | None = None
        try:
            resume = await depouillement.depouiller(db, chargee, ia=depouiller_aussitot)
            lecture = f"{resume.diplomes} diplôme(s), {resume.experiences} expérience(s)"
        except Exception as exc:
            # Le dépôt est acquis ; la lecture est un service rendu en plus.
            # Sans ce garde-fou, un seul CV illisible — ou une panne du
            # fournisseur sur le trentième fichier — remontait en 500, le
            # `commit` final n'avait jamais lieu, et **tout le lot était
            # perdu**. Cent dossiers déposés à la main disparaissaient parce
            # qu'un modèle n'avait pas répondu.
            logger.warning("dépouillement impossible au dépôt de %s : %s", candidature.id, exc)
            lecture = f"lecture impossible : {exc}"
            await evaluer_candidature(db, chargee)

        # Le lot est le cas où les doublons apparaissent. Un doublon n'est plus
        # ouvert puis signalé : ses pièces nouvelles rejoignent le dossier
        # existant, et rien d'autre n'est créé. Après la lecture, qui a pu
        # trouver l'adresse ou la date de naissance qui le révèlent.
        absorbe = await doublons.absorber(db, chargee)
        if absorbe is not None:
            gardee, doublon = absorbe
            resultats.append(
                {
                    "fichier": origines,
                    "accepte": False,
                    "doublon_de": doublon.nom_complet,
                    "candidature_id": gardee.id,
                    "erreur": (
                        f"Doublon du dossier de {doublon.nom_complet} ({doublon.libelle.lower()}) : "
                        "ses pièces nouvelles y ont été versées, aucun second dossier."
                    ),
                }
            )
            continue

        resultats.append(
            {
                "fichier": origines,
                "accepte": True,
                "candidature_id": candidature.id,
                "pieces": len(acceptees),
                "lecture": lecture,
                "doublons": [],
            }
        )

    acceptes = [r for r in resultats if r["accepte"]]
    ignores = [r for r in resultats if not r["accepte"] and r.get("doublon_de")]
    await audit.record(
        db,
        action="poste.depot_multiple",
        entity_type="poste",
        entity_id=poste.id,
        user_id=user.id,
        details={
            "deposes": len(acceptes),
            "refuses": len(resultats) - len(acceptes) - len(ignores),
            "doublons_ignores": len(ignores),
        },
    )
    await db.commit()

    return {
        "deposes": len(acceptes),
        "pieces": sum(r.get("pieces", 0) for r in acceptes),
        "refuses": len(resultats) - len(acceptes) - len(ignores),
        "doublons_ignores": len(ignores),
        "doublons": sum(1 for r in acceptes if r["doublons"]),
        "resultats": resultats,
    }


@router.get("/postes/{poste_id}/candidatures", response_model=CandidaturesPage)
async def lister_candidatures(
    poste_id: str,
    db: DbSession,
    _: CurrentUser,
    statut: StatutCandidature | None = Query(default=None),
    note_min: float | None = Query(default=None, ge=0),
    recherche: str | None = Query(default=None),
    tri: str = Query(default="note", pattern="^(note|nom|date)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=PAGE_MAX),
) -> CandidaturesPage:
    await get_poste_or_404(db, poste_id)

    # Jointure explicite sur la notation : le tri et le filtre sur la note se
    # font en SQL, pas après chargement de toutes les candidatures.
    base = (
        select(Candidature, Candidat, Notation)
        .join(Candidat, Candidat.id == Candidature.candidat_id)
        .outerjoin(Notation, Notation.candidature_id == Candidature.id)
        .where(Candidature.poste_id == poste_id)
    )
    if statut is not None:
        base = base.where(Candidature.statut == statut)
    if note_min is not None:
        base = base.where(Notation.total >= note_min)
    if recherche:
        motif = f"%{recherche}%"
        base = base.where(Candidat.nom.ilike(motif) | Candidat.prenom.ilike(motif))

    total = await db.execute(
        select(func.count()).select_from(base.order_by(None).subquery())
    )

    match tri:
        case "nom":
            base = base.order_by(Candidat.nom, Candidat.prenom)
        case "date":
            base = base.order_by(Candidature.recue_le.desc())
        case _:
            # Les non-notés en dernier plutôt qu'en tête.
            base = base.order_by(Notation.total.desc().nullslast(), Candidat.nom)

    lignes = await db.execute(base.offset((page - 1) * page_size).limit(page_size))

    items: list[CandidatureListItem] = []
    for candidature, candidat, notation in lignes:
        items.append(
            CandidatureListItem(
                id=candidature.id,
                statut=candidature.statut,
                source=candidature.source,
                recue_le=candidature.recue_le,
                nom=candidat.nom,
                prenom=candidat.prenom,
                note=float(notation.note_retenue) if notation else None,
                total_max=float(notation.total_max) if notation else None,
                atteint_le_seuil=notation.atteint_le_seuil if notation else None,
                a_verifier=candidature.statut is StatutCandidature.A_VERIFIER,
            )
        )

    # Les motifs en une requête pour toute la page, plutôt qu'une par ligne.
    if items:
        motifs = await db.execute(
            select(Elimination.candidature_id, Elimination.motif).where(
                Elimination.candidature_id.in_([i.id for i in items]),
                Elimination.leve_le.is_(None),
            )
        )
        par_candidature: dict[str, list] = {}
        for candidature_id, motif in motifs:
            par_candidature.setdefault(candidature_id, []).append(motif)
        # Comptage groupé pour tout le poste : une requête, pas une par ligne.
        repetitions = await doublons.compter_par_candidature(db, poste_id)
        for item in items:
            item.motifs = par_candidature.get(item.id, [])
            item.doublons = repetitions.get(item.id, 0)

    return CandidaturesPage(
        items=items, total=total.scalar_one(), page=page, page_size=page_size
    )


@router.get("/candidatures/{candidature_id}", response_model=CandidatureOut)
async def lire_candidature(
    candidature_id: str, db: DbSession, _: CurrentUser
) -> CandidatureOut:
    candidature = await get_candidature_or_404(db, candidature_id)
    sortie = _vers_sortie(candidature)
    sortie.doublons = [
        DoublonOut(
            candidature_id=d.candidature_id, nom_complet=d.nom_complet, libelle=d.libelle
        )
        for d in await doublons.detecter(db, candidature)
    ]
    return sortie


@router.post("/candidatures/{candidature_id}/verifier", response_model=CandidatureOut)
async def verifier_donnees(
    candidature_id: str, payload: VerificationIn, db: DbSession, user: CurrentUser
) -> CandidatureOut:
    """Confirme des données extraites après relecture humaine.

    C'est l'acte qui rend opposables les motifs qui en dépendent : tant qu'il
    n'a pas eu lieu, un dossier extrait automatiquement reste en A_VERIFIER et
    n'est éliminé par personne.
    """
    candidature = await get_candidature_or_404(db, candidature_id)
    candidat = candidature.candidat
    confirme: list[str] = []

    if payload.etat_civil and candidat.provenance is Provenance.EXTRAIT_IA:
        candidat.provenance = Provenance.VERIFIE_RH
        confirme.append("etat_civil")
    if payload.diplomes:
        for diplome in candidat.diplomes:
            if diplome.provenance is Provenance.EXTRAIT_IA:
                diplome.provenance = Provenance.VERIFIE_RH
        confirme.append("diplomes")
    if payload.experiences:
        for experience in candidat.experiences:
            if experience.provenance is Provenance.EXTRAIT_IA:
                experience.provenance = Provenance.VERIFIE_RH
        confirme.append("experiences")

    if not confirme:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Indiquez au moins une famille à confirmer."
        )

    candidat.verifie_le = utcnow()
    candidat.verifie_par_id = user.id
    await db.flush()

    # Le statut dépend de la provenance : reclasser après confirmation.
    await evaluer_candidature(db, candidature)
    await audit.record(
        db,
        action="candidature.verifier",
        entity_type="candidature",
        entity_id=candidature.id,
        user_id=user.id,
        details={"confirme": confirme},
    )
    await db.commit()
    return _vers_sortie(await get_candidature_or_404(db, candidature_id))


@router.post(
    "/candidatures/{candidature_id}/experiences/{experience_id}/domaines",
    response_model=CandidatureOut,
)
async def compter_experience(
    candidature_id: str,
    experience_id: str,
    payload: ExperienceCompteeIn,
    db: DbSession,
    user: CurrentUser,
) -> CandidatureOut:
    """Le recruteur a lu : cette expérience relève bien, ou pas, de ce domaine.

    C'est ce qui rattrape ce que la lecture n'a pas vu — et ce qui corrige ce
    qu'elle a compté à tort. La note et les motifs suivent aussitôt.
    """
    candidature = await get_candidature_or_404(db, candidature_id)
    experience = next(
        (e for e in candidature.candidat.experiences if e.id == experience_id), None
    )
    if experience is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Expérience introuvable.")
    actuels = [d for d in (experience.domaines or []) if d != payload.domaine]
    # Une nouvelle liste : SQLAlchemy ne voit pas une liste JSON modifiée sur place.
    experience.domaines = [*actuels, payload.domaine] if payload.compte else actuels
    await db.flush()
    await evaluer_candidature(db, await charger_candidature(db, candidature.id))
    await audit.record(
        db,
        action="candidature.experience_comptee",
        entity_type="candidature",
        entity_id=candidature.id,
        user_id=user.id,
        details={"domaine": payload.domaine, "compte": payload.compte},
    )
    await db.commit()
    return _vers_sortie(await get_candidature_or_404(db, candidature_id))


@router.post(
    "/candidatures/{candidature_id}/eliminations/{motif}/lever", response_model=EliminationOut
)
async def lever_elimination(
    candidature_id: str, motif: str, payload: LeveeIn, db: DbSession, user: CurrentUser
) -> EliminationOut:
    """Écarte un motif sans l'effacer : la trace et sa levée coexistent."""
    candidature = await get_candidature_or_404(db, candidature_id)
    elimination = next((e for e in candidature.eliminations if e.motif.value == motif), None)
    if elimination is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Motif introuvable sur cette candidature")
    if elimination.leve_le is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ce motif est déjà levé")

    elimination.leve_le = utcnow()
    elimination.leve_par_id = user.id
    elimination.leve_motif = payload.motif
    await db.flush()

    await evaluer_candidature(db, candidature)
    await audit.record(
        db,
        action="candidature.lever_motif",
        entity_type="candidature",
        entity_id=candidature.id,
        user_id=user.id,
        details={"motif": motif, "justification": payload.motif},
    )
    await db.commit()

    rechargee = await get_candidature_or_404(db, candidature_id)
    levee = next(e for e in rechargee.eliminations if e.motif.value == motif)
    sortie = EliminationOut.model_validate(levee)
    sortie.libelle = levee.motif.libelle
    return sortie


@router.patch("/candidatures/{candidature_id}/note", response_model=CandidatureOut)
async def saisir_note_manuelle(
    candidature_id: str, payload: NoteManuelleIn, db: DbSession, user: CurrentUser
) -> CandidatureOut:
    """La note des RH prime sur le calcul, et dit pourquoi."""
    candidature = await get_candidature_or_404(db, candidature_id)
    resultat = await db.execute(
        select(Notation).where(Notation.candidature_id == candidature.id)
    )
    notation = resultat.scalar_one_or_none()
    if notation is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Cette candidature n'a pas encore été évaluée."
        )

    notation.note_manuelle = payload.note
    notation.note_manuelle_motif = payload.motif.strip() or None
    await db.flush()

    # La catégorie remise au client suit la note retenue : sans ce recalcul, un
    # dossier remonté à la main resterait étiqueté d'après le calcul qu'on
    # vient précisément d'écarter.
    rechargee = await charger_candidature(db, candidature.id)
    await evaluer_candidature(db, rechargee)

    await audit.record(
        db,
        action="candidature.note_manuelle",
        entity_type="candidature",
        entity_id=candidature.id,
        user_id=user.id,
        details={"note": payload.note, "motif": payload.motif or None},
    )
    await db.commit()
    return _vers_sortie(await get_candidature_or_404(db, candidature_id))


@router.patch(
    "/candidatures/{candidature_id}/appreciation", response_model=CandidatureOut
)
async def apprecier_consistance(
    candidature_id: str, payload: AppreciationIn, db: DbSession, user: CurrentUser
) -> CandidatureOut:
    """Porte l'appréciation humaine de la consistance du dossier.

    La complétude et la cohérence chronologique se constatent ; la motivation
    et l'expression écrite se lisent. Ces points-là ne sont donc jamais
    attribués par le calcul, et jamais proposés par un modèle : ils demandent
    qu'un recruteur ouvre le dossier. Tant que personne ne l'a fait, la ligne
    de la grille le dit et les points restent à prendre.

    Le dossier est réévalué dans la foulée : la note et le rang doivent refléter
    l'appréciation immédiatement, sans qu'on ait à relancer le poste entier.
    """
    candidature = await get_candidature_or_404(db, candidature_id)
    bareme = construire_bareme(candidature.poste)
    plafond = bareme.consistance.points_appreciation
    if payload.note is not None and payload.note > plafond:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"L'appréciation du dossier vaut au plus {plafond:g} point(s) sur ce poste.",
        )

    candidature.appreciation_consistance = payload.note
    candidature.appreciation_motif = payload.motif.strip() or None
    await db.flush()

    rechargee = await charger_candidature(db, candidature.id)
    await evaluer_candidature(db, rechargee)
    await audit.record(
        db,
        action="candidature.appreciation",
        entity_type="candidature",
        entity_id=candidature.id,
        user_id=user.id,
        details={"note": payload.note, "motif": payload.motif or None},
    )
    await db.commit()
    return _vers_sortie(await get_candidature_or_404(db, candidature_id))


# --- entretiens structurés ---------------------------------------------------


def _fiche_entretien(candidature: Candidature) -> EntretienOut:
    """L'état des entretiens : la grille entière, et ce que chaque juré a mis.

    La grille est toujours renvoyée complète, critères non notés compris — un
    juré doit voir ce qu'il lui reste à faire, pas le deviner.
    """
    fiches = list(candidature.entretiens or ())
    bareme = (
        entretiens.bareme_depuis_liste(fiches[0].bareme_utilise)
        if fiches
        else entretiens.bareme_du_poste(candidature.poste)
    )

    grille = [
        LigneEntretienOut(
            code=l.code, libelle=l.libelle, points_max=l.points_max, section=l.section
        )
        for l in bareme
    ]

    detail: list[FicheJureOut] = []
    for fiche in sorted(fiches, key=lambda f: f.jure):
        grille_fiche = entretiens.bareme_depuis_liste(fiche.bareme_utilise)
        saisies = {l.code: l for l in fiche.lignes}
        detail.append(
            FicheJureOut(
                jure=fiche.jure,
                date_entretien=fiche.date_entretien,
                observations=fiche.observations,
                lignes=[
                    LigneEntretienOut(
                        code=l.code,
                        libelle=l.libelle,
                        points=float(saisies[l.code].points) if l.code in saisies else None,
                        points_max=l.points_max,
                        commentaire=saisies[l.code].commentaire if l.code in saisies else None,
                        section=l.section,
                    )
                    for l in grille_fiche
                ],
                total=sum(float(l.points) for l in fiche.lignes),
                complet=len(saisies) == len(grille_fiche),
            )
        )

    consolidation = entretiens.consolider(fiches, bareme)
    notation = entretiens.notation_depuis_base(candidature.notation)
    finale = (
        entretiens.calculer_note_finale(notation, fiches) if notation is not None else None
    )

    return EntretienOut(
        candidature_id=candidature.id,
        existe=bool(fiches),
        jury=next((f.jury for f in fiches if f.jury), None),
        grille=grille,
        sections=[
            {"libelle": nom, "points_max": total}
            for nom, total in sections_entretien(bareme)
        ],
        fiches=detail,
        total=consolidation.total,
        total_max=consolidation.total_max,
        complet=consolidation.complet,
        ecart_jures=consolidation.ecart,
        preselection_sur_cent=finale.preselection_sur_cent if finale else 0.0,
        entretien_sur_cent=finale.entretien_sur_cent if finale else 0.0,
        note_finale_sur_cent=finale.total_sur_cent if finale else 0.0,
    )


@router.get("/candidatures/{candidature_id}/entretien", response_model=EntretienOut)
async def lire_entretien(
    candidature_id: str, db: DbSession, _: CurrentUser
) -> EntretienOut:
    """Les entretiens d'une candidature : grille, fiches des jurés, moyenne."""
    return _fiche_entretien(await get_candidature_or_404(db, candidature_id))


@router.put("/candidatures/{candidature_id}/entretien", response_model=EntretienOut)
async def saisir_entretien(
    candidature_id: str, payload: EntretienIn, db: DbSession, user: CurrentUser
) -> EntretienOut:
    """Enregistre les points attribués par un juré.

    Rien n'est calculé ici : ces points sont un jugement humain porté en
    séance. L'assistance automatique n'y a aucune part et n'y accède pas.

    Une fiche est un état, pas un journal : les lignes envoyées remplacent
    celles de ce juré, et une note retirée disparaît. Les fiches des autres
    jurés ne bougent pas.
    """
    candidature = await get_candidature_or_404(db, candidature_id)
    saisie = entretiens.SaisieEntretien(
        notes={l.code: l.points for l in payload.lignes if l.points is not None},
        commentaires={l.code: l.commentaire for l in payload.lignes},
        jure=payload.jure,
        date_entretien=payload.date_entretien,
        jury=payload.jury,
        observations=payload.observations,
    )

    try:
        await entretiens.enregistrer(db, candidature, saisie, user.id)
    except entretiens.EntretienRefuse as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await audit.record(
        db,
        action="candidature.entretien",
        entity_type="candidature",
        entity_id=candidature.id,
        user_id=user.id,
        details={
            "jure": saisie.jure,
            "criteres_notes": len(saisie.notes),
            "date": payload.date_entretien.isoformat() if payload.date_entretien else None,
        },
    )
    await db.commit()
    return _fiche_entretien(await get_candidature_or_404(db, candidature_id))


@router.delete("/candidatures/{candidature_id}/entretien", response_model=EntretienOut)
async def effacer_entretien(
    candidature_id: str,
    db: DbSession,
    user: CurrentUser,
    jure: str | None = Query(default=None, max_length=255),
) -> EntretienOut:
    """Efface la fiche d'un juré, ou toutes si aucun n'est précisé."""
    candidature = await get_candidature_or_404(db, candidature_id)
    effacees = await entretiens.supprimer(db, candidature.id, jure)
    if not effacees:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Aucun entretien enregistré pour ce dossier."
        )

    await audit.record(
        db,
        action="candidature.entretien_efface",
        entity_type="candidature",
        entity_id=candidature.id,
        user_id=user.id,
        details={"jure": jure, "fiches": effacees},
    )
    await db.commit()
    return _fiche_entretien(await get_candidature_or_404(db, candidature_id))


@router.patch(
    "/candidatures/{candidature_id}/qualification", response_model=CandidatureOut
)
async def requalifier(
    candidature_id: str, payload: QualificationIn, db: DbSession, user: CurrentUser
) -> CandidatureOut:
    """Réinscrit la catégorie remise au client — avec sa raison.

    Le calcul propose fortement / partiellement / non qualifié à partir de la
    note ; un recruteur qui connaît le dossier peut corriger. Passer null
    rétablit la catégorie calculée.
    """
    candidature = await get_candidature_or_404(db, candidature_id)

    if payload.qualification is not None:
        try:
            Qualification(payload.qualification)
        except ValueError as exc:
            attendues = ", ".join(q.value for q in Qualification)
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Catégorie inconnue. Attendu : {attendues}.",
            ) from exc

    candidature.qualification_manuelle = payload.qualification
    candidature.qualification_motif = payload.motif.strip() or None
    await db.flush()

    await audit.record(
        db,
        action="candidature.qualification",
        entity_type="candidature",
        entity_id=candidature.id,
        user_id=user.id,
        details={"qualification": payload.qualification, "motif": payload.motif or None},
    )
    await db.commit()
    return _vers_sortie(await get_candidature_or_404(db, candidature_id))


@router.get("/courriel/etat")
async def etat_courriel(db: DbSession, _: CurrentUser) -> dict:
    reglages = await parametres.lire(db)
    return {
        "actif": reglages.courriel_utilisable,
        "boite": reglages.boite or None,
        "dossier": reglages.dossier_boite if reglages.courriel_utilisable else None,
        # Pourquoi ce n'est pas actif, dit en toutes lettres plutôt que laissé
        # à deviner. `releve_desactive` se distingue d'une configuration
        # incomplète : dans un cas on a décoché une case, dans l'autre il reste
        # des champs à remplir.
        "releve_desactive": not reglages.courriel_actif,
        "manquants": parametres.ce_qui_manque(reglages),
    }


async def _ouvrir_boite(db: AsyncSession):
    """La boîte Microsoft 365, prête à relever — ou un refus qui dit quoi faire.

    Tout se règle depuis Paramètres › Courriel : le message renvoie donc à
    l'écran, pas au fichier de configuration du serveur.
    """
    reglages = await parametres.lire(db)
    if not reglages.courriel_actif:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Le relevé de la boîte est désactivé. Activez-le dans Paramètres › Courriel.",
        )

    manquants = parametres.ce_qui_manque(reglages)
    if manquants:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Boîte incomplète : il manque {' et '.join(manquants)}. "
            "À renseigner dans Paramètres › Courriel.",
        )

    try:
        return graph_microsoft.BoiteGraph(
            reglages.config_oauth, reglages.boite, reglages.dossier_boite
        )
    except courriel.ErreurBoite as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/courriel/tester")
async def tester_courriel(db: DbSession, _: CurrentUser) -> dict:
    """Ouvre la boîte et compte, sans rien lire ni écrire."""
    boite = await _ouvrir_boite(db)
    try:
        return boite.verifier()
    except courriel.ErreurBoite as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    finally:
        boite.fermer()


@router.post("/courriel/apercu")
async def apercu_courriel(db: DbSession, _: CurrentUser) -> dict:
    """Ce qu'un relevé ferait, sans rien créer.

    À utiliser au premier branchement d'une boîte réelle : on voit comment les
    messages arrivent avant de laisser quoi que ce soit s'écrire en base.
    """
    boite = await _ouvrir_boite(db)
    try:
        lignes = await courriel.apercu(db, boite)
    except courriel.ErreurBoite as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    finally:
        boite.fermer()
    return {"messages": len(lignes), "details": lignes}


@router.post("/courriel/relever")
async def relever_courriel(
    db: DbSession, user: CurrentUser, limite: int = Query(25, ge=1, le=100)
) -> dict:
    """Relève un lot de messages et crée les candidatures rattachables.

    Déclenché à la demande plutôt que par une tâche de fond : le relevé est une
    action que les RH veulent voir aboutir, avec son compte-rendu.

    Par lots : une boîte de plusieurs centaines de non-lus ne tient pas dans
    une requête — chaque message se télécharge en entier. `reste` dit qu'un
    autre lot attend ; l'écran enchaîne et montre l'avancement. Chaque lot
    est enregistré : une coupure en route ne perd rien de ce qui est fait.
    """
    reglages = await parametres.lire(db)
    boite = await _ouvrir_boite(db)
    try:
        resultat = await courriel.relever(
            db,
            boite,
            limite=limite,
            accepter_spontanees=reglages.candidatures_spontanees,
            utilisateur=user.id,
        )
    except courriel.ErreurBoite as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Relevé impossible : {exc}"
        ) from exc
    finally:
        boite.fermer()

    await audit.record(
        db,
        action="courriel.relever",
        entity_type="courriel",
        entity_id=None,
        user_id=user.id,
        details={
            "crees": resultat.crees,
            "ignores": resultat.ignores,
            "spontanees": resultat.spontanees,
            "echanges_client": resultat.echanges_client,
        },
    )
    await db.commit()
    return {
        "crees": resultat.crees,
        "ignores": resultat.ignores,
        "spontanees": resultat.spontanees,
        "echanges_client": resultat.echanges_client,
        "non_rattaches": resultat.non_rattaches,
        "sans_piece": resultat.sans_piece,
        "expediteurs_ignores": resultat.expediteurs_ignores,
        "liens_recuperes": resultat.liens_recuperes,
        "liens_inaccessibles": resultat.liens_inaccessibles,
        "fusionnes": resultat.fusionnes,
        "reste": resultat.reste,
    }


@router.post(
    "/candidatures/{candidature_id}/pieces",
    response_model=CandidatureOut,
    status_code=status.HTTP_201_CREATED,
)
async def joindre_piece(
    candidature_id: str,
    db: DbSession,
    user: CurrentUser,
    type_piece: str = Form(...),
    fichier: UploadFile = File(...),
    intitule_libre: str | None = Form(default=None),
) -> CandidatureOut:
    """Classe un fichier sur une pièce du dossier.

    Si la pièce était seulement constatée reçue, le fichier vient s'y attacher
    plutôt que d'en créer une seconde : la complétude ne doit pas dépendre du
    moment où le document a été rangé.

    `intitule_libre` nomme une pièce hors nomenclature — c'est ce qui permet de
    ranger une lettre de recommandation sans la faire passer pour un diplôme.
    """
    candidature = await get_candidature_or_404(db, candidature_id)
    try:
        accepte = await uploads.validate(fichier)
    except uploads.RejectedUpload as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    chemin = await uploads.store(accepte)
    existante = next(
        (p for p in candidature.pieces if p.type_piece == type_piece and p.chemin_stockage is None),
        None,
    )
    piece = existante or PieceCandidature(
        candidature_id=candidature.id, type_piece=type_piece
    )
    piece.nom_fichier = accepte.filename
    piece.chemin_stockage = chemin
    piece.type_mime = accepte.mime_type
    piece.taille_octets = len(accepte.data)
    piece.empreinte = accepte.sha256
    if intitule_libre and intitule_libre.strip():
        piece.intitule_libre = intitule_libre.strip()[:255]
    if existante is None:
        db.add(piece)
    await db.flush()

    # La liste des pièces vient de changer : la complétude est réévaluée.
    rechargee = await get_candidature_or_404(db, candidature_id)
    await evaluer_candidature(db, rechargee)
    await audit.record(
        db,
        action="candidature.piece",
        entity_type="candidature",
        entity_id=candidature.id,
        user_id=user.id,
        details={"type": type_piece, "fichier": accepte.filename},
    )
    await db.commit()
    return _vers_sortie(await get_candidature_or_404(db, candidature_id))


@router.post(
    "/candidatures/{candidature_id}/pieces/lot",
    response_model=CandidatureOut,
    status_code=status.HTTP_201_CREATED,
)
async def joindre_pieces(
    candidature_id: str,
    db: DbSession,
    user: CurrentUser,
    fichiers: list[UploadFile] = File(...),
    types_pieces: list[str] | None = Form(default=None),
) -> CandidatureOut:
    """Rattache plusieurs fichiers d'un coup au dossier d'un candidat.

    Le cas est celui du dépôt en lot : un dossier a été ouvert sur un seul
    fichier, et le reste des pièces de la même personne arrive après — parce
    qu'elles étaient dans un second message, ou parce que le regroupement
    automatique les avait laissées de côté. Les rattacher une par une était le
    seul chemin, et il décourageait de le faire.

    Le type de chaque pièce est déduit de son nom quand il n'est pas fourni.
    Une archive est dépliée : « Dossier_KODJO.zip » verse ses pièces au dossier
    plutôt que d'y ajouter un fichier que personne ne peut lire.
    """
    candidature = await get_candidature_or_404(db, candidature_id)
    types = types_pieces or []

    recus, refuses = await _lire_lot(fichiers, [], [], types)
    if refuses:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, refuses[0]["erreur"])

    ajoutees: list[str] = []
    for recu in recus:
        try:
            accepte = uploads.valider_octets(recu.donnees, recu.nom)
        except uploads.RejectedUpload as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

        # Le même fichier deux fois sur le même dossier n'apporte rien.
        if any(p.empreinte == accepte.sha256 for p in candidature.pieces):
            continue

        # Le type donné prime ; sinon le nom, puis le contenu — et un PDF qui
        # réunit plusieurs pièces est découpé.
        preparees = await decoupage.preparer(
            accepte.filename, accepte.data, accepte.mime_type, recu.type_piece or None
        )
        for preparee in preparees:
            type_piece = preparee.type_piece or PieceDossier.AUTRE.value
            # Si la pièce était constatée reçue sans fichier, le fichier vient
            # s'y attacher plutôt que d'en créer une seconde.
            existante = next(
                (
                    p
                    for p in candidature.pieces
                    if p.type_piece == type_piece and p.chemin_stockage is None
                ),
                None,
            )
            piece = existante or PieceCandidature(
                candidature_id=candidature.id, type_piece=type_piece
            )
            piece.nom_fichier = preparee.nom[:255]
            piece.chemin_stockage = await storage.get_storage().save(
                storage.build_key(preparee.type_mime), preparee.donnees
            )
            piece.type_mime = preparee.type_mime
            piece.taille_octets = len(preparee.donnees)
            piece.empreinte = hashlib.sha256(preparee.donnees).hexdigest()
            piece.texte_extrait = preparee.texte or None
            if type_piece == PieceDossier.AUTRE.value:
                piece.intitule_libre = (preparee.intitule or preparee.nom)[:255]
            if existante is None:
                db.add(piece)
            ajoutees.append(preparee.nom)
    await db.flush()

    # La liste des pièces a changé : la complétude est réévaluée.
    rechargee = await get_candidature_or_404(db, candidature_id)
    await evaluer_candidature(db, rechargee)
    await audit.record(
        db,
        action="candidature.pieces_lot",
        entity_type="candidature",
        entity_id=candidature.id,
        user_id=user.id,
        details={"fichiers": ajoutees},
    )
    await db.commit()
    return _vers_sortie(await get_candidature_or_404(db, candidature_id))


@router.get("/candidatures/{candidature_id}/pieces/{piece_id}")
async def telecharger_piece(
    candidature_id: str, piece_id: str, db: DbSession, _: CurrentUser
) -> StreamingResponse:
    candidature = await get_candidature_or_404(db, candidature_id)
    piece = next((p for p in candidature.pieces if p.id == piece_id), None)
    if piece is None or piece.chemin_stockage is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucun fichier pour cette pièce")

    depot = storage.get_storage()
    if not await depot.exists(piece.chemin_stockage):
        raise HTTPException(status.HTTP_410_GONE, "Le fichier n'est plus disponible")

    return StreamingResponse(
        depot.stream(piece.chemin_stockage),
        media_type=piece.type_mime or "application/octet-stream",
        headers={
            "Content-Disposition": f'inline; filename="{piece.nom_fichier or piece.type_piece}"'
        },
    )


class TypePieceIn(BaseModel):
    type_piece: str = Field(min_length=1, max_length=64)
    intitule_libre: str | None = Field(default=None, max_length=255)


@router.patch(
    "/candidatures/{candidature_id}/pieces/{piece_id}", response_model=CandidatureOut
)
async def retyper_piece(
    candidature_id: str, piece_id: str, payload: TypePieceIn, db: DbSession, user: CurrentUser
) -> CandidatureOut:
    """Corrige le type d'une pièce mal classée.

    Le classement d'une pièce reçue par courriel se devine — d'après son nom,
    puis son contenu — et se trompe parfois : un passeport rangé en CV fausse la
    complétude du dossier. On corrige ici, et le dossier est réévalué.
    """
    if payload.type_piece not in {p.value for p in PieceDossier}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Type de pièce inconnu.")
    candidature = await get_candidature_or_404(db, candidature_id)
    piece = next((p for p in candidature.pieces if p.id == piece_id), None)
    if piece is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pièce introuvable")
    avant = piece.type_piece
    piece.type_piece = payload.type_piece
    piece.intitule_libre = (
        (payload.intitule_libre or "").strip() or None
        if payload.type_piece == PieceDossier.AUTRE.value
        else None
    )
    await db.flush()
    rechargee = await get_candidature_or_404(db, candidature_id)
    await evaluer_candidature(db, rechargee)
    await audit.record(
        db,
        action="candidature.piece_retypee",
        entity_type="candidature",
        entity_id=candidature.id,
        user_id=user.id,
        details={"piece": piece.nom_fichier, "de": avant, "vers": payload.type_piece},
    )
    await db.commit()
    return _vers_sortie(await get_candidature_or_404(db, candidature_id))


@router.delete("/candidatures/{candidature_id}/pieces/{piece_id}", response_model=CandidatureOut)
async def retirer_piece(
    candidature_id: str, piece_id: str, db: DbSession, user: CurrentUser
) -> CandidatureOut:
    candidature = await get_candidature_or_404(db, candidature_id)
    piece = next((p for p in candidature.pieces if p.id == piece_id), None)
    if piece is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pièce introuvable")

    if piece.chemin_stockage:
        await storage.get_storage().delete(piece.chemin_stockage)
    await db.delete(piece)
    await db.flush()

    rechargee = await get_candidature_or_404(db, candidature_id)
    await evaluer_candidature(db, rechargee)
    await audit.record(
        db,
        action="candidature.piece_retiree",
        entity_type="candidature",
        entity_id=candidature.id,
        user_id=user.id,
        details={"type": piece.type_piece},
    )
    await db.commit()
    return _vers_sortie(await get_candidature_or_404(db, candidature_id))


@router.post("/candidatures/{candidature_id}/pieces/{piece_id}/decouper", response_model=CandidatureOut)
async def decouper_piece(
    candidature_id: str, piece_id: str, db: DbSession, user: CurrentUser
) -> CandidatureOut:
    """Découpe un PDF qui réunit plusieurs pièces — CV, diplômes, attestations…

    Pour les dossiers reçus avant que le découpage ne se fasse à l'arrivée : le
    PDF fusionné y est rangé comme une seule pièce, souvent « CV ». Chaque
    page est classée, les pages consécutives du même type forment une pièce ;
    l'original est remplacé par ses morceaux, qui gardent ses pages dans leur
    nom. Rien n'est fait quand une seule pièce s'y reconnaît.
    """
    candidature = await get_candidature_or_404(db, candidature_id)
    piece = next((p for p in candidature.pieces if p.id == piece_id), None)
    if piece is None or not piece.chemin_stockage:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pièce introuvable")
    if piece.type_mime != extraction.PDF_MIME:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Seul un PDF se découpe.")

    depot = storage.get_storage()
    donnees = await depot.read(piece.chemin_stockage)
    morceaux = await decoupage.preparer(piece.nom_fichier or "dossier.pdf", donnees, extraction.PDF_MIME)
    if len(morceaux) < 2:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Une seule pièce se reconnaît dans ce PDF : rien à découper. Son type se corrige "
            "dans la liste.",
        )
    decoupage.completer_types(morceaux)
    for morceau in morceaux:
        db.add(
            PieceCandidature(
                candidature_id=candidature.id,
                type_piece=morceau.type_piece or PieceDossier.AUTRE.value,
                intitule_libre=morceau.intitule,
                nom_fichier=morceau.nom[:255],
                chemin_stockage=await depot.save(storage.build_key(morceau.type_mime), morceau.donnees),
                type_mime=morceau.type_mime,
                taille_octets=len(morceau.donnees),
                empreinte=hashlib.sha256(morceau.donnees).hexdigest(),
                texte_extrait=morceau.texte or None,
            )
        )
    await depot.delete(piece.chemin_stockage)
    await db.delete(piece)
    await db.flush()

    rechargee = await get_candidature_or_404(db, candidature_id)
    await evaluer_candidature(db, rechargee)
    await audit.record(
        db,
        action="candidature.piece_decoupee",
        entity_type="candidature",
        entity_id=candidature.id,
        user_id=user.id,
        details={"fichier": piece.nom_fichier, "pieces": [m.type_piece for m in morceaux]},
    )
    await db.commit()
    return _vers_sortie(await get_candidature_or_404(db, candidature_id))


@router.delete("/candidatures/{candidature_id}")
async def supprimer_candidature(
    candidature_id: str,
    db: DbSession,
    user: CurrentUser,
    motif: str = Query(min_length=3, max_length=500),
    confirmer: bool = Query(False),
) -> dict:
    """Retire un dossier entré par erreur.

    Le cas visé est étroit et fréquent : le mauvais fichier déposé, le même
    candidat saisi deux fois, un dossier rattaché au mauvais poste. Le laisser
    en place fausse la grille — il compte dans les effectifs, occupe un rang,
    et se retrouve dans les exports remis au client.

    Le dossier part avec ses fichiers, sa notation et ses motifs. Le journal
    garde le nom, le poste, la note, la liste des pièces et le motif écrit :
    une suppression reste ainsi une suppression expliquée, et non une
    disparition. Les courriels déjà partis, eux, sont détachés et non effacés —
    ils valent preuve d'envoi, et cette preuve ne dépend pas du dossier.

    Ce qui ne ressemble pas à une erreur est retenu : un entretien saisi, un
    courriel expédié, un dossier déjà présélectionné. `confirmer` passe outre,
    mais il faut le dire.
    """
    candidature = await get_candidature_or_404(db, candidature_id)
    compte_rendu, fichiers = await preparer_suppression(
        db, candidature, user_id=user.id, motif=motif, confirmer=confirmer
    )
    await db.commit()

    # Après le commit seulement : une transaction annulée ne doit pas laisser
    # un dossier intact dont les fichiers ont déjà disparu.
    depot = storage.get_storage()
    for chemin in fichiers:
        await depot.delete(chemin)
    return compte_rendu


class SuppressionRetenue(Exception):
    """Le dossier ne ressemble pas à une erreur : il faut confirmer."""


async def preparer_suppression(
    db: AsyncSession,
    candidature: Candidature,
    *,
    user_id: str,
    motif: str,
    confirmer: bool,
    lever: bool = True,
) -> tuple[dict, list[str]]:
    """Supprime un dossier dans la transaction en cours, sans la valider.

    Rend le compte rendu et les fichiers à effacer *après* le commit. Partagée
    par la suppression unitaire et la suppression groupée, pour que la
    seconde ne contourne aucune des retenues de la première.

    Un dossier venu d'un courriel laisse une trace « supprimé » : le relevé
    suivant ne le recréera pas.
    """
    candidat = candidature.candidat

    courriels = await db.scalar(
        select(func.count())
        .select_from(MessageEnvoye)
        .where(MessageEnvoye.candidature_id == candidature.id)
    )

    retenues: list[str] = []
    if candidature.entretiens:
        retenues.append(f"{len(candidature.entretiens)} fiche(s) d'entretien y sont saisies")
    if courriels:
        retenues.append(f"{courriels} courriel(s) ont été envoyés à ce candidat")
    if candidature.statut in (
        StatutCandidature.PRESELECTIONNEE,
        StatutCandidature.RETENUE,
    ):
        retenues.append("il figure dans la présélection")

    if retenues and not confirmer:
        message = (
            "Ce dossier ne ressemble pas à une erreur de saisie : "
            + " ; ".join(retenues)
            + ". Confirmez la suppression si c'est bien ce que vous voulez."
        )
        if lever:
            raise HTTPException(status.HTTP_409_CONFLICT, message)
        raise SuppressionRetenue(message)

    # Relevés avant la suppression : après, l'objet n'a plus ni pièces ni note.
    fichiers = [p.chemin_stockage for p in candidature.pieces if p.chemin_stockage]
    pieces = [p.nom_fichier or p.type_piece for p in candidature.pieces]
    note = float(candidature.notation.note_retenue) if candidature.notation else None

    await db.execute(
        update(MessageEnvoye)
        .where(MessageEnvoye.candidature_id == candidature.id)
        .values(candidature_id=None)
    )

    autres = await db.scalar(
        select(func.count())
        .select_from(Candidature)
        .where(Candidature.candidat_id == candidat.id, Candidature.id != candidature.id)
    )
    # Un profil créé pour ce seul dossier n'a plus d'objet. Le laisser derrière
    # remplirait le vivier de fiches sans pièces, que personne ne saurait
    # rattacher à quoi que ce soit.
    profil_supprime = not autres

    await audit.record(
        db,
        action="candidature.supprimer",
        entity_type="candidature",
        entity_id=candidature.id,
        user_id=user_id,
        details={
            "motif": motif,
            "candidat": f"{candidat.nom} {candidat.prenom}",
            "email": candidat.email,
            "poste_id": candidature.poste_id,
            "statut": candidature.statut.value,
            "note": note,
            "pieces": pieces,
            "courriels_detaches": courriels,
            "profil_supprime": profil_supprime,
            "passe_outre": retenues or None,
        },
    )

    if candidature.message_id:
        await courriel.tracer(
            db,
            courriel.MessageEntrant(
                message_id=candidature.message_id,
                expediteur=candidat.email or "",
                nom_expediteur="",
                sujet=(candidature.notes_rh or "")[:512],
                recu_le=candidature.recue_le,
            ),
            MessageTraite_SUPPRIME,
            motif=motif[:500],
            utilisateur=user_id,
        )

    # Un dossier peut réunir plusieurs courriels (pièces oubliées, renvoi) :
    # tous sont marqués supprimés, sans quoi le relevé suivant recréerait le
    # dossier à partir de l'un d'eux.
    await db.execute(
        update(MessageTraite)
        .where(MessageTraite.candidature_id == candidature.id)
        .values(statut=MessageTraite_SUPPRIME, motif=motif[:500], candidature_id=None)
    )

    await db.delete(candidature)
    if profil_supprime:
        await db.delete(candidat)
    await db.flush()

    return (
        {
            "supprime": True,
            "pieces_supprimees": len(fichiers),
            "profil_supprime": profil_supprime,
            "courriels_conserves": courriels,
        },
        fichiers,
    )


@router.post("/candidatures/{candidature_id}/depouiller")
async def depouiller_dossier(
    candidature_id: str, db: DbSession, user: CurrentUser
) -> dict:
    """Lit les pièces et propose un parcours à confirmer.

    Le dossier reste en A_VERIFIER : tout ce qui est écrit ici porte la
    provenance EXTRAIT_IA et n'élimine personne avant relecture.

    Relançable : un second appel remplace les propositions du premier, ce qui
    est le seul moyen de faire profiter un dossier déjà dépouillé d'une
    extraction corrigée. Rien de déclaré, saisi ou confirmé n'est touché.
    """
    candidature = await get_candidature_or_404(db, candidature_id)
    resultat = await depouillement.depouiller(db, candidature)

    await audit.record(
        db,
        action="candidature.depouiller",
        entity_type="candidature",
        entity_id=candidature.id,
        user_id=user.id,
        details={
            "diplomes": resultat.diplomes,
            "experiences": resultat.experiences,
            "remplacees": resultat.remplacees,
            # Les valeurs détectées ne sont pas journalisées, seulement leur
            # nature : le journal n'a pas à conserver de données sensibles.
            "demographiques": sorted(resultat.demographiques),
        },
    )
    await db.commit()

    return {
        "diplomes": resultat.diplomes,
        "experiences": resultat.experiences,
        "langues": resultat.langues,
        "certifications": resultat.certifications,
        "pieces_lues": resultat.pieces_lues,
        "remplacees": resultat.remplacees,
        "email_trouve": resultat.email_trouve,
        "nom_corrige": resultat.nom_corrige,
        "lecture": resultat.lecture,
        "avertissements": resultat.avertissements,
    }


class FusionDoublonsIn(BaseModel):
    poste_id: str | None = None
    sans_poste: bool = False


@router.post("/doublons/fusionner")
async def fusionner_les_doublons(payload: FusionDoublonsIn, db: DbSession, user: CurrentUser) -> dict:
    """Ne laisse aucun doublon déjà présent sur un poste (ou sans poste).

    Les dossiers arrivés avant que les doublons ne soient refusés à l'entrée.
    Le dossier gardé reçoit les pièces nouvelles de l'autre ; deux dossiers
    travaillés l'un et l'autre restent à trancher par une personne.
    """
    if payload.poste_id:
        await get_poste_or_404(db, payload.poste_id)
    elif not payload.sans_poste:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Précisez un poste, ou les candidatures sans poste.")
    fusion = await doublons.fusionner_poste(db, payload.poste_id)
    await audit.record(
        db,
        action="doublons.fusionner",
        entity_type="poste",
        entity_id=payload.poste_id,
        user_id=user.id,
        details={"fusionnes": fusion.fusionnes, "a_trancher": fusion.a_trancher},
    )
    await db.commit()
    return {"fusionnes": fusion.fusionnes, "a_trancher": fusion.a_trancher}


class RelectureNomsIn(BaseModel):
    # Un poste, ou les dossiers sans poste ; ni l'un ni l'autre : tous.
    poste_id: str | None = None
    sans_poste: bool = False


@router.post("/candidatures/noms/relire")
async def relire_les_noms(payload: RelectureNomsIn, db: DbSession, user: CurrentUser) -> dict:
    """Relit le nom de chaque candidat non confirmé dans son CV.

    Pour les dossiers arrivés avant que le nom ne soit lu dans le CV : l'en-tête
    du courriel inversait nom et prénom, et prenait parfois « Yahoo! » pour un
    nom. Rien de ce qu'un humain a confirmé n'est touché, et rien ne part au
    modèle. Quand le CV porte un tout autre nom, il n'est pas appliqué : il est
    signalé, c'est peut-être le CV de quelqu'un d'autre.
    """
    requete = (
        select(Candidature.id)
        .join(Candidat, Candidat.id == Candidature.candidat_id)
        .where(Candidat.provenance == Provenance.EXTRAIT_IA)
    )
    if payload.poste_id:
        requete = requete.where(Candidature.poste_id == payload.poste_id)
    elif payload.sans_poste:
        requete = requete.where(Candidature.poste_id.is_(None))
    identifiants = list((await db.execute(requete)).scalars())

    depot = storage.get_storage()
    corriges: list[dict] = []
    a_verifier: list[dict] = []
    for identifiant in identifiants:
        candidature = await charger_candidature(db, identifiant)
        candidat = candidature.candidat
        cvs = [p for p in candidature.pieces if p.type_piece == PieceDossier.CV.value and p.chemin_stockage]
        for piece in cvs:
            if piece.texte_extrait is None:
                try:
                    donnees = await depot.read(piece.chemin_stockage)
                    piece.texte_extrait = (
                        await extraction.extract(donnees, piece.type_mime or "", piece.nom_fichier or "", min_chars=0)
                    ).text or None
                except (extraction.UnreadableDocument, OSError, ValueError):
                    continue
        texte = "\n\n".join(p.texte_extrait for p in cvs if p.texte_extrait)
        if not texte:
            continue
        avant = f"{candidat.prenom} {candidat.nom}".strip()
        proposition = identite.proposer(candidat.nom, candidat.prenom, texte, candidat.email or "")
        if proposition is None:
            continue
        if proposition.avertissement:
            a_verifier.append({"candidature_id": identifiant, "nom": avant, "motif": proposition.avertissement})
            continue
        candidat.nom, candidat.prenom = proposition.nom[:255], proposition.prenom[:255]
        corriges.append(
            {"candidature_id": identifiant, "avant": avant, "apres": f"{candidat.prenom} {candidat.nom}".strip()}
        )

    await audit.record(
        db,
        action="candidatures.noms_relus",
        entity_type="poste",
        entity_id=payload.poste_id,
        user_id=user.id,
        details={"examines": len(identifiants), "corriges": len(corriges), "a_verifier": len(a_verifier)},
    )
    await db.commit()
    return {"examines": len(identifiants), "corriges": corriges, "a_verifier": a_verifier}


@router.post("/candidatures/{candidature_id}/evaluer", response_model=CandidatureOut)
async def reevaluer(candidature_id: str, db: DbSession, user: CurrentUser) -> CandidatureOut:
    candidature = await get_candidature_or_404(db, candidature_id)
    await evaluer_candidature(db, candidature)
    await audit.record(
        db,
        action="candidature.evaluer",
        entity_type="candidature",
        entity_id=candidature.id,
        user_id=user.id,
        details=None,
    )
    await db.commit()
    return _vers_sortie(await get_candidature_or_404(db, candidature_id))
