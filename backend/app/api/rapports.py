"""Rapports de recrutement et gabarits imposés.

Le rapport se construit en trois gestes, dans cet ordre : on le **génère** (les
chiffres sont figés, les sections proposées), on le **corrige** section par
section, on le **valide**. L'export vient après, dans le format que le client
attend ; le partager dans l'espace client est un geste séparé, parce que valider
en interne et remettre au commanditaire ne sont pas la même décision.

Un rapport validé n'est plus modifiable. C'est le seul verrou du fichier, et il
est là pour que « validé le 12 mars » désigne quelque chose de précis.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.mandats import get_mandat_or_404
from app.deps import CurrentUser, DbSession
from app.models import (
    Candidature,
    Mandat,
    ModeleDocument,
    Poste,
    Rapport,
    StatutCandidature,
    StatutRapport,
    UsageModele,
)
from app.models.base import utcnow
from app.services import audit, modeles, rapports, uploads
from app.services.exports import cv as export_cv
from app.services.exports import rapport as export_rapport
from app.services.preselection import charger_candidature

router = APIRouter(tags=["rapports"])


# --- schémas ----------------------------------------------------------------


class SectionOut(BaseModel):
    code: str
    titre: str
    contenu: str
    origine: str
    # Les tableaux d'une section calculée, en structure : colonnes, lignes, et
    # le genre de chaque ligne (rubrique, sous-critère, total). C'est ce que
    # l'aperçu et les exports dessinent en vraies tables. Vide sur une section
    # rédigée, et sur un rapport produit avant que la structure n'existe — il
    # reste alors son texte aligné.
    tableaux: list[dict] = Field(default_factory=list)
    # 1 pour une section, 2 pour une sous-section : le rapport remis est
    # hiérarchisé, et l'aperçu comme les exports doivent le montrer.
    niveau: int = 1
    # Un titre qui n'a pas de texte à lui mais porte des sous-sections.
    porteur: bool = False


class RapportOut(BaseModel):
    id: str
    mandat_id: str
    poste_id: str | None
    modele_id: str | None
    titre: str
    type_rapport: str
    statut: str
    sections: list[SectionOut] = Field(default_factory=list)
    donnees: dict = Field(default_factory=dict)
    valide_le: datetime | None = None
    partage_le: datetime | None = None
    created_at: datetime | None = None


class RapportItem(BaseModel):
    id: str
    titre: str
    type_rapport: str
    statut: str
    poste_id: str | None
    valide_le: datetime | None
    partage_le: datetime | None
    created_at: datetime | None


class GenerationIn(BaseModel):
    poste_id: str | None = None
    titre: str | None = None
    modele_id: str | None = None
    # Ce que le cabinet remet, et à quel moment de la mission. C'est ce choix
    # qui décide des sections : un rapport de présélection ne porte pas de
    # classement final, puisque les entretiens n'ont pas eu lieu.
    type_rapport: rapports.TypeRapport = rapports.TypeRapport.FINAL
    # L'assistance peut être refusée : sans fournisseur configuré, ou quand on
    # préfère écrire soi-même. Les chiffres et les tableaux sont produits dans
    # tous les cas.
    avec_assistance: bool = True


class SectionIn(BaseModel):
    code: str
    titre: str = Field(min_length=1, max_length=255)
    contenu: str = ""


class MiseAJourIn(BaseModel):
    titre: str | None = Field(default=None, max_length=500)
    sections: list[SectionIn] | None = None


class ModeleOut(BaseModel):
    id: str
    client_id: str | None
    mandat_id: str | None
    libelle: str
    usage: str
    nom_fichier: str | None
    actif: bool
    structure: dict | None
    notes: str | None
    created_at: datetime | None


class StructureIn(BaseModel):
    structure: dict
    libelle: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    actif: bool | None = None


def _vers_sortie(rapport: Rapport) -> RapportOut:
    return RapportOut(
        id=rapport.id,
        mandat_id=rapport.mandat_id,
        poste_id=rapport.poste_id,
        modele_id=rapport.modele_id,
        titre=rapport.titre,
        type_rapport=rapport.type_rapport or rapports.TypeRapport.FINAL.value,
        statut=rapport.statut.value,
        sections=[
            SectionOut(
                code=str(s.get("code") or ""),
                titre=str(s.get("titre") or ""),
                contenu=str(s.get("contenu") or ""),
                origine=str(s.get("origine") or rapports.ORIGINE_REDIGEE),
                tableaux=[t for t in (s.get("tableaux") or ()) if isinstance(t, dict)],
                niveau=int(s.get("niveau") or 1),
                porteur=bool(s.get("porteur")),
            )
            for s in (rapport.sections or ())
        ],
        donnees=rapport.donnees or {},
        valide_le=rapport.valide_le,
        partage_le=rapport.partage_le,
        created_at=rapport.created_at,
    )


async def _get_rapport(db, rapport_id: str) -> Rapport:
    rapport = await db.get(Rapport, rapport_id)
    if rapport is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rapport introuvable")
    return rapport


# --- rapports ---------------------------------------------------------------


@router.get("/mandats/{mandat_id}/rapports", response_model=list[RapportItem])
async def lister(mandat_id: str, db: DbSession, _: CurrentUser) -> list[RapportItem]:
    lignes = (
        await db.execute(
            select(Rapport)
            .where(Rapport.mandat_id == mandat_id)
            .order_by(Rapport.created_at.desc())
        )
    ).scalars().all()
    return [
        RapportItem(
            id=r.id,
            titre=r.titre,
            type_rapport=r.type_rapport or rapports.TypeRapport.FINAL.value,
            statut=r.statut.value,
            poste_id=r.poste_id,
            valide_le=r.valide_le,
            partage_le=r.partage_le,
            created_at=r.created_at,
        )
        for r in lignes
    ]


@router.post(
    "/mandats/{mandat_id}/rapports",
    response_model=RapportOut,
    status_code=status.HTTP_201_CREATED,
)
async def generer(
    mandat_id: str, donnees: GenerationIn, db: DbSession, user: CurrentUser
) -> RapportOut:
    """Produit un brouillon : chiffres figés, sections proposées.

    La génération peut être relancée autant de fois qu'on veut — chaque appel
    crée un nouveau rapport plutôt que d'écraser le précédent. Un brouillon
    déjà corrigé ne doit pas disparaître parce que quelqu'un a recliqué.
    """
    mandat = await get_mandat_or_404(db, mandat_id)

    if donnees.poste_id:
        poste = await db.get(Poste, donnees.poste_id)
        if poste is None or poste.mandat_id != mandat_id:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "Poste introuvable dans ce mandat"
            )

    # Le type choisit les sections ; une trame imposée par le client les
    # remplace toutes — c'est bien son objet, et elle prime donc sur le type.
    trame = rapports.trame_pour(donnees.type_rapport)
    if donnees.modele_id:
        modele = await db.get(ModeleDocument, donnees.modele_id)
        if modele is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Modèle introuvable")
        trame = rapports.trame_depuis_modele(modele.structure)

    chiffres = await rapports.rassembler(db, mandat_id, donnees.poste_id)
    sections = await rapports.rediger_sections(
        chiffres, trame, avec_assistance=donnees.avec_assistance
    )

    titre = donnees.titre or f"{donnees.type_rapport.libelle} — {mandat.intitule}"
    rapport = Rapport(
        mandat_id=mandat_id,
        poste_id=donnees.poste_id,
        modele_id=donnees.modele_id,
        titre=titre[:500],
        type_rapport=donnees.type_rapport.value,
        sections=sections,
        donnees=chiffres,
        redige_par_id=user.id,
    )
    db.add(rapport)
    await db.flush()

    await audit.record(
        db,
        action="rapport.generer",
        entity_type="mandat",
        entity_id=mandat_id,
        user_id=user.id,
        details={
            "rapport_id": rapport.id,
            "assistance": donnees.avec_assistance,
            "modele_id": donnees.modele_id,
        },
    )
    await db.commit()
    return _vers_sortie(rapport)


@router.get("/rapports/{rapport_id}", response_model=RapportOut)
async def lire(rapport_id: str, db: DbSession, _: CurrentUser) -> RapportOut:
    return _vers_sortie(await _get_rapport(db, rapport_id))


@router.put("/rapports/{rapport_id}", response_model=RapportOut)
async def modifier(
    rapport_id: str, donnees: MiseAJourIn, db: DbSession, user: CurrentUser
) -> RapportOut:
    """Enregistre les corrections. Une section touchée devient « rédigée ».

    Le changement d'origine n'est pas cosmétique : c'est ce qui permet de dire
    d'un rapport quelles parties ont été relues. Une section laissée exactement
    telle qu'elle a été proposée garde son étiquette, et se voit donc dans
    l'écran de relecture.
    """
    rapport = await _get_rapport(db, rapport_id)
    if rapport.statut is StatutRapport.VALIDE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ce rapport est validé : il ne peut plus être modifié. Générez-en "
            "une nouvelle version si le contenu doit changer.",
        )

    if donnees.titre is not None:
        rapport.titre = donnees.titre

    if donnees.sections is not None:
        anciennes = {
            str(s.get("code")): s for s in (rapport.sections or ()) if s.get("code")
        }
        nouvelles = []
        for section in donnees.sections:
            ancienne = anciennes.get(section.code, {})
            inchangee = str(ancienne.get("contenu") or "") == section.contenu
            origine = str(ancienne.get("origine") or rapports.ORIGINE_REDIGEE)
            nouvelle = {
                "code": section.code,
                "titre": section.titre,
                "contenu": section.contenu,
                "origine": origine if inchangee else rapports.ORIGINE_REDIGEE,
            }
            # Les tableaux d'une section calculée survivent à l'enregistrement
            # — sans quoi le premier « Enregistrer » ramenait le rapport à des
            # colonnes alignées à l'espace.
            #
            # Sauf si quelqu'un a corrigé le texte à la main : la table
            # afficherait alors autre chose que ce qu'il a écrit, et c'est la
            # main humaine qui fait foi. Le tableau est abandonné, pas
            # discrètement conservé à côté d'un texte qui le contredit.
            if inchangee and ancienne.get("tableaux"):
                nouvelle["tableaux"] = ancienne["tableaux"]
            # Le rang et le rôle d'une section ne se modifient pas depuis
            # l'écran de relecture : ils tiennent à la trame, pas au texte.
            for cle in ("niveau", "porteur", "tableaux_texte"):
                if ancienne.get(cle) is not None:
                    nouvelle[cle] = ancienne[cle]
            nouvelles.append(nouvelle)
        # Réaffectation complète : SQLAlchemy ne détecte pas la mutation d'une
        # liste JSON en place.
        rapport.sections = nouvelles

    rapport.statut = StatutRapport.EN_RELECTURE
    await db.commit()
    return _vers_sortie(rapport)


@router.post("/rapports/{rapport_id}/valider", response_model=RapportOut)
async def valider(rapport_id: str, db: DbSession, user: CurrentUser) -> RapportOut:
    """Fige le rapport. Après quoi il ne se modifie plus."""
    rapport = await _get_rapport(db, rapport_id)
    if rapport.statut is StatutRapport.VALIDE:
        return _vers_sortie(rapport)

    restantes = [
        str(s.get("titre"))
        for s in (rapport.sections or ())
        if s.get("origine") == rapports.ORIGINE_PROPOSEE
    ]
    if restantes:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ces sections n'ont pas encore été relues : "
            + ", ".join(restantes)
            + ". Le rapport engage le cabinet ; validez-les d'abord.",
        )

    rapport.statut = StatutRapport.VALIDE
    rapport.valide_le = utcnow()
    rapport.valide_par_id = user.id
    await audit.record(
        db,
        action="rapport.valider",
        entity_type="rapport",
        entity_id=rapport.id,
        user_id=user.id,
        details={"titre": rapport.titre},
    )
    await db.commit()
    return _vers_sortie(rapport)


@router.post("/rapports/{rapport_id}/partager", response_model=RapportOut)
async def partager(
    rapport_id: str,
    db: DbSession,
    user: CurrentUser,
    partager: bool = Query(default=True),
) -> RapportOut:
    """Rend — ou retire — le rapport visible dans l'espace du promoteur."""
    rapport = await _get_rapport(db, rapport_id)
    if partager and rapport.statut is not StatutRapport.VALIDE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Seul un rapport validé peut être remis au client.",
        )
    rapport.partage_le = utcnow() if partager else None
    await audit.record(
        db,
        action="rapport.partager" if partager else "rapport.retirer",
        entity_type="rapport",
        entity_id=rapport.id,
        user_id=user.id,
        details={"titre": rapport.titre},
    )
    await db.commit()
    return _vers_sortie(rapport)


