"""Postes, avis, et la grille de présélection.

La grille est l'artefact remis au client : elle et le tableau d'élimination
sortent d'un seul et même appel, pour que les totaux annoncés ne puissent pas
diverger entre deux fichiers produits à quelques minutes d'écart.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.mandats import get_mandat_or_404
from app.deps import CurrentUser, DbSession
from app.domain import Qualification, sections_entretien
from app.domain.serialisation import bareme_depuis_dict, bareme_vers_dict
from app.models import (
    Avis,
    Candidat,
    Candidature,
    Client,
    Elimination,
    Entretien,
    Mandat,
    ModeleDocument,
    Notation,
    Poste,
    StatutAvis,
    StatutCandidature,
)
from app.services.exports.grille import TypeGrille, construire_classeur
from app.models.base import utcnow
from app.schemas.recrutement import (
    AvisCreate,
    AvisOut,
    AvisUpdate,
    BaremeIn,
    GrilleEntretienIn,
    GrilleOut,
    GroupeElimination,
    LigneGrille,
    PosteCreate,
    PosteOut,
    PosteUpdate,
    RestrictionIn,
    SeuilIn,
)
from app.services import audit, doublons, entretiens, parametres, redaction_avis
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
    sortie.fiche_a_texte = bool((poste.fiche_texte or "").strip())
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
        # Aucun plancher au départ : le classement sélectionne. La barre se
        # trace sur la grille, une fois les notes connues, et c'est ce
        # premier geste qui fixe la référence.
        seuil_preselection=0.0,
        seuil_nominal=0.0,
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


# Les champs de la fiche dont dépendent l'éligibilité ou la note. Les autres —
# intitulé, description, missions — sont de la présentation : les toucher ne
# justifie pas de rejouer toutes les grilles du poste.
_CHAMPS_NOTATION = frozenset(
    {
        "niveau_min",
        "domaines_acceptes",
        "annees_experience_min",
        "annees_experience_specifique_min",
        "domaines_experience",
        "experiences_specifiques",
        "pieces_requises",
        "groupes_pieces",
        "langues_requises",
        "formation_complementaire_souhaitee",
    }
)


def _verifier_coherence_experience(poste: Poste, modifications: dict) -> None:
    """« Spécifique ≤ générale », vérifié sur la fiche *après* modification.

    La règle vivait sur `PosteBase`, donc sur la création seule : une
    modification partielle ne la voyait pas. Le poste incohérent était écrit en
    base, et l'erreur ne surgissait qu'à la sérialisation de la réponse — une
    500 après enregistrement, c'est-à-dire le pire des deux mondes. Le contrôle
    porte ici sur la valeur qui *résultera* de la modification, champ modifié
    ou champ conservé.
    """

    def apres(champ: str):
        return modifications.get(champ, getattr(poste, champ))

    generale = apres("annees_experience_min") or 0
    seuils = [apres("annees_experience_specifique_min") or 0]
    seuils += [
        int(exigence.get("annees_min") or 0)
        for exigence in (apres("experiences_specifiques") or ())
    ]
    if max(seuils) > generale:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "L'expérience spécifique demandée ne peut pas dépasser l'expérience "
            "générale : une expérience spécifique est aussi une expérience.",
        )


@router.get("/postes/{poste_id}", response_model=PosteOut)
async def lire_poste(poste_id: str, db: DbSession, _: CurrentUser) -> PosteOut:
    return await _vers_sortie(db, await get_poste_or_404(db, poste_id))


@router.patch("/postes/{poste_id}", response_model=PosteOut)
async def modifier_poste(
    poste_id: str, payload: PosteUpdate, db: DbSession, user: CurrentUser
) -> PosteOut:
    poste = await get_poste_or_404(db, poste_id)
    modifications = payload.model_dump(exclude_unset=True, exclude={"restriction"})
    _verifier_coherence_experience(poste, modifications)
    for champ, valeur in modifications.items():
        setattr(poste, champ, valeur)

    details: dict = {"champs": sorted(modifications)}
    if payload.restriction is not None:
        _appliquer_restriction(poste, payload.restriction)
        details["restriction"] = payload.restriction.justification or "levée"

    # Modifier une exigence change qui est éliminé et comment chacun est noté.
    # Laisser la grille en l'état jusqu'à ce que quelqu'un pense à cliquer
    # « Recalculer » afficherait des motifs qui ne correspondent plus à la
    # fiche — et c'est la grille, pas la fiche, que le client relit.
    touche_la_notation = bool(_CHAMPS_NOTATION & set(modifications)) or (
        payload.restriction is not None
    )
    if touche_la_notation:
        await db.flush()
        details["candidatures_reevaluees"] = await evaluer_poste(db, poste.id)

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


class ExtrasFormationIn(BaseModel):
    """Ce que la formation rapporte au-delà du seul niveau de diplôme."""

    points_par_certification: float = Field(default=0.0, ge=0, le=7)
    certifications_max: int = Field(default=3, ge=1, le=10)
    points_formation_complementaire: float = Field(default=0.0, ge=0, le=7)


@router.put("/postes/{poste_id}/bareme/formation", response_model=PosteOut)
async def definir_extras_formation(
    poste_id: str, payload: ExtrasFormationIn, db: DbSession, user: CurrentUser
) -> PosteOut:
    """Règle la part « certifications et formation complémentaire » du barème.

    Endpoint étroit plutôt que le barème entier : l'écran n'aurait sinon aucun
    moyen d'envoyer ces deux réglages sans reconstruire les trente points, et
    reconstruire trente points côté navigateur, c'est se donner l'occasion de
    les reconstruire faux.

    Ces points se prennent **dans les sept de la formation**, jamais au-dessus :
    le total du barème est inchangé, et `Bareme.__post_init__` le vérifie.
    """
    poste = await get_poste_or_404(db, poste_id)
    bareme = construire_bareme(poste)
    modifie = replace(
        bareme,
        formation=replace(
            bareme.formation,
            points_par_certification=payload.points_par_certification,
            certifications_max=payload.certifications_max,
            points_formation_complementaire=payload.points_formation_complementaire,
        ),
    )
    poste.bareme = bareme_vers_dict(modifie)
    await db.flush()
    reevaluees = await evaluer_poste(db, poste.id)

    await audit.record(
        db,
        action="poste.bareme",
        entity_type="poste",
        entity_id=poste.id,
        user_id=user.id,
        details={
            "points_par_certification": payload.points_par_certification,
            "points_formation_complementaire": payload.points_formation_complementaire,
            "candidatures_reevaluees": reevaluees,
        },
    )
    await db.commit()
    await db.refresh(poste)
    return await _vers_sortie(db, poste)


@router.get("/postes/{poste_id}/grille-entretien")
async def lire_grille_entretien(poste_id: str, db: DbSession, _: CurrentUser) -> dict:
    """La grille d'entretien en vigueur pour ce poste."""
    poste = await get_poste_or_404(db, poste_id)
    grille = entretiens.bareme_du_poste(poste)
    return {
        "criteres": entretiens.bareme_vers_liste(grille),
        "total_max": sum(l.points_max for l in grille),
        "sections": [
            {"libelle": nom, "points_max": total} for nom, total in sections_entretien(grille)
        ],
        "par_defaut": poste.bareme_entretien is None,
    }


