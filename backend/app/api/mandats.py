"""Clients et mandats : l'amont de la chaîne.

Un mandat existe avant d'être gagné — il porte l'AMI et l'appel d'offre — puis
devient le cadre des postes à pourvoir. C'est le même enregistrement de bout en
bout, pour éviter de ressaisir le dossier une fois le marché attribué.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import CurrentUser, DbSession
from app.models import Client, Mandat, Poste, StatutMandat
from app.models.base import utcnow
from app.schemas.recrutement import (
    ClientCreate,
    ClientOut,
    ClientUpdate,
    MandatCreate,
    MandatOut,
    MandatUpdate,
)
from app.services import audit, espace_client, purge

router = APIRouter(tags=["mandats"])


async def get_client_or_404(db: AsyncSession, client_id: str) -> Client:
    client = await db.get(Client, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client introuvable")
    return client


async def get_mandat_or_404(db: AsyncSession, mandat_id: str) -> Mandat:
    mandat = await db.get(Mandat, mandat_id)
    if mandat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mandat introuvable")
    return mandat


# --- clients ----------------------------------------------------------------


@router.get("/clients", response_model=list[ClientOut])
async def lister_clients(
    db: DbSession,
    _: CurrentUser,
    recherche: str | None = Query(default=None),
    archives: bool = Query(default=False),
) -> list[ClientOut]:
    # Le comptage se fait en une jointure groupée plutôt qu'une requête par
    # client : la liste reste à deux requêtes quel que soit le nombre de lignes.
    requete = (
        select(Client, func.count(Mandat.id))
        .outerjoin(Mandat, Mandat.client_id == Client.id)
        .group_by(Client.id)
        .order_by(Client.nom)
    )
    if recherche:
        requete = requete.where(Client.nom.ilike(f"%{recherche}%"))
    if not archives:
        requete = requete.where(Client.archive_le.is_(None))

    lignes = await db.execute(requete)
    sortie = []
    for client, nombre in lignes:
        item = ClientOut.model_validate(client)
        item.nombre_mandats = nombre
        sortie.append(item)
    return sortie


@router.post("/clients", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
async def creer_client(payload: ClientCreate, db: DbSession, user: CurrentUser) -> ClientOut:
    client = Client(**payload.model_dump())
    db.add(client)
    await db.flush()
    await audit.record(
        db,
        action="client.create",
        entity_type="client",
        entity_id=client.id,
        user_id=user.id,
        details={"nom": client.nom},
    )
    await db.commit()
    await db.refresh(client)
    return ClientOut.model_validate(client)


@router.get("/clients/{client_id}", response_model=ClientOut)
async def lire_client(client_id: str, db: DbSession, _: CurrentUser) -> ClientOut:
    return ClientOut.model_validate(await get_client_or_404(db, client_id))


@router.patch("/clients/{client_id}", response_model=ClientOut)
async def modifier_client(
    client_id: str, payload: ClientUpdate, db: DbSession, user: CurrentUser
) -> ClientOut:
    client = await get_client_or_404(db, client_id)
    modifications = payload.model_dump(exclude_unset=True)
    for champ, valeur in modifications.items():
        setattr(client, champ, valeur)
    await audit.record(
        db,
        action="client.update",
        entity_type="client",
        entity_id=client.id,
        user_id=user.id,
        details={"champs": sorted(modifications)},
    )
    await db.commit()
    await db.refresh(client)
    return ClientOut.model_validate(client)


async def _compter_sous_arbre(db: AsyncSession, **filtre) -> dict[str, int]:
    """Ce qu'une suppression emporterait avec elle."""
    from app.models import Avis, Candidature

    if "client_id" in filtre:
        postes = select(Poste.id).join(Mandat, Mandat.id == Poste.mandat_id).where(
            Mandat.client_id == filtre["client_id"]
        )
        mandats = select(func.count(Mandat.id)).where(Mandat.client_id == filtre["client_id"])
    else:
        postes = select(Poste.id).where(Poste.mandat_id == filtre["mandat_id"])
        mandats = select(func.count(Mandat.id)).where(Mandat.id == filtre["mandat_id"])

    identifiants = list((await db.execute(postes)).scalars())
    candidatures = 0
    avis = 0
    if identifiants:
        candidatures = (
            await db.execute(
                select(func.count(Candidature.id)).where(Candidature.poste_id.in_(identifiants))
            )
        ).scalar_one()
        avis = (
            await db.execute(select(func.count(Avis.id)).where(Avis.poste_id.in_(identifiants)))
        ).scalar_one()

    return {
        "mandats": (await db.execute(mandats)).scalar_one(),
        "postes": len(identifiants),
        "avis": avis,
        "candidatures": candidatures,
    }


