from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.domain.referentiel import MotifElimination, NiveauDiplome, PieceDossier, Sexe
from app.models.enums import Provenance, StatutCandidature
from app.models.recrutement import (
    Avis,
    Candidat,
    Candidature,
    Client,
    DiplomeCandidat,
    Elimination,
    ExperienceCandidat,
    Mandat,
    Notation,
    PieceCandidature,
    Poste,
)
from app.services.preselection import evaluer_candidature, evaluer_poste

pytestmark = pytest.mark.anyio

CLOTURE = date(2026, 7, 31)


async def monter_poste(db, **overrides) -> Poste:
    client = Client(nom="Dogta-Lafiè", secteur="Santé")
    db.add(client)
    await db.flush()

    mandat = Mandat(client_id=client.id, intitule="Recrutement direction générale")
    db.add(mandat)
    await db.flush()

    defauts = {
        "mandat_id": mandat.id,
        "intitule": "Directeur Général",
        "niveau_min": int(NiveauDiplome.BAC_PLUS_4),
        "domaines_acceptes": ["gestion hôtelière"],
        "annees_experience_min": 10,
        "annees_experience_specifique_min": 5,
        "domaines_experience": ["gestion hôtelière"],
        "pieces_requises": [PieceDossier.LETTRE_MOTIVATION.value, PieceDossier.CV.value],
        "langues_requises": ["français"],
    }
    poste = Poste(**{**defauts, **overrides})
    db.add(poste)
    await db.flush()

    db.add(Avis(poste_id=poste.id, date_cloture=CLOTURE))
    await db.flush()
    return poste


async def monter_candidature(
    db,
    poste: Poste,
    *,
    provenance_diplome=Provenance.DECLARE,
    provenance_etat_civil=Provenance.DECLARE,
    niveau=NiveauDiplome.BAC_PLUS_5,
    domaine="gestion hôtelière",
    debut=date(2010, 1, 1),
    pieces=(PieceDossier.LETTRE_MOTIVATION, PieceDossier.CV),
    naissance=date(1985, 3, 1),
    sexe=Sexe.FEMININ,
    nationalites=("Togolaise",),
    recue_le=datetime(2026, 7, 1, 10, 0),
) -> Candidature:
    candidat = Candidat(
        nom="Kodjo",
        prenom="Amina",
        date_naissance=naissance,
        sexe=sexe,
        nationalites=list(nationalites),
        langues=["français"],
        provenance=provenance_etat_civil,
    )
    db.add(candidat)
    await db.flush()

    db.add(
        DiplomeCandidat(
            candidat_id=candidat.id,
            intitule="Master",
            niveau=int(niveau),
            domaine=domaine,
            provenance=provenance_diplome,
        )
    )
    db.add(
        ExperienceCandidat(
            candidat_id=candidat.id,
            poste="Directrice adjointe",
            employeur="Hôtel du 2 Février",
            debut=debut,
            fin=date(2026, 1, 1),
            domaines=["gestion hôtelière"],
            pays="Togo",
        )
    )
    candidature = Candidature(poste_id=poste.id, candidat_id=candidat.id, recue_le=recue_le)
    db.add(candidature)
    await db.flush()

    for piece in pieces:
        db.add(
            PieceCandidature(
                candidature_id=candidature.id,
                type_piece=piece.value,
                nom_fichier=f"{piece.value.lower()}.pdf",
                chemin_stockage=f"/data/{piece.value.lower()}.pdf",
            )
        )
    await db.flush()

    from app.services.preselection import charger_candidature

    return await charger_candidature(db, candidature.id)


async def test_une_candidature_conforme_est_preselectionnee():
    async with SessionLocal() as db:
        poste = await monter_poste(db)
        candidature = await monter_candidature(db, poste)

        notation = await evaluer_candidature(db, candidature)
        await db.commit()

        assert candidature.statut is StatutCandidature.PRESELECTIONNEE
        assert notation.atteint_le_seuil is True
        assert float(notation.total) > 0
        assert len(notation.lignes) == 4


async def test_la_notation_est_persistee_avec_son_detail():
    async with SessionLocal() as db:
        poste = await monter_poste(db)
        candidature = await monter_candidature(db, poste)
        await evaluer_candidature(db, candidature)
        await db.commit()

        stocke = (
            await db.execute(select(Notation).where(Notation.candidature_id == candidature.id))
        ).scalar_one()
        codes = {ligne.code for ligne in stocke.lignes}
        # Le barème du cabinet : quatre critères, sans ligne « ajouts ».
        assert codes == {
            "CONSISTANCE",
            "FORMATION",
            "EXPERIENCE_GENERALE",
            "EXPERIENCE_SPECIFIQUE",
        }
        for ligne in stocke.lignes:
            assert ligne.detail


