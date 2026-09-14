"""Ce que le candidat déclare de lui-même, et ce que cela change.

Le formulaire public ne demandait que nom, prénom, adresse et téléphone. Tout
le reste vivait dans le CV, et n'entrait en base qu'après un dépouillement
assisté confirmé par un humain. Deux conséquences que ces tests figent :

- une **condition éliminatoire** ne s'appliquait qu'aux dossiers déjà lus. Un
  poste ouvert « aux 45 ans au plus » n'écartait personne au dépôt ;
- une **note** portait sur 3 points au lieu de 30, faute de diplôme et
  d'expérience en base.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from app.models import Provenance
from app.services import declaration

API = "/api/v1"
pytestmark = pytest.mark.anyio


# --- la lecture de ce qui arrive --------------------------------------------


def test_un_parcours_absent_n_est_pas_une_erreur():
    """Déclarer reste facultatif : un candidat pressé dépose son CV, et voilà."""
    for vide in (None, "", "   "):
        parcours = declaration.lire_parcours(vide)
        assert parcours.diplomes == [] and parcours.experiences == []


def test_un_parcours_complet_se_lit():
    brut = json.dumps(
        {
            "diplomes": [
                {
                    "intitule": "Master en sciences comptables",
                    "niveau": 5,
                    "domaine": "Comptabilité",
                    "etablissement": "Université de Lomé",
                    "annee": 2012,
                }
            ],
            "experiences": [
                {
                    "poste": "Chef comptable",
                    "employeur": "Groupe Atlantique",
                    "debut": "2015-01-01",
                    "fin": None,
                    "domaines": ["comptabilité générale"],
                    "pays": "Togo",
                }
            ],
            "langues": ["français", "anglais"],
            "certifications": ["IFRS"],
        }
    )
    parcours = declaration.lire_parcours(brut)

    assert parcours.diplomes[0].niveau == 5
    assert parcours.experiences[0].fin is None, "poste toujours occupé"
    assert parcours.langues == ["français", "anglais"]


def test_une_fin_anterieure_au_debut_est_refusee():
    brut = json.dumps(
        {
            "experiences": [
                {
                    "poste": "Comptable",
                    "employeur": "Cabinet",
                    "debut": "2015-01-01",
                    "fin": "2012-01-01",
                }
            ]
        }
    )
    with pytest.raises(declaration.DeclarationInvalide, match="précède"):
        declaration.lire_parcours(brut)


def test_une_experience_dans_le_futur_est_refusee():
    brut = json.dumps(
        {"experiences": [{"poste": "X", "employeur": "Y", "debut": "2099-01-01"}]}
    )
    with pytest.raises(declaration.DeclarationInvalide):
        declaration.lire_parcours(brut)


def test_le_refus_nomme_le_champ_en_francais():
    """« experiences.1.debut » ne dit rien à qui remplit un formulaire."""
    brut = json.dumps(
        {
            "experiences": [
                {"poste": "A", "employeur": "B", "debut": "2010-01-01"},
                {"poste": "C", "employeur": "D", "debut": "pas une date"},
            ]
        }
    )
    with pytest.raises(declaration.DeclarationInvalide) as echec:
        declaration.lire_parcours(brut)

    message = str(echec.value)
    assert "expérience" in message and "n° 2" in message
    assert "date de début" in message


def test_un_json_illisible_ne_fait_pas_tomber_le_depot():
    with pytest.raises(declaration.DeclarationInvalide, match="Rechargez"):
        declaration.lire_parcours("{ceci n'est pas du json")


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("togolaise, ghanéenne", ["togolaise", "ghanéenne"]),
        ("togolaise;ivoirienne", ["togolaise", "ivoirienne"]),
        ("Togolaise, togolaise", ["Togolaise"]),
        ("", []),
        (None, []),
    ],
)
def test_les_nationalites_se_lisent_en_liste(brut, attendu):
    assert declaration.lire_nationalites(brut) == attendu


def test_une_date_de_naissance_absurde_est_refusee():
    for mauvaise in ("2099-01-01", "1850-01-01"):
        with pytest.raises(declaration.DeclarationInvalide):
            declaration.lire_date_naissance(mauvaise)


def test_une_date_de_naissance_mal_formee_le_dit_clairement():
    with pytest.raises(declaration.DeclarationInvalide, match="AAAA-MM-JJ"):
        declaration.lire_date_naissance("12/05/1981")


# --- ce qu'on en fait --------------------------------------------------------


class FauxCandidat:
    id = "c1"
    langues = None
    certifications = None
    formations_complementaires = None


def test_le_parcours_declare_porte_la_provenance_DECLARE():
    """C'est l'intéressé qui parle : cela compte sans relecture.

    Une extraction, elle, force le dossier « à vérifier ».
    """
    parcours = declaration.lire_parcours(
        json.dumps(
            {
                "diplomes": [
                    {"intitule": "Licence", "niveau": 3, "domaine": "Gestion"}
                ],
                "experiences": [
                    {"poste": "Comptable", "employeur": "X", "debut": "2015-01-01"}
                ],
            }
        )
    )
    lignes = declaration.appliquer(FauxCandidat(), parcours)

    assert len(lignes) == 2
    assert all(l.provenance is Provenance.DECLARE for l in lignes)


def test_les_domaines_declares_passent_par_le_referentiel():
    """Le barème compare des domaines normalisés.

    Une déclaration qui garderait sa casse et ses accents ne s'y retrouverait
    pas, et le candidat perdrait les points de son propre métier.
    """
    parcours = declaration.lire_parcours(
        json.dumps(
            {
                "diplomes": [
                    {"intitule": "Master", "niveau": 5, "domaine": "Comptabilité"}
                ],
                "experiences": [
                    {
                        "poste": "Chef comptable",
                        "employeur": "X",
                        "debut": "2015-01-01",
                        "domaines": ["Comptabilité Générale"],
                    }
                ],
            }
        )
    )
    diplome, experience = declaration.appliquer(FauxCandidat(), parcours)

    assert diplome.domaine == "comptabilite"
    assert experience.domaines == ["comptabilite generale"]


# --- de bout en bout, par le formulaire public ------------------------------


async def monter_poste(client, auth, **restriction) -> str:
    """Un poste publié, avec ses conditions restrictives éventuelles.

    `restriction` prend les clés de `RestrictionIn` — age_max, nationalites,
    justification — que le schéma attend groupées sous un objet.
    """
    client_id = (
        await client.post(f"{API}/clients", json={"nom": "Sarakawa"}, headers=auth)
    ).json()["id"]
    mandat_id = (
        await client.post(
            f"{API}/mandats",
            json={"client_id": client_id, "intitule": "Recrutement"},
            headers=auth,
        )
    ).json()["id"]
    corps = {
        "intitule": "Chef comptable",
        "niveau_min": 3,
        "domaines_acceptes": ["comptabilite"],
        "annees_experience_min": 5,
        "annees_experience_specifique_min": 3,
        "domaines_experience": ["comptabilite"],
        "pieces_requises": ["CV"],
    }
    if restriction:
        # Une condition restrictive sans justification est refusée par le
        # schéma, comme en base et dans le moteur : on ne restreint pas sans
        # dire pourquoi. Les tests posent donc toujours la leur.
        restriction.setdefault("justification", "Exigence du commanditaire.")
        corps["restriction"] = restriction
    creation = await client.post(
        f"{API}/mandats/{mandat_id}/postes", json=corps, headers=auth
    )
    assert creation.status_code == 201, creation.text
    poste_id = creation.json()["id"]
    avis = await client.post(
        f"{API}/postes/{poste_id}/avis",
        json={"type_avis": "NATIONAL", "date_cloture": "2027-12-31"},
        headers=auth,
    )
    cle = avis.json()["cle_publique"]
    await client.post(f"{API}/avis/{avis.json()['id']}/publier", headers=auth)
    return cle


def dossier(**extra) -> dict:
    return {
        "nom": "ATTIOGBE",
        "prenom": "Sena",
        "email": "s.attiogbe@example.tg",
        "types_pieces": ["CV"],
        **extra,
    }


PARCOURS_COMPLET = json.dumps(
    {
        "diplomes": [
            {
                "intitule": "Master en sciences comptables",
                "niveau": 5,
                "domaine": "comptabilite",
                "annee": 2005,
            }
        ],
        "experiences": [
            {
                "poste": "Chef comptable",
                "employeur": "Groupe Atlantique",
                "debut": "2006-01-01",
                "fin": "2024-01-01",
                "domaines": ["comptabilite"],
            }
        ],
    }
)


async def test_la_condition_d_age_s_applique_des_le_depot(client, auth):
    """Elle ne s'appliquait qu'aux dossiers déjà dépouillés.

    Deux candidats du même âge connaissaient donc deux sorts différents selon
    qu'on avait eu le temps de lire leur CV. Le candidat déclarant tout son
    dossier, plus rien n'est « pas encore lu » : l'élimination est opposable et
    le statut est tranché au dépôt.
    """
    cle = await monter_poste(
        client,
        auth,
        age_max=45,
        justification="Pyramide des âges du service.",
    )

    reponse = await client.post(
        f"{API}/public/avis/{cle}/candidater",
        data=dossier(date_naissance="1960-05-04", parcours=PARCOURS_COMPLET),
        files={"fichiers": ("cv.pdf", b"%PDF-1.4 un CV", "application/pdf")},
    )
    assert reponse.status_code == 201, reponse.text

    detail = (
        await client.get(
            f"{API}/candidatures/{reponse.json()['candidature_id']}", headers=auth
        )
    ).json()
    motifs = [e["motif"] for e in detail["eliminations"]]
    assert "CONDITION_AGE" in motifs
    assert detail["statut"] == "ELIMINEE"


async def test_un_dossier_non_declare_reste_a_verifier(client, auth):
    """La prudence d'origine ne bouge pas.

    Sans parcours déclaré, « aucun diplôme » veut dire « pas encore dépouillé »
    et non « aucun diplôme » : le dossier attend une lecture au lieu d'être
    écarté pour un travail que le cabinet n'a pas encore fait. Déclarer ne
    supprime pas cette prudence — cela lui retire seulement son objet.
    """
    cle = await monter_poste(client, auth)

    reponse = await client.post(
        f"{API}/public/avis/{cle}/candidater",
        data=dossier(email="muet@example.tg"),
        files={"fichiers": ("cv.pdf", b"%PDF-1.4 un CV", "application/pdf")},
    )
    detail = (
        await client.get(
            f"{API}/candidatures/{reponse.json()['candidature_id']}", headers=auth
        )
    ).json()
    assert detail["statut"] == "A_VERIFIER"


async def test_sans_date_declaree_la_condition_reste_muette(client, auth):
    """Le comportement d'avant, conservé : on n'invente pas un âge."""
    cle = await monter_poste(client, auth, age_max=45)

    reponse = await client.post(
        f"{API}/public/avis/{cle}/candidater",
        data=dossier(email="autre@example.tg"),
        files={"fichiers": ("cv.pdf", b"%PDF-1.4 un CV", "application/pdf")},
    )
    assert reponse.status_code == 201

    detail = (
        await client.get(
            f"{API}/candidatures/{reponse.json()['candidature_id']}", headers=auth
        )
    ).json()
    assert "CONDITION_AGE" not in [e["motif"] for e in detail["eliminations"]]


async def test_le_parcours_declare_est_note_sans_attendre_de_relecture(client, auth):
    """Sans lui, le dossier valait 3 sur 30 — non par faiblesse, mais parce que
    personne ne l'avait encore lu."""
    cle = await monter_poste(client, auth)

    parcours = json.dumps(
        {
            "diplomes": [
                {
                    "intitule": "Master en sciences comptables",
                    "niveau": 5,
                    "domaine": "comptabilite",
                    "annee": 2012,
                }
            ],
            "experiences": [
                {
                    "poste": "Chef comptable",
                    "employeur": "Groupe Atlantique",
                    "debut": "2013-01-01",
                    "fin": "2024-01-01",
                    "domaines": ["comptabilite"],
                }
            ],
            "langues": ["français"],
        }
    )
    reponse = await client.post(
        f"{API}/public/avis/{cle}/candidater",
        data=dossier(parcours=parcours, date_naissance="1985-03-12"),
        files={"fichiers": ("cv.pdf", b"%PDF-1.4 un CV", "application/pdf")},
    )
    assert reponse.status_code == 201, reponse.text

    detail = (
        await client.get(
            f"{API}/candidatures/{reponse.json()['candidature_id']}", headers=auth
        )
    ).json()

    assert detail["candidat"]["diplomes"], "le diplôme déclaré est en base"
    assert detail["candidat"]["experiences"]
    assert detail["statut"] != "ELIMINEE"
    # La formation et l'expérience comptent : la note dépasse largement les
    # trois points de la seule consistance du dossier.
    assert detail["notation"]["total"] > 10