async def _purger_candidats_orphelins(db: AsyncSession) -> int:
    """Supprime les personnes qui ne portent plus aucune candidature.

    `Candidat` est volontairement distinct de `Candidature` pour qu'une même
    personne postulant à plusieurs postes reste un seul dossier. La contrepartie
    est qu'une suppression en cascade laisse derrière elle des états civils —
    nom, email, date de naissance, nationalité — sans plus aucune finalité.
    Les conserver serait une rétention de données personnelles sans objet ;
    celles rattachées à un autre poste, elles, ne bougent pas.
    """
    from app.models import Candidat, Candidature

    orphelins = (
        await db.execute(
            select(Candidat.id).where(
                ~select(Candidature.id)
                .where(Candidature.candidat_id == Candidat.id)
                .exists()
            )
        )
    ).scalars().all()
    for identifiant in orphelins:
        await db.execute(delete(Candidat).where(Candidat.id == identifiant))
    return len(orphelins)


def _exiger_archive(objet, quoi: str) -> None:
    """La suppression définitive passe obligatoirement par l'archive.

    Deux gestes valent mieux qu'un pour une action irréversible : on archive
    d'abord — ce qui n'efface rien et se défait —, et l'effacement ne se
    décide qu'ensuite, depuis la page des archives, à froid.
    """
    if objet.archive_le is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Archivez {quoi} avant de le supprimer. La suppression définitive ne se fait "
            "que depuis les archives.",
        )


def _refuser_si_dossiers(compte: dict[str, int], confirmer: bool) -> None:
    """Un dossier de candidature ne disparaît pas par inadvertance.

    Une erreur de saisie se supprime sans cérémonie ; un mandat qui a déjà reçu
    des candidatures emporte des données personnelles et du travail
    d'évaluation, donc il faut le demander explicitement.
    """
    if compte["candidatures"] and not confirmer:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cette suppression emporterait {compte['candidatures']} candidature(s), "
            f"{compte['postes']} poste(s) et {compte['avis']} avis. "
            "L'archivage conserve le dossier tout en le sortant des listes ; "
            "la suppression est définitive. "
            "Confirmez avec confirmer=true si c'est bien l'intention.",
        )


@router.delete("/clients/{client_id}", status_code=status.HTTP_200_OK)
async def supprimer_client(
    client_id: str,
    db: DbSession,
    user: CurrentUser,
    confirmer: bool = Query(default=False),
) -> dict:
    """Supprime un client et tout ce qui en dépend."""
    client = await get_client_or_404(db, client_id)
    _exiger_archive(client, "ce client")
    compte = await _compter_sous_arbre(db, client_id=client_id)
    _refuser_si_dossiers(compte, confirmer)

    await audit.record(
        db,
        action="client.delete",
        entity_type="client",
        entity_id=client.id,
        user_id=user.id,
        details={"nom": client.nom, **compte},
    )
    await db.delete(client)
    await db.flush()
    compte["candidats_supprimes"] = await _purger_candidats_orphelins(db)
    await db.commit()
    return {"supprime": client.nom, **compte}


# --- mandats ----------------------------------------------------------------


