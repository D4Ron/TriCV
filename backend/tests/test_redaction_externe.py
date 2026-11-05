"""Rapport et avis rédigés ailleurs : seule la prose voyage."""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from app.db import SessionLocal
from app.domain.referentiel import PieceDossier as P
from app.models.enums import Provenance, SourceCandidature
from app.models.recrutement import Avis, Candidat, Candidature, Client, Mandat, Poste
from app.services import redaction_externe
from app.services.preselection import charger_candidature, evaluer_candidature

pytestmark = pytest.mark.anyio

API = "/api/v1"


async def monter(db) -> dict:
    client = Client(nom="Client fictif")
    db.add(client)
    await db.flush()
    mandat = Mandat(client_id=client.id, intitule="Mandat fictif")
    db.add(mandat)
    await db.flush()
    poste = Poste(
        mandat_id=mandat.id, intitule="Directeur logistique", niveau_min=3,
        domaines_acceptes=["logistique"], annees_experience_min=5, pieces_requises=[P.CV.value],
    )
    db.add(poste)
    await db.flush()
    avis = Avis(poste_id=poste.id, reference="AVIS-1", date_cloture=date(2026, 12, 31))
    db.add(avis)
    candidat = Candidat(nom="DOSSOU", prenom="Afi", email="afi.dossou@example.tg", provenance=Provenance.VERIFIE_RH)
    db.add(candidat)
    await db.flush()
    candidature = Candidature(
        poste_id=poste.id, candidat_id=candidat.id, source=SourceCandidature.EMAIL,
        recue_le=datetime(2026, 7, 15, 9, 0),
    )
    db.add(candidature)
    await db.flush()
    await evaluer_candidature(db, await charger_candidature(db, candidature.id))
    await db.commit()
    return {"mandat": mandat.id, "poste": poste.id, "avis": avis.id}


def fichier(document) -> dict:
    return {"fichier": ("result.json", json.dumps(document).encode(), "application/json")}


async def rapport(client, auth, ids) -> dict:
    reponse = await client.post(
        f"{API}/mandats/{ids['mandat']}/rapports",
        json={"poste_id": ids["poste"], "avec_assistance": False, "type_rapport": "FINAL"},
        headers=auth,
    )
    assert reponse.status_code == 201, reponse.text
    return reponse.json()


async def lot_rapport(client, auth, identifiant) -> dict:
    reponse = await client.get(f"{API}/rapports/{identifiant}/redaction-externe", headers=auth)
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


def retour(lot, textes=None) -> dict:
    return {
        "format": redaction_externe.FORMAT,
        "lecteur": "ollama:qwen3:8b",
        "document": lot["document"],
        "sections": [
            {"code": t["code"], "texte": (textes or {}).get(t["code"], f"Texte de {t['code']}.")}
            for t in lot["taches"]
        ],
    }


async def test_le_lot_du_rapport_ne_porte_aucun_nom_de_candidat(client, auth):
    async with SessionLocal() as db:
        ids = await monter(db)
    r = await rapport(client, auth, ids)

    lot = await lot_rapport(client, auth, r["id"])

    assert lot["format"] == redaction_externe.FORMAT
    assert len(lot["taches"]) >= 1
    tout = json.dumps(lot, ensure_ascii=False)
    assert "DOSSOU" not in tout
    assert "example.tg" not in tout


async def test_la_redaction_remplit_les_sections_et_reste_a_relire(client, auth):
    async with SessionLocal() as db:
        ids = await monter(db)
    r = await rapport(client, auth, ids)
    lot = await lot_rapport(client, auth, r["id"])

    reponse = await client.post(
        f"{API}/rapports/{r['id']}/redaction-externe", files=fichier(retour(lot)), headers=auth
    )
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["versees"] == len(lot["taches"])

    corps = (await client.get(f"{API}/rapports/{r['id']}", headers=auth)).json()
    code = lot["taches"][0]["code"]
    section = next(s for s in corps["sections"] if s["code"] == code)
    assert section["contenu"] == f"Texte de {code}."
    assert section["origine"] == "PROPOSEE"


