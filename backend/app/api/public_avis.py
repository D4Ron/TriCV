"""Façade publique des avis : consultation et dépôt de candidature.

Non authentifiée, donc volontairement avare. Un candidat voit l'intitulé du
poste, le profil demandé et la liste des pièces à fournir. Il ne voit jamais
une note, un classement, ni l'existence d'un autre candidat.

Le dépôt écrit dans la même chaîne que les candidatures reçues par email, avec
une différence : ici le candidat déclare lui-même son état civil, ce qui donne
la provenance DECLARE — plus fiable qu'une extraction, et donc opposable sans
relecture.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import get_db
from app.deps import client_ip
from app.domain.referentiel import PieceDossier
from app.models import (
    Avis,
    Candidat,
    Candidature,
    PieceCandidature,
    Poste,
    Provenance,
    SourceCandidature,
    StatutAvis,
)
from app.models.base import utcnow
from app.services import doublons, uploads
from app.services.preselection import charger_candidature, evaluer_candidature
from app.services.ratelimit import public_limiter

router = APIRouter(prefix="/public", tags=["public"])


class PieceAttendue(BaseModel):
    code: str
    libelle: str


class AvisPublicItem(BaseModel):
    cle_publique: str
    intitule: str
    client: str | None = None
    departement: str | None = None
    type_avis: str
    date_cloture: date | None = None
    publie_le: date | None = None


class AvisPublicOut(AvisPublicItem):
    description: str | None = None
    missions: list[str] = Field(default_factory=list)
    profil: list[str] = Field(default_factory=list)
    pieces_attendues: list[PieceAttendue] = Field(default_factory=list)
    pieces_facultatives: list[PieceAttendue] = Field(default_factory=list)
    taille_max_mo: int = 10
    formats_acceptes: list[str] = Field(default_factory=lambda: ["PDF", "Word"])
    accepte_candidatures: bool = True


class DepotResponse(BaseModel):
    ok: bool
    message: str
    candidature_id: str


async def _avis_par_cle(db: AsyncSession, cle: str) -> Avis:
    resultat = await db.execute(
        select(Avis)
        .where(Avis.cle_publique == cle)
        .options(selectinload(Avis.poste).selectinload(Poste.mandat))
    )
    avis = resultat.scalar_one_or_none()
    if avis is None or avis.statut is StatutAvis.BROUILLON:
        # Un brouillon n'existe pas pour le public : même réponse qu'une clé
        # inconnue, pour ne pas révéler qu'un avis se prépare.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ce lien de candidature n'est pas valide.")
    return avis


def _profil(poste: Poste) -> list[str]:
    lignes = [f"Diplôme de niveau BAC+{poste.niveau_min} minimum"]
    if poste.domaines_acceptes:
        lignes.append(f"Domaines acceptés : {', '.join(poste.domaines_acceptes)}")
    if poste.annees_experience_min:
        lignes.append(f"{poste.annees_experience_min} an(s) d'expérience professionnelle")
    if poste.annees_experience_specifique_min:
        domaines = ", ".join(poste.domaines_experience) or "le domaine du poste"
        lignes.append(
            f"dont {poste.annees_experience_specifique_min} an(s) en {domaines}"
        )
    if poste.langues_requises:
        lignes.append(f"Langues : {', '.join(poste.langues_requises)}")
    return lignes


def _pieces(poste: Poste, codes: list | None) -> list[PieceAttendue]:
    sortie = []
    for code in codes or ():
        try:
            sortie.append(PieceAttendue(code=code, libelle=PieceDossier(code).libelle))
        except ValueError:
            sortie.append(PieceAttendue(code=code, libelle=code))
    return sortie


def _libelle_piece(code: str) -> str:
    try:
        return PieceDossier(code).libelle
    except ValueError:
        return code


def _accepte(avis: Avis) -> bool:
    if avis.statut is not StatutAvis.PUBLIE or not avis.accepte_candidatures:
        return False
    # La clôture ferme le dépôt d'elle-même : personne n'a à penser à le faire.
    return avis.date_cloture is None or avis.date_cloture >= utcnow().date()


@router.get("/avis", response_model=list[AvisPublicItem])
async def avis_ouverts(db: AsyncSession = Depends(get_db)) -> list[AvisPublicItem]:
    """L'index des postes ouverts."""
    resultat = await db.execute(
        select(Avis)
        .where(Avis.statut == StatutAvis.PUBLIE, Avis.accepte_candidatures.is_(True))
        .options(selectinload(Avis.poste).selectinload(Poste.mandat))
        .order_by(Avis.date_publication.desc())
    )
    sortie = []
    for avis in resultat.scalars():
        if not _accepte(avis):
            continue
        sortie.append(
            AvisPublicItem(
                cle_publique=avis.cle_publique,
                intitule=avis.poste.intitule,
                departement=avis.poste.departement,
                type_avis=avis.type_avis.value,
                date_cloture=avis.date_cloture,
                publie_le=avis.date_publication,
            )
        )
    return sortie


