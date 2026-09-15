"""Le rapport de recrutement : structure, chiffres, rédaction assistée.

Ce que le cabinet livre au terme d'un mandat. Il raconte ce qui a été fait — la
publication, les dossiers reçus, la présélection, les entretiens — et présente
les candidats proposés.

Trois principes.

**Les chiffres viennent d'ici, jamais du modèle.** Effectifs, notes, moyennes,
répartition : tout est calculé et figé dans `donnees`. Le texte rédigé s'appuie
dessus mais ne les produit pas. Un rapport dont les chiffres sortiraient d'une
rédaction automatique serait indéfendable devant un client, et invérifiable.

**La rédaction est une proposition.** Chaque section porte son origine —
`PROPOSEE` ou `REDIGEE` — et un rapport ne se valide qu'après relecture. Le
statut le dit : brouillon, en relecture, validé.

**Le rapport est figé une fois écrit.** `donnees` conserve l'état des dossiers
au moment de la rédaction. Réexporter six mois plus tard rend le même document,
même si les candidatures ont changé entre-temps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain import Qualification
from app.llm.factory import get_provider
from app.models import (
    Avis,
    Candidat,
    Candidature,
    Mandat,
    Notation,
    Poste,
    Rapport,
    StatutCandidature,
)
from app.services import entretiens as service_entretiens
from app.services.preselection import construire_bareme, construire_exigences

logger = logging.getLogger(__name__)

ORIGINE_PROPOSEE = "PROPOSEE"
ORIGINE_REDIGEE = "REDIGEE"
ORIGINE_CALCULEE = "CALCULEE"


@dataclass(frozen=True, slots=True)
class SectionType:
    """Une section du rapport type, avec la consigne qui sert à la rédiger."""

    code: str
    titre: str
    consigne: str
    # Une section calculée n'est jamais proposée par le modèle : elle est
    # produite par le code, à partir de `donnees`.
    calculee: bool = False
    # Le niveau de titre, 1 ou 2. Le rapport remis est hiérarchisé —
    # « Méthodologie » porte « Présélection » et « Critères éliminatoires » —
    # et une trame plate produisait sept titres de même rang, où le lecteur ne
    # voyait plus ce qui dépendait de quoi.
    niveau: int = 1
    # Le bloc de tableaux à joindre sous la prose de cette section, s'il y en
    # a. Dans le document remis, un tableau ne porte pas de titre à lui : il
    # suit la phrase qui l'annonce, à l'intérieur de la même section. Les
    # séparer fabriquait des intertitres — « Effectifs par poste » — qui
    # n'existent nulle part dans le document du cabinet.
    tableaux: str = ""


# La trame du cabinet. Elle reproduit le rapport que Kapi Consult remet
# réellement — titres, ordre, niveaux et emplacement des tableaux — relevés sur
# « Rapport des entretiens - WAPP 2025 ». Ce n'est pas une trame inspirée du
# document : c'en est la structure.
#
# Ce qui s'y lit et qui ne s'invente pas :
#
# - « Démarche » et « Objectifs de la mission » sont deux sections à part
#   entière. Le rapport dit d'abord *comment* on a procédé et *pourquoi*, avant
#   de dire ce qu'on a trouvé.
# - « Méthodologie » n'a pas de contenu propre : elle porte deux sous-sections.
# - Les tableaux n'ont pas de titre à eux. Ils suivent la phrase qui les
#   annonce, dans la section qui les annonce.
# - Il n'y a pas de conclusion. Le document se termine sur le tableau des
#   résultats et la mention du détail annexé.
#
# Un client qui impose sa propre trame passe par un ModeleDocument, dont les
# sections remplacent celles-ci.
TRAME: tuple[SectionType, ...] = (
    SectionType(
        code="INTRODUCTION",
        titre="Introduction",
        consigne=(
            "Rédigez la section « Introduction », en trois paragraphes pleins "
            "d'environ soixante mots chacun.\n"
            "1. Le commanditaire : qui il est, son secteur, ce que les données "
            "en disent. N'inventez ni son activité ni son organisation si les "
            "données ne les donnent pas — dans ce cas, présentez-le par ce "
            "qu'on sait de lui et passez au poste.\n"
            "2. Le ou les postes à pourvoir : intitulé, département, nombre de "
            "postes, ce que le titulaire aura à faire d'après la description et "
            "les missions, et le motif du recrutement s'il ressort des données.\n"
            "3. Le mandat confié au cabinet et l'objet du présent document : "
            "ce dont il rend compte, jusqu'à quelle étape du processus."
        ),
    ),
    SectionType(
        code="DEMARCHE",
        titre="Démarche",
        consigne=(
            "Rédigez la section « Démarche ». Annoncez en une phrase que la "
            "démarche du cabinet s'est déroulée comme suit, puis énumérez les "
            "étapes effectivement franchies, une par ligne préfixée d'un tiret "
            "— élaboration de l'avis, publication, réception des dossiers, "
            "présélection sur dossier, entretiens structurés, sélection "
            "finale. N'énumérez que les étapes que les données attestent, et "
            "précisez chacune en une ligne : ce qu'elle a consisté à faire, et "
            "la date ou le nombre que les données lui attachent quand il y en "
            "a un. Terminez par un paragraphe d'une quarantaine de mots "
            "rappelant sur quelle période l'ensemble s'est déroulé, si les "
            "dates le permettent."
        ),
    ),
    SectionType(
        code="OBJECTIFS",
        titre="Objectifs de la mission",
        consigne=(
            "Rédigez la section « Objectifs de la mission », en deux temps.\n"
            "1. Un paragraphe d'environ soixante-dix mots sur l'objectif "
            "principal confié au cabinet : identifier et sélectionner, sur la "
            "base de critères définis à l'avance, les profils qui répondent le "
            "mieux à la description du poste ; dites pour quel poste et pour "
            "quel commanditaire.\n"
            "2. Une phrase d'annonce — « Le but général est de : » — suivie des "
            "buts, un par ligne préfixée d'un tiret : analyser chaque dossier "
            "sur les critères définis et retenir les plus pertinents, assister "
            "le commanditaire dans la conduite des entretiens structurés, "
            "établir un rapport faisant ressortir les résultats. Développez "
            "chacun d'une proposition qui dise ce qu'il implique concrètement "
            "pour cette mission-ci."
        ),
    ),
    SectionType(
        code="METHODOLOGIE",
        titre="Méthodologie",
        consigne="",
        # Un titre porteur, sans texte : ses deux sous-sections disent tout.
        calculee=True,
    ),
    SectionType(
        code="METHODE_PRESELECTION",
        titre="Présélection",
        niveau=2,
        consigne=(
            "Rédigez la sous-section « Présélection » de la méthodologie, en "
            "trois temps.\n"
            "1. Un paragraphe d'environ soixante mots : ce qu'est la "
            "présélection sur dossier, pourquoi elle constitue l'une des "
            "étapes décisives du processus, et ce qu'elle permet d'identifier "
            "à partir d'une revue de la consistance de chaque dossier.\n"
            "2. Un paragraphe annonçant que le cabinet a conçu une grille "
            "conforme au contenu du poste, et que chaque candidat a été évalué "
            "selon les rubriques ci-après.\n"
            "3. Les rubriques de la grille, une par ligne préfixée d'un tiret, "
            "avec pour chacune son nombre de points et, en une proposition, ce "
            "qu'elle mesure. Reprenez les intitulés et les points exactement "
            "tels que les données les donnent.\n"
            "Décrivez la grille ; ne commentez aucun candidat, et ne citez "
            "aucune note individuelle."
        ),
        tableaux="GRILLE_PRESELECTION",
    ),
    SectionType(
        code="CRITERES_ELIMINATOIRES",
        titre="Critères éliminatoires et Condition de Présélection",
        niveau=2,
        consigne=(
            "Rédigez la sous-section « Critères éliminatoires et Condition de "
            "Présélection », en trois temps.\n"
            "1. Une phrase annonçant les critères éliminatoires retenus pour "
            "le poste.\n"
            "2. Les conditions de base, une par ligne préfixée d'un tiret, "
            "**reprises exactement du bloc CONDITIONS DE BASE des données**. "
            "N'en ajoutez aucune et n'en retirez aucune. Une condition que les "
            "données disent « aucune » ou « non posée » se rapporte comme "
            "telle — « aucune limite d'âge n'a été fixée » — et ne se remplace "
            "jamais par une valeur plausible : une condition inventée dans ce "
            "rapport devient opposable au cabinet.\n"
            "3. Un ou deux paragraphes de conclusion : que les candidats ne "
            "remplissant pas ces conditions ont été écartés du processus, "
            "combien l'ont été, et combien de candidats sont proposés au "
            "commanditaire pour la suite. N'énumérez aucun nom.\n"
            "Ne dites jamais *pourquoi* un dossier a été retenu ou écarté "
            "au-delà des conditions listées ci-dessus. N'invoquez aucun "
            "critère « implicite », « attendu » ou « de cohérence » : il n'en "
            "existe pas. Si les chiffres surprennent — des dossiers éligibles "
            "et aucun présélectionné —, rapportez-les tels quels sans les "
            "expliquer."
        ),
    ),
    SectionType(
        code="RESULTATS_PRESELECTION",
        titre="Résultats de la présélection",
        consigne=(
            "Rédigez la section « Résultats de la présélection ».\n"
            "1. Un paragraphe annonçant, poste par poste, le nombre de "
            "dossiers reçus et soumis à évaluation. Écrivez les nombres en "
            "toutes lettres suivis du chiffre entre parenthèses — « Soixante-"
            "quatre (64) dossiers » — comme le fait le cabinet.\n"
            "2. Une phrase introduisant le tableau : « L'analyse des dossiers "
            "de candidature a permis d'obtenir les résultats suivants : », "
            "puis la marque [TABLEAU] sur une ligne seule.\n"
            "3. Après la marque, le commentaire des chiffres : pour chaque "
            "poste, le nombre de candidatures préqualifiées et, parmi elles, "
            "combien sont proposées pour la prochaine étape ; puis la "
            "répartition des qualifications et l'étendue des notes, si les "
            "données les donnent. Rapportez ces chiffres sans les modifier et "
            "n'en calculez aucun autre. **N'expliquez pas** pourquoi un "
            "dossier a été ou n'a pas été présélectionné : les données ne "
            "portent pas ce motif, et l'écrire reviendrait à l'inventer."
        ),
        tableaux="SYNTHESE_EFFECTIFS",
    ),
    SectionType(
        code="LISTE_PRESELECTIONNES",
        titre="Liste des candidats présélectionnés",
        niveau=2,
        consigne=(
            "Rédigez la sous-section « Liste des candidats présélectionnés », "
            "en un paragraphe d'une cinquantaine de mots : annoncez que les "
            "candidats retenus pour la suite du processus figurent dans le "
            "tableau ci-après, rappelez sur quelle base ils l'ont été — la "
            "note de présélection et le rang — et précisez, si les données le "
            "disent, ce qu'il advient en cas de désistement de l'un d'eux. Ne "
            "commentez aucun candidat et n'en citez aucun nom."
        ),
        tableaux="TABLEAU_PRESELECTION",
    ),
    SectionType(
        code="ENTRETIENS_STRUCTURES",
        titre="Entretiens structurés",
        consigne="",
        calculee=True,
    ),
    SectionType(
        code="GUIDE_ENTRETIEN",
        titre="Adoption du guide d'interview et la grille de notation",
        niveau=2,
        consigne=(
            "Rédigez la sous-section « Adoption du guide d'interview et la "
            "grille de notation », en deux paragraphes.\n"
            "1. Environ cinquante mots : le guide d'entretien proposé par le "
            "cabinet a été soumis au panel de recrutement et validé par lui ; "
            "dites à quoi sert un guide structuré — faire passer à chaque "
            "candidat le même entretien, et rendre les notes comparables.\n"
            "2. Une annonce de la grille reproduite ci-après, avec les "
            "rubriques qu'elle comporte et le total sur lequel elle porte, "
            "repris exactement des données. Ne commentez aucun candidat."
        ),
        tableaux="GRILLE_ENTRETIEN",
    ),
    SectionType(
        code="JURY",
        titre="Validation du jury de sélection et conduite des interviews",
        niveau=2,
        consigne=(
            "Rédigez la sous-section « Validation du jury de sélection et "
            "conduite des interviews », en un à deux paragraphes d'environ "
            "soixante mots : la composition du panel, qui a animé les "
            "entretiens, et le déroulement — combien de candidats ont été "
            "reçus, sur quelle période, selon quelles modalités — tels que les "
            "données les donnent. Si les données ne précisent ni le nombre de "
            "jurés ni les dates, écrivez la section sans eux : n'inventez ni "
            "un effectif de panel, ni une date, ni un lieu."
        ),
    ),
    SectionType(
        code="RESULTATS_ENTRETIENS",
        titre="Résultats des entretiens structurés",
        niveau=2,
        consigne=(
            "Rédigez la sous-section « Résultats des entretiens structurés ».\n"
            "Si les données ne portent aucune note d'entretien, écrivez une "
            "seule phrase constatant que les entretiens n'ont pas encore eu "
            "lieu, et rien d'autre : pas de classement, pas de tableau, pas "
            "d'explication de cette absence.\n"
            "Sinon :\n"
            "1. Une phrase annonçant que la compilation des notes des membres "
            "du panel a permis d'obtenir les résultats ci-dessous. Le tableau "
            "est inséré automatiquement après votre texte — ne l'écrivez pas, "
            "et ne reproduisez aucune note individuelle.\n"
            "2. Un paragraphe d'une quarantaine de mots rappelant comment la "
            "moyenne sur 100 se compose — la présélection et l'entretien, dans "
            "les proportions que les données donnent — de sorte qu'un lecteur "
            "puisse relire le classement sans revenir en arrière. Ne commentez "
            "aucun candidat, n'en recommandez aucun, et ne désignez pas de "
            "lauréat : la décision appartient au commanditaire."
        ),
        tableaux="TABLEAU_FINAL",
    ),
)

PAR_CODE = {s.code: s for s in TRAME}


# --- types de rapport --------------------------------------------------------
#
# Le cabinet ne remet pas un rapport mais trois, à trois moments différents, et
# ils n'ont pas les mêmes sections. Produire la trame complète à chaque fois
# obligeait à supprimer à la main les sections d'un stade qui n'a pas eu lieu —
# un « Classement final » vide dans un rapport de présélection, et le lecteur
# se demande ce qui manque.
#
# Le type se choisit **avant** la génération : c'est lui qui décide des
# sections, et il n'y a rien à retirer ensuite.


class TypeRapport(str, Enum):
    PRESELECTION = "PRESELECTION"
    ENTRETIENS = "ENTRETIENS"
    FINAL = "FINAL"

    @property
    def libelle(self) -> str:
        return _LIBELLES_RAPPORT[self]


_LIBELLES_RAPPORT: dict[TypeRapport, str] = {
    TypeRapport.PRESELECTION: "Rapport de présélection",
    TypeRapport.ENTRETIENS: "Rapport des entretiens",
    TypeRapport.FINAL: "Rapport final de recrutement",
}

# Les sections retenues par type, dans l'ordre de la trame.
_SECTIONS_PAR_TYPE: dict[TypeRapport, tuple[str, ...]] = {
    # Remis avant les entretiens : il s'arrête au classement des dossiers.
    TypeRapport.PRESELECTION: (
        "INTRODUCTION",
        "DEMARCHE",
        "OBJECTIFS",
        "METHODOLOGIE",
        "METHODE_PRESELECTION",
        "CRITERES_ELIMINATOIRES",
        "RESULTATS_PRESELECTION",
        "LISTE_PRESELECTIONNES",
    ),
    # Remis après le jury. L'introduction est rappelée ; le détail de la
    # démarche et des critères a déjà été livré au stade précédent.
    TypeRapport.ENTRETIENS: (
        "INTRODUCTION",
        "ENTRETIENS_STRUCTURES",
        # La grille du jury figure dans le rapport des entretiens : c'est elle
        # que le client a adoptée avant les auditions, et les notes ne se
        # relisent pas sans elle.
        "GUIDE_ENTRETIEN",
        "JURY",
        "RESULTATS_ENTRETIENS",
    ),
    # Le document complet, qui reprend toute la mission. C'est celui-ci qui
    # doit être superposable au rapport remis par le cabinet.
    TypeRapport.FINAL: tuple(s.code for s in TRAME),
}


def trame_pour(type_rapport: TypeRapport = TypeRapport.FINAL) -> tuple[SectionType, ...]:
    """Les sections d'un type de rapport.

    La trame reste la liste de référence des sections : un type y puise, il
    n'en définit aucune de son côté. Ajouter une section au rapport final la
    rend donc disponible aux autres types sans rien dupliquer.
    """
    codes = _SECTIONS_PAR_TYPE.get(type_rapport, _SECTIONS_PAR_TYPE[TypeRapport.FINAL])
    return tuple(PAR_CODE[code] for code in codes if code in PAR_CODE)


# --- collecte des chiffres --------------------------------------------------


async def rassembler(db: AsyncSession, mandat_id: str, poste_id: str | None) -> dict:
    """L'état chiffré du mandat, figé pour le rapport.

    Rien ici n'est une opinion : ce sont des comptages et des notes déjà
    inscrites. C'est ce socle qui rend le rapport vérifiable, et c'est lui
    qu'on conserve pour que l'export reste identique dans le temps.
    """
    mandat = (
        await db.execute(
            select(Mandat)
            .where(Mandat.id == mandat_id)
            .options(selectinload(Mandat.client))
        )
    ).scalar_one()

    requete = (
        select(Poste)
        .where(Poste.mandat_id == mandat_id)
        .options(selectinload(Poste.avis))
    )
    if poste_id:
        requete = requete.where(Poste.id == poste_id)
    postes = (await db.execute(requete)).scalars().all()

    donnees: dict = {
        "mandat": {
            "intitule": mandat.intitule,
            "reference": mandat.reference,
            "client": mandat.client.nom if mandat.client else "",
            "secteur": mandat.client.secteur if mandat.client else None,
            "date_attribution": (
                mandat.date_attribution.isoformat() if mandat.date_attribution else None
            ),
        },
        "postes": [],
    }

    for poste in postes:
        donnees["postes"].append(await _chiffres_poste(db, poste))
    return donnees


def _age_a(naissance, reference) -> int | None:
    """L'âge à la clôture de l'avis, comme partout ailleurs dans l'outil.

    Jamais à la date d'écriture du rapport : deux rapports produits à deux
    mois d'intervalle donneraient des âges différents pour le même dossier.
    """
    if naissance is None:
        return None
    fin = reference or date.today()
    age = fin.year - naissance.year
    if (fin.month, fin.day) < (naissance.month, naissance.day):
        age -= 1
    return age


def _rang_ordinal(rang: int) -> str:
    """« 1er », « 2e », « 3e » — la forme employée dans les rapports remis."""
    return "1er" if rang == 1 else f"{rang}e"


def _grille_preselection(poste: Poste) -> list[dict]:
    """Les critères de présélection du poste et leurs maxima.

    Pris sur le barème effectivement en vigueur pour ce poste — celui qui a été
    validé par le client, et non le barème type du cabinet, dont un mandat peut
    s'écarter.
    """
    bareme = construire_bareme(poste)
    lignes = [
        ("CONSISTANCE", "Consistance du dossier", bareme.consistance.points_max),
        ("FORMATION", "Formation académique", bareme.formation.points_max),
        (
            "EXPERIENCE_GENERALE",
            "Expérience générale",
            bareme.experience_generale.points_max,
        ),
    ]
    # Une exigence spécifique par ligne quand le poste en déclare plusieurs :
    # c'est ainsi que la grille les note, et le rapport doit montrer la même
    # décomposition que la grille.
    exigences = construire_exigences(poste).specifiques
    total_specifique = bareme.experience_specifique.points_max
    if len(exigences) <= 1:
        lignes.append(("EXPERIENCE_SPECIFIQUE", "Expérience spécifique", total_specifique))
    else:
        poids = [e.poids if e.poids > 0 else 1.0 for e in exigences]
        somme = sum(poids)
        for rang, (exigence, sien) in enumerate(zip(exigences, poids), start=1):
            lignes.append(
                (
                    f"EXPERIENCE_SPECIFIQUE_{rang}",
                    f"Expérience spécifique — {exigence.nom}",
                    round(total_specifique * sien / somme, 2),
                )
            )

    return [
        {"code": code, "libelle": libelle, "points_max": points}
        for code, libelle, points in lignes
    ] + [{"code": "TOTAL", "libelle": "Total", "points_max": bareme.total_max}]


def _entier(valeur) -> int | None:
    return None if valeur is None else int(valeur)


def _reel(valeur) -> float | None:
    """Un Numeric de SQLAlchemy revient en Decimal, que le JSON refuse."""
    return None if valeur is None else float(valeur)


def _conditions_eligibilite(poste: Poste) -> dict:
    """Les conditions de base du poste, telles qu'elles ont servi à écarter.

    Le rapport leur consacre une sous-section entière — « Critères
    éliminatoires et Condition de Présélection » — et la consigne demande de
    les énumérer : nationalité, formation, âge, expérience. Or rien de tout
    cela n'était transmis au modèle, qui devait donc rédiger la liste sans
    disposer de la liste. Il la comblait : un rapport remis à un client de
    Lomé annonçait « les candidats devaient être de nationalité togolaise »
    pour un poste qui n'a jamais porté de condition de nationalité.

    D'où la forme de ce qui suit. Chaque condition est renvoyée **même quand
    elle est absente**, avec `None` pour valeur : « aucune » est un fait, et
    un fait écrit se recopie, là où un silence s'interprète.
    """
    restriction_nationalites = list(poste.restriction_nationalites or ())
    # `seuil_preselection` est un Numeric : il revient en `Decimal`, que le
    # sérialiseur JSON refuse. `donnees` part en base sous forme JSON, et un
    # rapport ne s'enregistrait plus du tout. Les autres chiffres du bloc sont
    # des entiers, mais les convertir tous coûte moins cher qu'un oubli.
    return {
        "niveau_min": _entier(poste.niveau_min),
        "domaines_acceptes": list(poste.domaines_acceptes or ()),
        "annees_experience_min": _entier(poste.annees_experience_min),
        "annees_experience_specifique_min": _entier(
            poste.annees_experience_specifique_min
        ),
        "domaines_experience": list(poste.domaines_experience or ()),
        "nationalites": restriction_nationalites or None,
        "age_min": _entier(poste.restriction_age_min),
        "age_max": _entier(poste.restriction_age_max),
        "sexe": poste.restriction_sexe,
        "justification_restriction": poste.restriction_justification or None,
        "pieces_requises": list(poste.pieces_requises or ()),
        "langues_requises": list(poste.langues_requises or ()),
        "seuil_preselection": _reel(poste.seuil_preselection),
    }


async def _chiffres_poste(db: AsyncSession, poste: Poste) -> dict:
    candidatures = (
        await db.execute(
            select(Candidature)
            .where(Candidature.poste_id == poste.id)
            .options(
                selectinload(Candidature.candidat).selectinload(Candidat.diplomes),
                selectinload(Candidature.notation).selectinload(Notation.lignes),
                selectinload(Candidature.entretiens),
                selectinload(Candidature.eliminations),
            )
        )
    ).scalars().all()

    avis: Avis | None = poste.avis[0] if poste.avis else None
    bareme = service_entretiens.bareme_du_poste(poste)

    par_statut: dict[str, int] = {}
    for candidature in candidatures:
        cle = candidature.statut.value
        par_statut[cle] = par_statut.get(cle, 0) + 1

    lignes = []
    for candidature in candidatures:
        notation = candidature.notation
        if notation is None:
            continue
        consolidation = service_entretiens.consolider(
            list(candidature.entretiens or ()), bareme
        )
        candidat = candidature.candidat
        # Les colonnes du tableau « Candidatures préqualifiées » tel que le
        # cabinet le remet : nom, âge, diplôme, pays, note, rang, téléphone,
        # adresse. Elles sont figées ici avec le reste des chiffres — un
        # rapport réexporté dans six mois doit montrer le dossier tel qu'il
        # était, pas tel qu'il est devenu.
        principal = max(
            (d for d in candidat.diplomes),
            key=lambda d: (d.niveau, d.annee or 0),
            default=None,
        )
        lignes.append(
            {
                "nom": f"{candidat.nom.upper()} {candidat.prenom}".strip(),
                "age": _age_a(candidat.date_naissance, avis.date_cloture if avis else None),
                "diplome": principal.intitule if principal else None,
                "pays": (candidat.nationalites or [None])[0],
                "telephone": candidat.telephone,
                "email": candidat.email,
                "statut": candidature.statut.value,
                "qualification": candidature.qualification,
                # `note_retenue` et non `total` : une note saisie à la main par
                # les RH prime sur le calcul, et c'est elle qui a servi à
                # classer. Le rapport doit dire ce qui a été décidé.
                "note_preselection": notation.note_retenue,
                "note_preselection_max": float(notation.total_max) or None,
                "note_entretien": consolidation.total if consolidation.complet else None,
                "note_entretien_max": consolidation.total_max or None,
                "jures": consolidation.par_jure,
            }
        )

    # Total /100 quand les deux moitiés existent. La présélection compte pour
    # 30, l'entretien pour 70 : c'est le barème du cabinet, pas une convention
    # de ce module.
    for ligne in lignes:
        note_p = ligne["note_preselection"]
        max_p = ligne["note_preselection_max"]
        note_e = ligne["note_entretien"]
        max_e = ligne["note_entretien_max"]
        if None in (note_p, max_p) or not max_p:
            ligne["total_100"] = None
            ligne["preselection_sur_100"] = None
            continue
        # La note de présélection **ramenée sur 100**, qui est la colonne du
        # tableau remis au client. À ne pas confondre avec `part_preselection`,
        # qui est sa contribution pondérée au total (30 points au plus) : un
        # candidat à 27/30 vaut 90 dans la colonne et 27 dans le total.
        ligne["preselection_sur_100"] = round(note_p / max_p * 100, 2)
        part_p = note_p / max_p * 30
        if note_e is None or not max_e:
            ligne["total_100"] = None
            ligne["part_preselection"] = round(part_p, 2)
            continue
        ligne["part_preselection"] = round(part_p, 2)
        ligne["part_entretien"] = round(note_e / max_e * 70, 2)
        ligne["total_100"] = round(part_p + note_e / max_e * 70, 2)

    lignes.sort(
        key=lambda ligne: (
            ligne["total_100"] if ligne["total_100"] is not None else -1,
            ligne["note_preselection"] or -1,
        ),
        reverse=True,
    )
    # Le rang est figé avec le reste : c'est celui qu'annonce le rapport, et il
    # ne doit pas se recalculer différemment selon l'endroit qui le lit.
    #
    # Il se compte **parmi les préqualifiés**, comme dans la grille et dans le
    # document remis : classer sur l'ensemble des dossiers reçus produisait un
    # tableau de préqualifiés numéroté 1er, 2e, 4e, 5e — les rangs manquants
    # étant ceux des candidats écartés, que ce tableau ne montre pas. Un
    # lecteur y voit une erreur, ou pire, une omission.
    position = 0
    for ligne in lignes:
        if ligne.get("statut") != StatutCandidature.PRESELECTIONNEE.value:
            ligne["rang"] = None
            ligne["rang_libelle"] = None
            continue
        position += 1
        ligne["rang"] = position
        ligne["rang_libelle"] = _rang_ordinal(position)

    return {
        "id": poste.id,
        "intitule": poste.intitule,
        "departement": poste.departement,
        "description": poste.description,
        "missions": list(poste.missions or ()),
        "nombre_a_pourvoir": poste.nombre_a_pourvoir,
        "nombre_a_retenir": poste.nombre_a_retenir,
        "niveau_min": poste.niveau_min,
        "annees_experience_min": poste.annees_experience_min,
        "annees_experience_specifique_min": poste.annees_experience_specifique_min,
        # Les conditions de base, y compris celles que le poste ne pose pas.
        "conditions": _conditions_eligibilite(poste),
        "avis": {
            "reference": avis.reference if avis else None,
            "type": avis.type_avis.value if avis else None,
            "publie_le": (
                avis.date_publication.isoformat()
                if avis and avis.date_publication
                else None
            ),
            "cloture_le": (
                avis.date_cloture.isoformat() if avis and avis.date_cloture else None
            ),
        },
        "grille_entretien": [
            {
                "code": ligne.code,
                "libelle": ligne.libelle,
                "points_max": ligne.points_max,
                # La rubrique, quand la grille en a : les grilles négociées
                # s'organisent en sections numérotées dont le total est
                # annoncé (« II. Expérience professionnelle : 50 »).
                "section": ligne.section,
            }
            for ligne in bareme
        ],
        # Le barème de présélection tel qu'il a servi, ligne par ligne. Le
        # rapport reproduit la grille employée, il ne se contente pas d'y
        # renvoyer : c'est elle que le client a validée, et un rapport qui
        # annonce des notes sans dire sur quoi elles portent ne se relit pas.
        "grille_preselection": _grille_preselection(poste),
        "candidatures_recues": len(candidatures),
        "par_statut": par_statut,
        "eliminees": par_statut.get(StatutCandidature.ELIMINEE.value, 0),
        "preselectionnees": par_statut.get(StatutCandidature.PRESELECTIONNEE.value, 0),
        "qualifications": {
            q.value: sum(1 for c in candidatures if c.qualification == q.value)
            for q in Qualification
        },
        "classement": lignes,
    }


# --- rédaction --------------------------------------------------------------


def _lignes_conditions(poste: dict) -> list[str]:
    """Les conditions de base, énoncées une par une — absentes comprises.

    « Aucune condition de nationalité n'a été posée » est une phrase que le
    modèle recopie. Le silence, lui, s'interprète : demander d'énumérer la
    nationalité sans dire laquelle, c'est demander de l'inventer, et c'est
    exactement ce qui s'est produit.
    """
    conditions = poste.get("conditions") or {}
    if not conditions:
        # Un rapport produit avant que ces données ne soient collectées. On
        # retombe sur ce que le poste porte à la racine, sans rien affirmer
        # des conditions qu'on ne connaît pas.
        return [
            f"  Niveau minimum exigé : BAC+{poste.get('niveau_min')}",
            f"  Expérience minimale : {poste.get('annees_experience_min')} an(s), "
            f"dont {poste.get('annees_experience_specifique_min')} an(s) dans le domaine",
        ]

    lignes = [
        "  CONDITIONS DE BASE (conditions éliminatoires du poste, à reprendre "
        "telles quelles ; celles dites « aucune » doivent être présentées comme "
        "non exigées, jamais remplacées par une valeur) :",
        f"    - Formation : diplôme de niveau BAC+{conditions['niveau_min']} au minimum",
    ]

    domaines = conditions.get("domaines_acceptes") or []
    lignes.append(
        f"    - Domaines de formation acceptés : {', '.join(domaines)}"
        if domaines
        else "    - Domaines de formation acceptés : aucun domaine imposé"
    )

    generale = conditions.get("annees_experience_min") or 0
    specifique = conditions.get("annees_experience_specifique_min") or 0
    lignes.append(
        f"    - Expérience professionnelle générale : {generale} an(s) au minimum"
        if generale
        else "    - Expérience professionnelle générale : aucune durée minimale"
    )
    domaines_exp = conditions.get("domaines_experience") or []
    if specifique:
        precision = f" dans : {', '.join(domaines_exp)}" if domaines_exp else ""
        lignes.append(
            f"    - Expérience spécifique : {specifique} an(s) au minimum{precision}"
        )
    else:
        lignes.append("    - Expérience spécifique : aucune durée minimale")

    nationalites = conditions.get("nationalites")
    lignes.append(
        f"    - Nationalité : réservé aux ressortissants de {', '.join(nationalites)}"
        if nationalites
        else "    - Nationalité : AUCUNE condition de nationalité n'a été posée ; "
        "le poste était ouvert sans restriction de nationalité"
    )

    age_min, age_max = conditions.get("age_min"), conditions.get("age_max")
    if age_min and age_max:
        lignes.append(f"    - Âge : entre {age_min} et {age_max} ans")
    elif age_max:
        lignes.append(f"    - Âge : {age_max} ans au plus")
    elif age_min:
        lignes.append(f"    - Âge : {age_min} ans au moins")
    else:
        lignes.append("    - Âge : AUCUNE limite d'âge n'a été posée")

    if conditions.get("sexe"):
        lignes.append(f"    - Sexe : {conditions['sexe']}")
        if conditions.get("justification_restriction"):
            lignes.append(
                f"    - Justification de la restriction : "
                f"{conditions['justification_restriction']}"
            )

    pieces = conditions.get("pieces_requises") or []
    if pieces:
        lignes.append(f"    - Pièces exigées au dossier : {', '.join(pieces)}")
    langues = conditions.get("langues_requises") or []
    if langues:
        lignes.append(f"    - Langues exigées : {', '.join(langues)}")
    # Énoncé même à zéro. Le laisser tomber quand il vaut zéro laissait le
    # modèle déduire un seuil de ce qu'il voyait : « aucun dossier
    # présélectionné, notes de 17 à 28 » lui a fait écrire « faute de candidat
    # atteignant le seuil minimal de 17 points », qui n'existe pas.
    seuil = conditions.get("seuil_preselection")
    lignes.append(
        f"    - Seuil de présélection retenu : {seuil:g} point(s)"
        if seuil
        else "    - Seuil de présélection : AUCUN seuil de note n'a été fixé"
    )
    return lignes


def _contexte_textuel(donnees: dict, section: SectionType) -> str:
    """Ce qu'on donne à lire au modèle : des chiffres, pas des dossiers.

    Volontairement dépouillé de tout ce qui identifie un candidat. Un rapport
    nomme les personnes proposées dans ses tableaux, qui sont produits par le
    code ; la prose, elle, n'a aucune raison de manipuler des noms, et le lui
    interdire supprime la catégorie entière des erreurs d'attribution.
    """
    mandat = donnees.get("mandat", {})
    lignes = [
        f"Commanditaire : {mandat.get('client') or 'non précisé'}",
        f"Mandat : {mandat.get('intitule') or ''}",
    ]
    if mandat.get("reference"):
        lignes.append(f"Référence : {mandat['reference']}")
    if mandat.get("secteur"):
        lignes.append(f"Secteur du commanditaire : {mandat['secteur']}")
    if mandat.get("date_attribution"):
        lignes.append(f"Mandat attribué le : {mandat['date_attribution']}")

    for poste in donnees.get("postes", []):
        lignes.append("")
        lignes.append(f"Poste : {poste['intitule']}")
        if poste.get("departement"):
            lignes.append(f"  Département : {poste['departement']}")
        if poste.get("description"):
            lignes.append(f"  Description du poste : {poste['description']}")
        for mission in poste.get("missions") or ():
            lignes.append(f"  Mission confiée au titulaire : {mission}")
        lignes.append(f"  Postes à pourvoir : {poste['nombre_a_pourvoir']}")
        if poste.get("nombre_a_retenir"):
            lignes.append(
                f"  Candidats à proposer au commanditaire à l'issue de la "
                f"présélection : {poste['nombre_a_retenir']}"
            )
        lignes.extend(_lignes_conditions(poste))
        avis = poste.get("avis", {})
        if avis.get("reference"):
            lignes.append(f"  Référence de l'avis : {avis['reference']}")
        if avis.get("publie_le"):
            lignes.append(f"  Avis publié le : {avis['publie_le']}")
        if avis.get("cloture_le"):
            lignes.append(f"  Clôture des candidatures : {avis['cloture_le']}")
        if avis.get("type"):
            lignes.append(f"  Type d'avis : {avis['type']}")
        lignes.append(f"  Candidatures reçues : {poste['candidatures_recues']}")
        lignes.append(f"  Dossiers écartés à l'éligibilité : {poste['eliminees']}")
        lignes.append(f"  Dossiers présélectionnés : {poste['preselectionnees']}")
        qualifications = {
            code: nombre
            for code, nombre in (poste.get("qualifications") or {}).items()
            if nombre
        }
        if qualifications:
            lignes.append(
                "  Répartition des qualifications : "
                + ", ".join(
                    f"{_libelle_qualification(code)} : {nombre}"
                    for code, nombre in qualifications.items()
                )
            )
        # La grille de présélection manquait. La section « Présélection »
        # demande pourtant d'en rappeler les rubriques et leur pondération : le
        # modèle, honnête, répondait « les rubriques ne sont pas spécifiées dans
        # les données fournies » — une phrase d'excuse imprimée dans un rapport
        # remis au client, sous un tableau qui, lui, portait la grille.
        if poste.get("grille_preselection"):
            rubriques = ", ".join(
                f"{ligne['libelle']} ({ligne['points_max']:g} pts)"
                for ligne in poste["grille_preselection"]
                if ligne.get("code") != "TOTAL"
            )
            lignes.append(f"  Grille de présélection : {rubriques}")
        if poste.get("grille_entretien"):
            rubriques = ", ".join(
                f"{ligne['libelle']} ({ligne['points_max']} pts)"
                for ligne in poste["grille_entretien"]
            )
            lignes.append(f"  Grille d'entretien : {rubriques}")
        notes = [
            ligne["note_preselection"]
            for ligne in poste.get("classement", [])
            if ligne.get("note_preselection") is not None
        ]
        if notes:
            lignes.append(
                f"  Notes de présélection : de {min(notes):.1f} à {max(notes):.1f} "
                f"sur {poste['classement'][0].get('note_preselection_max') or '?'}"
            )
    return "\n".join(lignes)


def _raccourcir(texte: str, largeur: int = 44) -> str:
    """Coupe sur un mot, pas au milieu d'un.

    « Diplôme en gestion des ressources humain » dans un document remis au
    client se lit comme une faute de frappe, pas comme une troncature.
    """
    if len(texte) <= largeur:
        return texte
    coupe = texte[: largeur - 1].rsplit(" ", 1)[0]
    return f"{coupe or texte[: largeur - 1]}…"


# --- tableaux ---------------------------------------------------------------
#
# Les tableaux du rapport étaient alignés à l'espace, en texte. C'est lisible
# dans une police à chasse fixe — l'écran de relecture, l'export TXT — et
# **illisible partout ailleurs** : le DOCX, le PDF et l'ODT rendent chaque
# ligne comme un paragraphe en Calibri ou en Helvetica, où les espaces d'un
# alignement n'ont plus la même largeur que les caractères. Les colonnes se
# décalaient les unes après les autres, et la grille remise au client
# ressemblait à un brouillon.
#
# Un tableau se décrit donc ici en structure — colonnes, lignes, genre de
# chaque ligne — et chaque format le rend avec ses propres moyens : une vraie
# table dans le DOCX, le PDF et l'ODT, l'alignement à l'espace dans le TXT et
# dans l'aperçu. Le texte reste produit et stocké : il sert de repli pour un
# rapport ancien, et de contenu relisable et corrigeable à la main.

GENRE_NORMAL = "normal"
# Une rubrique de grille — « II. Expérience professionnelle : 50 » — et les
# critères qu'elle regroupe. Les grilles négociées avec un client s'organisent
# ainsi, et le rapport doit montrer la même hiérarchie que la grille signée.
GENRE_RUBRIQUE = "rubrique"
GENRE_DETAIL = "detail"
GENRE_TOTAL = "total"


@dataclass(frozen=True, slots=True)
class Colonne:
    libelle: str
    # Une colonne de points s'aligne à droite : c'est ainsi que les unités se
    # lisent les unes sous les autres.
    numerique: bool = False


@dataclass(frozen=True, slots=True)
class LigneTableau:
    cellules: tuple[str, ...]
    genre: str = GENRE_NORMAL


@dataclass(frozen=True, slots=True)
class Tableau:
    titre: str
    colonnes: tuple[Colonne, ...]
    lignes: tuple[LigneTableau, ...]

    def en_dict(self) -> dict:
        """La forme stockée dans `Rapport.sections`, et rendue par l'API."""
        return {
            "titre": self.titre,
            "colonnes": [
                {"libelle": c.libelle, "numerique": c.numerique} for c in self.colonnes
            ],
            "lignes": [
                {"cellules": list(l.cellules), "genre": l.genre} for l in self.lignes
            ],
        }


