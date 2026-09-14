"""Le CV reconstitué, et les réponses du promoteur versées à son fil.

Deux ajouts sans rapport de fonction, mais qui partagent une règle : ne pas
donner à une donnée plus d'autorité qu'elle n'en a. Un CV à en-tête du cabinet
tiré d'une extraction non confirmée blanchirait une supposition ; une réponse de
promoteur classée en candidature ferait entrer un interlocuteur dans une grille.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime

import pytest

from app.db import SessionLocal

pytestmark = pytest.mark.anyio

API = "/api/v1"
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


async def monter_poste(client, auth) -> tuple[str, str]:
    client_id = (
        await client.post(f"{API}/clients", json={"nom": "Dogta"}, headers=auth)
    ).json()["id"]
    mandat_id = (
        await client.post(
            f"{API}/mandats", json={"client_id": client_id, "intitule": "M"}, headers=auth
        )
    ).json()["id"]
    poste_id = (
        await client.post(
            f"{API}/mandats/{mandat_id}/postes",
            json={"intitule": "Directeur", "niveau_min": 3, "pieces_requises": []},
            headers=auth,
        )
    ).json()["id"]
    return mandat_id, poste_id


async def saisir_dossier(client, auth, poste_id: str) -> str:
    """Un dossier saisi par les RH : provenance SAISI_RH, donc relu par nature."""
    reponse = await client.post(
        f"{API}/postes/{poste_id}/candidatures",
        json={
            "candidat": {
                "nom": "KODJO",
                "prenom": "Amina",
                "email": "amina@example.com",
                "telephone": "90 00 00 00",
                "diplomes": [
                    {
                        "intitule": "Master en gestion des ressources humaines",
                        "niveau": 5,
                        "domaine": "gestion des ressources humaines",
                        "etablissement": "Université de Lomé",
                        "annee": 2015,
                    }
                ],
                "experiences": [
                    {
                        "poste": "Responsable RH",
                        "employeur": "Groupe Sarakawa",
                        "debut": "2016-03-01",
                        "fin": None,
                        "domaines": ["ressources humaines"],
                        "pays": "Togo",
                    }
                ],
            },
            "pieces_fournies": [],
        },
        headers=auth,
    )
    assert reponse.status_code == 201, reponse.text
    return reponse.json()["id"]


# --- CV reconstitué ----------------------------------------------------------


async def test_le_cv_maison_reprend_le_parcours_du_dossier(client, auth):
    _, poste_id = await monter_poste(client, auth)
    candidature_id = await saisir_dossier(client, auth, poste_id)

    export = await client.get(
        f"{API}/candidatures/{candidature_id}/cv-maison?format=txt", headers=auth
    )
    assert export.status_code == 200, export.text
    texte = export.content.decode("utf-8")
    assert "KODJO Amina" in texte
    assert "Responsable RH — Groupe Sarakawa" in texte
    assert "mars 2016 – aujourd'hui" in texte
    assert "Master en gestion des ressources humaines" in texte


async def test_le_cv_maison_se_livre_sans_coordonnees(client, auth):
    """Certains mandats comparent les parcours avant de savoir qui est qui."""
    _, poste_id = await monter_poste(client, auth)
    candidature_id = await saisir_dossier(client, auth, poste_id)

    export = await client.get(
        f"{API}/candidatures/{candidature_id}/cv-maison?format=txt&avec_coordonnees=false",
        headers=auth,
    )
    assert export.status_code == 200
    texte = export.content.decode("utf-8")
    assert "amina@example.com" not in texte
    assert "90 00 00 00" not in texte
    # Le parcours, lui, reste entier.
    assert "Responsable RH — Groupe Sarakawa" in texte


@pytest.mark.parametrize("format_", ["docx", "pdf", "txt"])
async def test_le_cv_maison_se_rend_dans_chaque_format(client, auth, format_):
    _, poste_id = await monter_poste(client, auth)
    candidature_id = await saisir_dossier(client, auth, poste_id)
    export = await client.get(
        f"{API}/candidatures/{candidature_id}/cv-maison?format={format_}", headers=auth
    )
    assert export.status_code == 200, format_
    assert len(export.content) > 100, format_


async def test_un_parcours_non_relu_ne_donne_pas_de_cv_a_en_tete(client, auth):
    """C'est la règle qui gouverne tout le reste.

    Un CV reconstitué porte l'en-tête du cabinet. Y verser une extraction que
    personne n'a confirmée transformerait une supposition en pièce remise au
    client.
    """
    from sqlalchemy import select, update

    from app.models import Candidat, Provenance

    _, poste_id = await monter_poste(client, auth)
    candidature_id = await saisir_dossier(client, auth, poste_id)
    async with SessionLocal() as db:
        identifiant = (
            await db.execute(select(Candidat.id).limit(1))
        ).scalar_one()
        await db.execute(
            update(Candidat)
            .where(Candidat.id == identifiant)
            .values(provenance=Provenance.EXTRAIT_IA)
        )
        await db.commit()

    refus = await client.get(
        f"{API}/candidatures/{candidature_id}/cv-maison?format=txt", headers=auth
    )
    assert refus.status_code == 409
    assert "confirmée" in refus.json()["detail"]

    # Demandé explicitement, il sort — et le document le dit.
    force = await client.get(
        f"{API}/candidatures/{candidature_id}/cv-maison"
        "?format=txt&accepter_non_verifie=true",
        headers=auth,
    )
    assert force.status_code == 200
    assert "non encore confirmées" in force.content.decode("utf-8")


async def test_les_cv_d_un_poste_se_livrent_en_une_archive(client, auth):
    _, poste_id = await monter_poste(client, auth)
    await saisir_dossier(client, auth, poste_id)

    export = await client.get(
        f"{API}/postes/{poste_id}/cvs-maison.zip?format=txt&portee=tous", headers=auth
    )
    assert export.status_code == 200, export.text
    archive = zipfile.ZipFile(io.BytesIO(export.content))
    assert [n for n in archive.namelist() if n.startswith("CV - ")]
    assert export.headers["X-TriCV-Inclus"] == "1"


async def test_un_dossier_non_relu_est_ecarte_de_l_archive(client, auth):
    """Sur un lot, une mention se perd : mieux vaut écarter et le dire à part."""
    from sqlalchemy import select, update

    from app.models import Candidat, Provenance

    _, poste_id = await monter_poste(client, auth)
    await saisir_dossier(client, auth, poste_id)
    async with SessionLocal() as db:
        identifiant = (await db.execute(select(Candidat.id).limit(1))).scalar_one()
        await db.execute(
            update(Candidat)
            .where(Candidat.id == identifiant)
            .values(provenance=Provenance.EXTRAIT_IA)
        )
        await db.commit()

    refus = await client.get(
        f"{API}/postes/{poste_id}/cvs-maison.zip?format=txt&portee=tous", headers=auth
    )
    # Aucun dossier relu : rien à livrer, et le refus le dit.
    assert refus.status_code == 409


# --- réponses du promoteur ---------------------------------------------------


async def ouvrir_acces(client, auth, mandat_id: str, email: str) -> None:
    reponse = await client.post(
        f"{API}/mandats/{mandat_id}/acces",
        json={"email": email, "nom": "AGBEKO Yao", "envoyer_courriel": False},
        headers=auth,
    )
    assert reponse.status_code == 201, reponse.text


async def test_la_reponse_d_un_promoteur_rejoint_le_fil_de_son_mandat(client, auth):
    """Sinon elle restait dans la boîte, invisible de l'écran où l'échange se lit."""
    from app.services import courriel

    from tests.test_courriel import BoiteFactice, construire_message

    mandat_id, _ = await monter_poste(client, auth)
    await ouvrir_acces(client, auth, mandat_id, "promoteur@wapp.example.com")

    async with SessionLocal() as db:
        resultat = await courriel.relever(
            db,
            BoiteFactice(
                [
                    construire_message(
                        message_id="<rep@x>",
                        expediteur="AGBEKO Yao <promoteur@wapp.example.com>",
                        sujet="Re: Profil recherché",
                        pieces=(),
                    )
                ]
            ),
        )
        await db.commit()

    assert resultat.echanges_client == 1
    assert resultat.crees == 0
    assert resultat.spontanees == 0

    fil = (await client.get(f"{API}/mandats/{mandat_id}/echanges", headers=auth)).json()
    assert len(fil) == 1
    assert fil[0]["auteur"] == "CLIENT"
    assert fil[0]["objet"] == "Re: Profil recherché"


async def test_une_reponse_de_promoteur_n_est_jamais_une_candidature(client, auth):
    """Même avec une pièce jointe : c'est un document de travail, pas un CV."""
    from app.services import courriel

    from tests.test_courriel import BoiteFactice, construire_message

    mandat_id, _ = await monter_poste(client, auth)
    await ouvrir_acces(client, auth, mandat_id, "promoteur@wapp.example.com")

    async with SessionLocal() as db:
        resultat = await courriel.relever(
            db,
            BoiteFactice(
                [
                    construire_message(
                        message_id="<pj@x>",
                        expediteur="promoteur@wapp.example.com",
                        sujet="Termes de référence",
                        pieces=(("tdr.pdf", PDF),),
                    )
                ]
            ),
        )
        await db.commit()

    assert resultat.echanges_client == 1
    assert resultat.crees == 0
    assert resultat.spontanees == 0