@router.get("/avis/{cle_publique}", response_model=AvisPublicOut)
async def avis_public(cle_publique: str, db: AsyncSession = Depends(get_db)) -> AvisPublicOut:
    avis = await _avis_par_cle(db, cle_publique)
    poste = avis.poste
    return AvisPublicOut(
        cle_publique=avis.cle_publique,
        intitule=poste.intitule,
        departement=poste.departement,
        type_avis=avis.type_avis.value,
        date_cloture=avis.date_cloture,
        publie_le=avis.date_publication,
        description=poste.description or avis.texte,
        missions=list(poste.missions or ()),
        profil=_profil(poste),
        pieces_attendues=_pieces(poste, poste.pieces_requises),
        pieces_facultatives=_pieces(poste, poste.pieces_facultatives),
        taille_max_mo=uploads.PLAFOND_ABSOLU_MO,
        accepte_candidatures=_accepte(avis),
    )


@router.post(
    "/avis/{cle_publique}/candidater",
    response_model=DepotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def deposer(
    cle_publique: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    nom: str = Form(..., min_length=1, max_length=255),
    prenom: str = Form(..., min_length=1, max_length=255),
    email: EmailStr = Form(...),
    telephone: str | None = Form(default=None),
    fichiers: list[UploadFile] = File(...),
    types_pieces: list[str] = Form(...),
) -> DepotResponse:
    """Dépôt d'un dossier depuis la page publique.

    Les pièces arrivent appariées : `types_pieces[i]` décrit `fichiers[i]`.
    """
    avis = await _avis_par_cle(db, cle_publique)
    if not _accepte(avis):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Cet avis n'accepte plus de candidatures."
        )
    if len(fichiers) != len(types_pieces):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Chaque fichier doit être accompagné du type de pièce correspondant.",
        )

    public_limiter.check(client_ip(request))

    # Un même email ne redépose pas deux fois sur le même poste : la contrainte
    # d'unicité le refuserait, autant le dire clairement.
    existant = await db.execute(
        select(Candidature.id)
        .join(Candidat, Candidat.id == Candidature.candidat_id)
        .where(Candidature.poste_id == avis.poste_id, Candidat.email == email.lower())
        .limit(1)
    )
    if existant.scalar_one_or_none():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Une candidature a déjà été enregistrée pour cette adresse email.",
        )

    poste = avis.poste
    autorisees = set(poste.pieces_requises or ()) | set(poste.pieces_facultatives or ())
    inconnues = set(types_pieces) - autorisees
    if inconnues:
        # Refuser plutot que de classer sous un type que l'avis n'a pas prevu :
        # une piece hors nomenclature fausserait le controle de completude.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Pièce non prévue par cet avis : {', '.join(sorted(inconnues))}",
        )
    manquantes = set(poste.pieces_requises or ()) - set(types_pieces)
    if manquantes:
        libelles = sorted(_libelle_piece(c) for c in manquantes)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Pièce(s) obligatoire(s) manquante(s) : {', '.join(libelles)}",
        )

    acceptes = []
    for fichier in fichiers:
        try:
            # Route non authentifiée : le plafond absolu protège la
            # mémoire du serveur, il ne restreint aucun dossier réel.
            acceptes.append(
                await uploads.validate(fichier, uploads.PLAFOND_ABSOLU_MO)
            )
        except uploads.RejectedUpload as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    # Dossier strictement identique déjà reçu : inutile d'en ouvrir un second.
    identique = await doublons.trouver_identique(
        db, avis.poste_id, [a.sha256 for a in acceptes]
    )
    if identique is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ce dossier a déjà été reçu : les fichiers transmis sont identiques à "
            "une candidature existante.",
        )

    candidat = Candidat(
        nom=nom.strip(),
        prenom=prenom.strip(),
        email=email.lower(),
        telephone=(telephone or "").strip() or None,
        # Saisi par l'intéressé lui-même : plus fiable qu'une extraction, donc
        # opposable sans relecture préalable.
        provenance=Provenance.DECLARE,
    )
    db.add(candidat)
    await db.flush()

    candidature = Candidature(
        poste_id=avis.poste_id,
        candidat_id=candidat.id,
        source=SourceCandidature.FORMULAIRE,
        recue_le=utcnow(),
    )
    db.add(candidature)
    await db.flush()

    for accepte, type_piece in zip(acceptes, types_pieces, strict=True):
        chemin = await uploads.store(accepte)
        db.add(
            PieceCandidature(
                candidature_id=candidature.id,
                type_piece=type_piece,
                nom_fichier=accepte.filename,
                chemin_stockage=chemin,
                type_mime=accepte.mime_type,
                taille_octets=len(accepte.data),
                empreinte=accepte.sha256,
            )
        )
    await db.flush()

    await evaluer_candidature(db, await charger_candidature(db, candidature.id))
    await db.commit()

    return DepotResponse(
        ok=True,
        message="Votre candidature a bien été enregistrée.",
        candidature_id=candidature.id,
    )
