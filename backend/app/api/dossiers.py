"""Les dossiers des candidats, hors de la grille.

Deux gestes que l'écran du poste ne permettait pas :

- **Emporter plusieurs dossiers d'un coup.** Pour imprimer, ou pour les
  remettre sur une clé USB, les RH ouvraient chaque candidat et téléchargeaient
  ses pièces une à une. L'archive rend les fichiers *tels que reçus* — pas la
  version remise en forme des « CV à en-tête » —, un dossier par candidat.
- **Rattacher à un poste un dossier qui n'en a pas.** Un courriel dont l'objet
  ne nomme aucun avis devient une candidature spontanée : elle rejoignait le
  vivier, sans que personne puisse en ouvrir les pièces ni la ranger sous le
  poste visé. Le même geste répare un dossier rangé sous le mauvais poste.
"""

from __future__ import annotations

import csv
import io
import os
import re
import tempfile
import unicodedata
import zipfile
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.background import BackgroundTask

from app.api.candidatures import _vers_sortie, get_candidature_or_404
from app.api.postes import _PORTEES, get_poste_or_404
from app.deps import CurrentUser, DbSession
from app.models import Candidat, Candidature, Mandat, Poste, StatutCandidature
from app.models.base import utcnow
from app.schemas.recrutement import CandidatureOut
from app.services import audit, storage
from app.services.preselection import evaluer_candidature

router = APIRouter(tags=["dossiers"])

# Au-delà, l'archive deviendrait un téléchargement de plusieurs gigaoctets
# qu'aucun navigateur ne mène à bien sur une connexion ordinaire.
MAX_DOSSIERS = 500

LIBELLES_STATUT = {
    StatutCandidature.RECUE: "Reçue",
    StatutCandidature.A_VERIFIER: "À vérifier",
    StatutCandidature.ELIGIBLE: "Éligible",
    StatutCandidature.ELIMINEE: "Éliminée",
    StatutCandidature.PRESELECTIONNEE: "Préqualifiée",
    StatutCandidature.NON_RETENUE: "Non retenue",
    StatutCandidature.RETENUE: "Retenue",
}


def _nom_sur(texte: str, longueur: int = 80) -> str:
    """Un nom de fichier qui passe partout : Windows, clé USB, imprimante.

    Les accents sont gardés — l'explorateur de Windows les affiche bien depuis
    longtemps —, mais pas les caractères qu'un système de fichiers refuse.
    """
    texte = unicodedata.normalize("NFC", texte or "")
    texte = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", texte)
    texte = " ".join(texte.split()).strip(" .")
    return texte[:longueur].rstrip(" .") or "sans nom"


def _note(candidature: Candidature) -> str:
    notation = candidature.notation
    if notation is None:
        return ""
    return f"{float(notation.note_retenue):g}"


# --- l'export des dossiers d'un poste ---------------------------------------


class LigneDossier(BaseModel):
    candidature_id: str
    nom: str
    prenom: str
    statut: str
    note: str
    pieces: int
    pieces_disponibles: int


@router.get("/postes/{poste_id}/dossiers", response_model=list[LigneDossier])
async def dossiers_du_poste(
    poste_id: str, db: DbSession, _: CurrentUser, portee: str = "tous"
) -> list[LigneDossier]:
    """Les dossiers d'une portée, pour choisir ceux qu'on emporte."""
    await get_poste_or_404(db, poste_id)
    if portee not in _PORTEES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Portée inconnue : {portee}. Attendu : {', '.join(sorted(_PORTEES))}.",
        )
    requete = (
        select(Candidature)
        .join(Candidat, Candidature.candidat_id == Candidat.id)
        .where(Candidature.poste_id == poste_id)
        .options(selectinload(Candidature.candidat), selectinload(Candidature.notation))
        .order_by(Candidat.nom, Candidat.prenom)
    )
    statuts = _PORTEES[portee]
    if statuts is not None:
        requete = requete.where(Candidature.statut.in_(statuts))
    candidatures = (await db.execute(requete)).scalars().all()
    return [
        LigneDossier(
            candidature_id=c.id,
            nom=c.candidat.nom,
            prenom=c.candidat.prenom or "",
            statut=LIBELLES_STATUT.get(c.statut, str(c.statut)),
            note=_note(c),
            pieces=len(c.pieces),
            pieces_disponibles=sum(
                1 for p in c.pieces if p.chemin_stockage and p.purge_le is None
            ),
        )
        for c in candidatures
    ]


class SelectionDossiers(BaseModel):
    candidature_ids: list[str] = Field(min_length=1, max_length=MAX_DOSSIERS)


