"""La boîte de recrutement, lue dans l'application comme dans une messagerie.

Le relevé automatique tranche seul : il crée un dossier pour tout message
porteur d'une pièce lisible. C'est le bon réflexe — mieux vaut un dossier inutile
qu'une candidature manquée —, mais il ne laisse voir ni ce qui a été pris, ni ce
qui a été laissé, ni pourquoi. Cet écran montre la boîte telle qu'elle est :
chaque message, son expéditeur, ses pièces, et ce que l'application en a fait.
On y importe à la main ce que le relevé a laissé, on y écarte ce qui n'est pas
une candidature, et on y décide d'ignorer un expéditeur une fois pour toutes.

Rien ici n'efface de message dans la boîte Microsoft : l'application lit, marque
lu, et c'est tout.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.candidatures import _ouvrir_boite
from app.api.postes import get_poste_or_404
from app.deps import CurrentUser, DbSession
from app.models import Candidature, ExpediteurIgnore, MessageTraite
from app.models import boite as traces
from app.services import audit, courriel, doublons, extraction, liens, parametres
from app.services.graph_microsoft import ErreurGraph
from app.services.preselection import charger_candidature, evaluer_candidature

router = APIRouter(tags=["boite"])

LIBELLES = {
    traces.IMPORTE: "Importé",
    traces.IGNORE: "Ignoré",
    traces.SANS_PIECE: "Sans pièce lisible",
    traces.SUPPRIME: "Importé puis supprimé",
}


async def _avec_statut(db, messages: list[dict]) -> list[dict]:
    """Ajoute à chaque message ce que l'application en a fait."""
    ids = [m["message_id"] for m in messages if m.get("message_id")]
    traces_par_id = {
        t.message_id: t
        for t in (
            await db.execute(select(MessageTraite).where(MessageTraite.message_id.in_(ids)))
        ).scalars()
    } if ids else {}
    candidatures = dict(
        (
            await db.execute(
                select(Candidature.message_id, Candidature.id).where(Candidature.message_id.in_(ids))
            )
        ).all()
    ) if ids else {}
    regles = await courriel.regles_d_ignorance(db)
    for m in messages:
        trace = traces_par_id.get(m.get("message_id", ""))
        candidature = candidatures.get(m.get("message_id", ""))
        if candidature:
            m["statut"] = traces.IMPORTE
            m["candidature_id"] = candidature
        elif trace is not None:
            m["statut"] = trace.statut
            m["candidature_id"] = None
        else:
            m["statut"] = ""
            m["candidature_id"] = None
        m["motif"] = trace.motif if trace is not None else None
        m["expediteur_ignore"] = traces.est_ignore(m.get("expediteur", ""), regles)
    return messages


def _sur_la_boite(fonction, *args, **kwargs):
    """Un appel bloquant à Graph, traduit en erreur lisible."""
    try:
        return fonction(*args, **kwargs)
    except ErreurGraph as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.get("/boite/messages")
async def lister(
    db: DbSession,
    _: CurrentUser,
    filtre: str = Query("tous", pattern="^(tous|non_lus|avec_pj)$"),
    recherche: str = Query("", max_length=200),
    suite: str = Query("", max_length=4000),
) -> dict:
    """Une page de la boîte, les plus récents d'abord ; `suite` mène à la suivante."""
    boite = await _ouvrir_boite(db)
    try:
        page = await asyncio.to_thread(
            _sur_la_boite, boite.lister, filtre=filtre, recherche=recherche, suite=suite
        )
        compte = await asyncio.to_thread(_sur_la_boite, boite.verifier) if not suite else None
    finally:
        boite.fermer()
    page["messages"] = await _avec_statut(db, page["messages"])
    if compte:
        page["dossier"] = compte["dossier"]
        page["total"] = compte["messages"]
        page["non_lus"] = compte["non_lus"]
    return page


@router.get("/boite/messages/{identifiant}")
async def lire(identifiant: str, db: DbSession, _: CurrentUser) -> dict:
    """Le message, ses pièces, et les autres messages du même expéditeur."""
    boite = await _ouvrir_boite(db)
    try:
        message = await asyncio.to_thread(_sur_la_boite, boite.lire, identifiant)
        autres = await asyncio.to_thread(
            _sur_la_boite, boite.du_meme_expediteur, message["expediteur"]
        )
    finally:
        boite.fermer()
    (message,) = await _avec_statut(db, [message])
    message["liens"] = [
        {"url": l.url, "service": l.service, "telechargeable": l.telechargeable}
        for l in liens.liens_de_documents(message.get("corps", ""))
    ]
    message["autres"] = await _avec_statut(db, [a for a in autres if a["id"] != identifiant])

    # Le poste que le relevé aurait choisi, d'après l'objet : une proposition.
    poste = await courriel.poste_du_message(
        db,
        courriel.MessageEntrant(
            message_id=message["message_id"],
            expediteur=message["expediteur"],
            nom_expediteur=message["nom_expediteur"],
            sujet=message["sujet"],
            recu_le=datetime.now(),
        ),
    )
    message["poste_propose"] = (
        {"id": poste.id, "intitule": poste.intitule} if poste is not None else None
    )
    return message