@router.get("/rapports/{rapport_id}/export")
async def exporter(
    rapport_id: str,
    db: DbSession,
    _: CurrentUser,
    format: str = Query(default="docx"),
) -> Response:
    """Le rapport dans le format demandé : docx, pdf, odt ou txt."""
    rapport = await _get_rapport(db, rapport_id)
    mandat = await db.get(Mandat, rapport.mandat_id)

    sous_titre = (rapport.donnees or {}).get("mandat", {}).get("client") or (
        mandat.intitule if mandat else ""
    )
    try:
        octets, mime, extension = export_rapport.rendre(
            format,
            rapport.titre,
            sous_titre,
            list(rapport.sections or ()),
            rapport.valide_le or rapport.created_at or utcnow(),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    base = "".join(
        c if c.isalnum() or c in "-_" else "_" for c in rapport.titre
    )[:80] or "rapport"
    return Response(
        content=octets,
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="{base}.{extension}"'
        },
    )


@router.delete("/rapports/{rapport_id}", status_code=status.HTTP_204_NO_CONTENT)
async def supprimer(rapport_id: str, db: DbSession, user: CurrentUser) -> Response:
    """Jette un brouillon. Un rapport validé ne se supprime pas.

    La génération crée un rapport à chaque appel, volontairement : un brouillon
    déjà corrigé ne doit pas disparaître parce que quelqu'un a recliqué. Mais
    rien ne permettait ensuite de retirer celui qu'on venait de produire par
    erreur, et l'onglet accumulait des doublons qu'il fallait supprimer en base.

    La même règle que partout ailleurs sur les rapports : **validé, donc figé**.
    Un document remis au client ne s'efface pas d'un clic — il se retire du
    partage, ce qui est un geste différent et réversible. L'audit garde la trace
    de la suppression, titre compris.
    """
    rapport = await _get_rapport(db, rapport_id)
    if rapport.statut is StatutRapport.VALIDE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ce rapport est validé : il ne se supprime pas. Retirez-le du "
            "partage si le client ne doit plus le voir.",
        )

    await audit.record(
        db,
        action="rapport.supprimer",
        entity_type="mandat",
        entity_id=rapport.mandat_id,
        user_id=user.id,
        details={
            "rapport_id": rapport.id,
            "titre": rapport.titre,
            "type_rapport": rapport.type_rapport,
            "statut": rapport.statut.value,
        },
    )
    await db.delete(rapport)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/rapports/formats")
