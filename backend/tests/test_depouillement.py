from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.domain.referentiel import PieceDossier
from app.llm import factory
from app.llm.base import DossierExtrait
from app.models import (
    Avis,
    Candidat,
    Candidature,
    Client,
    DiplomeCandidat,
    ExperienceCandidat,
    Mandat,
    PieceCandidature,
    Poste,
    Provenance,
)
from app.models.enums import SourceCandidature, StatutCandidature
from app.services import depouillement, storage

pytestmark = pytest.mark.anyio

CV_TEXTE = """
Tchodie-Magla Ronald
ron4ever4@gmail.com — 98032961
Né le 12/05/1990 — Nationalité : Togolaise — Sexe : Masculin
Lomé, Tokoin

FORMATION
2014 — Master en gestion hôtelière, Université de Lomé

EXPÉRIENCE
2015 - 2026 : Directeur adjoint, Hôtel du 2 Février, Lomé, Togo
Encadrement des équipes, gestion budgétaire, suivi de la qualité de service.
Pilotage de la restauration et des achats sur l'ensemble des points de vente.

LANGUES
Français, Anglais
"""


class FournisseurExtraction:
    """Renvoie un parcours fixe et retient le texte reçu.

    `texte_recu` est ce que la vérification de confidentialité inspecte : il
    doit être expurgé avant d'arriver ici.
    """

    name = "stub-extraction"

    def __init__(self, dossier: DossierExtrait | None = None) -> None:
        self.texte_recu: str | None = None
        self.dossier = dossier or DossierExtrait.model_validate(
            {
                "diplomes": [
                    {
                        "intitule": "Master en gestion hôtelière",
                        "niveau": 5,
                        "domaine": "gestion hoteliere",
                        "etablissement": "Université de Lomé",
                        "annee": 2014,
                    }
                ],
                "experiences": [
                    {
                        "poste": "Directeur adjoint",
                        "employeur": "Hôtel du 2 Février",
                        "debut": "2015-01",
                        "fin": None,
                        "domaines": ["gestion hoteliere"],
                        "pays": "Togo",
                    }
                ],
                "langues": ["français", "anglais"],
                "certifications": [],
            }
        )

    async def extraire_dossier(self, texte: str) -> DossierExtrait:
        self.texte_recu = texte
        return self.dossier

    async def analyze_cv(self, *a, **k):  # pragma: no cover - non utilisé
        raise NotImplementedError

    async def structure_fiche(self, *a, **k):  # pragma: no cover - non utilisé
        raise NotImplementedError


@pytest.fixture
def fournisseur(monkeypatch) -> FournisseurExtraction:
    stub = FournisseurExtraction()
    monkeypatch.setattr(factory, "get_provider", lambda: stub)
    monkeypatch.setattr("app.services.depouillement.get_provider", lambda: stub)
    return stub


async def monter_dossier(db, *, avec_piece: bool = True, texte: str = CV_TEXTE) -> Candidature:
    client = Client(nom="TRANSCO CLSG")
    db.add(client)
    await db.flush()
    mandat = Mandat(client_id=client.id, intitule="Direction")
    db.add(mandat)
    await db.flush()
    poste = Poste(
        mandat_id=mandat.id,
        intitule="Directeur Général",
        niveau_min=4,
        domaines_acceptes=["gestion hoteliere"],
        annees_experience_min=5,
        annees_experience_specifique_min=3,
        domaines_experience=["gestion hoteliere"],
        pieces_requises=[PieceDossier.CV.value],
    )
    db.add(poste)
    await db.flush()
    db.add(Avis(poste_id=poste.id, reference="AVIS-1", date_cloture=date(2026, 7, 31)))

    candidat = Candidat(
        nom="Tchodie-Magla",
        prenom="Ronald",
        email="ron4ever4@gmail.com",
        provenance=Provenance.EXTRAIT_IA,
    )
    db.add(candidat)
    await db.flush()

    candidature = Candidature(
        poste_id=poste.id,
        candidat_id=candidat.id,
        source=SourceCandidature.EMAIL,
        message_id="<x@y>",
        # Avant la clôture : sans quoi HORS_DELAI, qui est un motif factuel,
        # éliminerait le dossier quoi qu'en dise le dépouillement.
        recue_le=datetime(2026, 7, 15, 9, 0),
    )
    db.add(candidature)
    await db.flush()

    if avec_piece:
        # Un vrai PDF n'est pas nécessaire : le texte est injecté au niveau de
        # l'extraction, ce qui teste le dépouillement et non le lecteur PDF.
        cle = await storage.get_storage().save("tests/cv.pdf", b"%PDF-1.4\n" + b"0" * 400)
        db.add(
            PieceCandidature(
                candidature_id=candidature.id,
                type_piece=PieceDossier.CV.value,
                nom_fichier="cv.pdf",
                chemin_stockage=cle,
                type_mime="application/pdf",
            )
        )
    await db.flush()

    from app.services.preselection import charger_candidature

    return await charger_candidature(db, candidature.id)


