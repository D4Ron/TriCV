"""La lecture se relance seule : le travail d'un humain ne doit jamais en souffrir.

Ce qu'une relecture ne touche pas : une ligne confirmée, saisie, déclarée, comptée
à la main ; une pièce reclassée ; une note corrigée ; une appréciation ; un motif
levé. Ce qu'elle voit autrement attend une décision.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.domain.referentiel import MotifElimination, PieceDossier as P
from app.llm.base import DiplomeExtrait, DossierExtrait, ExperienceExtraite, LLMConfigError
from app.models.base import utcnow
from app.models.enums import Provenance, SourceCandidature
from app.models.recrutement import (
    Avis,
    Candidat,
    Candidature,
    Client,
    DiplomeCandidat,
    Elimination,
    ExperienceCandidat,
    Mandat,
    PieceCandidature,
    Poste,
)
from app.models.travail import LECTURE_IA, LECTURE_LOCALE, Travail
from app.services import depouillement, parametres, travaux
from app.services.preselection import charger_candidature, evaluer_candidature

pytestmark = pytest.mark.anyio

API = "/api/v1"
CV = (
    "Afi DOSSOU\nExpérience professionnelle\n2018 - 2023 Responsable logistique, Port Sec de Lomé\n"
    "- suivi des expéditions, des dépôts et des équipes de quai, sur deux sites et trois équipes\n"
    "- négociation des contrats de transport et pilotage du budget annuel des opérations\n"
    "Formation\n2014 Master en logistique, Université de Lomé\nCompétences\nExcel\nLangues\nFrançais"
)


class Modele:
    name = "modele"

    def __init__(self, dossier=None):
        self.dossier = dossier or DossierExtrait(
            diplomes=[DiplomeExtrait(intitule="Master en logistique", niveau=5, domaine="logistique", annee=2014)],
            experiences=[
                ExperienceExtraite(
                    poste="Responsable logistique", employeur="Port Sec de Lomé",
                    debut="2018-01", fin="2023-01",
                ),
                ExperienceExtraite(
                    poste="Chef de quai", employeur="Togo Transit", debut="2012-01", fin="2017-12",
                ),
            ],
            langues=["Français", "Anglais"],
            certifications=["PMP"],
        )
        self.appels = 0

    async def extraire_dossier(self, texte, domaines=()):
        self.appels += 1
        return self.dossier

    async def repondre_json(self, consigne, contexte, systeme=""):
        return {}


@pytest.fixture
def modele(monkeypatch):
    def poser(dossier=None):
        stub = Modele(dossier)
        for chemin in (
            "app.services.depouillement.get_provider",
            "app.services.classement_ia.get_provider",
            "app.services.travaux.get_provider",
        ):
            monkeypatch.setattr(chemin, lambda: stub)
        return stub

    return poser


async def monter(db, *, provenance=Provenance.EXTRAIT_IA, archive=False, lignes=True) -> tuple[str, str]:
    client = Client(nom="Client fictif")
    db.add(client)
    await db.flush()
    mandat = Mandat(client_id=client.id, intitule="Mandat", archive_le=utcnow() if archive else None)
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
    candidat = Candidat(nom="DOSSOU", prenom="Afi", email="afi@example.tg", provenance=provenance)
    db.add(candidat)
    await db.flush()
    if lignes:
        db.add(
            DiplomeCandidat(
                candidat_id=candidat.id, intitule="Master en logistique", niveau=5,
                domaine="logistique", annee=2014, provenance=provenance,
            )
        )
        db.add(
            ExperienceCandidat(
                candidat_id=candidat.id, poste="Responsable logistique", employeur="Port Sec de Lomé",
                debut=date(2018, 1, 1), fin=date(2023, 1, 1), provenance=provenance,
            )
        )
    candidature = Candidature(
        poste_id=poste.id, candidat_id=candidat.id, source=SourceCandidature.EMAIL,
        recue_le=datetime(2026, 7, 15, 9, 0),
    )
    db.add(candidature)
    await db.flush()
    db.add(
        PieceCandidature(
            candidature_id=candidature.id, type_piece=P.CV.value, nom_fichier="cv.pdf",
            texte_extrait=CV, chemin_stockage=f"tests/{candidature.id}.pdf",
        )
    )
    await db.flush()
    await evaluer_candidature(db, await charger_candidature(db, candidature.id))
    await db.commit()
    return poste.id, candidature.id


async def lire(identifiant, *, ia=True):
    async with SessionLocal() as db:
        c = await charger_candidature(db, identifiant)
        resultat = await depouillement.depouiller(db, c, ia=ia)
        await db.commit()
    return resultat


async def dossier(db, identifiant):
    return await charger_candidature(db, identifiant)


async def confirmer(identifiant):
    async with SessionLocal() as db:
        c = await dossier(db, identifiant)
        c.candidat.verifie_le = utcnow()
        c.candidat.provenance = Provenance.VERIFIE_RH
        for ligne in [*c.candidat.diplomes, *c.candidat.experiences]:
            ligne.provenance = Provenance.VERIFIE_RH
        await db.commit()


# --- ce qui ne bouge pas -----------------------------------------------------


async def test_un_dossier_confirme_ne_change_pas_et_recoit_des_propositions(modele):
    modele()
    async with SessionLocal() as db:
        _, identifiant = await monter(db)
    await confirmer(identifiant)

    resultat = await lire(identifiant)

    async with SessionLocal() as db:
        c = await dossier(db, identifiant)
        assert [e.poste for e in c.candidat.experiences] == ["Responsable logistique"]
        assert len(c.candidat.diplomes) == 1
        familles = sorted((p["famille"], p["action"]) for p in c.candidat.propositions)
    assert resultat.propositions == 4
    assert familles == [
        ("certification", "ajouter"),
        ("experience", "ajouter"),
        ("langue", "ajouter"),
        ("langue", "ajouter"),
    ]


async def test_les_decisions_humaines_survivent_a_une_relecture(client, auth, modele):
    modele()
    async with SessionLocal() as db:
        _, identifiant = await monter(db)
        c = await dossier(db, identifiant)
        c.ajustements_note = {"FORMATION": {"points": 2, "motif": "Vérifié"}}
        c.appreciation_consistance = 1
        c.appreciation_motif = "Lettre soignée"
        c.pieces[0].type_source = "humain"
        c.qualification_manuelle = "FORTEMENT"
        await evaluer_candidature(db, c)
        await db.flush()
        c = await dossier(db, identifiant)
        c.notation.note_manuelle = 12
        c.notation.note_manuelle_motif = "Décision"
        motif = next(
            e for e in c.eliminations if e.motif is MotifElimination.EXPERIENCE_SPECIFIQUE_INSUFFISANTE
        )
        motif.leve_le = utcnow()
        motif.leve_motif = "Erreur de lecture"
        await db.commit()

    await lire(identifiant)

    async with SessionLocal() as db:
        c = await dossier(db, identifiant)
        ligne = next(l for l in c.notation.lignes if l.code == "FORMATION")
        assert float(ligne.points) == 2
        assert float(c.notation.note_manuelle) == 12
        assert float(c.appreciation_consistance) == 1
        assert c.pieces[0].type_source == "humain"
        assert c.qualification_manuelle == "FORTEMENT"
        levee = next(
            e for e in c.eliminations if e.motif is MotifElimination.EXPERIENCE_SPECIFIQUE_INSUFFISANTE
        )
        assert levee.leve_le is not None


async def test_une_experience_comptee_a_la_main_survit_a_la_relecture(client, auth, modele):
    modele()
    async with SessionLocal() as db:
        _, identifiant = await monter(db)
        experience = (await dossier(db, identifiant)).candidat.experiences[0].id

    reponse = await client.post(
        f"{API}/candidatures/{identifiant}/experiences/{experience}/domaines",
        json={"domaine": "Pétrole & Gaz"},
        headers=auth,
    )
    assert reponse.status_code == 200, reponse.text

    for ia in (True, False):
        await lire(identifiant, ia=ia)
        async with SessionLocal() as db:
            c = await dossier(db, identifiant)
            gardee = next(e for e in c.candidat.experiences if e.id == experience)
            assert "Pétrole & Gaz" in gardee.domaines
            # Le même emploi n'est pas ajouté une seconde fois à côté.
            assert sum(e.poste == "Responsable logistique" for e in c.candidat.experiences) == 1


async def test_une_experience_retiree_a_la_main_ne_se_recompte_pas(client, auth, modele):
    modele(
        DossierExtrait(
            experiences=[
                ExperienceExtraite(
                    poste="Responsable logistique", employeur="Port Sec de Lomé",
                    debut="2018-01", fin="2023-01", domaines=["Pétrole & Gaz"],
                )
            ]
        )
    )
    async with SessionLocal() as db:
        _, identifiant = await monter(db)
        experience = (await dossier(db, identifiant)).candidat.experiences[0].id
    await client.post(
        f"{API}/candidatures/{identifiant}/experiences/{experience}/domaines",
        json={"domaine": "Pétrole & Gaz", "compte": False},
        headers=auth,
    )

    await lire(identifiant)

    async with SessionLocal() as db:
        c = await dossier(db, identifiant)
        assert "Pétrole & Gaz" not in (c.candidat.experiences[0].domaines or [])


async def test_un_parcours_declare_par_le_candidat_ne_change_pas(modele):
    modele()
    async with SessionLocal() as db:
        _, identifiant = await monter(db, provenance=Provenance.DECLARE)

    resultat = await lire(identifiant)

    async with SessionLocal() as db:
        c = await dossier(db, identifiant)
        assert all(e.provenance is Provenance.DECLARE for e in c.candidat.experiences)
        assert len(c.candidat.experiences) == 1
    assert resultat.experiences == 0
    assert resultat.propositions >= 1


async def test_un_dossier_fige_ne_perd_rien_a_une_lecture_locale(modele):
    modele()
    async with SessionLocal() as db:
        _, identifiant = await monter(db)
        c = await dossier(db, identifiant)
        # Une seule famille confirmée : l'autre attend encore, et doit rester.
        c.candidat.verifie_le = utcnow()
        c.candidat.diplomes[0].provenance = Provenance.VERIFIE_RH
        await db.commit()

    await lire(identifiant, ia=False)

    async with SessionLocal() as db:
        c = await dossier(db, identifiant)
        assert len(c.candidat.experiences) == 1
        assert c.candidat.propositions == []


# --- ce qui suit la lecture --------------------------------------------------


async def test_un_dossier_sans_decision_humaine_est_remplace_comme_avant(modele):
    modele()
    async with SessionLocal() as db:
        _, identifiant = await monter(db)

    await lire(identifiant)

    async with SessionLocal() as db:
        c = await dossier(db, identifiant)
        assert sorted(e.poste for e in c.candidat.experiences) == ["Chef de quai", "Responsable logistique"]
        assert c.candidat.propositions == []
        assert sorted(c.candidat.langues) == ["Anglais", "Français"]


async def test_relire_deux_fois_ne_double_rien(modele):
    modele()
    async with SessionLocal() as db:
        _, identifiant = await monter(db)
    await confirmer(identifiant)

    await lire(identifiant)
    await lire(identifiant)

    async with SessionLocal() as db:
        c = await dossier(db, identifiant)
        assert len(c.candidat.experiences) == 1
        assert len(c.candidat.propositions) == 4


async def test_une_divergence_sur_une_ligne_confirmee_devient_une_proposition(client, auth, modele):
    modele(
        DossierExtrait(
            experiences=[
                ExperienceExtraite(
                    poste="Directeur logistique", employeur="Port Sec de Lomé",
                    debut="2017-01", fin="2023-01",
                )
            ]
        )
    )
    async with SessionLocal() as db:
        _, identifiant = await monter(db)
    await confirmer(identifiant)
    await lire(identifiant)

    corps = (await client.get(f"{API}/candidatures/{identifiant}", headers=auth)).json()
    proposition = next(p for p in corps["candidat"]["propositions"] if p["famille"] == "experience")
    assert proposition["action"] == "modifier"
    assert "Responsable logistique" in proposition["avant"]
    assert "Directeur logistique" in proposition["libelle"]
    # Rien de changé tant que personne n'a accepté.
    assert corps["candidat"]["experiences"][0]["poste"] == "Responsable logistique"
    note = corps["notation"]["total"]

    accepte = await client.post(
        f"{API}/candidatures/{identifiant}/propositions",
        json={"ids": [proposition["id"]], "accepter": True},
        headers=auth,
    )
    assert accepte.status_code == 200, accepte.text
    corps = accepte.json()
    assert corps["candidat"]["experiences"][0]["poste"] == "Directeur logistique"
    assert corps["candidat"]["experiences"][0]["debut"] == "2017-01-01"
    assert corps["candidat"]["experiences"][0]["provenance"] == "VERIFIE_RH"
    assert all(p["famille"] != "experience" for p in corps["candidat"]["propositions"])
    assert corps["notation"]["total"] >= note


async def test_une_proposition_acceptee_ajoute_la_ligne_et_la_note_suit(client, auth, modele):
    modele()
    async with SessionLocal() as db:
        _, identifiant = await monter(db)
    await confirmer(identifiant)
    await lire(identifiant)

    corps = (
        await client.post(
            f"{API}/candidatures/{identifiant}/propositions", json={"accepter": True}, headers=auth
        )
    ).json()
    assert sorted(e["poste"] for e in corps["candidat"]["experiences"]) == [
        "Chef de quai",
        "Responsable logistique",
    ]
    assert "Anglais" in corps["candidat"]["langues"]
    assert "PMP" in corps["candidat"]["certifications"]
    assert corps["candidat"]["propositions"] == []


async def test_une_proposition_ecartee_ne_revient_pas(client, auth, modele):
    modele()
    async with SessionLocal() as db:
        _, identifiant = await monter(db)
    await confirmer(identifiant)
    await lire(identifiant)

    ecarte = await client.post(
        f"{API}/candidatures/{identifiant}/propositions", json={"accepter": False}, headers=auth
    )
    assert ecarte.json()["candidat"]["propositions"] == []
    assert len(ecarte.json()["candidat"]["experiences"]) == 1

    await lire(identifiant)
    corps = (await client.get(f"{API}/candidatures/{identifiant}", headers=auth)).json()
    assert corps["candidat"]["propositions"] == []

    vide = await client.post(
        f"{API}/candidatures/{identifiant}/propositions", json={"accepter": True}, headers=auth
    )
    assert vide.status_code == 404


async def test_une_lecture_locale_ne_propose_rien(modele):
    modele()
    async with SessionLocal() as db:
        _, identifiant = await monter(db)
    await confirmer(identifiant)

    await lire(identifiant, ia=False)

    async with SessionLocal() as db:
        assert (await dossier(db, identifiant)).candidat.propositions == []


async def test_le_poste_compte_les_dossiers_a_trancher(client, auth, modele):
    modele()
    async with SessionLocal() as db:
        poste, identifiant = await monter(db)
    await confirmer(identifiant)
    await lire(identifiant)

    grille = (await client.get(f"{API}/postes/{poste}/grille", headers=auth)).json()
    assert grille["nombre_propositions"] == 1
    liste = (await client.get(f"{API}/postes/{poste}/candidatures", headers=auth)).json()
    assert liste["items"][0]["propositions"] == 4


# --- le lancement automatique ------------------------------------------------


async def en_file():
    async with SessionLocal() as db:
        return list((await db.execute(select(Travail))).scalars())


async def test_une_arrivee_programme_la_lecture_par_l_ia(modele):
    modele()
    async with SessionLocal() as db:
        poste, identifiant = await monter(db)
        await travaux.apres_arrivee(db, identifiant, poste)
        await travaux.apres_arrivee(db, identifiant, poste)
        await db.commit()

    assert [t.nature for t in await en_file()] == [LECTURE_IA]


async def test_desactivee_la_lecture_automatique_ne_part_pas(modele):
    modele()
    async with SessionLocal() as db:
        poste, identifiant = await monter(db)
        await parametres.ecrire(db, {parametres.LECTURE_IA_AUTO: False})
        await travaux.apres_arrivee(db, identifiant, poste)
        await db.commit()

    assert await en_file() == []


async def test_sans_fournisseur_rien_n_est_programme_et_rien_ne_casse(monkeypatch):
    def aucun():
        raise LLMConfigError("aucune clé")

    monkeypatch.setattr("app.services.travaux.get_provider", aucun)
    async with SessionLocal() as db:
        poste, identifiant = await monter(db)
        await travaux.apres_arrivee(db, identifiant, poste)
        await db.commit()

    assert await en_file() == []


async def test_le_reglage_se_voit_et_se_change_dans_l_api(client, auth):
    assert (await client.get(f"{API}/settings", headers=auth)).json()["lecture_ia_auto"] is True
    reponse = await client.patch(f"{API}/settings", json={"lecture_ia_auto": False}, headers=auth)
    assert reponse.json()["lecture_ia_auto"] is False


async def test_une_nouvelle_version_relit_tout_une_seule_fois(modele):
    stub = modele()
    async with SessionLocal() as db:
        _, confirme = await monter(db)
        _, ouvert = await monter(db)
        _, archive = await monter(db, archive=True)
    await confirmer(confirme)

    assert await travaux.relancer_apres_mise_a_jour() == 2
    assert await travaux.relancer_apres_mise_a_jour() == 0

    file = await en_file()
    assert {t.candidature_id for t in file} == {confirme, ouvert}
    assert {t.nature for t in file} == {LECTURE_IA}

    await travaux.traiter_un()
    await travaux.traiter_un()
    assert stub.appels == 2

    async with SessionLocal() as db:
        c = await dossier(db, confirme)
        assert len(c.candidat.experiences) == 1
        assert len(c.candidat.propositions) == 4


async def test_une_version_de_plus_relit_de_nouveau(modele, monkeypatch):
    modele()
    async with SessionLocal() as db:
        await monter(db)
    await travaux.relancer_apres_mise_a_jour()
    await travaux.traiter_un()

    monkeypatch.setattr(travaux, "VERSION_DE_LECTURE", travaux.VERSION_DE_LECTURE + 1)
    assert await travaux.relancer_apres_mise_a_jour() == 1


async def test_sans_lecture_automatique_la_relecture_reste_locale(modele):
    modele()
    async with SessionLocal() as db:
        _, confirme = await monter(db)
        _, ouvert = await monter(db)
        await parametres.ecrire(db, {parametres.LECTURE_IA_AUTO: False})
        await db.commit()
    await confirmer(confirme)

    assert await travaux.relancer_apres_mise_a_jour() == 1
    file = await en_file()
    assert [(t.candidature_id, t.nature) for t in file] == [(ouvert, LECTURE_LOCALE)]


async def test_une_piece_rangee_sur_un_dossier_confirme_n_est_plus_classee(modele):
    stub = modele()
    envoyes = []

    async def noter(consigne, contexte, systeme=""):
        envoyes.append(contexte)
        return {}

    stub.repondre_json = noter
    async with SessionLocal() as db:
        poste, identifiant = await monter(db)
        db.add(
            PieceCandidature(
                candidature_id=identifiant, type_piece=P.AUTRE.value, nom_fichier="scan.pdf",
                chemin_stockage="tests/scan.pdf",
                texte_extrait="Rapport de stage sur la modernisation du terminal à conteneurs.",
            )
        )
        await travaux.ajouter(db, [(identifiant, poste)], LECTURE_IA)
        await db.commit()
    await confirmer(identifiant)

    await travaux.traiter_un()
    assert envoyes == []