async def formats_disponibles(_: CurrentUser) -> dict:
    return {"formats": sorted(export_rapport.FORMATS)}


# --- CV reconstitués ---------------------------------------------------------


async def _fiche_cv(db, candidature_id: str, avec_coordonnees: bool):
    candidature = await charger_candidature(db, candidature_id)
    if candidature is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidature introuvable")
    return candidature, export_cv.construire(
        candidature, avec_coordonnees=avec_coordonnees
    )


async def _ordre_du_modele(db, modele_id: str | None) -> list[str] | None:
    if not modele_id:
        return None
    modele = await db.get(ModeleDocument, modele_id)
    if modele is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modèle introuvable")
    return export_cv.sections_du_modele(modele.structure)


@router.get("/candidatures/{candidature_id}/cv-maison")
async def cv_maison(
    candidature_id: str,
    db: DbSession,
    _: CurrentUser,
    format: str = Query(default="docx"),
    modele_id: str | None = Query(default=None),
    avec_coordonnees: bool = Query(default=True),
    accepter_non_verifie: bool = Query(default=False),
) -> Response:
    """Le CV du candidat, remis en forme depuis les données du dossier.

    Refusé tant que le parcours n'a pas été relu : un CV reconstitué porte
    l'en-tête du cabinet, et y verser une extraction non confirmée
    transformerait une supposition en pièce remise au client. Passer
    `accepter_non_verifie` lève le refus et fait apparaître la mention sur le
    document — la décision reste visible pour qui le reçoit.
    """
    candidature, fiche = await _fiche_cv(db, candidature_id, avec_coordonnees)
    if fiche.non_verifie and not accepter_non_verifie:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Le parcours de ce dossier vient d'une extraction que personne n'a "
            "confirmée. Relisez-le avant d'en tirer un CV à en-tête du cabinet, "
            "ou demandez-le explicitement : la mention figurera alors sur le "
            "document.",
        )

    ordre = await _ordre_du_modele(db, modele_id)
    try:
        octets, mime, extension = export_cv.rendre(format, fiche, ordre)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return Response(
        content=octets,
        media_type=mime,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{export_cv.nom_fichier(fiche, extension)}"'
            )
        },
    )


