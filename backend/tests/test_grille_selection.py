"""La grille de sélection : dérivée du barème, et ce que l'assistance y propose."""

from __future__ import annotations

import io

import docx

from app.llm.base import LLMProvider
from app.services import grille_selection
from tests.test_api_recrutement import API, monter_poste


class Repondeur(LLMProvider):
    def __init__(self, reponse):
        self.reponse = reponse
        self.consignes: list[str] = []

    async def analyze_cv(self, cv, fiche):  # pragma: no cover
        raise NotImplementedError

    async def structure_fiche(self, raw_text, language="fr"):  # pragma: no cover
        return []

    async def repondre_json(self, consigne, contexte, systeme=""):
        self.consignes.append(consigne)
        if isinstance(self.reponse, Exception):
            raise self.reponse
        return self.reponse


async def test_la_grille_detaille_le_bareme_en_vigueur(client, auth):
    poste_id = await monter_poste(client, auth)
    reponse = await client.get(f"{API}/postes/{poste_id}/grille-selection", headers=auth)
    assert reponse.status_code == 200, reponse.text
    grille = reponse.json()
    assert grille["total"] == 30
    assert grille["personnalise"] is False
    rubriques = {l["numero"]: l for l in grille["lignes"]}
    assert rubriques["1"]["points"] == 3
    assert rubriques["2"]["points"] == 7
    assert rubriques["3.1"]["points"] == 5
    assert rubriques["3.2"]["points"] == 15
    diplome = rubriques["2.1"]
    assert diplome["eliminatoire"] is True
    assert "BAC+4" in diplome["libelle"] and "gestion hôtelière" in diplome["libelle"]
    assert "Au moins 10 année(s)" in rubriques["3.1.1"]["libelle"]
    assert rubriques["3.1.1"]["eliminatoire"] is True


async def test_la_grille_se_telecharge_en_word(client, auth):
    poste_id = await monter_poste(client, auth)
    reponse = await client.get(f"{API}/postes/{poste_id}/grille-selection.docx", headers=auth)
    assert reponse.status_code == 200
    document = docx.Document(io.BytesIO(reponse.content))
    texte = "\n".join(c.text for t in document.tables for r in t.rows for c in r.cells)
    assert "Formation académique (FA)" in texte
    assert "Critère éliminatoire" in texte
    assert "TOTAL" in texte


async def test_le_bareme_propose_reste_dans_les_bornes_et_ne_s_enregistre_pas(
    client, auth, monkeypatch
):
    poste_id = await monter_poste(client, auth)
    faux = Repondeur(
        {
            # Des valeurs hors bornes : le serveur les ramène dedans.
            "formation": {"points_niveau_requis": 4, "points_par_certification": 9,
                          "certifications_max": 2, "points_formation_complementaire": 1},
            "experience_generale": {"points_au_seuil": 3, "points_par_annee_supplementaire": 1,
                                    "annees_supplementaires_max": 2},
            "experience_specifique": {"points_au_seuil": 50},
            "justification": "Les certifications comptent pour ce poste.",
        }
    )
    monkeypatch.setattr(grille_selection, "get_provider", lambda: faux)
    reponse = await client.post(f"{API}/postes/{poste_id}/bareme/suggestion", headers=auth)
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["bareme"]["formation"]["points_max"] == 7
    assert corps["bareme"]["formation"]["points_par_certification"] == 3
    assert corps["bareme"]["experience_specifique"]["points_au_seuil"] == 15
    assert corps["justification"]
    assert "7 points" in faux.consignes[0]

    # Rien n'est enregistré tant qu'on n'applique pas.
    grille = (await client.get(f"{API}/postes/{poste_id}/grille-selection", headers=auth)).json()
    assert grille["personnalise"] is False

    # Appliquer : le barème proposé devient celui du poste.
    applique = await client.put(
        f"{API}/postes/{poste_id}/bareme", json={"bareme": corps["bareme"]}, headers=auth
    )
    assert applique.status_code == 200, applique.text
    grille = (await client.get(f"{API}/postes/{poste_id}/grille-selection", headers=auth)).json()
    assert grille["personnalise"] is True
    assert any("par certification" in l["libelle"] for l in grille["lignes"])

    # Et l'on revient au barème du cabinet d'un clic.
    retour = await client.put(
        f"{API}/postes/{poste_id}/bareme", json={"bareme": grille["bareme_cabinet"]}, headers=auth
    )
    assert retour.status_code == 200


async def test_l_apercu_refuse_un_bareme_qui_ne_totalise_pas(client, auth):
    poste_id = await monter_poste(client, auth)
    grille = (await client.get(f"{API}/postes/{poste_id}/grille-selection", headers=auth)).json()
    bareme = grille["bareme"]
    bareme["formation"]["points_max"] = 9
    reponse = await client.post(
        f"{API}/postes/{poste_id}/grille-selection/apercu", json={"bareme": bareme}, headers=auth
    )
    assert reponse.status_code == 422


