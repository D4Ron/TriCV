from __future__ import annotations

from datetime import date

import pytest

from app.domain import (
    DOSSIER_STANDARD,
    Diplome,
    ExigencesPoste,
    Experience,
    MotifElimination,
    NiveauDiplome,
    PieceDossier,
    ProfilCandidat,
    RestrictionPoste,
    Sexe,
    est_eligible,
    evaluer_eligibilite,
    fusionner_intervalles,
)

CLOTURE = date(2026, 7, 31)


def profil(**overrides) -> ProfilCandidat:
    base = {
        "nom": "Kodjo",
        "prenom": "Amina",
        "date_naissance": date(1990, 5, 20),
        "sexe": Sexe.FEMININ,
        "nationalites": frozenset({"Togolaise"}),
        "diplomes": (
            Diplome("Master en gestion hôtelière", NiveauDiplome.BAC_PLUS_5, "gestion hôtelière"),
        ),
        "experiences": (
            Experience(
                "Directrice adjointe",
                "Hôtel du 2 Février",
                date(2014, 1, 1),
                date(2026, 1, 1),
                frozenset({"gestion hôtelière"}),
                "Togo",
            ),
        ),
        "pieces_fournies": frozenset({PieceDossier.LETTRE_MOTIVATION, PieceDossier.CV}),
    }
    return ProfilCandidat(**{**base, **overrides})


def exigences(**overrides) -> ExigencesPoste:
    base = {
        "niveau_min": NiveauDiplome.BAC_PLUS_4,
        "domaines_acceptes": frozenset({"gestion hôtelière"}),
        "annees_experience_min": 10,
        "annees_experience_specifique_min": 5,
        "domaines_experience": frozenset({"gestion hôtelière"}),
        "pieces_requises": DOSSIER_STANDARD,
        "date_reference": CLOTURE,
    }
    return ExigencesPoste(**{**base, **overrides})


def motifs(profil_, exigences_, depot=None) -> set[MotifElimination]:
    return {e.motif for e in evaluer_eligibilite(profil_, exigences_, depot)}


def test_un_dossier_conforme_passe():
    assert est_eligible(profil(), exigences())


def test_piece_manquante_elimine_et_nomme_la_piece():
    incomplet = profil(pieces_fournies=frozenset({PieceDossier.CV}))
    exig = exigences(
        pieces_requises=frozenset(
            {PieceDossier.CV, PieceDossier.LETTRE_MOTIVATION, PieceDossier.COPIE_DIPLOMES}
        )
    )
    (elimination,) = [
        e for e in evaluer_eligibilite(incomplet, exig)
        if e.motif is MotifElimination.DOSSIER_INCOMPLET
    ]
    assert "Lettre de motivation" in elimination.constate
    assert "Copie des diplômes" in elimination.constate


def test_niveau_insuffisant():
    faible = profil(
        diplomes=(Diplome("Licence", NiveauDiplome.BAC_PLUS_3, "gestion hôtelière"),)
    )
    assert MotifElimination.FORMATION_INSUFFISANTE in motifs(faible, exigences())


def test_domaine_non_conforme_meme_avec_un_diplome_plus_eleve():
    """Un BAC+8 hors domaine ne rachète pas le domaine."""
    hors_domaine = profil(diplomes=(Diplome("Doctorat", NiveauDiplome.BAC_PLUS_8, "droit"),))
    resultat = motifs(hors_domaine, exigences())
    assert MotifElimination.FORMATION_NON_CONFORME in resultat
    assert MotifElimination.FORMATION_INSUFFISANTE not in resultat


def test_un_diplome_hors_domaine_ne_releve_pas_le_niveau():
    """Le niveau s'apprécie dans le domaine exigé, pas au global."""
    mixte = profil(
        diplomes=(
            Diplome("BTS hôtellerie", NiveauDiplome.BAC_PLUS_2, "gestion hôtelière"),
            Diplome("Master en droit", NiveauDiplome.BAC_PLUS_5, "droit"),
        )
    )
    assert MotifElimination.FORMATION_INSUFFISANTE in motifs(mixte, exigences())


