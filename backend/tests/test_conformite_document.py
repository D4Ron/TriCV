"""Le rapport produit a la structure du rapport que le cabinet remet.

Relevée sur « Rapport des entretiens - WAPP 2025 », le document réel. Ce n'est
pas une trame inspirée de lui : c'est la sienne, titres, ordre, niveaux,
colonnes et mention finale compris.

Le document lui-même ne peut pas servir de référence automatique — il porte de
vraies données de candidats et n'a rien à faire dans un dépôt. Sa structure est
donc recopiée ici, à la main, et c'est elle qui fait foi. Quand le cabinet
change son modèle, c'est ce fichier qu'on met à jour, et les écarts sautent aux
yeux au lieu de se découvrir à la remise.

Ce fichier couvre le **corps** : les titres, leur ordre, leurs niveaux, les
colonnes des tableaux, la mention finale. Ce qui l'entoure dans le document
remis — page de garde à l'en-tête du cabinet, sommaire, numérotation des
titres — est relevé de la même façon dans `test_frontispice_rapport.py`.
"""

from __future__ import annotations

import pytest

from app.services import rapports

# --- ce qui est relevé sur le document remis --------------------------------

TITRES_ATTENDUS: list[tuple[str, int]] = [
    ("Introduction", 1),
    ("Démarche", 1),
    ("Objectifs de la mission", 1),
    ("Méthodologie", 1),
    ("Présélection", 2),
    ("Critères éliminatoires et Condition de Présélection", 2),
    ("Résultats de la présélection", 1),
    ("Liste des candidats présélectionnés", 2),
    ("Entretiens structurés", 1),
    ("Adoption du guide d'interview et la grille de notation", 2),
    ("Validation du jury de sélection et conduite des interviews", 2),
    ("Résultats des entretiens structurés", 2),
]

COLONNES_EFFECTIFS = [
    "Postes",
    "Nombre de dossiers analysés",
    "Effectif Préqualifié",
    "Nombre de candidats éliminés",
]

COLONNES_PREQUALIFIES = [
    "Nom & Prénoms",
    "Age",
    "Diplôme",
    "Pays",
    "Présélection Note/100",
    "Rang",
    "Téléphone",
    "E-mail",
]

COLONNES_RESULTATS = ["Nom & Prénoms", "PAYS", "Moyenne/100", "Rang"]


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
            "grille_entretien": [
                {"code": "PRES", "libelle": "Présentation", "points_max": 3.0,
                 "section": "Présentation et motivation"},
                {"code": "MOTIV", "libelle": "Motivation", "points_max": 2.0,
                 "section": "Présentation et motivation"},
                {"code": "EXPR", "libelle": "Expérience du secteur", "points_max": 45.0,
                 "section": "Expérience professionnelle"},
            ],
            "candidatures_recues": 64,
            "preselectionnees": 33,
            "eliminees": 31,
            "classement": [],
        }
    ],
}


# --- la trame ---------------------------------------------------------------


def test_les_titres_et_leurs_niveaux_sont_ceux_du_document():
    produits = [(s.titre, s.niveau) for s in rapports.trame_pour(rapports.TypeRapport.FINAL)]
    assert produits == TITRES_ATTENDUS


def test_le_rapport_ne_porte_pas_de_conclusion():
    """Le document du cabinet se termine sur le tableau et la mention d'annexe.

    Une « Conclusion » ajoutée d'office obligeait à supprimer à la main une
    section que le client n'attend pas.
    """
    codes = [s.code for s in rapports.TRAME]
    assert "CONCLUSION" not in codes


def test_methodologie_est_un_titre_porteur():
    """Elle n'a pas de texte à elle : ses deux sous-sections disent tout."""
    methodologie = rapports.PAR_CODE["METHODOLOGIE"]
    assert methodologie.calculee and not methodologie.consigne
    assert methodologie.niveau == 1


def test_un_rapport_de_preselection_s_arrete_avant_les_entretiens():
    titres = [s.titre for s in rapports.trame_pour(rapports.TypeRapport.PRESELECTION)]
    assert titres[-1] == "Liste des candidats présélectionnés"
    assert "Entretiens structurés" not in titres


# --- les tableaux, à leur place ---------------------------------------------


def test_le_tableau_des_effectifs_est_dans_la_section_des_resultats():
    """Il n'a pas d'intertitre à lui dans le document remis."""
    section = rapports.PAR_CODE["RESULTATS_PRESELECTION"]
    assert section.tableaux == "SYNTHESE_EFFECTIFS"
    assert section.consigne, "la section porte aussi de la prose"


def test_les_colonnes_du_tableau_des_effectifs():
    tableau = rapports.tableau_synthese(CHIFFRES)[0]
    assert [c.libelle for c in tableau.colonnes] == COLONNES_EFFECTIFS
    assert tableau.titre == "", "dans le document, ce tableau n'a pas de légende"


