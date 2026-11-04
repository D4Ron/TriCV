"""La file des lectures : elle attend le quota, reprend, et ne casse rien."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import fitz
import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.domain.referentiel import PieceDossier as P
from app.llm.base import LLMConfigError, LLMQuotaError
from app.models.base import utcnow
from app.models.enums import Provenance, SourceCandidature
from app.models.recrutement import (
    Avis,
    Candidat,
    Candidature,
    Client,
    Mandat,
    PieceCandidature,
    Poste,
)
from app.models.travail import (
    ATTENTE,
    DECOUPAGE,
    ECHEC,
    EN_COURS,
    FAIT,
    LECTURE_IA,
    LECTURE_LOCALE,
    Travail,
)
from app.services import classement_ia, storage, travaux
from app.services.preselection import charger_candidature

pytestmark = pytest.mark.anyio

API = "/api/v1"
CV = (
    "Afi DOSSOU\nExpérience professionnelle\n2018 - 2023 Responsable logistique, raffinerie de Lomé\n"
    "- suivi des expéditions, des dépôts et des équipes de quai, sur deux sites et trois équipes\n"
    "- négociation des contrats de transport et pilotage du budget annuel des opérations\n"
    "Formation\n2014 Master en logistique, Université de Lomé\nCompétences\nExcel\nLangues\nFrançais"
)
ATTESTATION = (
    "ATTESTATION DE TRAVAIL\nJe soussigné, directeur de la société Togo Transit, atteste que "
    "Mme Afi DOSSOU a travaillé en qualité de chef de quai du 1er mars 2010 au 30 juin 2013."
)


async def monter(db, pieces=(), nb=1) -> tuple[str, list[str]]:
    client = Client(nom="Client fictif")
    db.add(client)
    await db.flush()
    mandat = Mandat(client_id=client.id, intitule="Mandat")
    db.add(mandat)
    await db.flush()
    poste = Poste(
        mandat_id=mandat.id,
        intitule="Directeur logistique",
        niveau_min=3,
        domaines_acceptes=["logistique"],
        annees_experience_min=5,
        annees_experience_specifique_min=2,
        domaines_experience=["Pétrole & Gaz"],
        pieces_requises=[P.CV.value],
    )
    db.add(poste)
    await db.flush()
    db.add(Avis(poste_id=poste.id, reference="AVIS", date_cloture=date(2026, 12, 31)))
    ids = []
    for n in range(nb):
        candidat = Candidat(
            nom=f"DOSSOU{n}", prenom="Afi", email=f"afi{n}@example.tg", provenance=Provenance.EXTRAIT_IA
        )
        db.add(candidat)
        await db.flush()
        candidature = Candidature(
            poste_id=poste.id,
            candidat_id=candidat.id,
            source=SourceCandidature.EMAIL,
            recue_le=datetime(2026, 7, 15, 9, 0),
        )
        db.add(candidature)
        await db.flush()
        ids.append(candidature.id)
        for type_piece, nom, texte in pieces:
            db.add(
                PieceCandidature(
                    candidature_id=candidature.id,
                    type_piece=type_piece,
                    nom_fichier=nom,
                    texte_extrait=texte,
                    chemin_stockage=await storage.get_storage().save(
                        f"tests/{candidature.id}-{nom}", b"%PDF-1.4\n" + b"0" * 400
                    ),
                    type_mime="application/pdf",
                )
            )
    await db.commit()
    return poste.id, ids


class Modele:
    """Un fournisseur qui répond ce qu'on lui dit, ou refuse."""

    def __init__(self, panne=None, classement=None):
        self.panne = panne
        self.classement = classement or {}
        self.envois: list[str] = []
        self.appels = 0

    async def extraire_dossier(self, texte, domaines=()):
        from app.llm.base import DossierExtrait

        self.appels += 1
        if self.panne:
            raise self.panne
        return DossierExtrait()

    async def repondre_json(self, consigne, contexte, systeme=""):
        self.envois.append(contexte)
        if self.panne:
            raise self.panne
        return self.classement


@pytest.fixture
def modele(monkeypatch):
    def poser(**k):
        stub = Modele(**k)
        monkeypatch.setattr("app.services.depouillement.get_provider", lambda: stub)
        monkeypatch.setattr("app.services.classement_ia.get_provider", lambda: stub)
        return stub

    return poser


async def lignes():
    async with SessionLocal() as db:
        return list((await db.execute(select(Travail).order_by(Travail.created_at))).scalars())


async def test_mettre_en_file_deux_fois_ne_double_rien():
    async with SessionLocal() as db:
        poste, ids = await monter(db, nb=2)
        assert await travaux.ajouter(db, [(i, poste) for i in ids], LECTURE_LOCALE) == 2
        assert await travaux.ajouter(db, [(i, poste) for i in ids], LECTURE_LOCALE) == 0
        await db.commit()