@router.put("/postes/{poste_id}/grille-entretien")
async def definir_grille_entretien(
    poste_id: str, payload: GrilleEntretienIn, db: DbSession, user: CurrentUser
) -> dict:
    """Enregistre la grille négociée avec le client pour ce poste.

    L'offre technique du cabinet présente sa grille comme « indicative », dont
    « les critères et la pondération seront validés par le client ». Un mandat
    réel s'en écarte donc régulièrement — d'où ce réglage poste par poste.

    Envoyer `criteres: null` rétablit la grille type du cabinet.
    """
    poste = await get_poste_or_404(db, poste_id)
    donnees = (
        [c.model_dump() for c in payload.criteres] if payload.criteres is not None else None
    )
    try:
        grille = entretiens.definir_grille(poste, donnees)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    await audit.record(
        db,
        action="poste.grille_entretien",
        entity_type="poste",
        entity_id=poste.id,
        user_id=user.id,
        details={
            "criteres": len(grille),
            "total": sum(l.points_max for l in grille),
            "par_defaut": donnees is None,
        },
    )
    await db.commit()
    return {
        "criteres": entretiens.bareme_vers_liste(grille),
        "total_max": sum(l.points_max for l in grille),
        "sections": [
            {"libelle": nom, "points_max": total} for nom, total in sections_entretien(grille)
        ],
        "par_defaut": donnees is None,
    }


