"""Moteur d'éligibilité : les règles éliminatoires de la présélection.

Aucune IA, aucun appel réseau, aucun aléa. Les mêmes entrées donnent toujours
la même sortie, et chaque élimination porte la comparaison qui l'a produite —
c'est ce qui permet de répondre à un candidat qui conteste, et de faire relire
la grille par le client.

Une élimination n'est pas une note basse : un candidat au mauvais diplôme n'est
pas « 12/30 », il est écarté avec un motif. Les motifs sont donc évalués avant
toute notation, et tous sont évalués — un dossier peut être écarté pour
plusieurs raisons à la fois, et le tableau d'élimination les attend toutes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.domain.profil import ExigencesPoste, ProfilCandidat
from app.domain.referentiel import (
    ORDRE_MOTIFS,
    MotifElimination,
    NiveauDiplome,
    PieceDossier,
)


@dataclass(frozen=True, slots=True)
class Elimination:
    """Un motif retenu contre un dossier, avec de quoi le justifier."""

    motif: MotifElimination
    attendu: str
    constate: str
    justification_poste: str = ""

    @property
    def explication(self) -> str:
        base = f"{self.motif.libelle} — attendu : {self.attendu} ; constaté : {self.constate}."
        if self.justification_poste:
            return f"{base} Condition posée par l'avis : {self.justification_poste}"
        return base


def _mois_en_annees(mois: int) -> str:
    annees, reste = divmod(mois, 12)
    if annees and reste:
        return f"{annees} an(s) et {reste} mois"
    if annees:
        return f"{annees} an(s)"
    return f"{reste} mois"


def _libelle_piece(code: str) -> str:
    try:
        return PieceDossier(code).libelle
    except ValueError:
        return code


def _decrire_groupe(groupe) -> str:
    """Ce qu'un groupe demande, dit comme on le dirait à un candidat."""
    if groupe.libelle:
        return groupe.libelle
    libelles = sorted(_libelle_piece(c) for c in groupe.codes)
    if groupe.mode == "AU_MOINS_UNE":
        return " ou ".join(libelles)
    return ", ".join(libelles)


def verifier_completude(
    profil: ProfilCandidat, exigences: ExigencesPoste
) -> tuple[Elimination, ...]:
    """Le dossier est-il complet — pièces isolées et groupes compris.

    Un groupe « au moins une » est satisfait par n'importe laquelle de ses
    options : réclamer à la fois la carte d'identité et le passeport
    éliminerait des candidats parfaitement en règle.
    """
    fournies = profil.pieces_fournies
    manquantes = set(exigences.pieces_requises - fournies)
    attendus = [_libelle_piece(c) for c in exigences.pieces_requises]
    non_satisfaits: list[str] = []

    for groupe in exigences.groupes_pieces:
        attendus.append(_decrire_groupe(groupe))
        if not groupe.satisfait(fournies):
            non_satisfaits.append(_decrire_groupe(groupe))
            manquantes.update(groupe.manquantes(fournies))

    if not manquantes and not non_satisfaits:
        return ()

    constate = sorted({_libelle_piece(c) for c in manquantes})
    if non_satisfaits:
        # Nommer le groupe entier, pas ses membres : « carte d'identité ou
        # passeport » se comprend, « carte d'identité, passeport » se lit
        # comme deux pièces exigées.
        constate = sorted(set(constate) | set(non_satisfaits))

    return (
        Elimination(
            motif=MotifElimination.DOSSIER_INCOMPLET,
            attendu=", ".join(sorted(set(attendus))),
            constate=f"pièce(s) manquante(s) : {', '.join(constate)}",
        ),
    )


def verifier_formation(
    profil: ProfilCandidat, exigences: ExigencesPoste
) -> tuple[Elimination, ...]:
    """Deux règles distinctes : le niveau, et le domaine.

    Elles sont indépendantes — un BAC+5 en droit face à un poste demandant un
    BAC+3 en comptabilité est non conforme sans être insuffisant — et un
    dossier peut donc cumuler les deux motifs.
    """
    motifs: list[Elimination] = []

    if not profil.diplomes:
        return (
            Elimination(
                motif=MotifElimination.FORMATION_INSUFFISANTE,
                attendu=exigences.niveau_min.libelle,
                constate="aucun diplôme déclaré",
            ),
        )

    # Le niveau s'apprécie sur les seuls diplômes du domaine attendu quand un
    # domaine est exigé : un BAC+5 hors domaine ne compense pas un BAC+2 dans
    # le domaine.
    dans_domaine = profil.diplomes_dans(exigences.domaines_acceptes)

    if exigences.domaines_acceptes and not dans_domaine:
        principal = profil.diplome_principal
        motifs.append(
            Elimination(
                motif=MotifElimination.FORMATION_NON_CONFORME,
                attendu=", ".join(sorted(exigences.domaines_acceptes)),
                constate=principal.domaine if principal else "domaine non déclaré",
            )
        )

    candidats = dans_domaine or profil.diplomes
    niveau_atteint: NiveauDiplome = max(d.niveau for d in candidats)
    if niveau_atteint < exigences.niveau_min:
        motifs.append(
            Elimination(
                motif=MotifElimination.FORMATION_INSUFFISANTE,
                attendu=exigences.niveau_min.libelle,
                constate=niveau_atteint.libelle,
            )
        )

    return tuple(motifs)