def _tableau(entetes: list[str], lignes: list[list[str]]) -> str:
    """Un tableau en texte à colonnes alignées.

    Le repli : ce que lisent l'export TXT et tout rendu sans mise en page.
    """
    colonnes = [len(e) for e in entetes]
    for ligne in lignes:
        for i, cellule in enumerate(ligne):
            colonnes[i] = max(colonnes[i], len(cellule))

    def rendre(valeurs: list[str]) -> str:
        return "  ".join(v.ljust(colonnes[i]) for i, v in enumerate(valeurs)).rstrip()

    separateur = "  ".join("-" * largeur for largeur in colonnes)
    return "\n".join([rendre(entetes), separateur, *(rendre(l) for l in lignes)])


def texte_des_tableaux(tableaux: list[Tableau]) -> str:
    """Les tableaux d'une section, rendus en texte aligné.

    C'est ce qui s'enregistre dans `contenu` : la section reste corrigeable à
    la main, et un format qui ne sait pas dessiner de table a toujours quelque
    chose à imprimer.
    """
    blocs: list[str] = []
    for tableau in tableaux:
        if not tableau.lignes:
            # Un tableau sans ligne porte tout de même son message — « aucune
            # candidature préqualifiée à ce stade » tient dans son titre.
            blocs.append(tableau.titre)
            continue
        corps = [
            [
                # L'indentation remplace en texte ce que la mise en page rend
                # par un retrait de cellule.
                f"   {cellule}" if l.genre == GENRE_DETAIL and i == 0 else cellule
                for i, cellule in enumerate(l.cellules)
            ]
            for l in tableau.lignes
        ]
        rendu = _tableau([c.libelle for c in tableau.colonnes], corps)
        blocs.append(f"{tableau.titre}\n{rendu}" if tableau.titre else rendu)
    return "\n\n".join(blocs)


