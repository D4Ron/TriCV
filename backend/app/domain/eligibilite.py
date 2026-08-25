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


def verifier_completude(
    profil: ProfilCandidat, exigences: ExigencesPoste
) -> tuple[Elimination, ...]:
    manquantes = exigences.pieces_requises - profil.pieces_fournies
    if not manquantes:
        return ()
    libelles = sorted(_libelle_piece(code) for code in manquantes)
    return (
        Elimination(
            motif=MotifElimination.DOSSIER_INCOMPLET,
            attendu=", ".join(sorted(_libelle_piece(c) for c in exigences.pieces_requises)),
            constate=f"pièce(s) manquante(s) : {', '.join(libelles)}",
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

    if exigences.annees_experience_specifique_min:
        mois = profil.mois_experience_specifique(reference, exigences.domaines_experience)
        if mois < exigences.mois_experience_specifique_min:
            domaines = ", ".join(sorted(exigences.domaines_experience)) or "le domaine du poste"
            motifs.append(
                Elimination(
                    motif=MotifElimination.EXPERIENCE_SPECIFIQUE_INSUFFISANTE,
                    attendu=f"{exigences.annees_experience_specifique_min} an(s) en {domaines}",
                    constate=_mois_en_annees(mois),
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
