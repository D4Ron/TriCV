"""Le barème de présélection, tel que le cabinet le pratique.

Les maxima — consistance 3, formation 7, expérience générale 5, expérience
spécifique 15 — viennent des documents réels ; les tests les verrouillent, car
c'est sur eux que se juge la fidélité de la grille remise au client. La courbe
interne de chaque critère, elle, est un réglage : les tests vérifient qu'elle
se règle, pas qu'elle vaut telle valeur.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain import (
    BAREME_ENTRETIEN,
    BAREME_PAR_DEFAUT,
    TOTAL_ENTRETIEN,
    Bareme,
    BaremeConsistance,
    BaremeExperience,
    BaremeFormation,
    CodeAjout,
    DecisionSeuil,
    Diplome,
    ExigencesPoste,
    Experience,
    NiveauDiplome,
    NoteEntretien,
    PieceDossier,
    ProfilCandidat,
    RegleAjout,
    appliquer_seuil,
    classer,
    note_de_conformite,
    note_finale,
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


# --- structure du barème -----------------------------------------------------


def test_le_bareme_reprend_la_repartition_du_cabinet():
    """3 / 7 / 5 / 15 : les quatre maxima des documents réels."""
    b = BAREME_PAR_DEFAUT
    assert b.consistance.points_max == 3.0
    assert b.formation.points_max == 7.0
    assert b.experience_generale.points_max == 5.0
    assert b.experience_specifique.points_max == 15.0
    assert b.total_max == 30.0


def test_l_experience_specifique_pese_la_moitie_du_total():
    """Ce n'est pas un détail de réglage mais le sens du barème.

    Le cabinet cherche quelqu'un qui a déjà exercé la fonction, pas quelqu'un
    qui a beaucoup travaillé : quinze points contre cinq.
    """
    b = BAREME_PAR_DEFAUT
    assert b.experience_specifique.points_max == b.total_max / 2
    assert b.experience_specifique.points_max == 3 * b.experience_generale.points_max


def test_les_trente_points_valent_trente_pour_cent_de_la_note_finale():
    assert BAREME_PAR_DEFAUT.poids_note_finale == 30.0
    assert TOTAL_ENTRETIEN == 70.0
    assert BAREME_PAR_DEFAUT.poids_note_finale + TOTAL_ENTRETIEN == 100.0


def test_la_grille_d_entretien_totalise_bien_soixante_dix():
    # Relevée dans l'offre technique du cabinet.
    attendus = {
        "PRESENTATION": 2.0,
        "MOTIVATION": 2.0,
        "RELATIONNELLES": 20.0,
        "TECHNIQUES": 25.0,
        "POTENTIEL": 20.0,
        "CONNAISSANCES_CLIENT": 1.0,
    }
    assert {l.code: l.points_max for l in BAREME_ENTRETIEN} == attendus


def test_un_bareme_incoherent_est_refuse_a_la_construction():
    with pytest.raises(ValueError, match="plafonne"):
        Bareme(
            formation=BaremeFormation(points_max=10, points_niveau_requis=10),
            experience_generale=BaremeExperience(points_max=5, points_au_seuil=5),
            experience_specifique=BaremeExperience(points_max=5, points_au_seuil=5),
            total_max=30,
        )


def test_une_consistance_mal_decomposee_est_refusee():
    """Le détail doit refermer le maximum, sinon la ligne ment sur son plafond."""
    with pytest.raises(ValueError, match="consistance"):
        Bareme(
            consistance=BaremeConsistance(
                points_max=3.0,
                points_dossier_complet=1.0,
                points_coherence=1.0,
                points_appreciation=5.0,
            ),
            formation=BaremeFormation(points_max=7, points_niveau_requis=5),
            experience_generale=BaremeExperience(points_max=5, points_au_seuil=3),
            experience_specifique=BaremeExperience(points_max=15, points_au_seuil=9),
            total_max=30,
        )


def test_aucune_ligne_ne_depasse_son_plafond():
    excellent = profil(
        diplomes=(Diplome("Doctorat", NiveauDiplome.BAC_PLUS_8, "gestion"),),
        experiences=(
            Experience(
                "Directrice", "Hôtel", date(1990, 1, 1), None,
                frozenset({"gestion"}), "France",
            ),
        ),
    )
    notation = noter(excellent, exigences(), appreciation_consistance=99)
    for l in notation.lignes:
        assert l.points <= l.points_max


def test_le_total_est_la_somme_des_lignes():
    notation = noter(profil(), exigences())
    assert notation.total == pytest.approx(sum(l.points for l in notation.lignes))
    assert notation.total <= notation.total_max


def test_le_bareme_du_cabinet_n_a_pas_de_ligne_ajouts():
    """Les quatre critères totalisent déjà 30 : une colonne vide interrogerait."""
    codes = {l.code for l in noter(profil(), exigences()).lignes}
    assert "AJOUTS" not in codes
    assert codes == {
        "CONSISTANCE",
        "FORMATION",
        "EXPERIENCE_GENERALE",
        "EXPERIENCE_SPECIFIQUE",
    }


# --- consistance du dossier --------------------------------------------------


def test_la_consistance_est_notee_et_non_un_simple_controle():
    """C'est le changement demandé : le dossier vaut des points, pas un verdict."""
    complet = profil(pieces_fournies=frozenset({PieceDossier.CV.value}))
    notation = noter(complet, exigences(pieces_requises=frozenset({PieceDossier.CV.value})))
    consistance = ligne(notation, "CONSISTANCE")
    assert consistance.points_max == 3.0
    assert consistance.points > 0


