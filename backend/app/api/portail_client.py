"""L'espace du promoteur : ce que le client voit de son recrutement.

Porte séparée de celle du cabinet, jusque dans le type de jeton. Un accès
client ne peut atteindre aucune route interne, et aucune route d'ici ne consulte
un mandat autre que le sien.

**Ce que le client ne voit pas**, et c'est le point le plus important de ce
fichier : ni nom de candidat, ni note, ni motif d'élimination, ni pièce de
dossier. La confidentialité des candidatures est due aux candidats, pas au
commanditaire ; un promoteur qui suit l'avancement n'a pas à savoir qui a
postulé ni qui a été écarté. Ce qu'il obtient : où en est le recrutement, en
gros, et de quoi écrire à son interlocuteur.

L'avancement est délibérément vague — un chronogramme d'étapes, un état par
poste. Il renseigne sans exposer, et il reste juste même quand le dossier prend
un chemin imprévu.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import client_ip
from app.models import (
    AccesClient,
    AuteurEchange,
    Avis,
    Candidature,
    EchangeClient,
    EtapeMandat,
    Mandat,
    Poste,
    Rapport,
    StatutAvis,
    StatutCandidature,
    StatutRapport,
    TypeEchange,
)
from app.models.base import utcnow
from app.security import create_client_token, decode_token
from app.services import espace_client
from app.services.ratelimit import public_limiter

router = APIRouter(prefix="/espace-client", tags=["espace-client"])

bearer = HTTPBearer(auto_error=False)
DbSession = Annotated[AsyncSession, Depends(get_db)]


# --- authentification -------------------------------------------------------


async def acces_courant(
    db: DbSession,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> AccesClient:
    """Le promoteur derrière la requête, revérifié en base à chaque appel.

    Le jeton porte déjà le mandat, mais s'y fier seul laisserait un accès
    révoqué fonctionner jusqu'à l'expiration de son jeton. Une clôture doit
    fermer la porte immédiatement.
    """
    if creds is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Authentification requise",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        charge = decode_token(creds.credentials, "client")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expirée") from None
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Jeton invalide") from None

    acces = await db.get(AccesClient, charge["sub"])
    if acces is None or acces.active_le is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Accès fermé")
    if acces.revoque_le is not None:
        # 403 et non 401 : le jeton est authentique, c'est l'accès qui a pris
        # fin. Le dire ainsi évite au promoteur de croire qu'il s'est trompé de
        # mot de passe et de recommencer.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            acces.motif_revocation
            or "Cet espace de suivi a été fermé. Contactez votre interlocuteur.",
        )

    mandat = await db.get(Mandat, acces.mandat_id)
    if mandat is None or not espace_client.mandat_ouvert(mandat):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Ce recrutement est clos : votre espace de suivi n'est plus actif.",
        )
    return acces


AccesCourant = Annotated[AccesClient, Depends(acces_courant)]


class ConnexionIn(BaseModel):
    email: EmailStr
    mot_de_passe: str = Field(min_length=1)


class ActivationIn(BaseModel):
    jeton: str = Field(min_length=1)
    mot_de_passe: str = Field(min_length=espace_client.LONGUEUR_MOT_DE_PASSE)


class SessionOut(BaseModel):
    token: str
    nom: str
    email: str
    mandat: str
    client: str


class InvitationOut(BaseModel):
    """Ce qu'on montre avant d'avoir un mot de passe : juste de quoi se situer."""

    nom: str
    email: str
    mandat: str
    client: str


async def _session(db: AsyncSession, acces: AccesClient) -> SessionOut:
    mandat = (
        await db.execute(
            select(Mandat)
            .where(Mandat.id == acces.mandat_id)
            .options(selectinload(Mandat.client))
        )
    ).scalar_one()
    return SessionOut(
        token=create_client_token(acces.id, acces.mandat_id),
        nom=acces.nom,
        email=acces.email,
        mandat=mandat.intitule,
        client=mandat.client.nom if mandat.client else "",
    )


@router.get("/activation/{jeton}", response_model=InvitationOut)
async def verifier_lien(jeton: str, db: DbSession) -> InvitationOut:
    """Avant de demander un mot de passe, on montre à qui le lien appartient."""
    try:
        acces = await espace_client.par_jeton(db, jeton)
    except espace_client.ErreurAcces as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    mandat = (
        await db.execute(
            select(Mandat)
            .where(Mandat.id == acces.mandat_id)
            .options(selectinload(Mandat.client))
        )
    ).scalar_one()
    return InvitationOut(
        nom=acces.nom,
        email=acces.email,
        mandat=mandat.intitule,
        client=mandat.client.nom if mandat.client else "",
    )


@router.post("/activation", response_model=SessionOut)
async def activer(donnees: ActivationIn, request: Request, db: DbSession) -> SessionOut:
    public_limiter.check(client_ip(request))
    try:
        acces = await espace_client.activer(db, donnees.jeton, donnees.mot_de_passe)
    except espace_client.ErreurAcces as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    sortie = await _session(db, acces)
    await db.commit()
    return sortie


@router.post("/connexion", response_model=SessionOut)
async def connexion(donnees: ConnexionIn, request: Request, db: DbSession) -> SessionOut:
    # Route non authentifiée : sans limitation, elle se prête aux essais
    # successifs de mots de passe.
    public_limiter.check(client_ip(request))
    try:
        acces = await espace_client.authentifier(
            db, str(donnees.email), donnees.mot_de_passe
        )
    except espace_client.ErreurAcces as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    mandat = await db.get(Mandat, acces.mandat_id)
    if mandat is None or not espace_client.mandat_ouvert(mandat):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Ce recrutement est clos : votre espace de suivi n'est plus actif.",
        )
    sortie = await _session(db, acces)
    await db.commit()
    return sortie


# --- suivi ------------------------------------------------------------------


class EtapeVue(BaseModel):
    libelle: str
    etat: str
    date_prevue: date | None


class PosteVue(BaseModel):
    intitule: str
    nombre_a_pourvoir: int
    # Volontairement grossier : « publié », « candidatures reçues »,
    # « présélection en cours », « entretiens », « terminé ». Aucun chiffre de
    # dossier, aucun nom.
    avancement: str
    avis_publie_le: date | None
    date_cloture: date | None


class SuiviOut(BaseModel):
    mandat: str
    reference: str | None
    client: str
    etapes: list[EtapeVue]
    postes: list[PosteVue]
    messages_non_lus: int
    rapports_disponibles: int


def _avancement(
    poste: Poste, avis: Avis | None, statuts: dict[str, int]
) -> str:
    """Une phrase, pas un tableau de bord.

    Le client a demandé à savoir où en est son recrutement. Répondre par des
    effectifs de dossiers reviendrait à lui livrer, tranche par tranche, une
    information qui appartient aux candidats — et à l'exposer aux comparaisons
    (« seulement quatre candidats ? ») que le cabinet est seul à savoir situer.
    """
    if statuts.get(StatutCandidature.RETENUE.value):
        return "Recrutement finalisé"
    if statuts.get(StatutCandidature.PRESELECTIONNEE.value):
        return "Entretiens en cours"
    if avis is not None and avis.statut is StatutAvis.CLOTURE:
        return "Présélection en cours"
    if sum(statuts.values()):
        return "Réception des candidatures"
    if avis is not None and avis.statut is StatutAvis.PUBLIE:
        return "Avis publié"
    return "En préparation"


@router.get("/suivi", response_model=SuiviOut)
async def suivi(acces: AccesCourant, db: DbSession) -> SuiviOut:
    mandat = (
        await db.execute(
            select(Mandat)
            .where(Mandat.id == acces.mandat_id)
            .options(
                selectinload(Mandat.client),
                selectinload(Mandat.postes).selectinload(Poste.avis),
            )
        )
    ).scalar_one()

    # Un seul décompte pour tout le mandat, groupé par poste et par statut.
    lignes = await db.execute(
        select(Candidature.poste_id, Candidature.statut, func.count(Candidature.id))
        .join(Poste, Poste.id == Candidature.poste_id)
        .where(Poste.mandat_id == mandat.id)
        .group_by(Candidature.poste_id, Candidature.statut)
    )
    par_poste: dict[str, dict[str, int]] = {}
    for poste_id, statut, compte in lignes:
        valeur = statut.value if hasattr(statut, "value") else str(statut)
        par_poste.setdefault(poste_id, {})[valeur] = compte

    etapes = (
        await db.execute(
            select(EtapeMandat)
            .where(EtapeMandat.mandat_id == mandat.id, EtapeMandat.visible_client.is_(True))
            .order_by(EtapeMandat.ordre)
        )
    ).scalars().all()

    non_lus = (
        await db.execute(
            select(func.count(EchangeClient.id)).where(
                EchangeClient.mandat_id == mandat.id,
                EchangeClient.auteur == AuteurEchange.CABINET,
                EchangeClient.lu_le.is_(None),
            )
        )
    ).scalar_one()

    rapports = (
        await db.execute(
            select(func.count(Rapport.id)).where(
                Rapport.mandat_id == mandat.id,
                Rapport.partage_le.is_not(None),
                Rapport.statut == StatutRapport.VALIDE,
            )
        )
    ).scalar_one()

    postes = []
    for poste in mandat.postes:
        avis = poste.avis[0] if poste.avis else None
        postes.append(
            PosteVue(
                intitule=poste.intitule,
                nombre_a_pourvoir=poste.nombre_a_pourvoir,
                avancement=_avancement(poste, avis, par_poste.get(poste.id, {})),
                avis_publie_le=avis.date_publication if avis else None,
                date_cloture=avis.date_cloture if avis else None,
            )
        )

    return SuiviOut(
        mandat=mandat.intitule,
        reference=mandat.reference,
        client=mandat.client.nom if mandat.client else "",
        etapes=[
            EtapeVue(libelle=e.libelle, etat=e.etat.value, date_prevue=e.date_prevue)
            for e in etapes
        ],
        postes=postes,
        messages_non_lus=int(non_lus or 0),
        rapports_disponibles=int(rapports or 0),
    )


# --- échanges ---------------------------------------------------------------


class MessageClientIn(BaseModel):
    corps: str = Field(min_length=1, max_length=10000)
    objet: str | None = Field(default=None, max_length=500)
    # Une demande de modification est suivie jusqu'à son traitement, là où un
    # simple message se lit et se classe.
    demande_modification: bool = False


class MessageVue(BaseModel):
    id: str
    auteur: str
    auteur_nom: str
    type_echange: str
    objet: str | None
    corps: str
    envoye_le: datetime
    traite_le: datetime | None


@router.get("/messages", response_model=list[MessageVue])
async def lire_messages(acces: AccesCourant, db: DbSession) -> list[MessageVue]:
    lignes = (
        await db.execute(
            select(EchangeClient)
            .where(EchangeClient.mandat_id == acces.mandat_id)
            .order_by(EchangeClient.envoye_le)
        )
    ).scalars().all()

    # Lire le fil marque comme lus les messages du cabinet : le compteur de
    # l'écran d'accueil doit refléter ce qui reste à voir, pas ce qui existe.
    maintenant = utcnow()
    for ligne in lignes:
        if ligne.auteur is AuteurEchange.CABINET and ligne.lu_le is None:
            ligne.lu_le = maintenant
    await db.commit()

    return [
        MessageVue(
            id=ligne.id,
            auteur=ligne.auteur.value,
            auteur_nom=ligne.auteur_nom,
            type_echange=ligne.type_echange.value,
            objet=ligne.objet,
            corps=ligne.corps,
            envoye_le=ligne.envoye_le,
            traite_le=ligne.traite_le,
        )
        for ligne in lignes
    ]


@router.post(
    "/messages", response_model=MessageVue, status_code=status.HTTP_201_CREATED
)
async def ecrire_message(
    donnees: MessageClientIn, acces: AccesCourant, db: DbSession
) -> MessageVue:
    echange = EchangeClient(
        mandat_id=acces.mandat_id,
        auteur=AuteurEchange.CLIENT,
        auteur_nom=acces.nom,
        type_echange=(
            TypeEchange.DEMANDE_MODIFICATION
            if donnees.demande_modification
            else TypeEchange.MESSAGE
        ),
        objet=donnees.objet,
        corps=donnees.corps,
    )
    db.add(echange)
    await db.commit()
    return MessageVue(
        id=echange.id,
        auteur=echange.auteur.value,
        auteur_nom=echange.auteur_nom,
        type_echange=echange.type_echange.value,
        objet=echange.objet,
        corps=echange.corps,
        envoye_le=echange.envoye_le,
        traite_le=None,
    )


# --- rapports partagés ------------------------------------------------------


class RapportVue(BaseModel):
    id: str
    titre: str
    partage_le: datetime | None


@router.get("/rapports", response_model=list[RapportVue])
async def lister_rapports(acces: AccesCourant, db: DbSession) -> list[RapportVue]:
    """Seuls les rapports validés *et* explicitement partagés apparaissent.

    Deux conditions plutôt qu'une : un rapport peut être validé en interne sans
    être encore le bon moment pour le remettre.
    """
    lignes = (
        await db.execute(
            select(Rapport)
            .where(
                Rapport.mandat_id == acces.mandat_id,
                Rapport.statut == StatutRapport.VALIDE,
                Rapport.partage_le.is_not(None),
            )
            .order_by(Rapport.partage_le.desc())
        )
    ).scalars().all()
    return [
        RapportVue(id=r.id, titre=r.titre, partage_le=r.partage_le) for r in lignes
    ]
