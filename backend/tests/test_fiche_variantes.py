"""Fiches de poste aux formes variées, et pièces demandées une seule fois.

Tout est inventé. Chaque fiche reprend une forme rencontrée : description de
poste en anglais, profil découpé en « Formation » et « Expérience », durée
écrite en lettres ou après le mot « expérience », plusieurs niveaux cités,
pièces hors du référentiel.
"""

from __future__ import annotations

import pytest

from app.domain import pieces
from app.services import fiche_poste

pytestmark = pytest.mark.anyio

API = "/api/v1"


def test_une_description_de_poste_en_anglais():
    lu = fiche_poste.lire_trame(
        "JOB DESCRIPTION\n"
        "Job title: Finance Officer\n"
        "Location: Lomé, Togo\n"
        "Reports to: Finance Manager\n"
        "PURPOSE OF THE ROLE\n"
        "Keeps the books of the regional office.\n"
        "KEY RESPONSIBILITIES\n"
        "- Prepare monthly financial statements\n"
        "- Reconcile bank accounts\n"
        "REQUIREMENTS\n"
        "- Bachelor's degree in Accounting\n"
        "- At least five years of experience in accounting\n"
        "- Fluent in English and French\n"
    )
    assert lu["intitule"] == "Finance Officer"
    assert lu["localisation"] == "Lomé, Togo"
    assert lu["rattachement"] == "Finance Manager"
    assert lu["responsabilites"] == ["Prepare monthly financial statements", "Reconcile bank accounts"]
    assert lu["niveau_min"] == 3
    assert lu["annees_experience_min"] == 5
    assert lu["langues_requises"] == ["français", "anglais"]


def test_un_profil_decoupe_en_formation_et_experience():
    lu = fiche_poste.lire_trame(
        "Poste : Chargé de la logistique\n"
        "PRINCIPALES ACTIVITÉS\n"
        "- Planifier les livraisons\n"
        "FORMATION\n"
        "Licence minimum en logistique, un Master serait un atout\n"
        "EXPÉRIENCE PROFESSIONNELLE\n"
        "Avoir une expérience professionnelle d'au moins cinq (05) ans\n"
    )
    assert lu["intitule"] == "Chargé de la logistique"
    assert lu["responsabilites"] == ["Planifier les livraisons"]
    # Le plancher, pas le souhait.
    assert lu["niveau_min"] == 3
    assert lu["annees_experience_min"] == 5


def test_une_duree_en_lettres_sans_parenthese():
    lu = fiche_poste.lire_trame("Profil requis\nSix ans d'expérience dans un poste similaire\n")
    assert lu["annees_experience_min"] == 6


async def test_plusieurs_niveaux_cites_sont_signales():
    proposition = await fiche_poste.proposer(
        "Intitulé du poste : Contrôleur de gestion\nProfil requis\nBAC+3 minimum, BAC+5 souhaité\n",
        avec_assistance=False,
    )
    assert proposition.valeurs["niveau_min"] == 3
    assert "plusieurs niveaux" in proposition.avertissement


async def test_les_pieces_de_la_fiche_sont_rangees_et_les_inconnues_dites():
    proposition = await fiche_poste.proposer(
        "Intitulé du poste : Comptable\n"
        "PIÈCES À FOURNIR\n"
        "- Un CV détaillé\n"
        "- Copie de la CNI ou du passeport\n"
        "- Copie légalisée de la CNI\n"
        "- Extrait de casier judiciaire de moins de trois mois\n"
        "- Extrait d'acte de naissance\n",
        avec_assistance=False,
    )
    v = proposition.valeurs
    assert v["pieces_requises"] == ["CV", "CASIER_JUDICIAIRE"]
    assert v["groupes_pieces"][0]["codes"] == ["PIECE_IDENTITE", "PASSEPORT"]
    assert "acte de naissance" in proposition.avertissement


# --- le rangement des pièces --------------------------------------------------


def test_un_groupe_prend_les_pieces_qu_il_contient():
    """La CNI exigée seule *et* « CNI ou passeport » : le choix l'emporte."""
    rangees = pieces.normaliser(
        ["CV", "PIECE_IDENTITE", "COPIE_DIPLOMES"],
        ["ATTESTATIONS_TRAVAIL", "LETTRE_RECOMMANDATION"],
        [
            {"codes": ["PIECE_IDENTITE", "PASSEPORT"], "mode": "AU_MOINS_UNE", "libelle": "Pièce d'identité"},
            {"codes": ["COPIE_DIPLOMES", "ATTESTATIONS_TRAVAIL"], "mode": "TOUTES", "libelle": "Diplôme et attestation"},
        ],
    )
    assert rangees.requises == ["CV"]
    assert rangees.facultatives == ["LETTRE_RECOMMANDATION"]
    assert [g["codes"] for g in rangees.groupes] == [
        ["PIECE_IDENTITE", "PASSEPORT"],
        ["COPIE_DIPLOMES", "ATTESTATIONS_TRAVAIL"],
    ]
    assert len(rangees.remarques) == 3


def test_exigee_l_emporte_sur_facultative_et_autre_rejoint_les_documents_libres():
    rangees = pieces.normaliser(["CV", "CV"], ["CV", "AUTRE"], [], libres_autorisees=False)
    assert rangees.requises == ["CV"]
    assert rangees.facultatives == []
    assert rangees.libres_autorisees is True


def test_un_choix_qui_n_offre_plus_de_choix_devient_une_exigence():
    rangees = pieces.normaliser(
        [],
        [],
        [
            {"codes": ["PIECE_IDENTITE", "PASSEPORT"], "mode": "AU_MOINS_UNE", "libelle": "A"},
            {"codes": ["PASSEPORT", "CERTIFICAT_NATIONALITE"], "mode": "AU_MOINS_UNE", "libelle": "B"},
        ],
    )
    assert rangees.requises == ["CERTIFICAT_NATIONALITE"]
    assert [g["libelle"] for g in rangees.groupes] == ["A"]


def test_rien_a_ranger_rien_a_dire():
    assert pieces.normaliser(["CV"], ["PHOTO"], [], True).remarques == []


async def test_la_fiche_enregistree_range_ses_pieces_et_le_dit(client, auth):
    from tests.test_doublons import monter_poste

    poste_id = await monter_poste(client, auth)
    reponse = await client.patch(
        f"{API}/postes/{poste_id}",
        json={
            "pieces_requises": ["CV", "PIECE_IDENTITE"],
            "groupes_pieces": [
                {"codes": ["PIECE_IDENTITE", "PASSEPORT"], "mode": "AU_MOINS_UNE", "libelle": "Pièce d'identité"}
            ],
        },
        headers=auth,
    )
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["pieces_requises"] == ["CV"]
    assert any("n'est plus exigée seule" in r for r in corps["remarques_pieces"])

    # L'avis ne publie pas sans CV demandé.
    await client.patch(f"{API}/postes/{poste_id}", json={"pieces_requises": []}, headers=auth)
    avis = (
        await client.post(f"{API}/postes/{poste_id}/avis", json={"date_cloture": "2099-01-31"}, headers=auth)
    ).json()
    refus = await client.post(f"{API}/avis/{avis['id']}/publier", headers=auth)
    assert refus.status_code == 422 and "CV" in refus.json()["detail"]
