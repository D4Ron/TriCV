"""Postes, avis, et la grille de présélection.

La grille est l'artefact remis au client : elle et le tableau d'élimination
sortent d'un seul et même appel, pour que les totaux annoncés ne puissent pas
diverger entre deux fichiers produits à quelques minutes d'écart.
"""

from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.mandats import get_mandat_or_404
from app.deps import CurrentUser, DbSession
from app.domain.serialisation import bareme_depuis_dict, bareme_vers_dict
from app.models import (
    Avis,
    Candidat,
    Candidature,
    Client,
    Elimination,
    Mandat,
    Notation,
    Poste,
    StatutAvis,
    StatutCandidature,
)
from app.services.exports.grille import construire_classeur
from app.models.base import utcnow
from app.schemas.recrutement import (
    AvisCreate,
    AvisOut,
    AvisUpdate,
    BaremeIn,
    GrilleOut,
    GroupeElimination,
    LigneGrille,
    PosteCreate,
    PosteOut,
    PosteUpdate,
    RestrictionIn,
    SeuilIn,
)
from app.services import audit, doublons, parametres
from app.services.preselection import construire_bareme, definir_seuil, evaluer_poste

router = APIRouter(tags=["postes"])


async def get_poste_or_404(db: AsyncSession, poste_id: str) -> Poste:
    poste = await db.get(Poste, poste_id)
    if poste is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Poste introuvable")
    return poste


async def _vers_sortie(db: AsyncSession, poste: Poste) -> PosteOut:
    sortie = PosteOut.model_validate(poste)
    sortie.restriction = RestrictionIn(
        age_min=poste.restriction_age_min,
        age_max=poste.restriction_age_max,
        sexe=poste.restriction_sexe,
        nationalites=list(poste.restriction_nationalites or ()),
        justification=poste.restriction_justification or "",
    )
    nombre = await db.execute(
        select(func.count(Candidature.id)).where(Candidature.poste_id == poste.id)
    )
    sortie.nombre_candidatures = nombre.scalar_one()
    return sortie


def _appliquer_restriction(poste: Poste, restriction: RestrictionIn) -> None:
    poste.restriction_age_min = restriction.age_min
    poste.restriction_age_max = restriction.age_max
    poste.restriction_sexe = restriction.sexe
    poste.restriction_nationalites = restriction.nationalites or None
    poste.restriction_justification = restriction.justification.strip() or None


# --- postes -----------------------------------------------------------------


@router.get("/mandats/{mandat_id}/postes", response_model=list[PosteOut])
async def lister_postes(mandat_id: str, db: DbSession, _: CurrentUser) -> list[PosteOut]:
    await get_mandat_or_404(db, mandat_id)
    resultat = await db.execute(
        select(Poste).where(Poste.mandat_id == mandat_id).order_by(Poste.created_at)
    )
    return [await _vers_sortie(db, poste) for poste in resultat.scalars()]


@router.post(
    "/mandats/{mandat_id}/postes", response_model=PosteOut, status_code=status.HTTP_201_CREATED
)
async def creer_poste(
    mandat_id: str, payload: PosteCreate, db: DbSession, user: CurrentUser
) -> PosteOut:
    await get_mandat_or_404(db, mandat_id)
    donnees = payload.model_dump(exclude={"restriction"})
    # Les valeurs non précisées reprennent les réglages du cabinet, pour que
    # changer la pratique n'oblige pas à réécrire chaque fiche de poste.
    reglages = await parametres.lire(db)
    poste = Poste(
        mandat_id=mandat_id,
        seuil_preselection=reglages.seuil_preselection_defaut,
        seuil_nominal=reglages.seuil_preselection_defaut,
        **donnees,
    )
    _appliquer_restriction(poste, payload.restriction)
    db.add(poste)
    await db.flush()

    details: dict = {"intitule": poste.intitule}
    if payload.restriction.justification:
        # Une condition restrictive est une décision sensible : elle est
        # journalisée avec son motif dès la création du poste.
        details["restriction"] = payload.restriction.justification
    await audit.record(
        db,
        action="poste.create",
        entity_type="poste",
        entity_id=poste.id,
        user_id=user.id,
        details=details,
    )
    await db.commit()
    await db.refresh(poste)
    return await _vers_sortie(db, poste)


@router.get("/postes/{poste_id}", response_model=PosteOut)
async def lire_poste(poste_id: str, db: DbSession, _: CurrentUser) -> PosteOut:
    return await _vers_sortie(db, await get_poste_or_404(db, poste_id))