@router.post("/postes/{poste_id}/dossiers.zip")
async def archive_des_dossiers(
    poste_id: str, payload: SelectionDossiers, db: DbSession, user: CurrentUser
) -> FileResponse:
    """Les pièces reçues, telles quelles, un dossier par candidat.

    L'archive s'écrit dans un fichier temporaire plutôt qu'en mémoire : deux
    cents dossiers de trois pièces pèsent vite plusieurs centaines de
    mégaoctets. Les PDF y sont rangés sans recompression — ils sont déjà
    compressés, et l'archive se construit deux fois plus vite.

    Un sommaire (tableur) ouvre l'archive : nom, statut, note et pièces de
    chaque dossier, dans l'ordre des dossiers. Une pièce dont le fichier a été
    purgé y est signalée plutôt que d'être passée sous silence.
    """
    poste = await get_poste_or_404(db, poste_id)
    demandes = list(dict.fromkeys(payload.candidature_ids))
    candidatures = (
        (
            await db.execute(
                select(Candidature)
                .join(Candidat, Candidature.candidat_id == Candidat.id)
                .where(Candidature.id.in_(demandes), Candidature.poste_id == poste_id)
                .options(selectinload(Candidature.candidat), selectinload(Candidature.notation))
                .order_by(Candidat.nom, Candidat.prenom)
            )
        )
        .scalars()
        .all()
    )
    if len(candidatures) != len(demandes):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Certains dossiers demandés n'appartiennent pas à ce poste.",
        )

    depot = storage.get_storage()
    descripteur, chemin = tempfile.mkstemp(prefix="tricv-dossiers-", suffix=".zip")
    os.close(descripteur)
    sommaire = io.StringIO()
    tableur = csv.writer(sommaire, delimiter=";")
    tableur.writerow(
        ["N°", "Dossier", "Nom", "Prénom", "Email", "Téléphone", "Statut", "Note",
         "Reçue le", "Pièces dans l'archive", "Pièces sans fichier"]
    )
    fichiers = 0
    try:
        with zipfile.ZipFile(chemin, "w", zipfile.ZIP_DEFLATED) as archive:
            for rang, candidature in enumerate(candidatures, start=1):
                candidat = candidature.candidat
                dossier = _nom_sur(
                    f"{rang:03d} - {candidat.nom.upper()} {candidat.prenom or ''}"
                )
                pris: set[str] = set()
                inclus: list[str] = []
                absents: list[str] = []
                for piece in candidature.pieces:
                    nom = _nom_sur(piece.nom_fichier or piece.type_piece, 120)
                    if not piece.chemin_stockage or piece.purge_le is not None:
                        absents.append(nom)
                        continue
                    try:
                        donnees = await depot.read(piece.chemin_stockage)
                    except (FileNotFoundError, OSError):
                        absents.append(nom)
                        continue
                    # Deux pièces du même nom — « CV.pdf » deux fois — ne
                    # doivent pas s'écraser dans l'archive.
                    base, extension = os.path.splitext(nom)
                    unique, n = nom, 2
                    while unique.lower() in pris:
                        unique, n = f"{base} ({n}){extension}", n + 1
                    pris.add(unique.lower())
                    compression = (
                        zipfile.ZIP_STORED
                        if (piece.type_mime or "") == "application/pdf"
                        else zipfile.ZIP_DEFLATED
                    )
                    archive.writestr(f"{dossier}/{unique}", donnees, compress_type=compression)
                    inclus.append(unique)
                    fichiers += 1
                tableur.writerow(
                    [
                        rang,
                        dossier,
                        candidat.nom,
                        candidat.prenom or "",
                        candidat.email or "",
                        candidat.telephone or "",
                        LIBELLES_STATUT.get(candidature.statut, str(candidature.statut)),
                        _note(candidature),
                        f"{candidature.recue_le:%d/%m/%Y}",
                        ", ".join(inclus),
                        ", ".join(absents),
                    ]
                )
            # Le BOM fait ouvrir le fichier en UTF-8 par Excel : sans lui, les
            # accents des noms arrivent en mojibake.
            archive.writestr("000 - Sommaire.csv", "﻿" + sommaire.getvalue())
    except BaseException:
        os.unlink(chemin)
        raise

    await audit.record(
        db,
        action="poste.export_dossiers",
        entity_type="poste",
        entity_id=poste.id,
        user_id=user.id,
        details={"dossiers": len(candidatures), "fichiers": fichiers},
    )
    await db.commit()

    nom_archive = _nom_sur(f"Dossiers - {poste.intitule} - {utcnow():%Y-%m-%d}", 120) + ".zip"
    return FileResponse(
        chemin,
        media_type="application/zip",
        filename=nom_archive,
        background=BackgroundTask(os.unlink, chemin),
    )


# --- les dossiers sans poste ------------------------------------------------


class PieceSansPoste(BaseModel):
    id: str
    nom_fichier: str
    disponible: bool