@router.get("/boite/messages/{identifiant}/pieces/{piece}")
async def piece_jointe(identifiant: str, piece: str, db: DbSession, _: CurrentUser) -> Response:
    """Une pièce jointe, pour la lire avant d'importer quoi que ce soit."""
    boite = await _ouvrir_boite(db)
    try:
        donnees, nom, type_mime = await asyncio.to_thread(
            _sur_la_boite, boite.piece_jointe, identifiant, piece
        )
    finally:
        boite.fermer()
    return Response(
        content=donnees,
        media_type=type_mime or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{nom.replace(chr(34), "")}"'},
    )


class ImportIn(BaseModel):
    identifiants: list[str] = Field(min_length=1, max_length=100)
    poste_id: str | None = None
    # Les messages d'un même expéditeur forment un seul dossier.
    regrouper: bool = True


@router.post("/boite/importer")
async def importer(payload: ImportIn, db: DbSession, user: CurrentUser) -> dict:
    """Fait des messages choisis des candidatures — vers un poste, ou sans poste.

    Le geste humain qui complète le relevé : un message laissé faute de
    référence, un CV envoyé en deux courriels. Avec `regrouper`, les messages
    d'une même adresse se versent au même dossier ; un message dont le dossier
    existe déjà n'en crée pas un second.
    """
    poste = await get_poste_or_404(db, payload.poste_id) if payload.poste_id else None
    boite = await _ouvrir_boite(db)
    crees: list[str] = []
    completes: list[str] = []
    sans_piece: list[str] = []
    deja: list[str] = []
    liens_recuperes = 0
    liens_inaccessibles: list[str] = []
    fusionnes = 0
    try:
        messages = []
        for identifiant in dict.fromkeys(payload.identifiants):
            messages.append(
                await asyncio.to_thread(_sur_la_boite, boite.message_complet, identifiant)
            )

        groupes: dict[str, list[courriel.MessageEntrant]] = defaultdict(list)
        for m in sorted(messages, key=lambda m: m.recu_le):
            cle = m.expediteur if payload.regrouper and m.expediteur else m.message_id
            groupes[cle].append(m)

        for groupe in groupes.values():
            dossier: Candidature | None = None
            for m in groupe:
                existant = (
                    await db.execute(select(Candidature).where(Candidature.message_id == m.message_id))
                ).scalar_one_or_none()
                if existant is not None:
                    deja.append(m.sujet or m.expediteur)
                    dossier = dossier or existant
                    continue
                if m.liens:
                    joints = await courriel.joindre_les_liens(m)
                    liens_recuperes += joints.recuperes
                    liens_inaccessibles.extend(joints.inaccessibles)
                lisibles = [
                    p for p in m.pieces
                    if extraction.piece_retenue(p.donnees, p.nom)
                ]
                if not lisibles:
                    sans_piece.append(m.sujet or m.expediteur)
                    await courriel.tracer(db, m, traces.SANS_PIECE, utilisateur=user.id)
                    continue
                if dossier is None:
                    dossier = await courriel.creer_depuis_message(db, m, poste)
                    crees.append(dossier.id)
                else:
                    await courriel.enregistrer_pieces(db, dossier, m)
                    completes.append(dossier.id)
                await courriel.tracer(
                    db, m, traces.IMPORTE, candidature_id=dossier.id, utilisateur=user.id
                )
                await asyncio.to_thread(boite.marquer_traite, m.message_id)
            if dossier is not None and dossier.id in crees:
                # Un dossier existait déjà pour ce candidat : on le complète,
                # on n'en garde pas un second.
                absorbe = await doublons.absorber(db, dossier)
                if absorbe is not None:
                    gardee, _ = absorbe
                    crees.remove(dossier.id)
                    completes = [gardee.id if c == dossier.id else c for c in completes]
                    completes.append(gardee.id)
                    fusionnes += 1
                    continue
            if dossier is not None and dossier.id in completes:
                rechargee = await charger_candidature(db, dossier.id)
                await evaluer_candidature(db, rechargee)
    finally:
        boite.fermer()

    await audit.record(
        db,
        action="boite.importer",
        entity_type="courriel",
        entity_id=None,
        user_id=user.id,
        details={
            "messages": len(payload.identifiants),
            "crees": len(crees),
            "completes": len(set(completes)),
            "poste_id": poste.id if poste else None,
        },
    )
    await db.commit()
    return {
        "crees": len(crees),
        "completes": len(set(completes)),
        "sans_piece": sans_piece,
        "deja_importes": deja,
        "candidature_ids": crees,
        "fusionnes": fusionnes,
        "liens_recuperes": liens_recuperes,
        "liens_inaccessibles": liens_inaccessibles,
    }


