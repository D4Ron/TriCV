"""Lire ailleurs : un seul format, les mêmes contrôles, la même protection."""

from __future__ import annotations

import importlib.util
import json
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.domain.referentiel import PieceDossier as P
from app.models.base import utcnow
from app.models.enums import Provenance, SourceCandidature
from app.models.recrutement import (
    Avis,
    Candidat,
    Candidature,
    Client,
    ExperienceCandidat,
    Mandat,
    PieceCandidature,
    Poste,
)
from app.models.travail import ATTENTE, EN_COURS, FAIT, LECTURE_IA, Travail
from app.services import lecture_externe, travaux
from app.services.preselection import charger_candidature, evaluer_candidature

pytestmark = pytest.mark.anyio

API = "/api/v1"
CV = (
    "Afi DOSSOU\nafi.dossou@example.tg\nExpérience professionnelle\n"
    "2018 - 2023 Responsable logistique, Port Sec de Lomé\n"
    "- suivi des expéditions, des dépôts et des équipes de quai, sur deux sites et trois équipes\n"
    "- négociation des contrats de transport et pilotage du budget annuel des opérations\n"
    "Formation\n2014 Master en logistique, Université de Lomé\nLangues\nFrançais"
)
LU = {
    "diplomes": [{"intitule": "Master en logistique", "niveau": 5, "domaine": "logistique", "annee": 2014}],
    "experiences": [
        {"poste": "Responsable logistique", "employeur": "Port Sec de Lomé", "debut": "2018-01", "fin": "2023-01"},
        {"poste": "Chef de quai", "employeur": "Togo Transit", "debut": "2012-01", "fin": "2017-12"},
    ],
    "langues": ["Français", "Anglais"],
    "certifications": ["PMP"],
    "remarques": "Une interruption à vérifier en 2024.",
}


@pytest.fixture(autouse=True)
def sans_lecteur():
    travaux.lecteur_oublie()
    yield
    travaux.lecteur_oublie()


async def monter(db) -> tuple[str, str]:
    client = Client(nom="Client fictif")
    db.add(client)
    await db.flush()
    mandat = Mandat(client_id=client.id, intitule="Mandat")
    db.add(mandat)
    await db.flush()
    poste = Poste(
        mandat_id=mandat.id, intitule="Directeur logistique", niveau_min=3,
        domaines_acceptes=["logistique"], annees_experience_min=5, pieces_requises=[P.CV.value],
    )
    db.add(poste)
    await db.flush()
    db.add(Avis(poste_id=poste.id, reference="AVIS", date_cloture=date(2026, 12, 31)))
    candidat = Candidat(nom="DOSSOU", prenom="Afi", email="afi.dossou@example.tg", provenance=Provenance.EXTRAIT_IA)
    db.add(candidat)
    await db.flush()
    candidature = Candidature(
        poste_id=poste.id, candidat_id=candidat.id, source=SourceCandidature.EMAIL,
        recue_le=datetime(2026, 7, 15, 9, 0),
    )
    db.add(candidature)
    await db.flush()
    db.add(
        PieceCandidature(
            candidature_id=candidature.id, type_piece=P.CV.value, nom_fichier="DOSSOU_cv.pdf",
            texte_extrait=CV, chemin_stockage=f"tests/{candidature.id}.pdf",
        )
    )
    await db.flush()
    await evaluer_candidature(db, await charger_candidature(db, candidature.id))
    await db.commit()
    return poste.id, candidature.id


def fichier(document) -> dict:
    return {"fichier": ("result.json", json.dumps(document).encode(), "application/json")}


async def lot(client, auth, poste) -> dict:
    reponse = await client.get(f"{API}/postes/{poste}/lecture-externe", headers=auth)
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


