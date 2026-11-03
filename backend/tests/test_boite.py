"""La boîte lue dans l'application, et le ménage des dossiers inutiles.

Constaté en production : la boîte de recrutement reçoit bien plus que des
candidatures — lettres d'information en PDF, rapports, réponses à des collègues.
Le relevé en tire des dossiers, ce qui est voulu : mieux vaut un dossier inutile
qu'une candidature manquée. Ce qui est vérifié ici, c'est que ces dossiers se
retirent en nombre, qu'ils ne reviennent pas, et qu'un expéditeur peut être
ignoré une fois pour toutes.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from app.api import boite as api_boite
from app.api import candidatures as api_candidatures
from app.db import SessionLocal
from app.models import Candidature, ExpediteurIgnore, MessageTraite
from app.models import boite as traces
from app.services import courriel

pytestmark = pytest.mark.anyio

API = "/api/v1"
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def message(
    gid: str, expediteur: str, sujet: str = "Candidature", piece: bytes | None = PDF, jour: int = 1
) -> dict:
    return {
        "gid": gid,
        "entrant": courriel.MessageEntrant(
            message_id=f"<{gid}@example.test>",
            expediteur=expediteur,
            nom_expediteur=expediteur.split("@")[0].replace(".", " ").title(),
            sujet=sujet,
            recu_le=datetime(2026, 10, jour, 9, 0),
            pieces=[courriel.PieceJointe(nom=f"CV {gid}.pdf", donnees=piece + gid.encode())]
            if piece
            else [],
        ),
    }


class BoiteFactice:
    """La boîte Microsoft, en mémoire : listes, lecture, MIME, marquage."""

    def __init__(self, messages: list[dict]) -> None:
        self.messages = {m["gid"]: m["entrant"] for m in messages}
        self.lus: set[str] = set()
        self.reste = False

    def _resume(self, gid: str) -> dict:
        m = self.messages[gid]
        return {
            "id": gid,
            "message_id": m.message_id,
            "sujet": m.sujet,
            "expediteur": m.expediteur,
            "nom_expediteur": m.nom_expediteur,
            "recu_le": m.recu_le.isoformat(),
            "lu": gid in self.lus,
            "avec_pieces": bool(m.pieces),
            "apercu": "",
            "conversation": "",
        }

    def verifier(self) -> dict:
        return {"boite": "recrutement@kapi.tg", "dossier": "Boîte de réception",
                "messages": len(self.messages), "non_lus": len(self.messages) - len(self.lus)}

    def lister(self, *, filtre="tous", recherche="", taille=50, suite=""):
        return {"messages": [self._resume(g) for g in self.messages], "suite": ""}

    def lire(self, gid: str) -> dict:
        resume = self._resume(gid)
        resume.update({"corps": "Bonjour", "destinataires": [], "pieces": []})
        return resume

    def du_meme_expediteur(self, adresse: str) -> list[dict]:
        return [self._resume(g) for g, m in self.messages.items() if m.expediteur == adresse]

    def message_complet(self, gid: str) -> courriel.MessageEntrant:
        return self.messages[gid]

    def relever(self, limite: int = 50, exclure=frozenset()):
        nouveaux = [
            m for g, m in sorted(self.messages.items(), key=lambda x: x[1].recu_le)
            if g not in self.lus and m.message_id not in exclure
        ]
        self.reste = len(nouveaux) > limite
        return nouveaux[:limite]

    def marquer_traite(self, message_id: str) -> None:
        for g, m in self.messages.items():
            if m.message_id == message_id:
                self.lus.add(g)

    def fermer(self) -> None:
        pass


@pytest.fixture
def boite(monkeypatch):
    def brancher(messages: list[dict]) -> BoiteFactice:
        factice = BoiteFactice(messages)

        async def ouvrir(_db):
            return factice

        monkeypatch.setattr(api_boite, "_ouvrir_boite", ouvrir)
        monkeypatch.setattr(api_candidatures, "_ouvrir_boite", ouvrir)
        return factice

    return brancher


async def _candidatures() -> list[Candidature]:
    async with SessionLocal() as db:
        return list((await db.execute(select(Candidature))).scalars())


# --- la boîte à l'écran --------------------------------------------------------


async def test_la_liste_dit_ce_que_l_application_a_fait_de_chaque_message(client, auth, boite):
    boite([message("a", "kwami@example.tg"), message("b", "lettre@journal.test", "Journal n°12")])
    await client.post(f"{API}/boite/importer", json={"identifiants": ["a"]}, headers=auth)

    page = (await client.get(f"{API}/boite/messages", headers=auth)).json()
    par_id = {m["id"]: m for m in page["messages"]}
    assert par_id["a"]["statut"] == traces.IMPORTE
    assert par_id["a"]["candidature_id"]
    assert par_id["b"]["statut"] == ""
    assert page["total"] == 2


async def test_les_courriels_d_un_meme_candidat_font_un_seul_dossier(client, auth, boite):
    """Le CV, puis « j'ai oublié les diplômes » : un dossier, pas deux."""
    boite([
        message("cv", "kwami@example.tg", "Candidature", jour=1),
        message("dip", "kwami@example.tg", "Mes diplômes", jour=2),
    ])
    reponse = await client.post(
        f"{API}/boite/importer", json={"identifiants": ["cv", "dip"]}, headers=auth
    )
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["crees"] == 1
    dossiers = await _candidatures()
    assert len(dossiers) == 1
    async with SessionLocal() as db:
        from app.services.preselection import charger_candidature

        assert len((await charger_candidature(db, dossiers[0].id)).pieces) == 2


