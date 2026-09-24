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
from app.domain import GroupePieces
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
from app.services import declaration, doublons, parametres, uploads
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
    localisation: str | None = None
    type_avis: str
    date_cloture: date | None = None
    publie_le: date | None = None


class AvisPublicOut(AvisPublicItem):
    description: str | None = None
    missions: list[str] = Field(default_factory=list)
    reference: str | None = None
    rattachement: str | None = None
    responsabilites: list[str] = Field(default_factory=list)
    competences_techniques: list[str] = Field(default_factory=list)
    competences_comportementales: list[str] = Field(default_factory=list)
    # À qui écrire en cas de difficulté. Vide si aucune adresse n'est réglée :
    # la page renvoie alors à l'aide seule plutôt que d'afficher une adresse
    # inventée.
    contact: str | None = None
    profil: list[str] = Field(default_factory=list)
    # Les conditions éliminatoires, dites avant le dépôt : un dossier complet
    # composé pour rien serait un manque d'égards, et le candidat déclare
    # maintenant lui-même ce sur quoi elles portent.
    conditions: list[str] = Field(default_factory=list)
    # La justification que le poste donne de ses conditions restrictives. Le
    # cabinet l'exige en interne ; le candidat a le même droit de la lire.
    justification_conditions: str | None = None
    pieces_attendues: list[PieceAttendue] = Field(default_factory=list)
    pieces_facultatives: list[PieceAttendue] = Field(default_factory=list)
    # Groupes de pièces liées : « la CNI ou le passeport ». Le formulaire doit
    # les présenter comme un choix, pas comme deux exigences séparées.
    groupes_pieces: list[dict] = Field(default_factory=list)
    formats_pieces: dict[str, list[str]] = Field(default_factory=dict)
    pieces_libres_autorisees: bool = True
    taille_max_mo: int = 10
    formats_acceptes: list[str] = Field(default_factory=lambda: ["PDF", "Word"])
    accepte_candidatures: bool = True


class AidePublique(BaseModel):
    """Ce que la page d'aide aux candidats doit connaître du cabinet."""

    contact: str | None = None


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


def _conditions(poste: Poste) -> list[str]:
    """Les conditions éliminatoires, annoncées avant le dépôt.

    Le formulaire demande maintenant la date de naissance et la nationalité, et
    elles sont opposables dès l'enregistrement. Laisser quelqu'un composer un
    dossier complet pour l'écarter ensuite sur un critère qu'il n'avait jamais
    vu serait le traiter avec désinvolture — et l'avis publié porte de toute
    façon ces conditions.
    """
    dites: list[str] = []
    bas, haut = poste.restriction_age_min, poste.restriction_age_max
    if bas is not None and haut is not None:
        dites.append(f"Être âgé de {bas} à {haut} ans à la date de clôture")
    elif haut is not None:
        dites.append(f"Être âgé de {haut} ans au plus à la date de clôture")
    elif bas is not None:
        dites.append(f"Être âgé de {bas} ans au moins à la date de clôture")

    if poste.restriction_nationalites:
        dites.append(
            "Nationalité : " + ", ".join(sorted(poste.restriction_nationalites))
        )
    if poste.restriction_sexe:
        dites.append(f"Ce poste est réservé : {poste.restriction_sexe}")
    return dites


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


def _apparier_intitules(intitules: list[str] | None, attendus: int) -> list[str]:
    """Aligne les intitulés libres sur les fichiers.

    Le champ est facultatif : un formulaire qui ne l'envoie pas — ou qui n'en
    envoie que pour les pièces libres — reste accepté. On complète par des
    chaînes vides plutôt que de refuser un dépôt pour une étiquette absente.
    """
    valeurs = [(v or "").strip() for v in (intitules or ())]
    if len(valeurs) > attendus:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Il y a plus d'intitulés que de fichiers transmis.",
        )
    return valeurs + [""] * (attendus - len(valeurs))


