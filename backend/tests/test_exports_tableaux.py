"""Les tableaux du rapport sont de vrais tableaux dans les documents remis.

Ils étaient alignés à l'espace, en texte, et chaque ligne partait dans le DOCX
comme un paragraphe en Calibri — une police à chasse variable. Les colonnes s'y
décalaient les unes après les autres : la grille remise au client, celle-là
même qu'il avait validée avant le lancement, arrivait en escalier.

Ce fichier vérifie donc deux choses. Que la structure est produite — rubriques
et sous-critères compris, puisque c'est la hiérarchie de la grille signée. Et
que chaque format la dessine avec ses propres moyens plutôt qu'avec des
espaces.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime

import pytest
from docx import Document

from app.services import rapports
from app.services.exports import rapport as export

CHIFFRES = {
    "mandat": {"intitule": "Cadres 2026", "client": "WAPP"},
    "postes": [
        {
            "id": "p1",
            "intitule": "Directeur Administratif et Financier",
            "grille_preselection": [
                {"code": "CONSISTANCE", "libelle": "Consistance du dossier", "points_max": 3},
                {"code": "FORMATION", "libelle": "Formation académique", "points_max": 7},
                {"code": "TOTAL", "libelle": "Total", "points_max": 30},
            ],
            # Une grille à rubriques, comme celles que certains clients
            # négocient : « II. Expérience professionnelle : 45 ».
            "grille_entretien": [
                {"code": "PRES", "libelle": "Présentation", "points_max": 5.0,
                 "section": "I. Présentation générale"},
                {"code": "EXPR", "libelle": "Expérience du secteur", "points_max": 20.0,
                 "section": "II. Expérience professionnelle"},
                {"code": "TECH", "libelle": "Compétences techniques", "points_max": 45.0,
                 "section": "II. Expérience professionnelle"},
            ],
            "candidatures_recues": 3,
            "preselectionnees": 1,
            "eliminees": 2,
            "classement": [],
        }
    ],
}


def grille() -> list[rapports.Tableau]:
    return rapports.grille_de_notation(CHIFFRES)


def sections_calculees() -> list[dict]:
    """Ce que `rediger_sections` enregistre pour une section calculée."""
    tableaux = grille()
    return [
        {
            "code": "GRILLE_DE_NOTATION",
            "titre": "Grilles de notation",
            "contenu": rapports.texte_des_tableaux(tableaux),
            "tableaux": [t.en_dict() for t in tableaux],
            "origine": rapports.ORIGINE_CALCULEE,
        }
    ]


# --- la structure -----------------------------------------------------------


def test_la_grille_produit_un_tableau_par_grille():
    """Deux grilles, deux tableaux.

    Le récapitulatif 30+70 qui les suivait a été retiré : il ne figure pas
    dans le document remis, où chaque grille porte déjà son total.
    """
    titres = [t.titre for t in grille()]
    assert titres == [
        "Grille de présélection — Directeur Administratif et Financier",
        "Grille de notation — Directeur Administratif et Financier",
    ]


def test_les_rubriques_portent_leur_total_et_precedent_leurs_criteres():
    """« II » vaut 65 : 20 + 45, et ses critères sont 2.1 et 2.2.

    Un client qui relit la grille vérifie d'abord les totaux de rubrique ; les
    aplatir l'obligeait à les recalculer de tête.
    """
    entretien = grille()[1]

    assert [l.cellules for l in entretien.lignes] == [
        ("I", "I. PRÉSENTATION GÉNÉRALE", "5"),
        ("1.1", "Présentation", "5"),
        ("II", "II. EXPÉRIENCE PROFESSIONNELLE", "65"),
        ("2.1", "Expérience du secteur", "20"),
        ("2.2", "Compétences techniques", "45"),
        ("", "TOTAL", "70"),
    ]
    assert [l.genre for l in entretien.lignes] == [
        rapports.GENRE_RUBRIQUE,
        rapports.GENRE_DETAIL,
        rapports.GENRE_RUBRIQUE,
        rapports.GENRE_DETAIL,
        rapports.GENRE_DETAIL,
        rapports.GENRE_TOTAL,
    ]


def test_la_ligne_de_total_est_marquee_comme_telle():
    preselection = grille()[0]
    assert preselection.lignes[-1].genre == rapports.GENRE_TOTAL
    assert preselection.lignes[0].genre == rapports.GENRE_NORMAL


def test_une_colonne_de_points_est_numerique():
    """C'est ce qui l'aligne à droite dans les trois formats de mise en page."""
    preselection = grille()[0]
    assert [c.numerique for c in preselection.colonnes] == [False, True]


def test_le_texte_reste_produit_comme_repli():
    texte = rapports.texte_des_tableaux(grille())
    assert "Consistance du dossier" in texte
    assert "II. EXPÉRIENCE PROFESSIONNELLE" in texte
    # Le sous-critère se lit en retrait, ce que la mise en page rend autrement.
    assert "   2.1" in texte


# --- les formats ------------------------------------------------------------


def test_le_docx_porte_de_vraies_tables():
    octets = export.rendre_docx("Rapport", "WAPP", sections_calculees(), datetime(2026, 9, 10))
    document = Document(io.BytesIO(octets))

    assert len(document.tables) == 2, "une table par grille"

    entretien = document.tables[1]
    assert [c.text for c in entretien.rows[0].cells] == [
        "",
        "Critères d'appréciation",
        "Notes",
    ]
    libelles = [ligne.cells[1].text for ligne in entretien.rows]
    assert "II. EXPÉRIENCE PROFESSIONNELLE" in libelles
    assert "Compétences techniques" in libelles
    # Le retrait remplace les espaces : le libellé lui-même n'en porte plus.
    assert not any(c.startswith("   ") for c in libelles)
    # Et la numérotation du document remis est là.
    assert [ligne.cells[0].text for ligne in entretien.rows] == [
        "", "I", "1.1", "II", "2.1", "2.2", "",
    ]


def test_une_rubrique_et_un_total_sont_en_gras_dans_le_docx():
    octets = export.rendre_docx("Rapport", "WAPP", sections_calculees(), datetime(2026, 9, 10))
    document = Document(io.BytesIO(octets))
    entretien = document.tables[1]

    par_libelle = {l.cells[1].text: l for l in entretien.rows}
    for remarquable in ("II. EXPÉRIENCE PROFESSIONNELLE", "TOTAL"):
        run = par_libelle[remarquable].cells[1].paragraphs[0].runs[0]
        assert run.font.bold, f"{remarquable} devrait ressortir"

    ordinaire = par_libelle["Compétences techniques"].cells[1].paragraphs[0].runs[0]
    assert not ordinaire.font.bold


def test_l_odt_porte_de_vraies_tables():
    octets = export.rendre_odt("Rapport", "WAPP", sections_calculees(), datetime(2026, 9, 10))
    with zipfile.ZipFile(io.BytesIO(octets)) as archive:
        contenu = archive.read("content.xml").decode()

    assert contenu.count("<table:table ") == 2
    assert "<table:table-header-rows>" in contenu
    assert "II. EXPÉRIENCE PROFESSIONNELLE" in contenu


def test_le_pdf_se_produit_avec_ses_tables():
    """Un PDF ne se relit pas ligne à ligne : ce qui compte est qu'il sorte."""
    octets = export.rendre_pdf("Rapport", "WAPP", sections_calculees(), datetime(2026, 9, 10))
    assert octets.startswith(b"%PDF")
    assert len(octets) > 1500


def test_le_txt_garde_l_alignement_a_l_espace():
    """Là, la chasse est fixe : l'alignement est le bon outil."""
    octets = export.rendre_txt("Rapport", "WAPP", sections_calculees(), datetime(2026, 9, 10))
    texte = octets.decode("utf-8")
    assert "Consistance du dossier" in texte
    assert "----" in texte


# --- les rapports produits avant la structure -------------------------------


@pytest.mark.parametrize(
    "rendu", [export.rendre_docx, export.rendre_pdf, export.rendre_odt, export.rendre_txt]
)
def test_une_section_sans_tableaux_retombe_sur_son_texte(rendu):
    """Un rapport déjà en base n'a pas la structure. Il doit sortir quand même."""
    ancienne = [
        {
            "code": "GRILLE_DE_NOTATION",
            "titre": "Grilles de notation",
            "contenu": "Critère  Points\n-------  ------\nFormation  7",
            "origine": rapports.ORIGINE_CALCULEE,
        }
    ]
    octets = rendu("Rapport", "WAPP", ancienne, datetime(2026, 9, 10))
    assert octets
