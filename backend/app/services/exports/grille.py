"""Export tableur de la grille de présélection.

Le fichier reproduit le document de travail : un en-tête qui rappelle le
mandat, le poste et les paramètres du calcul, puis la grille, le tableau
d'élimination subdivisé par motif, et une synthèse.

L'en-tête n'est pas décoratif : une grille sans son seuil, sa date de clôture
et sa référence d'avis n'est pas relisable six mois plus tard, et c'est
précisément ce qu'on ressort quand une décision est contestée.
"""

from __future__ import annotations

import io
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.domain.referentiel import NiveauDiplome
from app.models import Poste
from app.schemas.recrutement import GrilleOut, LigneGrille

ENCRE = "1F2933"
REMPLISSAGE_ENTETE = PatternFill("solid", fgColor=ENCRE)
POLICE_ENTETE = Font(bold=True, color="FFFFFF", size=10)
POLICE_TITRE = Font(bold=True, size=14, color=ENCRE)
POLICE_SECTION = Font(bold=True, size=11, color=ENCRE)
POLICE_DISCRETE = Font(size=9, color="6B7280")
FILET = Side(style="thin", color="D7DCE2")
BORDURE = Border(bottom=FILET)

COLONNES = (
    ("Nom", 18),
    ("Prénom", 16),
    ("Âge", 7),
    ("Nationalité", 16),
    ("Dernier diplôme", 30),
    ("École / Université", 26),
    ("Structure / Employeur", 26),
    ("Adresse", 22),
    ("Note", 10),
    ("Présélectionné", 14),
    ("Éliminé", 10),
    ("Motifs", 34),
)

LIBELLE_TYPE_AVIS = {
    "NATIONAL": "Avis national",
    "INTERNATIONAL": "Avis international",
    "GRE_A_GRE": "Gré à gré",
}


def _styler_entete(feuille: Worksheet, ligne: int, nombre: int) -> None:
    for colonne in range(1, nombre + 1):
        cellule = feuille.cell(row=ligne, column=colonne)
        cellule.fill = REMPLISSAGE_ENTETE
        cellule.font = POLICE_ENTETE
        cellule.alignment = Alignment(vertical="center", wrap_text=True)
    feuille.row_dimensions[ligne].height = 28


def _largeurs(feuille: Worksheet) -> None:
    for index, (_, largeur) in enumerate(COLONNES, start=1):
        feuille.column_dimensions[get_column_letter(index)].width = largeur


def _bloc_identification(feuille: Worksheet, grille: GrilleOut, poste: Poste) -> int:
    """En-tête du document. Renvoie la première ligne libre."""
    feuille["A1"] = "Grille de présélection"
    feuille["A1"].font = POLICE_TITRE

    niveau = NiveauDiplome(poste.niveau_min).libelle
    lignes = [
        ("Client", grille.client_nom or "—"),
        ("Mandat", grille.mandat_intitule or "—"),
        ("Poste", grille.poste_intitule),
        (
            "Avis",
            " · ".join(
                filter(
                    None,
                    (
                        grille.reference_avis,
                        LIBELLE_TYPE_AVIS.get(
                            grille.type_avis.value if grille.type_avis else "", None
                        ),
                    ),
                )
            )
            or "—",
        ),
        (
            "Date de clôture",
            grille.date_reference.strftime("%d/%m/%Y") if grille.date_reference else "—",
        ),
        ("Profil exigé", f"{niveau}, {poste.annees_experience_min} an(s) d'expérience"),
        (
            "Dont expérience spécifique",
            f"{poste.annees_experience_specifique_min} an(s)",
        ),
        ("Seuil de présélection", f"{grille.seuil:g} / {grille.total_max:g}"),
        ("Édité le", date.today().strftime("%d/%m/%Y")),
    ]

    ligne = 3
    for intitule, valeur in lignes:
        feuille.cell(row=ligne, column=1, value=intitule).font = Font(bold=True, size=10)
        feuille.cell(row=ligne, column=2, value=valeur)
        ligne += 1

    if poste.seuil_justification:
        # Un seuil abaissé change qui est retenu : la raison voyage avec le
        # fichier plutôt que de rester dans le journal applicatif.
        feuille.cell(row=ligne, column=1, value="Seuil abaissé").font = Font(bold=True, size=10)
        feuille.cell(row=ligne, column=2, value=poste.seuil_justification)
        ligne += 1

    if poste.restriction_justification:
        feuille.cell(row=ligne, column=1, value="Poste restreint").font = Font(
            bold=True, size=10
        )
        feuille.cell(row=ligne, column=2, value=poste.restriction_justification)
        ligne += 1

    return ligne + 1