def tableau_synthese(donnees: dict) -> list[Tableau]:
    """Effectifs par poste — le premier tableau du rapport remis.

    Postes, dossiers analysés, préqualifiés, éliminés, et la ligne de total.
    C'est le tableau que le lecteur regarde en premier pour savoir de quel
    volume on parle.
    """
    lignes: list[LigneTableau] = []
    totaux = [0, 0, 0]
    for poste in donnees.get("postes", []):
        recues = poste.get("candidatures_recues", 0)
        prequalifies = poste.get("preselectionnees", 0)
        elimines = poste.get("eliminees", 0)
        totaux = [
            totaux[0] + recues,
            totaux[1] + prequalifies,
            totaux[2] + elimines,
        ]
        lignes.append(
            LigneTableau(
                (poste["intitule"], str(recues), str(prequalifies), str(elimines))
            )
        )
    if not lignes:
        return [Tableau("Aucun poste sur ce mandat.", (), ())]
    if len(lignes) > 1:
        lignes.append(
            LigneTableau(("TOTAL", *(str(v) for v in totaux)), GENRE_TOTAL)
        )

    return [
        Tableau(
            # Sans titre : dans le document remis, ce tableau suit directement
            # la phrase qui l'annonce, à l'intérieur de « Résultats de la
            # présélection ». Lui donner un intertitre en inventerait un.
            titre="",
            # Les intitulés du document, mot pour mot.
            colonnes=(
                Colonne("Postes"),
                Colonne("Nombre de dossiers analysés", numerique=True),
                Colonne("Effectif Préqualifié", numerique=True),
                Colonne("Nombre de candidats éliminés", numerique=True),
            ),
            lignes=tuple(lignes),
        )
    ]


