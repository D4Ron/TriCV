from __future__ import annotations

from datetime import datetime
from email.message import EmailMessage

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.domain.referentiel import PieceDossier
from app.models import Avis, Candidat, Candidature, Client, Mandat, Poste, Provenance
from app.models.enums import SourceCandidature, StatutCandidature
from app.services import courriel

pytestmark = pytest.mark.anyio

PDF = b"%PDF-1.4\n" + b"0" * 400


def construire_message(
    *,
    sujet: str = "[AVIS-2026-014] Candidature au poste de Directeur",
    expediteur: str = "Amina Kodjo <amina.kodjo@example.com>",
    pieces: tuple[tuple[str, bytes], ...] = (("CV_Amina.pdf", PDF),),
    message_id: str = "<msg-1@example.com>",
) -> bytes:
    message = EmailMessage()
    message["Subject"] = sujet
    message["From"] = expediteur
    message["To"] = "recrutement@kapiconsult.tg"
    message["Message-ID"] = message_id
    message["Date"] = "Wed, 15 Jul 2026 09:00:00 +0000"
    message.set_content("Madame, Monsieur, veuillez trouver ci-joint ma candidature.")
    for nom, donnees in pieces:
        message.add_attachment(
            donnees, maintype="application", subtype="pdf", filename=nom
        )
    return message.as_bytes()


class BoiteFactice:
    """Une boîte en mémoire : le relevé se teste sans serveur ni réseau."""

    def __init__(self, messages: list[bytes]) -> None:
        self.messages = [courriel.depuis_message(m) for m in messages]
        self.traites: list[str] = []

    def relever(self, limite: int = 50) -> list[courriel.MessageEntrant]:
        return [m for m in self.messages if m.message_id not in self.traites][:limite]

    def marquer_traite(self, message_id: str) -> None:
        self.traites.append(message_id)


async def monter_poste(db, reference: str = "AVIS-2026-014") -> Poste:
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
        pieces_requises=[PieceDossier.LETTRE_MOTIVATION.value, PieceDossier.CV.value],
    )
    db.add(poste)
    await db.flush()
    db.add(Avis(poste_id=poste.id, reference=reference, date_cloture=None))
    await db.flush()
    return poste


# --- analyse du message -----------------------------------------------------


def test_lecture_d_un_message():
    message = courriel.depuis_message(construire_message())
    assert message.expediteur == "amina.kodjo@example.com"
    assert message.nom_expediteur == "Amina Kodjo"
    assert message.recu_le == datetime(2026, 7, 15, 9, 0)
    assert [p.nom for p in message.pieces] == ["CV_Amina.pdf"]


def test_un_sujet_encode_est_decode():
    brut = construire_message(sujet="=?utf-8?B?Q2FuZGlkYXR1cmUgw6AgTG9tw6k=?=")
    assert courriel.depuis_message(brut).sujet == "Candidature à Lomé"


def test_extraction_des_references():
    assert courriel.references_du_sujet("[AVIS-2026-014] Candidature") == ["AVIS-2026-014"]
    assert courriel.references_du_sujet("Candidature spontanée") == []


def test_nom_devine_depuis_l_entete():
    assert courriel.nom_prenom(courriel.depuis_message(construire_message())) == (
        "Amina",
        "Kodjo",
    )
    sans_nom = courriel.depuis_message(
        construire_message(expediteur="kofi.mensah@example.com")
    )
    assert courriel.nom_prenom(sans_nom) == ("Kofi", "Mensah")


def test_classement_des_pieces_jointes():
    assert courriel.type_de_piece("CV_Amina.pdf") == PieceDossier.CV.value
    assert (
        courriel.type_de_piece("lettre_de_motivation.pdf")
        == PieceDossier.LETTRE_MOTIVATION.value
    )
    assert courriel.type_de_piece("diplome_master.pdf") == PieceDossier.COPIE_DIPLOMES.value


# --- relevé -----------------------------------------------------------------


async def test_un_message_devient_une_candidature():
    async with SessionLocal() as db:
        poste = await monter_poste(db)
        await db.commit()

        boite = BoiteFactice([construire_message()])
        resultat = await courriel.relever(db, boite)
        await db.commit()

        assert resultat.crees == 1
        candidature = (await db.execute(select(Candidature))).scalar_one()
        assert candidature.poste_id == poste.id
        assert candidature.source is SourceCandidature.EMAIL
        assert candidature.recue_le == datetime(2026, 7, 15, 9, 0)
        assert boite.traites == ["<msg-1@example.com>"]


async def test_l_etat_civil_issu_de_l_email_n_elimine_personne():
    """Le coeur du garde-fou : rien n'a été lu, donc rien n'élimine."""
    async with SessionLocal() as db:
        await monter_poste(db)
        await db.commit()

        await courriel.relever(db, BoiteFactice([construire_message()]))
        await db.commit()

        candidat = (await db.execute(select(Candidat))).scalar_one()
        assert candidat.provenance is Provenance.EXTRAIT_IA

        candidature = (await db.execute(select(Candidature))).scalar_one()
        # Dossier incomplet ET sans diplôme, pourtant non éliminé : les motifs
        # reposent sur des données que personne n'a encore confirmées.
        assert candidature.statut is StatutCandidature.A_VERIFIER


