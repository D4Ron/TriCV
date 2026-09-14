"""Côté cabinet : écrire aux candidats, ouvrir et tenir l'espace du promoteur.

Ce routeur est celui des RH. Il ouvre un accès client, publie le chronogramme,
répond aux demandes du promoteur, et envoie les courriels aux candidats.

Une règle traverse tout le fichier : **rien ne part sans avoir été relu**. Les
routes de préparation (`/apercu`) rendent le texte rédigé sans rien expédier ;
les routes d'envoi prennent le texte qu'on leur donne. Un courriel ne se
rattrape pas, et un modèle bien écrit reste faux sur un cas particulier.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.mandats import get_mandat_or_404
from app.deps import CurrentUser, DbSession
from app.domain.referentiel import PieceDossier
from app.models import (
    AccesClient,
    AuteurEchange,
    Candidature,
    EchangeClient,
    EtapeMandat,
    EtatEtape,
    Mandat,
    MessageEnvoye,
    Poste,
    StatutEnvoi,
    TypeEchange,
)
from app.models.base import utcnow
from app.services import audit, espace_client, messagerie, parametres

router = APIRouter(tags=["collaboration"])


# --- schémas ----------------------------------------------------------------


class ModeleOut(BaseModel):
    code: str
    libelle: str
    description: str
    sujet: str
    corps: str
    variables: list[str]
    # CANDIDAT ou CLIENT : l'écran des candidatures ne propose que les premiers.
    destinataire: str


class ApercuIn(BaseModel):
    modele: str
    candidature_ids: list[str] = Field(min_length=1)
    # Ce que le modèle ne peut pas deviner : date d'entretien, lieu, signature.
    valeurs: dict[str, str] = Field(default_factory=dict)


class MessagePrepare(BaseModel):
    candidature_id: str
    destinataire: str
    nom: str
    sujet: str
    corps: str
    # Variables restées sans valeur : le message part avec un « {lieu} » visible
    # si personne ne s'en occupe, ce qu'il vaut mieux signaler avant.
    variables_manquantes: list[str] = Field(default_factory=list)


class EnvoiIn(BaseModel):
    """Un envoi porte le texte relu, pas un code de modèle.

    C'est délibéré : ce qui part est ce qui a été montré. Reconstruire le
    message côté serveur au moment de l'envoi rouvrirait l'écart entre le texte
    validé et le texte expédié.
    """

    modele: str | None = None
    messages: list["EnvoiMessage"] = Field(min_length=1)


class EnvoiMessage(BaseModel):
    candidature_id: str
    destinataire: EmailStr
    sujet: str = Field(min_length=1, max_length=500)
    corps: str = Field(min_length=1)


class ResultatEnvoi(BaseModel):
    envoyes: int
    echecs: int
    details: list[dict]


class MessageEnvoyeOut(BaseModel):
    id: str
    destinataire: str
    sujet: str
    corps: str
    modele: str | None
    statut: str
    erreur: str | None
    envoye_le: datetime

    model_config = {"from_attributes": True}


class AccesIn(BaseModel):
    email: EmailStr
    nom: str = Field(min_length=1, max_length=255)
    fonction: str | None = Field(default=None, max_length=255)
    # L'envoi du courriel est séparé de la création : une installation sans
    # serveur d'envoi doit tout de même pouvoir ouvrir l'accès, quitte à ce que
    # le lien soit transmis à la main.
    envoyer_courriel: bool = True


class AccesOut(BaseModel):
    id: str
    mandat_id: str
    email: str
    nom: str
    fonction: str | None
    active_le: datetime | None
    dernier_acces_le: datetime | None
    revoque_le: datetime | None
    motif_revocation: str | None
    # Rendu une seule fois, à la création : il n'est jamais relu depuis la base
    # (il y est, mais l'exposer en liste ferait de chaque écran une distribution
    # de clés).
    lien_activation: str | None = None
    courriel_envoye: bool | None = None
    avertissement: str | None = None

    model_config = {"from_attributes": True}


class EtapeIn(BaseModel):
    libelle: str = Field(min_length=1, max_length=255)
    etat: EtatEtape = EtatEtape.A_VENIR
    date_prevue: date | None = None
    date_reelle: date | None = None
    visible_client: bool = True


class EtapeOut(EtapeIn):
    id: str
    ordre: int

    model_config = {"from_attributes": True}


class EchangeIn(BaseModel):
    corps: str = Field(min_length=1)
    objet: str | None = Field(default=None, max_length=500)
    poste_id: str | None = None
    type_echange: TypeEchange = TypeEchange.MESSAGE


class EchangeOut(BaseModel):
    id: str
    mandat_id: str
    poste_id: str | None
    auteur: str
    auteur_nom: str
    type_echange: str
    objet: str | None
    corps: str
    envoye_le: datetime
    lu_le: datetime | None
    traite_le: datetime | None

    model_config = {"from_attributes": True}


EnvoiIn.model_rebuild()


# --- modèles de courriel ----------------------------------------------------


@router.get("/messagerie/modeles", response_model=list[ModeleOut])
async def lister_modeles(
    _: CurrentUser, destinataire: str | None = Query(default=None)
) -> list[ModeleOut]:
    """Les modèles disponibles, filtrables par destinataire."""
    return [
        ModeleOut(
            code=m.code,
            libelle=m.libelle,
            description=m.description,
            sujet=m.sujet,
            corps=m.corps,
            destinataire=m.destinataire,
            variables=sorted(
                messagerie.variables_utilisees(m.sujet)
                | messagerie.variables_utilisees(m.corps)
            ),
        )
        for m in messagerie.MODELES
        if destinataire is None or m.destinataire == destinataire
    ]


def _libelle(code: str) -> str:
    try:
        return PieceDossier(code).libelle
    except ValueError:
        return code


async def _contexte(db: AsyncSession, candidature: Candidature) -> dict[str, object]:
    """Ce qu'un modèle peut nommer, pour une candidature donnée."""
    candidat = candidature.candidat
    poste = candidature.poste
    mandat = poste.mandat if poste is not None else None

    fournies = {p.type_piece for p in candidature.pieces}
    requises = list(poste.pieces_requises or ()) if poste is not None else []
    # Nommées par leur libellé : « CNI » dans un courriel à un candidat n'a de
    # sens que pour qui connaît le référentiel interne.
    manquantes = [_libelle(c) for c in requises if c not in fournies]

    return {
        "nom": f"{candidat.nom.upper()} {candidat.prenom}".strip(),
        "nom_famille": candidat.nom.upper(),
        "prenom": candidat.prenom,
        "email": candidat.email or "",
        "poste": poste.intitule if poste is not None else "",
        "client": mandat.client.nom if mandat is not None and mandat.client else "",
        "mandat": mandat.intitule if mandat is not None else "",
        "reference": mandat.reference if mandat is not None else "",
        "pieces_manquantes": "\n".join(f"— {c}" for c in manquantes),
        "date_du_jour": utcnow().strftime("%d/%m/%Y"),
    }