async def test_importer_deux_fois_ne_cree_pas_de_doublon(client, auth, boite):
    boite([message("a", "kwami@example.tg")])
    await client.post(f"{API}/boite/importer", json={"identifiants": ["a"]}, headers=auth)
    second = (await client.post(f"{API}/boite/importer", json={"identifiants": ["a"]}, headers=auth)).json()
    assert second["crees"] == 0
    assert len(second["deja_importes"]) == 1
    assert len(await _candidatures()) == 1


async def test_un_message_sans_piece_n_est_pas_importe(client, auth, boite):
    boite([message("a", "kwami@example.tg", piece=None)])
    reponse = (await client.post(f"{API}/boite/importer", json={"identifiants": ["a"]}, headers=auth)).json()
    assert reponse["crees"] == 0 and len(reponse["sans_piece"]) == 1


async def test_un_message_ignore_n_est_plus_releve(client, auth, boite):
    factice = boite([message("a", "lettre@journal.test", "Journal n°12")])
    m = factice.messages["a"]
    await client.post(
        f"{API}/boite/ignorer",
        json={"messages": [{"message_id": m.message_id, "expediteur": m.expediteur, "sujet": m.sujet}]},
        headers=auth,
    )
    releve = (await client.post(f"{API}/courriel/relever", headers=auth))
    assert releve.status_code == 409 or releve.json()["crees"] + releve.json()["spontanees"] == 0
    assert await _candidatures() == []


# --- les expéditeurs ignorés -------------------------------------------------------


async def test_un_domaine_ignore_ne_produit_plus_de_dossier(client, auth, boite):
    boite([message("a", "lettre@journal.test", "Journal n°12"), message("b", "kwami@example.tg")])
    await client.post(f"{API}/boite/expediteurs-ignores", json={"adresse": "@journal.test"}, headers=auth)

    async with SessionLocal() as db:
        resultat = await courriel.relever(db, await api_candidatures._ouvrir_boite(db))
        await db.commit()
    assert resultat.expediteurs_ignores == 1
    dossiers = await _candidatures()
    assert len(dossiers) == 1


async def test_on_n_ignore_pas_la_boite_elle_meme(client, auth):
    await client.patch(f"{API}/settings", json={"adresse_boite": "recrutement@kapi.tg"}, headers=auth)
    refus = await client.post(
        f"{API}/boite/expediteurs-ignores", json={"adresse": "@kapi.tg"}, headers=auth
    )
    assert refus.status_code == 409


async def test_on_n_ignore_pas_une_messagerie_publique_entiere(client, auth):
    """@gmail.com, c'est la plupart des candidats : seule une adresse précise s'ignore."""
    refus = await client.post(
        f"{API}/boite/expediteurs-ignores", json={"adresse": "@Gmail.com"}, headers=auth
    )
    assert refus.status_code == 409
    assert "messagerie publique" in refus.json()["detail"]
    accepte = await client.post(
        f"{API}/boite/expediteurs-ignores", json={"adresse": "lettre.info@gmail.com"}, headers=auth
    )
    assert accepte.status_code == 200


async def test_une_regle_se_retire(client, auth):
    await client.post(f"{API}/boite/expediteurs-ignores", json={"adresse": "x@journal.test"}, headers=auth)
    regles = (await client.get(f"{API}/boite/expediteurs-ignores", headers=auth)).json()
    assert [r["adresse"] for r in regles] == ["x@journal.test"]
    await client.delete(f"{API}/boite/expediteurs-ignores/{regles[0]['id']}", headers=auth)
    assert (await client.get(f"{API}/boite/expediteurs-ignores", headers=auth)).json() == []


