"""Jeu de démonstration de la chaîne de recrutement.

Il ne s'agit pas de remplir la base, mais de raconter le processus : un mandat
encore en phase amont, deux mandats gagnés, et un poste dont les candidatures
couvrent *chaque* issue possible — présélectionné, sous le seuil, éliminé pour
chacun des motifs, en attente de relecture, doublon, note manuelle, motif levé.

Ouvrir la grille de ce poste doit suffire à comprendre l'outil.
"""

from __future__ import annotations

import io
import logging
from datetime import date, datetime, timedelta

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.referentiel import PieceDossier, Sexe, TypeAvis
from app.models import (
    AccesClient,
    Avis,
    Candidat,
    Candidature,
    Client,
    DiplomeCandidat,
    EchangeClient,
    EtapeMandat,
    ExperienceCandidat,
    Mandat,
    MessageEnvoye,
    ModeleDocument,
    PieceCandidature,
    Poste,
    Provenance,
    Rapport,
    SourceCandidature,
    StatutAvis,
    StatutMandat,
)
from app.services import entretiens, storage
from app.services.preselection import charger_candidature, evaluer_candidature

logger = logging.getLogger(__name__)

# Repères temporels calés sur aujourd'hui : la démo ne se périme pas.
AUJOURD_HUI = date.today()
CLOTURE = AUJOURD_HUI + timedelta(days=45)
PUBLICATION = AUJOURD_HUI - timedelta(days=15)
RECEPTION = datetime.combine(AUJOURD_HUI - timedelta(days=7), datetime.min.time())

LM = PieceDossier.LETTRE_MOTIVATION.value
CV = PieceDossier.CV.value
DIPLOMES = PieceDossier.COPIE_DIPLOMES.value
ATTESTATIONS = PieceDossier.ATTESTATIONS_TRAVAIL.value


def _pdf(titre: str, lignes: list[str]) -> bytes:
    """Un document lisible, généré localement : la démo n'a aucun fichier à
    embarquer, et la prévisualisation dans le tiroir montre du vrai contenu."""
    tampon = io.BytesIO()
    page = canvas.Canvas(tampon, pagesize=A4)
    page.setTitle(titre)
    y = 270 * mm
    page.setFont("Helvetica-Bold", 13)
    page.drawString(20 * mm, y, titre)
    y -= 10 * mm
    for ligne in lignes:
        if y < 20 * mm:
            page.showPage()
            y = 270 * mm
        page.setFont("Helvetica-Bold" if ligne.isupper() and ligne.strip() else "Helvetica", 10)
        page.drawString(20 * mm, y, ligne[:110])
        y -= 6 * mm
    page.save()
    return tampon.getvalue()


async def _ranger(chemin_mime: str, donnees: bytes) -> str:
    depot = storage.get_storage()
    return await depot.save(storage.build_key(chemin_mime), donnees)


class _Profil:
    """Un candidat de démonstration et l'issue qu'il doit illustrer."""

    def __init__(
        self,
        nom: str,
        prenom: str,
        *,
        illustre: str,
        niveau: int = 5,
        domaine: str = "gestion des ressources humaines",
        debut: date = date(2013, 1, 1),
        fin: date | None = None,
        domaines_exp: tuple[str, ...] = ("gestion des ressources humaines",),
        pays: str = "Togo",
        naissance: date = date(1985, 6, 12),
        sexe: Sexe = Sexe.FEMININ,
        langues: tuple[str, ...] = ("français",),
        certifications: tuple[str, ...] = (),
        pieces: tuple[str, ...] = (LM, CV, DIPLOMES),
        recue_le: datetime | None = None,
        source: SourceCandidature = SourceCandidature.FORMULAIRE,
        provenance: Provenance = Provenance.DECLARE,
        sans_parcours: bool = False,
        empreinte_partagee: str | None = None,
    ) -> None:
        self.__dict__.update(locals())
        del self.__dict__["self"]