async def test_une_lecture_locale_se_fait_et_se_note():
    async with SessionLocal() as db:
        poste, ids = await monter(db, [(P.CV.value, "cv.pdf", CV)])
        await travaux.ajouter(db, [(ids[0], poste)], LECTURE_LOCALE)
        await db.commit()

    assert await travaux.traiter_un() == LECTURE_LOCALE
    assert (await lignes())[0].etat == FAIT
    assert await travaux.traiter_un() is None

    async with SessionLocal() as db:
        c = await charger_candidature(db, ids[0])
        assert c.candidat.experiences[0].domaines == ["petrole & gaz", "logistique"]


async def test_l_attestation_rejoint_le_parcours_par_la_file():
    async with SessionLocal() as db:
        poste, ids = await monter(
            db,
            [(P.CV.value, "cv.pdf", CV), (P.ATTESTATIONS_TRAVAIL.value, "att.pdf", ATTESTATION)],
        )
        await travaux.ajouter(db, [(ids[0], poste)], LECTURE_LOCALE)
        await db.commit()

    await travaux.traiter_un()

    async with SessionLocal() as db:
        c = await charger_candidature(db, ids[0])
        postes = sorted(e.poste for e in c.candidat.experiences)
    assert "chef de quai" in postes
    assert len(postes) == 2


async def test_un_quota_epuise_attend_sans_echouer_et_retient_toute_la_file(modele):
    stub = modele(panne=LLMQuotaError("plus de quota"))
    async with SessionLocal() as db:
        poste, ids = await monter(db, [(P.CV.value, "cv.pdf", CV)], nb=3)
        await travaux.ajouter(db, [(i, poste) for i in ids], LECTURE_IA)
        await db.commit()

    assert await travaux.traiter_un() == LECTURE_IA
    # Les deux autres attendent aussi : on ne frappe pas à chaque dossier.
    assert await travaux.traiter_un() is None
    assert stub.appels == 1

    toutes = await lignes()
    assert {t.etat for t in toutes} == {ATTENTE}
    assert all(t.pas_avant and t.pas_avant > utcnow() for t in toutes)

    async with SessionLocal() as db:
        etat = await travaux.etat_du_poste(db, poste)
    assert etat["en_attente"] == 3
    assert etat["reprise_le"]


async def test_le_quota_revenu_tout_reprend(modele):
    modele(panne=LLMQuotaError("plus de quota"))
    async with SessionLocal() as db:
        poste, ids = await monter(db, [(P.CV.value, "cv.pdf", CV)])
        await travaux.ajouter(db, [(ids[0], poste)], LECTURE_IA)
        await db.commit()
    await travaux.traiter_un()

    modele()
    async with SessionLocal() as db:
        travail = (await db.execute(select(Travail))).scalars().one()
        travail.pas_avant = utcnow() - timedelta(minutes=1)
        await db.commit()

    assert await travaux.traiter_un() == LECTURE_IA
    assert (await lignes())[0].etat == FAIT


async def test_quatre_heures_sans_quota_finissent_en_echec(modele):
    modele(panne=LLMQuotaError("plus de quota"))
    async with SessionLocal() as db:
        poste, ids = await monter(db, [(P.CV.value, "cv.pdf", CV)])
        await travaux.ajouter(db, [(ids[0], poste)], LECTURE_IA)
        await db.commit()
        travail = (await db.execute(select(Travail))).scalars().one()
        travail.essais = travaux.ESSAIS_MAX - 1
        await db.commit()

    await travaux.traiter_un()
    assert (await lignes())[0].etat == ECHEC


async def test_une_cle_refusee_echoue_au_lieu_d_attendre(modele):
    modele(panne=LLMConfigError("clé refusée"))
    async with SessionLocal() as db:
        poste, ids = await monter(db, [(P.CV.value, "cv.pdf", CV)])
        await travaux.ajouter(db, [(ids[0], poste)], LECTURE_IA)
        await db.commit()

    await travaux.traiter_un()
    travail = (await lignes())[0]
    assert travail.etat == ECHEC
    assert "clé refusée" in travail.erreur


async def test_un_dossier_en_erreur_n_arrete_pas_la_file(monkeypatch):
    async with SessionLocal() as db:
        poste, ids = await monter(db, [(P.CV.value, "cv.pdf", CV)], nb=2)
        await travaux.ajouter(db, [(i, poste) for i in ids], LECTURE_LOCALE)
        await db.commit()

    vrai = travaux.depouillement.depouiller
    appels = []

    async def une_fois_sur_deux(db, candidature, **k):
        appels.append(candidature.id)
        if len(appels) == 1:
            raise ValueError("dossier abîmé")
        return await vrai(db, candidature, **k)

    monkeypatch.setattr(travaux.depouillement, "depouiller", une_fois_sur_deux)
    await travaux.traiter_un()
    await travaux.traiter_un()

    assert sorted(t.etat for t in await lignes()) == sorted([ECHEC, FAIT])


