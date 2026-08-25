"""Présélection persistée : base → domaine → base.

Le calcul lui-même vit dans `app.domain` et ne connaît ni SQLAlchemy ni
réseau. Ce module fait les trois choses que le domaine ne peut pas faire :
lire les enregistrements, écrire les résultats, et décider du statut de la
candidature en tenant compte de la provenance des données.

Recalculer est sans effet de bord : la notation et les motifs sont remplacés,
jamais empilés, et une élimination levée par un humain le reste.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain import (
    BAREME_PAR_DEFAUT,
    Bareme,
    DecisionSeuil,
    Diplome,
    ExigencesPoste,
    Experience,
    Notation,
    ProfilCandidat,
    RestrictionPoste,
    evaluer_eligibilite,
    noter,
)
from app.domain.referentiel import NiveauDiplome
from app.domain.serialisation import bareme_depuis_dict, bareme_vers_dict
from app.models.enums import Provenance, StatutCandidature
from app.models.recrutement import (
    Avis,
    Candidat,
    Candidature,
    Elimination,
    LigneNotation,
    Notation as NotationDb,
    Poste,
)
from app.services.assistance import motif_opposable


# --- base → domaine ---------------------------------------------------------


def construire_profil(candidat: Candidat, pieces_fournies: frozenset[str]) -> ProfilCandidat:
    return ProfilCandidat(
        nom=candidat.nom,
        prenom=candidat.prenom,
        date_naissance=candidat.date_naissance,
        sexe=candidat.sexe,
        nationalites=frozenset(candidat.nationalites or ()),
        adresse=candidat.adresse,
        diplomes=tuple(
            Diplome(
                intitule=d.intitule,
                niveau=NiveauDiplome(d.niveau),
                domaine=d.domaine,
                etablissement=d.etablissement,
                annee=d.annee,
            )
            for d in candidat.diplomes
        ),
        experiences=tuple(
            Experience(
                poste=e.poste,
                employeur=e.employeur,
                debut=e.debut,
                fin=e.fin,
                domaines=frozenset(e.domaines or ()),
                pays=e.pays,
            )
            for e in candidat.experiences
        ),
        langues=frozenset(candidat.langues or ()),
        certifications=tuple(candidat.certifications or ()),
        pieces_fournies=pieces_fournies,
    )


def construire_exigences(poste: Poste, date_cloture: date | None = None) -> ExigencesPoste:
    restriction = RestrictionPoste(
        age_min=poste.restriction_age_min,
        age_max=poste.restriction_age_max,
        sexe=poste.restriction_sexe,
        nationalites=frozenset(poste.restriction_nationalites or ()),
        justification=poste.restriction_justification or "",
    )
    return ExigencesPoste(
        niveau_min=NiveauDiplome(poste.niveau_min),
        domaines_acceptes=frozenset(poste.domaines_acceptes or ()),
        annees_experience_min=poste.annees_experience_min,
        annees_experience_specifique_min=poste.annees_experience_specifique_min,
        domaines_experience=frozenset(poste.domaines_experience or ()),
        pieces_requises=frozenset(poste.pieces_requises or ()),
        langues_requises=frozenset(poste.langues_requises or ()),
        restriction=restriction,
        date_reference=date_cloture or date.today(),
    )


def construire_bareme(poste: Poste) -> Bareme:
    bareme = bareme_depuis_dict(poste.bareme) if poste.bareme else BAREME_PAR_DEFAUT
    # Le seuil vit sur le poste : il peut être abaissé pour un poste en
    # tension sans toucher à la répartition des points.
    if poste.seuil_preselection is not None:
        bareme = replace(bareme, seuil_preselection=float(poste.seuil_preselection))
    return bareme


def provenances_du_dossier(candidat: Candidat) -> dict[str, Provenance]:
    """La provenance la moins fiable de chaque famille de données.

    Un seul diplôme extrait sans relecture suffit à rendre l'ensemble des
    motifs « formation » non opposables : c'est le maillon faible qui compte.
    """

    def pire(provenances: list[Provenance]) -> Provenance:
        if not provenances:
            # Rien n'a été saisi : « pas encore dépouillé », et non « vérifié
            # vide ». Un candidat du formulaire public dépose son CV sans
            # ressaisir ses diplômes ; l'éliminer pour « aucun diplôme
            # déclaré » lui reprocherait un travail que le cabinet n'a pas
            # encore fait. Seule une prise en main humaine explicite — saisie
            # ou confirmation — permet de conclure à une absence réelle.
            return (
                candidat.provenance
                if candidat.provenance in (Provenance.SAISI_RH, Provenance.VERIFIE_RH)
                else Provenance.EXTRAIT_IA
            )
        return (
            Provenance.EXTRAIT_IA
            if any(p is Provenance.EXTRAIT_IA for p in provenances)
            else Provenance.VERIFIE_RH
        )

    return {
        "etat_civil": candidat.provenance,
        "diplomes": pire([d.provenance for d in candidat.diplomes]),
        "experiences": pire([e.provenance for e in candidat.experiences]),
    }


# --- domaine → base ---------------------------------------------------------


# Tout ce qu'une candidature doit porter pour être évaluée *et* sérialisée.
# En asynchrone, un attribut non chargé déclenche un lazy load hors contexte
# greenlet, c'est-à-dire une erreur : le chargement est donc exhaustif.
_CHARGEMENT_COMPLET = (
    selectinload(Candidature.candidat).selectinload(Candidat.diplomes),
    selectinload(Candidature.candidat).selectinload(Candidat.experiences),
    selectinload(Candidature.pieces),
    selectinload(Candidature.eliminations),
    selectinload(Candidature.poste),
    selectinload(Candidature.notation).selectinload(NotationDb.lignes),
)


async def charger_candidature(db: AsyncSession, candidature_id: str) -> Candidature | None:
    """Recharge une candidature avec tout son dossier.

    `populate_existing` n'est pas optionnel : si la session détient déjà
    l'objet, une simple requête renvoie l'instance du registre d'identité sans
    rafraîchir les relations déjà chargées. Une notation créée juste avant
    resterait donc invisible — l'appelant relirait un dossier périmé.
    """
    resultat = await db.execute(
        select(Candidature)
        .where(Candidature.id == candidature_id)
        .options(*_CHARGEMENT_COMPLET)
        .execution_options(populate_existing=True)
    )
    return resultat.scalar_one_or_none()


async def _date_cloture(db: AsyncSession, poste_id: str) -> date | None:
    resultat = await db.execute(
        select(Avis.date_cloture)
        .where(Avis.poste_id == poste_id, Avis.date_cloture.is_not(None))
        .order_by(Avis.date_cloture.desc())
    )
    return resultat.scalars().first()


async def evaluer_candidature(db: AsyncSession, candidature: Candidature) -> NotationDb:
    """Recalcule éligibilité et note, puis persiste les deux.

    Ne commit pas : l'appelant décide de la transaction, ce qui permet de
    réévaluer tout un poste en une seule.
    """
    poste = candidature.poste
    candidat = candidature.candidat

    cloture = await _date_cloture(db, poste.id)
    exigences = construire_exigences(poste, cloture)
    pieces = frozenset(p.type_piece for p in candidature.pieces)
    profil = construire_profil(candidat, pieces)
    bareme = construire_bareme(poste)

    motifs = evaluer_eligibilite(profil, exigences, candidature.recue_le)
    provenances = provenances_du_dossier(candidat)
    notation = noter(profil, exigences, bareme)

    await _remplacer_eliminations(db, candidature, motifs, provenances)
    enregistrement = await _remplacer_notation(db, candidature, notation, bareme)

    candidature.statut = _statut(candidature, notation, provenances)
    return enregistrement


async def _remplacer_eliminations(
    db: AsyncSession,
    candidature: Candidature,
    motifs,
    provenances: dict[str, Provenance],
) -> None:
    """Réécrit les motifs, en préservant ceux qu'un humain a levés.

    Le flush est indispensable : SQLAlchemy émet les INSERT avant les DELETE
    d'un même flush, si bien que les nouveaux motifs entreraient en collision
    avec les anciens sur uq_elimination_motif.
    """
    levees = {e.motif: e for e in candidature.eliminations if e.leve_le is not None}

    for existante in list(candidature.eliminations):
        await db.delete(existante)
    candidature.eliminations = []
    await db.flush()

    for motif in motifs:
        precedente = levees.get(motif.motif)
        db.add(
            Elimination(
                candidature_id=candidature.id,
                motif=motif.motif,
                attendu=motif.attendu,
                constate=motif.constate,
                justification_poste=motif.justification_poste or None,
                sur_donnee_non_verifiee=not motif_opposable(motif.motif, provenances),
                leve_le=precedente.leve_le if precedente else None,
                leve_par_id=precedente.leve_par_id if precedente else None,
                leve_motif=precedente.leve_motif if precedente else None,
            )
        )
    await db.flush()
    await db.refresh(candidature, ["eliminations"])


async def _remplacer_notation(
    db: AsyncSession, candidature: Candidature, notation: Notation, bareme: Bareme
) -> NotationDb:
    ancienne = await db.execute(
        select(NotationDb).where(NotationDb.candidature_id == candidature.id)
    )
    precedente = ancienne.scalar_one_or_none()
    note_manuelle = precedente.note_manuelle if precedente else None
    motif_manuel = precedente.note_manuelle_motif if precedente else None
    if precedente is not None:
        await db.delete(precedente)
        await db.flush()

    enregistrement = NotationDb(
        candidature_id=candidature.id,
        total=notation.total,
        total_max=notation.total_max,
        seuil=notation.seuil,
        atteint_le_seuil=notation.atteint_le_seuil,
        bareme_utilise=bareme_vers_dict(bareme),
        note_manuelle=note_manuelle,
        note_manuelle_motif=motif_manuel,
    )
    # Les lignes passent par la relation plutôt que par des INSERT séparés :
    # l'objet renvoyé porte alors son détail en mémoire. Autrement, le premier
    # accès à `.lignes` déclencherait un lazy load — interdit hors contexte
    # greenlet, donc une erreur dans toute réponse d'API.
    enregistrement.lignes = [
        LigneNotation(
            code=ligne.code,
            libelle=ligne.libelle,
            points=ligne.points,
            points_max=ligne.points_max,
            detail=ligne.detail,
        )
        for ligne in notation.lignes
    ]
    db.add(enregistrement)
    await db.flush()
    return enregistrement


def _statut(
    candidature: Candidature,
    notation: Notation,
    provenances: dict[str, Provenance],
) -> StatutCandidature:
    """Le statut découle des motifs actifs, jamais d'une note seule.

    La relecture est exigée dans les deux sens, et pas seulement du côté des
    éliminations. Un dossier dont le parcours a été proposé par extraction et
    que personne n'a confirmé ne rejoint pas la présélection : il figurerait
    sinon dans la grille remise au client sur la foi d'un diplôme que nul n'a
    vérifié. Une qualification inventée est plus difficile à repérer qu'une
    élimination injuste, et elle voyage plus loin.
    """
    actifs = [e for e in candidature.eliminations if e.actif]
    if any(e.sur_donnee_non_verifiee for e in actifs):
        return StatutCandidature.A_VERIFIER
    if actifs:
        return StatutCandidature.ELIMINEE
    if any(p is Provenance.EXTRAIT_IA for p in provenances.values()):
        return StatutCandidature.A_VERIFIER
    if notation.atteint_le_seuil:
        return StatutCandidature.PRESELECTIONNEE
    return StatutCandidature.ELIGIBLE


def definir_seuil(poste: Poste, seuil: float, justification: str = "") -> None:
    """Change le seuil de présélection d'un poste.

    Passe par `DecisionSeuil` pour que la règle « abaisser exige une
    justification » soit appliquée partout, et pas seulement là où l'API pense
    à la vérifier. Relever le seuil ne demande rien : cela ne lèse personne.
    """
    decision = DecisionSeuil(
        seuil_retenu=seuil,
        seuil_nominal=float(poste.seuil_nominal),
        justification=justification,
    )
    poste.seuil_preselection = decision.seuil_retenu
    poste.seuil_justification = justification.strip() or None


async def evaluer_poste(db: AsyncSession, poste_id: str) -> int:
    """Réévalue toutes les candidatures d'un poste. Renvoie le nombre traité."""
    resultat = await db.execute(
        select(Candidature)
        .where(Candidature.poste_id == poste_id)
        .options(*_CHARGEMENT_COMPLET)
    )
    candidatures = list(resultat.scalars())
    for candidature in candidatures:
        await evaluer_candidature(db, candidature)
    return len(candidatures)