async def test_une_assistance_indisponible_le_dit(client, auth, monkeypatch):
    poste_id = await monter_poste(client, auth)
    monkeypatch.setattr(grille_selection, "get_provider", lambda: Repondeur(RuntimeError("quota")))
    reponse = await client.post(f"{API}/postes/{poste_id}/bareme/suggestion", headers=auth)
    assert reponse.status_code == 503
    reponse = await client.post(
        f"{API}/postes/{poste_id}/suggestions/formation-complementaire", headers=auth
    )
    assert reponse.status_code == 503


async def test_la_formation_complementaire_est_proposee_sans_prefixe(client, auth, monkeypatch):
    poste_id = await monter_poste(client, auth)
    faux = Repondeur(
        {
            "propositions": [
                "Formation complémentaire en revenue management.",
                "hygiène et sécurité alimentaire (HACCP)",
                "hygiène et sécurité alimentaire (HACCP)",
            ],
            "justification": "La fiche insiste sur la rentabilité.",
        }
    )
    monkeypatch.setattr(grille_selection, "get_provider", lambda: faux)
    reponse = await client.post(
        f"{API}/postes/{poste_id}/suggestions/formation-complementaire", headers=auth
    )
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["propositions"] == [
        "revenue management",
        "hygiène et sécurité alimentaire (HACCP)",
    ]


# --- l'objet du courriel : l'intitulé du poste --------------------------------


async def test_l_avis_demande_l_intitule_en_objet_et_non_la_reference():
    from types import SimpleNamespace

    from app.services import redaction_avis
    from tests.test_fiche_de_poste import _reglages

    poste = SimpleNamespace(intitule="Assistant(e) Administratif(ve)")
    avis = SimpleNamespace(cle_publique="abc", reference="AVIS-2026-014")
    lignes = redaction_avis.modalites(
        avis, _reglages(imap_user="recrutement@kapiconsult.tg"), poste
    )
    courriel = lignes[-1]
    assert "« Candidature au poste de Assistant(e) Administratif(ve) »" in courriel
    assert "AVIS-2026-014" not in courriel


async def test_la_releve_rattache_par_l_intitule_et_toujours_par_la_reference(client, auth):
    from datetime import datetime

    from app.db import SessionLocal
    from app.services.courriel import MessageEntrant, poste_du_message

    poste_id = await monter_poste(client, auth, intitule="Chargé d'Études Économiques")
    avis = (await client.get(f"{API}/postes/{poste_id}/avis", headers=auth)).json()[0]
    await client.patch(f"{API}/avis/{avis['id']}", json={"reference": "CEE-01"}, headers=auth)
    publie = await client.post(f"{API}/avis/{avis['id']}/publier", headers=auth)
    assert publie.status_code == 200, publie.text

    def message(sujet: str) -> MessageEntrant:
        return MessageEntrant(
            message_id="x", expediteur="a@b.tg", nom_expediteur="", sujet=sujet,
            recu_le=datetime(2026, 9, 1), corps="", pieces=[],
        )

    async with SessionLocal() as db:
        # Casse, accents et ponctuation ne comptent pas.
        trouve = await poste_du_message(db, message("CANDIDATURE AU POSTE DE CHARGE D'ETUDES ECONOMIQUES"))
        assert trouve is not None and trouve.id == poste_id
        # Les avis déjà diffusés demandaient la référence : elle marche toujours.
        trouve = await poste_du_message(db, message("[CEE-01] candidature"))
        assert trouve is not None and trouve.id == poste_id
        # Rien de reconnaissable : pas de rattachement au hasard.
        assert await poste_du_message(db, message("Candidature spontanée")) is None


# --- lien court -----------------------------------------------------------------


async def test_le_lien_court_et_l_ancien_lien_menent_au_meme_avis(client, auth):
    poste_id = await monter_poste(client, auth)
    avis = (await client.get(f"{API}/postes/{poste_id}/avis", headers=auth)).json()[0]
    assert (await client.post(f"{API}/avis/{avis['id']}/publier", headers=auth)).status_code == 200
    code = avis["code_court"]
    assert code and len(code) == 8 and code.isupper()

    court = await client.get(f"{API}/public/avis/{code}")
    ancien = await client.get(f"{API}/public/avis/{avis['cle_publique']}")
    minuscules = await client.get(f"{API}/public/avis/{code.lower()}")
    assert court.status_code == ancien.status_code == minuscules.status_code == 200
    assert court.json()["intitule"] == ancien.json()["intitule"]
    assert (await client.get(f"{API}/public/avis/ZZZZZZZZ")).status_code == 404