async def test_les_pieces_jointes_deviennent_des_pieces_du_dossier():
    async with SessionLocal() as db:
        await monter_poste(db)
        await db.commit()

        await courriel.relever(
            db,
            BoiteFactice(
                [
                    construire_message(
                        pieces=(("CV_Amina.pdf", PDF), ("lettre_motivation.pdf", PDF))
                    )
                ]
            ),
        )
        await db.commit()

        from app.services.preselection import charger_candidature

        candidature = (await db.execute(select(Candidature))).scalar_one()
        chargee = await charger_candidature(db, candidature.id)
        types = {p.type_piece for p in chargee.pieces}
        assert types == {PieceDossier.CV.value, PieceDossier.LETTRE_MOTIVATION.value}
        assert all(p.chemin_stockage for p in chargee.pieces)


async def test_une_piece_jointe_non_supportee_est_ignoree_sans_echec():
    async with SessionLocal() as db:
        await monter_poste(db)
        await db.commit()

        await courriel.relever(
            db,
            BoiteFactice(
                [construire_message(pieces=(("CV.pdf", PDF), ("signature.png", b"\x89PNG\r\n")))]
            ),
        )
        await db.commit()

        from app.services.preselection import charger_candidature

        candidature = (await db.execute(select(Candidature))).scalar_one()
        chargee = await charger_candidature(db, candidature.id)
        assert len(chargee.pieces) == 1


async def test_un_message_sans_reference_n_est_pas_rattache_au_hasard():
    """Sans référence, le dossier ne rejoint aucun poste — surtout pas le seul ouvert."""
    async with SessionLocal() as db:
        await monter_poste(db)
        await db.commit()

        resultat = await courriel.relever(
            db, BoiteFactice([construire_message(sujet="Candidature spontanée")])
        )
        await db.commit()

        assert resultat.crees == 0
        assert resultat.spontanees == 1

        candidature = (await db.execute(select(Candidature))).scalar_one()
        assert candidature.poste_id is None
        assert candidature.spontanee is True


async def test_un_message_sans_reference_reste_de_cote_si_les_spontanees_sont_fermees():
    async with SessionLocal() as db:
        await monter_poste(db)
        await db.commit()

        resultat = await courriel.relever(
            db,
            BoiteFactice([construire_message(sujet="Candidature spontanée")]),
            accepter_spontanees=False,
        )
        await db.commit()

        assert resultat.crees == 0
        assert resultat.spontanees == 0
        assert resultat.non_rattaches == ["Candidature spontanée"]
        assert (await db.execute(select(Candidature))).scalars().all() == []


async def test_un_message_sans_reference_ni_piece_reste_non_rattache():
    """Rien à en tirer : ni avis, ni CV. Il attend une lecture humaine."""
    async with SessionLocal() as db:
        await monter_poste(db)
        await db.commit()

        resultat = await courriel.relever(
            db, BoiteFactice([construire_message(sujet="Bonjour", pieces=())])
        )
        await db.commit()

        assert resultat.spontanees == 0
        assert resultat.non_rattaches == ["Bonjour"]
        assert (await db.execute(select(Candidature))).scalars().all() == []


async def test_une_reference_inconnue_ne_cree_rien():
    async with SessionLocal() as db:
        await monter_poste(db, reference="AVIS-2026-014")
        await db.commit()

        resultat = await courriel.relever(
            db, BoiteFactice([construire_message(sujet="[AVIS-9999] Candidature")])
        )
        await db.commit()
        assert resultat.crees == 0


async def test_rejouer_le_releve_ne_duplique_pas():
    """Si le marquage « lu » échoue, un second relevé doit être inoffensif."""
    async with SessionLocal() as db:
        await monter_poste(db)
        await db.commit()

        messages = [construire_message()]
        premier = await courriel.relever(db, BoiteFactice(messages))
        await db.commit()
        assert premier.crees == 1

        # Une boîte neuve : le message n'a pas été marqué du point de vue IMAP.
        second = await courriel.relever(db, BoiteFactice(messages))
        await db.commit()
        assert second.crees == 0
        assert second.ignores == 1
        assert len((await db.execute(select(Candidature))).scalars().all()) == 1


async def test_plusieurs_messages_en_un_releve():
    async with SessionLocal() as db:
        await monter_poste(db)
        await db.commit()

        # Des pieces distinctes : deux dossiers strictement identiques
        # seraient desormais ecartes comme doublons.
        boite = BoiteFactice(
            [
                construire_message(
                    message_id="<a@x>", expediteur="Amina Kodjo <a@x.com>",
                    pieces=(("CV_Amina.pdf", PDF + b"A"),),
                ),
                construire_message(
                    message_id="<b@x>", expediteur="Kofi Mensah <b@x.com>",
                    pieces=(("CV_Kofi.pdf", PDF + b"B"),),
                ),
                construire_message(message_id="<c@x>", sujet="Sans référence"),
            ]
        )
        resultat = await courriel.relever(db, boite)
        await db.commit()

        assert resultat.crees == 2
        # Le troisième n'a pas de référence : il devient une candidature
        # spontanée plutôt que d'être écarté.
        assert resultat.spontanees == 1


async def test_un_dossier_identique_renvoye_par_email_est_ignore():
    """Le meme CV renvoye dans un autre message n'ouvre pas un second dossier."""
    async with SessionLocal() as db:
        await monter_poste(db)
        await db.commit()

        premier = await courriel.relever(
            db, BoiteFactice([construire_message(message_id="<un@x>")])
        )
        await db.commit()
        assert premier.crees == 1

        second = await courriel.relever(
            db,
            BoiteFactice(
                [construire_message(message_id="<deux@x>", expediteur="Autre <autre@x.com>")]
            ),
        )
        await db.commit()
        assert second.crees == 0
        assert second.ignores == 1
        assert len((await db.execute(select(Candidature))).scalars().all()) == 1