@router.get("/mandats", response_model=list[MandatOut])
async def lister_mandats(
    db: DbSession,
    _: CurrentUser,
    statut: StatutMandat | None = Query(default=None),
    client_id: str | None = Query(default=None),
    archives: bool = Query(default=False),
) -> list[MandatOut]:
    requete = (
        select(Mandat, Client.nom, func.count(Poste.id))
        .join(Client, Client.id == Mandat.client_id)
        .outerjoin(Poste, Poste.mandat_id == Mandat.id)
        .group_by(Mandat.id, Client.nom)
        .order_by(Mandat.created_at.desc())
    )
    if statut is not None:
        requete = requete.where(Mandat.statut == statut)
    if client_id:
        requete = requete.where(Mandat.client_id == client_id)
    # Les archives sortent des listes sans disparaître : elles restent
    # consultables à la demande, et par leur lien direct.
    if not archives:
        requete = requete.where(Mandat.archive_le.is_(None))

    sortie = []
    for mandat, client_nom, nombre in await db.execute(requete):
        item = MandatOut.model_validate(mandat)
        item.client_nom = client_nom
        item.nombre_postes = nombre
        sortie.append(item)
    return sortie


@router.post("/mandats", response_model=MandatOut, status_code=status.HTTP_201_CREATED)
async def creer_mandat(payload: MandatCreate, db: DbSession, user: CurrentUser) -> MandatOut:
    client = await get_client_or_404(db, payload.client_id)
    mandat = Mandat(**payload.model_dump())
    db.add(mandat)
    await db.flush()
    await audit.record(
        db,
        action="mandat.create",
        entity_type="mandat",
        entity_id=mandat.id,
        user_id=user.id,
        details={"intitule": mandat.intitule, "client": client.nom},
    )
    await db.commit()
    await db.refresh(mandat)
    sortie = MandatOut.model_validate(mandat)
    sortie.client_nom = client.nom
    return sortie


@router.get("/mandats/{mandat_id}", response_model=MandatOut)
async def lire_mandat(mandat_id: str, db: DbSession, _: CurrentUser) -> MandatOut:
    mandat = await get_mandat_or_404(db, mandat_id)
    client = await db.get(Client, mandat.client_id)
    sortie = MandatOut.model_validate(mandat)
    sortie.client_nom = client.nom if client else None
    nombre = await db.execute(
        select(func.count(Poste.id)).where(Poste.mandat_id == mandat.id)
    )
    sortie.nombre_postes = nombre.scalar_one()
    return sortie


@router.patch("/mandats/{mandat_id}", response_model=MandatOut)
async def modifier_mandat(
    mandat_id: str, payload: MandatUpdate, db: DbSession, user: CurrentUser
) -> MandatOut:
    mandat = await get_mandat_or_404(db, mandat_id)
    modifications = payload.model_dump(exclude_unset=True)
    ancien_statut = mandat.statut
    for champ, valeur in modifications.items():
        setattr(mandat, champ, valeur)

    details: dict = {"champs": sorted(modifications)}
    if "statut" in modifications and mandat.statut != ancien_statut:
        details["statut"] = f"{ancien_statut.value} -> {mandat.statut.value}"
        if not espace_client.mandat_ouvert(mandat):
            # L'espace de suivi vit le temps du recrutement : le clore ferme la
            # porte au lieu de la laisser ouverte « au cas où ».
            fermes = await espace_client.fermer_ceux_du_mandat(
                db, mandat, f"Mandat passé au statut {mandat.statut.value}"
            )
            if fermes:
                details["acces_client_fermes"] = fermes
    await audit.record(
        db,
        action="mandat.update",
        entity_type="mandat",
        entity_id=mandat.id,
        user_id=user.id,
        details=details,
    )
    await db.commit()
    await db.refresh(mandat)
    return MandatOut.model_validate(mandat)


@router.delete("/mandats/{mandat_id}", status_code=status.HTTP_200_OK)
async def supprimer_mandat(
    mandat_id: str,
    db: DbSession,
    user: CurrentUser,
    confirmer: bool = Query(default=False),
) -> dict:
    """Supprime un mandat, ses postes, ses avis et leurs candidatures."""
    mandat = await get_mandat_or_404(db, mandat_id)
    _exiger_archive(mandat, "ce mandat")
    compte = await _compter_sous_arbre(db, mandat_id=mandat_id)
    _refuser_si_dossiers(compte, confirmer)

    await audit.record(
        db,
        action="mandat.delete",
        entity_type="mandat",
        entity_id=mandat.id,
        user_id=user.id,
        details={"intitule": mandat.intitule, **compte},
    )
    await db.delete(mandat)
    await db.flush()
    compte["candidats_supprimes"] = await _purger_candidats_orphelins(db)
    await db.commit()
    return {"supprime": mandat.intitule, **compte}