@router.post("/postes/{poste_id}/seuil", response_model=PosteOut)
async def changer_seuil(
    poste_id: str, payload: SeuilIn, db: DbSession, user: CurrentUser
) -> PosteOut:
    poste = await get_poste_or_404(db, poste_id)
    try:
        definir_seuil(poste, payload.seuil, payload.justification)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    # Déplacer la barre *est* le geste qui change la présélection : c'est même
    # le seul but de l'écran, qui montre la distribution des notes pour aider à
    # la placer. Sans cette réévaluation, la barre bougeait et la liste des
    # préqualifiés restait celle de l'ancienne, jusqu'à ce que quelqu'un pense
    # à cliquer « Recalculer ».
    await db.flush()
    reevaluees = await evaluer_poste(db, poste.id)

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
            "candidatures_reevaluees": reevaluees,
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


def _ligne(candidature: Candidature, poids: float = 30.0) -> LigneGrille:
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
        note_sur_cent=_sur_cent(notation, poids),
        **_notes_entretien(candidature),
        **_qualification(candidature),
        preselectionne=candidature.statut is StatutCandidature.PRESELECTIONNEE,
        elimine=bool(actifs),
        appreciation_attendue=candidature.appreciation_consistance is None,
        motifs=[e.motif.value for e in actifs],
    )


def _notes_entretien(candidature: Candidature) -> dict:
    """La seconde étape, telle qu'elle apparaît dans la grille.

    Un dossier sans entretien renvoie des valeurs nulles plutôt que zéro :
    « pas encore reçu en entretien » et « n'a rien obtenu » ne se confondent
    pas dans un document remis au client. Avec plusieurs jurés, c'est leur
    moyenne qui remonte — comme dans le rapport du cabinet.
    """
    if candidature.notation is None:
        return {}
    fiches = list(candidature.entretiens or ())
    if not fiches:
        return {}

    notation = entretiens.notation_depuis_base(candidature.notation)
    finale = entretiens.calculer_note_finale(notation, fiches)
    return {
        "note_entretien_sur_cent": finale.entretien_sur_cent,
        "note_finale_sur_cent": finale.total_sur_cent,
        "entretien_complet": finale.entretien_complet,
    }


def _distribuer(notes: list[float], total_max: float, tranches: int = 6) -> list[dict]:
    """Combien de dossiers par tranche de note.

    Sert à poser le seuil en connaissance de cause : une barre tracée juste
    au-dessus d'un peloton de douze candidats n'est pas la même décision qu'une
    barre tracée dans un vide.
    """
    if not notes or total_max <= 0:
        return []
    largeur = total_max / tranches
    resultat = []
    for i in range(tranches):
        bas = i * largeur
        haut = total_max if i == tranches - 1 else (i + 1) * largeur
        # Borne haute incluse sur la dernière tranche seulement, sinon un
        # candidat au maximum tomberait hors de toutes les tranches.
        compte = sum(
            1 for n in notes if (bas <= n <= haut if i == tranches - 1 else bas <= n < haut)
        )
        resultat.append(
            {"de": round(bas, 1), "a": round(haut, 1), "candidats": compte}
        )
    return resultat


