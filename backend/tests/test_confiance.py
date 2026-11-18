"""Seuls remontent les dossiers que la plateforme n'a pas su trancher seule."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.db import SessionLocal
from app.domain.referentiel import PieceDossier as P
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
from app.services import confiance
from app.services.preselection import charger_candidature, evaluer_candidature

pytestmark = pytest.mark.anyio

# L'original, avant que la fixture ne le remplace.
_TIRAGE = confiance._tire_au_sort

API = "/api/v1"

CV = (
    "Afi DOSSOU\nEXPÉRIENCE PROFESSIONNELLE\n2014 - 2024 : Responsable logistique, Port Sec de Lomé\n"
    "- suivi des expéditions et des équipes de quai\nFORMATION\n2012 : Master en logistique, Université de Lomé\n"
)
LETTRE = (
    "LETTRE DE MOTIVATION\nObjet : candidature au poste de responsable logistique\nMadame, Monsieur,\n"
    "Je vous adresse ma candidature avec un vif intérêt pour ce poste.\n"
    "Veuillez agréer, Madame, Monsieur, mes salutations distinguées.\n"
)


@pytest.fixture(autouse=True)
def sans_tirage(monkeypatch):
    monkeypatch.setattr(confiance, "_tire_au_sort", lambda identifiant: False)


async def poste_de(db, annees: int = 5) -> str:
    client = Client(nom="Client fictif")
    db.add(client)
    await db.flush()
    mandat = Mandat(client_id=client.id, intitule="Mandat")
    db.add(mandat)
    await db.flush()
    poste = Poste(
        mandat_id=mandat.id, intitule="Responsable logistique", niveau_min=3,
        domaines_acceptes=["logistique"], annees_experience_min=annees,
        pieces_requises=[P.CV.value],
    )
    db.add(poste)
    await db.flush()
    db.add(Avis(poste_id=poste.id, reference="AVIS", date_cloture=date(2026, 12, 31)))
    await db.flush()
    return poste.id


async def dossier(
    db, poste_id: str, *, pieces, diplomes=(("Master en logistique", 5),),
    experiences=(("Responsable logistique", "Port Sec de Lomé", date(2014, 1, 1), date(2024, 1, 1)),),
) -> str:
    candidat = Candidat(nom="DOSSOU", prenom="Afi", email="afi@example.tg", provenance=Provenance.EXTRAIT_IA)
    db.add(candidat)
    await db.flush()
    for intitule, niveau in diplomes:
        db.add(DiplomeCandidat(candidat_id=candidat.id, intitule=intitule, niveau=niveau, domaine="logistique", provenance=Provenance.EXTRAIT_IA))
    for poste, employeur, debut, fin in experiences:
        db.add(ExperienceCandidat(candidat_id=candidat.id, poste=poste, employeur=employeur, debut=debut, fin=fin, provenance=Provenance.EXTRAIT_IA))
    candidature = Candidature(poste_id=poste_id, candidat_id=candidat.id, source=SourceCandidature.EMAIL, recue_le=datetime(2026, 7, 15))
    db.add(candidature)
    await db.flush()
    for type_piece, texte in pieces:
        db.add(PieceCandidature(candidature_id=candidature.id, type_piece=type_piece, nom_fichier=f"{type_piece}.pdf", texte_extrait=texte))
    await db.flush()
    await evaluer_candidature(db, await charger_candidature(db, candidature.id))
    return candidature.id


async def voie(identifiant: str) -> confiance.Confiance:
    async with SessionLocal() as db:
        return confiance.evaluer(await charger_candidature(db, identifiant))


async def test_un_dossier_sans_signe_est_sur():
    async with SessionLocal() as db:
        poste = await poste_de(db)
        identifiant = await dossier(db, poste, pieces=[(P.CV.value, CV), (P.LETTRE_MOTIVATION.value, LETTRE)])
        await db.commit()

    assert (await voie(identifiant)).voie == confiance.SUR


async def test_un_cv_consistant_sans_experience_lue_est_a_relire():
    long_cv = CV + "\n".join(f"- mission {n} : coordination des expéditions et des inventaires" for n in range(40))
    async with SessionLocal() as db:
        poste = await poste_de(db)
        identifiant = await dossier(db, poste, pieces=[(P.CV.value, long_cv)], experiences=())
        await db.commit()

    avis = await voie(identifiant)

    assert avis.voie == confiance.RELIRE
    assert "parcours_vide" in [s.code for s in avis.signaux]


async def test_une_lettre_cachee_dans_le_pdf_du_cv_pose_une_question():
    async with SessionLocal() as db:
        poste = await poste_de(db)
        identifiant = await dossier(db, poste, pieces=[(P.CV.value, CV + "\n" + LETTRE)])
        await db.commit()

    avis = await voie(identifiant)

    assert avis.voie == confiance.QUESTION
    compose = next(s for s in avis.signaux if s.code == "fichier_compose")
    assert "lettre de motivation" in compose.texte


async def test_un_master_en_cours_pose_une_question():
    async with SessionLocal() as db:
        poste = await poste_de(db)
        identifiant = await dossier(
            db, poste, pieces=[(P.CV.value, CV), (P.LETTRE_MOTIVATION.value, LETTRE)],
            diplomes=(("Master professionnel en logistique (mémoire en cours)", 5),),
        )
        await db.commit()

    assert "diplome_en_cours" in [s.code for s in (await voie(identifiant)).signaux]


async def test_quelques_mois_du_seuil_posent_une_question():
    async with SessionLocal() as db:
        poste = await poste_de(db, annees=10)
        identifiant = await dossier(
            db, poste, pieces=[(P.CV.value, CV), (P.LETTRE_MOTIVATION.value, LETTRE)],
            experiences=(("Responsable logistique", "Port Sec de Lomé", date(2014, 4, 1), date(2024, 1, 1)),),
        )
        await db.commit()

    avis = await voie(identifiant)

    assert "seuil_experience" in [s.code for s in avis.signaux]
    # L'expérience manque : le motif est à confirmer, pas tranché.
    assert any(s.code.startswith("motif_") for s in avis.signaux)


async def test_le_controle_au_hasard_remonte_un_dossier_sur(monkeypatch):
    monkeypatch.setattr(confiance, "_tire_au_sort", lambda identifiant: True)
    async with SessionLocal() as db:
        poste = await poste_de(db)
        identifiant = await dossier(db, poste, pieces=[(P.CV.value, CV), (P.LETTRE_MOTIVATION.value, LETTRE)])
        await db.commit()

    avis = await voie(identifiant)

    assert (avis.voie, avis.controle) == (confiance.QUESTION, True)


def test_le_tirage_est_stable_et_vaut_environ_un_sur_dix():
    tirages = [_TIRAGE(f"candidature-{n}") for n in range(2000)]

    assert tirages == [_TIRAGE(f"candidature-{n}") for n in range(2000)]
    assert 0.07 < sum(tirages) / len(tirages) < 0.13


async def test_seuls_les_dossiers_surs_sont_confirmes_d_un_coup(client, auth):
    async with SessionLocal() as db:
        poste = await poste_de(db)
        sur = await dossier(db, poste, pieces=[(P.CV.value, CV), (P.LETTRE_MOTIVATION.value, LETTRE)])
        douteux = await dossier(db, poste, pieces=[(P.CV.value, CV + "\n" + LETTRE)])
        await db.commit()

    voies = (await client.get(f"{API}/postes/{poste}/confiance", headers=auth)).json()
    assert voies["dossiers"][sur]["voie"] == confiance.SUR
    assert voies["dossiers"][douteux]["voie"] == confiance.QUESTION

    reponse = await client.post(f"{API}/postes/{poste}/confiance/confirmer", headers=auth)
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["confirmes"] == 1

    apres = (await client.get(f"{API}/postes/{poste}/confiance", headers=auth)).json()
    assert apres["dossiers"][sur]["voie"] == confiance.FAIT
    assert apres["dossiers"][douteux]["voie"] == confiance.QUESTION


async def test_un_motif_net_ecarte_sans_poser_de_question():
    async with SessionLocal() as db:
        poste = await poste_de(db, annees=10)
        identifiant = await dossier(
            db, poste,
            pieces=[(P.CV.value, "EXPÉRIENCE PROFESSIONNELLE\n2022 - 2024 : Agent de quai, Port Sec de Lomé\n"), (P.LETTRE_MOTIVATION.value, LETTRE)],
            experiences=(("Agent de quai", "Port Sec de Lomé", date(2022, 1, 1), date(2024, 1, 1)),),
        )
        await db.commit()

    avis = await voie(identifiant)

    assert avis.voie == confiance.ECARTE
    assert all(s.gravite == confiance.DECISION for s in avis.signaux)


async def test_un_cv_bien_plus_long_que_la_lecture_n_est_jamais_ecarte():
    cv = (
        "EXPÉRIENCE PROFESSIONNELLE\n2005 - 2015 : Chef de quai, Togo Transit\n"
        "2015 - 2024 : Responsable logistique, Port Sec de Lomé\n"
    )
    async with SessionLocal() as db:
        poste = await poste_de(db, annees=10)
        # La lecture n'a gardé que le dernier emploi : 2 ans.
        identifiant = await dossier(
            db, poste, pieces=[(P.CV.value, cv), (P.LETTRE_MOTIVATION.value, LETTRE)],
            experiences=(("Responsable logistique", "Port Sec de Lomé", date(2022, 1, 1), date(2024, 1, 1)),),
        )
        await db.commit()

    avis = await voie(identifiant)

    assert avis.voie == confiance.RELIRE
    assert "lecture_incomplete" in [s.code for s in avis.signaux]


async def test_les_ecartes_nets_se_confirment_a_part(client, auth):
    async with SessionLocal() as db:
        poste = await poste_de(db, annees=10)
        ecarte = await dossier(
            db, poste,
            pieces=[(P.CV.value, "EXPÉRIENCE PROFESSIONNELLE\n2022 - 2024 : Agent de quai, Port Sec de Lomé\n"), (P.LETTRE_MOTIVATION.value, LETTRE)],
            experiences=(("Agent de quai", "Port Sec de Lomé", date(2022, 1, 1), date(2024, 1, 1)),),
        )
        await db.commit()

    assert (await client.post(f"{API}/postes/{poste}/confiance/confirmer", headers=auth)).json()["confirmes"] == 0
    reponse = await client.post(f"{API}/postes/{poste}/confiance/confirmer?voie=ECARTE", headers=auth)

    assert reponse.json()["confirmes"] == 1
    corps = (await client.get(f"{API}/candidatures/{ecarte}", headers=auth)).json()
    assert corps["statut"] == "ELIMINEE"
