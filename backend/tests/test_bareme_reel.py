"""Le barème du cabinet, de bout en bout.

Le domaine est déjà couvert par test_domaine_bareme.py. Ce module vérifie ce
que le domaine seul ne peut pas garantir : que la grille servie par l'API porte
bien le rang et la proposition, que l'appréciation humaine se saisit et modifie
la note, et que le quota du poste distingue les proposés des préqualifiés.
"""

from __future__ import annotations

import pytest

from tests.test_api_recrutement import dossier, monter_poste

pytestmark = pytest.mark.anyio

API = "/api/v1"


async def deposer(client, auth, poste_id: str, **overrides) -> dict:
    reponse = await client.post(
        f"{API}/postes/{poste_id}/candidatures", json=dossier(**overrides), headers=auth
    )
    assert reponse.status_code == 201, reponse.text
    return reponse.json()


# --- la note reflète la répartition réelle -----------------------------------


async def test_la_notation_porte_les_quatre_criteres_du_cabinet(client, auth):
    poste_id = await monter_poste(client, auth)
    corps = await deposer(client, auth, poste_id)

    lignes = {l["code"]: l for l in corps["notation"]["lignes"]}
    assert set(lignes) == {
        "CONSISTANCE",
        "FORMATION",
        "EXPERIENCE_GENERALE",
        "EXPERIENCE_SPECIFIQUE",
    }
    assert lignes["CONSISTANCE"]["points_max"] == 3.0
    assert lignes["FORMATION"]["points_max"] == 7.0
    assert lignes["EXPERIENCE_GENERALE"]["points_max"] == 5.0
    assert lignes["EXPERIENCE_SPECIFIQUE"]["points_max"] == 15.0
    assert corps["notation"]["total_max"] == 30.0


async def test_la_grille_rappelle_que_la_preselection_pese_trente_pour_cent(client, auth):
    """Une note sur 30 lue seule se prendrait pour un résultat final."""
    poste_id = await monter_poste(client, auth)
    await deposer(client, auth, poste_id)

    grille = (await client.get(f"{API}/postes/{poste_id}/grille", headers=auth)).json()
    assert grille["poids_preselection"] == 30.0

    ligne = grille["preselectionnes"][0]
    assert ligne["note_sur_cent"] is not None
    assert ligne["note_sur_cent"] <= 30.0


# --- appréciation humaine de la consistance ----------------------------------


async def test_un_dossier_non_lu_attend_son_appreciation(client, auth):
    poste_id = await monter_poste(client, auth)
    await deposer(client, auth, poste_id)

    grille = (await client.get(f"{API}/postes/{poste_id}/grille", headers=auth)).json()
    assert grille["preselectionnes"][0]["appreciation_attendue"] is True


async def test_l_appreciation_se_saisit_et_change_la_note(client, auth):
    poste_id = await monter_poste(client, auth)
    corps = await deposer(client, auth, poste_id)
    avant = corps["notation"]["total"]

    reponse = await client.patch(
        f"{API}/candidatures/{corps['id']}/appreciation",
        json={"note": 1, "motif": "Lettre argumentée, expression soignée."},
        headers=auth,
    )
    assert reponse.status_code == 200, reponse.text
    apres = reponse.json()

    assert apres["appreciation_consistance"] == 1.0
    assert apres["notation"]["total"] == avant + 1.0

    grille = (await client.get(f"{API}/postes/{poste_id}/grille", headers=auth)).json()
    assert grille["preselectionnes"][0]["appreciation_attendue"] is False


async def test_une_appreciation_sans_motif_est_refusee(client, auth):
    """Un point attribué sans raison écrite ne serait pas opposable."""
    poste_id = await monter_poste(client, auth)
    corps = await deposer(client, auth, poste_id)

    refus = await client.patch(
        f"{API}/candidatures/{corps['id']}/appreciation",
        json={"note": 1, "motif": ""},
        headers=auth,
    )
    assert refus.status_code == 422


async def test_une_appreciation_au_dela_du_bareme_est_refusee(client, auth):
    poste_id = await monter_poste(client, auth)
    corps = await deposer(client, auth, poste_id)

    refus = await client.patch(
        f"{API}/candidatures/{corps['id']}/appreciation",
        json={"note": 3, "motif": "Excellent dossier."},
        headers=auth,
    )
    assert refus.status_code == 422
    assert "au plus" in refus.json()["detail"]


