"""Les ajouts demandés après la présentation.

Groupes de pièces, formats imposés, pièce libre, candidature spontanée, espace
du promoteur, rapports. Chaque test vérifie une règle qu'on ne veut pas voir se
défaire — pas la mécanique qui la met en œuvre.
"""

from __future__ import annotations

import pytest

from app.db import SessionLocal

pytestmark = pytest.mark.anyio

API = "/api/v1"
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
DOCX = (
    b"PK\x03\x04\x14\x00\x06\x00" + b"\x00" * 20 + b"word/document.xml" + b"\x00" * 40
)


async def monter_mandat(client, auth) -> tuple[str, str]:
    client_id = (
        await client.post(f"{API}/clients", json={"nom": "WAPP"}, headers=auth)
    ).json()["id"]
    mandat_id = (
        await client.post(
            f"{API}/mandats",
            json={"client_id": client_id, "intitule": "Recrutement cadres 2026"},
            headers=auth,
        )
    ).json()["id"]
    return client_id, mandat_id


async def monter_poste(client, auth, **surcharges) -> tuple[str, str]:
    _, mandat_id = await monter_mandat(client, auth)
    charge = {
        "intitule": "Directeur Général",
        "niveau_min": 4,
        "pieces_requises": ["CV"],
        **surcharges,
    }
    poste = (
        await client.post(
            f"{API}/mandats/{mandat_id}/postes", json=charge, headers=auth
        )
    ).json()
    return mandat_id, poste["id"]


async def publier(client, auth, poste_id: str) -> str:
    avis = (
        await client.post(
            f"{API}/postes/{poste_id}/avis",
            json={"reference": "AV-1", "date_cloture": "2026-12-31"},
            headers=auth,
        )
    ).json()
    return (
        await client.post(f"{API}/avis/{avis['id']}/publier", headers=auth)
    ).json()["cle_publique"]


# --- groupes de pièces ------------------------------------------------------


async def test_un_groupe_au_moins_une_accepte_l_une_ou_l_autre(client, auth):
    """« La CNI ou le passeport » est un choix, pas deux exigences.

    Exiger les deux obligerait un candidat qui n'a qu'un passeport valide à
    aller refaire une carte d'identité pour postuler.
    """
    _, poste_id = await monter_poste(
        client,
        auth,
        groupes_pieces=[
            {
                "codes": ["PIECE_IDENTITE", "PASSEPORT"],
                "mode": "AU_MOINS_UNE",
                "libelle": "Pièce d'identité",
            }
        ],
    )
    cle = await publier(client, auth, poste_id)

    detail = (await client.get(f"{API}/public/avis/{cle}")).json()
    assert detail["groupes_pieces"][0]["mode"] == "AU_MOINS_UNE"

    depot = await client.post(
        f"{API}/public/avis/{cle}/candidater",
        data={
            "nom": "Kodjo",
            "prenom": "Amina",
            "email": "amina@example.com",
            "types_pieces": ["CV", "PASSEPORT"],
        },
        files=[
            ("fichiers", ("cv.pdf", PDF, "application/pdf")),
            ("fichiers", ("passeport.pdf", PDF + b"P", "application/pdf")),
        ],
    )
    assert depot.status_code == 201, depot.text


async def test_un_groupe_au_moins_une_refuse_le_dossier_sans_aucune(client, auth):
    _, poste_id = await monter_poste(
        client,
        auth,
        groupes_pieces=[
            {"codes": ["PIECE_IDENTITE", "PASSEPORT"], "mode": "AU_MOINS_UNE"}
        ],
    )
    cle = await publier(client, auth, poste_id)

    depot = await client.post(
        f"{API}/public/avis/{cle}/candidater",
        data={
            "nom": "Kodjo",
            "prenom": "Amina",
            "email": "amina@example.com",
            "types_pieces": ["CV"],
        },
        files=[("fichiers", ("cv.pdf", PDF, "application/pdf"))],
    )
    assert depot.status_code == 422
    # Le message nomme les options, sinon le candidat ne sait pas quoi joindre.
    assert "ou" in depot.json()["detail"]