async def test_ce_qui_sort_ne_porte_ni_nom_ni_fichier(client, auth):
    async with SessionLocal() as db:
        poste, _ = await monter(db)

    document = await lot(client, auth, poste)

    assert document["format"] == lecture_externe.FORMAT
    assert len(document["dossiers"]) == 1
    tout = json.dumps(document, ensure_ascii=False)
    assert "DOSSOU" not in tout
    assert "afi.dossou" not in tout
    assert "=== PIÈCE : CV ===" in document["dossiers"][0]["texte"]


async def test_un_result_json_verse_le_parcours_et_le_lecteur(client, auth):
    async with SessionLocal() as db:
        poste, identifiant = await monter(db)
    d = (await lot(client, auth, poste))["dossiers"][0]

    reponse = await client.post(
        f"{API}/postes/{poste}/lecture-externe",
        files=fichier(
            {
                "format": lecture_externe.FORMAT,
                "lecteur": "ollama:qwen3:8b",
                "dossiers": [{"candidature_id": identifiant, "empreinte": d["empreinte"], **LU}],
            }
        ),
        headers=auth,
    )
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["comptes"] == {"lu": 1}

    corps = (await client.get(f"{API}/candidatures/{identifiant}", headers=auth)).json()
    assert sorted(e["poste"] for e in corps["candidat"]["experiences"]) == [
        "Chef de quai",
        "Responsable logistique",
    ]
    assert corps["synthese"]["lecteur"] == "ollama:qwen3:8b"
    assert "interruption" in corps["synthese"]["remarques"]


async def test_une_note_dans_le_fichier_est_ignoree(client, auth):
    async with SessionLocal() as db:
        poste, identifiant = await monter(db)
    d = (await lot(client, auth, poste))["dossiers"][0]
    avant = (await client.get(f"{API}/candidatures/{identifiant}", headers=auth)).json()

    reponse = await client.post(
        f"{API}/postes/{poste}/lecture-externe",
        files=fichier(
            {
                "format": lecture_externe.FORMAT,
                "dossiers": [
                    {
                        "candidature_id": identifiant, "empreinte": d["empreinte"], "note": 30,
                        "score": 100, "diplomes": [], "experiences": [],
                    }
                ],
            }
        ),
        headers=auth,
    )
    assert reponse.json()["notes_ignorees"] == 1
    apres = (await client.get(f"{API}/candidatures/{identifiant}", headers=auth)).json()
    assert apres["notation"]["note_manuelle"] is None
    assert apres["notation"]["total"] <= avant["notation"]["total_max"]
    assert apres["notation"]["total"] != 30


async def test_un_dossier_confirme_ne_recoit_que_des_propositions(client, auth):
    async with SessionLocal() as db:
        poste, identifiant = await monter(db)
        c = await charger_candidature(db, identifiant)
        db.add(
            ExperienceCandidat(
                candidat_id=c.candidat_id, poste="Directeur", employeur="Port Sec de Lomé",
                debut=date(2018, 1, 1), fin=date(2023, 1, 1), provenance=Provenance.VERIFIE_RH,
            )
        )
        c.candidat.verifie_le = utcnow()
        await db.commit()
    d = (await lot(client, auth, poste))
    assert d["dossiers"] == []
    empreinte = lecture_externe.empreinte_du_dossier(await _charger(identifiant))

    reponse = await client.post(
        f"{API}/postes/{poste}/lecture-externe",
        files=fichier(
            {
                "format": lecture_externe.FORMAT,
                "dossiers": [{"candidature_id": identifiant, "empreinte": empreinte, **LU}],
            }
        ),
        headers=auth,
    )
    assert reponse.json()["propositions"] >= 1
    corps = (await client.get(f"{API}/candidatures/{identifiant}", headers=auth)).json()
    assert [e["poste"] for e in corps["candidat"]["experiences"]] == ["Directeur"]


async def _charger(identifiant):
    async with SessionLocal() as db:
        return await charger_candidature(db, identifiant)