def test_experience_insuffisante():
    junior = profil(
        experiences=(
            Experience(
                "Réceptionniste",
                "Hôtel Sarakawa",
                date(2023, 1, 1),
                date(2026, 1, 1),
                frozenset({"gestion hôtelière"}),
                "Togo",
            ),
        )
    )
    resultat = motifs(junior, exigences())
    assert MotifElimination.EXPERIENCE_INSUFFISANTE in resultat
    assert MotifElimination.EXPERIENCE_SPECIFIQUE_INSUFFISANTE in resultat


def test_experience_hors_domaine_compte_au_general_mais_pas_au_specifique():
    reconverti = profil(
        experiences=(
            Experience(
                "Comptable", "SGI", date(2010, 1, 1), date(2024, 1, 1), frozenset({"finance"}), "Togo"
            ),
        )
    )
    resultat = motifs(reconverti, exigences())
    assert MotifElimination.EXPERIENCE_INSUFFISANTE not in resultat
    assert MotifElimination.EXPERIENCE_SPECIFIQUE_INSUFFISANTE in resultat


def test_les_emplois_simultanes_ne_comptent_pas_double():
    """Deux postes menés de front sur la même période font une ancienneté."""
    cumul = profil(
        experiences=(
            Experience(
                "Directrice", "Hôtel A", date(2020, 1, 1), date(2026, 1, 1),
                frozenset({"gestion hôtelière"}), "Togo",
            ),
            Experience(
                "Consultante", "Hôtel B", date(2020, 1, 1), date(2026, 1, 1),
                frozenset({"gestion hôtelière"}), "Togo",
            ),
        )
    )
    # 6 ans réels, pas 12 : la barre des 10 ans n'est pas franchie.
    assert MotifElimination.EXPERIENCE_INSUFFISANTE in motifs(cumul, exigences())


def test_fusion_des_intervalles():
    fusionnes = fusionner_intervalles(
        [
            (date(2020, 1, 1), date(2022, 1, 1)),
            (date(2021, 1, 1), date(2023, 1, 1)),
            (date(2024, 1, 1), date(2025, 1, 1)),
        ]
    )
    assert fusionnes == [
        (date(2020, 1, 1), date(2023, 1, 1)),
        (date(2024, 1, 1), date(2025, 1, 1)),
    ]


def test_un_poste_en_cours_est_arrete_a_la_date_de_cloture():
    en_poste = profil(
        experiences=(
            Experience(
                "Directrice", "Hôtel", date(2016, 8, 1), None,
                frozenset({"gestion hôtelière"}), "Togo",
            ),
        )
    )
    # Du 01/08/2016 au 31/07/2026 : 9 ans et 11 mois, donc sous les 10 ans.
    assert MotifElimination.EXPERIENCE_INSUFFISANTE in motifs(en_poste, exigences())


def test_age_calcule_a_la_date_de_cloture_et_non_du_jour():
    """Un anniversaire après la clôture ne doit pas changer la grille."""
    restriction = RestrictionPoste(
        age_max=35, justification="Limite d'âge fixée par le statut du personnel du client."
    )
    ne_le_lendemain = profil(date_naissance=date(1991, 8, 1))  # 34 ans au 31/07/2026
    assert MotifElimination.CONDITION_AGE not in motifs(
        ne_le_lendemain, exigences(restriction=restriction)
    )
    ne_la_veille = profil(date_naissance=date(1991, 7, 30))  # 35 ans au 31/07/2026
    assert MotifElimination.CONDITION_AGE not in motifs(
        ne_la_veille, exigences(restriction=restriction)
    )
    trop_age = profil(date_naissance=date(1990, 7, 30))  # 36 ans
    assert MotifElimination.CONDITION_AGE in motifs(trop_age, exigences(restriction=restriction))