def _ecrire_lignes(feuille: Worksheet, depart: int, lignes: list[LigneGrille]) -> int:
    for decalage, item in enumerate(lignes):
        rang = depart + decalage
        valeurs = (
            item.nom,
            item.prenom,
            item.age,
            item.nationalite,
            item.dernier_diplome,
            item.ecole_universite,
            item.structure_employeur,
            item.adresse,
            item.note,
            "Oui" if item.preselectionne else "",
            "Oui" if item.elimine else "",
            ", ".join(item.motifs),
        )
        for colonne, valeur in enumerate(valeurs, start=1):
            cellule = feuille.cell(row=rang, column=colonne, value=valeur)
            cellule.border = BORDURE
            if colonne in (3, 9):
                cellule.alignment = Alignment(horizontal="center")
    return depart + len(lignes)


def _feuille_grille(classeur: Workbook, grille: GrilleOut, poste: Poste) -> None:
    feuille = classeur.active
    feuille.title = "Grille de présélection"
    _largeurs(feuille)

    ligne = _bloc_identification(feuille, grille, poste)

    for titre, lot in (
        ("Présélectionnés", grille.preselectionnes),
        ("Non retenus (sous le seuil)", grille.non_retenus),
    ):
        feuille.cell(row=ligne, column=1, value=f"{titre} ({len(lot)})").font = POLICE_SECTION
        ligne += 1

        for index, (intitule, _) in enumerate(COLONNES, start=1):
            feuille.cell(row=ligne, column=index, value=intitule)
        _styler_entete(feuille, ligne, len(COLONNES))
        ligne += 1

        if lot:
            ligne = _ecrire_lignes(feuille, ligne, lot)
        else:
            feuille.cell(row=ligne, column=1, value="Aucun dossier").font = POLICE_DISCRETE
            ligne += 1
        ligne += 1

    # Les en-têtes restent visibles au défilement : une grille de deux cents
    # lignes se lit mal autrement.
    feuille.freeze_panes = "A3"


def _feuille_elimination(classeur: Workbook, grille: GrilleOut) -> None:
    feuille = classeur.create_sheet("Tableau d'élimination")
    _largeurs(feuille)

    feuille["A1"] = "Tableau d'élimination"
    feuille["A1"].font = POLICE_TITRE
    feuille["A2"] = (
        "Un dossier peut figurer sous plusieurs motifs : chaque motif est une règle distincte."
    )
    feuille["A2"].font = POLICE_DISCRETE

    ligne = 4
    if not grille.elimines:
        feuille.cell(row=ligne, column=1, value="Aucun dossier éliminé").font = POLICE_DISCRETE
        return

    for groupe in grille.elimines:
        feuille.cell(
            row=ligne, column=1, value=f"{groupe.libelle} ({len(groupe.lignes)})"
        ).font = POLICE_SECTION
        ligne += 1

        for index, (intitule, _) in enumerate(COLONNES, start=1):
            feuille.cell(row=ligne, column=index, value=intitule)
        _styler_entete(feuille, ligne, len(COLONNES))
        ligne += 1

        ligne = _ecrire_lignes(feuille, ligne, groupe.lignes) + 1


def _feuille_synthese(classeur: Workbook, grille: GrilleOut) -> None:
    feuille = classeur.create_sheet("Synthèse")
    feuille.column_dimensions["A"].width = 34
    feuille.column_dimensions["B"].width = 16

    feuille["A1"] = "Synthèse"
    feuille["A1"].font = POLICE_TITRE

    lignes = [
        ("Candidatures reçues", grille.nombre_candidatures),
        ("Présélectionnés", grille.nombre_preselectionnes),
        ("Non retenus (sous le seuil)", len(grille.non_retenus)),
        ("Éliminés", grille.nombre_elimines),
        ("En attente de vérification", grille.nombre_a_verifier),
    ]
    ligne = 3
    for intitule, valeur in lignes:
        feuille.cell(row=ligne, column=1, value=intitule).font = Font(bold=True, size=10)
        feuille.cell(row=ligne, column=2, value=valeur).alignment = Alignment(
            horizontal="center"
        )
        ligne += 1

    ligne += 1
    feuille.cell(row=ligne, column=1, value="Répartition des motifs").font = POLICE_SECTION
    ligne += 1
    for groupe in grille.elimines:
        feuille.cell(row=ligne, column=1, value=groupe.libelle)
        feuille.cell(row=ligne, column=2, value=len(groupe.lignes)).alignment = Alignment(
            horizontal="center"
        )
        ligne += 1

    if grille.nombre_a_verifier:
        ligne += 1
        cellule = feuille.cell(
            row=ligne,
            column=1,
            value=(
                f"{grille.nombre_a_verifier} dossier(s) reposent sur des données extraites "
                "automatiquement et non confirmées. Ils ne sont éliminés par personne tant "
                "qu'un relecteur ne les a pas validés."
            ),
        )
        cellule.font = POLICE_DISCRETE
        cellule.alignment = Alignment(wrap_text=True, vertical="top")


def construire_classeur(grille: GrilleOut, poste: Poste) -> bytes:
    classeur = Workbook()
    _feuille_grille(classeur, grille, poste)
    _feuille_elimination(classeur, grille)
    _feuille_synthese(classeur, grille)

    tampon = io.BytesIO()
    classeur.save(tampon)
    return tampon.getvalue()