PROFILS = [
    _Profil(
        "Kodjo", "Amina",
        illustre="Présélectionnée en tête : BAC+5, 13 ans, expérience à l'étranger",
        debut=date(2013, 1, 1), pays="Côte d'Ivoire",
        langues=("français", "anglais"), certifications=("Certification RH — CIPD",),
        pieces=(LM, CV, DIPLOMES, ATTESTATIONS),
    ),
    _Profil(
        "Mensah", "Afiwa",
        illustre="Présélectionnée : profil solide, sans extras",
        debut=date(2016, 3, 1),
    ),
    _Profil(
        "Agbeko", "Yawo",
        illustre="Présélectionné de justesse",
        debut=date(2017, 9, 1), sexe=Sexe.MASCULIN, naissance=date(1988, 2, 3),
    ),
    _Profil(
        "Lawson", "Koffi",
        # Niveau exactement requis et ancienneté au minimum : rien ne
        # l'élimine, mais le total reste sous la barre.
        illustre="Éligible, mais sous le seuil : aucun motif, note insuffisante",
        niveau=5, debut=CLOTURE.replace(year=CLOTURE.year - 8),
        sexe=Sexe.MASCULIN, naissance=date(1990, 11, 8),
    ),
    _Profil(
        "Sossou", "Ayélé",
        illustre="Éliminée : formation inférieure au niveau demandé (BAC+3)",
        niveau=3, debut=date(2014, 1, 1),
    ),
    _Profil(
        "Bakari", "Ibrahim",
        illustre="Éliminé : formation hors domaine (droit)",
        domaine="droit", domaines_exp=("droit",), sexe=Sexe.MASCULIN,
        debut=date(2012, 1, 1), naissance=date(1983, 4, 20),
    ),
    _Profil(
        "Adjovi", "Sena",
        illustre="Éliminée : expérience insuffisante",
        debut=date(2023, 6, 1),
    ),
    _Profil(
        "Tchalla", "Komi",
        illustre="Éliminé : dossier incomplet (lettre de motivation absente)",
        pieces=(CV, DIPLOMES), sexe=Sexe.MASCULIN, debut=date(2014, 5, 1),
        naissance=date(1986, 9, 30),
    ),
    _Profil(
        "Amouzou", "Délali",
        illustre="Éliminée : candidature reçue après la clôture",
        debut=date(2013, 2, 1),
        recue_le=datetime.combine(CLOTURE + timedelta(days=3), datetime.min.time()),
    ),
    _Profil(
        "Dossou", "Marius",
        illustre="Reçu par email, pas encore dépouillé : en attente de relecture",
        sexe=Sexe.MASCULIN, sans_parcours=True, pieces=(CV,),
        source=SourceCandidature.EMAIL, provenance=Provenance.EXTRAIT_IA,
        naissance=date(1987, 7, 14),
    ),
    _Profil(
        "Kodjo", "Amina",
        # Un fichier identique serait refusé au dépôt ; celui-ci renvoie des
        # pièces différentes depuis la même adresse — c'est le cas que l'on
        # signale sans l'écarter, parce que la seconde version est souvent la
        # bonne.
        illustre="Renvoi depuis la même adresse : signalé, jamais écarté d'office",
        debut=date(2013, 1, 1), pays="Côte d'Ivoire",
        langues=("français", "anglais"),
        pieces=(LM, CV, DIPLOMES),
        source=SourceCandidature.EMAIL,
    ),
]