async def test_un_dossier_change_depuis_l_export_est_refuse(client, auth):
    async with SessionLocal() as db:
        poste, identifiant = await monter(db)
    d = (await lot(client, auth, poste))["dossiers"][0]
    async with SessionLocal() as db:
        db.add(
            PieceCandidature(
                candidature_id=identifiant, type_piece=P.ATTESTATIONS_TRAVAIL.value,
                nom_fichier="att.pdf", texte_extrait="Nouvelle pièce.", chemin_stockage="tests/a.pdf",
            )
        )
        await db.commit()

    reponse = await client.post(
        f"{API}/postes/{poste}/lecture-externe",
        files=fichier(
            {
                "format": lecture_externe.FORMAT,
                "dossiers": [{"candidature_id": identifiant, "empreinte": d["empreinte"], **LU}],
            }
        ),
        headers=auth,
    )
    assert reponse.json()["comptes"] == {"perime": 1}


async def test_un_fichier_ne_touche_pas_a_un_autre_poste(client, auth):
    async with SessionLocal() as db:
        poste, _ = await monter(db)
        _, ailleurs = await monter(db)
    empreinte = lecture_externe.empreinte_du_dossier(await _charger(ailleurs))

    reponse = await client.post(
        f"{API}/postes/{poste}/lecture-externe",
        files=fichier(
            {
                "format": lecture_externe.FORMAT,
                "dossiers": [{"candidature_id": ailleurs, "empreinte": empreinte, **LU}],
            }
        ),
        headers=auth,
    )
    assert reponse.json()["comptes"] == {"autre_poste": 1}


@pytest.mark.parametrize(
    "contenu",
    [b"pas du json", b"[]", b'{"format": "autre"}', b'{"format": "tricv-lecture/1"}'],
)
async def test_un_fichier_invalide_est_refuse_proprement(client, auth, contenu):
    async with SessionLocal() as db:
        poste, _ = await monter(db)
    reponse = await client.post(
        f"{API}/postes/{poste}/lecture-externe",
        files={"fichier": ("result.json", contenu, "application/json")},
        headers=auth,
    )
    assert reponse.status_code == 422


async def test_un_dossier_mal_forme_n_arrete_pas_les_autres(client, auth):
    async with SessionLocal() as db:
        poste, identifiant = await monter(db)
    d = (await lot(client, auth, poste))["dossiers"][0]
    reponse = await client.post(
        f"{API}/postes/{poste}/lecture-externe",
        files=fichier(
            {
                "format": lecture_externe.FORMAT,
                "dossiers": [
                    {"candidature_id": "x"},
                    "n\'importe quoi",
                    {"candidature_id": identifiant, "empreinte": d["empreinte"], **LU},
                ],
            }
        ),
        headers=auth,
    )
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["comptes"]["lu"] == 1


# --- le lecteur local --------------------------------------------------------


async def cle(client, auth) -> dict:
    reponse = await client.post(f"{API}/settings/lecteur/cle", headers=auth)
    assert reponse.status_code == 200, reponse.text
    return {"x-cle-lecteur": reponse.json()["cle"]}


async def en_file(identifiant, poste):
    async with SessionLocal() as db:
        await travaux.ajouter(db, [(identifiant, poste)], LECTURE_IA)
        await db.commit()


async def lignes():
    async with SessionLocal() as db:
        return list((await db.execute(select(Travail))).scalars())


async def test_le_lecteur_exige_sa_cle(client, auth):
    assert (await client.get(f"{API}/lecteur/travaux")).status_code == 401
    assert (await client.get(f"{API}/lecteur/travaux", headers={"x-cle-lecteur": "non"})).status_code == 401
    # Un jeton de connexion n'ouvre pas ces adresses, et la clé n'ouvre rien d'autre.
    assert (await client.get(f"{API}/lecteur/travaux", headers=auth)).status_code == 401
    entetes = await cle(client, auth)
    assert (await client.get(f"{API}/lecteur/travaux", headers=entetes)).status_code == 200
    assert (await client.get(f"{API}/settings", headers=entetes)).status_code == 401


