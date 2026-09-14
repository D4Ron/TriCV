"""Le dépôt en lot : un candidat, plusieurs pièces.

Les RH vident une boîte email et se retrouvent avec les quatre fichiers d'une
même personne. Ce qui est testé ici, c'est qu'ils forment un dossier et non
quatre — et surtout que le regroupement se trompe *dans le bon sens* : mieux
vaut un dossier en trop que deux personnes mélangées.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from app.services import lots

pytestmark = pytest.mark.anyio

API = "/api/v1"
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def pdf(marque: bytes) -> bytes:
    """Un PDF minimal mais distinct : deux fichiers identiques sont un doublon."""
    return PDF + marque


# --- reconnaissance du type --------------------------------------------------


@pytest.mark.parametrize(
    ("nom", "attendu"),
    [
        ("KODJO_Amina_CV.pdf", "CV"),
        ("CV - Amina Kodjo.pdf", "CV"),
        ("curriculum-vitae-kodjo.pdf", "CV"),
        ("Lettre de motivation KODJO.pdf", "LETTRE_MOTIVATION"),
        ("KODJO_diplome_master.pdf", "COPIE_DIPLOMES"),
        ("attestation-travail-kodjo.pdf", "ATTESTATIONS_TRAVAIL"),
        ("Passeport_KODJO.pdf", "PASSEPORT"),
        ("CNI Amina Kodjo.pdf", "PIECE_IDENTITE"),
        # « recommandation » doit l'emporter sur « lettre » : sans quoi une
        # recommandation passerait pour une lettre de motivation.
        ("Lettre de recommandation - BOAD.pdf", "LETTRE_RECOMMANDATION"),
    ],
)
def test_le_nom_du_fichier_indique_le_type(nom, attendu):
    assert lots.type_devine(nom) == attendu


def test_un_nom_muet_ne_donne_aucun_type():
    """Classer d'office en CV donnerait une complétude fausse.

    Un dossier compté complet alors que le CV manque est une erreur qui ne se
    voit qu'au moment de la grille — bien trop tard.
    """
    assert lots.type_devine("scan001.pdf") is None
    assert lots.type_devine("Dossier_KODJO.pdf") is None


# --- regroupement ------------------------------------------------------------


def test_les_pieces_d_un_meme_candidat_forment_un_dossier():
    dossiers = lots.proposer(
        [
            "KODJO_Amina_CV.pdf",
            "KODJO_Amina_lettre.pdf",
            "Diplome - Amina KODJO.pdf",
        ]
    )
    assert len(dossiers) == 1
    assert len(dossiers[0].pieces) == 3


def test_les_mots_de_liaison_ne_separent_pas_un_dossier():
    """« lettre_de_motivation » laissait un « de » dans la clé.

    Le fichier formait alors un dossier à part, séparé du CV de la même
    personne — l'erreur la plus coûteuse, car elle ne se voit qu'en rouvrant
    chaque dossier.
    """
    dossiers = lots.proposer(
        [
            "ABALO_Kossi_CV.pdf",
            "ABALO_Kossi_lettre_de_motivation.pdf",
            "Diplome - Kossi ABALO.pdf",
        ]
    )
    assert len(dossiers) == 1
    assert len(dossiers[0].pieces) == 3


def test_deux_candidats_restent_deux_dossiers():
    dossiers = lots.proposer(
        ["KODJO_Amina_CV.pdf", "MENSAH_Afiwa_CV.pdf", "MENSAH_Afiwa_lettre.pdf"]
    )
    assert len(dossiers) == 2
    assert sorted(len(d.pieces) for d in dossiers) == [1, 2]


def test_un_fichier_sans_identite_lisible_reste_seul():
    """« CV.pdf » ne désigne personne : le rattacher au hasard mélangerait tout."""
    dossiers = lots.proposer(["CV.pdf", "CV (1).pdf", "KODJO_Amina_CV.pdf"])
    seuls = [d for d in dossiers if len(d.pieces) == 1]
    assert len(seuls) == 3


def test_l_arborescence_l_emporte_sur_le_nom():
    """Un classement en sous-dossiers vient d'un humain : il ne se discute pas."""
    dossiers = lots.proposer(
        ["CV.pdf", "lettre.pdf", "CV.pdf"],
        ["KODJO Amina/CV.pdf", "KODJO Amina/lettre.pdf", "MENSAH Afiwa/CV.pdf"],
    )
    assert len(dossiers) == 2
    assert all(d.depuis_arborescence for d in dossiers)
    kodjo = next(d for d in dossiers if "KODJO" in d.libelle)
    assert len(kodjo.pieces) == 2


# --- archives ----------------------------------------------------------------


def archive(entrees: dict[str, bytes]) -> bytes:
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as z:
        for nom, contenu in entrees.items():
            z.writestr(nom, contenu)
    return tampon.getvalue()


def test_une_archive_se_deplie_en_pieces():
    donnees = archive({"CV.pdf": pdf(b"1"), "lettre.pdf": pdf(b"2")})
    assert lots.est_archive("Dossier_KODJO.zip", donnees)
    extraits = lots.extraire("Dossier_KODJO.zip", donnees)
    assert sorted(e.nom for e in extraits) == ["CV.pdf", "lettre.pdf"]


