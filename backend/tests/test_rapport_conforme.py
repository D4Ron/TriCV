"""Le rapport reproduit les tableaux du document que le cabinet remet.

Les quatre tableaux du « Rapport des entretiens » réel : effectifs par poste,
grilles de notation employées, candidatures préqualifiées (nom, âge, diplôme,
pays, note sur cent, rang, téléphone, e-mail) et classement final.

Ce qui manquait : les **grilles** n'y figuraient pas. Le rapport annonçait des
notes sans dire sur quoi elles portaient, alors que ce sont précisément les
grilles que le client valide avant le lancement — un rapport qui y renvoie
oblige à ressortir un autre document pour se relire.
"""

from __future__ import annotations

import pytest

from app.db import SessionLocal
from app.services import rapports

pytestmark = pytest.mark.anyio

API = "/api/v1"


async def monter(client, auth) -> tuple[str, str]:
    client_id = (
        await client.post(f"{API}/clients", json={"nom": "WAPP"}, headers=auth)
    ).json()["id"]
    mandat_id = (
        await client.post(
            f"{API}/mandats",
            json={"client_id": client_id, "intitule": "Cadres 2026"},
            headers=auth,
        )
    ).json()["id"]
    poste_id = (
        await client.post(
            f"{API}/mandats/{mandat_id}/postes",
            json={
                "intitule": "Directeur Administratif et Financier",
                "niveau_min": 4,
                "domaines_acceptes": ["finance"],
                "annees_experience_min": 5,
                "annees_experience_specifique_min": 3,
                "domaines_experience": ["finance"],
                "pieces_requises": ["CV"],
            },
            headers=auth,
        )
    ).json()["id"]
    await client.post(
        f"{API}/postes/{poste_id}/avis",
        json={"type_avis": "NATIONAL", "date_cloture": "2026-07-31"},
        headers=auth,
    )
    return mandat_id, poste_id


async def candidat(client, auth, poste_id, **champs):
    corps = {
        "candidat": {
            "nom": champs.get("nom", "Sankhare"),
            "prenom": champs.get("prenom", "Ousseynou"),
            "email": champs.get("email", "o.sankhare@example.tg"),
            "telephone": champs.get("telephone", "+228 90 11 22 33"),
            "date_naissance": "1981-05-04",
            "nationalites": [champs.get("pays", "Sénégalaise")],
            "diplomes": [
                {
                    "intitule": "Master en ingénierie financière",
                    "niveau": 5,
                    "domaine": "finance",
                    "annee": 2008,
                }
            ],
            "experiences": [
                {
                    "poste": "DAF",
                    "employeur": "Groupe",
                    "debut": "2010-01-01",
                    "fin": "2026-01-01",
                    "domaines": ["finance"],
                }
            ],
        },
        "pieces_fournies": ["CV"],
        # Avant la clôture : sans quoi HORS_DELAI, motif factuel, écarterait le
        # dossier et le tableau des préqualifiés resterait vide.
        "recue_le": "2026-07-15T09:00:00",
    }
    reponse = await client.post(
        f"{API}/postes/{poste_id}/candidatures", json=corps, headers=auth
    )
    assert reponse.status_code == 201, reponse.text
    return reponse.json()


async def sections(client, auth, mandat_id, type_rapport="FINAL") -> dict:
    """Le texte de chaque section, tableaux compris.

    Sans assistance, la prose est vide et `contenu` porte le texte aligné des
    tableaux ; avec assistance il porterait la prose, et `tableaux_texte` le
    rendu des tables. On concatène les deux pour que ces contrôles portent sur
    ce que la section dit, quelle que soit la source.
    """
    rapport = (
        await client.post(
            f"{API}/mandats/{mandat_id}/rapports",
            json={"avec_assistance": False, "type_rapport": type_rapport},
            headers=auth,
        )
    ).json()
    return {
        s["code"]: "\n".join(
            partie
            for partie in (s["contenu"], _texte_des_tableaux(s))
            if partie
        )
        for s in rapport["sections"]
    }


def _texte_des_tableaux(section: dict) -> str:
    """Les en-têtes et les cellules d'une section, en une chaîne cherchable.

    Les tableaux ne sont plus du texte : ils ont une structure. Ces contrôles
    portent sur ce que la section *dit*, pas sur sa mise en forme — on remet
    donc les libellés à plat.
    """
    morceaux: list[str] = []
    for tableau in section.get("tableaux") or ():
        morceaux.append(str(tableau.get("titre") or ""))
        morceaux += [str(c.get("libelle") or "") for c in tableau.get("colonnes") or ()]
        for ligne in tableau.get("lignes") or ():
            morceaux += [str(c) for c in ligne.get("cellules") or ()]
    return "\n".join(m for m in morceaux if m)


