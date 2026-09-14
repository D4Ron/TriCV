from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio

API = "/api/v1"
PDF_A = b"%PDF-1.4\n" + b"A" * 400
PDF_B = b"%PDF-1.4\n" + b"B" * 400


async def monter_poste(client, auth) -> str:
    client_id = (
        await client.post(f"{API}/clients", json={"nom": "Client doublons"}, headers=auth)
    ).json()["id"]
    mandat_id = (
        await client.post(
            f"{API}/mandats", json={"client_id": client_id, "intitule": "M"}, headers=auth
        )
    ).json()["id"]
    return (
        await client.post(
            f"{API}/mandats/{mandat_id}/postes",
            json={"intitule": "Poste", "niveau_min": 3, "pieces_requises": ["CV"]},
            headers=auth,
        )
    ).json()["id"]


async def depot(client, auth, poste_id, fichiers):
    return await client.post(
        f"{API}/postes/{poste_id}/candidatures/depot-multiple",
        files=[("fichiers", (nom, donnees, "application/pdf")) for nom, donnees in fichiers],
        headers=auth,
    )


async def test_depot_multiple_cree_une_candidature_par_candidat(client, auth):
    poste_id = await monter_poste(client, auth)
    reponse = await depot(
        client, auth, poste_id, [("kodjo_amina.pdf", PDF_A), ("mensah_kofi.pdf", PDF_B)]
    )
    assert reponse.status_code == 201, reponse.text
    corps = reponse.json()
    assert corps["deposes"] == 2
    assert corps["refuses"] == 0

    page = (await client.get(f"{API}/postes/{poste_id}/candidatures", headers=auth)).json()
    assert page["total"] == 2
    # Le nom du fichier sert d'identité provisoire, débarrassé de ses
    # séparateurs, puis réparti entre nom et prénom : « kodjo_amina.pdf »
    # remplit les deux colonnes de la grille. Versé d'un bloc dans le nom, il
    # laissait la colonne « prénom » vide sur tout dossier arrivé en lot.
    assert {(i["nom"], i["prenom"]) for i in page["items"]} == {
        ("kodjo", "amina"),
        ("mensah", "kofi"),
    }


async def test_les_dossiers_deposes_en_lot_attendent_une_relecture(client, auth):
    """Personne n'a rien saisi : ils ne sont ni éliminés ni présélectionnés."""
    poste_id = await monter_poste(client, auth)
    await depot(client, auth, poste_id, [("cv.pdf", PDF_A)])

    page = (await client.get(f"{API}/postes/{poste_id}/candidatures", headers=auth)).json()
    assert page["items"][0]["statut"] == "A_VERIFIER"


async def test_le_meme_fichier_est_ecarte_au_depot(client, auth):
    """Un fichier identique n'apporte rien : aucun second dossier n'est ouvert."""
    poste_id = await monter_poste(client, auth)
    await depot(client, auth, poste_id, [("premier.pdf", PDF_A)])
    reponse = await depot(client, auth, poste_id, [("second.pdf", PDF_A)])

    corps = reponse.json()
    assert corps["deposes"] == 0
    assert corps["doublons_ignores"] == 1
    resultat = corps["resultats"][0]
    assert resultat["accepte"] is False
    assert "doublon" in resultat["erreur"].lower()

    # Une seule candidature en base : rien n'a été créé puis effacé.
    page = (await client.get(f"{API}/postes/{poste_id}/candidatures", headers=auth)).json()
    assert page["total"] == 1


async def test_deux_fichiers_differents_sont_acceptes(client, auth):
    poste_id = await monter_poste(client, auth)
    await depot(client, auth, poste_id, [("a.pdf", PDF_A)])
    reponse = await depot(client, auth, poste_id, [("b.pdf", PDF_B)])
    assert reponse.json()["deposes"] == 1
    assert reponse.json()["doublons_ignores"] == 0


async def test_un_lot_contenant_deux_fois_le_meme_fichier(client, auth):
    """Le doublon interne au lot est écarté au passage, pas après coup."""
    poste_id = await monter_poste(client, auth)
    reponse = await depot(
        client, auth, poste_id, [("a.pdf", PDF_A), ("copie.pdf", PDF_A), ("b.pdf", PDF_B)]
    )
    corps = reponse.json()
    assert corps["deposes"] == 2
    assert corps["doublons_ignores"] == 1

    page = (await client.get(f"{API}/postes/{poste_id}/candidatures", headers=auth)).json()
    assert page["total"] == 2


async def test_le_refus_nomme_le_dossier_duplique(client, auth):
    poste_id = await monter_poste(client, auth)
    await depot(client, auth, poste_id, [("kodjo.pdf", PDF_A)])
    seconde = (await depot(client, auth, poste_id, [("copie.pdf", PDF_A)])).json()

    resultat = seconde["resultats"][0]
    # Savoir *lequel* il duplique évite d'avoir à le chercher à la main.
    assert "KODJO" in resultat["doublon_de"].upper()


async def test_un_fichier_refuse_n_interrompt_pas_le_lot(client, auth):
    poste_id = await monter_poste(client, auth)
    reponse = await depot(
        client,
        auth,
        poste_id,
        [("bon.pdf", PDF_A), ("image.png", b"\x89PNG\r\n\x1a\n" + b"0" * 200), ("autre.pdf", PDF_B)],
    )
    corps = reponse.json()
    assert corps["deposes"] == 2
    assert corps["refuses"] == 1
    refuse = next(r for r in corps["resultats"] if not r["accepte"])
    assert refuse["fichier"] == "image.png"
    assert refuse["erreur"]


async def test_un_depot_authentifie_n_a_pas_de_plafond_de_taille(client, auth):
    """Un scan de diplômes lourd ne doit pas être refusé à l'arrivée.

    Le stockage se maîtrise en purgeant les mandats archivés — voir
    test_purge.py — pas en écartant des dossiers légitimes.
    """
    client_id = (
        await client.post(f"{API}/clients", json={"nom": "C"}, headers=auth)
    ).json()["id"]
    mandat_id = (
        await client.post(
            f"{API}/mandats", json={"client_id": client_id, "intitule": "M"}, headers=auth
        )
    ).json()["id"]
    poste_id = (
        await client.post(
            f"{API}/mandats/{mandat_id}/postes",
            json={"intitule": "Poste", "pieces_requises": ["CV"]},
            headers=auth,
        )
    ).json()["id"]

    gros = b"%PDF-1.4\n" + b"0" * (12 * 1024 * 1024)
    reponse = await depot(client, auth, poste_id, [("gros.pdf", gros)])
    corps = reponse.json()
    assert corps["refuses"] == 0, corps


async def test_une_piece_ne_peut_etre_exigee_et_facultative(client, auth):
    client_id = (
        await client.post(f"{API}/clients", json={"nom": "C"}, headers=auth)
    ).json()["id"]
    mandat_id = (
        await client.post(
            f"{API}/mandats", json={"client_id": client_id, "intitule": "M"}, headers=auth
        )
    ).json()["id"]
    reponse = await client.post(
        f"{API}/mandats/{mandat_id}/postes",
        json={
            "intitule": "Poste",
            "pieces_requises": ["CV"],
            "pieces_facultatives": ["CV"],
        },
        headers=auth,
    )
    assert reponse.status_code == 422