async def test_le_bareme_est_fige_dans_la_notation():
    """Retoucher le barème du poste ne doit pas réécrire une grille déjà rendue."""
    async with SessionLocal() as db:
        poste = await monter_poste(db)
        candidature = await monter_candidature(db, poste)
        notation = await evaluer_candidature(db, candidature)
        await db.commit()

        assert notation.bareme_utilise["total_max"] == 30.0
        assert notation.bareme_utilise["formation"]["points_max"] == 7.0
        assert notation.bareme_utilise["consistance"]["points_max"] == 3.0


async def test_un_dossier_incomplet_est_elimine_avec_le_motif():
    async with SessionLocal() as db:
        poste = await monter_poste(db)
        candidature = await monter_candidature(db, poste, pieces=(PieceDossier.CV,))
        await evaluer_candidature(db, candidature)
        await db.commit()

        motifs = {e.motif for e in candidature.eliminations}
        assert MotifElimination.DOSSIER_INCOMPLET in motifs
        assert candidature.statut is StatutCandidature.ELIMINEE


async def test_une_donnee_extraite_par_ia_n_elimine_pas_seule():
    """Le coeur de la règle : l'assistance propose, elle ne décide pas."""
    async with SessionLocal() as db:
        poste = await monter_poste(db)
        candidature = await monter_candidature(
            db,
            poste,
            niveau=NiveauDiplome.BAC_PLUS_2,  # insuffisant
            provenance_diplome=Provenance.EXTRAIT_IA,
        )
        await evaluer_candidature(db, candidature)
        await db.commit()

        elimination = next(
            e
            for e in candidature.eliminations
            if e.motif is MotifElimination.FORMATION_INSUFFISANTE
        )
        assert elimination.sur_donnee_non_verifiee is True
        assert candidature.statut is StatutCandidature.A_VERIFIER


async def test_la_meme_donnee_verifiee_elimine():
    async with SessionLocal() as db:
        poste = await monter_poste(db)
        candidature = await monter_candidature(
            db,
            poste,
            niveau=NiveauDiplome.BAC_PLUS_2,
            provenance_diplome=Provenance.VERIFIE_RH,
        )
        await evaluer_candidature(db, candidature)
        await db.commit()

        elimination = next(
            e
            for e in candidature.eliminations
            if e.motif is MotifElimination.FORMATION_INSUFFISANTE
        )
        assert elimination.sur_donnee_non_verifiee is False
        assert candidature.statut is StatutCandidature.ELIMINEE


async def test_un_motif_factuel_reste_opposable_malgre_une_extraction():
    """Une pièce absente est un fait : l'extraction n'y change rien."""
    async with SessionLocal() as db:
        poste = await monter_poste(db)
        candidature = await monter_candidature(
            db, poste, pieces=(), provenance_diplome=Provenance.EXTRAIT_IA
        )
        await evaluer_candidature(db, candidature)
        await db.commit()

        incomplet = next(
            e for e in candidature.eliminations if e.motif is MotifElimination.DOSSIER_INCOMPLET
        )
        assert incomplet.sur_donnee_non_verifiee is False


async def test_recalculer_ne_duplique_pas_les_motifs():
    """Sans le flush entre DELETE et INSERT, la contrainte d'unicité saute."""
    async with SessionLocal() as db:
        poste = await monter_poste(db)
        candidature = await monter_candidature(db, poste, pieces=(PieceDossier.CV,))

        for _ in range(3):
            await evaluer_candidature(db, candidature)
        await db.commit()

        motifs = (
            await db.execute(
                select(Elimination).where(Elimination.candidature_id == candidature.id)
            )
        ).scalars().all()
        assert len(motifs) == len({m.motif for m in motifs})

        notations = (
            await db.execute(select(Notation).where(Notation.candidature_id == candidature.id))
        ).scalars().all()
        assert len(notations) == 1


async def test_une_elimination_levee_survit_au_recalcul():
    async with SessionLocal() as db:
        poste = await monter_poste(db)
        candidature = await monter_candidature(db, poste, pieces=(PieceDossier.CV,))
        await evaluer_candidature(db, candidature)
        await db.flush()

        motif = next(
            e for e in candidature.eliminations if e.motif is MotifElimination.DOSSIER_INCOMPLET
        )
        motif.leve_le = datetime(2026, 8, 1)
        motif.leve_motif = "Lettre reçue séparément par email."
        await db.flush()

        await evaluer_candidature(db, candidature)
        await db.commit()

        rechargee = next(
            e for e in candidature.eliminations if e.motif is MotifElimination.DOSSIER_INCOMPLET
        )
        assert rechargee.leve_le is not None
        assert rechargee.actif is False
        # Le seul motif étant levé, la candidature repasse dans le processus.
        assert candidature.statut is not StatutCandidature.ELIMINEE


