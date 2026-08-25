from __future__ import annotations

from datetime import date

import pytest

from app.domain import (
    BAREME_PAR_DEFAUT,
    Bareme,
    BaremeExperience,
    BaremeFormation,
    CodeAjout,
    DecisionSeuil,
    Diplome,
    ExigencesPoste,
    Experience,
    NiveauDiplome,
    ProfilCandidat,
    RegleAjout,
    appliquer_seuil,
    classer,
    noter,
)

CLOTURE = date(2026, 7, 31)


def exigences(**overrides) -> ExigencesPoste:
    base = {
        "niveau_min": NiveauDiplome.BAC_PLUS_4,
        "domaines_acceptes": frozenset({"gestion"}),
        "annees_experience_min": 10,
        "annees_experience_specifique_min": 5,
        "domaines_experience": frozenset({"gestion"}),
        "langues_requises": frozenset({"français"}),
        "date_reference": CLOTURE,
    }
    return ExigencesPoste(**{**base, **overrides})


def profil(**overrides) -> ProfilCandidat:
    base = {
        "nom": "Kodjo",
        "prenom": "Amina",
        "diplomes": (Diplome("Master", NiveauDiplome.BAC_PLUS_5, "gestion"),),
        "experiences": (
            Experience(
                "Directrice", "Hôtel", date(2010, 1, 1), date(2026, 1, 1),
                frozenset({"gestion"}), "Togo",
            ),
        ),
        "langues": frozenset({"français"}),
    }
    return ProfilCandidat(**{**base, **overrides})


def ligne(notation, code):
    return next(l for l in notation.lignes if l.code == code)


def test_le_bareme_par_defaut_totalise_bien_trente():
    assert BAREME_PAR_DEFAUT.total_max == 30.0
    somme = (
        BAREME_PAR_DEFAUT.formation.points_max
        + BAREME_PAR_DEFAUT.experience_generale.points_max
        + BAREME_PAR_DEFAUT.experience_specifique.points_max
        + BAREME_PAR_DEFAUT.points_ajouts_max
    )
    assert somme == 30.0


def test_un_bareme_incoherent_est_refuse_a_la_construction():
    """Un barème qui ne peut pas atteindre son total annoncé est un bug."""
    with pytest.raises(ValueError, match="plafonne"):
        Bareme(
            formation=BaremeFormation(points_max=10, points_niveau_requis=8),
            experience_generale=BaremeExperience(points_max=5, points_au_seuil=3),
            experience_specifique=BaremeExperience(points_max=5, points_au_seuil=3),
            points_ajouts_max=0,
            total_max=30.0,
        )


def test_aucune_ligne_ne_depasse_son_plafond():
    surdiplome = profil(
        diplomes=(Diplome("Doctorat", NiveauDiplome.BAC_PLUS_8, "gestion"),),
        experiences=(
            Experience(
                "Directrice", "Hôtel", date(1990, 1, 1), date(2026, 1, 1),
                frozenset({"gestion"}), "France",
            ),
        ),
        langues=frozenset({"français", "anglais", "allemand", "espagnol", "mina"}),
        certifications=("PMP", "ITIL", "PRINCE2"),
    )
    notation = noter(surdiplome, exigences())
    for l in notation.lignes:
        assert l.points <= l.points_max, l.code
    assert notation.total <= notation.total_max


def test_le_total_est_la_somme_des_lignes():
    notation = noter(profil(), exigences())
    assert notation.total == sum(l.points for l in notation.lignes)


def test_la_formation_recompense_le_niveau_superieur():
    juste = noter(
        profil(diplomes=(Diplome("Maîtrise", NiveauDiplome.BAC_PLUS_4, "gestion"),)), exigences()
    )
    au_dessus = noter(profil(), exigences())  # BAC+5 pour un BAC+4 demandé
    assert ligne(au_dessus, "FORMATION").points > ligne(juste, "FORMATION").points


def test_un_niveau_insuffisant_note_zero_sans_planter():
    """Le cas est éliminatoire, mais la grille doit rester calculable."""
    notation = noter(
        profil(diplomes=(Diplome("BTS", NiveauDiplome.BAC_PLUS_2, "gestion"),)), exigences()
    )
    assert ligne(notation, "FORMATION").points == 0.0


