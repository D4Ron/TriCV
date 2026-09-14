"""Plusieurs expériences spécifiques, certifications, formation complémentaire.

Trois ajouts à la fiche de poste, et une même règle pour les trois : ils ne
changent rien tant que le poste ne les déclare pas. La répartition 3/7/5/15
vient des documents du cabinet ; aucune de ces nouveautés n'y touche.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from app.domain import (
    BAREME_PAR_DEFAUT,
    BaremeFormation,
    Diplome,
    ExigenceSpecifique,
    ExigencesPoste,
    Experience,
    NiveauDiplome,
    ProfilCandidat,
    evaluer_eligibilite,
    noter,
)
from app.domain.referentiel import MotifElimination

CLOTURE = date(2026, 7, 31)


def exigences(**overrides) -> ExigencesPoste:
    base = {
        "niveau_min": NiveauDiplome.BAC_PLUS_4,
        "domaines_acceptes": frozenset({"droit"}),
        "annees_experience_min": 10,
        "date_reference": CLOTURE,
    }
    return ExigencesPoste(**{**base, **overrides})


def experience(domaine: str, depuis: date, jusqu_a: date) -> Experience:
    return Experience("Chargé", f"Employeur {domaine}", depuis, jusqu_a, frozenset({domaine}))


def profil(*experiences: Experience, **overrides) -> ProfilCandidat:
    base = {
        "nom": "Kodjo",
        "prenom": "Amina",
        "diplomes": (Diplome("Master en droit", NiveauDiplome.BAC_PLUS_5, "droit"),),
        "experiences": experiences,
    }
    return ProfilCandidat(**{**base, **overrides})


def lignes_specifiques(notation):
    return [l for l in notation.lignes if l.code.startswith("EXPERIENCE_SPECIFIQUE")]


# --- une seule exigence : rien ne bouge --------------------------------------


def test_une_exigence_unique_garde_le_code_et_les_points_d_origine():
    """Les grilles remises, les exports et les rapports lisent ce code."""
    exig = exigences(
        annees_experience_specifique_min=5, domaines_experience=frozenset({"marches"})
    )
    notation = noter(profil(experience("marches", date(2014, 1, 1), date(2026, 1, 1))), exig)

    specifiques = lignes_specifiques(notation)
    assert len(specifiques) == 1
    assert specifiques[0].code == "EXPERIENCE_SPECIFIQUE"
    assert specifiques[0].libelle == "Expérience spécifique"
    assert specifiques[0].points_max == 15.0


# --- plusieurs exigences -----------------------------------------------------


def test_les_quinze_points_se_partagent_sans_deborder():
    exig = exigences(
        experiences_specifiques=(
            ExigenceSpecifique("passation des marchés", frozenset({"marches"}), 5),
            ExigenceSpecifique("gestion de projet", frozenset({"projet"}), 3),
        )
    )
    notation = noter(
        profil(
            experience("marches", date(2014, 1, 1), date(2026, 1, 1)),
            experience("projet", date(2014, 1, 1), date(2026, 1, 1)),
        ),
        exig,
    )

    specifiques = lignes_specifiques(notation)
    assert [l.code for l in specifiques] == [
        "EXPERIENCE_SPECIFIQUE_1",
        "EXPERIENCE_SPECIFIQUE_2",
    ]
    assert sum(l.points_max for l in specifiques) == 15.0
    assert sum(l.points for l in specifiques) <= 15.0
    assert notation.total <= notation.total_max


def test_le_poids_repartit_les_points():
    exig = exigences(
        experiences_specifiques=(
            ExigenceSpecifique("métier principal", frozenset({"marches"}), 5, poids=2.0),
            ExigenceSpecifique("métier secondaire", frozenset({"projet"}), 3, poids=1.0),
        )
    )
    notation = noter(profil(), exig)
    principal, secondaire = lignes_specifiques(notation)
    assert principal.points_max == 10.0
    assert secondaire.points_max == 5.0


def test_la_ligne_nomme_l_exigence():
    """Deux lignes « Expérience spécifique » identiques seraient illisibles."""
    exig = exigences(
        experiences_specifiques=(
            ExigenceSpecifique("passation des marchés", frozenset({"marches"}), 5),
            ExigenceSpecifique("gestion de projet", frozenset({"projet"}), 3),
        )
    )
    libelles = [l.libelle for l in lignes_specifiques(noter(profil(), exig))]
    assert libelles == [
        "Expérience spécifique — passation des marchés",
        "Expérience spécifique — gestion de projet",
    ]


def test_tout_faire_dans_un_seul_domaine_ne_suffit_plus():
    """C'est la raison d'être de la liste.

    Réunies en un seul jeu de domaines, les deux exigences n'en faisaient
    qu'une : douze ans de marchés couvraient à la fois les cinq ans de marchés
    et les trois ans de gestion de projet, et un candidat n'ayant jamais
    conduit de projet passait la barre.
    """
    exig = exigences(
        experiences_specifiques=(
            ExigenceSpecifique("passation des marchés", frozenset({"marches"}), 5),
            ExigenceSpecifique("gestion de projet", frozenset({"projet"}), 3),
        )
    )
    motifs = evaluer_eligibilite(
        profil(experience("marches", date(2014, 1, 1), date(2026, 1, 1))), exig
    )

    manquants = [m for m in motifs if m.motif is MotifElimination.EXPERIENCE_SPECIFIQUE_INSUFFISANTE]
    assert len(manquants) == 1, "un seul motif : la table n'accepte qu'une ligne par code"
    assert "gestion de projet" in manquants[0].attendu
    assert "passation des marchés" not in manquants[0].attendu


def test_le_motif_enumere_tous_les_manquements():
    exig = exigences(
        experiences_specifiques=(
            ExigenceSpecifique("passation des marchés", frozenset({"marches"}), 5),
            ExigenceSpecifique("gestion de projet", frozenset({"projet"}), 3),
        )
    )
    motifs = evaluer_eligibilite(profil(), exig)
    manquant = next(
        m for m in motifs if m.motif is MotifElimination.EXPERIENCE_SPECIFIQUE_INSUFFISANTE
    )
    assert "passation des marchés" in manquant.attendu
    assert "gestion de projet" in manquant.attendu
    assert "passation des marchés" in manquant.constate


def test_une_exigence_sans_seuil_se_note_sans_jamais_eliminer():
    """Zéro année demandée : le domaine classe, il n'écarte pas."""
    exig = exigences(
        experiences_specifiques=(
            ExigenceSpecifique("veille sectorielle", frozenset({"veille"}), 0),
        )
    )
    motifs = evaluer_eligibilite(profil(), exig)
    assert not [
        m for m in motifs if m.motif is MotifElimination.EXPERIENCE_SPECIFIQUE_INSUFFISANTE
    ]