async def test_un_groupe_toutes_exige_chaque_piece(client, auth):
    """« Le diplôme et son attestation » : l'un sans l'autre ne vaut pas."""
    _, poste_id = await monter_poste(
        client,
        auth,
        groupes_pieces=[
            {"codes": ["DIPLOME", "ATTESTATION_TRAVAIL"], "mode": "TOUTES"}
        ],
    )
    cle = await publier(client, auth, poste_id)

    depot = await client.post(
        f"{API}/public/avis/{cle}/candidater",
        data={
            "nom": "Kodjo",
            "prenom": "Amina",
            "email": "amina@example.com",
            "types_pieces": ["CV", "DIPLOME"],
        },
        files=[
            ("fichiers", ("cv.pdf", PDF, "application/pdf")),
            ("fichiers", ("dip.pdf", PDF + b"D", "application/pdf")),
        ],
    )
    assert depot.status_code == 422


async def test_une_fiche_anterieure_aux_groupes_reste_lisible(client, auth):
    """Les colonnes ajoutées après coup valent NULL sur les fiches existantes.

    `default_factory` ne joue que si la clé est absente ; ici elle est présente
    et vaut None, si bien qu'une seule fiche ancienne rendait tout l'écran des
    postes inaccessible en 500. La coercition doit donc vivre dans le schéma.
    """
    from sqlalchemy import update

    from app.models import Poste as PosteDb

    _, poste_id = await monter_poste(client, auth)
    async with SessionLocal() as db:
        await db.execute(
            update(PosteDb)
            .where(PosteDb.id == poste_id)
            # Les deux colonnes JSON sont nullables ; le booléen, lui, reçoit
            # un défaut à l'ajout, donc il ne peut pas valoir NULL.
            .values(groupes_pieces=None, formats_pieces=None)
        )
        await db.commit()

    fiche = await client.get(f"{API}/postes/{poste_id}", headers=auth)
    assert fiche.status_code == 200, fiche.text
    assert fiche.json()["groupes_pieces"] == []
    assert fiche.json()["formats_pieces"] == {}

    mandat_id = fiche.json()["mandat_id"]
    liste = await client.get(f"{API}/mandats/{mandat_id}/postes", headers=auth)
    assert liste.status_code == 200, liste.text


# --- brouillons d'avis -------------------------------------------------------


async def test_un_brouillon_sans_date_se_reprend_puis_se_publie(client, auth):
    """Un brouillon sans date de clôture ne se publiait pas, et ne se modifiait
    pas non plus : il restait bloqué, sans autre issue que de l'abandonner.
    """
    _, poste_id = await monter_poste(client, auth)
    avis = (
        await client.post(f"{API}/postes/{poste_id}/avis", json={}, headers=auth)
    ).json()
    assert avis["date_cloture"] is None

    refus = await client.post(f"{API}/avis/{avis['id']}/publier", headers=auth)
    assert refus.status_code == 422

    reprise = await client.patch(
        f"{API}/avis/{avis['id']}",
        json={"reference": "AV-2026-001", "date_cloture": "2026-12-31"},
        headers=auth,
    )
    assert reprise.status_code == 200, reprise.text

    publie = await client.post(f"{API}/avis/{avis['id']}/publier", headers=auth)
    assert publie.status_code == 200, publie.text
    assert publie.json()["statut"] == "PUBLIE"


async def test_un_brouillon_se_supprime(client, auth):
    _, poste_id = await monter_poste(client, auth)
    avis = (
        await client.post(f"{API}/postes/{poste_id}/avis", json={}, headers=auth)
    ).json()

    suppression = await client.delete(f"{API}/avis/{avis['id']}", headers=auth)
    assert suppression.status_code == 204
    assert (await client.get(f"{API}/postes/{poste_id}/avis", headers=auth)).json() == []


async def test_un_avis_publie_ne_se_supprime_pas(client, auth):
    """Sa clé circule : l'effacer rendrait introuvable un lien reçu de bonne foi."""
    _, poste_id = await monter_poste(client, auth)
    cle = await publier(client, auth, poste_id)
    avis = (await client.get(f"{API}/postes/{poste_id}/avis", headers=auth)).json()[0]

    refus = await client.delete(f"{API}/avis/{avis['id']}", headers=auth)
    assert refus.status_code == 409
    assert "Clôturez" in refus.json()["detail"]

    # Le lien répond toujours : c'est précisément ce qu'on protège.
    assert (await client.get(f"{API}/public/avis/{cle}")).status_code == 200