async def _candidatures(db: AsyncSession, identifiants: list[str]) -> list[Candidature]:
    lignes = (
        await db.execute(
            select(Candidature)
            .where(Candidature.id.in_(identifiants))
            .options(
                selectinload(Candidature.candidat),
                selectinload(Candidature.pieces),
                selectinload(Candidature.poste)
                .selectinload(Poste.mandat)
                .selectinload(Mandat.client),
            )
        )
    ).scalars().all()
    if not lignes:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucune candidature trouvée.")
    return list(lignes)


@router.post("/messagerie/apercu", response_model=list[MessagePrepare])
async def apercu_messages(
    donnees: ApercuIn, db: DbSession, _: CurrentUser
) -> list[MessagePrepare]:
    """Les messages tels qu'ils partiraient. Rien n'est envoyé."""
    try:
        gabarit = messagerie.modele(donnees.modele)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if gabarit.destinataire != "CANDIDAT":
        # Envoyer à un candidat le message d'accès destiné au commanditaire lui
        # livrerait un lien vers l'espace de suivi du mandat.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"« {gabarit.libelle} » ne s'adresse pas à un candidat.",
        )

    attendues = messagerie.variables_utilisees(gabarit.sujet) | messagerie.variables_utilisees(
        gabarit.corps
    )
    sortie = []
    for candidature in await _candidatures(db, donnees.candidature_ids):
        valeurs = await _contexte(db, candidature)
        valeurs.update({k: v for k, v in donnees.valeurs.items() if v})
        message = messagerie.preparer(
            donnees.modele,
            candidature.candidat.email or "",
            valeurs,
            nom_destinataire=str(valeurs["nom"]),
        )
        manquantes = sorted(
            v for v in attendues if not str(valeurs.get(v) or "").strip()
        )
        sortie.append(
            MessagePrepare(
                candidature_id=candidature.id,
                destinataire=message.destinataire,
                nom=str(valeurs["nom"]),
                sujet=message.sujet,
                corps=message.corps,
                variables_manquantes=manquantes,
            )
        )
    return sortie