@router.patch("/postes/{poste_id}", response_model=PosteOut)
async def modifier_poste(
    poste_id: str, payload: PosteUpdate, db: DbSession, user: CurrentUser
) -> PosteOut:
    poste = await get_poste_or_404(db, poste_id)
    modifications = payload.model_dump(exclude_unset=True, exclude={"restriction"})
    for champ, valeur in modifications.items():
        setattr(poste, champ, valeur)

    details: dict = {"champs": sorted(modifications)}
    if payload.restriction is not None:
        _appliquer_restriction(poste, payload.restriction)
        details["restriction"] = payload.restriction.justification or "levée"

    await audit.record(
        db,
        action="poste.update",
        entity_type="poste",
        entity_id=poste.id,
        user_id=user.id,
        details=details,
    )
    await db.commit()
    await db.refresh(poste)
    return await _vers_sortie(db, poste)


@router.put("/postes/{poste_id}/bareme", response_model=PosteOut)
async def definir_bareme(
    poste_id: str, payload: BaremeIn, db: DbSession, user: CurrentUser
) -> PosteOut:
    poste = await get_poste_or_404(db, poste_id)
    try:
        # Valide avant d'enregistrer : un barème dont les lignes ne totalisent
        # pas le maximum annoncé produirait des notes sur une base fausse.
        bareme = bareme_depuis_dict(payload.bareme)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Barème invalide : {exc}") from exc

    poste.bareme = bareme_vers_dict(bareme)
    await audit.record(
        db,
        action="poste.bareme",
        entity_type="poste",
        entity_id=poste.id,
        user_id=user.id,
        details={"total_max": bareme.total_max},
    )
    await db.commit()
    await db.refresh(poste)
    return await _vers_sortie(db, poste)


@router.post("/postes/{poste_id}/seuil", response_model=PosteOut)
async def changer_seuil(
    poste_id: str, payload: SeuilIn, db: DbSession, user: CurrentUser
) -> PosteOut:
    poste = await get_poste_or_404(db, poste_id)
    try:
        definir_seuil(poste, payload.seuil, payload.justification)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    await audit.record(
        db,
        action="poste.seuil",
        entity_type="poste",
        entity_id=poste.id,
        user_id=user.id,
        details={
            "seuil": payload.seuil,
            "nominal": float(poste.seuil_nominal),
            "justification": payload.justification or None,
        },
    )
    await db.commit()
    await db.refresh(poste)
    return await _vers_sortie(db, poste)


@router.post("/postes/{poste_id}/evaluer")
async def relancer_evaluation(poste_id: str, db: DbSession, user: CurrentUser) -> dict:
    """Recalcule toute la présélection du poste.

    Idempotent : les motifs et la notation sont remplacés, les levées et les
    notes manuelles conservées.
    """
    poste = await get_poste_or_404(db, poste_id)
    nombre = await evaluer_poste(db, poste.id)
    await audit.record(
        db,
        action="poste.evaluer",
        entity_type="poste",
        entity_id=poste.id,
        user_id=user.id,
        details={"candidatures": nombre},
    )
    await db.commit()
    return {"candidatures_evaluees": nombre}


# --- grille -----------------------------------------------------------------


def _motifs_opposables(candidature: Candidature) -> list:
    """Les motifs qui écartent réellement le dossier.

    Un dossier en attente de relecture porte des motifs, mais ils ne sont pas
    opposables : le faire figurer au tableau d'élimination contredirait la
    garantie affichée partout ailleurs, et le compterait deux fois — une fois
    comme éliminé, une fois comme à vérifier.
    """
    if candidature.statut is StatutCandidature.A_VERIFIER:
        return []
    return [e for e in candidature.eliminations if e.leve_le is None]


def _ligne(candidature: Candidature) -> LigneGrille:
    candidat = candidature.candidat
    notation = candidature.notation
    actifs = _motifs_opposables(candidature)

    dernier = max(candidat.diplomes, key=lambda d: (d.niveau, d.annee or 0), default=None)
    # Le poste le plus récent : celui encore en cours d'abord, sinon la fin la
    # plus tardive.
    derniere = max(
        candidat.experiences,
        key=lambda e: (e.fin is None, e.fin or e.debut),
        default=None,
    )

    return LigneGrille(
        candidature_id=candidature.id,
        nom=candidat.nom,
        prenom=candidat.prenom,
        age=_age(candidat, candidature),
        nationalite=", ".join(candidat.nationalites or ()) or None,
        dernier_diplome=dernier.intitule if dernier else None,
        structure_employeur=derniere.employeur if derniere else None,
        ecole_universite=dernier.etablissement if dernier else None,
        adresse=candidat.adresse,
        note=float(notation.note_retenue) if notation else None,
        total_max=float(notation.total_max) if notation else None,
        preselectionne=candidature.statut is StatutCandidature.PRESELECTIONNEE,
        elimine=bool(actifs),
        motifs=[e.motif.value for e in actifs],
    )