_ROMAINS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")


def grille_preselection_tableau(donnees: dict) -> list[Tableau]:
    """La grille de présélection employée, poste par poste.

    Le document du cabinet décrit ces rubriques en prose. Les reproduire en
    tableau est un écart assumé : c'est la grille que le client valide avant le
    lancement, et un tableau se vérifie ligne à ligne là où un paragraphe
    oblige à recompter.
    """
    tableaux: list[Tableau] = []
    for poste in donnees.get("postes", []):
        lignes = poste.get("grille_preselection") or []
        if not lignes:
            continue
        tableaux.append(
            Tableau(
                titre=f"Grille de présélection — {poste['intitule']}",
                colonnes=(Colonne("Critère"), Colonne("Points", numerique=True)),
                lignes=tuple(
                    LigneTableau(
                        (l["libelle"], f"{l['points_max']:g}"),
                        GENRE_TOTAL if l.get("code") == "TOTAL" else GENRE_NORMAL,
                    )
                    for l in lignes
                ),
            )
        )
    return tableaux


def grille_entretien_tableau(donnees: dict) -> list[Tableau]:
    """La grille d'entretien, dans la présentation du document remis.

    Trois colonnes quand la grille est structurée en rubriques — numéro,
    critère, note — comme dans le rapport du cabinet :

        I     PRESENTATION ET MOTIVATION    5
        1.1   Présentation                  3
        1.2   Motivation                    2

    La numérotation n'est pas décorative : c'est elle qui dit qu'un critère
    appartient à une rubrique, et c'est ainsi que le client a signé la grille.
    Une grille plate n'en a pas besoin et garde deux colonnes.
    """
    tableaux: list[Tableau] = []
    for poste in donnees.get("postes", []):
        entretien = poste.get("grille_entretien") or []
        if not entretien:
            continue

        rubriques = [
            r for r in dict.fromkeys((l.get("section") or "") for l in entretien) if r
        ]
        numerote = bool(rubriques)

        lignes: list[LigneTableau] = []
        rang_rubrique = 0
        rang_critere = 0
        section_courante = ""

        for ligne in entretien:
            section = ligne.get("section") or ""
            if numerote and section and section != section_courante:
                rang_rubrique += 1
                rang_critere = 0
                total = sum(
                    l["points_max"]
                    for l in entretien
                    if (l.get("section") or "") == section
                )
                numero = _ROMAINS[rang_rubrique - 1] if rang_rubrique <= 10 else str(rang_rubrique)
                lignes.append(
                    LigneTableau((numero, section.upper(), f"{total:g}"), GENRE_RUBRIQUE)
                )
                section_courante = section

            points = f"{ligne['points_max']:g}"
            if not numerote:
                lignes.append(LigneTableau((ligne["libelle"], points)))
                continue
            if section:
                rang_critere += 1
                lignes.append(
                    LigneTableau(
                        (f"{rang_rubrique}.{rang_critere}", ligne["libelle"], points),
                        GENRE_DETAIL,
                    )
                )
            else:
                lignes.append(LigneTableau(("", ligne["libelle"], points)))

        total_general = f"{sum(l['points_max'] for l in entretien):g}"
        lignes.append(
            LigneTableau(
                ("", "TOTAL", total_general) if numerote else ("TOTAL", total_general),
                GENRE_TOTAL,
            )
        )

        colonnes = (
            (Colonne(""), Colonne("Critères d'appréciation"), Colonne("Notes", numerique=True))
            if numerote
            else (Colonne("Critères d'appréciation"), Colonne("Notes", numerique=True))
        )
        tableaux.append(
            Tableau(
                titre=f"Grille de notation — {poste['intitule']}",
                colonnes=colonnes,
                lignes=tuple(lignes),
            )
        )
    return tableaux