@pytest.fixture
def texte_pdf(monkeypatch):
    """Court-circuite le lecteur PDF : on teste le dépouillement, pas fitz."""
    from app.services import extraction

    async def faux_extract(donnees, mime, nom=""):
        return extraction.ExtractedDocument(
            text=CV_TEXTE, page_count=1, mime_type="application/pdf"
        )

    monkeypatch.setattr(extraction, "extract", faux_extract)
    return CV_TEXTE


async def test_le_modele_ne_recoit_jamais_l_identite(fournisseur, texte_pdf):
    """La garantie centrale : rien d'identifiant ne sort de la machine."""
    async with SessionLocal() as db:
        candidature = await monter_dossier(db)
        await depouillement.depouiller(db, candidature)
        await db.commit()

        envoye = fournisseur.texte_recu
        assert envoye is not None
        for fuite in (
            "Tchodie-Magla",
            "Ronald",
            "ron4ever4@gmail.com",
            "98032961",
            "12/05/1990",
            "Togolaise",
        ):
            assert fuite not in envoye, f"fuite dans le texte envoyé : {fuite}"

        # Le parcours, lui, doit bien être présent : sinon il n'y a rien à lire.
        assert "Hôtel du 2 Février" in envoye or "hôtel" in envoye.lower()


async def test_le_parcours_extrait_est_persiste(fournisseur, texte_pdf):
    async with SessionLocal() as db:
        candidature = await monter_dossier(db)
        resultat = await depouillement.depouiller(db, candidature)
        await db.commit()

        assert resultat.diplomes == 1
        assert resultat.experiences == 1

        diplome = (await db.execute(select(DiplomeCandidat))).scalar_one()
        assert diplome.niveau == 5
        assert diplome.domaine == "gestion hoteliere"
        assert diplome.provenance is Provenance.EXTRAIT_IA

        experience = (await db.execute(select(ExperienceCandidat))).scalar_one()
        assert experience.debut == date(2015, 1, 1)
        assert experience.fin is None
        assert experience.provenance is Provenance.EXTRAIT_IA


async def test_un_dossier_extrait_ne_rejoint_pas_la_preselection_sans_relecture(
    fournisseur, texte_pdf
):
    """Le garde-fou joue dans les deux sens.

    Ce dossier ne déclenche aucun motif et dépasse le seuil : il irait donc
    droit dans la grille remise au client. Mais son parcours n'a été que
    proposé, pas confirmé — un diplôme inventé y passerait inaperçu. Il attend
    donc une relecture, comme s'il avait été éliminé à tort.
    """
    async with SessionLocal() as db:
        candidature = await monter_dossier(db)
        await depouillement.depouiller(db, candidature)
        await db.commit()

        from app.services.preselection import charger_candidature

        rechargee = await charger_candidature(db, candidature.id)
        assert rechargee.eliminations == []
        assert rechargee.notation.atteint_le_seuil is True
        assert rechargee.statut is StatutCandidature.A_VERIFIER


async def test_la_confirmation_humaine_debloque_la_preselection(fournisseur, texte_pdf):
    async with SessionLocal() as db:
        candidature = await monter_dossier(db)
        await depouillement.depouiller(db, candidature)
        await db.flush()

        from app.services.preselection import charger_candidature

        rechargee = await charger_candidature(db, candidature.id)
        rechargee.candidat.provenance = Provenance.VERIFIE_RH
        for diplome in rechargee.candidat.diplomes:
            diplome.provenance = Provenance.VERIFIE_RH
        for experience in rechargee.candidat.experiences:
            experience.provenance = Provenance.VERIFIE_RH
        await db.flush()

        from app.services.preselection import evaluer_candidature

        await evaluer_candidature(db, await charger_candidature(db, candidature.id))
        await db.commit()

        finale = (await db.execute(select(Candidature))).scalar_one()
        assert finale.statut is StatutCandidature.PRESELECTIONNEE


async def test_les_donnees_sensibles_sont_detectees_localement(fournisseur, texte_pdf):
    """Date de naissance et nationalité viennent de la détection locale,
    jamais du modèle."""
    async with SessionLocal() as db:
        candidature = await monter_dossier(db)
        resultat = await depouillement.depouiller(db, candidature)
        await db.commit()

        candidat = (await db.execute(select(Candidat))).scalar_one()
        assert "date_of_birth" in resultat.demographiques
        assert candidat.date_naissance == date(1990, 5, 12)
        assert candidat.nationalites == ["Togolaise"]


def test_lecture_des_dates_a_la_francaise():
    """Les CV d'ici écrivent le jour en premier."""
    assert depouillement._date_francaise("03/09/1984") == date(1984, 9, 3)
    assert depouillement._date_francaise("3-9-1984") == date(1984, 9, 3)
    assert depouillement._date_francaise("1984-09-03") == date(1984, 9, 3)
    assert depouillement._date_francaise("32/01/1984") is None
    assert depouillement._date_francaise("pas une date") is None