def test_une_archive_trop_fournie_est_refusee():
    """Une bombe de décompression tient en quelques kilo-octets."""
    donnees = archive({f"f{i}.pdf": pdf(str(i).encode()) for i in range(lots.ENTREES_MAX + 5)})
    with pytest.raises(lots.ArchiveRefusee):
        lots.extraire("gros.zip", donnees)


def test_une_entree_qui_remonte_l_arborescence_est_ecartee():
    donnees = archive({"../evasion.pdf": pdf(b"x"), "CV.pdf": pdf(b"y")})
    extraits = lots.extraire("archive.zip", donnees)
    assert [e.nom for e in extraits] == ["CV.pdf"]


# --- de bout en bout ---------------------------------------------------------


async def monter_poste(client, auth) -> str:
    client_id = (
        await client.post(f"{API}/clients", json={"nom": "Dogta"}, headers=auth)
    ).json()["id"]
    mandat_id = (
        await client.post(
            f"{API}/mandats", json={"client_id": client_id, "intitule": "M"}, headers=auth
        )
    ).json()["id"]
    return (
        await client.post(
            f"{API}/mandats/{mandat_id}/postes",
            json={"intitule": "Directeur", "pieces_requises": ["CV"]},
            headers=auth,
        )
    ).json()["id"]


async def test_le_depot_en_lot_regroupe_les_pieces_par_candidat(client, auth):
    poste_id = await monter_poste(client, auth)

    reponse = await client.post(
        f"{API}/postes/{poste_id}/candidatures/depot-multiple",
        data={"depouiller_aussitot": "false"},
        files=[
            ("fichiers", ("KODJO_Amina_CV.pdf", pdf(b"a"), "application/pdf")),
            ("fichiers", ("KODJO_Amina_lettre.pdf", pdf(b"b"), "application/pdf")),
            ("fichiers", ("MENSAH_Afiwa_CV.pdf", pdf(b"c"), "application/pdf")),
        ],
        headers=auth,
    )
    assert reponse.status_code == 201, reponse.text
    corps = reponse.json()
    # Deux candidats, trois pièces — et non trois candidatures.
    assert corps["deposes"] == 2
    assert corps["pieces"] == 3

    page = (await client.get(f"{API}/postes/{poste_id}/candidatures", headers=auth)).json()
    assert page["total"] == 2


async def test_le_depot_en_lot_classe_les_pieces_par_leur_nom(client, auth):
    poste_id = await monter_poste(client, auth)
    reponse = await client.post(
        f"{API}/postes/{poste_id}/candidatures/depot-multiple",
        files=[
            ("fichiers", ("KODJO_Amina_CV.pdf", pdf(b"a"), "application/pdf")),
            ("fichiers", ("KODJO_Amina_lettre.pdf", pdf(b"b"), "application/pdf")),
        ],
        headers=auth,
    )
    candidature_id = reponse.json()["resultats"][0]["candidature_id"]
    dossier = (
        await client.get(f"{API}/candidatures/{candidature_id}", headers=auth)
    ).json()
    assert {p["type_piece"] for p in dossier["pieces"]} == {"CV", "LETTRE_MOTIVATION"}


async def test_un_regroupement_impose_prime_sur_la_deduction(client, auth):
    """L'écran montre le découpage et quelqu'un le corrige : ça fait foi."""
    poste_id = await monter_poste(client, auth)
    reponse = await client.post(
        f"{API}/postes/{poste_id}/candidatures/depot-multiple",
        data={"groupes": ["KODJO Amina", "KODJO Amina"]},
        files=[
            ("fichiers", ("scan001.pdf", pdf(b"a"), "application/pdf")),
            ("fichiers", ("scan002.pdf", pdf(b"b"), "application/pdf")),
        ],
        headers=auth,
    )
    assert reponse.status_code == 201, reponse.text
    assert reponse.json()["deposes"] == 1
    assert reponse.json()["pieces"] == 2


async def test_une_archive_donne_un_dossier_complet(client, auth):
    poste_id = await monter_poste(client, auth)
    donnees = archive(
        {
            "CV.pdf": pdf(b"cv"),
            "Lettre de motivation.pdf": pdf(b"lm"),
            "diplome.pdf": pdf(b"dip"),
        }
    )
    reponse = await client.post(
        f"{API}/postes/{poste_id}/candidatures/depot-multiple",
        files=[("fichiers", ("Dossier_KODJO.zip", donnees, "application/zip"))],
        headers=auth,
    )
    assert reponse.status_code == 201, reponse.text
    assert reponse.json()["deposes"] == 1
    assert reponse.json()["pieces"] == 3

    candidature_id = reponse.json()["resultats"][0]["candidature_id"]
    dossier = (
        await client.get(f"{API}/candidatures/{candidature_id}", headers=auth)
    ).json()
    assert {p["type_piece"] for p in dossier["pieces"]} == {
        "CV",
        "LETTRE_MOTIVATION",
        "COPIE_DIPLOMES",
    }