@router.get("/postes/{poste_id}/cvs-maison.zip")
async def cvs_maison(
    poste_id: str,
    db: DbSession,
    _: CurrentUser,
    format: str = Query(default="docx"),
    modele_id: str | None = Query(default=None),
    avec_coordonnees: bool = Query(default=True),
    accepter_non_verifie: bool = Query(default=False),
    portee: str = Query(default="proposes"),
) -> Response:
    """Les CV du poste, dans une présentation unique, en une archive.

    C'est la demande réelle : livrer au client vingt dossiers sous la même
    forme. Un dossier dont le parcours n'a pas été relu est **écarté**, pas
    inclus avec une mention — sur un lot, une mention se perd, et le client
    recevrait une pièce non vérifiée au milieu de pièces vérifiées. La liste
    des écartés accompagne l'archive dans un fichier lisible.
    """
    poste = await db.get(Poste, poste_id)
    if poste is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Poste introuvable")

    statuts = (
        [StatutCandidature.PRESELECTIONNEE, StatutCandidature.RETENUE]
        if portee == "proposes"
        else None
    )
    requete = select(Candidature.id).where(Candidature.poste_id == poste_id)
    if statuts is not None:
        requete = requete.where(Candidature.statut.in_(statuts))
    identifiants = (await db.execute(requete)).scalars().all()

    if not identifiants:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Aucun dossier à reconstituer pour cette sélection.",
        )

    ordre = await _ordre_du_modele(db, modele_id)
    tampon = io.BytesIO()
    ecartes: list[str] = []
    inclus = 0

    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as archive:
        for identifiant in identifiants:
            _, fiche = await _fiche_cv(db, identifiant, avec_coordonnees)
            if fiche.non_verifie and not accepter_non_verifie:
                ecartes.append(fiche.nom_complet)
                continue
            try:
                octets, _mime, extension = export_cv.rendre(format, fiche, ordre)
            except ValueError as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
            archive.writestr(export_cv.nom_fichier(fiche, extension), octets)
            inclus += 1

        if ecartes:
            archive.writestr(
                "DOSSIERS NON INCLUS.txt",
                "Ces dossiers n'ont pas été reconstitués : leur parcours vient "
                "d'une extraction automatique que personne n'a confirmée.\n"
                "Relisez-les depuis l'application, puis relancez l'export.\n\n"
                + "\n".join(f"— {nom}" for nom in ecartes)
                + "\n",
            )

    if inclus == 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Aucun de ces dossiers n'a été relu : leurs parcours viennent d'une "
            "extraction non confirmée. Vérifiez-les avant d'en tirer des CV à "
            "en-tête du cabinet.",
        )

    nom = "".join(c if c.isalnum() or c in " -_" else "_" for c in poste.intitule)[:60]
    return Response(
        content=tampon.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="CV - {nom or "poste"}.zip"',
            # Le compte rendu voyage dans l'en-tête : l'écran doit pouvoir dire
            # « 12 inclus, 3 écartés » sans rouvrir l'archive.
            "X-TriCV-Inclus": str(inclus),
            "X-TriCV-Ecartes": str(len(ecartes)),
        },
    )