def _qualification(candidature: Candidature) -> dict:
    """La catégorie remise au client, calculée ou réinscrite."""
    retenue = candidature.qualification_manuelle or candidature.qualification
    if not retenue:
        return {}
    try:
        libelle = Qualification(retenue).libelle
    except ValueError:
        libelle = retenue
    return {"qualification": retenue, "qualification_libelle": libelle}


def _sur_cent(notation, poids: float) -> float | None:
    """Ce que la présélection apporte à la note finale sur 100.

    Calculée et non supposée : le barème vaut aujourd'hui 30 points pour un
    poids de 30 %, mais un client qui pondère autrement ne doit pas obliger à
    toucher au code.
    """
    if notation is None or not notation.total_max:
        return None
    return round(float(notation.note_retenue) / float(notation.total_max) * poids * 2) / 2


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
            selectinload(Candidature.entretiens).selectinload(Entretien.lignes),
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
        ligne = _ligne(candidature, bareme.poids_note_finale)
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

    # Le processus retient « les N premiers candidats ayant obtenu les
    # meilleures notes » : le rang est donc une information de la grille, et la
    # proposition au client s'y lit. Les préqualifiés au-delà du quota restent
    # affichés — ce sont eux qu'on rappelle si un candidat proposé se désiste.
    # Répartition des notes : c'est elle qui permet de poser le seuil après
    # coup, au vu des dossiers réellement reçus, plutôt qu'à l'avance.
    notes = sorted(
        (float(l.note) for l in preselectionnes + non_retenus if l.note is not None),
        reverse=True,
    )
    distribution = _distribuer(notes, bareme.total_max)

    quota = poste.nombre_a_retenir
    for rang, ligne in enumerate(preselectionnes, start=1):
        ligne.rang = rang
        ligne.propose = quota is None or rang <= quota
    nombre_proposes = sum(1 for l in preselectionnes if l.propose)
    nombre_entretiens = sum(1 for c in candidatures if c.entretiens)

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
        poids_preselection=bareme.poids_note_finale,
        nombre_a_proposer=poste.nombre_a_retenir,
        distribution=distribution,
        nombre_candidatures=len(candidatures),
        nombre_proposes=nombre_proposes,
        nombre_entretiens=nombre_entretiens,
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


# Les portées d'envoi, du côté du serveur pour qu'elles aient une définition
# unique. `None` = aucun filtre de statut.
_PORTEES: dict[str, tuple[StatutCandidature, ...] | None] = {
    # Tout le monde, y compris les dossiers écartés. C'est la portée de
    # l'accusé de réception : quelqu'un qui a déposé un dossier a le droit de
    # savoir qu'il est arrivé, quelle qu'en soit l'issue.
    "tous": None,
    "preselectionnes": (StatutCandidature.PRESELECTIONNEE,),
    "elimines": (StatutCandidature.ELIMINEE,),
    "a_verifier": (StatutCandidature.A_VERIFIER,),
    # Reçus et éligibles sans franchir le seuil : ni retenus, ni écartés.
    "sous_le_seuil": (StatutCandidature.ELIGIBLE, StatutCandidature.RECUE),
}


@router.get("/postes/{poste_id}/destinataires")
async def destinataires(
    poste_id: str, db: DbSession, _: CurrentUser, portee: str = "tous"
) -> dict:
    """Les dossiers d'un poste auxquels écrire, par portée.

    Les portées sont définies ici et non dans l'écran : « tous » doit signifier
    toutes les candidatures reçues, et non celles que la grille a chargées. Un
    accusé de réception qui saute les dossiers arrivés après le dernier
    rafraîchissement est pire que pas d'accusé du tout.

    Les dossiers sans adresse sont comptés à part : ils ne peuvent rien
    recevoir, et l'écran doit pouvoir le dire avant l'envoi plutôt que de
    rendre des échecs après.
    """
    await get_poste_or_404(db, poste_id)
    if portee not in _PORTEES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Portée inconnue : {portee}. Attendu : {', '.join(sorted(_PORTEES))}.",
        )

    requete = (
        select(Candidature.id, Candidat.email)
        .join(Candidat, Candidature.candidat_id == Candidat.id)
        .where(Candidature.poste_id == poste_id)
        .order_by(Candidature.recue_le)
    )
    statuts = _PORTEES[portee]
    if statuts is not None:
        requete = requete.where(Candidature.statut.in_(statuts))

    lignes = (await db.execute(requete)).all()
    joignables = [identifiant for identifiant, email in lignes if (email or "").strip()]
    return {
        "portee": portee,
        "candidature_ids": joignables,
        "total": len(lignes),
        "sans_adresse": len(lignes) - len(joignables),
    }