# --- certifications ----------------------------------------------------------


def bareme_avec_formation(**champs):
    return replace(
        BAREME_PAR_DEFAUT,
        formation=replace(BAREME_PAR_DEFAUT.formation, **champs),
    )


def test_les_certifications_ne_valent_rien_par_defaut():
    """Le barème du cabinet note le diplôme, et rien d'autre."""
    avec = profil(certifications=("PMP", "IFRS"))
    sans = profil()
    exig = exigences()
    assert noter(avec, exig).total == noter(sans, exig).total


def test_les_certifications_comptent_quand_le_poste_les_note():
    bareme = bareme_avec_formation(points_par_certification=0.5)
    exig = exigences()
    nu = noter(profil(), exig, bareme)
    certifie = noter(profil(certifications=("PMP", "IFRS")), exig, bareme)
    assert certifie.total - nu.total == 1.0


def test_les_certifications_ne_debordent_pas_des_sept_points():
    """Sinon la formation vaudrait plus que ce que disent les documents."""
    bareme = bareme_avec_formation(points_par_certification=3.0, certifications_max=5)
    notation = noter(profil(certifications=("A", "B", "C", "D", "E")), exigences(), bareme)
    formation = next(l for l in notation.lignes if l.code == "FORMATION")
    assert formation.points == 7.0
    assert notation.total <= 30.0


def test_le_nombre_de_certifications_retenues_est_plafonne():
    bareme = bareme_avec_formation(points_par_certification=0.5, certifications_max=2)
    notation = noter(profil(certifications=("A", "B", "C", "D")), exigences(), bareme)
    formation = next(l for l in notation.lignes if l.code == "FORMATION")
    assert "2 certification(s)" in formation.detail


# --- formation complémentaire ------------------------------------------------


def test_la_formation_complementaire_se_rapproche_du_dossier():
    bareme = bareme_avec_formation(points_formation_complementaire=1.0)
    exig = exigences(formation_complementaire="certificat en passation des marchés publics")
    dossier = profil(certifications=("Certificat en passation des marchés publics (ISADE)",))

    notation = noter(dossier, exig, bareme)
    formation = next(l for l in notation.lignes if l.code == "FORMATION")
    assert "ISADE" in formation.detail
    assert "à confirmer" in formation.detail, "un rapprochement de mots se relit"


def test_un_dossier_sans_rapport_ne_gagne_rien_et_la_ligne_le_dit():
    bareme = bareme_avec_formation(points_formation_complementaire=1.0)
    exig = exigences(formation_complementaire="certificat en passation des marchés publics")

    nu = noter(profil(), exigences(), bareme)
    sans_rapport = noter(profil(certifications=("Secourisme",)), exig, bareme)
    assert sans_rapport.total == nu.total
    formation = next(l for l in sans_rapport.lignes if l.code == "FORMATION")
    assert "Rien au dossier ne répond" in formation.detail


def test_la_formation_complementaire_ne_vaut_rien_sans_reglage():
    exig = exigences(formation_complementaire="certificat en passation des marchés publics")
    dossier = profil(certifications=("Certificat en passation des marchés publics",))
    assert noter(dossier, exig).total == noter(profil(), exigences()).total


def test_un_souhait_n_elimine_jamais():
    """Une formation *souhaitée* n'est pas une exigence."""
    exig = exigences(formation_complementaire="doctorat en droit fiscal")
    assert not evaluer_eligibilite(
        profil(experience("droit", date(2010, 1, 1), date(2026, 1, 1))), exig
    )


def test_un_poids_absurde_ne_fait_pas_deborder_le_critere():
    """Un zéro normalisé d'un seul côté aurait fait valoir 22 points aux 15."""
    exig = exigences(
        experiences_specifiques=(
            ExigenceSpecifique("sans poids", frozenset({"marches"}), 5, poids=0.0),
            ExigenceSpecifique("bien pesée", frozenset({"projet"}), 3, poids=2.0),
        )
    )
    notation = noter(
        profil(
            experience("marches", date(2010, 1, 1), date(2026, 1, 1)),
            experience("projet", date(2010, 1, 1), date(2026, 1, 1)),
        ),
        exig,
    )
    specifiques = lignes_specifiques(notation)
    assert sum(l.points_max for l in specifiques) == 15.0
    assert sum(l.points for l in specifiques) <= 15.0
