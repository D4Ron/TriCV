"""Entretiens structurés : la seconde étape, et la note sur 100.

La présélection vaut 30 points et se calcule ; l'entretien en vaut 70 et se
juge. Ce module ne fait donc rien d'intelligent — il enregistre ce qu'un jury a
décidé, borne chaque note par son maximum, et additionne. C'est délibéré : la
seule chose qui compte ici est que le chiffre remis au client soit exactement
celui que des humains ont attribué.

Deux traits viennent directement des documents du cabinet :

- **Plusieurs jurés, une moyenne.** Un mandat récent a fait siéger sept membres
  de panel, et la note publiée est leur *Moyenne/100*. Chaque juré remplit donc
  sa propre fiche ; l'application les moyenne et montre l'écart.
- **La grille se négocie.** L'offre technique la qualifie de « grille de
  notation indicative » dont « les critères et la pondération seront validés
  par le client ». Elle se règle donc poste par poste, et se fige sur chaque
  fiche à la saisie.

Trois garde-fous, tous pour la même raison — un entretien se défend des mois
plus tard :

- **La grille est figée à la saisie.** `bareme_utilise` conserve la répartition
  en vigueur ce jour-là. La retoucher plus tard ne réécrit rien.
- **Un dossier éliminé ne se note pas.** Il faut d'abord lever le motif, ce qui
  laisse une trace.
- **Une saisie partielle reste partielle.** Tant qu'un critère manque, la note
  sur 100 est un acquis, pas un résultat.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import mean

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.bareme import (
    BAREME_ENTRETIEN,
    LigneEntretien as LigneBareme,
    NoteEntretien,
    NoteFinale,
    Notation as NotationDomaine,
    grille_entretien_depuis_liste,
    grille_entretien_vers_liste,
    note_finale,
    valider_grille_entretien,
)
from app.models import Candidature, Entretien, LigneEntretien, Poste, StatutCandidature

# Nom porté par une fiche quand personne n'a précisé de juré. Un panel d'une
# seule personne reste le cas courant sur les petits mandats.
JURE_PAR_DEFAUT = "Jury"


class EntretienRefuse(Exception):
    """Motif lisible par les RH : l'appelant le transforme en 409."""


def bareme_du_poste(poste: Poste | None) -> tuple[LigneBareme, ...]:
    """La grille en vigueur pour ce poste, ou celle du cabinet à défaut."""
    if poste is None:
        return BAREME_ENTRETIEN
    return grille_entretien_depuis_liste(poste.bareme_entretien)


def bareme_vers_liste(bareme: tuple[LigneBareme, ...]) -> list[dict]:
    return grille_entretien_vers_liste(bareme)


def bareme_depuis_liste(donnees: list[dict] | None) -> tuple[LigneBareme, ...]:
    return grille_entretien_depuis_liste(donnees)


def definir_grille(poste: Poste, donnees: list[dict] | None) -> tuple[LigneBareme, ...]:
    """Enregistre la grille négociée pour un poste. Ne commit pas.

    Passer None remet la grille type du cabinet, ce qui est la façon de revenir
    en arrière sans avoir à la retaper.
    """
    if donnees is None:
        poste.bareme_entretien = None
        return BAREME_ENTRETIEN

    grille = grille_entretien_depuis_liste(donnees)
    valider_grille_entretien(grille)
    poste.bareme_entretien = grille_entretien_vers_liste(grille)
    return grille


@dataclass(slots=True)
class SaisieEntretien:
    """Ce qu'un juré remet : des points par critère, et de quoi les situer."""

    notes: dict[str, float]
    commentaires: dict[str, str]
    jure: str = JURE_PAR_DEFAUT
    date_entretien: date | None = None
    jury: str = ""
    observations: str = ""


async def par_poste(db: AsyncSession, poste_id: str) -> dict[str, list[Entretien]]:
    """Les fiches d'entretien d'un poste, groupées par candidature.

    Sert à l'export : le tableau remis au cabinet a besoin du détail — les
    points critère par critère et ce qui a été observé — là où l'écran se
    contente du total. C'est cette matière-là qui sert à rédiger le rapport,
    que l'application ne rédige pas.
    """
    resultat = await db.execute(
        select(Entretien)
        .join(Candidature, Candidature.id == Entretien.candidature_id)
        .options(selectinload(Entretien.lignes))
        .where(Candidature.poste_id == poste_id)
        .order_by(Entretien.jure)
    )
    fiches: dict[str, list[Entretien]] = {}
    for entretien in resultat.scalars():
        fiches.setdefault(entretien.candidature_id, []).append(entretien)
    return fiches


