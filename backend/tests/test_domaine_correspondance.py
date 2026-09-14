"""Le rapprochement des domaines : ce qu'il absorbe, ce qu'il refuse.

La comparaison était l'égalité de deux chaînes. C'était le défaut le plus
coûteux de la présélection : il produisait des motifs de non-conformité qu'un
lecteur humain aurait refusés, sur des dossiers parfaitement conformes. Ces
tests fixent la frontière — variations d'écriture absorbées, différences de
métier refusées.
"""

from __future__ import annotations

import pytest

from app.domain import Diplome, Experience, ExigencesPoste, NiveauDiplome, ProfilCandidat
from app.domain.referentiel import domaine_correspond

from datetime import date


@pytest.mark.parametrize(
    ("declare", "attendu"),
    [
        # Écriture : accents, casse, virgules, traits d'union, liaisons.
        ("Comptabilité", "comptabilite"),
        ("comptabilite et finance", "comptabilité"),
        ("comptabilité, finance", "finance"),
        ("finance d'entreprise", "finance"),
        ("gestion des ressources humaines", "gestion ressources humaines"),
        ("Gestion Hôtelière", "gestion hoteliere"),
        # Précision : un domaine plus précis relève du domaine plus large.
        ("comptabilité générale et analytique", "comptabilite generale"),
        ("audit interne et conformité", "audit interne"),
    ],
)
def test_les_variations_d_ecriture_sont_absorbees(declare: str, attendu: str):
    assert domaine_correspond(declare, attendu)


@pytest.mark.parametrize(
    ("declare", "attendu"),
    [
        # Métiers différents : rien ne les rapproche.
        ("droit", "comptabilite"),
        ("droit social", "droit des affaires"),
        ("audit interne", "comptabilite generale"),
        ("genie civil", "informatique"),
        # Sens strict : le plus large ne satisfait pas le plus précis.
        ("finance", "finance d'entreprise"),
        ("comptabilite", "comptabilite generale"),
    ],
)
def test_les_metiers_distincts_restent_distincts(declare: str, attendu: str):
    assert not domaine_correspond(declare, attendu)


def test_aucun_domaine_attendu_accepte_tout():
    """Un poste qui n'exige aucun domaine ne peut écarter personne pour cela."""
    assert domaine_correspond("n'importe quoi", "")


def test_un_diplome_plus_precis_reste_dans_le_domaine_accepte():
    """« Master en sciences comptables » relève de « comptabilité »."""
    profil = ProfilCandidat(
        nom="Attiogbe",
        prenom="Sena",
        diplomes=(
            Diplome("Master en sciences comptables", NiveauDiplome.BAC_PLUS_5, "sciences comptables"),
            Diplome("Licence", NiveauDiplome.BAC_PLUS_3, "comptabilite"),
        ),
    )
    retenus = profil.diplomes_dans(frozenset({"comptabilite"}))
    assert len(retenus) == 2
    assert profil.niveau_max() is NiveauDiplome.BAC_PLUS_5


def test_une_experience_plus_precise_compte_pour_le_domaine_attendu():
    exp = Experience(
        "Comptable",
        "Société",
        date(2016, 1, 1),
        date(2020, 1, 1),
        frozenset({"comptabilite generale et analytique"}),
    )
    assert exp.concerne(frozenset({"comptabilite generale"}))
    assert not exp.concerne(frozenset({"audit interne"}))


def test_l_exigence_de_domaine_reste_opposable():
    """Le garde-fou : un diplôme hors sujet ne passe toujours pas."""
    profil = ProfilCandidat(
        nom="Bakari",
        prenom="Ibrahim",
        diplomes=(Diplome("Master en droit", NiveauDiplome.BAC_PLUS_5, "droit des affaires"),),
    )
    assert profil.diplomes_dans(frozenset({"comptabilite", "finance"})) == ()


@pytest.mark.parametrize(
    ("declare", "attendu"),
    [
        ("sciences comptables", "comptabilite"),
        ("finance d'entreprise", "financier"),
    ],
)
def test_une_racine_commune_suffit(declare: str, attendu: str):
    """« comptabilité », « comptable », « comptables » : le même métier.

    Les avis et les CV n'emploient pas la même forme du même mot, et exiger la
    même forme revenait à exiger la même plume.
    """
    assert domaine_correspond(declare, attendu)


@pytest.mark.parametrize(
    ("declare", "attendu"),
    [
        ("gestation", "gestion"),
        ("droit", "droits humains"),
        # Sens strict, morphologie comprise : le plus large ne satisfait pas
        # le plus précis, même quand les racines se répondent.
        ("comptabilite", "sciences comptables"),
    ],
)
def test_une_racine_trop_courte_ne_rapproche_rien(declare: str, attendu: str):
    assert not domaine_correspond(declare, attendu)