def grille_de_notation(donnees: dict) -> list[Tableau]:
    """Les deux grilles d'un coup.

    Conservée pour les trames imposées par un client qui nomment une seule
    section « Grilles de notation ». La trame du cabinet, elle, les place
    chacune dans sa section, comme le fait le document remis.
    """
    tableaux = grille_preselection_tableau(donnees)
    tableaux.extend(grille_entretien_tableau(donnees))
    return tableaux


def tableau_preselection(donnees: dict) -> list[Tableau]:
    """Les candidatures préqualifiées, dans les colonnes du document remis.

    Nom, âge, diplôme, pays, note ramenée sur 100, rang, téléphone, adresse :
    ce sont les colonnes du tableau « Candidatures préqualifiées » que le
    cabinet livre. La note sur 100 n'est pas la contribution pondérée au total
    — c'est la note de présélection exprimée en pourcentage, ce que la colonne
    annonce.
    """
    tableaux: list[Tableau] = []
    for poste in donnees.get("postes", []):
        lignes = [
            ligne
            for ligne in poste.get("classement", [])
            if ligne.get("preselection_sur_100") is not None
            and ligne.get("statut") == StatutCandidature.PRESELECTIONNEE.value
        ]
        titre = f"Candidatures préqualifiées — {poste['intitule']}"
        if not lignes:
            tableaux.append(
                Tableau(
                    f"{titre}\nAucune candidature préqualifiée à ce stade.", (), ()
                )
            )
            continue

        tableaux.append(
            Tableau(
                titre=titre,
                # Les huit colonnes du document remis, dans son libellé exact —
                # « Age » sans accent et « Présélection Note/100 » sont ceux du
                # rapport WAPP, et un client qui compare deux documents côte à
                # côte remarque un intitulé qui a bougé.
                colonnes=(
                    Colonne("Nom & Prénoms"),
                    Colonne("Age", numerique=True),
                    Colonne("Diplôme"),
                    Colonne("Pays"),
                    Colonne("Présélection Note/100", numerique=True),
                    Colonne("Rang", numerique=True),
                    Colonne("Téléphone"),
                    Colonne("E-mail"),
                ),
                lignes=tuple(
                    LigneTableau(
                        (
                            ligne["nom"],
                            str(ligne.get("age") or "—"),
                            _raccourcir(ligne.get("diplome") or "—"),
                            (ligne.get("pays") or "—"),
                            f"{ligne['preselection_sur_100']:g}",
                            ligne.get("rang_libelle") or "",
                            ligne.get("telephone") or "—",
                            ligne.get("email") or "—",
                        )
                    )
                    for ligne in lignes
                ),
            )
        )
    return tableaux