async def test_un_parcours_incoherent_refuse_le_depot_avec_un_message_utile(client, auth):
    cle = await monter_poste(client, auth)

    mauvais = json.dumps(
        {
            "experiences": [
                {
                    "poste": "Comptable",
                    "employeur": "X",
                    "debut": "2020-01-01",
                    "fin": "2015-01-01",
                }
            ]
        }
    )
    reponse = await client.post(
        f"{API}/public/avis/{cle}/candidater",
        data=dossier(parcours=mauvais),
        files={"fichiers": ("cv.pdf", b"%PDF-1.4 un CV", "application/pdf")},
    )
    assert reponse.status_code == 422
    assert "précède" in reponse.json()["detail"]


async def test_les_conditions_eliminatoires_sont_annoncees_au_candidat(client, auth):
    """Composer un dossier complet pour être écarté sur un critère jamais vu
    serait traiter le candidat avec désinvolture."""
    cle = await monter_poste(
        client,
        auth,
        age_max=45,
        nationalites=["togolaise"],
        justification="Exigence du commanditaire.",
    )

    avis = (await client.get(f"{API}/public/avis/{cle}")).json()

    assert any("45 ans au plus" in c for c in avis["conditions"])
    assert any("togolaise" in c for c in avis["conditions"])
    assert avis["justification_conditions"] == "Exigence du commanditaire."