def test_un_dossier_incomplet_perd_le_point_de_completude():
    incomplet = profil(pieces_fournies=frozenset())
    exigee = exigences(pieces_requises=frozenset({PieceDossier.CV.value}))
    consistance = ligne(noter(incomplet, exigee), "CONSISTANCE")
    assert "incomplet" in consistance.detail
    # Cohérence acquise, complétude et appréciation non : 1 point sur 3.
    assert consistance.points == 1.0


def test_une_interruption_longue_est_signalee():
    hache = profil(
        experiences=(
            Experience("Chargée", "A", date(2005, 1, 1), date(2008, 1, 1), frozenset({"gestion"})),
            Experience("Directrice", "B", date(2016, 1, 1), date(2026, 1, 1), frozenset({"gestion"})),
        ),
    )
    consistance = ligne(noter(hache, exigences()), "CONSISTANCE")
    assert "interruption" in consistance.detail


def test_des_dates_impossibles_sont_signalees_sans_planter():
    absurde = profil(
        experiences=(
            Experience("Directrice", "A", date(2020, 1, 1), date(2015, 1, 1), frozenset({"gestion"})),
        ),
    )
    consistance = ligne(noter(absurde, exigences()), "CONSISTANCE")
    assert "impossible" in consistance.detail


def test_l_appreciation_non_portee_ne_compte_pas_comme_un_zero():
    """Une lecture qui n'a pas eu lieu n'est pas un jugement défavorable."""
    notation = noter(profil(), exigences())
    consistance = ligne(notation, "CONSISTANCE")
    assert "appréciation non portée" in consistance.detail
    assert notation.attend_appreciation is True


def test_l_appreciation_portee_entre_dans_la_note():
    sans = noter(profil(), exigences())
    avec = noter(profil(), exigences(), appreciation_consistance=1.0)
    assert avec.total == sans.total + 1.0
    assert avec.attend_appreciation is False
    assert "appréciation du dossier : 1" in ligne(avec, "CONSISTANCE").detail


def test_l_appreciation_est_bornee_par_le_bareme():
    genereuse = noter(profil(), exigences(), appreciation_consistance=10.0)
    assert ligne(genereuse, "CONSISTANCE").points <= 3.0


# --- formation et expérience -------------------------------------------------


def test_la_formation_recompense_le_niveau_superieur():
    juste = profil(diplomes=(Diplome("M1", NiveauDiplome.BAC_PLUS_4, "gestion"),))
    au_dessus = profil(diplomes=(Diplome("Doctorat", NiveauDiplome.BAC_PLUS_8, "gestion"),))
    assert ligne(noter(au_dessus, exigences()), "FORMATION").points > ligne(
        noter(juste, exigences()), "FORMATION"
    ).points