@router.post("/messagerie/envoyer", response_model=ResultatEnvoi)
async def envoyer_messages(
    donnees: EnvoiIn, db: DbSession, user: CurrentUser
) -> ResultatEnvoi:
    """Expédie des messages déjà relus, un par candidature.

    Un échec n'interrompt pas la série : sur trente convocations, la seule
    adresse invalide ne doit pas empêcher les vingt-neuf autres de partir. Les
    échecs sont rendus en clair, avec leur motif, pour être repris à la main.
    """
    reglages = await parametres.lire(db)
    if not reglages.envoi_utilisable:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "L'envoi de courriels n'est pas configuré. Renseignez le serveur "
            "d'envoi dans Paramètres › Courriel.",
        )

    envoyes = 0
    echecs = 0
    details: list[dict] = []
    for element in donnees.messages:
        message = messagerie.Message(
            destinataire=str(element.destinataire),
            sujet=element.sujet,
            corps=element.corps,
        )
        trace = MessageEnvoye(
            candidature_id=element.candidature_id,
            modele=donnees.modele,
            destinataire=str(element.destinataire),
            sujet=element.sujet,
            corps=element.corps,
            envoye_par_id=user.id,
        )
        try:
            await messagerie.envoyer(message, reglages, nom_expediteur="Kapi Consult")
            trace.statut = StatutEnvoi.ENVOYE
            envoyes += 1
            details.append({"candidature_id": element.candidature_id, "ok": True})
        except messagerie.ErreurEnvoi as exc:
            trace.statut = StatutEnvoi.ECHEC
            trace.erreur = str(exc)
            echecs += 1
            details.append(
                {
                    "candidature_id": element.candidature_id,
                    "ok": False,
                    "erreur": str(exc),
                }
            )
        db.add(trace)

    await audit.record(
        db,
        action="messagerie.envoyer",
        entity_type="messagerie",
        entity_id=None,
        user_id=user.id,
        details={"modele": donnees.modele, "envoyes": envoyes, "echecs": echecs},
    )
    await db.commit()
    return ResultatEnvoi(envoyes=envoyes, echecs=echecs, details=details)


@router.get(
    "/candidatures/{candidature_id}/messages", response_model=list[MessageEnvoyeOut]
)
async def historique_messages(
    candidature_id: str, db: DbSession, _: CurrentUser
) -> list[MessageEnvoyeOut]:
    """Ce qui a été écrit à ce candidat. Vaut preuve d'envoi."""
    lignes = (
        await db.execute(
            select(MessageEnvoye)
            .where(MessageEnvoye.candidature_id == candidature_id)
            .order_by(MessageEnvoye.envoye_le.desc())
        )
    ).scalars().all()
    return [MessageEnvoyeOut.model_validate(m) for m in lignes]


@router.post("/messagerie/test")
async def tester_envoi(db: DbSession, user: CurrentUser) -> dict:
    """Ouvre une session SMTP sans rien envoyer.

    À utiliser au branchement : une erreur d'identifiants doit se découvrir ici,
    pas au moment où trente convocations partent.
    """
    reglages = await parametres.lire(db)
    try:
        await messagerie.verifier(reglages)
    except messagerie.ErreurEnvoi as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return {"ok": True, "expediteur": reglages.expediteur}


# --- accès du promoteur -----------------------------------------------------


@router.get("/mandats/{mandat_id}/acces", response_model=list[AccesOut])
async def lister_acces(mandat_id: str, db: DbSession, _: CurrentUser) -> list[AccesOut]:
    lignes = (
        await db.execute(
            select(AccesClient)
            .where(AccesClient.mandat_id == mandat_id)
            .order_by(AccesClient.created_at)
        )
    ).scalars().all()
    return [AccesOut.model_validate(a) for a in lignes]