def tableau_final(donnees: dict) -> list[Tableau]:
    """Le classement final /100, quand les entretiens ont eu lieu.

    Colonnes du document remis : nom, pays, moyenne /100, rang. Le détail des
    deux moitiés reste affiché — c'est ce qui permet de comprendre un
    classement où la présélection et l'entretien ne disent pas la même chose.
    """
    tableaux: list[Tableau] = []
    for poste in donnees.get("postes", []):
        lignes = [
            ligne
            for ligne in poste.get("classement", [])
            if ligne.get("total_100") is not None
        ]
        if not lignes:
            continue
        # Quatre colonnes, comme le document remis — nom, pays, moyenne, rang.
        # Le détail des deux moitiés n'y figure pas : le rapport du cabinet le
        # renvoie en annexe (« NB : Le détail des notes obtenues par chaque
        # candidat est annexé au présent rapport »), et c'est l'export de la
        # grille qui le porte ici.
        tableaux.append(
            Tableau(
                titre=f"Résultats des entretiens — {poste['intitule']}",
                colonnes=(
                    Colonne("Nom & Prénoms"),
                    Colonne("PAYS"),
                    Colonne("Moyenne/100", numerique=True),
                    Colonne("Rang", numerique=True),
                ),
                lignes=tuple(
                    LigneTableau(
                        (
                            ligne["nom"],
                            ligne.get("pays") or "—",
                            f"{ligne['total_100']:.2f}",
                            _rang_ordinal(rang),
                        )
                    )
                    for rang, ligne in enumerate(lignes, start=1)
                ),
            )
        )
    return tableaux


