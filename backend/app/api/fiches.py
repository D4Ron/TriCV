"""La fiche de poste fournie par le client : lecture, dépôt, téléchargement.

Deux usages, deux routes :

- **Lire** une fiche — document ou texte collé — pour préremplir le formulaire
  d'un poste. Rien n'est enregistré : la proposition revient à l'écran, et
  c'est l'enregistrement du formulaire, après relecture, qui fait foi.
- **Joindre** la fiche à un poste. Le document est conservé tel quel, et son
  texte sert ensuite à rédiger l'avis : l'avis dit du poste ce que la fiche en
  dit.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.postes import _vers_sortie, get_poste_or_404
from app.deps import CurrentUser, DbSession
from app.models.base import utcnow
from app.schemas.recrutement import PosteOut
from app.services import audit, fiche_poste, storage, uploads

router = APIRouter(tags=["fiches de poste"])


class PropositionOut(BaseModel):
    """Ce que la fiche permet de préremplir, et d'où vient chaque valeur."""

    valeurs: dict[str, Any] = Field(default_factory=dict)
    # champ -> "document" (recopié de la fiche) ou "assistance" (proposé par
    # le modèle, à vérifier de plus près).
    origines: dict[str, str] = Field(default_factory=dict)
    avertissement: str | None = None


class FicheJointeOut(BaseModel):
    poste: PosteOut
    proposition: PropositionOut | None = None


def _vers_proposition(proposition: fiche_poste.Proposition) -> PropositionOut:
    return PropositionOut(
        valeurs=proposition.valeurs,
        origines=proposition.origines,
        avertissement=proposition.avertissement,
    )


async def _texte_de(fichier: UploadFile | None, texte: str | None) -> tuple[str, bytes | None]:
    """Le texte à lire, et les octets du document s'il y en a un."""
    if fichier is not None and fichier.filename:
        donnees = await fichier.read()
        await fichier.close()
        if not donnees:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Le fichier est vide.")
        try:
            lu, _ = await fiche_poste.lire_document(donnees, fichier.filename)
        except fiche_poste.FicheIllisible as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        return lu, donnees
    if texte and texte.strip():
        return texte, None
    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Joignez la fiche de poste (PDF ou Word) ou collez son texte.",
    )


@router.post("/fiches/lecture", response_model=PropositionOut)
async def lire_fiche(
    _: CurrentUser,
    fichier: UploadFile | None = File(default=None),
    texte: str | None = Form(default=None),
    avec_assistance: bool = Form(default=True),
) -> PropositionOut:
    """Propose les champs d'un poste à partir d'une fiche. N'enregistre rien."""
    contenu, _ = await _texte_de(fichier, texte)
    try:
        proposition = await fiche_poste.proposer(contenu, avec_assistance=avec_assistance)
    except fiche_poste.FicheIllisible as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return _vers_proposition(proposition)


@router.post("/postes/{poste_id}/fiche", response_model=FicheJointeOut)
async def joindre_fiche(
    poste_id: str,
    db: DbSession,
    user: CurrentUser,
    fichier: UploadFile | None = File(default=None),
    texte: str | None = Form(default=None),
    proposer: bool = Form(default=False),
    avec_assistance: bool = Form(default=True),
) -> FicheJointeOut:
    """Joint la fiche au poste — un document, ou un texte collé.

    Une nouvelle fiche remplace l'ancienne : un poste n'en a qu'une, celle sur
    laquelle l'avis se rédige. `proposer` renvoie en plus de quoi mettre à jour
    le formulaire du poste à partir de cette fiche ; rien n'est appliqué sans
    que quelqu'un l'enregistre.
    """
    poste = await get_poste_or_404(db, poste_id)
    contenu, donnees = await _texte_de(fichier, texte)

    ancien = poste.fiche_chemin
    if donnees is not None:
        try:
            accepte = uploads.valider_octets(donnees, fichier.filename or "fiche")  # type: ignore[union-attr]
        except uploads.RejectedUpload as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        poste.fiche_chemin = await uploads.store(accepte)
        poste.fiche_nom_fichier = accepte.filename
        poste.fiche_type_mime = accepte.mime_type
    else:
        # Un texte collé remplace aussi le document : garder l'ancien fichier
        # laisserait croire qu'il est la source de l'avis.
        poste.fiche_chemin = None
        poste.fiche_nom_fichier = None
        poste.fiche_type_mime = None
    poste.fiche_texte = contenu.strip()
    poste.fiche_deposee_le = utcnow()

    await audit.record(
        db,
        action="poste.fiche",
        entity_type="poste",
        entity_id=poste.id,
        user_id=user.id,
        details={"fichier": poste.fiche_nom_fichier or "texte collé"},
    )
    await db.commit()
    await db.refresh(poste)

    if ancien and ancien != poste.fiche_chemin:
        # Après l'enregistrement : si la base avait refusé, l'ancien fichier
        # serait encore la fiche du poste.
        await storage.get_storage().delete(ancien)

    proposition = None
    if proposer:
        try:
            proposition = _vers_proposition(
                await fiche_poste.proposer(contenu, avec_assistance=avec_assistance)
            )
        except fiche_poste.FicheIllisible as exc:
            proposition = PropositionOut(avertissement=str(exc))
    return FicheJointeOut(poste=await _vers_sortie(db, poste), proposition=proposition)


@router.get("/postes/{poste_id}/fiche")
async def telecharger_fiche(poste_id: str, db: DbSession, _: CurrentUser) -> StreamingResponse:
    poste = await get_poste_or_404(db, poste_id)
    if not poste.fiche_chemin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucun document de fiche pour ce poste")
    depot = storage.get_storage()
    if not await depot.exists(poste.fiche_chemin):
        raise HTTPException(status.HTTP_410_GONE, "Le fichier n'est plus disponible")
    nom = (poste.fiche_nom_fichier or "fiche-de-poste").replace('"', "")
    return StreamingResponse(
        depot.stream(poste.fiche_chemin),
        media_type=poste.fiche_type_mime or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{nom}"'},
    )


@router.delete("/postes/{poste_id}/fiche", status_code=status.HTTP_204_NO_CONTENT)
async def retirer_fiche(poste_id: str, db: DbSession, user: CurrentUser) -> Response:
    poste = await get_poste_or_404(db, poste_id)
    chemin = poste.fiche_chemin
    poste.fiche_chemin = None
    poste.fiche_nom_fichier = None
    poste.fiche_type_mime = None
    poste.fiche_texte = None
    poste.fiche_deposee_le = None
    await audit.record(
        db,
        action="poste.fiche.retirer",
        entity_type="poste",
        entity_id=poste.id,
        user_id=user.id,
        details=None,
    )
    await db.commit()
    if chemin:
        await storage.get_storage().delete(chemin)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