class CandidatureSansPoste(BaseModel):
    id: str
    nom: str
    prenom: str
    email: str | None
    recue_le: datetime
    source: str
    objet: str | None
    pieces: list[PieceSansPoste]


@router.get("/dossiers/sans-poste", response_model=list[CandidatureSansPoste])
async def sans_poste(db: DbSession, _: CurrentUser) -> list[CandidatureSansPoste]:
    """Les candidatures reçues hors de tout poste, les plus récentes d'abord.

    Ce sont surtout des courriels dont l'objet ne citait aucun avis : le
    candidat visait sans doute un poste, mais rien ne permettait de dire
    lequel. Une personne le peut, pièces en main.
    """
    candidatures = (
        (
            await db.execute(
                select(Candidature)
                .where(Candidature.poste_id.is_(None))
                .options(selectinload(Candidature.candidat))
                .order_by(Candidature.recue_le.desc())
                .limit(MAX_DOSSIERS)
            )
        )
        .scalars()
        .all()
    )
    return [
        CandidatureSansPoste(
            id=c.id,
            nom=c.candidat.nom,
            prenom=c.candidat.prenom or "",
            email=c.candidat.email,
            recue_le=c.recue_le,
            source=str(c.source.value if hasattr(c.source, "value") else c.source),
            objet=c.notes_rh,
            pieces=[
                PieceSansPoste(
                    id=p.id,
                    nom_fichier=p.nom_fichier or p.type_piece,
                    disponible=bool(p.chemin_stockage) and p.purge_le is None,
                )
                for p in c.pieces
            ],
        )
        for c in candidatures
    ]


class PosteOuvert(BaseModel):
    id: str
    intitule: str
    mandat: str
    client: str


@router.get("/postes-actifs", response_model=list[PosteOuvert])
async def postes_actifs(db: DbSession, _: CurrentUser) -> list[PosteOuvert]:
    """Les postes auxquels on peut rattacher un dossier : ceux des mandats actifs."""
    postes = (
        (
            await db.execute(
                select(Poste)
                .join(Mandat, Poste.mandat_id == Mandat.id)
                .where(Mandat.archive_le.is_(None))
                .options(selectinload(Poste.mandat).selectinload(Mandat.client))
                .order_by(Poste.intitule)
            )
        )
        .scalars()
        .all()
    )
    return [
        PosteOuvert(
            id=p.id,
            intitule=p.intitule,
            mandat=p.mandat.intitule,
            client=p.mandat.client.nom if p.mandat.client else "",
        )
        for p in postes
    ]


class RattachementIn(BaseModel):
    poste_id: str = Field(min_length=1, max_length=36)


@router.post("/candidatures/{candidature_id}/rattacher", response_model=CandidatureOut)
async def rattacher(
    candidature_id: str, payload: RattachementIn, db: DbSession, user: CurrentUser
) -> CandidatureOut:
    """Range un dossier sous un poste, puis le note selon ce poste.

    Une candidature spontanée y entre comme si elle avait été reçue pour lui ;
    un dossier rangé sous le mauvais poste en change. Il est noté à nouveau —
    l'ancienne notation valait pour d'autres exigences.

    Deux refus. Un dossier déjà présent sous ce poste pour la même personne :
    les deux se confondraient. Un dossier déjà passé en entretien : ses notes
    d'entretien portent sur l'ancien poste, et le déplacer les rendrait fausses.
    """
    candidature = await get_candidature_or_404(db, candidature_id)
    poste = await get_poste_or_404(db, payload.poste_id)
    if candidature.poste_id == poste.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ce dossier est déjà rangé sous ce poste.")
    mandat = await db.get(Mandat, poste.mandat_id)
    if mandat is not None and mandat.archive_le is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Ce poste appartient à un mandat archivé."
        )
    if candidature.entretiens:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ce dossier a déjà des notes d'entretien pour son poste actuel : il ne "
            "peut pas changer de poste.",
        )
    deja = (
        await db.execute(
            select(Candidature.id).where(
                Candidature.poste_id == poste.id,
                Candidature.candidat_id == candidature.candidat_id,
            )
        )
    ).scalar_one_or_none()
    if deja is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cette personne a déjà un dossier sous ce poste.",
        )

    ancien = candidature.poste_id
    candidature.poste_id = poste.id
    await db.flush()
    rechargee = await get_candidature_or_404(db, candidature_id)
    await evaluer_candidature(db, rechargee)
    await audit.record(
        db,
        action="candidature.rattachement",
        entity_type="candidature",
        entity_id=candidature.id,
        user_id=user.id,
        details={"de": ancien, "vers": poste.id},
    )
    await db.commit()
    return _vers_sortie(await get_candidature_or_404(db, candidature_id))