async def test_la_cle_retiree_ne_vaut_plus_rien_et_n_est_pas_gardee_en_clair(client, auth):
    entetes = await cle(client, auth)
    async with SessionLocal() as db:
        from app.services import parametres

        gardee = await db.get(parametres.Parametre, parametres.LECTEUR_CLE)
        assert gardee.valeur != entetes["x-cle-lecteur"]

    assert (await client.delete(f"{API}/settings/lecteur/cle", headers=auth)).status_code == 204
    assert (await client.get(f"{API}/lecteur/travaux", headers=entetes)).status_code == 401


async def test_le_lecteur_prend_lit_et_rend(client, auth):
    entetes = await cle(client, auth)
    async with SessionLocal() as db:
        poste, identifiant = await monter(db)
    await en_file(identifiant, poste)

    pris = (await client.get(f"{API}/lecteur/travaux?modele=ollama:qwen3:8b", headers=entetes)).json()
    d = pris["dossiers"][0]
    assert "DOSSOU" not in d["texte"]
    assert (await lignes())[0].etat == EN_COURS
    # Réservé : un autre appel ne le reprend pas.
    assert (await client.get(f"{API}/lecteur/travaux", headers=entetes)).json()["dossiers"] == []

    rendu = await client.post(
        f"{API}/lecteur/resultats",
        json={
            "travail_id": d["travail_id"], "lecteur": "ollama:qwen3:8b", "secondes": 48.0, "jetons": 3000,
            "resultat": {"candidature_id": identifiant, "empreinte": d["empreinte"], **LU},
        },
        headers=entetes,
    )
    assert rendu.status_code == 200, rendu.text
    travail = (await lignes())[0]
    assert (travail.etat, travail.secondes, travail.fournisseur) == (FAIT, 48.0, "ollama:qwen3:8b")

    corps = (await client.get(f"{API}/candidatures/{identifiant}", headers=auth)).json()
    assert len(corps["candidat"]["experiences"]) == 2


async def test_tant_que_le_lecteur_est_la_le_serveur_ne_lit_pas(client, auth):
    entetes = await cle(client, auth)
    async with SessionLocal() as db:
        poste, identifiant = await monter(db)
    await en_file(identifiant, poste)
    await client.post(f"{API}/settings/lecteur/cle", headers=auth)
    travaux.lecteur_vu("ollama:qwen3:8b")

    assert await travaux.traiter_un() is None
    assert (await lignes())[0].etat == ATTENTE

    # Parti : le serveur reprend la main.
    travaux.lecteur_oublie()
    async with SessionLocal() as db:
        assert (await travaux._suivant(db)) is not None
    assert entetes


async def test_un_echec_du_lecteur_rend_le_dossier_a_la_file(client, auth):
    entetes = await cle(client, auth)
    async with SessionLocal() as db:
        poste, identifiant = await monter(db)
    await en_file(identifiant, poste)
    d = (await client.get(f"{API}/lecteur/travaux", headers=entetes)).json()["dossiers"][0]

    await client.post(
        f"{API}/lecteur/resultats", json={"travail_id": d["travail_id"], "erreur": "JSON illisible"}, headers=entetes
    )
    travail = (await lignes())[0]
    assert (travail.etat, travail.essais) == (ATTENTE, 1)


async def test_un_lecteur_tombe_en_route_rend_le_dossier(client, auth):
    entetes = await cle(client, auth)
    async with SessionLocal() as db:
        poste, identifiant = await monter(db)
    await en_file(identifiant, poste)
    await client.get(f"{API}/lecteur/travaux", headers=entetes)
    async with SessionLocal() as db:
        travail = (await db.execute(select(Travail))).scalars().one()
        travail.pas_avant = datetime(2020, 1, 1)
        await db.commit()

    repris = (await client.get(f"{API}/lecteur/travaux", headers=entetes)).json()
    assert len(repris["dossiers"]) == 1