def test_un_niveau_insuffisant_note_zero_sans_planter():
    faible = profil(diplomes=(Diplome("Licence", NiveauDiplome.BAC_PLUS_3, "gestion"),))
    formation = ligne(noter(faible, exigences()), "FORMATION")
    assert formation.points == 0.0
    assert "inférieur" in formation.detail


def test_l_experience_sous_le_seuil_note_zero():
    junior = profil(
        experiences=(
            Experience(
                "Chargée", "Hôtel", date(2024, 1, 1), date(2026, 1, 1),
                frozenset({"gestion"}), "Togo",
            ),
        ),
    )
    assert ligne(noter(junior, exigences()), "EXPERIENCE_GENERALE").points == 0.0


def test_l_experience_specifique_departage_deux_profils_conformes():
    """Quinze points : c'est là que le classement se joue."""
    conforme = profil(
        experiences=(
            Experience(
                "Directrice", "Hôtel", date(2011, 1, 1), date(2026, 1, 1),
                frozenset({"gestion"}), "Togo",
            ),
        ),
    )
    chevronnee = profil(
        experiences=(
            Experience(
                "Directrice", "Hôtel", date(2000, 1, 1), date(2026, 1, 1),
                frozenset({"gestion"}), "Togo",
            ),
        ),
    )
    ecart = (
        ligne(noter(chevronnee, exigences()), "EXPERIENCE_SPECIFIQUE").points
        - ligne(noter(conforme, exigences()), "EXPERIENCE_SPECIFIQUE").points
    )
    assert ecart > 0


def test_chaque_ligne_explique_son_calcul():
    for l in noter(profil(), exigences()).lignes:
        assert l.detail.strip()


# --- note sur 100 ------------------------------------------------------------


def test_la_preselection_se_convertit_en_points_sur_cent():
    notation = noter(profil(), exigences())
    attendu = round(notation.total / notation.total_max * 30 * 2) / 2
    assert notation.points_sur_cent == attendu


def test_sans_entretien_la_note_finale_est_l_acquis_de_la_preselection():
    notation = noter(profil(), exigences())
    finale = note_finale(notation)
    assert finale.entretien_sur_cent == 0.0
    assert finale.total_sur_cent == notation.points_sur_cent
    # Le drapeau évite qu'un acquis partiel se lise comme un résultat.
    assert finale.entretien_complet is False


def test_un_entretien_parfait_ajoute_ses_soixante_dix_points():
    notation = noter(profil(), exigences(), appreciation_consistance=1.0)
    parfait = NoteEntretien(points={l.code: l.points_max for l in BAREME_ENTRETIEN})
    finale = note_finale(notation, parfait)
    assert finale.entretien_sur_cent == 70.0
    assert finale.entretien_complet is True
    assert finale.total_sur_cent == notation.points_sur_cent + 70.0


def test_un_entretien_partiel_n_est_pas_annonce_complet():
    notation = noter(profil(), exigences())
    partiel = NoteEntretien(points={"TECHNIQUES": 30.0})
    finale = note_finale(notation, partiel)
    assert finale.entretien_complet is False
    assert 0 < finale.entretien_sur_cent < 70.0


def test_une_note_d_entretien_hors_bornes_est_ramenee_au_plafond():
    trop = NoteEntretien(points={"CONNAISSANCES_CLIENT": 99.0})
    assert trop.total() == 1.0


# --- seuil et classement -----------------------------------------------------


def test_par_defaut_aucun_plancher_n_ecarte_personne():
    """Le processus du cabinet sélectionne par le classement, pas par un seuil."""
    assert BAREME_PAR_DEFAUT.seuil_preselection == 0.0
    assert noter(profil(), exigences()).atteint_le_seuil is True