def test_nettoyage_de_la_nationalite():
    """La capture ramasse parfois la suite de la ligne du CV."""
    assert depouillement._nettoyer_nationalite("Togolaise - Sexe : Feminin") == "Togolaise"
    assert depouillement._nettoyer_nationalite("Ivoirienne, célibataire") == "Ivoirienne"
    assert depouillement._nettoyer_nationalite("  Béninoise  ") == "Béninoise"


async def test_une_saisie_humaine_n_est_jamais_ecrasee(fournisseur, texte_pdf):
    async with SessionLocal() as db:
        candidature = await monter_dossier(db)
        candidature.candidat.provenance = Provenance.VERIFIE_RH
        candidature.candidat.date_naissance = date(1985, 1, 1)
        db.add(
            DiplomeCandidat(
                candidat_id=candidature.candidat.id,
                intitule="Licence saisie à la main",
                niveau=3,
                domaine="gestion",
                provenance=Provenance.SAISI_RH,
            )
        )
        await db.flush()

        from app.services.preselection import charger_candidature

        rechargee = await charger_candidature(db, candidature.id)
        resultat = await depouillement.depouiller(db, rechargee)
        await db.commit()

        assert resultat.diplomes == 0
        assert any("conservées" in a for a in resultat.avertissements)

        diplomes = (await db.execute(select(DiplomeCandidat))).scalars().all()
        assert len(diplomes) == 1
        assert diplomes[0].intitule == "Licence saisie à la main"

        candidat = (await db.execute(select(Candidat))).scalar_one()
        assert candidat.date_naissance == date(1985, 1, 1)


async def test_un_diplome_sans_niveau_est_ignore_plutot_que_devine(monkeypatch, texte_pdf):
    stub = FournisseurExtraction(
        DossierExtrait.model_validate(
            {"diplomes": [{"intitule": "Formation interne", "niveau": None, "domaine": "gestion"}]}
        )
    )
    monkeypatch.setattr("app.services.depouillement.get_provider", lambda: stub)

    async with SessionLocal() as db:
        candidature = await monter_dossier(db)
        resultat = await depouillement.depouiller(db, candidature)
        await db.commit()

        assert resultat.diplomes == 0
        assert any("niveau indéterminable" in a for a in resultat.avertissements)
        assert (await db.execute(select(DiplomeCandidat))).scalars().all() == []


async def test_une_experience_sans_date_de_debut_est_ignoree(monkeypatch, texte_pdf):
    stub = FournisseurExtraction(
        DossierExtrait.model_validate(
            {"experiences": [{"poste": "Stagiaire", "employeur": "X", "debut": "illisible"}]}
        )
    )
    monkeypatch.setattr("app.services.depouillement.get_provider", lambda: stub)

    async with SessionLocal() as db:
        candidature = await monter_dossier(db)
        resultat = await depouillement.depouiller(db, candidature)
        await db.commit()

        assert resultat.experiences == 0
        assert (await db.execute(select(ExperienceCandidat))).scalars().all() == []


async def test_un_dossier_sans_piece_lisible_ne_plante_pas(fournisseur):
    async with SessionLocal() as db:
        candidature = await monter_dossier(db, avec_piece=False)
        resultat = await depouillement.depouiller(db, candidature)
        await db.commit()

        assert resultat.a_produit_quelque_chose is False
        assert any("Saisie manuelle" in a for a in resultat.avertissements)
        # Le modèle n'a même pas été sollicité : rien à lui envoyer.
        assert fournisseur.texte_recu is None


async def test_une_panne_du_modele_laisse_le_dossier_intact(monkeypatch, texte_pdf):
    from app.llm.base import LLMError

    class Panne(FournisseurExtraction):
        async def extraire_dossier(self, texte: str) -> DossierExtrait:
            raise LLMError("fournisseur injoignable")

    monkeypatch.setattr("app.services.depouillement.get_provider", lambda: Panne())

    async with SessionLocal() as db:
        candidature = await monter_dossier(db)
        resultat = await depouillement.depouiller(db, candidature)
        await db.commit()

        assert resultat.a_produit_quelque_chose is False
        assert any("Extraction indisponible" in a for a in resultat.avertissements)
        assert (await db.execute(select(DiplomeCandidat))).scalars().all() == []


def test_lecture_des_dates_partielles():
    assert depouillement._mois_vers_date("2015-03") == date(2015, 3, 1)
    assert depouillement._mois_vers_date("2015") == date(2015, 1, 1)
    assert depouillement._mois_vers_date("2015-03-14") == date(2015, 3, 14)
    assert depouillement._mois_vers_date("hier") is None
    assert depouillement._mois_vers_date("2015-13") is None
    assert depouillement._mois_vers_date(None) is None