async def charger(db: AsyncSession, candidature_id: str) -> list[Entretien]:
    """Toutes les fiches d'une candidature, un juré par fiche."""
    resultat = await db.execute(
        select(Entretien)
        .options(selectinload(Entretien.lignes))
        .where(Entretien.candidature_id == candidature_id)
        .order_by(Entretien.jure)
    )
    return list(resultat.scalars())


async def charger_une(
    db: AsyncSession, candidature_id: str, jure: str
) -> Entretien | None:
    resultat = await db.execute(
        select(Entretien)
        .options(selectinload(Entretien.lignes))
        .where(Entretien.candidature_id == candidature_id, Entretien.jure == jure)
    )
    return resultat.scalar_one_or_none()


def _refuser_si_elimine(candidature: Candidature) -> None:
    actifs = [e for e in candidature.eliminations if e.actif]
    if candidature.statut is StatutCandidature.ELIMINEE or actifs:
        motifs = ", ".join(sorted({e.motif.libelle for e in actifs})) or "motif actif"
        raise EntretienRefuse(
            f"Ce dossier est écarté ({motifs}). Levez le motif avant de saisir un "
            "entretien : convoquer un candidat éliminé se décide, cela ne se contourne pas."
        )


def valider(saisie: SaisieEntretien, bareme: tuple[LigneBareme, ...]) -> dict[str, float]:
    """Retient les critères connus, et refuse une note hors barème.

    Borner silencieusement serait pire que refuser : le juré croirait avoir mis
    la note qu'il a tapée, et la grille en afficherait une autre.
    """
    connus = {l.code: l for l in bareme}
    retenues: dict[str, float] = {}

    for code, valeur in saisie.notes.items():
        ligne = connus.get(code)
        if ligne is None:
            raise EntretienRefuse(f"Critère inconnu dans la grille d'entretien : {code}.")
        if valeur is None:
            continue
        note = float(valeur)
        if note < 0 or note > ligne.points_max:
            raise EntretienRefuse(
                f"« {ligne.libelle} » se note de 0 à {ligne.points_max:g} ; "
                f"{note:g} est hors barème."
            )
        retenues[code] = note

    return retenues


async def enregistrer(
    db: AsyncSession,
    candidature: Candidature,
    saisie: SaisieEntretien,
    user_id: str | None = None,
) -> Entretien:
    """Crée ou met à jour la fiche d'un juré. Ne commit pas.

    Les lignes sont remplacées en bloc : une fiche est un état, pas un journal
    d'ajouts. Effacer une note revient donc à ne plus l'envoyer.
    """
    _refuser_si_elimine(candidature)

    jure = (saisie.jure or JURE_PAR_DEFAUT).strip() or JURE_PAR_DEFAUT
    existant = await charger_une(db, candidature.id, jure)

    # Une fiche déjà ouverte garde sa grille : c'est celle sur laquelle ce juré
    # a délibéré, même si la répartition a changé depuis.
    bareme = (
        bareme_depuis_liste(existant.bareme_utilise)
        if existant
        else bareme_du_poste(candidature.poste)
    )
    notes = valider(saisie, bareme)

    entretien = existant
    if entretien is None:
        # Ajouté sans flush intermédiaire : sur un objet déjà persistant, la
        # collection `lignes` n'est pas chargée, et l'affecter déclencherait
        # une lecture — donc une erreur hors contexte greenlet.
        entretien = Entretien(candidature_id=candidature.id, jure=jure)
        db.add(entretien)

    entretien.date_entretien = saisie.date_entretien
    entretien.jury = saisie.jury.strip() or None
    entretien.observations = saisie.observations.strip() or None
    entretien.bareme_utilise = bareme_vers_liste(bareme)
    entretien.conduit_par_id = user_id

    if existant is not None:
        # Le flush est indispensable : SQLAlchemy émet les INSERT avant les
        # DELETE d'un même flush, si bien que les nouvelles lignes entreraient
        # en collision avec les anciennes sur uq_ligne_entretien_code.
        entretien.lignes.clear()
        await db.flush()

    entretien.lignes = [
        LigneEntretien(
            code=ligne.code,
            libelle=ligne.libelle,
            points=notes[ligne.code],
            points_max=ligne.points_max,
            commentaire=(saisie.commentaires.get(ligne.code) or "").strip() or None,
        )
        for ligne in bareme
        if ligne.code in notes
    ]
    await db.flush()
    return entretien


