"""Le vivier : rechercher parmi les profils déjà connus du cabinet.

La purge des mandats archivés efface les fichiers et garde ce qu'on en a tiré.
Ces routes sont ce qui donne un usage à cette distinction : retrouver, des mois
plus tard, « un contrôleur de gestion BAC+5 avec dix ans d'expérience » sans
republier un avis.

Les données servies ici sont des données personnelles — identité, âge, sexe,
nationalité, coordonnées. L'accès est donc authentifié comme partout, et la
recherche est journalisée quand elle porte sur les attributs sensibles : voir
une liste filtrée par sexe ou par nationalité est une action qui doit laisser
une trace, même si le motif est parfaitement légitime (poste réservé, quota,
condition posée par le client).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.deps import CurrentUser, DbSession
from app.domain.referentiel import Sexe
from app.schemas.vivier import (
    DiplomeVivier,
    ExperienceVivier,
    HistoriqueVivier,
    ProfilVivier,
    VivierItem,
    VivierPage,
)
from app.services import audit, vivier

router = APIRouter(tags=["vivier"])

PAGE_MAX = 200


def _item(ligne: vivier.LigneVivier) -> VivierItem:
    candidat = ligne.candidat
    return VivierItem(
        id=candidat.id,
        nom=candidat.nom,
        prenom=candidat.prenom,
        email=candidat.email,
        telephone=candidat.telephone,
        sexe=candidat.sexe,
        age=ligne.age,
        nationalites=list(candidat.nationalites or ()),
        provenance=candidat.provenance,
        verifie=candidat.verifie_le is not None,
        niveau_max=ligne.niveau_max,
        niveau_libelle=vivier.libelle_niveau(ligne.niveau_max),
        diplome_principal=ligne.diplome_principal,
        domaine_principal=ligne.domaine_principal,
        annees_experience=ligne.annees_experience,
        dernier_poste=ligne.dernier_poste,
        dernier_employeur=ligne.dernier_employeur,
        nombre_candidatures=ligne.nombre_candidatures,
        derniere_candidature=ligne.derniere_candidature,
        postes_vises=ligne.postes_vises,
        pieces_conservees=ligne.pieces_conservees,
        pieces_purgees=ligne.pieces_purgees,
    )


@router.get("/vivier", response_model=VivierPage)
async def rechercher_vivier(
    db: DbSession,
    user: CurrentUser,
    recherche: str = Query(default="", max_length=255),
    niveau_min: int | None = Query(default=None, ge=0, le=8),
    domaine: str = Query(default="", max_length=255),
    annees_experience_min: float | None = Query(default=None, ge=0, le=60),
    sexe: Sexe | None = None,
    age_min: int | None = Query(default=None, ge=15, le=100),
    age_max: int | None = Query(default=None, ge=15, le=100),
    nationalite: str = Query(default="", max_length=128),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=PAGE_MAX),
) -> VivierPage:
    criteres = vivier.Criteres(
        recherche=recherche,
        niveau_min=niveau_min,
        domaine=domaine,
        annees_experience_min=annees_experience_min,
        sexe=sexe,
        age_min=age_min,
        age_max=age_max,
        nationalite=nationalite,
    )
    lignes, total = await vivier.rechercher(db, criteres, page=page, page_size=page_size)

    # Filtrer sur un attribut protégé est légitime — un client peut poser la
    # condition — mais ce n'est pas une recherche ordinaire : elle laisse une
    # trace, comme les conditions restrictives d'un poste.
    sensibles = {
        cle: valeur
        for cle, valeur in (
            ("sexe", sexe.value if sexe else None),
            ("age_min", age_min),
            ("age_max", age_max),
            ("nationalite", nationalite or None),
        )
        if valeur is not None
    }
    if sensibles:
        await audit.record(
            db,
            action="vivier.recherche_sensible",
            entity_type="vivier",
            entity_id=None,
            user_id=user.id,
            details={"criteres": sensibles, "resultats": total},
        )
        await db.commit()

    return VivierPage(
        items=[_item(ligne) for ligne in lignes],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/vivier/{candidat_id}", response_model=ProfilVivier)
async def profil_vivier(candidat_id: str, db: DbSession, _: CurrentUser) -> ProfilVivier:
    """Tout ce que le cabinet sait d'une personne, fichiers ou non."""
    candidat = await vivier.charger(db, candidat_id)
    if candidat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profil introuvable")

    # Le résumé porte sur la personne, pas sur l'enregistrement demandé : si
    # elle a postulé trois fois, les trois dossiers sont réunis ici.
    resume = await vivier.resumer(db, candidat)
    representant = resume.candidat
    historique = await vivier.historique(db, resume.identifiants)

    return ProfilVivier(
        **_item(resume).model_dump(),
        adresse=representant.adresse,
        date_naissance=representant.date_naissance,
        langues=list(representant.langues or ()),
        certifications=list(representant.certifications or ()),
        diplomes=[
            DiplomeVivier(
                intitule=d.intitule,
                niveau=d.niveau,
                niveau_libelle=vivier.libelle_niveau(d.niveau),
                domaine=d.domaine,
                etablissement=d.etablissement,
                annee=d.annee,
                provenance=d.provenance,
            )
            for d in sorted(resume.diplomes, key=lambda d: d.niveau, reverse=True)
        ],
        experiences=[
            ExperienceVivier(
                poste=e.poste,
                employeur=e.employeur,
                debut=e.debut,
                fin=e.fin,
                domaines=list(e.domaines or ()),
                pays=e.pays,
                provenance=e.provenance,
            )
            for e in sorted(resume.experiences, key=lambda e: e.debut, reverse=True)
        ],
        historique=[HistoriqueVivier(**ligne) for ligne in historique],
    )