async def test_le_rapport_reproduit_les_grilles_employees(client, auth):
    """Chaque grille dans la section qui l'annonce, comme le document remis."""
    mandat_id, poste_id = await monter(client, auth)
    await candidat(client, auth, poste_id)

    tout = await sections(client, auth, mandat_id)

    # La grille de présélection, sous « Méthodologie › Présélection ».
    presel = tout["METHODE_PRESELECTION"]
    for attendu in (
        "Consistance du dossier",
        "Formation académique",
        "Expérience générale",
        "Expérience spécifique",
        "Total",
    ):
        assert attendu in presel, f"{attendu!r} absent de la grille de présélection"

    # La grille d'entretien, sous « Adoption du guide d'interview ».
    entretien = tout["GUIDE_ENTRETIEN"]
    assert "Critères d'appréciation" in entretien
    assert "TOTAL" in entretien


async def test_le_tableau_des_prequalifies_porte_les_colonnes_du_document(client, auth):
    mandat_id, poste_id = await monter(client, auth)
    await candidat(client, auth, poste_id)

    tableau = (await sections(client, auth, mandat_id))["LISTE_PRESELECTIONNES"]

    for colonne in (
        "Nom & Prénoms",
        "Age",
        "Diplôme",
        "Pays",
        "Présélection Note/100",
        "Rang",
        "Téléphone",
        "E-mail",
    ):
        assert colonne in tableau, f"colonne {colonne!r} absente"

    assert "SANKHARE" in tableau
    assert "o.sankhare@example.tg" in tableau, "l'adresse est une colonne du document remis"
    assert "+228 90 11 22 33" in tableau
    assert "Sénégalaise" in tableau
    assert "1er" in tableau, "le rang s'écrit en ordinal, comme dans le document"


async def test_la_note_sur_cent_n_est_pas_la_contribution_ponderee(client, auth):
    """Un dossier à 27 sur 30 vaut 90 dans la colonne et 27 dans le total.

    Confondre les deux ferait lire au client une note de présélection
    plafonnée à 30 là où son document en annonce une sur cent.
    """
    mandat_id, poste_id = await monter(client, auth)
    await candidat(client, auth, poste_id)

    async with SessionLocal() as db:
        chiffres = await rapports.rassembler(db, mandat_id, None)

    ligne = chiffres["postes"][0]["classement"][0]
    note = float(ligne["note_preselection"])
    maximum = float(ligne["note_preselection_max"])
    assert ligne["preselection_sur_100"] == pytest.approx(note / maximum * 100, abs=0.01)
    assert ligne["rang"] == 1
    assert ligne["rang_libelle"] == "1er"


async def test_le_tableau_des_effectifs_compte_les_dossiers(client, auth):
    mandat_id, poste_id = await monter(client, auth)
    await candidat(client, auth, poste_id)
    await candidat(
        client, auth, poste_id, nom="Fallah", prenom="Aruna", email="a.fallah@example.tg"
    )

    # Les effectifs vivent dans « Résultats de la présélection » : dans le
    # document remis, ce tableau n'a pas d'intertitre à lui.
    synthese = (await sections(client, auth, mandat_id))["RESULTATS_PRESELECTION"]

    assert "Nombre de dossiers analysés" in synthese
    assert "Effectif Préqualifié" in synthese
    assert "Nombre de candidats éliminés" in synthese
    assert "Directeur Administratif et Financier" in synthese


async def test_un_rapport_de_preselection_porte_la_grille_et_les_effectifs(client, auth):
    mandat_id, poste_id = await monter(client, auth)
    await candidat(client, auth, poste_id)

    codes = list((await sections(client, auth, mandat_id, "PRESELECTION")).keys())
    assert codes == [
        "INTRODUCTION",
        "DEMARCHE",
        "OBJECTIFS",
        "METHODOLOGIE",
        "METHODE_PRESELECTION",
        "CRITERES_ELIMINATOIRES",
        "RESULTATS_PRESELECTION",
        "LISTE_PRESELECTIONNES",
    ]