async def test_ce_qui_etait_en_cours_reprend_au_demarrage():
    async with SessionLocal() as db:
        poste, ids = await monter(db)
        await travaux.ajouter(db, [(ids[0], poste)], LECTURE_LOCALE)
        travail = (await db.execute(select(Travail))).scalars().one()
        travail.etat = EN_COURS
        await db.commit()

    await travaux.reprendre()
    assert (await lignes())[0].etat == ATTENTE


def pdf(*pages: str) -> bytes:
    doc = fitz.open()
    for texte in pages:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(40, 40, 555, 800), texte, fontsize=11)
    return doc.tobytes()


async def test_un_dossier_fusionne_du_formulaire_est_decoupe():
    async with SessionLocal() as db:
        poste, ids = await monter(db)
        donnees = pdf(CV, ATTESTATION)
        db.add(
            PieceCandidature(
                candidature_id=ids[0],
                type_piece=P.CV.value,
                nom_fichier="dossier.pdf",
                chemin_stockage=await storage.get_storage().save("tests/f.pdf", donnees),
                type_mime="application/pdf",
            )
        )
        await travaux.ajouter(db, [(ids[0], poste)], DECOUPAGE)
        await db.commit()

    await travaux.traiter_un()

    async with SessionLocal() as db:
        c = await charger_candidature(db, ids[0])
        assert sorted(p.type_piece for p in c.pieces) == sorted(
            [P.CV.value, P.ATTESTATIONS_TRAVAIL.value]
        )


async def test_le_meme_fichier_dans_deux_champs_ne_double_pas_ses_pieces():
    async with SessionLocal() as db:
        poste, ids = await monter(db)
        donnees = pdf(CV, ATTESTATION)
        for type_piece in (P.CV.value, P.ATTESTATIONS_TRAVAIL.value):
            db.add(
                PieceCandidature(
                    candidature_id=ids[0],
                    type_piece=type_piece,
                    nom_fichier="dossier.pdf",
                    chemin_stockage=await storage.get_storage().save(f"tests/{type_piece}.pdf", donnees),
                    type_mime="application/pdf",
                )
            )
        await travaux.ajouter(db, [(ids[0], poste)], DECOUPAGE)
        await db.commit()

    await travaux.traiter_un()

    async with SessionLocal() as db:
        c = await charger_candidature(db, ids[0])
        assert len(c.pieces) == 2


RAPPORT = "Rapport de stage sur la modernisation du terminal à conteneurs de la zone franche de Lomé."


async def test_l_ia_ne_voit_que_l_incertain_et_range(modele):
    stub = modele(
        classement={"pieces": [{"n": 1, "type": "AUTRE", "intitule": "Rapport de stage"}]}
    )
    async with SessionLocal() as db:
        poste, ids = await monter(
            db,
            [
                (P.CV.value, "cv.pdf", CV),
                (P.AUTRE.value, "scan-DOSSOU.pdf", RAPPORT + " Rédigé par Afi DOSSOU0."),
            ],
        )
        await travaux.ajouter(db, [(ids[0], poste)], LECTURE_IA)
        await db.commit()

    await travaux.traiter_un()

    envoye = stub.envois[0]
    assert "modernisation du terminal" in envoye
    assert "Responsable logistique" not in envoye
    assert "DOSSOU" not in envoye

    async with SessionLocal() as db:
        c = await charger_candidature(db, ids[0])
        autre = next(p for p in c.pieces if p.type_piece == P.AUTRE.value)
    assert autre.intitule_libre == "Rapport de stage"
    assert autre.type_source == "ia"


async def test_ce_qui_ressemble_a_de_l_etat_civil_ne_part_pas(modele):
    stub = modele()
    async with SessionLocal() as db:
        poste, ids = await monter(
            db,
            [
                (P.CV.value, "cv.pdf", CV),
                (P.AUTRE.value, "scan.pdf", "Né le 3 mars 1980 à Lomé, nationalité togolaise, profession cadre."),
            ],
        )
        await travaux.ajouter(db, [(ids[0], poste)], LECTURE_IA)
        await db.commit()

    await travaux.traiter_un()
    assert stub.envois == []