def verifier_experience(
    profil: ProfilCandidat, exigences: ExigencesPoste
) -> tuple[Elimination, ...]:
    motifs: list[Elimination] = []
    reference = exigences.date_reference

    if exigences.annees_experience_min:
        mois = profil.mois_experience(reference)
        if mois < exigences.mois_experience_min:
            motifs.append(
                Elimination(
                    motif=MotifElimination.EXPERIENCE_INSUFFISANTE,
                    attendu=f"{exigences.annees_experience_min} an(s)",
                    constate=_mois_en_annees(mois),
                )
            )

    # Chaque exigence spécifique est vérifiée séparément — c'est tout l'objet
    # de la liste : cumuler les domaines laissait passer un candidat qui avait
    # tout fait dans l'un et rien dans l'autre. Les manquements sont ensuite
    # réunis en **un seul** motif, la table n'acceptant qu'une ligne par code
    # (uq_elimination_motif) ; l'énumération dit lesquels, ce qui suffit à
    # répondre à un candidat qui conteste.
    manquements: list[tuple[object, int]] = []
    for exigence in exigences.specifiques:
        if not exigence.annees_min:
            continue
        mois = profil.mois_experience_specifique(reference, exigence.domaines)
        if mois < exigence.annees_min * 12:
            manquements.append((exigence, mois))

    if manquements:
        if len(manquements) == 1:
            exigence, mois = manquements[0]
            attendu = f"{exigence.annees_min} an(s) en {exigence.nom}"
            constate = _mois_en_annees(mois)
        else:
            attendu = " ; ".join(f"{e.annees_min} an(s) en {e.nom}" for e, _ in manquements)
            constate = " ; ".join(f"{e.nom} : {_mois_en_annees(m)}" for e, m in manquements)
        motifs.append(
            Elimination(
                motif=MotifElimination.EXPERIENCE_SPECIFIQUE_INSUFFISANTE,
                attendu=attendu,
                constate=constate,
            )
        )

    return tuple(motifs)


def verifier_restrictions(
    profil: ProfilCandidat, exigences: ExigencesPoste
) -> tuple[Elimination, ...]:
    """Conditions d'âge, de sexe et de nationalité posées par l'avis.

    Ces règles ne s'exécutent que si le poste les déclare. Elles portent sur
    des données personnelles sensibles : elles restent donc entièrement
    locales, ne sont jamais transmises à un service externe, et chaque
    élimination qu'elles produisent recopie la justification écrite du poste,
    de sorte qu'aucune ne puisse exister sans motif consigné.

    Une donnée absente n'élimine jamais : un candidat sans date de naissance
    face à une limite d'âge relève de la vérification humaine, pas du rejet
    automatique.
    """
    restriction = exigences.restriction
    if not restriction.active:
        return ()

    motifs: list[Elimination] = []
    justification = restriction.justification

    age = profil.age_au(exigences.date_reference)
    if age is not None and (restriction.age_min is not None or restriction.age_max is not None):
        borne_basse = restriction.age_min if restriction.age_min is not None else "—"
        borne_haute = restriction.age_max if restriction.age_max is not None else "—"
        trop_jeune = restriction.age_min is not None and age < restriction.age_min
        trop_age = restriction.age_max is not None and age > restriction.age_max
        if trop_jeune or trop_age:
            motifs.append(
                Elimination(
                    motif=MotifElimination.CONDITION_AGE,
                    attendu=f"entre {borne_basse} et {borne_haute} ans",
                    constate=f"{age} ans à la date de clôture",
                    justification_poste=justification,
                )
            )

    if restriction.sexe is not None and profil.sexe is not None:
        if profil.sexe is not restriction.sexe:
            motifs.append(
                Elimination(
                    motif=MotifElimination.CONDITION_SEXE,
                    attendu=restriction.sexe.libelle,
                    constate=profil.sexe.libelle,
                    justification_poste=justification,
                )
            )

    if restriction.nationalites and profil.nationalites:
        attendues = frozenset(n.strip().casefold() for n in restriction.nationalites)
        detenues = frozenset(n.strip().casefold() for n in profil.nationalites)
        if not (attendues & detenues):
            motifs.append(
                Elimination(
                    motif=MotifElimination.CONDITION_NATIONALITE,
                    attendu=", ".join(sorted(restriction.nationalites)),
                    constate=", ".join(sorted(profil.nationalites)),
                    justification_poste=justification,
                )
            )

    return tuple(motifs)


def verifier_delai(
    depot: datetime | date | None, cloture: date | None
) -> tuple[Elimination, ...]:
    if depot is None or cloture is None:
        return ()
    jour = depot.date() if isinstance(depot, datetime) else depot
    if jour <= cloture:
        return ()
    return (
        Elimination(
            motif=MotifElimination.HORS_DELAI,
            attendu=f"au plus tard le {cloture.strftime('%d/%m/%Y')}",
            constate=f"reçue le {jour.strftime('%d/%m/%Y')}",
        ),
    )


def evaluer_eligibilite(
    profil: ProfilCandidat,
    exigences: ExigencesPoste,
    depot: datetime | date | None = None,
) -> tuple[Elimination, ...]:
    """Toutes les éliminations retenues, dans l'ordre du tableau.

    Un tuple vide signifie « éligible » : le dossier passe à la notation.
    """
    motifs = (
        verifier_delai(depot, exigences.date_reference)
        + verifier_completude(profil, exigences)
        + verifier_restrictions(profil, exigences)
        + verifier_formation(profil, exigences)
        + verifier_experience(profil, exigences)
    )
    rang = {motif: i for i, motif in enumerate(ORDRE_MOTIFS)}
    return tuple(sorted(motifs, key=lambda e: rang[e.motif]))


def est_eligible(profil: ProfilCandidat, exigences: ExigencesPoste) -> bool:
    return not evaluer_eligibilite(profil, exigences)