async def _creer_candidature(
    db: AsyncSession, poste: Poste, profil: _Profil, fichiers: dict[str, str]
) -> Candidature:
    candidat = Candidat(
        nom=profil.nom,
        prenom=profil.prenom,
        email=f"{profil.prenom}.{profil.nom}@example.com".lower().replace(" ", ""),
        telephone="90 00 00 00",
        adresse="Lomé, Togo",
        date_naissance=profil.naissance,
        sexe=profil.sexe,
        nationalites=["Togolaise"],
        langues=list(profil.langues),
        certifications=list(profil.certifications),
        provenance=profil.provenance,
    )
    db.add(candidat)
    await db.flush()

    if not profil.sans_parcours:
        db.add(
            DiplomeCandidat(
                candidat_id=candidat.id,
                intitule=f"Diplôme en {profil.domaine}",
                niveau=profil.niveau,
                domaine=profil.domaine,
                etablissement="Université de Lomé",
                annee=2010,
                provenance=profil.provenance,
            )
        )
        db.add(
            ExperienceCandidat(
                candidat_id=candidat.id,
                poste="Responsable des ressources humaines",
                employeur="Groupe Sarakawa",
                debut=profil.debut,
                fin=profil.fin,
                domaines=list(profil.domaines_exp),
                pays=profil.pays,
                provenance=profil.provenance,
            )
        )

    candidature = Candidature(
        poste_id=poste.id,
        candidat_id=candidat.id,
        source=profil.source,
        recue_le=profil.recue_le or RECEPTION,
        notes_rh=profil.illustre,
    )
    db.add(candidature)
    await db.flush()

    for code in profil.pieces:
        # Le doublon partage volontairement l'empreinte du dossier d'origine :
        # c'est ce que la détection est censée voir.
        empreinte = (
            profil.empreinte_partagee
            if profil.empreinte_partagee and code == CV
            else f"{candidature.id}-{code}"
        )
        db.add(
            PieceCandidature(
                candidature_id=candidature.id,
                type_piece=code,
                nom_fichier=f"{code.lower()}-{profil.nom.lower()}.pdf",
                chemin_stockage=fichiers[code],
                type_mime="application/pdf",
                taille_octets=2048,
                empreinte=empreinte,
            )
        )
    await db.flush()

    chargee = await charger_candidature(db, candidature.id)
    await evaluer_candidature(db, chargee)
    return chargee


async def _semer_entretien(
    db: AsyncSession,
    candidature: Candidature,
    *,
    jure: str,
    notes: dict[str, float],
    commentaires: dict[str, str] | None = None,
    jury: str = "",
    observations: str = "",
) -> None:
    """Une fiche d'entretien de démonstration, passée par le service réel.

    Écrire les lignes à la main donnerait une fiche que le service n'aurait pas
    validée — et donc une démonstration qui ne prouve rien du chemin réel.

    Une fiche par juré : le cabinet fait siéger un panel et retient la moyenne.
    La démonstration doit le montrer, sinon l'écran des entretiens paraît prévu
    pour une personne seule.
    """
    await entretiens.enregistrer(
        db,
        await charger_candidature(db, candidature.id),
        entretiens.SaisieEntretien(
            notes=notes,
            commentaires=commentaires or {},
            jure=jure,
            date_entretien=CLOTURE,
            jury=jury,
            observations=observations,
        ),
    )


async def _wipe(db: AsyncSession) -> None:
    """Rejouable : la démo est remplacée, jamais dupliquée."""
    # L'ordre suit les dépendances ; les cascades font le reste.
    await db.execute(delete(EchangeClient))
    await db.execute(delete(EtapeMandat))
    await db.execute(delete(AccesClient))
    await db.execute(delete(Rapport))
    await db.execute(delete(MessageEnvoye))
    await db.execute(delete(ModeleDocument))
    await db.execute(delete(Candidature))
    await db.execute(delete(Candidat))
    await db.execute(delete(Avis))
    await db.execute(delete(Poste))
    await db.execute(delete(Mandat))
    await db.execute(delete(Client))
    await db.flush()


