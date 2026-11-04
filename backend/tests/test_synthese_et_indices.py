"""La synthèse d'un dossier, et ce que le dossier oppose à un motif."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.db import SessionLocal
from app.domain.referentiel import MotifElimination, PieceDossier as P
from app.models.base import utcnow
from app.models.enums import Provenance, SourceCandidature, StatutCandidature
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
from app.services import synthese
from app.services.preselection import charger_candidature, evaluer_candidature

pytestmark = pytest.mark.anyio

API = "/api/v1"


async def monter(db, *, poste=None, provenance=Provenance.EXTRAIT_IA, pieces=(), diplomes=(), experiences=()):
    client = Client(nom="Client fictif")
    db.add(client)
    await db.flush()
    mandat = Mandat(client_id=client.id, intitule="Mandat")
    db.add(mandat)
    await db.flush()
    valeurs = dict(
        intitule="Directeur logistique",
        niveau_min=3,
        domaines_acceptes=["logistique"],
        annees_experience_min=0,
        annees_experience_specifique_min=5,
        domaines_experience=["Pétrole & Gaz"],
        pieces_requises=[P.CV.value],
    )
    valeurs.update(poste or {})
    fiche = Poste(mandat_id=mandat.id, **valeurs)
    db.add(fiche)
    await db.flush()
    db.add(Avis(poste_id=fiche.id, reference="AVIS", date_cloture=date(2026, 12, 31)))
    candidat = Candidat(nom="DOSSOU", prenom="Afi", email="afi@example.tg", provenance=provenance)
    db.add(candidat)
    await db.flush()
    for d in diplomes:
        db.add(DiplomeCandidat(candidat_id=candidat.id, provenance=provenance, **d))
    for e in experiences:
        db.add(ExperienceCandidat(candidat_id=candidat.id, provenance=provenance, **e))
    candidature = Candidature(
        poste_id=fiche.id,
        candidat_id=candidat.id,
        source=SourceCandidature.EMAIL,
        recue_le=datetime(2026, 7, 15, 9, 0),
    )
    db.add(candidature)
    await db.flush()
    for type_piece, nom, texte in pieces:
        db.add(
            PieceCandidature(
                candidature_id=candidature.id, type_piece=type_piece, nom_fichier=nom, texte_extrait=texte
            )
        )
    await db.flush()
    chargee = await charger_candidature(db, candidature.id)
    await evaluer_candidature(db, chargee)
    await db.flush()
    return await charger_candidature(db, candidature.id)


def motif(candidature, code):
    return next(e for e in candidature.eliminations if e.motif is code)


DIPLOME = {"intitule": "Master en supply chain", "niveau": 5, "domaine": "supply chain", "etablissement": "Université de Lomé"}
EXPERIENCE = {
    "poste": "Directeur logistique",
    "employeur": "Oryx Energies",
    "debut": date(2014, 1, 1),
    "fin": None,
    "domaines": [],
}


async def test_le_profil_se_dit_en_deux_phrases():
    async with SessionLocal() as db:
        c = await monter(db, diplomes=[DIPLOME], experiences=[EXPERIENCE])
        rendu = synthese.rediger(c, date(2026, 11, 4))

    assert rendu.profil.startswith("Profil logistique")
    assert "Bac+5 (Master en supply chain)" in rendu.profil
    assert "plus de 12 ans d'expérience" in rendu.profil
    assert "Poste actuel : Directeur logistique chez Oryx Energies." in rendu.profil


async def test_l_experience_specifique_s_ajoute_au_profil():
    async with SessionLocal() as db:
        c = await monter(
            db,
            diplomes=[DIPLOME],
            experiences=[{**EXPERIENCE, "domaines": ["Pétrole & Gaz"]}],
        )
        rendu = synthese.rediger(c, date(2026, 11, 4))

    assert "dont 12 ans en Pétrole & Gaz" in rendu.profil


async def test_ce_qui_se_remarque_est_note():
    async with SessionLocal() as db:
        c = await monter(
            db,
            diplomes=[
                DIPLOME,
                {"intitule": "MBA", "niveau": 5, "domaine": "gestion", "etablissement": "HEC Paris"},
            ],
            experiences=[{**EXPERIENCE, "pays": "Sénégal"}],
        )
        c.candidat.langues = ["Français", "Anglais"]
        c.candidat.certifications = ["PMP"]
        rendu = synthese.rediger(c, date(2026, 11, 4))

    notes = " | ".join(rendu.notes)
    assert "HEC Paris" in notes
    assert "Certifications : PMP" in notes
    assert "Langues : Anglais" in notes
    assert "Encadrement : Directeur logistique" in notes
    assert "Expérience hors du Togo : Sénégal" in notes


async def test_la_synthese_ne_parle_ni_d_age_ni_de_sexe_ni_de_nationalite():
    async with SessionLocal() as db:
        c = await monter(db, diplomes=[DIPLOME], experiences=[EXPERIENCE])
        c.candidat.date_naissance = date(1980, 1, 1)
        c.candidat.nationalites = ["Togolaise"]
        rendu = synthese.rediger(c, date(2026, 11, 4))

    tout = " ".join([rendu.profil, *rendu.notes, *rendu.a_verifier]).lower()
    for mot in ("1980", "togolaise", "âge", " ans,", "monsieur", "madame", " elle ", " il "):
        assert mot not in tout


async def test_a_verifier_dit_ce_qui_manque_au_parcours():
    async with SessionLocal() as db:
        c = await monter(
            db,
            diplomes=[DIPLOME],
            experiences=[
                {**EXPERIENCE, "debut": date(2015, 1, 1), "fin": date(2017, 1, 1)},
                {**EXPERIENCE, "debut": date(2020, 1, 1), "fin": None},
            ],
            pieces=[(P.CV.value, "cv.pdf", "x"), (P.CV.value, "cv2.pdf", "x"), (P.AUTRE.value, "scan.pdf", "x")],
        )
        points = " | ".join(synthese.rediger(c, date(2026, 11, 4)).a_verifier)

    assert "Aucune attestation de travail" in points
    assert "Diplôme cité sans copie jointe" in points
    assert "2 documents rangés comme CV" in points
    assert "1 document(s) non identifié(s)" in points
    assert "Interruption de 3 ans" in points


async def test_une_attestation_contredit_le_motif_et_le_retient():
    """Le dossier est déclaré : sans indice, le motif éliminerait aussitôt."""
    async with SessionLocal() as db:
        c = await monter(
            db,
            provenance=Provenance.DECLARE,
            diplomes=[DIPLOME],
            experiences=[{**EXPERIENCE, "employeur": "Une société", "poste": "Agent"}],
            pieces=[(P.ATTESTATIONS_TRAVAIL.value, "attestation.pdf", "Chef de dépôt à la raffinerie de Lomé")],
        )
        retenu = motif(c, MotifElimination.EXPERIENCE_SPECIFIQUE_INSUFFISANTE)

    assert retenu.indice == "« raffinerie » figure dans « attestation.pdf »"
    assert retenu.sur_donnee_non_verifiee
    assert c.statut is StatutCandidature.A_VERIFIER


async def test_sans_rien_dans_le_dossier_le_motif_elimine_comme_avant():
    async with SessionLocal() as db:
        c = await monter(
            db,
            provenance=Provenance.DECLARE,
            diplomes=[DIPLOME],
            experiences=[{**EXPERIENCE, "employeur": "Une société", "poste": "Agent"}],
            pieces=[(P.CV.value, "cv.pdf", "Agent de bureau dans une société de services")],
        )
        retenu = motif(c, MotifElimination.EXPERIENCE_SPECIFIQUE_INSUFFISANTE)

    assert retenu.indice is None
    assert not retenu.sur_donnee_non_verifiee
    assert c.statut is StatutCandidature.ELIMINEE


async def test_une_fois_relu_l_indice_ne_retient_plus():
    async with SessionLocal() as db:
        c = await monter(
            db,
            provenance=Provenance.DECLARE,
            diplomes=[DIPLOME],
            experiences=[{**EXPERIENCE, "employeur": "Une société", "poste": "Agent"}],
            pieces=[(P.ATTESTATIONS_TRAVAIL.value, "attestation.pdf", "Chef de dépôt à la raffinerie de Lomé")],
        )
        c.candidat.verifie_le = utcnow()
        await db.flush()
        await evaluer_candidature(db, c)
        await db.flush()
        c = await charger_candidature(db, c.id)
        retenu = motif(c, MotifElimination.EXPERIENCE_SPECIFIQUE_INSUFFISANTE)

    assert retenu.indice
    assert not retenu.sur_donnee_non_verifiee
    assert c.statut is StatutCandidature.ELIMINEE


async def test_un_diplome_voisin_n_elimine_pas_d_office():
    async with SessionLocal() as db:
        c = await monter(
            db,
            provenance=Provenance.DECLARE,
            poste={
                "domaines_acceptes": ["comptabilité"],
                "annees_experience_specifique_min": 0,
                "domaines_experience": [],
            },
            diplomes=[{"intitule": "Master en audit et contrôle de gestion", "niveau": 5, "domaine": "audit"}],
            experiences=[EXPERIENCE],
        )
        retenu = motif(c, MotifElimination.FORMATION_NON_CONFORME)

    assert "domaine voisin de « comptabilité »" in retenu.indice
    assert retenu.sur_donnee_non_verifiee


async def test_un_domaine_sans_rapport_reste_non_conforme():
    async with SessionLocal() as db:
        c = await monter(
            db,
            provenance=Provenance.DECLARE,
            poste={
                "domaines_acceptes": ["comptabilité"],
                "annees_experience_specifique_min": 0,
                "domaines_experience": [],
            },
            diplomes=[{"intitule": "Licence de lettres modernes", "niveau": 3, "domaine": "lettres"}],
            experiences=[EXPERIENCE],
        )
        retenu = motif(c, MotifElimination.FORMATION_NON_CONFORME)

    assert retenu.indice is None
    assert c.statut is StatutCandidature.ELIMINEE


async def test_une_piece_mal_rangee_est_signalee():
    async with SessionLocal() as db:
        c = await monter(
            db,
            poste={
                "pieces_requises": [P.CV.value, P.CASIER_JUDICIAIRE.value],
                "annees_experience_specifique_min": 0,
                "domaines_experience": [],
            },
            provenance=Provenance.DECLARE,
            diplomes=[DIPLOME],
            experiences=[EXPERIENCE],
            pieces=[
                (P.CV.value, "cv.pdf", "Expérience"),
                (P.AUTRE.value, "scan.pdf", "RÉPUBLIQUE TOGOLAISE\nCASIER JUDICIAIRE\nBulletin n° 3"),
            ],
        )
        retenu = motif(c, MotifElimination.DOSSIER_INCOMPLET)

    assert "« scan.pdf » semble contenir" in retenu.indice
    assert c.statut is StatutCandidature.A_VERIFIER


async def test_compter_une_experience_efface_le_motif_et_se_retire(client, auth):
    async with SessionLocal() as db:
        c = await monter(
            db,
            diplomes=[DIPLOME],
            experiences=[{**EXPERIENCE, "employeur": "Une société", "poste": "Agent"}],
            pieces=[(P.CV.value, "cv.pdf", "x")],
        )
        await db.commit()
        experience = c.candidat.experiences[0].id
        identifiant = c.id

    url = f"{API}/candidatures/{identifiant}/experiences/{experience}/domaines"
    reponse = await client.post(url, json={"domaine": "Pétrole & Gaz"}, headers=auth)
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert "EXPERIENCE_SPECIFIQUE_INSUFFISANTE" not in [e["motif"] for e in corps["eliminations"]]
    assert corps["synthese"]["domaines_specifiques"] == ["Pétrole & Gaz"]
    assert "dont 12 ans en Pétrole & Gaz" in corps["synthese"]["profil"]

    reponse = await client.post(url, json={"domaine": "Pétrole & Gaz", "compte": False}, headers=auth)
    assert "EXPERIENCE_SPECIFIQUE_INSUFFISANTE" in [e["motif"] for e in reponse.json()["eliminations"]]