# La marque que la rédaction pose là où le tableau doit paraître.
#
# Le document du cabinet ne met pas ses tableaux en fin de section : une phrase
# les annonce, le tableau suit, et un commentaire des chiffres vient après —
# « Trente-trois (33) candidatures préqualifiées pour le poste de DAF, dont
# cinq (5) proposés pour la prochaine étape ». Tout rendre avant le tableau
# plaçait ce commentaire au-dessus des chiffres qu'il commente, juste après la
# phrase qui annonçait « les résultats suivants ».
#
# Le modèle pose donc cette ligne à l'endroit voulu, et la section garde deux
# blocs de prose. S'il l'oublie — ce qui arrive —, tout reste avant le
# tableau : c'est l'ancien comportement, correct quoique moins fidèle. Une
# marque oubliée ne doit jamais faire perdre du texte.
MARQUE_TABLEAU = "[TABLEAU]"


def decouper_autour_du_tableau(contenu: str) -> tuple[str, str]:
    """Sépare la prose qui précède le tableau de celle qui le suit."""
    if not contenu:
        return "", ""
    lignes = contenu.split("\n")
    for rang, ligne in enumerate(lignes):
        if ligne.strip().strip("*_ ").upper() == MARQUE_TABLEAU:
            avant = "\n".join(lignes[:rang]).strip()
            apres = "\n".join(lignes[rang + 1 :]).strip()
            return avant, apres
    # La marque au fil d'une phrase plutôt que sur sa ligne : on la retire sans
    # découper, plutôt que de l'imprimer dans le document remis.
    if MARQUE_TABLEAU in contenu:
        return contenu.replace(MARQUE_TABLEAU, "").strip(), ""
    return contenu.strip(), ""