async def semer(db: AsyncSession) -> dict:
    await _wipe(db)

    # --- documents partagés par tous les dossiers --------------------------
    fichiers = {
        LM: await _ranger(
            "application/pdf",
            _pdf("Lettre de motivation", ["Madame, Monsieur,", "", "Je vous soumets ma candidature."]),
        ),
        CV: await _ranger(
            "application/pdf",
            _pdf(
                "Curriculum vitae",
                [
                    "FORMATION",
                    "2010 — Master en gestion des ressources humaines, Université de Lomé",
                    "",
                    "EXPERIENCE PROFESSIONNELLE",
                    "2013 à ce jour — Responsable RH, Groupe Sarakawa, Lomé",
                    "   Encadrement des équipes, paie, relations sociales.",
                ],
            ),
        ),
        DIPLOMES: await _ranger("application/pdf", _pdf("Copie des diplômes", ["Master, 2010."])),
        ATTESTATIONS: await _ranger(
            "application/pdf", _pdf("Attestations de travail", ["Groupe Sarakawa, 2013-2026."])
        ),
    }

    # --- 1. mandat encore en phase amont -----------------------------------
    transco = Client(nom="TRANSCO CLSG", secteur="Énergie — transport d'électricité")
    db.add(transco)
    await db.flush()
    db.add(
        Mandat(
            client_id=transco.id,
            reference="AMI-2026-031",
            intitule="Recrutement du Directeur Général",
            statut=StatutMandat.AMI_SOUMIS,
            type_attribution=TypeAvis.INTERNATIONAL,
            date_ami=AUJOURD_HUI - timedelta(days=20),
            notes=(
                "Manifestation d'intérêt déposée. En attente de la liste restreinte : "
                "aucun poste n'est ouvert et aucun candidat n'est encore concerné."
            ),
        )
    )

    # --- 2. mandat gagné, le showcase principal ----------------------------
    dogta = Client(
        nom="Dogta-Lafiè",
        secteur="Santé — société de gestion hospitalière",
        contact_nom="Direction générale",
        contact_email="contact@dogta-lafie.example",
    )
    db.add(dogta)
    await db.flush()

    mandat = Mandat(
        client_id=dogta.id,
        reference="AO-2026-014",
        intitule="Recrutement de cadres hospitaliers",
        statut=StatutMandat.GAGNE,
        type_attribution=TypeAvis.NATIONAL,
        date_ami=AUJOURD_HUI - timedelta(days=90),
        date_offre=AUJOURD_HUI - timedelta(days=60),
        date_attribution=AUJOURD_HUI - timedelta(days=30),
    )
    db.add(mandat)
    await db.flush()

    poste = Poste(
        mandat_id=mandat.id,
        intitule="Directeur des Ressources Humaines",
        departement="Ressources Humaines",
        description=(
            "Piloter la fonction RH de l'établissement : recrutement, paie, relations "
            "sociales et développement des compétences."
        ),
        missions=[
            "Définir et mettre en œuvre la politique RH",
            "Encadrer l'équipe RH et la gestion de la paie",
            "Conduire le dialogue social",
            "Piloter le plan de formation",
        ],
        nombre_a_pourvoir=1,
        niveau_min=5,
        domaines_acceptes=["gestion des ressources humaines", "droit social", "management"],
        annees_experience_min=8,
        annees_experience_specifique_min=5,
        domaines_experience=["gestion des ressources humaines"],
        pieces_requises=[LM, CV, DIPLOMES],
        pieces_facultatives=[ATTESTATIONS],
        langues_requises=["français"],
    )
    db.add(poste)
    await db.flush()

    db.add(
        Avis(
            poste_id=poste.id,
            reference="DL-2026-007",
            type_avis=TypeAvis.NATIONAL,
            statut=StatutAvis.PUBLIE,
            date_publication=PUBLICATION,
            date_cloture=CLOTURE,
            canaux=["EmploiTogo", "LinkedIn", "Site institutionnel"],
            texte=(
                "Dogta-Lafiè recrute un Directeur des Ressources Humaines. "
                "Les dossiers sont reçus jusqu'à la date de clôture."
            ),
        )
    )
    await db.flush()

    creees = []
    for profil in PROFILS:
        creees.append(await _creer_candidature(db, poste, profil, fichiers))

    # Une note manuelle motivée sur la deuxième candidate : les RH priment.
    # La notation est relue depuis la base : celle portée par l'objet chargé
    # avant l'évaluation est antérieure à la ligne qui vient d'être écrite.
    seconde = await charger_candidature(db, creees[1].id)
    seconde.notation.note_manuelle = 27.0
    seconde.notation.note_manuelle_motif = (
        "Entretien téléphonique très favorable ; expérience du secteur hospitalier."
    )
    await db.flush()
    # Réévaluer : la catégorie remise au client suit la note retenue, et c'est
    # ce que fait l'application quand une note est saisie. Écrire la note sans
    # ce passage donnerait une démonstration qui ne se comporte pas comme le
    # produit — un dossier à 27/30 étiqueté « partiellement qualifié ».
    await evaluer_candidature(db, await charger_candidature(db, seconde.id))

    # Un motif levé sur le dossier incomplet : la pièce est arrivée à part.
    incomplet = creees[7]
    for motif in incomplet.eliminations:
        motif.leve_le = datetime.now()
        motif.leve_motif = "Lettre de motivation reçue séparément par email, versée au dossier."
    await db.flush()
    await evaluer_candidature(db, await charger_candidature(db, incomplet.id))

    # Deux entretiens saisis, dont un partiel : la démonstration doit montrer
    # les deux étapes de la note sur 100, et la différence entre un résultat et
    # un acquis en cours de séance.
    JURY = "Mme Adjovi (DRH Dogta-Lafiè), M. Lawson (Kapi Consult)"

    # Deux jurés sur le même dossier, avec des notes proches mais distinctes :
    # c'est ce qui fait apparaître la moyenne et l'écart entre jurés, et donc
    # la raison d'être du panel.
    await _semer_entretien(
        db,
        creees[1],
        jure="Mme Adjovi",
        notes={
            "PRESENTATION": 2,
            "MOTIVATION": 2,
            "RELATIONNELLES": 17,
            "TECHNIQUES": 22,
            "POTENTIEL": 17,
            "CONNAISSANCES_CLIENT": 1,
        },
        commentaires={
            "TECHNIQUES": "Maîtrise des outils de paie et du droit social togolais.",
            "RELATIONNELLES": "Exemples précis de médiation d'un conflit d'équipe.",
            "POTENTIEL": "A conduit une réorganisation de service sur deux ans.",
        },
        jury=JURY,
        observations=(
            "Candidate la plus solide du panel. Connaît le secteur hospitalier "
            "et se projette dans le poste."
        ),
    )
    await _semer_entretien(
        db,
        creees[1],
        jure="M. Lawson",
        notes={
            "PRESENTATION": 1.5,
            "MOTIVATION": 2,
            "RELATIONNELLES": 15,
            "TECHNIQUES": 23,
            "POTENTIEL": 15,
            "CONNAISSANCES_CLIENT": 1,
        },
        commentaires={
            "PRESENTATION": "Exposé clair, un peu long sur la partie technique.",
        },
        jury=JURY,
        observations="Profil solide, à confirmer sur la conduite du changement.",
    )
    # Une fiche partielle : la note sur 100 doit s'annoncer comme telle plutôt
    # que de passer pour un résultat.
    await _semer_entretien(
        db,
        creees[3],
        jure="Mme Adjovi",
        notes={"TECHNIQUES": 18, "RELATIONNELLES": 12},
        commentaires={"TECHNIQUES": "Bonnes bases, moins à l'aise sur la GPEC."},
        jury=JURY,
        observations="Séance interrompue, à reprendre.",
    )

    # --- 3. mandat de gré à gré, avec condition restrictive ----------------
    sarakawa = Client(nom="Groupe Hôtelier Sarakawa", secteur="Hôtellerie et restauration")
    db.add(sarakawa)
    await db.flush()
    mandat_gag = Mandat(
        client_id=sarakawa.id,
        intitule="Recrutement d'un Chef comptable",
        statut=StatutMandat.GAGNE,
        type_attribution=TypeAvis.GRE_A_GRE,
        date_attribution=AUJOURD_HUI - timedelta(days=10),
        notes="Attribué de gré à gré : ni AMI ni appel d'offre.",
    )
    db.add(mandat_gag)
    await db.flush()
    db.add(
        Poste(
            mandat_id=mandat_gag.id,
            intitule="Chef comptable",
            departement="Finances",
            niveau_min=4,
            domaines_acceptes=["comptabilité", "finance"],
            annees_experience_min=5,
            annees_experience_specifique_min=3,
            domaines_experience=["comptabilité"],
            pieces_requises=[CV, DIPLOMES],
            langues_requises=["français"],
            # Illustre la condition restrictive : déclarée, justifiée, journalisée.
            restriction_age_max=45,
            restriction_justification=(
                "Limite d'âge fixée par le statut du personnel du client pour les postes "
                "d'encadrement comptable."
            ),
        )
    )
    await db.commit()

    from sqlalchemy import select

    cle = (
        await db.execute(select(Avis.cle_publique).where(Avis.poste_id == poste.id))
    ).scalars().first()

    return {
        "clients": 3,
        "mandats": 3,
        "postes": 2,
        "candidatures": len(PROFILS),
        "cle_publique_avis": cle,
    }