async def test_un_quota_en_attente_n_empeche_pas_le_lecteur(client, auth):
    entetes = await cle(client, auth)
    async with SessionLocal() as db:
        poste, identifiant = await monter(db)
    await en_file(identifiant, poste)
    async with SessionLocal() as db:
        travail = (await db.execute(select(Travail))).scalars().one()
        travail.pas_avant = datetime(2099, 1, 1)
        await db.commit()

    assert len((await client.get(f"{API}/lecteur/travaux", headers=entetes)).json()["dossiers"]) == 1


async def test_le_suivi_annonce_le_lecteur_local(client, auth):
    async with SessionLocal() as db:
        poste, _ = await monter(db)
    travaux.lecteur_vu("ollama:qwen3:8b")
    etat = (await client.get(f"{API}/postes/{poste}/lectures", headers=auth)).json()
    assert etat["fournisseurs"][0]["local"] is True
    assert "qwen3" in etat["fournisseurs"][0]["nom"]


# --- le script du poste ------------------------------------------------------


def script():
    chemin = Path(__file__).resolve().parents[1] / "tools" / "lecteur_local.py"
    spec = importlib.util.spec_from_file_location("lecteur_local", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "brut",
    [
        '{"diplomes": []}',
        '<think>je réfléchis { pas du json</think>{"diplomes": []}',
        '```json\n{"diplomes": []}\n```',
        'Voici :\n{"diplomes": []}\nFin.',
    ],
)
def test_le_script_lit_ce_que_rendent_les_modeles(brut):
    assert script().lire_json(brut) == {"diplomes": []}


def test_le_script_refuse_une_reponse_sans_json():
    with pytest.raises(ValueError):
        script().lire_json("Je ne peux pas.")


def test_le_script_n_a_besoin_de_rien_d_autre_que_python():
    texte = (Path(__file__).resolve().parents[1] / "tools" / "lecteur_local.py").read_text(encoding="utf-8")
    assert "from app" not in texte
    assert "import httpx" not in texte


def test_le_fichier_fabrique_par_le_script_se_lit_comme_un_resultat(tmp_path, monkeypatch):
    module = script()
    entree = tmp_path / "lecture.json"
    entree.write_text(
        json.dumps(
            {
                "format": lecture_externe.FORMAT,
                "consigne": "c",
                "dossiers": [{"candidature_id": "a", "empreinte": "e", "texte": "t"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "lire_un_dossier", lambda *a: ({"diplomes": [], "experiences": []}, 10))
    sortie = tmp_path / "result.json"
    module.traiter_fichier(str(entree), str(sortie), "http://ollama", "qwen3:8b")

    rendu = json.loads(sortie.read_text(encoding="utf-8"))
    assert rendu["lecteur"] == "ollama:qwen3:8b"
    assert lecture_externe.ResultatDossier.model_validate(rendu["dossiers"][0]).empreinte == "e"


@pytest.mark.parametrize("exhaustif, attendus", [
    (False, ["Chef de quai", "Responsable logistique"]),
    (True, ["Chef de quai"]),
])
async def test_une_lecture_exhaustive_n_est_pas_completee_par_les_regles(client, auth, exhaustif, attendus):
    """Le lecteur qui a tout vérifié a pu écarter un poste à dessein : on ne le remet pas."""
    async with SessionLocal() as db:
        poste, identifiant = await monter(db)
    d = (await lot(client, auth, poste))["dossiers"][0]
    lu = {**LU, "experiences": [LU["experiences"][1]], "exhaustif": exhaustif}

    reponse = await client.post(
        f"{API}/postes/{poste}/lecture-externe",
        files=fichier({"format": lecture_externe.FORMAT, "lecteur": "claude-code",
                       "dossiers": [{"candidature_id": identifiant, "empreinte": d["empreinte"], **lu}]}),
        headers=auth,
    )
    assert reponse.status_code == 200, reponse.text

    corps = (await client.get(f"{API}/candidatures/{identifiant}", headers=auth)).json()
    assert sorted(e["poste"] for e in corps["candidat"]["experiences"]) == attendus
