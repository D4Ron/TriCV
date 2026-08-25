"""Où l'assistance automatique intervient — et où elle n'intervient pas.

Le calcul déterministe couvre tout ce qui est comparable : un niveau, une
durée, une liste de pièces. Restent des jugements qu'aucune règle ne tranche
proprement, et c'est précisément là que le modèle sert :

1. ÉQUIVALENCE DE DIPLÔME. Les avis écrivent « ou tout autre diplôme
   équivalent ». Décider si « Master en Sciences de Gestion » relève de
   « management des affaires » n'est pas une comparaison de chaînes.
2. CLASSEMENT D'UNE EXPÉRIENCE. Rattacher « Directrice adjointe, Hôtel du
   2 Février » au domaine « gestion hôtelière » demande de lire, pas de
   filtrer.
3. EXTRACTION D'UN CV REÇU PAR EMAIL. Quand la candidature arrive par
   message et non par formulaire, personne n'a saisi les champs structurés :
   il faut les proposer à partir du document.
4. RÉDACTION D'UN AVIS à partir de la fiche de poste — de la mise en forme,
   relue avant publication.

La règle qui tient l'ensemble : **une proposition n'est pas une décision.**
Une donnée produite ici porte la provenance EXTRAIT_IA et, tant qu'un humain ne
l'a pas confirmée, elle ne peut pas éliminer un candidat. Elle peut le
positionner dans le classement ; elle ne peut pas le sortir du processus. Un
dossier dont le motif d'élimination repose sur une donnée non confirmée passe
en A_VERIFIER, pas en ELIMINEE.

Conséquence pratique : le modèle n'a jamais à connaître l'âge, le sexe ni la
nationalité. Ces attributs ne servent qu'aux conditions restrictives, qui sont
évaluées localement par du code, sur des données déclarées.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.models.enums import Provenance


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover
        return self.value


class BesoinAssistance(StrEnum):
    """Les seuls cas où l'appel à un modèle est justifié."""

    EQUIVALENCE_DIPLOME = "EQUIVALENCE_DIPLOME"
    CLASSEMENT_EXPERIENCE = "CLASSEMENT_EXPERIENCE"
    EXTRACTION_DOSSIER = "EXTRACTION_DOSSIER"
    REDACTION_AVIS = "REDACTION_AVIS"

    @property
    def libelle(self) -> str:
        return {
            BesoinAssistance.EQUIVALENCE_DIPLOME: "Équivalence de diplôme",
            BesoinAssistance.CLASSEMENT_EXPERIENCE: "Rattachement d'une expérience à un domaine",
            BesoinAssistance.EXTRACTION_DOSSIER: "Extraction d'un dossier reçu par email",
            BesoinAssistance.REDACTION_AVIS: "Rédaction d'un avis",
        }[self]

    @property
    def touche_une_decision(self) -> bool:
        """Vrai si le résultat peut peser sur l'éligibilité.

        Ces besoins-là produisent des propositions à confirmer ; la rédaction
        d'un avis, elle, ne décide du sort de personne.
        """
        return self is not BesoinAssistance.REDACTION_AVIS


@dataclass(frozen=True, slots=True)
class Proposition:
    """Une valeur suggérée, jamais appliquée telle quelle.

    `justification` doit citer ce sur quoi la proposition s'appuie, afin que la
    relecture humaine soit une vérification et non un acte de foi.
    """

    besoin: BesoinAssistance
    valeur: str
    justification: str
    confiance: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confiance <= 1.0:
            raise ValueError("La confiance doit être comprise entre 0 et 1.")

    @property
    def provenance(self) -> Provenance:
        return Provenance.EXTRAIT_IA


# Motifs d'élimination et donnée dont ils dépendent. Sert à décider si un motif
# peut être opposé au candidat ou doit d'abord passer en relecture.
from app.domain.referentiel import MotifElimination  # noqa: E402

DONNEE_SOURCE: dict[MotifElimination, str] = {
    # Ces deux-là sont des faits vérifiables sans jugement : un fichier est
    # présent ou non, un message est arrivé avant la clôture ou après.
    MotifElimination.DOSSIER_INCOMPLET: "pieces",
    MotifElimination.HORS_DELAI: "depot",
    MotifElimination.FORMATION_INSUFFISANTE: "diplomes",
    MotifElimination.FORMATION_NON_CONFORME: "diplomes",
    MotifElimination.EXPERIENCE_INSUFFISANTE: "experiences",
    MotifElimination.EXPERIENCE_SPECIFIQUE_INSUFFISANTE: "experiences",
    MotifElimination.CONDITION_AGE: "etat_civil",
    MotifElimination.CONDITION_NATIONALITE: "etat_civil",
    MotifElimination.CONDITION_SEXE: "etat_civil",
}

# Une donnée factuelle ne dépend d'aucune interprétation : un motif fondé
# dessus est opposable même si le reste du dossier a été extrait.
DONNEES_FACTUELLES: frozenset[str] = frozenset({"pieces", "depot"})


def motif_opposable(motif: MotifElimination, provenances: dict[str, Provenance]) -> bool:
    """Le motif peut-il éliminer, ou doit-il d'abord être confirmé ?

    `provenances` associe chaque famille de données ("diplomes",
    "experiences", "etat_civil") à sa provenance la moins fiable.
    """
    source = DONNEE_SOURCE.get(motif)
    if source is None or source in DONNEES_FACTUELLES:
        return True
    return provenances.get(source, Provenance.DECLARE).fiable