def _libelle_qualification(code: str | None) -> str:
    return {
        Qualification.FORTEMENT.value: "fortement qualifié",
        Qualification.PARTIELLEMENT.value: "partiellement qualifié",
        Qualification.NON.value: "non qualifié",
    }.get(code or "", "")


# Les sections que le code remplit, par code de section. Une trame imposée par
# un client peut nommer l'une d'elles : elle sera calculée comme les autres.
_CALCULEES = {
    # Les deux grilles séparément : c'est ainsi que le document remis les
    # place, chacune dans la section qui l'annonce.
    "GRILLE_PRESELECTION": grille_preselection_tableau,
    "GRILLE_ENTRETIEN": grille_entretien_tableau,
    # Les deux d'un coup, pour une trame de client qui n'a qu'une section.
    "GRILLE_DE_NOTATION": grille_de_notation,
    "SYNTHESE_EFFECTIFS": tableau_synthese,
    "TABLEAU_PRESELECTION": tableau_preselection,
    "TABLEAU_FINAL": tableau_final,
}


async def rediger_sections(
    donnees: dict,
    trame: tuple[SectionType, ...] = TRAME,
    avec_assistance: bool = True,
) -> list[dict]:
    """Produit les sections du rapport.

    Les sections calculées sont remplies par le code. Les autres sont proposées
    par le modèle si l'assistance est demandée et disponible ; sinon elles
    arrivent vides, avec leur titre et leur consigne, pour être écrites à la
    main. Une panne du fournisseur ne doit jamais empêcher de produire un
    rapport — elle rend seulement le travail plus long.
    """
    fournisseur = get_provider() if avec_assistance else None
    contexte = _contexte_textuel(donnees, TRAME[0])

    sections = []
    for modele in trame:
        # Le bloc de tableaux : celui que la section déclare, ou celui qui
        # porte son propre code pour une section entièrement calculée.
        cle_tableaux = modele.tableaux or (modele.code if modele.calculee else "")
        tableaux = _CALCULEES[cle_tableaux](donnees) if cle_tableaux in _CALCULEES else []

        contenu = ""
        origine = ORIGINE_CALCULEE
        if not modele.calculee and modele.consigne:
            origine = ORIGINE_REDIGEE
            if fournisseur is not None:
                try:
                    contenu = await fournisseur.rediger(
                        modele.consigne, contexte, titre=modele.titre
                    )
                    # Une proposition vide n'est pas une proposition : la
                    # marquer « proposée » obligeait à relire un champ blanc
                    # pour valider le rapport. Elle arrive « rédigée ».
                    origine = ORIGINE_PROPOSEE if contenu else ORIGINE_REDIGEE
                except Exception:
                    # Le rapport existe quand même, sections vides à remplir.
                    # Perdre l'assistance n'est pas perdre le rapport.
                    logger.exception(
                        "rédaction assistée indisponible pour %s", modele.code
                    )

        avant, apres = decouper_autour_du_tableau(contenu)
        section = {
            "code": modele.code,
            "titre": modele.titre,
            "contenu": avant,
            "origine": origine,
            "niveau": modele.niveau,
        }
        if apres:
            section["contenu_apres"] = apres
        if tableaux:
            # Trois champs, trois rôles, et il a fallu s'y reprendre :
            #
            #   `contenu`        la prose, et elle seule — c'est ce que
            #                    l'écran fait relire et ce qu'un humain corrige ;
            #   `tableaux`       la structure, que dessinent le DOCX, le PDF,
            #                    l'ODT et l'aperçu ;
            #   `tableaux_texte` le même tableau aligné à l'espace, pour le TXT
            #                    et pour tout format sans tables.
            #
            # Verser le texte aligné dans `contenu` faisait paraître chaque
            # tableau deux fois : une fois en texte, une fois en table.
            section["tableaux"] = [t.en_dict() for t in tableaux]
            section["tableaux_texte"] = texte_des_tableaux(tableaux)
        elif modele.calculee:
            # Un titre porteur : « Méthodologie » n'a pas de texte à elle, ses
            # sous-sections disent tout. Elle doit paraître quand même, sans
            # quoi ses sous-sections flottent sans rattachement.
            section["porteur"] = True

        sections.append(section)
    return sections


def trame_depuis_modele(structure: dict | None) -> tuple[SectionType, ...]:
    """La trame imposée par un client, lue depuis un ModeleDocument.

    `structure` porte `{"sections": [{"code", "titre", "consigne"}]}`. Une
    structure absente ou illisible retombe sur la trame maison : mieux vaut un
    rapport dans le format du cabinet qu'aucun rapport.
    """
    sections = (structure or {}).get("sections")
    if not isinstance(sections, list) or not sections:
        return TRAME

    sortie = []
    for i, brute in enumerate(sections):
        if not isinstance(brute, dict) or not brute.get("titre"):
            continue
        code = str(brute.get("code") or f"SECTION_{i + 1}").upper()
        sortie.append(
            SectionType(
                code=code,
                titre=str(brute["titre"]),
                consigne=str(
                    brute.get("consigne")
                    or f"Rédigez la section « {brute['titre']} » du rapport de recrutement."
                ),
                # Une trame de client qui reprend l'un de ces codes obtient la
                # section calculée, pas une consigne de rédaction.
                calculee=bool(brute.get("calculee")) or code in _CALCULEES,
            )
        )
    return tuple(sortie) or TRAME


def texte_complet(rapport: Rapport) -> str:
    """Le rapport rendu en texte, pour les exports simples et l'aperçu."""
    morceaux = [rapport.titre, ""]
    for section in rapport.sections or ():
        morceaux.append(str(section.get("titre") or "").upper())
        morceaux.append("")
        contenu = str(section.get("contenu") or "")
        if contenu:
            morceaux.append(contenu)
        # Les tableaux vivent à part de la prose depuis qu'ils sont structurés :
        # les oublier ici viderait la moitié du rapport.
        aligne = str(section.get("tableaux_texte") or "")
        if aligne and aligne != contenu:
            morceaux.append(aligne)
        morceaux.append("")
    return "\n".join(morceaux).strip()