async def test_rejouer_le_releve_ne_double_pas_la_reponse(client, auth):
    from app.services import courriel

    from tests.test_courriel import BoiteFactice, construire_message

    mandat_id, _ = await monter_poste(client, auth)
    await ouvrir_acces(client, auth, mandat_id, "promoteur@wapp.example.com")
    messages = [
        construire_message(
            message_id="<rep@x>",
            expediteur="promoteur@wapp.example.com",
            sujet="Re: suivi",
            pieces=(),
        )
    ]

    for _ in range(2):
        async with SessionLocal() as db:
            await courriel.relever(db, BoiteFactice(messages))
            await db.commit()

    fil = (await client.get(f"{API}/mandats/{mandat_id}/echanges", headers=auth)).json()
    assert len(fil) == 1


async def test_un_acces_revoque_ne_capte_plus_les_messages(client, auth):
    """Après la clôture du mandat, l'expéditeur redevient un inconnu."""
    from app.services import courriel

    from tests.test_courriel import BoiteFactice, construire_message

    mandat_id, _ = await monter_poste(client, auth)
    await ouvrir_acces(client, auth, mandat_id, "promoteur@wapp.example.com")
    await client.patch(
        f"{API}/mandats/{mandat_id}", json={"statut": "CLOTURE"}, headers=auth
    )

    async with SessionLocal() as db:
        resultat = await courriel.relever(
            db,
            BoiteFactice(
                [
                    construire_message(
                        message_id="<apres@x>",
                        expediteur="promoteur@wapp.example.com",
                        sujet="Bonjour",
                        pieces=(),
                    )
                ]
            ),
        )
        await db.commit()

    assert resultat.echanges_client == 0