async def test_l_apercu_montre_le_decoupage_sans_rien_ecrire(client, auth):
    poste_id = await monter_poste(client, auth)
    reponse = await client.post(
        f"{API}/postes/{poste_id}/candidatures/depot-multiple/apercu",
        data={"noms": ["KODJO_Amina_CV.pdf", "KODJO_Amina_lettre.pdf", "MENSAH_CV.pdf"]},
        headers=auth,
    )
    assert reponse.status_code == 200, reponse.text
    dossiers = reponse.json()["dossiers"]
    assert len(dossiers) == 2

    # Rien n'a été créé : l'aperçu ne touche à rien.
    page = (await client.get(f"{API}/postes/{poste_id}/candidatures", headers=auth)).json()
    assert page["total"] == 0


async def test_on_rattache_plusieurs_pieces_a_un_dossier_existant(client, auth):
    """Le reste des pièces arrive après — second message, ou oubli du tri."""
    poste_id = await monter_poste(client, auth)
    depot = await client.post(
        f"{API}/postes/{poste_id}/candidatures/depot-multiple",
        files=[("fichiers", ("KODJO_Amina_CV.pdf", pdf(b"a"), "application/pdf"))],
        headers=auth,
    )
    candidature_id = depot.json()["resultats"][0]["candidature_id"]

    ajout = await client.post(
        f"{API}/candidatures/{candidature_id}/pieces/lot",
        files=[
            ("fichiers", ("lettre de motivation.pdf", pdf(b"b"), "application/pdf")),
            ("fichiers", ("diplome master.pdf", pdf(b"c"), "application/pdf")),
        ],
        headers=auth,
    )
    assert ajout.status_code == 201, ajout.text
    assert {p["type_piece"] for p in ajout.json()["pieces"]} == {
        "CV",
        "LETTRE_MOTIVATION",
        "COPIE_DIPLOMES",
    }


async def test_rattacher_deux_fois_le_meme_fichier_ne_le_duplique_pas(client, auth):
    poste_id = await monter_poste(client, auth)
    depot = await client.post(
        f"{API}/postes/{poste_id}/candidatures/depot-multiple",
        files=[("fichiers", ("KODJO_Amina_CV.pdf", pdf(b"a"), "application/pdf"))],
        headers=auth,
    )
    candidature_id = depot.json()["resultats"][0]["candidature_id"]

    for _ in range(2):
        reponse = await client.post(
            f"{API}/candidatures/{candidature_id}/pieces/lot",
            files=[("fichiers", ("lettre.pdf", pdf(b"b"), "application/pdf"))],
            headers=auth,
        )
        assert reponse.status_code == 201, reponse.text
    assert len(reponse.json()["pieces"]) == 2


def test_le_patronyme_en_capitales_est_reconnu_comme_nom():
    """Le cabinet écrit le nom de famille en capitales — dans ses fichiers
    comme dans ses grilles. C'est le seul indice disponible sur un dépôt en
    lot : la lecture assistée ne rend pas l'état civil, le texte étant expurgé
    des noms avant de partir au modèle."""
    assert lots.separer_identite("AGBODJAN Komlan") == ("AGBODJAN", "Komlan")
    # L'ordre inverse désigne la même personne.
    assert lots.separer_identite("Komlan AGBODJAN") == ("AGBODJAN", "Komlan")
    assert lots.separer_identite("AGBODJAN Komlan Mensah") == ("AGBODJAN", "Komlan Mensah")


def test_sans_capitales_le_premier_mot_fait_office_de_nom():
    assert lots.separer_identite("Kodjo Amina") == ("Kodjo", "Amina")
    # Tout en capitales ne distingue rien : on retombe sur l'ordre.
    assert lots.separer_identite("KODJO AMINA") == ("KODJO", "AMINA")


def test_un_seul_mot_reste_entier():
    """Inventer un prénom serait pire qu'une case vide."""
    assert lots.separer_identite("Dossier") == ("Dossier", "")
    assert lots.separer_identite("") == ("", "")


async def test_un_depot_en_lot_remplit_la_colonne_prenom(client, auth):
    """La colonne « prénom » de la grille partait vide sur tout dossier arrivé
    en lot : le libellé du regroupement était versé en bloc dans le nom."""
    poste_id = await monter_poste(client, auth)
    depot = await client.post(
        f"{API}/postes/{poste_id}/candidatures/depot-multiple",
        files=[
            ("fichiers", ("AGBODJAN_Komlan_cv.pdf", pdf(b"a"), "application/pdf")),
            ("fichiers", ("AGBODJAN_Komlan_lettre.pdf", pdf(b"b"), "application/pdf")),
        ],
        headers=auth,
    )
    assert depot.status_code == 201, depot.text
    candidature_id = depot.json()["resultats"][0]["candidature_id"]

    dossier = (await client.get(f"{API}/candidatures/{candidature_id}", headers=auth)).json()
    assert dossier["candidat"]["nom"] == "AGBODJAN"
    assert dossier["candidat"]["prenom"] == "Komlan"