async def supprimer(db: AsyncSession, candidature_id: str, jure: str | None = None) -> int:
    """Efface une fiche saisie par erreur, ou toutes. Ne commit pas.

    Renvoie le nombre de fiches effacées.
    """
    fiches = await charger(db, candidature_id)
    if jure is not None:
        fiches = [f for f in fiches if f.jure == jure]
    for fiche in fiches:
        await db.delete(fiche)
    await db.flush()
    return len(fiches)


# --- lecture -----------------------------------------------------------------


@dataclass(slots=True)
class Consolidation:
    """Ce que plusieurs jurés donnent une fois réunis."""

    fiches: int = 0
    total: float = 0.0
    total_max: float = 0.0
    complet: bool = False
    # Écart entre le juré le plus sévère et le plus généreux : un panel très
    # dispersé mérite une relecture avant que la note ne parte au client.
    ecart: float = 0.0
    par_jure: dict[str, float] | None = None


def _arrondir(valeur: float) -> float:
    return round(valeur * 2) / 2


def consolider(
    entretiens: list[Entretien], bareme: tuple[LigneBareme, ...] | None = None
) -> Consolidation:
    """Moyenne les fiches des jurés, comme le fait le rapport du cabinet.

    Une fiche incomplète compte quand même — un juré peut n'avoir rempli qu'une
    partie — mais l'ensemble n'est déclaré complet que si chaque fiche l'est.
    """
    if not entretiens:
        return Consolidation(total_max=sum(l.points_max for l in (bareme or BAREME_ENTRETIEN)))

    totaux: dict[str, float] = {}
    complets: list[bool] = []
    maxima: list[float] = []

    for fiche in entretiens:
        grille = bareme_depuis_liste(fiche.bareme_utilise)
        note = NoteEntretien(points={l.code: float(l.points) for l in fiche.lignes})
        totaux[fiche.jure] = note.total(grille)
        complets.append(note.complete(grille))
        maxima.append(sum(l.points_max for l in grille))

    valeurs = list(totaux.values())
    return Consolidation(
        fiches=len(entretiens),
        total=_arrondir(mean(valeurs)),
        total_max=max(maxima),
        complet=all(complets),
        ecart=_arrondir(max(valeurs) - min(valeurs)) if len(valeurs) > 1 else 0.0,
        par_jure=totaux,
    )


def vers_note_domaine(
    entretiens: list[Entretien], bareme: tuple[LigneBareme, ...] | None = None
) -> NoteEntretien | None:
    """La moyenne du panel, exprimée dans le vocabulaire du domaine.

    Le domaine raisonne critère par critère ; on lui présente la moyenne comme
    un unique total, parce que répartir une moyenne de panel entre les critères
    n'aurait aucun sens — deux jurés peuvent arriver au même total par des
    chemins opposés.
    """
    if not entretiens:
        return None
    return NoteEntretien(points={"_TOTAL": consolider(entretiens, bareme).total})


def calculer_note_finale(
    notation: NotationDomaine, entretiens: list[Entretien]
) -> NoteFinale:
    """Combine la présélection et la moyenne du panel en une note sur 100."""
    if not entretiens:
        return note_finale(notation, None)

    consolidation = consolider(entretiens)
    # Grille à une seule ligne portant le total du panel : le combinateur borne
    # et convertit, il n'a pas besoin du détail par critère.
    grille = (LigneBareme("_TOTAL", "Entretien", consolidation.total_max),)
    resultat = note_finale(notation, NoteEntretien(points={"_TOTAL": consolidation.total}), grille)

    # `complete()` sur une grille à une ligne dirait toujours « complet » ; la
    # vérité vient des fiches elles-mêmes.
    return NoteFinale(
        preselection_sur_cent=resultat.preselection_sur_cent,
        entretien_sur_cent=resultat.entretien_sur_cent,
        total_sur_cent=resultat.total_sur_cent,
        entretien_complet=consolidation.complet,
    )


def notation_depuis_base(notation_db) -> NotationDomaine | None:
    """Reconstruit juste ce qu'il faut du domaine pour combiner les deux notes.

    Le détail des lignes n'entre pas dans la note sur 100 : seuls comptent le
    total retenu, le maximum et le poids. On évite ainsi de recharger tout un
    dossier pour afficher un chiffre.
    """
    if notation_db is None:
        return None
    # Le poids vient du barème figé au moment de la notation, pas du barème
    # courant : une grille rendue sous une pondération 30/70 doit continuer de
    # se lire ainsi même si le cabinet change de répartition ensuite.
    fige = notation_db.bareme_utilise or {}
    return NotationDomaine(
        lignes=(),
        total=float(notation_db.note_retenue),
        total_max=float(notation_db.total_max),
        seuil=float(notation_db.seuil),
        poids_note_finale=float(fige.get("poids_note_finale", 30.0)),
    )