@router.post(
    "/mandats/{mandat_id}/acces",
    response_model=AccesOut,
    status_code=status.HTTP_201_CREATED,
)
async def ouvrir_acces(
    mandat_id: str, donnees: AccesIn, db: DbSession, user: CurrentUser
) -> AccesOut:
    """Ouvre l'espace de suivi à un interlocuteur du client.

    Le lien d'activation n'est rendu qu'ici, une fois. Si l'envoi automatique
    échoue — serveur non configuré, adresse refusée — il reste affichable pour
    être transmis autrement : mieux vaut un lien copié à la main qu'un accès
    créé que personne ne peut utiliser.
    """
    mandat = await get_mandat_or_404(db, mandat_id)
    if not espace_client.mandat_ouvert(mandat):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ce mandat est clos ou archivé : son espace de suivi ne peut plus "
            "être ouvert.",
        )

    reglages = await parametres.lire(db)
    try:
        invitation = await espace_client.ouvrir(
            db,
            mandat,
            email=str(donnees.email),
            nom=donnees.nom,
            fonction=donnees.fonction,
            url_publique=reglages.url_publique,
        )
    except espace_client.ErreurAcces as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    avertissement = None
    if not invitation.lien:
        avertissement = (
            "L'adresse publique de l'application n'est pas renseignée "
            "(Paramètres › Envoi de courriels) : le lien d'activation ne peut "
            "pas être construit. L'accès existe, mais personne ne peut encore "
            "l'activer."
        )

    courriel_envoye = False
    if donnees.envoyer_courriel and invitation.lien:
        if not reglages.envoi_utilisable:
            avertissement = (
                "L'envoi de courriels n'est pas configuré : transmettez le lien "
                "d'activation vous-même."
            )
        else:
            message = messagerie.preparer(
                "ACCES_CLIENT",
                str(donnees.email),
                {
                    "nom": donnees.nom,
                    "mandat": mandat.intitule,
                    "lien_activation": invitation.lien,
                    "expiration": invitation.expire_le,
                    "signature": user.full_name,
                },
                nom_destinataire=donnees.nom,
            )
            trace = MessageEnvoye(
                mandat_id=mandat.id,
                modele="ACCES_CLIENT",
                destinataire=str(donnees.email),
                sujet=message.sujet,
                corps=message.corps,
                envoye_par_id=user.id,
            )
            try:
                await messagerie.envoyer(message, reglages, nom_expediteur="Kapi Consult")
                trace.statut = StatutEnvoi.ENVOYE
                courriel_envoye = True
            except messagerie.ErreurEnvoi as exc:
                trace.statut = StatutEnvoi.ECHEC
                trace.erreur = str(exc)
                avertissement = (
                    f"{exc} Le lien reste affiché ci-dessus : transmettez-le "
                    "vous-même."
                )
            db.add(trace)

    # Le chronogramme n'existe qu'à partir du moment où quelqu'un le regarde :
    # inutile de peupler tous les mandats de cinq étapes vides.
    deja = (
        await db.execute(select(EtapeMandat.id).where(EtapeMandat.mandat_id == mandat.id).limit(1))
    ).scalar_one_or_none()
    if deja is None:
        for etape in espace_client.etapes_initiales(mandat.id):
            db.add(etape)

    await audit.record(
        db,
        action="acces_client.ouvrir",
        entity_type="mandat",
        entity_id=mandat.id,
        user_id=user.id,
        details={"email": str(donnees.email), "courriel_envoye": courriel_envoye},
    )
    await db.commit()

    sortie = AccesOut.model_validate(invitation.acces)
    sortie.lien_activation = invitation.lien or None
    sortie.courriel_envoye = courriel_envoye
    sortie.avertissement = avertissement
    return sortie