def test_l_experience_sous_le_seuil_note_zero():
    junior = profil(
        experiences=(
            Experience(
                "Analyste", "SGI", date(2024, 1, 1), date(2026, 1, 1),
                frozenset({"gestion"}), "Togo",
            ),
        )
    )
    notation = noter(junior, exigences())
    assert ligne(notation, "EXPERIENCE_GENERALE").points == 0.0
    assert ligne(notation, "EXPERIENCE_SPECIFIQUE").points == 0.0


def test_les_ajouts_se_cumulent_mais_restent_plafonnes():
    riche = profil(
        experiences=(
            Experience(
                "Directrice", "Groupe", date(2010, 1, 1), date(2026, 1, 1),
                frozenset({"gestion"}), "Côte d'Ivoire",
            ),
        ),
        langues=frozenset({"français", "anglais", "espagnol", "portugais"}),
        certifications=("PMP", "ITIL", "CFA"),
    )
    ajouts = ligne(noter(riche, exigences()), "AJOUTS")
    assert ajouts.points == ajouts.points_max
    assert "Expérience à l'étranger" in ajouts.detail


def test_l_experience_au_togo_ne_donne_pas_le_bonus_international():
    ajouts = ligne(noter(profil(), exigences()), "AJOUTS")
    assert "Expérience à l'étranger" not in ajouts.detail


def test_la_langue_exigee_ne_compte_pas_comme_ajout():
    seulement_francais = profil(langues=frozenset({"français"}))
    detail = ligne(noter(seulement_francais, exigences()), "AJOUTS").detail
    assert "Langue supplémentaire" not in detail


def test_les_repetitions_d_ajout_sont_plafonnees():
    bareme = Bareme(
        formation=BaremeFormation(points_max=10, points_niveau_requis=10),
        experience_generale=BaremeExperience(points_max=8, points_au_seuil=8),
        experience_specifique=BaremeExperience(points_max=8, points_au_seuil=8),
        ajouts=(RegleAjout(CodeAjout.LANGUE_SUPPLEMENTAIRE, points=1.0, repetitions_max=2),),
        points_ajouts_max=4.0,
        total_max=30.0,
    )
    polyglotte = profil(langues=frozenset({"français", "anglais", "mina", "éwé", "haoussa"}))
    # Quatre langues en plus, mais la règle plafonne à deux.
    assert ligne(noter(polyglotte, exigences(), bareme), "AJOUTS").points == 2.0


def test_chaque_ligne_explique_son_calcul():
    for l in noter(profil(), exigences()).lignes:
        assert l.detail.strip(), f"la ligne {l.code} n'explique rien"


def test_le_seuil_decide_de_la_preselection():
    notation = noter(profil(), exigences())
    assert notation.seuil == 20.0
    assert notation.atteint_le_seuil is (notation.total >= 20.0)


def test_abaisser_le_seuil_exige_une_justification():
    with pytest.raises(ValueError, match="justification"):
        DecisionSeuil(seuil_retenu=15.0, seuil_nominal=20.0, justification="")
    decision = DecisionSeuil(
        seuil_retenu=15.0, seuil_nominal=20.0, justification="Poste en tension, 3 candidatures."
    )
    assert appliquer_seuil(BAREME_PAR_DEFAUT, decision).seuil_preselection == 15.0


def test_relever_le_seuil_ne_demande_rien():
    """Seul l'assouplissement est sensible ; durcir ne lèse personne."""
    assert DecisionSeuil(seuil_retenu=25.0, seuil_nominal=20.0, justification="").seuil_retenu == 25


def test_classement_par_note_puis_par_seuil():
    notations = {
        "c1": noter(profil(), exigences()),
        "c2": noter(
            profil(
                experiences=(
                    Experience(
                        "Analyste", "SGI", date(2024, 1, 1), date(2026, 1, 1),
                        frozenset({"gestion"}), "Togo",
                    ),
                )
            ),
            exigences(),
        ),
    }
    classement = classer(notations)
    assert [i for i, _ in classement.retenus] == ["c1"]
    assert [i for i, _ in classement.non_retenus] == ["c2"]


def test_le_quota_bascule_les_admissibles_excedentaires():
    notations = {nom: noter(profil(), exigences()) for nom in ("c1", "c2", "c3")}
    classement = classer(notations, nombre_max=2)
    assert len(classement.retenus) == 2
    assert len(classement.non_retenus) == 1
    # À note égale, l'ordre reste stable et reproductible.
    assert [i for i, _ in classement.retenus] == ["c1", "c2"]


def test_notation_reproductible():
    """Deux calculs identiques donnent exactement la même note."""
    a = noter(profil(), exigences())
    b = noter(profil(), exigences())
    assert a == b