# --- gabarits imposés -------------------------------------------------------


@router.get("/modeles-documents", response_model=list[ModeleOut])
async def lister_modeles(
    db: DbSession,
    _: CurrentUser,
    client_id: str | None = Query(default=None),
    mandat_id: str | None = Query(default=None),
    usage: UsageModele | None = Query(default=None),
) -> list[ModeleOut]:
    requete = select(ModeleDocument).order_by(ModeleDocument.created_at.desc())
    if client_id:
        requete = requete.where(ModeleDocument.client_id == client_id)
    if mandat_id:
        requete = requete.where(ModeleDocument.mandat_id == mandat_id)
    if usage is not None:
        requete = requete.where(ModeleDocument.usage == usage)
    lignes = (await db.execute(requete)).scalars().all()
    return [
        ModeleOut(
            id=m.id,
            client_id=m.client_id,
            mandat_id=m.mandat_id,
            libelle=m.libelle,
            usage=m.usage.value,
            nom_fichier=m.nom_fichier,
            actif=m.actif,
            structure=m.structure,
            notes=m.notes,
            created_at=m.created_at,
        )
        for m in lignes
    ]


@router.post(
    "/modeles-documents", response_model=ModeleOut, status_code=status.HTTP_201_CREATED
)
async def deposer_modele(
    db: DbSession,
    user: CurrentUser,
    libelle: str = Form(..., min_length=1, max_length=255),
    usage: UsageModele = Form(...),
    client_id: str | None = Form(default=None),
    mandat_id: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    fichier: UploadFile = File(...),
) -> ModeleOut:
    """Enregistre le gabarit d'un client et propose sa correspondance.

    La correspondance rendue ici est une proposition : elle s'enregistre telle
    quelle, mais l'écran la fait relire avant de s'en servir pour produire quoi
    que ce soit. Une trame mal découpée se paie sur tous les rapports du client.
    """
    if not client_id and not mandat_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Un modèle se rattache à un client ou à un mandat.",
        )
    try:
        accepte = await uploads.validate(fichier, uploads.PLAFOND_ABSOLU_MO)
    except uploads.RejectedUpload as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    chemin = await uploads.store(accepte)
    texte, structure = await modeles.analyser(
        accepte.data, accepte.mime_type, accepte.filename
    )

    modele = ModeleDocument(
        client_id=client_id,
        mandat_id=mandat_id,
        libelle=libelle,
        usage=usage,
        nom_fichier=accepte.filename,
        chemin_stockage=chemin,
        type_mime=accepte.mime_type,
        empreinte=accepte.sha256 or hashlib.sha256(accepte.data).hexdigest(),
        texte_source=texte or None,
        structure=structure,
        notes=notes,
    )
    db.add(modele)
    await db.flush()

    await audit.record(
        db,
        action="modele_document.deposer",
        entity_type="modele_document",
        entity_id=modele.id,
        user_id=user.id,
        details={"libelle": libelle, "usage": usage.value},
    )
    await db.commit()
    return ModeleOut(
        id=modele.id,
        client_id=modele.client_id,
        mandat_id=modele.mandat_id,
        libelle=modele.libelle,
        usage=modele.usage.value,
        nom_fichier=modele.nom_fichier,
        actif=modele.actif,
        structure=modele.structure,
        notes=modele.notes,
        created_at=modele.created_at,
    )