def _age(candidat: Candidat, candidature: Candidature) -> int | None:
    if candidat.date_naissance is None:
        return None
    reference = candidature.recue_le.date()
    naissance = candidat.date_naissance
    age = reference.year - naissance.year
    if (reference.month, reference.day) < (naissance.month, naissance.day):
        age -= 1
    return age


async def construire_grille(db: AsyncSession, poste: Poste) -> GrilleOut:
    """Assemble la grille. Partagée par la lecture JSON et l'export Excel :
    les deux sorties viennent du même calcul, donc les totaux remis au client
    ne peuvent pas diverger d'un format à l'autre."""
    poste_id = poste.id

    resultat = await db.execute(
        select(Candidature)
        .where(Candidature.poste_id == poste_id)
        .options(
            selectinload(Candidature.candidat).selectinload(Candidat.diplomes),
            selectinload(Candidature.candidat).selectinload(Candidat.experiences),
            selectinload(Candidature.eliminations),
            selectinload(Candidature.notation),
        )
    )
    candidatures = list(resultat.scalars())

    # L'avis le plus récent porte la référence et la date de clôture qui
    # figureront en tête du fichier remis au client.
    dernier_avis = (
        await db.execute(
            select(Avis).where(Avis.poste_id == poste_id).order_by(Avis.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()

    mandat = await db.get(Mandat, poste.mandat_id)
    client = await db.get(Client, mandat.client_id) if mandat else None

    # Signaler les doublons dans la grille elle-même : sans cela, deux
    # homonymes se lisent comme une erreur de saisie plutôt que comme un
    # doublon détecté.
    repetitions = await doublons.compter_par_candidature(db, poste_id)

    bareme = construire_bareme(poste)
    preselectionnes: list[LigneGrille] = []
    non_retenus: list[LigneGrille] = []
    groupes: dict = {}
    a_verifier = 0

    for candidature in candidatures:
        ligne = _ligne(candidature)
        ligne.doublons = repetitions.get(candidature.id, 0)
        if candidature.statut is StatutCandidature.A_VERIFIER:
            a_verifier += 1

        if ligne.elimine:
            for motif in _motifs_opposables(candidature):
                groupe = groupes.setdefault(
                    motif.motif,
                    GroupeElimination(motif=motif.motif, libelle=motif.motif.libelle),
                )
                groupe.lignes.append(ligne)
        elif candidature.statut is StatutCandidature.PRESELECTIONNEE:
            preselectionnes.append(ligne)
        elif candidature.statut is not StatutCandidature.A_VERIFIER:
            non_retenus.append(ligne)

    # Note décroissante, puis nom : l'ordre reste stable à note égale, donc le
    # fichier remis au client ne change pas d'un export à l'autre.
    tri = lambda l: (-(l.note or 0), l.nom, l.prenom)  # noqa: E731
    preselectionnes.sort(key=tri)
    non_retenus.sort(key=tri)
    for groupe in groupes.values():
        groupe.lignes.sort(key=tri)

    return GrilleOut(
        poste_id=poste.id,
        poste_intitule=poste.intitule,
        client_nom=client.nom if client else None,
        mandat_intitule=mandat.intitule if mandat else None,
        reference_avis=dernier_avis.reference if dernier_avis else None,
        type_avis=dernier_avis.type_avis if dernier_avis else None,
        date_reference=dernier_avis.date_cloture if dernier_avis else None,
        seuil=float(poste.seuil_preselection),
        total_max=bareme.total_max,
        nombre_candidatures=len(candidatures),
        nombre_preselectionnes=len(preselectionnes),
        nombre_elimines=sum(1 for c in candidatures if _motifs_opposables(c)),
        nombre_a_verifier=a_verifier,
        preselectionnes=preselectionnes,
        non_retenus=non_retenus,
        elimines=sorted(groupes.values(), key=lambda g: g.motif.value),
    )


@router.get("/postes/{poste_id}/grille", response_model=GrilleOut)
async def grille(poste_id: str, db: DbSession, _: CurrentUser) -> GrilleOut:
    return await construire_grille(db, await get_poste_or_404(db, poste_id))


@router.get("/postes/{poste_id}/grille.xlsx")
async def grille_excel(poste_id: str, db: DbSession, user: CurrentUser) -> Response:
    """La grille de présélection au format tableur, telle qu'elle est remise."""
    poste = await get_poste_or_404(db, poste_id)
    donnees = await construire_grille(db, poste)
    classeur = construire_classeur(donnees, poste)

    await audit.record(
        db,
        action="poste.export_grille",
        entity_type="poste",
        entity_id=poste.id,
        user_id=user.id,
        details={"candidatures": donnees.nombre_candidatures},
    )
    await db.commit()

    nom = f"grille-preselection-{_slug(poste.intitule)}-{date.today():%Y%m%d}.xlsx"
    return Response(
        content=classeur,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


def _slug(texte: str) -> str:
    import unicodedata

    sans_accents = "".join(
        c
        for c in unicodedata.normalize("NFD", texte.lower())
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", "-", sans_accents).strip("-")[:60] or "poste"


# --- avis -------------------------------------------------------------------


@router.get("/postes/{poste_id}/avis", response_model=list[AvisOut])
async def lister_avis(poste_id: str, db: DbSession, _: CurrentUser) -> list[AvisOut]:
    await get_poste_or_404(db, poste_id)
    resultat = await db.execute(
        select(Avis).where(Avis.poste_id == poste_id).order_by(Avis.created_at.desc())
    )
    return [AvisOut.model_validate(a) for a in resultat.scalars()]


@router.post(
    "/postes/{poste_id}/avis", response_model=AvisOut, status_code=status.HTTP_201_CREATED
)
async def creer_avis(
    poste_id: str, payload: AvisCreate, db: DbSession, user: CurrentUser
) -> AvisOut:
    await get_poste_or_404(db, poste_id)
    avis = Avis(poste_id=poste_id, **payload.model_dump())
    db.add(avis)
    await db.flush()
    await audit.record(
        db,
        action="avis.create",
        entity_type="avis",
        entity_id=avis.id,
        user_id=user.id,
        details={"type": avis.type_avis.value},
    )
    await db.commit()
    await db.refresh(avis)
    return AvisOut.model_validate(avis)


async def _get_avis_or_404(db: AsyncSession, avis_id: str) -> Avis:
    avis = await db.get(Avis, avis_id)
    if avis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Avis introuvable")
    return avis


@router.patch("/avis/{avis_id}", response_model=AvisOut)
async def modifier_avis(
    avis_id: str, payload: AvisUpdate, db: DbSession, user: CurrentUser
) -> AvisOut:
    avis = await _get_avis_or_404(db, avis_id)
    modifications = payload.model_dump(exclude_unset=True)
    for champ, valeur in modifications.items():
        setattr(avis, champ, valeur)
    await audit.record(
        db,
        action="avis.update",
        entity_type="avis",
        entity_id=avis.id,
        user_id=user.id,
        details={"champs": sorted(modifications)},
    )
    await db.commit()
    await db.refresh(avis)
    return AvisOut.model_validate(avis)


@router.post("/avis/{avis_id}/publier", response_model=AvisOut)
async def publier_avis(avis_id: str, db: DbSession, user: CurrentUser) -> AvisOut:
    avis = await _get_avis_or_404(db, avis_id)
    if avis.date_cloture is None:
        # La clôture sert de date de référence à l'âge et à l'ancienneté :
        # sans elle, la grille ne serait pas reproductible.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Fixez la date de clôture avant de publier : elle sert de référence au calcul.",
        )
    avis.statut = StatutAvis.PUBLIE
    if avis.date_publication is None:
        avis.date_publication = utcnow().date()
    await audit.record(
        db,
        action="avis.publier",
        entity_type="avis",
        entity_id=avis.id,
        user_id=user.id,
        details={"cloture": avis.date_cloture.isoformat()},
    )
    await db.commit()
    await db.refresh(avis)
    return AvisOut.model_validate(avis)


@router.post("/avis/{avis_id}/cloturer", response_model=AvisOut)
async def cloturer_avis(avis_id: str, db: DbSession, user: CurrentUser) -> AvisOut:
    avis = await _get_avis_or_404(db, avis_id)
    avis.statut = StatutAvis.CLOTURE
    avis.accepte_candidatures = False
    await audit.record(
        db,
        action="avis.cloturer",
        entity_type="avis",
        entity_id=avis.id,
        user_id=user.id,
        details=None,
    )
    await db.commit()
    await db.refresh(avis)
    return AvisOut.model_validate(avis)