async def _enregistrer_pieces(
    db: AsyncSession,
    candidature_id: str,
    acceptes: list,
    types_pieces: list[str],
    intitules: list[str],
) -> None:
    """Écrit les pièces d'un dépôt public, intitulé libre compris."""
    for accepte, type_piece, intitule in zip(
        acceptes, types_pieces, intitules, strict=True
    ):
        chemin = await uploads.store(accepte)
        db.add(
            PieceCandidature(
                candidature_id=candidature_id,
                type_piece=type_piece,
                nom_fichier=accepte.filename,
                chemin_stockage=chemin,
                type_mime=accepte.mime_type,
                taille_octets=len(accepte.data),
                empreinte=accepte.sha256,
                # Ne garder l'intitulé que là où il veut dire quelque chose : sur
                # une pièce codifiée, le libellé du référentiel fait foi.
                intitule_libre=(
                    intitule[:255] if intitule and type_piece == PieceDossier.AUTRE.value else None
                ),
            )
        )
    await db.flush()


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
                localisation=avis.poste.localisation,
                type_avis=avis.type_avis.value,
                date_cloture=avis.date_cloture,
                publie_le=avis.date_publication,
            )
        )
    return sortie


@router.get("/aide", response_model=AidePublique)
async def aide_publique(db: AsyncSession = Depends(get_db)) -> AidePublique:
    """L'adresse de contact des candidats, pour la page d'aide."""
    return AidePublique(contact=(await parametres.lire(db)).contact or None)


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
        reference=avis.reference,
        localisation=poste.localisation,
        rattachement=poste.rattachement,
        responsabilites=list(poste.responsabilites or ()),
        competences_techniques=list(poste.competences_techniques or ()),
        competences_comportementales=list(poste.competences_comportementales or ()),
        contact=(await parametres.lire(db)).contact or None,
        profil=_profil(poste),
        conditions=_conditions(poste),
        justification_conditions=poste.restriction_justification or None,
        pieces_attendues=_pieces(poste, poste.pieces_requises),
        pieces_facultatives=_pieces(poste, poste.pieces_facultatives),
        groupes_pieces=[
            {
                "mode": g.get("mode") or "TOUTES",
                "libelle": g.get("libelle") or "",
                "pieces": [
                    {"code": c, "libelle": _libelle_piece(c)} for c in (g.get("codes") or ())
                ],
            }
            for g in (poste.groupes_pieces or ())
        ],
        formats_pieces=poste.formats_pieces or {},
        pieces_libres_autorisees=poste.pieces_libres_autorisees,
        taille_max_mo=uploads.PLAFOND_ABSOLU_MO,
        accepte_candidatures=_accepte(avis),
    )