@router.delete("/acces-client/{acces_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoquer_acces(
    acces_id: str,
    db: DbSession,
    user: CurrentUser,
    motif: str = Query(default=""),
) -> Response:
    acces = await db.get(AccesClient, acces_id)
    if acces is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Accès introuvable")
    await espace_client.revoquer(db, acces, motif)
    await audit.record(
        db,
        action="acces_client.revoquer",
        entity_type="mandat",
        entity_id=acces.mandat_id,
        user_id=user.id,
        details={"email": acces.email, "motif": motif},
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- chronogramme -----------------------------------------------------------


@router.get("/mandats/{mandat_id}/chronogramme", response_model=list[EtapeOut])
async def lire_chronogramme(mandat_id: str, db: DbSession, _: CurrentUser) -> list[EtapeOut]:
    lignes = (
        await db.execute(
            select(EtapeMandat)
            .where(EtapeMandat.mandat_id == mandat_id)
            .order_by(EtapeMandat.ordre)
        )
    ).scalars().all()
    return [EtapeOut.model_validate(e) for e in lignes]


@router.put("/mandats/{mandat_id}/chronogramme", response_model=list[EtapeOut])
async def ecrire_chronogramme(
    mandat_id: str, etapes: list[EtapeIn], db: DbSession, user: CurrentUser
) -> list[EtapeOut]:
    """Remplace le chronogramme du mandat.

    Remplacement plutôt que modification ligne à ligne : les étapes sont
    ordonnées, peu nombreuses, et se réorganisent d'un bloc. Un PATCH par étape
    obligerait l'interface à orchestrer des suppressions et des insertions pour
    un résultat que ce PUT décrit d'une seule pièce.
    """
    await get_mandat_or_404(db, mandat_id)
    anciennes = (
        await db.execute(select(EtapeMandat).where(EtapeMandat.mandat_id == mandat_id))
    ).scalars().all()
    for ancienne in anciennes:
        await db.delete(ancienne)
    await db.flush()

    sortie = []
    for ordre, etape in enumerate(etapes):
        ligne = EtapeMandat(mandat_id=mandat_id, ordre=ordre, **etape.model_dump())
        db.add(ligne)
        sortie.append(ligne)
    await db.flush()

    await audit.record(
        db,
        action="chronogramme.ecrire",
        entity_type="mandat",
        entity_id=mandat_id,
        user_id=user.id,
        details={"etapes": len(etapes)},
    )
    await db.commit()
    return [EtapeOut.model_validate(e) for e in sortie]


# --- échanges ---------------------------------------------------------------


@router.get("/mandats/{mandat_id}/echanges", response_model=list[EchangeOut])
async def lister_echanges(mandat_id: str, db: DbSession, _: CurrentUser) -> list[EchangeOut]:
    lignes = (
        await db.execute(
            select(EchangeClient)
            .where(EchangeClient.mandat_id == mandat_id)
            .order_by(EchangeClient.envoye_le)
        )
    ).scalars().all()
    return [EchangeOut.model_validate(e) for e in lignes]


@router.post(
    "/mandats/{mandat_id}/echanges",
    response_model=EchangeOut,
    status_code=status.HTTP_201_CREATED,
)
async def ecrire_au_client(
    mandat_id: str, donnees: EchangeIn, db: DbSession, user: CurrentUser
) -> EchangeOut:
    """Le cabinet écrit dans le fil du mandat.

    Le message est doublé d'une notification par courriel quand l'envoi est
    configuré : un fil qu'il faut penser à consulter n'est pas consulté. La
    notification annonce, elle ne recopie pas — le contenu reste dans l'espace,
    qui est le seul endroit où il est daté et attribué.
    """
    mandat = await get_mandat_or_404(db, mandat_id)
    echange = EchangeClient(
        mandat_id=mandat_id,
        poste_id=donnees.poste_id,
        auteur=AuteurEchange.CABINET,
        auteur_nom=user.full_name,
        type_echange=donnees.type_echange,
        objet=donnees.objet,
        corps=donnees.corps,
    )
    db.add(echange)
    await db.flush()

    reglages = await parametres.lire(db)
    if reglages.envoi_utilisable:
        destinataires = (
            await db.execute(
                select(AccesClient).where(
                    AccesClient.mandat_id == mandat_id,
                    AccesClient.revoque_le.is_(None),
                    AccesClient.active_le.is_not(None),
                )
            )
        ).scalars().all()
        for acces in destinataires:
            lien = f"{reglages.url_publique.rstrip('/')}/espace-client" if reglages.url_publique else ""
            corps = (
                f"Madame, Monsieur {acces.nom},\n\n"
                f"Un nouveau message vous attend dans votre espace de suivi du "
                f"mandat « {mandat.intitule} ».\n\n"
                + (f"{lien}\n\n" if lien else "")
                + "Cordialement,\nKapi Consult"
            )
            try:
                await messagerie.envoyer(
                    messagerie.Message(
                        destinataire=acces.email,
                        nom_destinataire=acces.nom,
                        sujet=f"Nouveau message — {mandat.intitule}",
                        corps=corps,
                    ),
                    reglages,
                    nom_expediteur="Kapi Consult",
                )
            except messagerie.ErreurEnvoi:
                # La notification est un confort. Son échec ne doit pas empêcher
                # le message d'exister dans le fil, où il sera lu à la connexion
                # suivante.
                pass

    await db.commit()
    return EchangeOut.model_validate(echange)


@router.post("/echanges/{echange_id}/traiter", response_model=EchangeOut)
async def marquer_traite(echange_id: str, db: DbSession, user: CurrentUser) -> EchangeOut:
    """Clôt une demande de modification : elle a été prise en compte."""
    echange = await db.get(EchangeClient, echange_id)
    if echange is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Échange introuvable")
    echange.traite_le = utcnow()
    echange.traite_par_id = user.id
    await db.commit()
    return EchangeOut.model_validate(echange)