# --- le relevé par lots ------------------------------------------------------------


async def test_le_releve_se_fait_par_lots_jusqu_au_bout(client, auth, boite):
    boite([message(f"m{i}", f"c{i}@example.tg", jour=i + 1) for i in range(5)])
    premier = (await client.post(f"{API}/courriel/relever?limite=2", headers=auth))
    # Le relevé exige une boîte activée ; la boîte factice tient lieu de configuration.
    assert premier.status_code == 200, premier.text
    corps = premier.json()
    assert corps["reste"] is True
    total = corps["spontanees"] + corps["crees"]
    while corps["reste"]:
        corps = (await client.post(f"{API}/courriel/relever?limite=2", headers=auth)).json()
        total += corps["spontanees"] + corps["crees"]
    assert total == 5
    assert len(await _candidatures()) == 5


# --- le ménage en nombre ---------------------------------------------------------


async def test_les_dossiers_inutiles_se_suppriment_en_lot_et_ne_reviennent_pas(client, auth, boite):
    factice = boite([message(f"j{i}", "lettre@journal.test", f"Journal n°{i}", jour=i + 1) for i in range(3)])
    async with SessionLocal() as db:
        await courriel.relever(db, factice)
        await db.commit()
    dossiers = await _candidatures()
    # Trois messages de la même adresse : un seul dossier, pas trois doublons.
    assert len(dossiers) == 1

    reponse = await client.post(
        f"{API}/dossiers/suppression",
        json={
            "candidature_ids": [d.id for d in dossiers],
            "motif": "lettre d'information, pas une candidature",
            "ignorer_expediteurs": True,
        },
        headers=auth,
    )
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["supprimes"] == 1
    assert corps["expediteurs_ignores"] == ["lettre@journal.test"]
    assert await _candidatures() == []

    # Une boîte où les messages sont encore non lus : rien ne revient.
    factice.lus.clear()
    async with SessionLocal() as db:
        resultat = await courriel.relever(db, factice)
        await db.commit()
        statuts = {t.statut for t in (await db.execute(select(MessageTraite))).scalars()}
    assert resultat.crees + resultat.spontanees == 0
    assert await _candidatures() == []
    assert statuts == {traces.SUPPRIME}


async def test_la_suppression_en_lot_garde_ce_qui_ne_ressemble_pas_a_une_erreur(client, auth, boite):
    """Les mêmes retenues qu'à l'unité : un dossier passé en entretien est gardé."""
    factice = boite([message("a", "a@example.tg"), message("b", "b@example.tg", jour=2)])
    async with SessionLocal() as db:
        await courriel.relever(db, factice)
        await db.commit()
    dossiers = await _candidatures()

    from app.models import Entretien

    async with SessionLocal() as db:
        db.add(Entretien(candidature_id=dossiers[0].id))
        await db.commit()

    corps = (await client.post(
        f"{API}/dossiers/suppression",
        json={"candidature_ids": [d.id for d in dossiers], "motif": "ménage"},
        headers=auth,
    )).json()
    assert corps["supprimes"] == 1
    assert [r["id"] for r in corps["retenus"]] == [dossiers[0].id]
    assert len(await _candidatures()) == 1


async def test_retablir_un_message_ignore_le_rend_au_releve(client, auth, boite):
    factice = boite([message("a", "kwami@example.tg")])
    m = factice.messages["a"]
    await client.post(
        f"{API}/boite/ignorer",
        json={"messages": [{"message_id": m.message_id, "expediteur": m.expediteur}]},
        headers=auth,
    )
    retabli = (await client.post(f"{API}/boite/retablir", json={"message_ids": [m.message_id]}, headers=auth)).json()
    assert retabli["retablis"] == 1
    async with SessionLocal() as db:
        resultat = await courriel.relever(db, factice)
        await db.commit()
    assert resultat.spontanees == 1


async def test_un_recruteur_peut_relever_mais_la_regle_est_journalisee(client, auth):
    from app.models import AuditLog

    await client.post(f"{API}/boite/expediteurs-ignores", json={"adresse": "@journal.test"}, headers=auth)
    async with SessionLocal() as db:
        actions = set((await db.execute(select(AuditLog.action))).scalars())
        regles = list((await db.execute(select(ExpediteurIgnore))).scalars())
    assert "boite.ignorer_expediteur" in actions
    assert regles[0].motif_adresse == "@journal.test"