@router.post(
    "/candidature-spontanee",
    response_model=DepotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def deposer_spontanee(
    request: Request,
    db: AsyncSession = Depends(get_db),
    nom: str = Form(..., min_length=1, max_length=255),
    prenom: str = Form(..., min_length=1, max_length=255),
    email: EmailStr = Form(...),
    telephone: str | None = Form(default=None),
    adresse: str | None = Form(default=None, max_length=512),
    date_naissance: str | None = Form(default=None),
    sexe: str | None = Form(default=None),
    nationalites: str | None = Form(default=None),
    parcours: str | None = Form(default=None),
    domaine: str | None = Form(default=None, max_length=255),
    message: str | None = Form(default=None, max_length=2000),
    fichiers: list[UploadFile] = File(...),
    types_pieces: list[str] | None = Form(default=None),
    intitules_pieces: list[str] | None = Form(default=None),
) -> DepotResponse:
    """Dépôt hors avis : le formulaire « déposer votre CV » du site.

    Rattachée à aucun poste, donc jamais notée : il n'y a pas d'exigences à
    confronter. Le dossier rejoint le vivier, où une recherche par profil le
    retrouvera le jour où un mandat lui correspond. C'est la seconde porte de la
    même chaîne que le relevé courriel, qui traite pareillement un message sans
    référence d'avis mais porteur d'un CV lisible.

    Le seul type de pièce imposé est le CV : sans lui, il n'y a rien à classer.
    """
    reglages = await parametres.lire(db)
    if not reglages.candidatures_spontanees:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Les candidatures spontanées ne sont pas ouvertes actuellement.",
        )

    try:
        declare = declaration.lire_parcours(parcours)
        naissance = declaration.lire_date_naissance(date_naissance)
    except declaration.DeclarationInvalide as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    types = list(types_pieces or ())
    if not types:
        # Formulaire minimal : un seul fichier, forcément le CV.
        types = [PieceDossier.CV.value] * len(fichiers)
    if len(fichiers) != len(types):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Chaque fichier doit être accompagné du type de pièce correspondant.",
        )
    if PieceDossier.CV.value not in types:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Un curriculum vitae est nécessaire pour une candidature spontanée.",
        )
    intitules = _apparier_intitules(intitules_pieces, len(fichiers))

    public_limiter.check(client_ip(request))

    # Hors avis, l'unicité (poste, candidat) ne joue pas : on se rabat sur le
    # doublon strict de dossier pour ne pas ouvrir deux fois le même profil.
    acceptes = []
    for fichier in fichiers:
        try:
            acceptes.append(await uploads.validate(fichier, uploads.PLAFOND_ABSOLU_MO))
        except uploads.RejectedUpload as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    if await doublons.trouver_identique(db, None, [a.sha256 for a in acceptes]):
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
        adresse=(adresse or "").strip() or None,
        date_naissance=naissance,
        sexe=declaration.lire_sexe(sexe),
        nationalites=declaration.lire_nationalites(nationalites) or None,
        provenance=Provenance.DECLARE,
    )
    db.add(candidat)
    await db.flush()

    # Un profil du vivier ne vaut que par ce qu'on peut y chercher. Un parcours
    # déclaré le rend trouvable le jour où un mandat lui correspond ; sans lui,
    # le dossier n'est qu'un fichier joint à un nom.
    for ligne in declaration.appliquer(candidat, declare):
        db.add(ligne)
    await db.flush()

    notes = ["Candidature spontanée déposée depuis le site."]
    if domaine and domaine.strip():
        notes.append(f"Domaine visé : {domaine.strip()}")
    if message and message.strip():
        notes.append(message.strip())

    candidature = Candidature(
        poste_id=None,
        candidat_id=candidat.id,
        source=SourceCandidature.FORMULAIRE,
        recue_le=utcnow(),
        spontanee=True,
        notes_rh="\n".join(notes),
    )
    db.add(candidature)
    await db.flush()

    await _enregistrer_pieces(db, candidature.id, acceptes, types, intitules)
    await db.commit()

    return DepotResponse(
        ok=True,
        message=(
            "Votre candidature spontanée a bien été enregistrée. Elle sera "
            "conservée et examinée dès qu'un poste correspondra à votre profil."
        ),
        candidature_id=candidature.id,
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
    adresse: str | None = Form(default=None, max_length=512),
    # État civil déclaré. La date de naissance et la nationalité décident de
    # deux conditions éliminatoires ; sans elles, ces conditions ne
    # s'appliquaient qu'aux dossiers déjà dépouillés — donc pas à tous.
    date_naissance: str | None = Form(default=None),
    sexe: str | None = Form(default=None),
    nationalites: str | None = Form(default=None),
    # Le parcours déclaré, en JSON : diplômes, expériences, langues,
    # certifications. Voir `app.services.declaration`.
    parcours: str | None = Form(default=None),
    fichiers: list[UploadFile] = File(...),
    types_pieces: list[str] = Form(...),
    intitules_pieces: list[str] | None = Form(default=None),
) -> DepotResponse:
    """Dépôt d'un dossier depuis la page publique.

    Les pièces arrivent appariées : `types_pieces[i]` décrit `fichiers[i]`, et
    `intitules_pieces[i]` le nomme quand le type est libre (« AUTRE ») — c'est
    ce qui permet à un candidat de joindre une lettre de recommandation ou une
    attestation que l'avis n'avait pas prévue, sans la ranger sous un code qui
    fausserait le contrôle de complétude.

    Le candidat déclare aussi son état civil et son parcours. C'est redondant
    avec le CV, volontairement : le CV doit être lu pour livrer ses données, et
    tant qu'il ne l'a pas été le dossier est noté sur presque rien.
    """
    avis = await _avis_par_cle(db, cle_publique)
    if not _accepte(avis):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Cet avis n'accepte plus de candidatures."
        )
    # Lu avant de toucher aux fichiers : une déclaration incohérente se corrige
    # à l'écran, et rien ne sert de stocker des pièces pour les reprendre.
    try:
        declare = declaration.lire_parcours(parcours)
        naissance = declaration.lire_date_naissance(date_naissance)
    except declaration.DeclarationInvalide as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    if len(fichiers) != len(types_pieces):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Chaque fichier doit être accompagné du type de pièce correspondant.",
        )
    intitules = _apparier_intitules(intitules_pieces, len(fichiers))

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
    groupes = [
        GroupePieces(
            codes=frozenset(g.get("codes") or ()),
            mode=g.get("mode") or "TOUTES",
            libelle=g.get("libelle") or "",
        )
        for g in (poste.groupes_pieces or ())
    ]

    autorisees = set(poste.pieces_requises or ()) | set(poste.pieces_facultatives or ())
    for groupe in groupes:
        autorisees |= set(groupe.codes)
    if poste.pieces_libres_autorisees:
        # Le candidat peut joindre ce qu'il juge utile — une lettre de
        # recommandation, une attestation. Il la nomme lui-même.
        autorisees.add(PieceDossier.AUTRE.value)

    inconnues = set(types_pieces) - autorisees
    if inconnues:
        # Refuser plutot que de classer sous un type que l'avis n'a pas prevu :
        # une piece hors nomenclature fausserait le controle de completude.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Pièce non prévue par cet avis : {', '.join(sorted(inconnues))}",
        )

    fournies = frozenset(types_pieces)
    manquantes = set(poste.pieces_requises or ()) - fournies
    if manquantes:
        libelles = sorted(_libelle_piece(c) for c in manquantes)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Pièce(s) obligatoire(s) manquante(s) : {', '.join(libelles)}",
        )

    for groupe in groupes:
        if groupe.satisfait(fournies):
            continue
        if groupe.mode == "AU_MOINS_UNE":
            options = " ou ".join(sorted(_libelle_piece(c) for c in groupe.codes))
            detail = f"Fournissez l'un de ces documents : {options}."
        else:
            absentes = sorted(_libelle_piece(c) for c in groupe.manquantes(fournies))
            detail = f"Pièce(s) obligatoire(s) manquante(s) : {', '.join(absentes)}"
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)

    # Formats imposés : un avis peut exiger le PDF pour telle pièce.
    formats = poste.formats_pieces or {}
    for code, fichier in zip(types_pieces, fichiers):
        attendus = [f.lower().lstrip(".") for f in (formats.get(code) or ())]
        if not attendus:
            continue
        extension = (fichier.filename or "").rsplit(".", 1)[-1].lower()
        if extension not in attendus:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"« {_libelle_piece(code)} » doit être fourni au format "
                f"{' ou '.join(attendus).upper()}.",
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
        adresse=(adresse or "").strip() or None,
        date_naissance=naissance,
        sexe=declaration.lire_sexe(sexe),
        nationalites=declaration.lire_nationalites(nationalites) or None,
        # Saisi par l'intéressé lui-même : plus fiable qu'une extraction, donc
        # opposable sans relecture préalable.
        provenance=Provenance.DECLARE,
    )
    db.add(candidat)
    await db.flush()

    # Le parcours déclaré, avant l'évaluation : c'est lui qui la rend juste.
    for ligne in declaration.appliquer(candidat, declare):
        db.add(ligne)
    await db.flush()

    candidature = Candidature(
        poste_id=avis.poste_id,
        candidat_id=candidat.id,
        source=SourceCandidature.FORMULAIRE,
        recue_le=utcnow(),
    )
    db.add(candidature)
    await db.flush()

    await _enregistrer_pieces(db, candidature.id, acceptes, types_pieces, intitules)

    await evaluer_candidature(db, await charger_candidature(db, candidature.id))
    await db.commit()

    return DepotResponse(
        ok=True,
        message="Votre candidature a bien été enregistrée.",
        candidature_id=candidature.id,
    )