async def test_une_section_ecrite_a_la_main_n_est_jamais_remplacee(client, auth):
    async with SessionLocal() as db:
        ids = await monter(db)
    r = await rapport(client, auth, ids)
    lot = await lot_rapport(client, auth, r["id"])
    code = lot["taches"][0]["code"]
    sections = [
        {
            "code": s["code"], "titre": s["titre"],
            "contenu": "Écrit à la main." if s["code"] == code else s["contenu"],
        }
        for s in r["sections"]
    ]
    enregistre = await client.put(f"{API}/rapports/{r['id']}", json={"sections": sections}, headers=auth)
    assert enregistre.status_code == 200, enregistre.text

    reponse = await client.post(
        f"{API}/rapports/{r['id']}/redaction-externe", files=fichier(retour(lot)), headers=auth
    )
    assert reponse.json()["gardees"] == 1

    corps = (await client.get(f"{API}/rapports/{r['id']}", headers=auth)).json()
    assert next(s for s in corps["sections"] if s["code"] == code)["contenu"] == "Écrit à la main."
    # Elle ne repart pas non plus dans le lot suivant.
    assert code not in [t["code"] for t in (await lot_rapport(client, auth, r["id"]))["taches"]]


async def test_une_section_calculee_ne_se_remplace_pas(client, auth):
    async with SessionLocal() as db:
        ids = await monter(db)
    r = await rapport(client, auth, ids)
    lot = await lot_rapport(client, auth, r["id"])
    redigees = {t["code"] for t in lot["taches"]}
    calculee = next(s for s in r["sections"] if s["code"] not in redigees)

    document = retour(lot)
    document["sections"].append({"code": calculee["code"], "texte": "Faux tableau."})
    reponse = await client.post(
        f"{API}/rapports/{r['id']}/redaction-externe", files=fichier(document), headers=auth
    )
    assert reponse.json()["inconnues"] == 1

    corps = (await client.get(f"{API}/rapports/{r['id']}", headers=auth)).json()
    assert "Faux tableau." not in json.dumps(corps, ensure_ascii=False)


async def test_un_rapport_valide_refuse_l_import(client, auth):
    async with SessionLocal() as db:
        ids = await monter(db)
    r = await rapport(client, auth, ids)
    lot = await lot_rapport(client, auth, r["id"])
    from app.models.enums import StatutRapport
    from app.models.collaboration import Rapport

    async with SessionLocal() as db:
        (await db.get(Rapport, r["id"])).statut = StatutRapport.VALIDE
        await db.commit()

    reponse = await client.post(
        f"{API}/rapports/{r['id']}/redaction-externe", files=fichier(retour(lot)), headers=auth
    )
    assert reponse.status_code == 409


async def test_le_retour_d_un_autre_rapport_est_refuse(client, auth):
    async with SessionLocal() as db:
        ids = await monter(db)
    un = await rapport(client, auth, ids)
    autre = await rapport(client, auth, ids)
    lot = await lot_rapport(client, auth, un["id"])

    reponse = await client.post(
        f"{API}/rapports/{autre['id']}/redaction-externe", files=fichier(retour(lot)), headers=auth
    )
    assert reponse.status_code == 422
    assert "autre document" in reponse.json()["detail"]


@pytest.mark.parametrize("contenu", [b"pas du json", b"[]", b'{"format": "autre"}'])
async def test_un_fichier_invalide_est_refuse_proprement(client, auth, contenu):
    async with SessionLocal() as db:
        ids = await monter(db)
    r = await rapport(client, auth, ids)
    reponse = await client.post(
        f"{API}/rapports/{r['id']}/redaction-externe",
        files={"fichier": ("result.json", contenu, "application/json")},
        headers=auth,
    )
    assert reponse.status_code == 422


# --- avis --------------------------------------------------------------------