@router.get("/postes/{poste_id}/grille.xlsx")
async def grille_excel(
    poste_id: str,
    db: DbSession,
    user: CurrentUser,
    type_grille: TypeGrille = TypeGrille.COMPLET,
) -> Response:
    """Un des documents tableur du poste, ou le classeur complet.

    Le défaut reste le classeur entier : un lien existant continue de rendre ce
    qu'il rendait. Les quatre autres valeurs isolent un document, parce qu'ils
    ne s'adressent pas aux mêmes personnes — le classement au client, le
    tableau d'élimination à un candidat qui conteste.
    """
    poste = await get_poste_or_404(db, poste_id)
    donnees = await construire_grille(db, poste)
    # Le détail des entretiens ne circule que dans l'export : l'écran se
    # contente des totaux, le rapport a besoin des observations.
    fiches = await entretiens.par_poste(db, poste.id)
    classeur = construire_classeur(donnees, poste, fiches, type_grille)

    await audit.record(
        db,
        action="poste.export_grille",
        entity_type="poste",
        entity_id=poste.id,
        user_id=user.id,
        details={
            "type": type_grille.value,
            "candidatures": donnees.nombre_candidatures,
            "entretiens": len(fiches),
        },
    )
    await db.commit()

    nom = (
        f"kapi-{type_grille.fichier}-{_slug(poste.intitule)}-{date.today():%Y%m%d}.xlsx"
    )
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


class RedactionAvisIn(BaseModel):
    """Une proposition de texte d'avis, à relire avant publication."""

    avis_id: str | None = None
    # Gabarit imposé par le client. Facultatif : sans lui, l'avis est rédigé
    # dans la présentation habituelle du cabinet. La rédaction assistée
    # elle-même est facultative — `avec_assistance=false` rend le squelette,
    # à compléter à la main.
    modele_id: str | None = None
    avec_assistance: bool = True


class RedactionAvisOut(BaseModel):
    texte: str
    # Vrai si le texte vient du modèle de langage. Faux quand on rend le
    # squelette : l'écran doit dire lequel des deux il affiche.
    propose: bool
    avertissement: str | None = None


@router.post("/postes/{poste_id}/avis/redaction", response_model=RedactionAvisOut)
async def rediger_avis(
    poste_id: str, payload: RedactionAvisIn, db: DbSession, _: CurrentUser
) -> RedactionAvisOut:
    """Propose le texte d'un avis à partir de la fiche de poste.

    Ne crée ni ne modifie rien : le texte est rendu pour être relu, corrigé, et
    enregistré ensuite sur l'avis par le PATCH habituel. Un avis publié est
    opposable ; il ne doit jamais s'écrire sans que quelqu'un l'ait lu.
    """
    poste = await get_poste_or_404(db, poste_id)
    mandat = (
        await db.execute(
            select(Mandat)
            .where(Mandat.id == poste.mandat_id)
            .options(selectinload(Mandat.client))
        )
    ).scalar_one_or_none()

    avis = None
    if payload.avis_id:
        avis = await _get_avis_or_404(db, payload.avis_id)

    gabarit = ""
    if payload.modele_id:
        modele = await db.get(ModeleDocument, payload.modele_id)
        if modele is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Modèle introuvable")
        gabarit = modele.texte_source or ""

    reglages = await parametres.lire(db)
    if payload.avec_assistance:
        texte = await redaction_avis.rediger(poste, avis, mandat, gabarit, reglages)
        if texte:
            return RedactionAvisOut(
                texte=texte,
                propose=True,
                avertissement=_avertissement_redaction(poste, reglages),
            )
        return RedactionAvisOut(
            texte=redaction_avis.brouillon_manuel(poste, avis, mandat, reglages),
            propose=False,
            avertissement=(
                "La rédaction assistée n'a rien renvoyé. Voici les éléments de "
                "la fiche, à mettre en forme."
            ),
        )

    return RedactionAvisOut(
        texte=redaction_avis.brouillon_manuel(poste, avis, mandat, reglages),
        propose=False,
        avertissement=_avertissement_redaction(poste, reglages),
    )