def test_les_colonnes_du_tableau_des_prequalifies():
    donnees = {
        "postes": [
            {
                **CHIFFRES["postes"][0],
                "classement": [
                    {
                        "nom": "SANKHARE Ousseynou",
                        "age": 44,
                        "diplome": "Master en ingénierie financière",
                        "pays": "Sénégalaise",
                        "telephone": "+228 90 11 22 33",
                        "email": "o.sankhare@example.tg",
                        "statut": "PRESELECTIONNEE",
                        "preselection_sur_100": 86.0,
                        "rang_libelle": "1er",
                    }
                ],
            }
        ]
    }
    tableau = rapports.tableau_preselection(donnees)[0]
    assert [c.libelle for c in tableau.colonnes] == COLONNES_PREQUALIFIES


def test_les_colonnes_du_tableau_des_resultats():
    """Quatre colonnes, comme le document. Le détail part en annexe."""
    donnees = {
        "postes": [
            {
                **CHIFFRES["postes"][0],
                "classement": [
                    {
                        "nom": "SANKHARE Ousseynou",
                        "pays": "Sénégalaise",
                        "total_100": 86.0,
                        "part_preselection": 26.0,
                        "part_entretien": 60.0,
                    }
                ],
            }
        ]
    }
    tableau = rapports.tableau_final(donnees)[0]
    assert [c.libelle for c in tableau.colonnes] == COLONNES_RESULTATS


# --- la grille d'entretien, numérotée ---------------------------------------


def test_la_grille_d_entretien_est_numerotee_comme_dans_le_document():
    """« I / PRESENTATION ET MOTIVATION / 5 » puis « 1.1 / Présentation / 3 ».

    La numérotation dit qu'un critère appartient à une rubrique. C'est sous
    cette forme que le client a signé la grille.
    """
    tableau = rapports.grille_entretien_tableau(CHIFFRES)[0]

    assert [c.libelle for c in tableau.colonnes] == ["", "Critères d'appréciation", "Notes"]
    assert [l.cellules for l in tableau.lignes] == [
        ("I", "PRÉSENTATION ET MOTIVATION", "5"),
        ("1.1", "Présentation", "3"),
        ("1.2", "Motivation", "2"),
        ("II", "EXPÉRIENCE PROFESSIONNELLE", "45"),
        ("2.1", "Expérience du secteur", "45"),
        ("", "TOTAL", "50"),
    ]


def test_une_grille_plate_garde_deux_colonnes():
    """La numérotation sert à montrer une hiérarchie. Sans rubrique, elle ne
    montrerait rien et ajouterait une colonne vide."""
    plate = {
        "postes": [
            {
                "intitule": "Chef comptable",
                "grille_entretien": [
                    {"code": "A", "libelle": "Présentation", "points_max": 2.0, "section": ""},
                    {"code": "B", "libelle": "Motivation", "points_max": 2.0, "section": ""},
                ],
            }
        ]
    }
    tableau = rapports.grille_entretien_tableau(plate)[0]
    assert [c.libelle for c in tableau.colonnes] == ["Critères d'appréciation", "Notes"]
    assert tableau.lignes[-1].cellules == ("TOTAL", "4")


def test_la_grille_de_preselection_a_sa_propre_section():
    section = rapports.PAR_CODE["METHODE_PRESELECTION"]
    assert section.tableaux == "GRILLE_PRESELECTION"
    assert section.niveau == 2


# --- jeter un brouillon ------------------------------------------------------


API = "/api/v1"


async def _mandat(client, auth) -> str:
    client_id = (
        await client.post(f"{API}/clients", json={"nom": "WAPP"}, headers=auth)
    ).json()["id"]
    return (
        await client.post(
            f"{API}/mandats",
            json={"client_id": client_id, "intitule": "Cadres 2026"},
            headers=auth,
        )
    ).json()["id"]


@pytest.mark.anyio
async def test_un_brouillon_se_supprime(client, auth):
    """La génération crée un rapport à chaque appel, volontairement.

    Rien ne permettait ensuite de retirer celui qu'on venait de produire par
    erreur, et l'onglet accumulait des doublons qu'il fallait supprimer en base.
    """
    mandat_id = await _mandat(client, auth)
    rapport = (
        await client.post(
            f"{API}/mandats/{mandat_id}/rapports",
            json={"avec_assistance": False},
            headers=auth,
        )
    ).json()

    efface = await client.delete(f"{API}/rapports/{rapport['id']}", headers=auth)
    assert efface.status_code == 204

    restants = (await client.get(f"{API}/mandats/{mandat_id}/rapports", headers=auth)).json()
    assert rapport["id"] not in [r["id"] for r in restants]


@pytest.mark.anyio
async def test_un_rapport_valide_ne_se_supprime_pas(client, auth):
    """Un document remis au client ne s'efface pas d'un clic.

    Il se retire du partage, ce qui est un geste différent et réversible.
    """
    mandat_id = await _mandat(client, auth)
    rapport = (
        await client.post(
            f"{API}/mandats/{mandat_id}/rapports",
            json={"avec_assistance": False},
            headers=auth,
        )
    ).json()
    await client.post(f"{API}/rapports/{rapport['id']}/valider", headers=auth)

    refus = await client.delete(f"{API}/rapports/{rapport['id']}", headers=auth)
    assert refus.status_code == 409
    assert "partage" in refus.json()["detail"]