# --- archivage ---------------------------------------------------------------


async def _basculer_archive(
    db: AsyncSession, objet, *, archiver: bool, entite: str, nom: str, user_id: str
) -> dict:
    """Archiver n'efface rien : avis, grilles et dossiers restent lisibles.

    C'est le geste normal pour un mandat terminé ou abandonné ; la suppression
    reste réservée aux saisies erronées, où il n'y a rien à conserver.
    """
    objet.archive_le = utcnow() if archiver else None
    if archiver and isinstance(objet, Mandat):
        await espace_client.fermer_ceux_du_mandat(db, objet, "Mandat archivé")
    await audit.record(
        db,
        action=f"{entite}.{'archive' if archiver else 'desarchive'}",
        entity_type=entite,
        entity_id=objet.id,
        user_id=user_id,
        details={"nom": nom},
    )
    await db.commit()
    return {"archive": archiver, "nom": nom}


@router.post("/clients/{client_id}/archiver")
async def archiver_client(client_id: str, db: DbSession, user: CurrentUser) -> dict:
    client = await get_client_or_404(db, client_id)
    return await _basculer_archive(
        db, client, archiver=True, entite="client", nom=client.nom, user_id=user.id
    )


@router.post("/clients/{client_id}/desarchiver")
async def desarchiver_client(client_id: str, db: DbSession, user: CurrentUser) -> dict:
    client = await get_client_or_404(db, client_id)
    return await _basculer_archive(
        db, client, archiver=False, entite="client", nom=client.nom, user_id=user.id
    )


@router.post("/mandats/{mandat_id}/archiver")
async def archiver_mandat(mandat_id: str, db: DbSession, user: CurrentUser) -> dict:
    mandat = await get_mandat_or_404(db, mandat_id)
    return await _basculer_archive(
        db, mandat, archiver=True, entite="mandat", nom=mandat.intitule, user_id=user.id
    )


@router.post("/mandats/{mandat_id}/desarchiver")
async def desarchiver_mandat(mandat_id: str, db: DbSession, user: CurrentUser) -> dict:
    mandat = await get_mandat_or_404(db, mandat_id)
    return await _basculer_archive(
        db, mandat, archiver=False, entite="mandat", nom=mandat.intitule, user_id=user.id
    )


# --- purge des fichiers -------------------------------------------------------


@router.get("/mandats/{mandat_id}/purge")
async def estimer_purge(mandat_id: str, db: DbSession, _: CurrentUser) -> dict:
    """Ce qu'une purge libérerait, sans rien supprimer."""
    await get_mandat_or_404(db, mandat_id)
    estimation = await purge.estimer(db, mandat_id)
    return {
        "fichiers": estimation.fichiers,
        "mo": estimation.mo,
        "candidatures": estimation.candidatures,
    }


@router.post("/mandats/{mandat_id}/purge")
async def purger(mandat_id: str, db: DbSession, user: CurrentUser) -> dict:
    """Supprime les fichiers d'un mandat archivé, garde les dossiers.

    Réservé aux mandats archivés : tant que le recrutement est en cours, les
    pièces servent encore — relire un CV, vérifier une donnée extraite,
    répondre à un candidat qui conteste.
    """
    mandat = await purge.mandat_purgeable(db, mandat_id)
    if mandat is None:
        await get_mandat_or_404(db, mandat_id)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Archivez le mandat avant de purger ses fichiers : tant qu'il est en cours, "
            "les pièces peuvent encore être consultées.",
        )

    resultat = await purge.purger_mandat(db, mandat_id)
    await audit.record(
        db,
        action="mandat.purge",
        entity_type="mandat",
        entity_id=mandat.id,
        user_id=user.id,
        details={
            "intitule": mandat.intitule,
            "fichiers": resultat.fichiers,
            "mo": resultat.mo,
        },
    )
    await db.commit()
    return {
        "fichiers": resultat.fichiers,
        "mo": resultat.mo,
        "candidatures": resultat.candidatures,
    }
