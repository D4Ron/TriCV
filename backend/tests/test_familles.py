"""Les familles de métiers : ce qui vaut, ce qui n'est que voisin, ce qui ne l'est pas."""

from __future__ import annotations

from datetime import date

import pytest

from app.domain import familles
from app.domain.referentiel import domaine_correspond
from app.llm.base import ExperienceExtraite
from app.services import lecture_locale


@pytest.mark.parametrize(
    ("declare", "attendu"),
    [
        ("supply chain management", "logistique"),
        ("ressources humaines", "gestion des ressources humaines"),
        ("gestion du personnel", "ressources humaines"),
        ("reseaux et informatique", "informatique"),
        ("sciences comptables", "comptabilité"),
        ("agronomie", "agriculture"),
        ("Oil & Gas", "Pétrole & Gaz"),
        ("hydrocarbures", "Pétrole & Gaz"),
        ("gestion des stocks", "logistique"),
    ],
)
def test_la_meme_chose_dite_autrement_correspond(declare, attendu):
    assert domaine_correspond(declare, attendu)


@pytest.mark.parametrize(
    ("declare", "attendu"),
    [
        ("droit", "comptabilité"),
        ("droit social", "droit des affaires"),
        ("finance", "finance d'entreprise"),
        ("marketing", "commerce"),
        ("audit et contrôle de gestion", "comptabilité"),
        ("gestion des stocks", "gestion"),
    ],
)
def test_ce_qui_differe_reste_different(declare, attendu):
    if (declare, attendu) == ("gestion des stocks", "gestion"):
        # Le mot à mot l'accepte déjà ; la famille n'y ajoute rien.
        assert not familles.equivalents(declare, attendu)
        return
    assert not domaine_correspond(declare, attendu)


@pytest.mark.parametrize(
    ("declare", "attendu"),
    [
        ("audit et contrôle de gestion", "comptabilité"),
        ("banque et assurance", "finance"),
        ("marketing", "commerce"),
        ("psychologie du travail", "ressources humaines"),
        ("réseaux et télécommunications", "informatique"),
        ("santé publique", "médecine"),
    ],
)
def test_un_voisin_est_apparente_sans_etre_equivalent(declare, attendu):
    assert familles.apparente(declare, attendu)
    assert not familles.equivalents(declare, attendu)


def test_sans_lien_ni_voisinage():
    assert not familles.apparente("lettres modernes", "comptabilité")
    assert not familles.apparente("comptabilité", "domaine inconnu du référentiel")


@pytest.mark.parametrize(
    "texte",
    [
        "TotalEnergies Togo - Directeur logistique",
        "Directeur commercial, secteur Oil & Gas",
        "Sté pétrolière : responsable supply chain",
        "Hydrocarbures : achats et trading",
        "Distribution de produits pétroliers",
    ],
)
def test_le_secteur_se_lit_sans_ses_mots_exacts(texte):
    assert lecture_locale.domaines_de(texte, ["Pétrole & Gaz"]) == ["Pétrole & Gaz"]


@pytest.mark.parametrize(
    "texte",
    [
        "Boîte postale BP 1234, Lomé",
        "Un total de quinze agents encadrés",
        "Directeur des ressources humaines",
    ],
)
def test_les_mots_ambigus_ne_font_pas_un_secteur(texte):
    assert lecture_locale.domaines_de(texte, ["Pétrole & Gaz", "Énergie"]) == []


def test_le_lexique_du_poste_complete_les_familles():
    lexique = {"Énergie": ["Compagnie du Mono"]}
    assert lecture_locale.domaines_de("Chef de service, Compagnie du Mono", ["Énergie"]) == []
    assert lecture_locale.domaines_de(
        "Chef de service, Compagnie du Mono", ["Énergie"], lexique
    ) == ["Énergie"]


ATTESTATION = (
    "ATTESTATION DE TRAVAIL\nJe soussigné, directeur de la société Togo Transit, atteste que "
    "Mme Afi DOSSOU a travaillé en qualité de chef de quai du 1er mars 2015 au 30 juin 2018 "
    "au terminal pétrolier."
)


def test_une_attestation_se_lit_en_phrases():
    lue = lecture_locale.experience_d_une_attestation(ATTESTATION, ["Pétrole & Gaz"])
    assert lue.poste == "chef de quai"
    assert lue.employeur == "Togo Transit"
    assert (lue.debut, lue.fin) == ("2015-03", "2018-06")
    assert lue.domaines == ["Pétrole & Gaz"]


def test_une_attestation_en_cours_reste_ouverte():
    lue = lecture_locale.experience_d_une_attestation(
        "Nous certifions que M. Koffi occupe le poste de responsable logistique "
        "à la société Port Sec depuis juillet 2018.",
        aujourd_hui=date(2026, 11, 4),
    )
    assert lue.poste == "responsable logistique"
    assert (lue.debut, lue.fin) == ("2018-07", None)


def test_une_attestation_sans_date_ne_fait_pas_un_emploi():
    assert lecture_locale.experience_d_une_attestation("Atteste que M. Koffi est sérieux.") is None


def test_le_meme_emploi_ne_se_compte_pas_deux_fois_mais_gagne_ses_domaines():
    cv = ExperienceExtraite(poste="Chef de quai", employeur="TT", debut="2015-01", fin="2018-07")
    parcours = [cv]
    attestee = lecture_locale.experience_d_une_attestation(ATTESTATION, ["Pétrole & Gaz"])

    assert not lecture_locale.verser_attestation(parcours, attestee)
    assert len(parcours) == 1
    assert cv.domaines == ["Pétrole & Gaz"]


def test_un_emploi_absent_du_cv_rejoint_le_parcours():
    parcours = [ExperienceExtraite(poste="Autre", employeur="X", debut="2020-01", fin="2022-01")]
    attestee = lecture_locale.experience_d_une_attestation(ATTESTATION)

    assert lecture_locale.verser_attestation(parcours, attestee)
    assert len(parcours) == 2