async def lot_avis(client, auth, ids) -> dict:
    reponse = await client.get(
        f"{API}/postes/{ids['poste']}/avis/redaction-externe",
        params={"avis_id": ids["avis"]},
        headers=auth,
    )
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


async def importer_avis(client, auth, ids, document):
    return await client.post(
        f"{API}/postes/{ids['poste']}/avis/redaction-externe",
        data={"avis_id": ids["avis"]},
        files=fichier(document),
        headers=auth,
    )


async def test_l_avis_s_assemble_et_garde_ses_rubriques_opposables(client, auth):
    async with SessionLocal() as db:
        ids = await monter(db)
    lot = await lot_avis(client, auth, ids)
    assert len(lot["taches"]) >= 2

    reponse = await importer_avis(client, auth, ids, retour(lot))
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()

    assert corps["propose"] is True
    assert f"Texte de {lot['taches'][0]['code']}." in corps["texte"]
    assert "DIRECTEUR LOGISTIQUE" in corps["texte"]
    assert "31/12/2026" in corps["texte"]
    assert "Dossier de candidature" in corps["texte"]


async def test_une_date_dans_la_prose_recue_ne_remplace_pas_celle_du_code(client, auth):
    """Le modèle entame une rubrique réservée : elle est coupée, le code écrit la sienne."""
    async with SessionLocal() as db:
        ids = await monter(db)
    lot = await lot_avis(client, auth, ids)
    code = lot["taches"][0]["code"]

    reponse = await importer_avis(
        client, auth, ids,
        retour(lot, {code: "Bon texte.\n\nModalités de dépôt\nDate limite : 01/01/2020."}),
    )
    texte = reponse.json()["texte"]
    assert "01/01/2020" not in texte
    assert "31/12/2026" in texte


async def test_un_avis_a_qui_il_manque_une_section_est_refuse(client, auth):
    async with SessionLocal() as db:
        ids = await monter(db)
    lot = await lot_avis(client, auth, ids)
    document = retour(lot)
    document["sections"] = document["sections"][:-1]

    reponse = await importer_avis(client, auth, ids, document)
    assert reponse.status_code == 422
    assert "Il manque" in reponse.json()["detail"]


async def test_un_poste_modifie_depuis_l_export_est_refuse(client, auth):
    async with SessionLocal() as db:
        ids = await monter(db)
    lot = await lot_avis(client, auth, ids)
    async with SessionLocal() as db:
        (await db.get(Poste, ids["poste"])).niveau_min = 5
        await db.commit()

    reponse = await importer_avis(client, auth, ids, retour(lot))
    assert reponse.status_code == 422
    assert "a changé" in reponse.json()["detail"]


async def test_rien_n_est_enregistre_sur_l_avis_sans_relecture(client, auth):
    async with SessionLocal() as db:
        ids = await monter(db)
    lot = await lot_avis(client, auth, ids)
    await importer_avis(client, auth, ids, retour(lot))

    async with SessionLocal() as db:
        assert (await db.get(Avis, ids["avis"])).texte in (None, "")


def test_le_script_traite_aussi_un_lot_de_redaction(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path

    chemin = Path(__file__).resolve().parents[1] / "tools" / "lecteur_local.py"
    spec = importlib.util.spec_from_file_location("lecteur_local", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    entree = tmp_path / "redaction.json"
    entree.write_text(
        json.dumps(
            {
                "format": redaction_externe.FORMAT,
                "document": {"type": "avis", "id": "p", "empreinte": "e"},
                "taches": [{"code": "section_1", "titre": "Mission", "systeme": "s", "demande": "d"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "rediger_une_section", lambda *a: "Un paragraphe.")
    sortie = tmp_path / "result.json"
    module.traiter_fichier(str(entree), str(sortie), "http://ollama", "qwen3:8b")

    rendu = json.loads(sortie.read_text(encoding="utf-8"))
    assert rendu["document"]["empreinte"] == "e"
    assert redaction_externe.Retour.model_validate(rendu).sections[0].texte == "Un paragraphe."