@router.put("/modeles-documents/{modele_id}", response_model=ModeleOut)
async def corriger_modele(
    modele_id: str, donnees: StructureIn, db: DbSession, user: CurrentUser
) -> ModeleOut:
    """Enregistre la correspondance relue. C'est elle qui fait foi ensuite."""
    modele = await db.get(ModeleDocument, modele_id)
    if modele is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modèle introuvable")
    modele.structure = donnees.structure
    if donnees.libelle is not None:
        modele.libelle = donnees.libelle
    if donnees.notes is not None:
        modele.notes = donnees.notes
    if donnees.actif is not None:
        modele.actif = donnees.actif
    await audit.record(
        db,
        action="modele_document.corriger",
        entity_type="modele_document",
        entity_id=modele.id,
        user_id=user.id,
        details={"sections": len(donnees.structure.get("sections") or ())},
    )
    await db.commit()
    return ModeleOut(
        id=modele.id,
        client_id=modele.client_id,
        mandat_id=modele.mandat_id,
        libelle=modele.libelle,
        usage=modele.usage.value,
        nom_fichier=modele.nom_fichier,
        actif=modele.actif,
        structure=modele.structure,
        notes=modele.notes,
        created_at=modele.created_at,
    )


@router.delete("/modeles-documents/{modele_id}", status_code=status.HTTP_204_NO_CONTENT)
async def supprimer_modele(
    modele_id: str, db: DbSession, user: CurrentUser
) -> Response:
    modele = await db.get(ModeleDocument, modele_id)
    if modele is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modèle introuvable")
    await audit.record(
        db,
        action="modele_document.supprimer",
        entity_type="modele_document",
        entity_id=modele.id,
        user_id=user.id,
        details={"libelle": modele.libelle},
    )
    await db.delete(modele)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
