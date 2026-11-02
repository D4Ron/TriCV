"""Le type des pièces reçues : d'après le nom, puis le contenu.

Relevé en production sur un dossier reçu par courriel : certificat de travail,
passeport, carte d'identité et certificat de langue rangés en « CV » ; une
attestation de stage et une attestation de participation en « copie des
diplômes ». Les noms ci-dessous reprennent la forme de ces fichiers, avec des
noms de personnes fictifs.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.domain.referentiel import PieceDossier as P
from app.services import courriel, lots

pytestmark = pytest.mark.anyio

API = "/api/v1"


@pytest.mark.parametrize(
    ("nom", "attendu"),
    [
        ("Certificat de travail ACME.pdf", (P.ATTESTATIONS_TRAVAIL.value, None)),
        ("ATTESTATION_de_STAGE2026.pdf", (P.ATTESTATIONS_TRAVAIL.value, None)),
        ("Lettre de motivation DOSSOU.pdf", (P.LETTRE_MOTIVATION.value, None)),
        ("Passport Afi DOSSOU.pdf", (P.PASSEPORT.value, None)),
        ("Carte d'identité 26-08-2026 14.21.pdf", (P.PIECE_IDENTITE.value, None)),
        ("certificat de langue DOSSOU afi.pdf", (P.AUTRE.value, "Certificat de langue")),
        ("Attestation de Master pro QSE DOSSOU Afi.pdf", (P.COPIE_DIPLOMES.value, None)),
        ("attestation de participation DOSSOU AFI.pdf", (P.AUTRE.value, "Attestation de formation")),
        ("CV DOSSOU AFI.pdf", (P.CV.value, None)),
        ("scan001.pdf", (None, None)),
    ],
)
def test_le_nom_dit_le_type(nom, attendu):
    assert lots.classer(nom) == attendu


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [
        (
            "CURRICULUM VITAE\nExpériences professionnelles\n2020 - 2024 Comptable\n"
            "Compétences\nExcel, SAGE\nLangues\nFrançais, anglais",
            P.CV.value,
        ),
        (
            "ATTESTATION\nNous soussignés, la société X, certifions que Mme Y a travaillé "
            "en qualité de comptable du 1er mars 2021 au 30 juin 2024.",
            P.ATTESTATIONS_TRAVAIL.value,
        ),
        (
            "RÉPUBLIQUE TOGOLAISE PASSEPORT / PASSPORT Type P Nationalité TOGOLAISE "
            "P<TGODOSSOU<<AFI<<<<<<<<<<<<<<<<<<",
            P.PASSEPORT.value,
        ),
        (
            "Madame, Monsieur,\nObjet : candidature au poste de comptable\n"
            "J'ai l'honneur de vous soumettre ma candidature.",
            P.LETTRE_MOTIVATION.value,
        ),
        ("", None),
    ],
)
def test_le_contenu_dit_le_type_quand_le_nom_se_tait(texte, attendu):
    assert lots.type_par_contenu(texte) == attendu


async def test_un_envoi_sans_cv_reconnu_prend_sa_premiere_piece_inconnue_pour_cv(monkeypatch):
    """Les inconnues suivantes deviennent des « autres documents », pas des CV."""

    async def extraire(donnees, type_mime, nom):
        raise courriel.extraction.UnreadableDocument("scan")

    monkeypatch.setattr(courriel.extraction, "extract", extraire)
    pieces = [
        (courriel.PieceJointe(nom="scan001.pdf", donnees=b"a"), "application/pdf"),
        (courriel.PieceJointe(nom="scan002.pdf", donnees=b"b"), "application/pdf"),
        (courriel.PieceJointe(nom="Passport X.pdf", donnees=b"c"), "application/pdf"),
    ]
    types = await courriel._classer_pieces(pieces)
    assert types == [
        (P.CV.value, None),
        (P.AUTRE.value, "scan002"),
        (P.PASSEPORT.value, None),
    ]


async def test_un_envoi_avec_cv_ne_fait_pas_de_cv_d_une_inconnue(monkeypatch):
    async def extraire(donnees, type_mime, nom):
        raise courriel.extraction.UnreadableDocument("scan")

    monkeypatch.setattr(courriel.extraction, "extract", extraire)
    pieces = [
        (courriel.PieceJointe(nom="CV X.pdf", donnees=b"a"), "application/pdf"),
        (courriel.PieceJointe(nom="scan001.pdf", donnees=b"b"), "application/pdf"),
    ]
    types = await courriel._classer_pieces(pieces)
    assert types[1] == (P.AUTRE.value, "scan001")


def test_la_migration_ne_touche_que_ce_que_l_ancienne_regle_a_produit():
    chemin = Path(__file__).parents[1] / "alembic" / "versions" / "0008_pieces_reclassees.py"
    spec = importlib.util.spec_from_file_location("migration_0008", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # L'ancienne règle rangeait le passeport en CV : la migration le reprend.
    assert module.ancien_type("Passport X.pdf") == P.CV.value
    assert module.nouveau_type("Passport X.pdf")[0] == P.PASSEPORT.value
    # Une attestation de stage était une « copie des diplômes ».
    assert module.ancien_type("ATTESTATION_de_STAGE.pdf") == P.COPIE_DIPLOMES.value
    assert module.nouveau_type("ATTESTATION_de_STAGE.pdf")[0] == P.ATTESTATIONS_TRAVAIL.value


async def test_une_piece_mal_classee_se_corrige_a_la_main(client, auth):
    from app.db import SessionLocal

    poste_id = await _poste(client, auth)
    reponse = await client.post(
        f"{API}/postes/{poste_id}/candidatures/depot-multiple",
        data={"depouiller_aussitot": "false"},
        files=[("fichiers", ("KODJO_Amina_CV.pdf", _pdf(b"a"), "application/pdf"))],
        headers=auth,
    )
    candidature_id = reponse.json()["resultats"][0]["candidature_id"]
    dossier = (await client.get(f"{API}/candidatures/{candidature_id}", headers=auth)).json()
    piece_id = dossier["pieces"][0]["id"]

    corrige = await client.patch(
        f"{API}/candidatures/{candidature_id}/pieces/{piece_id}",
        json={"type_piece": "PASSEPORT"},
        headers=auth,
    )
    assert corrige.status_code == 200, corrige.text
    assert corrige.json()["pieces"][0]["type_piece"] == "PASSEPORT"

    refus = await client.patch(
        f"{API}/candidatures/{candidature_id}/pieces/{piece_id}",
        json={"type_piece": "N_IMPORTE_QUOI"},
        headers=auth,
    )
    assert refus.status_code == 422

    async with SessionLocal() as db:
        from sqlalchemy import select

        from app.models import AuditLog

        actions = set((await db.execute(select(AuditLog.action))).scalars())
    assert "candidature.piece_retypee" in actions


def _pdf(marque: bytes) -> bytes:
    return b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n" + marque


async def _poste(client, auth) -> str:
    client_id = (await client.post(f"{API}/clients", json={"nom": "Dogta"}, headers=auth)).json()["id"]
    mandat_id = (
        await client.post(f"{API}/mandats", json={"client_id": client_id, "intitule": "M"}, headers=auth)
    ).json()["id"]
    return (
        await client.post(
            f"{API}/mandats/{mandat_id}/postes",
            json={"intitule": "Directeur", "pieces_requises": ["CV"]},
            headers=auth,
        )
    ).json()["id"]
