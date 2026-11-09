"""Les RH corrigent chaque ligne de la note ; le calcul reste visible à côté."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.db import SessionLocal
from app.domain.bareme import LigneNote, Notation, appliquer_ajustements
from app.domain.referentiel import PieceDossier as P
from app.llm import quotas
from app.llm.base import DiplomeExtrait, DossierExtrait, ExperienceExtraite
from app.models.enums import Provenance, SourceCandidature
from app.models.recrutement import (
    Avis,
    Candidat,
    Candidature,
    Client,
    DiplomeCandidat,
    ExperienceCandidat,
    Mandat,
    PieceCandidature,
    Poste,
)
from app.models.travail import FAIT, LECTURE_IA, Travail
from app.services import depouillement, lecture_locale, travaux
from app.services.preselection import charger_candidature, evaluer_candidature

pytestmark = pytest.mark.anyio

API = "/api/v1"


def notation() -> Notation:
    return Notation(
        lignes=(
            LigneNote("FORMATION", "Formation", 3.0, 7.0, "x"),
            LigneNote("CONSISTANCE", "Consistance", 1.0, 3.0, "y"),
        ),
        total=4.0,
        total_max=10.0,
        seuil=5.0,
    )


def test_un_ajustement_refait_le_total_et_garde_le_calcul():
    ajustee = appliquer_ajustements(notation(), {"FORMATION": 6})
    ligne = ajustee.lignes[0]
    assert (ligne.points, ligne.points_calcules) == (6.0, 3.0)
    assert ajustee.total == 7.0
    assert ajustee.atteint_le_seuil


def test_un_ajustement_reste_borne_et_ignore_une_ligne_disparue():
    ajustee = appliquer_ajustements(notation(), {"FORMATION": 99, "DISPARUE": 5})
    assert ajustee.lignes[0].points == 7.0
    assert ajustee.total == 8.0


async def monter(db) -> str:
    client = Client(nom="Client fictif")
    db.add(client)
    await db.flush()
    mandat = Mandat(client_id=client.id, intitule="Mandat")
    db.add(mandat)
    await db.flush()
    poste = Poste(
        mandat_id=mandat.id,
        intitule="Directeur logistique",
        niveau_min=3,
        domaines_acceptes=["logistique"],
        annees_experience_min=2,
        pieces_requises=[P.CV.value],
    )
    db.add(poste)
    await db.flush()
    db.add(Avis(poste_id=poste.id, reference="AVIS", date_cloture=date(2026, 12, 31)))
    candidat = Candidat(nom="DOSSOU", prenom="Afi", email="a@example.tg", provenance=Provenance.EXTRAIT_IA)
    db.add(candidat)
    await db.flush()
    db.add(
        DiplomeCandidat(
            candidat_id=candidat.id, intitule="Master en logistique", niveau=5,
            domaine="logistique", provenance=Provenance.EXTRAIT_IA,
        )
    )
    db.add(
        ExperienceCandidat(
            candidat_id=candidat.id, poste="Chef de quai", employeur="Togo Transit",
            debut=date(2015, 1, 1), fin=date(2020, 1, 1), provenance=Provenance.EXTRAIT_IA,
        )
    )
    candidature = Candidature(
        poste_id=poste.id, candidat_id=candidat.id, source=SourceCandidature.EMAIL,
        recue_le=datetime(2026, 7, 15, 9, 0),
    )
    db.add(candidature)
    await db.flush()
    db.add(
        PieceCandidature(
            candidature_id=candidature.id, type_piece=P.ATTESTATIONS_TRAVAIL.value,
            nom_fichier="att.pdf", texte_extrait="Chef de quai à Togo Transit de 2015 à 2020.",
        )
    )
    db.add(
        PieceCandidature(
            candidature_id=candidature.id, type_piece=P.LETTRE_MOTIVATION.value,
            nom_fichier="lettre.pdf", texte_extrait="Madame, je vous écris.",
        )
    )
    await db.flush()
    await evaluer_candidature(db, await charger_candidature(db, candidature.id))
    await db.commit()
    return candidature.id


def ligne(corps, code):
    return next(l for l in corps["notation"]["lignes"] if l["code"] == code)


async def test_corriger_une_ligne_change_le_total_et_survit_au_recalcul(client, auth):
    async with SessionLocal() as db:
        identifiant = await monter(db)
    avant = (await client.get(f"{API}/candidatures/{identifiant}", headers=auth)).json()
    formation = ligne(avant, "FORMATION")
    vise = formation["points_max"] - 0.5 if formation["points"] != formation["points_max"] - 0.5 else 1

    reponse = await client.patch(
        f"{API}/candidatures/{identifiant}/lignes/FORMATION",
        json={"points": vise, "motif": "Vérifié sur le document"},
        headers=auth,
    )
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    corrigee = ligne(corps, "FORMATION")
    assert corrigee["points"] == vise
    assert corrigee["points_calcules"] == formation["points"]
    assert corrigee["ajustement_motif"] == "Vérifié sur le document"
    assert corps["notation"]["total"] == pytest.approx(
        avant["notation"]["total"] - formation["points"] + vise
    )

    async with SessionLocal() as db:
        await evaluer_candidature(db, await charger_candidature(db, identifiant))
        await db.commit()
    apres = (await client.get(f"{API}/candidatures/{identifiant}", headers=auth)).json()
    assert ligne(apres, "FORMATION")["points"] == vise

    rendue = await client.patch(
        f"{API}/candidatures/{identifiant}/lignes/FORMATION", json={"points": None}, headers=auth
    )
    assert ligne(rendue.json(), "FORMATION")["points"] == formation["points"]
    assert ligne(rendue.json(), "FORMATION")["points_calcules"] is None


async def test_une_correction_sans_motif_ou_trop_haute_est_refusee(client, auth):
    async with SessionLocal() as db:
        identifiant = await monter(db)
    url = f"{API}/candidatures/{identifiant}/lignes/FORMATION"

    assert (await client.patch(url, json={"points": 1}, headers=auth)).status_code == 422
    trop = await client.patch(url, json={"points": 99, "motif": "x"}, headers=auth)
    assert trop.status_code == 422
    assert "se note sur" in trop.json()["detail"]
    inconnue = await client.patch(
        f"{API}/candidatures/{identifiant}/lignes/NIMPORTE", json={"points": 1, "motif": "x"}, headers=auth
    )
    assert inconnue.status_code == 404


async def test_la_synthese_dit_ce_que_chaque_piece_confirme(client, auth):
    async with SessionLocal() as db:
        identifiant = await monter(db)
        c = await charger_candidature(db, identifiant)
        attestation = next(p for p in c.pieces if p.nom_fichier == "att.pdf").id
        lettre = next(p for p in c.pieces if p.nom_fichier == "lettre.pdf").id
        experience = c.candidat.experiences[0].id

    corps = (await client.get(f"{API}/candidatures/{identifiant}", headers=auth)).json()
    par_piece = corps["synthese"]["par_piece"]
    assert par_piece[attestation]["experiences"] == [experience]
    assert lettre not in par_piece


# --- ce qui part au modèle ---------------------------------------------------


def test_chaque_piece_est_annoncee_et_le_brouillon_suit():
    locale = DossierExtrait(
        diplomes=[DiplomeExtrait(intitule="Master", niveau=5, annee=2012)],
        experiences=[ExperienceExtraite(poste="Chef", employeur="TT", debut="2015-01")],
    )
    texte = depouillement.composer_pour_ia(
        [(P.CV.value, "le cv"), (P.ATTESTATIONS_TRAVAIL.value, "attestation")], locale
    )
    assert "=== PIÈCE : CV ===\nle cv" in texte
    assert "=== PIÈCE : Attestation de travail ===" in texte
    assert "=== LECTURE AUTOMATIQUE À VÉRIFIER ===" in texte
    assert "Chef — TT" in texte


def test_un_long_cv_ne_chasse_plus_les_attestations():
    texte = depouillement.composer_pour_ia(
        [(P.CV.value, "x" * 40_000), (P.ATTESTATIONS_TRAVAIL.value, "EMPLOI ATTESTE")]
    )
    assert "EMPLOI ATTESTE" in texte
    assert len(texte) < 40_000


def test_ce_que_l_ia_oublie_et_que_la_lecture_a_vu_s_ajoute():
    locale = DossierExtrait(
        experiences=[
            ExperienceExtraite(poste="Chef", employeur="TT", debut="2015-01", fin="2018-01"),
            ExperienceExtraite(poste="Agent", employeur="PS", debut="2010-01", fin="2012-01"),
            ExperienceExtraite(poste="poste non précisé", employeur="X", debut="2005-01", fin="2006-01"),
        ],
        certifications=["PMP"],
    )
    ia = DossierExtrait(
        experiences=[ExperienceExtraite(poste="Chef de quai", employeur="Togo Transit", debut="2015-03", fin="2018-01")],
        certifications=["pmp", "ITIL"],
    )
    dossier, notes = lecture_locale.fusionner(locale, ia, date(2026, 11, 4))

    assert [e.poste for e in dossier.experiences] == ["Chef de quai", "Agent"]
    assert dossier.certifications == ["pmp", "ITIL"]
    assert any("oublié par l'IA" in n for n in notes)


def test_une_ligne_introuvable_dans_les_pieces_est_signalee():
    dossier = DossierExtrait(
        experiences=[
            ExperienceExtraite(poste="Chef de quai", employeur="Togo Transit", debut="2015-01"),
            ExperienceExtraite(poste="Astronaute", employeur="Lune SA", debut="2019-01"),
        ],
        diplomes=[DiplomeExtrait(intitule="Doctorat de physique quantique", niveau=8)],
    )
    notes = lecture_locale.non_ancrees(dossier, "Chef de quai chez Togo Transit, Master en logistique")
    assert len(notes) == 2
    assert "Astronaute" in notes[0]


# --- le temps restant --------------------------------------------------------


def test_les_entetes_de_mistral_et_de_groq_se_lisent():
    quotas.oublier()
    quotas.noter_entetes(
        "openai",
        {
            "x-ratelimit-limit-req-minute": "30",
            "x-ratelimit-remaining-req-minute": "29",
            "x-ratelimit-limit-tokens-minute": "937500",
            "x-ratelimit-remaining-tokens-minute": "937489",
        },
    )
    quotas.noter_entetes(
        "groq",
        {
            "x-ratelimit-limit-requests": "1000",
            "x-ratelimit-remaining-requests": "990",
            "x-ratelimit-limit-tokens": "8000",
            "x-ratelimit-remaining-tokens": "7000",
        },
    )
    quotas.noter_entetes("gemini", {"content-type": "application/json"})

    assert quotas.releve("openai").requetes_limite == 30
    assert quotas.releve("groq").periode_requetes == "jour"
    assert quotas.releve("gemini").requetes_limite is None
    quotas.oublier()


def test_la_consommation_se_lit_chez_tous():
    quotas.oublier()
    quotas.noter_usage("openai", {"usage": {"total_tokens": 11}})
    quotas.noter_usage("gemini", {"usageMetadata": {"totalTokenCount": 4}})
    assert quotas.consommation() == {"openai": 11, "gemini": 4}
    quotas.oublier()


def fournisseur(**k):
    return {
        "disponible": True, "requetes_limite": None, "periode_requetes": None,
        "jetons_limite": None, "periode_jetons": None, **k,
    }


def test_le_rythme_vient_de_la_lecture_sauf_si_le_quota_est_plus_lent():
    assert travaux._rythme_ia(10, 6000, [fournisseur()]) == (10 + travaux.PAUSE_ENTRE_APPELS, "lecture")
    assert travaux._rythme_ia(1, 6000, [fournisseur(requetes_limite=2, periode_requetes="minute")]) == (30, "quota")
    # Une limite par jour ne fixe pas le rythme d'une minute à l'autre.
    assert travaux._rythme_ia(1, 6000, [fournisseur(requetes_limite=2, periode_requetes="jour")])[1] == "lecture"


async def test_le_suivi_mesure_et_annonce_le_temps_restant(client, auth, monkeypatch):
    monkeypatch.setattr(travaux, "get_provider", lambda: (_ for _ in ()).throw(travaux.LLMError("rien")))
    async with SessionLocal() as db:
        identifiant = await monter(db)
        c = await charger_candidature(db, identifiant)
        poste = c.poste_id
        for _ in range(3):
            db.add(
                Travail(
                    nature=LECTURE_IA, candidature_id=identifiant, poste_id="autre", etat=FAIT,
                    secondes=20.0, jetons=5000, fournisseur="openai",
                )
            )
        await db.flush()
        await travaux.ajouter(db, [(identifiant, poste)], LECTURE_IA)
        await db.commit()

    etat = (await client.get(f"{API}/postes/{poste}/lectures", headers=auth)).json()
    assert etat["total"] == 1
    assert etat["mesures"] == 3
    assert etat["secondes_restantes"] == 20 + travaux.PAUSE_ENTRE_APPELS
    assert etat["cause"] == "lecture"
    assert etat["dossiers_a_lire"] == 1


def test_un_poste_lu_en_cours_garde_la_fin_que_le_dossier_ecrit():
    locale = DossierExtrait(
        experiences=[ExperienceExtraite(poste="Chef", employeur="TT", debut="2018-01", fin="2022-12")]
    )
    ia = DossierExtrait(
        experiences=[ExperienceExtraite(poste="Chef de quai", employeur="Togo Transit", debut="2018-01", fin=None)]
    )
    dossier, notes = lecture_locale.fusionner(locale, ia, date(2026, 11, 4))

    assert dossier.experiences[0].fin == "2022-12"
    assert any("toujours en poste" in n for n in notes)


def test_un_poste_vraiment_en_cours_le_reste():
    locale = DossierExtrait(
        experiences=[ExperienceExtraite(poste="Chef", employeur="TT", debut="2018-01", fin=None)]
    )
    ia = DossierExtrait(
        experiences=[ExperienceExtraite(poste="Chef de quai", employeur="Togo Transit", debut="2018-01", fin=None)]
    )
    dossier, _ = lecture_locale.fusionner(locale, ia, date(2026, 11, 4))

    assert dossier.experiences[0].fin is None


def test_une_fin_dans_l_annee_en_cours_ne_prouve_pas_que_le_poste_a_cesse():
    locale = DossierExtrait(
        experiences=[ExperienceExtraite(poste="Chef", employeur="TT", debut="2018-01", fin="2026-01")]
    )
    ia = DossierExtrait(
        experiences=[ExperienceExtraite(poste="Chef de quai", employeur="Togo Transit", debut="2018-01", fin=None)]
    )
    dossier, _ = lecture_locale.fusionner(locale, ia, date(2026, 11, 4))

    assert dossier.experiences[0].fin is None


# --- une correction contredit le motif qu'elle dément -------------------------


async def exiger_dix_ans(identifiant: str) -> None:
    async with SessionLocal() as db:
        candidature = await charger_candidature(db, identifiant)
        candidature.poste.annees_experience_min = 10
        await evaluer_candidature(db, candidature)
        await db.commit()


def motif(corps, code):
    return next(e for e in corps["eliminations"] if e["motif"] == code)


async def test_une_ligne_corrigee_leve_le_motif_qu_elle_dement_et_le_rend_si_on_la_retire(client, auth):
    async with SessionLocal() as db:
        identifiant = await monter(db)
    await exiger_dix_ans(identifiant)
    url = f"{API}/candidatures/{identifiant}/lignes/EXPERIENCE_GENERALE"
    avant = (await client.get(f"{API}/candidatures/{identifiant}", headers=auth)).json()
    assert motif(avant, "EXPERIENCE_INSUFFISANTE")["leve_le"] is None

    corps = (await client.patch(url, json={"points": 3, "motif": "Deux emplois oubliés par la lecture"}, headers=auth)).json()

    leve = motif(corps, "EXPERIENCE_INSUFFISANTE")
    assert leve["leve_le"] is not None
    assert "Deux emplois oubliés" in leve["leve_motif"]

    rendu = (await client.patch(url, json={"points": None}, headers=auth)).json()
    assert motif(rendu, "EXPERIENCE_INSUFFISANTE")["leve_le"] is None


async def test_une_correction_a_zero_ne_leve_rien(client, auth):
    async with SessionLocal() as db:
        identifiant = await monter(db)
    await exiger_dix_ans(identifiant)

    corps = (
        await client.patch(
            f"{API}/candidatures/{identifiant}/lignes/EXPERIENCE_GENERALE",
            json={"points": 0, "motif": "Confirmé"}, headers=auth,
        )
    ).json()

    assert motif(corps, "EXPERIENCE_INSUFFISANTE")["leve_le"] is None


async def test_une_levee_faite_a_la_main_survit_au_retrait_d_une_correction(client, auth):
    async with SessionLocal() as db:
        identifiant = await monter(db)
    await exiger_dix_ans(identifiant)
    leve = await client.post(
        f"{API}/candidatures/{identifiant}/eliminations/EXPERIENCE_INSUFFISANTE/lever",
        json={"motif": "Équivalence accordée par le client"}, headers=auth,
    )
    assert leve.status_code == 200, leve.text
    url = f"{API}/candidatures/{identifiant}/lignes/EXPERIENCE_GENERALE"
    await client.patch(url, json={"points": 3, "motif": "Vérifié"}, headers=auth)

    corps = (await client.patch(url, json={"points": None}, headers=auth)).json()

    garde = motif(corps, "EXPERIENCE_INSUFFISANTE")
    assert garde["leve_le"] is not None
    assert garde["leve_motif"] == "Équivalence accordée par le client"


async def test_la_synthese_suit_la_correction_au_lieu_de_la_contredire(client, auth):
    async with SessionLocal() as db:
        identifiant = await monter(db)
    avant = (await client.get(f"{API}/candidatures/{identifiant}", headers=auth)).json()
    assert "Bac+5" in avant["synthese"]["profil"]

    corps = (
        await client.patch(
            f"{API}/candidatures/{identifiant}/lignes/FORMATION",
            json={"points": 0, "motif": "Master en cours, mémoire non soutenu"}, headers=auth,
        )
    ).json()

    assert "Bac+5" not in corps["synthese"]["profil"]
    assert "formation revue par un relecteur" in corps["synthese"]["profil"]
    assert corps["synthese"]["notes"][0] == "Note corrigée — formation : 0 pt (Master en cours, mémoire non soutenu)"


def test_un_diplome_que_le_cv_dit_en_cours_n_est_pas_compte():
    cv = (
        "FORMATION\n"
        "Master Professionnel – Génie mécanique | 2024 — 2026 | Mémoire en cours | École fictive\n"
        "Licence Professionnelle – Génie mécanique | 2021 — 2024 | École fictive\n"
        "Parcours MBA (Sécurité et environnement)\n"
        "EXPÉRIENCE PROFESSIONNELLE\n2015 - 2020 : Chef de quai, Port Sec\n"
    )

    lus = lecture_locale.lire(cv, []).diplomes

    assert [(d.niveau, d.annee) for d in lus] == [(3, 2024)]