async def test_la_note_manuelle_survit_au_recalcul():
    async with SessionLocal() as db:
        poste = await monter_poste(db)
        candidature = await monter_candidature(db, poste)
        notation = await evaluer_candidature(db, candidature)
        await db.flush()

        notation.note_manuelle = 27.0
        notation.note_manuelle_motif = "Entretien téléphonique concluant."
        await db.flush()

        recalculee = await evaluer_candidature(db, candidature)
        await db.commit()

        assert float(recalculee.note_manuelle) == 27.0
        assert recalculee.note_retenue == 27.0


async def test_la_note_manuelle_decide_aussi_du_seuil():
    """Une note saisie à la main classe, ou elle ne sert à rien.

    Le franchissement du seuil se jugeait sur le calcul seul : un dossier
    remonté à 27 sous un seuil de 26 restait « sous le seuil », et la grille
    affichait 27/30 dans l'onglet des non-retenus sans qu'aucune ligne
    n'explique pourquoi.
    """
    async with SessionLocal() as db:
        poste = await monter_poste(db)
        poste.seuil_preselection = 26.0
        candidature = await monter_candidature(db, poste)
        notation = await evaluer_candidature(db, candidature)
        await db.flush()

        assert float(notation.total) < 26.0, "le dossier de départ doit être sous le seuil"

        notation.note_manuelle = 27.0
        notation.note_manuelle_motif = "Diplôme étranger reconnu équivalent après vérification."
        await db.flush()

        await evaluer_candidature(db, candidature)
        await db.commit()

        assert candidature.statut is StatutCandidature.PRESELECTIONNEE


async def test_la_restriction_du_poste_est_appliquee_depuis_la_base():
    async with SessionLocal() as db:
        poste = await monter_poste(
            db,
            restriction_age_max=35,
            restriction_justification="Limite d'âge du statut du personnel.",
        )
        candidature = await monter_candidature(db, poste, naissance=date(1980, 1, 1))
        await evaluer_candidature(db, candidature)
        await db.commit()

        motif = next(
            e for e in candidature.eliminations if e.motif is MotifElimination.CONDITION_AGE
        )
        assert "statut du personnel" in motif.justification_poste
        assert candidature.statut is StatutCandidature.ELIMINEE


async def test_la_date_de_cloture_de_l_avis_sert_de_reference():
    """L'ancienneté s'arrête à la clôture, pas au jour du calcul."""
    async with SessionLocal() as db:
        poste = await monter_poste(db)
        # Débuté le 01/09/2016 : 9 ans et 11 mois au 31/07/2026, sous les 10 ans.
        candidature = await monter_candidature(db, poste, debut=date(2016, 9, 1))
        await evaluer_candidature(db, candidature)
        await db.commit()

        motifs = {e.motif for e in candidature.eliminations}
        assert MotifElimination.EXPERIENCE_INSUFFISANTE in motifs


async def test_candidature_hors_delai_depuis_la_date_de_reception():
    async with SessionLocal() as db:
        poste = await monter_poste(db)
        candidature = await monter_candidature(
            db, poste, recue_le=datetime(2026, 8, 5, 9, 0)
        )
        await evaluer_candidature(db, candidature)
        await db.commit()

        assert MotifElimination.HORS_DELAI in {e.motif for e in candidature.eliminations}


async def test_evaluer_tout_un_poste():
    async with SessionLocal() as db:
        poste = await monter_poste(db)
        await monter_candidature(db, poste)
        await monter_candidature(db, poste, pieces=(PieceDossier.CV,))
        await db.commit()

        traitees = await evaluer_poste(db, poste.id)
        await db.commit()
        assert traitees == 2

        notations = (await db.execute(select(Notation))).scalars().all()
        assert len(notations) == 2


async def test_abaisser_le_seuil_sans_justification_est_refuse():
    from app.services.preselection import definir_seuil

    async with SessionLocal() as db:
        poste = await monter_poste(db)
        with pytest.raises(ValueError, match="justification"):
            definir_seuil(poste, 15.0)

        definir_seuil(poste, 15.0, "Poste en tension, trois candidatures reçues.")
        assert float(poste.seuil_preselection) == 15.0
        assert poste.seuil_justification

        # Relever ne demande rien.
        definir_seuil(poste, 25.0)
        assert float(poste.seuil_preselection) == 25.0


async def test_le_seuil_abaisse_du_poste_est_pris_en_compte():
    async with SessionLocal() as db:
        poste = await monter_poste(
            db,
            seuil_preselection=5.0,
            seuil_nominal=20.0,
            seuil_justification="Poste en tension, trois candidatures reçues.",
            annees_experience_min=0,
            annees_experience_specifique_min=0,
        )
        candidature = await monter_candidature(db, poste, debut=date(2024, 1, 1))
        notation = await evaluer_candidature(db, candidature)
        await db.commit()

        assert float(notation.seuil) == 5.0
        assert notation.atteint_le_seuil is True