def test_restriction_de_sexe_et_de_nationalite():
    restriction = RestrictionPoste(
        sexe=Sexe.FEMININ,
        nationalites=frozenset({"Togolaise"}),
        justification="Poste réservé par la convention du projet.",
    )
    exig = exigences(restriction=restriction)
    assert MotifElimination.CONDITION_SEXE not in motifs(profil(), exig)

    homme = profil(sexe=Sexe.MASCULIN)
    assert MotifElimination.CONDITION_SEXE in motifs(homme, exig)

    etranger = profil(nationalites=frozenset({"Ghanéenne"}))
    assert MotifElimination.CONDITION_NATIONALITE in motifs(etranger, exig)

    binational = profil(nationalites=frozenset({"Ghanéenne", "Togolaise"}))
    assert MotifElimination.CONDITION_NATIONALITE not in motifs(binational, exig)


def test_une_restriction_exige_une_justification_ecrite():
    with pytest.raises(ValueError, match="justifiée"):
        RestrictionPoste(age_max=35)
    with pytest.raises(ValueError, match="justifiée"):
        RestrictionPoste(sexe=Sexe.FEMININ, justification="   ")
    # Sans restriction, aucune justification n'est requise.
    assert RestrictionPoste().active is False


def test_l_elimination_recopie_la_justification_du_poste():
    restriction = RestrictionPoste(
        age_max=30, justification="Programme jeunes diplômés financé par le bailleur."
    )
    (elimination,) = [
        e
        for e in evaluer_eligibilite(profil(), exigences(restriction=restriction))
        if e.motif is MotifElimination.CONDITION_AGE
    ]
    assert "bailleur" in elimination.explication


def test_une_donnee_absente_n_elimine_jamais():
    """Sans date de naissance ni sexe déclarés, la vérification revient aux RH."""
    restriction = RestrictionPoste(
        age_max=30, sexe=Sexe.MASCULIN, justification="Condition posée par le client."
    )
    anonyme = profil(date_naissance=None, sexe=None, nationalites=frozenset())
    resultat = motifs(anonyme, exigences(restriction=restriction))
    assert MotifElimination.CONDITION_AGE not in resultat
    assert MotifElimination.CONDITION_SEXE not in resultat


def test_les_restrictions_sont_ignorees_si_le_poste_n_en_declare_pas():
    homme_etranger = profil(sexe=Sexe.MASCULIN, nationalites=frozenset({"Béninoise"}))
    assert est_eligible(homme_etranger, exigences())


def test_candidature_hors_delai():
    assert MotifElimination.HORS_DELAI in motifs(profil(), exigences(), date(2026, 8, 1))
    assert MotifElimination.HORS_DELAI not in motifs(profil(), exigences(), CLOTURE)


def test_les_motifs_sortent_dans_l_ordre_du_tableau():
    catastrophe = profil(
        diplomes=(Diplome("BEPC", NiveauDiplome.BAC, "droit"),),
        experiences=(),
        pieces_fournies=frozenset(),
    )
    obtenus = [e.motif for e in evaluer_eligibilite(catastrophe, exigences())]
    assert obtenus[0] is MotifElimination.DOSSIER_INCOMPLET
    assert obtenus.index(MotifElimination.FORMATION_NON_CONFORME) < obtenus.index(
        MotifElimination.EXPERIENCE_INSUFFISANTE
    )


def test_le_domaine_se_compare_sans_accents_ni_casse():
    variante = profil(
        diplomes=(Diplome("Master", NiveauDiplome.BAC_PLUS_5, "GESTION HOTELIERE"),)
    )
    assert MotifElimination.FORMATION_NON_CONFORME not in motifs(variante, exigences())


def test_reconnaissance_du_niveau_depuis_le_texte_de_l_avis():
    assert NiveauDiplome.depuis_texte("BAC+5") is NiveauDiplome.BAC_PLUS_5
    assert NiveauDiplome.depuis_texte("Bac + 4") is NiveauDiplome.BAC_PLUS_4
    assert NiveauDiplome.depuis_texte("Master 2") is NiveauDiplome.BAC_PLUS_5
    assert NiveauDiplome.depuis_texte("Licence professionnelle") is NiveauDiplome.BAC_PLUS_3
    assert NiveauDiplome.depuis_texte("Doctorat") is NiveauDiplome.BAC_PLUS_8
    # Un niveau non reconnu remonte à un humain plutôt que d'être deviné.
    assert NiveauDiplome.depuis_texte("diplôme maison") is None
