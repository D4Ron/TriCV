"""Le profil déclaré du candidat et les exigences du poste.

Structures immuables, sans dépendance à la base : elles sont l'entrée des
moteurs d'éligibilité et de notation, ce qui rend ceux-ci testables sans
fixture ni session SQL.

Le profil est *déclaré* : ce sont les champs saisis dans le formulaire de
candidature, vérifiés par les RH contre les pièces jointes. Les documents sont
la preuve, pas la source. C'est ce qui permet à toute la présélection de
tourner sans extraction automatique.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.domain.referentiel import NiveauDiplome, Sexe, normaliser_domaine


def _mois_entre(debut: date, fin: date) -> int:
    """Nombre de mois entamés entre deux dates, jamais négatif."""
    if fin <= debut:
        return 0
    mois = (fin.year - debut.year) * 12 + (fin.month - debut.month)
    if fin.day < debut.day:
        mois -= 1
    return max(mois, 0)


@dataclass(frozen=True, slots=True)
class Diplome:
    intitule: str
    niveau: NiveauDiplome
    domaine: str
    etablissement: str | None = None
    annee: int | None = None

    @property
    def domaine_normalise(self) -> str:
        return normaliser_domaine(self.domaine)


@dataclass(frozen=True, slots=True)
class Experience:
    poste: str
    employeur: str
    debut: date
    # None = poste occupé actuellement ; la durée est alors arrêtée à la date
    # de référence de l'avis, pas à aujourd'hui.
    fin: date | None = None
    domaines: frozenset[str] = field(default_factory=frozenset)
    pays: str | None = None

    @property
    def domaines_normalises(self) -> frozenset[str]:
        return frozenset(normaliser_domaine(d) for d in self.domaines)

    def intervalle(self, reference: date) -> tuple[date, date]:
        return self.debut, min(self.fin or reference, reference)

    def concerne(self, domaines: frozenset[str]) -> bool:
        """Vrai si l'expérience relève d'au moins un des domaines visés."""
        if not domaines:
            return True
        cibles = frozenset(normaliser_domaine(d) for d in domaines)
        return bool(self.domaines_normalises & cibles)


def fusionner_intervalles(intervalles: list[tuple[date, date]]) -> list[tuple[date, date]]:
    """Fusionne les périodes qui se chevauchent.

    Un candidat qui cumule deux emplois sur la même période a une seule
    ancienneté, pas deux. Sans cette fusion, deux CDI menés de front pendant
    trois ans compteraient six ans et feraient franchir un seuil à tort.
    """
    if not intervalles:
        return []
    ordonnes = sorted(i for i in intervalles if i[1] > i[0])
    if not ordonnes:
        return []

    fusionnes = [ordonnes[0]]
    for debut, fin in ordonnes[1:]:
        dernier_debut, derniere_fin = fusionnes[-1]
        if debut <= derniere_fin:
            fusionnes[-1] = (dernier_debut, max(derniere_fin, fin))
        else:
            fusionnes.append((debut, fin))
    return fusionnes


def duree_mois(experiences: tuple[Experience, ...], reference: date) -> int:
    """Ancienneté totale en mois, chevauchements déduits."""
    intervalles = [e.intervalle(reference) for e in experiences]
    return sum(_mois_entre(d, f) for d, f in fusionner_intervalles(intervalles))


@dataclass(frozen=True, slots=True)
class ProfilCandidat:
    nom: str
    prenom: str
    date_naissance: date | None = None
    sexe: Sexe | None = None
    nationalites: frozenset[str] = field(default_factory=frozenset)
    adresse: str | None = None
    diplomes: tuple[Diplome, ...] = ()
    experiences: tuple[Experience, ...] = ()
    langues: frozenset[str] = field(default_factory=frozenset)
    certifications: tuple[str, ...] = ()
    pieces_fournies: frozenset[str] = field(default_factory=frozenset)

    @property
    def nom_complet(self) -> str:
        return f"{self.nom.upper()} {self.prenom}".strip()

    def age_au(self, reference: date) -> int | None:
        """Âge à la date de référence de l'avis, pas à la date du calcul.

        Un âge calculé sur `date.today()` ferait basculer un candidat d'un côté
        ou de l'autre d'une limite selon le jour où la grille est recalculée.
        """
        if self.date_naissance is None:
            return None
        naissance = self.date_naissance
        age = reference.year - naissance.year
        if (reference.month, reference.day) < (naissance.month, naissance.day):
            age -= 1
        return age

    @property
    def diplome_principal(self) -> Diplome | None:
        """Le diplôme le plus élevé ; à égalité, le plus récent."""
        if not self.diplomes:
            return None
        return max(self.diplomes, key=lambda d: (d.niveau, d.annee or 0))

    def niveau_max(self) -> NiveauDiplome | None:
        principal = self.diplome_principal
        return principal.niveau if principal else None

    def diplomes_dans(self, domaines: frozenset[str]) -> tuple[Diplome, ...]:
        if not domaines:
            return self.diplomes
        cibles = frozenset(normaliser_domaine(d) for d in domaines)
        return tuple(d for d in self.diplomes if d.domaine_normalise in cibles)

    def mois_experience(self, reference: date) -> int:
        return duree_mois(self.experiences, reference)

    def mois_experience_specifique(self, reference: date, domaines: frozenset[str]) -> int:
        pertinentes = tuple(e for e in self.experiences if e.concerne(domaines))
        return duree_mois(pertinentes, reference)


@dataclass(frozen=True, slots=True)
class RestrictionPoste:
    """Conditions restrictives déclarées sur un poste.

    Ces critères touchent des caractéristiques protégées. Le modèle impose donc
    deux choses : ils doivent être déclarés explicitement sur le poste (jamais
    déduits), et toute restriction posée exige une justification écrite, qui
    est recopiée sur chaque élimination qu'elle provoque. Une restriction sans
    justification est une erreur de programmation, pas une valeur par défaut.
    """

    age_min: int | None = None
    age_max: int | None = None
    sexe: Sexe | None = None
    nationalites: frozenset[str] = field(default_factory=frozenset)
    justification: str = ""

    def __post_init__(self) -> None:
        if self.active and not self.justification.strip():
            raise ValueError(
                "Une restriction d'âge, de sexe ou de nationalité doit être justifiée "
                "par écrit sur le poste."
            )
        if self.age_min is not None and self.age_max is not None and self.age_min > self.age_max:
            raise ValueError("L'âge minimum ne peut pas dépasser l'âge maximum.")

    @property
    def active(self) -> bool:
        return any(
            (
                self.age_min is not None,
                self.age_max is not None,
                self.sexe is not None,
                bool(self.nationalites),
            )
        )


SANS_RESTRICTION = RestrictionPoste()


@dataclass(frozen=True, slots=True)
class ExigencesPoste:
    """Ce que l'avis exige, sous forme comparable."""

    niveau_min: NiveauDiplome
    domaines_acceptes: frozenset[str] = field(default_factory=frozenset)
    annees_experience_min: int = 0
    annees_experience_specifique_min: int = 0
    domaines_experience: frozenset[str] = field(default_factory=frozenset)
    pieces_requises: frozenset[str] = field(default_factory=frozenset)
    langues_requises: frozenset[str] = field(default_factory=frozenset)
    restriction: RestrictionPoste = SANS_RESTRICTION
    # Date de clôture de l'avis : sert de référence à l'âge comme à
    # l'ancienneté, pour que la grille soit reproductible dans le temps.
    date_reference: date = field(default_factory=date.today)

    @property
    def mois_experience_min(self) -> int:
        return self.annees_experience_min * 12

    @property
    def mois_experience_specifique_min(self) -> int:
        return self.annees_experience_specifique_min * 12
