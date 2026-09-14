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
            "Rédigez la section « Introduction » : présentez le commanditaire, "
            "puis le ou les postes à pourvoir et le motif du recrutement tel "
            "qu'il ressort des données. Trois à six phrases. N'inventez ni "
            "l'activité du commanditaire ni son organisation si les données ne "
            "les donnent pas."
        ),
    ),
    SectionType(
        code="DEMARCHE",
        titre="Démarche",
        consigne=(
            "Rédigez la section « Démarche » : annoncez en une phrase que la "
            "démarche du cabinet s'est déroulée comme suit, puis énumérez les "
            "étapes effectivement franchies — élaboration de l'avis, "
            "publication, réception des dossiers, présélection sur dossier, "
            "entretiens structurés, sélection finale. N'énumérez que les étapes "
            "que les données attestent."
        ),
    ),
    SectionType(
        code="OBJECTIFS",
        titre="Objectifs de la mission",
        consigne=(
            "Rédigez la section « Objectifs de la mission » : l'objectif "
            "principal confié au cabinet — identifier et sélectionner les "
            "candidats répondant au profil — puis les buts généraux : analyser "
            "les dossiers sur les critères définis, assister le commanditaire "
            "pendant les entretiens, établir le rapport des résultats."
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
            "Rédigez la sous-section « Présélection » de la méthodologie : "
            "expliquez ce qu'est la présélection sur dossier et à quoi elle "
            "sert, puis annoncez que le cabinet a conçu une grille conforme au "
            "profil du poste, dont les rubriques sont celles listées dans les "
            "données. Décrivez la grille, ne commentez aucun candidat."
        ),
        tableaux="GRILLE_PRESELECTION",
    ),
    SectionType(
        code="CRITERES_ELIMINATOIRES",
        titre="Critères éliminatoires et Condition de Présélection",
        niveau=2,
        consigne=(
            "Rédigez la sous-section « Critères éliminatoires et Condition de "
            "Présélection » : énumérez les conditions de base retenues — "
            "nationalité, formation académique, âge, expérience professionnelle "
            "— telles que les données les donnent, et précisez que les "
            "candidats qui ne les remplissaient pas ont été éliminés du "
            "processus. Indiquez enfin combien de candidats sont proposés au "
            "commanditaire. N'énumérez aucun nom."
        ),
    ),
    SectionType(
        code="RESULTATS_PRESELECTION",
        titre="Résultats de la présélection",
        consigne=(
            "Rédigez la section « Résultats de la présélection » : annoncez le "
            "nombre de dossiers reçus par poste, puis introduisez le tableau "
            "des effectifs par une phrase du type « L'analyse des dossiers de "
            "candidature a permis d'obtenir les résultats suivants ». Après le "
            "tableau, rappelez pour chaque poste le nombre de candidatures "
            "préqualifiées. Reprenez les chiffres sans les modifier."
        ),
        tableaux="SYNTHESE_EFFECTIFS",
    ),
    SectionType(
        code="LISTE_PRESELECTIONNES",
        titre="Liste des candidats présélectionnés",
        niveau=2,
        consigne=(
            "Rédigez la sous-section « Liste des candidats présélectionnés » : "
            "une ou deux phrases annonçant que les candidats retenus pour la "
            "suite du processus figurent ci-après. Ne commentez aucun candidat."
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
            "grille de notation » : indiquez que le guide d'entretien proposé "
            "par le cabinet a été soumis au panel de recrutement et validé, "
            "puis annoncez la grille de notation reproduite ci-après."
        ),
        tableaux="GRILLE_ENTRETIEN",
    ),
    SectionType(
        code="JURY",
        titre="Validation du jury de sélection et conduite des interviews",
        niveau=2,
        consigne=(
            "Rédigez la sous-section « Validation du jury de sélection et "
            "conduite des interviews » : composition du jury et déroulement des "
            "entretiens, tels que les données les donnent. Si les données ne "
            "précisent ni le nombre de jurés ni les dates, écrivez la section "
            "sans eux."
        ),
    ),
    SectionType(
        code="RESULTATS_ENTRETIENS",
        titre="Résultats des entretiens structurés",
        niveau=2,
        consigne=(
            "Rédigez la sous-section « Résultats des entretiens structurés » : "
            "une phrase annonçant que la compilation des notes des membres du "
            "panel a permis d'obtenir les résultats ci-dessous. Ne commentez "
            "aucun candidat et n'en recommandez aucun."
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
        "nombre_a_pourvoir": poste.nombre_a_pourvoir,
        "nombre_a_retenir": poste.nombre_a_retenir,
        "niveau_min": poste.niveau_min,
        "annees_experience_min": poste.annees_experience_min,
        "annees_experience_specifique_min": poste.annees_experience_specifique_min,
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
        lignes.append(f"Secteur : {mandat['secteur']}")

    for poste in donnees.get("postes", []):
        lignes.append("")
        lignes.append(f"Poste : {poste['intitule']}")
        lignes.append(f"  Postes à pourvoir : {poste['nombre_a_pourvoir']}")
        lignes.append(f"  Niveau minimum exigé : BAC+{poste['niveau_min']}")
        lignes.append(
            f"  Expérience minimale : {poste['annees_experience_min']} an(s), "
            f"dont {poste['annees_experience_specifique_min']} an(s) dans le domaine"
        )
        avis = poste.get("avis", {})
        if avis.get("publie_le"):
            lignes.append(f"  Avis publié le : {avis['publie_le']}")
        if avis.get("cloture_le"):
            lignes.append(f"  Clôture des candidatures : {avis['cloture_le']}")
        if avis.get("type"):
            lignes.append(f"  Type d'avis : {avis['type']}")
        lignes.append(f"  Candidatures reçues : {poste['candidatures_recues']}")
        lignes.append(f"  Dossiers écartés à l'éligibilité : {poste['eliminees']}")
        lignes.append(f"  Dossiers présélectionnés : {poste['preselectionnees']}")
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

        section = {
            "code": modele.code,
            "titre": modele.titre,
            "contenu": contenu,
            "origine": origine,
            "niveau": modele.niveau,
        }
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