def _avertissement_redaction(poste: Poste, reglages) -> str | None:
    """Ce qui manque pour que l'avis soit complet — dit avant qu'on le publie."""
    manques: list[str] = []
    if not (poste.fiche_texte or "").strip():
        manques.append(
            "aucune fiche de poste n'est jointe : le texte ne s'appuie que sur les "
            "champs du poste"
        )
    if not reglages.url_publique:
        manques.append(
            "l'adresse publique de l'application n'est pas réglée : le lien de "
            "candidature et celui de l'aide ne peuvent pas figurer dans l'avis"
        )
    if not reglages.contact:
        manques.append(
            "aucune adresse de contact n'est réglée : la section « En cas de "
            "difficulté » n'a personne à indiquer"
        )
    if not manques:
        return None
    return "À savoir : " + " ; ".join(manques) + "."


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


@router.delete("/avis/{avis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def supprimer_avis(avis_id: str, db: DbSession, user: CurrentUser) -> Response:
    """Supprime un avis resté au brouillon.

    Un brouillon est un essai : on en crée un, on se trompe de type ou de
    référence, et il n'y a aucune raison de le garder. Rien n'y est attaché —
    sa clé publique n'a jamais été diffusée, et les candidatures se rattachent
    au poste, pas à l'avis.

    Un avis **publié** ne se supprime pas. Sa clé circule : elle est dans les
    messages envoyés aux candidats, peut-être dans un journal officiel. La
    faire disparaître transformerait un lien reçu de bonne foi en page
    introuvable, sans que personne sache pourquoi. Pour arrêter les dépôts, on
    le clôture — le lien répond alors qu'il est fermé.
    """
    avis = await _get_avis_or_404(db, avis_id)
    if avis.statut is StatutAvis.PUBLIE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cet avis est publié : son lien a pu être diffusé, et le supprimer "
            "le rendrait introuvable pour les candidats qui l'ont reçu. "
            "Clôturez-le plutôt : les dépôts s'arrêtent et le lien continue de "
            "répondre.",
        )
    if avis.statut is StatutAvis.CLOTURE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cet avis a été publié puis clôturé : il fait partie de l'historique "
            "du poste, et son lien peut encore être suivi. Archivez le mandat "
            "pour le sortir des listes.",
        )

    await audit.record(
        db,
        action="avis.supprimer",
        entity_type="avis",
        entity_id=avis.id,
        user_id=user.id,
        details={"reference": avis.reference, "type": avis.type_avis.value},
    )
    await db.delete(avis)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/avis/{avis_id}/publier", response_model=AvisOut)
async def publier_avis(avis_id: str, db: DbSession, user: CurrentUser) -> AvisOut:
    avis = await _get_avis_or_404(db, avis_id)
    poste = await get_poste_or_404(db, avis.poste_id)
    if poste.a_completer:
        # Un poste créé « à compléter plus tard » n'a que des exigences par
        # défaut. Publier l'avis ferait noter des candidats sur des valeurs que
        # personne n'a décidées.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "La fiche de ce poste n'est pas encore complétée : ses exigences sont "
            "des valeurs par défaut. Complétez-la (« Modifier la fiche ») avant "
            "de publier l'avis.",
        )
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