def test_la_note_de_conformite_donne_un_plancher_defendable():
    """« Au moins ce que vaut un candidat conforme » se justifie ; un nombre rond non."""
    conforme = note_de_conformite()
    b = BAREME_PAR_DEFAUT
    assert conforme == (
        b.consistance.points_dossier_complet
        + b.consistance.points_coherence
        + b.formation.points_niveau_requis
        + b.experience_generale.points_au_seuil
        + b.experience_specifique.points_au_seuil
    )
    # L'appréciation humaine n'y entre pas : le plancher doit s'appliquer avant
    # toute lecture.
    assert conforme < b.total_max


def test_abaisser_le_seuil_exige_une_justification():
    with pytest.raises(ValueError, match="justification"):
        DecisionSeuil(seuil_retenu=10.0, seuil_nominal=19.0, justification="")

    decision = DecisionSeuil(10.0, 19.0, "Poste en tension, deux relances infructueuses.")
    assert appliquer_seuil(BAREME_PAR_DEFAUT, decision).seuil_preselection == 10.0


def test_relever_le_seuil_ne_demande_rien():
    """Relever la barre ne lèse personne qui l'aurait franchie."""
    assert DecisionSeuil(25.0, 19.0, "").seuil_retenu == 25.0


def notation_a(total: float, seuil: float = 0.0):
    from app.domain import Notation

    return Notation(lignes=(), total=total, total_max=30.0, seuil=seuil)


def test_le_classement_ordonne_par_note_decroissante():
    classement = classer(
        {"a": notation_a(12), "b": notation_a(25), "c": notation_a(18)}
    )
    assert [i for i, _ in classement.proposes] == ["b", "c", "a"]


def test_le_quota_distingue_proposes_et_prequalifies():
    """Un dossier peut être recevable sans figurer parmi les N remis au client."""
    notations = {"a": notation_a(28), "b": notation_a(25), "c": notation_a(20)}
    classement = classer(notations, nombre_a_proposer=2)

    assert [i for i, _ in classement.proposes] == ["a", "b"]
    assert [i for i, _ in classement.prequalifies_non_proposes] == ["c"]
    # Le troisième reste préqualifié : c'est lui qu'on rappelle en cas de désistement.
    assert [i for i, _ in classement.prequalifies] == ["a", "b", "c"]
    assert classement.ecartes == ()


def test_le_plancher_ecarte_avant_le_quota():
    notations = {
        "a": notation_a(28, seuil=19),
        "b": notation_a(10, seuil=19),
    }
    classement = classer(notations, nombre_a_proposer=5)
    assert [i for i, _ in classement.proposes] == ["a"]
    assert [i for i, _ in classement.ecartes] == ["b"]


def test_l_ordre_est_stable_a_note_egale():
    classement = classer({"zoe": notation_a(20), "abel": notation_a(20)})
    assert [i for i, _ in classement.proposes] == ["abel", "zoe"]


def test_notation_reproductible():
    """Deux calculs identiques donnent le même résultat, ligne à ligne."""
    a = noter(profil(), exigences(), appreciation_consistance=0.5)
    b = noter(profil(), exigences(), appreciation_consistance=0.5)
    assert a == b


# --- référentiel d'ajouts, resté disponible ----------------------------------


def test_un_client_peut_encore_demander_des_ajouts():
    """Le référentiel n'est pas retiré : il est seulement absent par défaut."""
    bareme = Bareme(
        consistance=BaremeConsistance(
            points_max=3.0,
            points_dossier_complet=1.0,
            points_coherence=1.0,
            points_appreciation=1.0,
        ),
        formation=BaremeFormation(points_max=7, points_niveau_requis=5),
        experience_generale=BaremeExperience(points_max=5, points_au_seuil=3),
        experience_specifique=BaremeExperience(points_max=13, points_au_seuil=9),
        ajouts=(RegleAjout(CodeAjout.LANGUE_SUPPLEMENTAIRE, points=1.0, repetitions_max=2),),
        points_ajouts_max=2.0,
        total_max=30.0,
    )
    polyglotte = profil(langues=frozenset({"français", "anglais", "allemand", "wolof"}))
    assert ligne(noter(polyglotte, exigences(), bareme), "AJOUTS").points == 2.0