async def test_l_appreciation_est_journalisee(client, auth):
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import AuditLog

    poste_id = await monter_poste(client, auth)
    corps = await deposer(client, auth, poste_id)
    await client.patch(
        f"{API}/candidatures/{corps['id']}/appreciation",
        json={"note": 0.5, "motif": "Motivation générique."},
        headers=auth,
    )

    async with SessionLocal() as db:
        actions = [a.action for a in (await db.execute(select(AuditLog))).scalars()]
    assert "candidature.appreciation" in actions


async def test_l_appreciation_survit_a_une_reevaluation(client, auth):
    """La notation est effacée et recréée à chaque recalcul ; la lecture, non."""
    poste_id = await monter_poste(client, auth)
    corps = await deposer(client, auth, poste_id)
    await client.patch(
        f"{API}/candidatures/{corps['id']}/appreciation",
        json={"note": 1, "motif": "Dossier soigné."},
        headers=auth,
    )

    reponse = await client.post(f"{API}/postes/{poste_id}/evaluer", headers=auth)
    assert reponse.status_code == 200, reponse.text

    relu = (await client.get(f"{API}/candidatures/{corps['id']}", headers=auth)).json()
    assert relu["appreciation_consistance"] == 1.0
    assert relu["notation"]["lignes"]


# --- classement, proposition, quota ------------------------------------------


async def test_la_grille_porte_le_rang(client, auth):
    poste_id = await monter_poste(client, auth)
    await deposer(client, auth, poste_id, nom="Kodjo", prenom="Amina")
    await deposer(
        client,
        auth,
        poste_id,
        nom="Mensah",
        prenom="Kofi",
        experiences=[
            {
                "poste": "Directeur",
                "employeur": "Hôtel Sarakawa",
                "debut": "1998-01-01",
                "fin": "2026-01-01",
                "domaines": ["gestion hôtelière"],
                "pays": "Togo",
            }
        ],
    )

    grille = (await client.get(f"{API}/postes/{poste_id}/grille", headers=auth)).json()
    rangs = [l["rang"] for l in grille["preselectionnes"]]
    assert rangs == [1, 2]
    # Le plus expérimenté passe devant : quinze points d'expérience spécifique.
    assert grille["preselectionnes"][0]["nom"] == "Mensah"


async def test_le_quota_du_poste_distingue_proposes_et_prequalifies(client, auth):
    """« Les cinq premiers candidats » : le reste reste recevable, non proposé."""
    poste_id = await monter_poste(client, auth)
    await client.patch(
        f"{API}/postes/{poste_id}", json={"nombre_a_retenir": 1}, headers=auth
    )

    await deposer(client, auth, poste_id, nom="Kodjo", prenom="Amina")
    await deposer(
        client,
        auth,
        poste_id,
        nom="Mensah",
        prenom="Kofi",
        experiences=[
            {
                "poste": "Directeur",
                "employeur": "Hôtel Sarakawa",
                "debut": "1998-01-01",
                "fin": "2026-01-01",
                "domaines": ["gestion hôtelière"],
                "pays": "Togo",
            }
        ],
    )

    grille = (await client.get(f"{API}/postes/{poste_id}/grille", headers=auth)).json()
    assert grille["nombre_a_proposer"] == 1
    assert grille["nombre_preselectionnes"] == 2
    assert grille["nombre_proposes"] == 1

    proposes = [l["nom"] for l in grille["preselectionnes"] if l["propose"]]
    prequalifies = [l["nom"] for l in grille["preselectionnes"] if not l["propose"]]
    assert proposes == ["Mensah"]
    # Le second n'est pas écarté : c'est lui qu'on rappelle en cas de désistement.
    assert prequalifies == ["Kodjo"]


async def test_sans_quota_tous_les_recevables_sont_proposes(client, auth):
    poste_id = await monter_poste(client, auth)
    await deposer(client, auth, poste_id)

    grille = (await client.get(f"{API}/postes/{poste_id}/grille", headers=auth)).json()
    assert grille["nombre_a_proposer"] is None
    assert all(l["propose"] for l in grille["preselectionnes"])