async def test_un_avis_cloture_ne_se_supprime_pas_non_plus(client, auth):
    """Et le refus le dit dans les termes justes.

    Le message parlait d'avis « publié » alors que celui-ci est clôturé : lu
    par quelqu'un qui vient de le clôturer, il donne l'impression que le
    logiciel n'a pas suivi.
    """
    _, poste_id = await monter_poste(client, auth)
    await publier(client, auth, poste_id)
    avis = (await client.get(f"{API}/postes/{poste_id}/avis", headers=auth)).json()[0]
    await client.post(f"{API}/avis/{avis['id']}/cloturer", headers=auth)

    refus = await client.delete(f"{API}/avis/{avis['id']}", headers=auth)
    assert refus.status_code == 409
    assert "clôturé" in refus.json()["detail"]


# --- formats imposés --------------------------------------------------------


async def test_un_format_impose_est_verifie_au_depot(client, auth):
    _, poste_id = await monter_poste(client, auth, formats_pieces={"CV": ["pdf"]})
    cle = await publier(client, auth, poste_id)

    refus = await client.post(
        f"{API}/public/avis/{cle}/candidater",
        data={
            "nom": "Kodjo",
            "prenom": "Amina",
            "email": "amina@example.com",
            "types_pieces": ["CV"],
        },
        files=[
            (
                "fichiers",
                (
                    "cv.docx",
                    DOCX,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            )
        ],
    )
    assert refus.status_code == 422
    assert "PDF" in refus.json()["detail"]


# --- pièce libre ------------------------------------------------------------


async def test_le_candidat_peut_joindre_un_document_qu_il_nomme(client, auth):
    """Une lettre de recommandation n'a pas à entrer dans une case prévue.

    Elle est rangée sous « AUTRE » avec l'intitulé donné par le candidat, ce
    qui la rend lisible sans fausser le contrôle de complétude.
    """
    _, poste_id = await monter_poste(client, auth)
    cle = await publier(client, auth, poste_id)

    depot = await client.post(
        f"{API}/public/avis/{cle}/candidater",
        data={
            "nom": "Kodjo",
            "prenom": "Amina",
            "email": "amina@example.com",
            "types_pieces": ["CV", "AUTRE"],
            "intitules_pieces": ["", "Lettre de recommandation — BOAD"],
        },
        files=[
            ("fichiers", ("cv.pdf", PDF, "application/pdf")),
            ("fichiers", ("reco.pdf", PDF + b"R", "application/pdf")),
        ],
    )
    assert depot.status_code == 201, depot.text

    dossier = (
        await client.get(
            f"{API}/candidatures/{depot.json()['candidature_id']}", headers=auth
        )
    ).json()
    libres = [p for p in dossier["pieces"] if p["type_piece"] == "AUTRE"]
    assert libres and libres[0]["intitule_libre"] == "Lettre de recommandation — BOAD"


async def test_une_piece_libre_est_refusee_si_l_avis_les_interdit(client, auth):
    _, poste_id = await monter_poste(client, auth, pieces_libres_autorisees=False)
    cle = await publier(client, auth, poste_id)

    refus = await client.post(
        f"{API}/public/avis/{cle}/candidater",
        data={
            "nom": "Kodjo",
            "prenom": "Amina",
            "email": "amina@example.com",
            "types_pieces": ["CV", "AUTRE"],
        },
        files=[
            ("fichiers", ("cv.pdf", PDF, "application/pdf")),
            ("fichiers", ("x.pdf", PDF + b"X", "application/pdf")),
        ],
    )
    assert refus.status_code == 422


# --- candidature spontanée --------------------------------------------------


async def test_une_candidature_spontanee_rejoint_le_vivier_sans_poste(client, auth):
    """Reçue hors de tout avis, elle n'est rattachée à rien — et n'est pas notée.

    Il n'y a pas d'exigences à confronter : le profil vaut pour lui-même,
    jusqu'au jour où un mandat lui correspond.
    """
    depot = await client.post(
        f"{API}/public/candidature-spontanee",
        data={
            "nom": "Mensah",
            "prenom": "Kofi",
            "email": "kofi@example.com",
            "domaine": "Gestion hôtelière",
        },
        files=[("fichiers", ("cv.pdf", PDF, "application/pdf"))],
    )
    assert depot.status_code == 201, depot.text

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models import Candidature

    async with SessionLocal() as db:
        candidature = (
            await db.execute(
                select(Candidature).options(selectinload(Candidature.notation))
            )
        ).scalar_one()
        assert candidature.poste_id is None
        assert candidature.spontanee is True
        assert candidature.notation is None


async def test_une_candidature_spontanee_exige_un_cv(client, auth):
    refus = await client.post(
        f"{API}/public/candidature-spontanee",
        data={
            "nom": "Mensah",
            "prenom": "Kofi",
            "email": "kofi@example.com",
            "types_pieces": ["DIPLOME"],
        },
        files=[("fichiers", ("dip.pdf", PDF, "application/pdf"))],
    )
    assert refus.status_code == 422


async def test_les_candidatures_spontanees_se_ferment_depuis_les_reglages(client, auth):
    await client.patch(
        f"{API}/settings", json={"candidatures_spontanees": False}, headers=auth
    )
    refus = await client.post(
        f"{API}/public/candidature-spontanee",
        data={"nom": "M", "prenom": "K", "email": "k@example.com"},
        files=[("fichiers", ("cv.pdf", PDF, "application/pdf"))],
    )
    assert refus.status_code == 409


async def test_le_meme_dossier_spontane_n_est_pas_recu_deux_fois(client, auth):
    donnees = {"nom": "M", "prenom": "K", "email": "k@example.com"}
    fichiers = [("fichiers", ("cv.pdf", PDF, "application/pdf"))]

    premier = await client.post(
        f"{API}/public/candidature-spontanee", data=donnees, files=fichiers
    )
    assert premier.status_code == 201
    second = await client.post(
        f"{API}/public/candidature-spontanee", data=donnees, files=fichiers
    )
    assert second.status_code == 409


# --- espace du promoteur ----------------------------------------------------


async def ouvrir_acces(client, auth, mandat_id: str) -> dict:
    reponse = await client.post(
        f"{API}/mandats/{mandat_id}/acces",
        json={
            "email": "promoteur@wapp.example",
            "nom": "AGBEKO Yao",
            "fonction": "Directeur des ressources humaines",
            "envoyer_courriel": False,
        },
        headers=auth,
    )
    assert reponse.status_code == 201, reponse.text
    return reponse.json()


async def jeton_depuis_la_base(mandat_id: str) -> str:
    from sqlalchemy import select

    from app.models import AccesClient

    async with SessionLocal() as db:
        acces = (
            await db.execute(
                select(AccesClient).where(AccesClient.mandat_id == mandat_id)
            )
        ).scalar_one()
        return acces.jeton_activation


async def activer(client, auth, mandat_id: str) -> str:
    await ouvrir_acces(client, auth, mandat_id)
    jeton = await jeton_depuis_la_base(mandat_id)
    reponse = await client.post(
        f"{API}/espace-client/activation",
        json={"jeton": jeton, "mot_de_passe": "un-bon-mot-de-passe"},
    )
    assert reponse.status_code == 200, reponse.text
    return reponse.json()["token"]


async def test_le_lien_d_activation_ne_sert_qu_une_fois(client, auth):
    """Un courriel reste des années dans une boîte. Le lien, non."""
    _, mandat_id = await monter_mandat(client, auth)
    await ouvrir_acces(client, auth, mandat_id)
    jeton = await jeton_depuis_la_base(mandat_id)

    premier = await client.post(
        f"{API}/espace-client/activation",
        json={"jeton": jeton, "mot_de_passe": "un-bon-mot-de-passe"},
    )
    assert premier.status_code == 200

    second = await client.post(
        f"{API}/espace-client/activation",
        json={"jeton": jeton, "mot_de_passe": "un-autre-mot-de-passe"},
    )
    assert second.status_code == 400


async def test_un_jeton_client_n_ouvre_aucune_route_interne(client, auth):
    """Deux portes séparées, jusque dans le type de jeton."""
    _, mandat_id = await monter_mandat(client, auth)
    jeton = await activer(client, auth, mandat_id)
    entetes = {"Authorization": f"Bearer {jeton}"}

    assert (await client.get(f"{API}/clients", headers=entetes)).status_code == 401
    assert (await client.get(f"{API}/settings", headers=entetes)).status_code == 401
    # Et sa propre porte fonctionne.
    assert (await client.get(f"{API}/espace-client/suivi", headers=entetes)).status_code == 200


async def test_le_suivi_ne_montre_aucun_candidat(client, auth):
    """La confidentialité est due aux candidats, pas au commanditaire.

    Le promoteur suit l'avancement ; il n'a pas à savoir qui a postulé, ni
    combien de dossiers ont été écartés.
    """
    _, mandat_id = await monter_mandat(client, auth)
    poste_id = (
        await client.post(
            f"{API}/mandats/{mandat_id}/postes",
            json={"intitule": "Directeur", "pieces_requises": ["CV"]},
            headers=auth,
        )
    ).json()["id"]
    cle = await publier(client, auth, poste_id)
    await client.post(
        f"{API}/public/avis/{cle}/candidater",
        data={
            "nom": "Kodjo",
            "prenom": "Amina",
            "email": "amina@example.com",
            "types_pieces": ["CV"],
        },
        files=[("fichiers", ("cv.pdf", PDF, "application/pdf"))],
    )

    jeton = await activer(client, auth, mandat_id)
    suivi = (
        await client.get(
            f"{API}/espace-client/suivi", headers={"Authorization": f"Bearer {jeton}"}
        )
    ).json()

    corps = str(suivi)
    assert "Kodjo" not in corps and "amina@example.com" not in corps
    # Aucun effectif de dossiers non plus : seulement un état d'avancement.
    assert suivi["postes"][0]["avancement"] == "Réception des candidatures"


async def test_clore_le_mandat_ferme_l_espace_du_client(client, auth):
    """L'accès vit le temps du recrutement. C'est la promesse tenue."""
    _, mandat_id = await monter_mandat(client, auth)
    jeton = await activer(client, auth, mandat_id)
    entetes = {"Authorization": f"Bearer {jeton}"}
    assert (await client.get(f"{API}/espace-client/suivi", headers=entetes)).status_code == 200

    await client.patch(
        f"{API}/mandats/{mandat_id}", json={"statut": "CLOTURE"}, headers=auth
    )

    # Le jeton n'a pas expiré, mais la porte est fermée : l'accès est relu en
    # base à chaque requête, précisément pour que la clôture soit immédiate.
    assert (await client.get(f"{API}/espace-client/suivi", headers=entetes)).status_code == 403


async def test_le_promoteur_ecrit_et_le_cabinet_repond(client, auth):
    _, mandat_id = await monter_mandat(client, auth)
    jeton = await activer(client, auth, mandat_id)
    entetes = {"Authorization": f"Bearer {jeton}"}

    envoi = await client.post(
        f"{API}/espace-client/messages",
        json={
            "objet": "Profil recherché",
            "corps": "Pouvez-vous relever le niveau exigé à BAC+5 ?",
            "demande_modification": True,
        },
        headers=entetes,
    )
    assert envoi.status_code == 201, envoi.text
    assert envoi.json()["type_echange"] == "DEMANDE_MODIFICATION"

    fil = (await client.get(f"{API}/mandats/{mandat_id}/echanges", headers=auth)).json()
    assert len(fil) == 1
    assert fil[0]["auteur"] == "CLIENT"
    assert fil[0]["traite_le"] is None

    traite = await client.post(f"{API}/echanges/{fil[0]['id']}/traiter", headers=auth)
    assert traite.status_code == 200
    assert traite.json()["traite_le"] is not None


# --- rapports ---------------------------------------------------------------


async def test_un_rapport_se_genere_sans_assistance(client, auth):
    """Une panne de fournisseur allonge le travail ; elle ne le bloque pas."""
    _, mandat_id = await monter_mandat(client, auth)
    await client.post(
        f"{API}/mandats/{mandat_id}/postes",
        json={"intitule": "Directeur", "pieces_requises": ["CV"]},
        headers=auth,
    )

    reponse = await client.post(
        f"{API}/mandats/{mandat_id}/rapports",
        json={"avec_assistance": False},
        headers=auth,
    )
    assert reponse.status_code == 201, reponse.text
    rapport = reponse.json()
    assert rapport["statut"] == "BROUILLON"
    assert [s["code"] for s in rapport["sections"]]
    # Les chiffres sont figés avec le rapport : il reste exportable à
    # l'identique quoi qu'il advienne des dossiers ensuite.
    assert rapport["donnees"]["mandat"]["client"] == "WAPP"


async def test_un_rapport_reprend_les_notes_des_dossiers(client, auth):
    """Les tableaux du rapport se calculent sur de vraies candidatures notées.

    Le test précédent porte sur un mandat vide, où rien n'est jamais lu dans
    une notation : il laissait passer une génération qui échouait dès qu'un
    dossier avait été noté.
    """
    _, poste_id = await monter_poste(client, auth)
    mandat_id = (await client.get(f"{API}/postes/{poste_id}", headers=auth)).json()[
        "mandat_id"
    ]
    cle = await publier(client, auth, poste_id)
    await client.post(
        f"{API}/public/avis/{cle}/candidater",
        data={
            "nom": "Kodjo",
            "prenom": "Amina",
            "email": "amina@example.com",
            "types_pieces": ["CV"],
        },
        files=[("fichiers", ("cv.pdf", PDF, "application/pdf"))],
    )

    rapport = await client.post(
        f"{API}/mandats/{mandat_id}/rapports",
        json={"avec_assistance": False},
        headers=auth,
    )
    assert rapport.status_code == 201, rapport.text
    poste = rapport.json()["donnees"]["postes"][0]
    assert poste["candidatures_recues"] == 1
    assert poste["classement"][0]["nom"] == "KODJO Amina"


async def test_une_note_saisie_a_la_main_reclasse_le_dossier(client, auth):
    """La catégorie remise au client suit la note qui a servi à classer.

    Qualifier sur le calcul afficherait un dossier à 28/30 étiqueté
    « partiellement qualifié » — incompréhensible, et repris tel quel dans le
    rapport livré.
    """
    _, poste_id = await monter_poste(client, auth)
    cle = await publier(client, auth, poste_id)
    depot = await client.post(
        f"{API}/public/avis/{cle}/candidater",
        data={
            "nom": "Kodjo",
            "prenom": "Amina",
            "email": "amina@example.com",
            "types_pieces": ["CV"],
        },
        files=[("fichiers", ("cv.pdf", PDF, "application/pdf"))],
    )
    candidature_id = depot.json()["candidature_id"]

    releve = await client.patch(
        f"{API}/candidatures/{candidature_id}/note",
        json={"note": 28, "motif": "Dossier exceptionnel, relu par la direction."},
        headers=auth,
    )
    assert releve.status_code == 200, releve.text
    assert releve.json()["qualification"] == "FORTEMENT_QUALIFIE"


async def test_un_rapport_valide_ne_se_modifie_plus(client, auth):
    _, mandat_id = await monter_mandat(client, auth)
    rapport = (
        await client.post(
            f"{API}/mandats/{mandat_id}/rapports",
            json={"avec_assistance": False},
            headers=auth,
        )
    ).json()

    valide = await client.post(f"{API}/rapports/{rapport['id']}/valider", headers=auth)
    assert valide.status_code == 200, valide.text

    refus = await client.put(
        f"{API}/rapports/{rapport['id']}",
        json={"titre": "Autre titre"},
        headers=auth,
    )
    assert refus.status_code == 409


async def test_un_rapport_s_exporte_dans_les_formats_attendus(client, auth):
    _, mandat_id = await monter_mandat(client, auth)
    rapport = (
        await client.post(
            f"{API}/mandats/{mandat_id}/rapports",
            json={"avec_assistance": False},
            headers=auth,
        )
    ).json()
    await client.put(
        f"{API}/rapports/{rapport['id']}",
        json={
            "sections": [
                {"code": "CONTEXTE", "titre": "Contexte", "contenu": "Un texte relu."}
            ]
        },
        headers=auth,
    )

    for format_ in ("docx", "pdf", "odt", "txt"):
        export = await client.get(
            f"{API}/rapports/{rapport['id']}/export?format={format_}", headers=auth
        )
        assert export.status_code == 200, format_
        assert len(export.content) > 100, format_


async def test_seul_un_rapport_valide_est_remis_au_client(client, auth):
    _, mandat_id = await monter_mandat(client, auth)
    rapport = (
        await client.post(
            f"{API}/mandats/{mandat_id}/rapports",
            json={"avec_assistance": False},
            headers=auth,
        )
    ).json()

    refus = await client.post(f"{API}/rapports/{rapport['id']}/partager", headers=auth)
    assert refus.status_code == 409

    await client.post(f"{API}/rapports/{rapport['id']}/valider", headers=auth)
    partage = await client.post(f"{API}/rapports/{rapport['id']}/partager", headers=auth)
    assert partage.status_code == 200

    jeton = await activer(client, auth, mandat_id)
    liste = (
        await client.get(
            f"{API}/espace-client/rapports",
            headers={"Authorization": f"Bearer {jeton}"},
        )
    ).json()
    assert len(liste) == 1


# --- envoi de courriels -----------------------------------------------------


async def test_l_apercu_rend_le_message_sans_rien_envoyer(client, auth):
    """Un courriel ne se rattrape pas : on montre avant d'expédier."""
    _, poste_id = await monter_poste(client, auth)
    cle = await publier(client, auth, poste_id)
    depot = await client.post(
        f"{API}/public/avis/{cle}/candidater",
        data={
            "nom": "Kodjo",
            "prenom": "Amina",
            "email": "amina@example.com",
            "types_pieces": ["CV"],
        },
        files=[("fichiers", ("cv.pdf", PDF, "application/pdf"))],
    )
    candidature_id = depot.json()["candidature_id"]

    apercu = await client.post(
        f"{API}/messagerie/apercu",
        json={
            "modele": "PRESELECTION_RETENU",
            "candidature_ids": [candidature_id],
            "valeurs": {"signature": "Kapi Consult"},
        },
        headers=auth,
    )
    assert apercu.status_code == 200, apercu.text
    message = apercu.json()[0]
    assert message["destinataire"] == "amina@example.com"
    assert "Directeur Général" in message["sujet"]
    assert "KODJO Amina" in message["corps"]

    # Aucune trace d'envoi : l'aperçu ne touche à rien.
    historique = (
        await client.get(f"{API}/candidatures/{candidature_id}/messages", headers=auth)
    ).json()
    assert historique == []


async def test_le_message_d_acces_client_ne_s_envoie_pas_a_un_candidat(client, auth):
    """Il porte un lien vers l'espace de suivi du mandat.

    L'expédier à un candidat lui ouvrirait le suivi du recrutement auquel il
    postule. Le modèle est donc marqué comme destiné au commanditaire, et
    l'écran des candidatures ne le propose pas.
    """
    candidat_seulement = (
        await client.get(f"{API}/messagerie/modeles?destinataire=CANDIDAT", headers=auth)
    ).json()
    assert all(m["destinataire"] == "CANDIDAT" for m in candidat_seulement)
    assert "ACCES_CLIENT" not in {m["code"] for m in candidat_seulement}

    refus = await client.post(
        f"{API}/messagerie/apercu",
        json={"modele": "ACCES_CLIENT", "candidature_ids": ["peu-importe"]},
        headers=auth,
    )
    assert refus.status_code == 422


async def test_envoyer_sans_serveur_configure_est_refuse_clairement(client, auth):
    """Mieux vaut un refus lisible qu'un envoi silencieusement perdu."""
    refus = await client.post(
        f"{API}/messagerie/envoyer",
        json={
            "modele": "NON_RETENU",
            "messages": [
                {
                    "candidature_id": "inexistante",
                    "destinataire": "a@example.com",
                    "sujet": "Objet",
                    "corps": "Corps",
                }
            ],
        },
        headers=auth,
    )
    assert refus.status_code == 409
    assert "Paramètres" in refus.json()["detail"]


# --- types de rapport --------------------------------------------------------


async def test_un_rapport_de_preselection_s_arrete_a_la_preselection(client, auth):
    """Les entretiens n'ont pas eu lieu : leurs sections n'ont rien à dire.

    La trame complète les produisait quand même, et il fallait supprimer à la
    main un « Classement final » vide avant d'envoyer le document.
    """
    # Un poste, sans quoi il n'y a ni grille ni effectifs à reproduire et le
    # contrôle ne porterait que sur des titres.
    mandat_id, _ = await monter_poste(client, auth)
    reponse = await client.post(
        f"{API}/mandats/{mandat_id}/rapports",
        json={"avec_assistance": False, "type_rapport": "PRESELECTION"},
        headers=auth,
    )
    assert reponse.status_code == 201, reponse.text
    rapport = reponse.json()
    codes = [s["code"] for s in rapport["sections"]]

    # Le tableau des préqualifiés est porté par « Liste des candidats
    # présélectionnés », comme dans le document remis : il n'a pas de section
    # à lui.
    assert "LISTE_PRESELECTIONNES" in codes
    liste = next(s for s in rapport["sections"] if s["code"] == "LISTE_PRESELECTIONNES")
    assert liste["tableaux"], "la section porte le tableau, pas seulement son titre"

    assert "ENTRETIENS_STRUCTURES" not in codes
    assert "RESULTATS_ENTRETIENS" not in codes
    assert rapport["type_rapport"] == "PRESELECTION"
    assert rapport["titre"].startswith("Rapport de présélection")


async def test_un_rapport_d_entretiens_ne_refait_pas_la_preselection(client, auth):
    mandat_id, _ = await monter_poste(client, auth)
    rapport = (
        await client.post(
            f"{API}/mandats/{mandat_id}/rapports",
            json={"avec_assistance": False, "type_rapport": "ENTRETIENS"},
            headers=auth,
        )
    ).json()
    codes = [s["code"] for s in rapport["sections"]]

    # La grille du jury figure dans le rapport : c'est elle que le client a
    # adoptée avant les auditions, et les notes ne se relisent pas sans elle.
    # L'ordre est celui du document remis.
    assert codes == [
        "INTRODUCTION",
        "ENTRETIENS_STRUCTURES",
        "GUIDE_ENTRETIEN",
        "JURY",
        "RESULTATS_ENTRETIENS",
    ]
    assert rapport["titre"].startswith("Rapport des entretiens")
    # Et elle est bien remplie, pas seulement annoncée.
    grille = next(s for s in rapport["sections"] if s["code"] == "GUIDE_ENTRETIEN")
    assert grille["tableaux"], "la grille est reproduite, pas seulement citée"


async def test_le_rapport_final_reste_la_trame_complete(client, auth):
    """Le défaut ne change pas : un appel sans type produit ce qu'il produisait."""
    from app.services import rapports as service

    _, mandat_id = await monter_mandat(client, auth)
    rapport = (
        await client.post(
            f"{API}/mandats/{mandat_id}/rapports",
            json={"avec_assistance": False},
            headers=auth,
        )
    ).json()

    assert [s["code"] for s in rapport["sections"]] == [s.code for s in service.TRAME]
    assert rapport["type_rapport"] == "FINAL"


async def test_une_trame_imposee_par_le_client_prime_sur_le_type(client, auth):
    """C'est l'objet même d'un modèle : le client impose son plan."""
    from app.models import ModeleDocument

    _, mandat_id = await monter_mandat(client, auth)

    # Déposé directement : l'API de dépôt attend le fichier du client et en
    # déduit la trame, ce qui n'est pas ce qu'on vérifie ici.
    async with SessionLocal() as db:
        modele = ModeleDocument(
            mandat_id=mandat_id,
            libelle="Trame bailleur",
            usage="RAPPORT",
            structure={"sections": [{"code": "RESUME", "titre": "Résumé exécutif"}]},
        )
        db.add(modele)
        await db.commit()
        modele_id = modele.id

    rapport = (
        await client.post(
            f"{API}/mandats/{mandat_id}/rapports",
            json={
                "avec_assistance": False,
                "type_rapport": "PRESELECTION",
                "modele_id": modele_id,
            },
            headers=auth,
        )
    ).json()
    assert [s["code"] for s in rapport["sections"]] == ["RESUME"]