class MessageResume(BaseModel):
    message_id: str = Field(min_length=1, max_length=512)
    expediteur: str = Field(default="", max_length=320)
    sujet: str = Field(default="", max_length=1000)
    recu_le: datetime | None = None


class IgnorerIn(BaseModel):
    messages: list[MessageResume] = Field(min_length=1, max_length=500)
    motif: str = Field(default="écarté à la main", max_length=500)


@router.post("/boite/ignorer")
async def ignorer(payload: IgnorerIn, db: DbSession, user: CurrentUser) -> dict:
    """Écarte des messages : le relevé ne les lira plus. Rien n'est effacé."""
    for m in payload.messages:
        await courriel.tracer(
            db,
            courriel.MessageEntrant(
                message_id=m.message_id,
                expediteur=m.expediteur.lower(),
                nom_expediteur="",
                sujet=m.sujet,
                recu_le=m.recu_le or datetime.now(),
            ),
            traces.IGNORE,
            motif=payload.motif,
            utilisateur=user.id,
        )
    await audit.record(
        db, action="boite.ignorer", entity_type="courriel", entity_id=None,
        user_id=user.id, details={"messages": len(payload.messages)},
    )
    await db.commit()
    return {"ignores": len(payload.messages)}


class RetablirIn(BaseModel):
    message_ids: list[str] = Field(min_length=1, max_length=500)


@router.post("/boite/retablir")
async def retablir(payload: RetablirIn, db: DbSession, user: CurrentUser) -> dict:
    """Annule « ignoré » ou « sans pièce » : le relevé reconsidérera ces messages.

    Une trace d'import n'est pas retirée : le dossier existe, ou a été
    supprimé exprès, et le relevé ne doit pas le recréer en douce.
    """
    resultat = await db.execute(
        delete(MessageTraite).where(
            MessageTraite.message_id.in_(payload.message_ids),
            MessageTraite.statut.in_((traces.IGNORE, traces.SANS_PIECE)),
        )
    )
    await db.commit()
    return {"retablis": resultat.rowcount or 0}


# --- les expéditeurs ignorés --------------------------------------------------


class RegleIn(BaseModel):
    # Une adresse, ou un domaine entier précédé de « @ ».
    adresse: str = Field(min_length=3, max_length=320)
    raison: str = Field(default="", max_length=500)


@router.get("/boite/expediteurs-ignores")
async def regles(db: DbSession, _: CurrentUser) -> list[dict]:
    lignes = (await db.execute(select(ExpediteurIgnore).order_by(ExpediteurIgnore.cree_le.desc()))).scalars()
    return [
        {"id": r.id, "adresse": r.motif_adresse, "raison": r.raison, "cree_le": r.cree_le}
        for r in lignes
    ]


@router.post("/boite/expediteurs-ignores")
async def ajouter_regle(payload: RegleIn, db: DbSession, user: CurrentUser) -> dict:
    adresse = traces.normaliser_adresse(payload.adresse)
    if "@" not in adresse:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Une adresse (nom@domaine) ou un domaine précédé de @ (@domaine.com).",
        )
    if traces.domaine_public(adresse):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{adresse} est une messagerie publique : la plupart des candidats y ont leur "
            "adresse. Ignorez l'expéditeur précis plutôt que tout le domaine.",
        )
    reglages = await parametres.lire(db)
    # La boîte elle-même : l'ignorer couperait les réponses des candidats.
    if reglages.boite and traces.est_ignore(reglages.boite, {adresse}):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "C'est l'adresse de la boîte de recrutement elle-même."
        )
    existante = (
        await db.execute(select(ExpediteurIgnore).where(ExpediteurIgnore.motif_adresse == adresse))
    ).scalar_one_or_none()
    if existante is None:
        db.add(ExpediteurIgnore(motif_adresse=adresse, raison=payload.raison or None, cree_par=user.id))
        await audit.record(
            db, action="boite.ignorer_expediteur", entity_type="courriel", entity_id=None,
            user_id=user.id, details={"adresse": adresse},
        )
        await db.commit()
    return {"adresse": adresse}


@router.delete("/boite/expediteurs-ignores/{regle_id}")
async def retirer_regle(regle_id: str, db: DbSession, user: CurrentUser) -> dict:
    regle = await db.get(ExpediteurIgnore, regle_id)
    if regle is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Règle introuvable")
    await db.delete(regle)
    await audit.record(
        db, action="boite.retablir_expediteur", entity_type="courriel", entity_id=None,
        user_id=user.id, details={"adresse": regle.motif_adresse},
    )
    await db.commit()
    return {"retire": regle.motif_adresse}

