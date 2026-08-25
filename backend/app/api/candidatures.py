"""Candidatures : dépôt, consultation, vérification, arbitrage.

Trois actions sont réservées à un humain et ne peuvent pas être déduites :
confirmer des données extraites, lever un motif d'élimination, saisir une note
manuelle. Toutes les trois exigent un motif écrit et passent au journal.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.postes import get_poste_or_404
from app.deps import CurrentUser, DbSession
from app.models import (
    Candidat,
    Candidature,
    DiplomeCandidat,
    Elimination,
    ExperienceCandidat,
    Notation,
    PieceCandidature,
    Provenance,
    SourceCandidature,
    StatutCandidature,
)
from app.models.base import utcnow
from app.schemas.recrutement import (
    CandidatureCreate,
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
    audit,
    courriel,
    depouillement,
    doublons,
    parametres,
    storage,
    uploads,
)
from app.services.preselection import charger_candidature, evaluer_candidature

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
) -> dict:
    """Dépôt en lot de dossiers déjà en main — typiquement une boîte email
    vidée à la main.

    Un fichier donne une candidature. Personne n'ayant rien saisi, l'état civil
    se réduit au nom du fichier et porte la provenance EXTRAIT_IA : les dossiers
    atterrissent donc en A_VERIFIER, jamais éliminés ni présélectionnés
    d'office.

    Un fichier refusé n'interrompt pas le lot : le compte rendu dit lequel et
    pourquoi.
    """
    poste = await get_poste_or_404(db, poste_id)
    resultats: list[dict] = []

    for fichier in fichiers:
        nom_fichier = (fichier.filename or "dossier").strip()
        try:
            # Dépôt authentifié : aucune limite de taille.
            accepte = await uploads.validate(fichier)
        except uploads.RejectedUpload as exc:
            resultats.append({"fichier": nom_fichier, "accepte": False, "erreur": str(exc)})
            continue

        # Fichier déjà reçu pour ce poste : rien à en tirer, on n'ouvre pas
        # de second dossier. Le compte rendu dit lequel il duplique.
        identique = await doublons.trouver_identique(db, poste.id, [accepte.sha256])
        if identique is not None:
            resultats.append(
                {
                    "fichier": nom_fichier,
                    "accepte": False,
                    "doublon_de": identique[1],
                    "erreur": f"Doublon du dossier de {identique[1]} — fichier identique, ignoré.",
                }
            )
            continue

        candidat = Candidat(
            # Le nom du fichier est le seul indice disponible ; il sera corrigé
            # au dépouillement ou à la relecture.
            nom=Path(accepte.filename).stem[:255] or "Dossier",
            prenom="",
            provenance=Provenance.EXTRAIT_IA,
        )
        db.add(candidat)
        await db.flush()

        candidature = Candidature(
            poste_id=poste.id,
            candidat_id=candidat.id,
            source=SourceCandidature.IMPORT_MANUEL,
            recue_le=utcnow(),
            notes_rh=f"Déposé en lot — fichier d'origine : {nom_fichier}",
        )
        db.add(candidature)
        await db.flush()

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

        chargee = await charger_candidature(db, candidature.id)
        await evaluer_candidature(db, chargee)

        # Le lot est le cas où les doublons apparaissent : on les signale tout
        # de suite plutôt que de laisser les RH les découvrir dans la grille.
        repetitions = await doublons.detecter(db, chargee)
        if depouiller_aussitot:
            await depouillement.depouiller(db, chargee)

        resultats.append(
            {
                "fichier": nom_fichier,
                "accepte": True,
                "candidature_id": candidature.id,
                "doublons": [
                    {"candidature_id": d.candidature_id, "nom": d.nom_complet, "motif": d.libelle}
                    for d in repetitions
                ],
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


@router.get("/courriel/etat")
async def etat_courriel(db: DbSession, _: CurrentUser) -> dict:
    reglages = await parametres.lire(db)
    return {
        "actif": reglages.courriel_utilisable,
        "boite": reglages.imap_user or None,
        "dossier": reglages.imap_folder if reglages.courriel_utilisable else None,
    }


async def _config_boite(db: AsyncSession) -> courriel.ConfigBoite:
    """Les coordonnées de la boîte, ou un refus qui dit quoi faire.

    Tout se règle depuis Paramètres › Boîte de candidatures : le message
    renvoie donc à l'écran, pas au fichier de configuration du serveur.
    """
    reglages = await parametres.lire(db)
    if not reglages.courriel_actif:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Le relevé de la boîte est désactivé. Activez-le dans "
            "Paramètres › Boîte de candidatures.",
        )
    manquants = [
        libelle
        for libelle, valeur in (
            ("le serveur", reglages.imap_host),
            ("l'adresse", reglages.imap_user),
            ("le mot de passe", reglages.imap_password),
        )
        if not valeur
    ]
    if manquants:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Boîte incomplète : il manque {' et '.join(manquants)}. "
            "À renseigner dans Paramètres › Boîte de candidatures.",
        )
    return courriel.ConfigBoite(
        hote=reglages.imap_host,
        port=reglages.imap_port,
        utilisateur=reglages.imap_user,
        mot_de_passe=reglages.imap_password,
        dossier=reglages.imap_folder,
    )


@router.post("/courriel/tester")
async def tester_courriel(db: DbSession, _: CurrentUser) -> dict:
    """Ouvre la boîte et compte, sans rien lire ni écrire."""
    boite = courriel.BoiteImap(await _config_boite(db))
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
    boite = courriel.BoiteImap(await _config_boite(db))
    try:
        lignes = await courriel.apercu(db, boite)
    except courriel.ErreurBoite as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    finally:
        boite.fermer()
    return {"messages": len(lignes), "details": lignes}


@router.post("/courriel/relever")
async def relever_courriel(db: DbSession, user: CurrentUser) -> dict:
    """Relève la boîte et crée les candidatures rattachables.

    Déclenché à la demande plutôt que par une tâche de fond : le relevé est une
    action que les RH veulent voir aboutir, avec son compte-rendu.
    """
    boite = courriel.BoiteImap(await _config_boite(db))
    try:
        resultat = await courriel.relever(db, boite)
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
        details={"crees": resultat.crees, "ignores": resultat.ignores},
    )
    await db.commit()
    return {
        "crees": resultat.crees,
        "ignores": resultat.ignores,
        "non_rattaches": resultat.non_rattaches,
        "sans_piece": resultat.sans_piece,
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
) -> CandidatureOut:
    """Classe un fichier sur une pièce du dossier.

    Si la pièce était seulement constatée reçue, le fichier vient s'y attacher
    plutôt que d'en créer une seconde : la complétude ne doit pas dépendre du
    moment où le document a été rangé.
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


@router.post("/candidatures/{candidature_id}/depouiller")
async def depouiller_dossier(
    candidature_id: str, db: DbSession, user: CurrentUser
) -> dict:
    """Lit les pièces et propose un parcours à confirmer.

    Le dossier reste en A_VERIFIER : tout ce qui est écrit ici porte la
    provenance EXTRAIT_IA et n'élimine personne avant relecture.
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
        "avertissements": resultat.avertissements,
    }


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