async def test_une_correction_humaine_n_est_jamais_reprise(modele):
    stub = modele(classement={"pieces": [{"n": 1, "type": "CV"}]})
    async with SessionLocal() as db:
        poste, ids = await monter(db, [(P.CV.value, "cv.pdf", CV), (P.AUTRE.value, "scan.pdf", RAPPORT)])
        piece = next(
            p for p in (await charger_candidature(db, ids[0])).pieces if p.type_piece == P.AUTRE.value
        )
        piece.type_source = "humain"
        await travaux.ajouter(db, [(ids[0], poste)], LECTURE_IA)
        await db.commit()

    await travaux.traiter_un()
    assert stub.envois == []


async def test_un_type_invente_par_le_modele_est_ignore(modele):
    modele(classement={"pieces": [{"n": 1, "type": "PIECE_IDENTITE"}, {"n": 9, "type": "CV"}, "n'importe quoi"]})
    async with SessionLocal() as db:
        poste, ids = await monter(db, [(P.CV.value, "cv.pdf", CV), (P.AUTRE.value, "scan.pdf", RAPPORT)])
        await travaux.ajouter(db, [(ids[0], poste)], LECTURE_IA)
        await db.commit()

    await travaux.traiter_un()
    async with SessionLocal() as db:
        c = await charger_candidature(db, ids[0])
    assert sorted(p.type_piece for p in c.pieces) == sorted([P.CV.value, P.AUTRE.value])


async def test_l_api_lance_suit_et_annule(client, auth):
    async with SessionLocal() as db:
        poste, _ = await monter(db, [(P.CV.value, "cv.pdf", CV)], nb=2)

    reponse = await client.post(f"{API}/postes/{poste}/lectures", json={"ia": False}, headers=auth)
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["ajoutes"] == 2

    assert (await client.get(f"{API}/postes/{poste}/lectures", headers=auth)).json()["en_attente"] == 2
    annule = await client.delete(f"{API}/postes/{poste}/lectures", headers=auth)
    assert annule.json()["retires"] == 2


async def test_un_dossier_confirme_ne_se_relit_pas(client, auth):
    async with SessionLocal() as db:
        poste, ids = await monter(db, [(P.CV.value, "cv.pdf", CV)], nb=2)
        c = await charger_candidature(db, ids[0])
        c.candidat.verifie_le = utcnow()
        await db.commit()

    reponse = await client.post(f"{API}/postes/{poste}/lectures", json={"ia": True}, headers=auth)
    assert reponse.json()["ajoutes"] == 1


async def test_le_lexique_relit_les_dossiers_et_se_propose(client, auth, modele):
    async with SessionLocal() as db:
        poste, _ = await monter(db, [(P.CV.value, "cv.pdf", CV)])

    reponse = await client.patch(
        f"{API}/postes/{poste}",
        json={"lexique": {"Pétrole & Gaz": ["Compagnie du Mono"]}},
        headers=auth,
    )
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["lexique"] == {"Pétrole & Gaz": ["Compagnie du Mono"]}
    assert "raffinerie" in corps["lexique_connu"]["Pétrole & Gaz"] or corps["lexique_connu"]["Pétrole & Gaz"]
    assert (await lignes())[0].nature == LECTURE_LOCALE

    stub = modele(classement={"lexique": {"Pétrole & Gaz": ["GPL", " ", "dépôt"], "autre": ["x"]}})
    monkeypatched = "app.api.travaux.get_provider"
    import app.api.travaux as api_travaux

    api_travaux.get_provider = lambda: stub
    try:
        propose = await client.post(f"{API}/postes/{poste}/lexique/proposer", headers=auth)
    finally:
        from app.llm.factory import get_provider

        api_travaux.get_provider = get_provider
    assert monkeypatched
    assert propose.json()["lexique"]["Pétrole & Gaz"] == ["GPL", "dépôt"]
    # Rien du candidat ne part : seulement le poste.
    assert "DOSSOU" not in stub.envois[0]
    assert "Directeur logistique" in stub.envois[0]


async def test_un_fichier_disparu_ne_fait_pas_tomber_le_decoupage(client, auth):
    async with SessionLocal() as db:
        poste, ids = await monter(db)
        db.add(
            PieceCandidature(
                candidature_id=ids[0],
                type_piece=P.CV.value,
                nom_fichier="dossier.pdf",
                chemin_stockage="tests/disparu.pdf",
                type_mime="application/pdf",
            )
        )
        await db.commit()
        c = await charger_candidature(db, ids[0])
        piece = c.pieces[0].id
        await travaux.ajouter(db, [(ids[0], poste)], DECOUPAGE)
        await db.commit()

    reponse = await client.post(f"{API}/candidatures/{ids[0]}/pieces/{piece}/decouper", headers=auth)
    assert reponse.status_code == 410

    await travaux.traiter_un()
    assert (await lignes())[0].etat == FAIT
