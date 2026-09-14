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

from app.domain.referentiel import (
    NiveauDiplome,
    Sexe,
    domaine_correspond,
    normaliser_domaine,
)


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
        """Vrai si l'expérience relève d'au moins un des domaines visés.

        Le rapprochement passe par `domaine_correspond` et non par l'égalité :
        une expérience étiquetée « comptabilité générale et analytique » relève
        bien de la « comptabilité générale » que le poste attend.
        """
        if not domaines:
            return True
        return any(
            domaine_correspond(declare, attendu)
            for declare in self.domaines
            for attendu in domaines
        )


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
        """Les diplômes qui relèvent d'un des domaines acceptés.

        Même rapprochement que pour les expériences : un « Master en sciences
        comptables » relève de la « comptabilité » attendue, et l'exiger au mot
        près écartait des diplômes parfaitement conformes.
        """
        if not domaines:
            return self.diplomes
        return tuple(
            d
            for d in self.diplomes
            if any(domaine_correspond(d.domaine, attendu) for attendu in domaines)
        )

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
class GroupePieces:
    """Un ensemble de pièces et la règle qui les lie.

    Une pièce exigée seule est le cas courant, mais deux situations réelles ne
    s'expriment pas ainsi :

    - « une carte d'identité **ou** un passeport » : exiger les deux
      éliminerait des candidats parfaitement en règle ;
    - « le diplôme **et** l'attestation de travail » : n'en exiger qu'une
      laisserait passer un dossier incomplet.

    D'où deux modes seulement. `TOUTES` reproduit exactement l'ancien
    comportement, ce qui permet de convertir sans rien changer aux résultats.
    """

    codes: frozenset[str]
    mode: str = "TOUTES"  # TOUTES | AU_MOINS_UNE
    libelle: str = ""

    def satisfait(self, fournies: frozenset[str]) -> bool:
        if not self.codes:
            return True
        if self.mode == "AU_MOINS_UNE":
            return bool(self.codes & fournies)
        return self.codes <= fournies

    def manquantes(self, fournies: frozenset[str]) -> frozenset[str]:
        """Ce qu'il reste à fournir pour satisfaire le groupe.

        Pour un groupe « au moins une », toutes les options restent
        acceptables tant qu'aucune n'est arrivée : on les nomme donc toutes,
        car le candidat choisit laquelle envoyer.
        """
        if self.satisfait(fournies):
            return frozenset()
        if self.mode == "AU_MOINS_UNE":
            return self.codes
        return self.codes - fournies


@dataclass(frozen=True, slots=True)
class ExigenceSpecifique:
    """Une expérience spécifique attendue : un métier, ses domaines, son seuil.

    Un avis en énonce souvent plusieurs — « 5 ans en passation de marchés
    **et** 3 ans en gestion de projet ». Réunies en un seul jeu de domaines,
    comme elles l'étaient, ces deux exigences devenaient une seule : huit
    années passées dans l'un des deux suffisaient, et un candidat n'ayant
    jamais conduit de projet franchissait la barre.

    `poids` répartit les points de l'expérience spécifique entre les
    exigences. Égal par défaut : rien n'autorise à supposer qu'une compte
    davantage tant que personne ne l'a dit.
    """

    libelle: str = ""
    domaines: frozenset[str] = field(default_factory=frozenset)
    annees_min: int = 0
    poids: float = 1.0

    @property
    def nom(self) -> str:
        """De quoi nommer l'exigence dans une grille ou un motif."""
        return self.libelle.strip() or ", ".join(sorted(self.domaines)) or "le domaine du poste"


@dataclass(frozen=True, slots=True)
class ExigencesPoste:
    """Ce que l'avis exige, sous forme comparable."""

    niveau_min: NiveauDiplome
    domaines_acceptes: frozenset[str] = field(default_factory=frozenset)
    annees_experience_min: int = 0
    annees_experience_specifique_min: int = 0
    domaines_experience: frozenset[str] = field(default_factory=frozenset)
    # Vide = une seule exigence, décrite par les deux champs ci-dessus. C'est
    # la forme historique, et elle reste la plus fréquente : la liste ne se
    # remplit que lorsqu'un avis distingue vraiment plusieurs métiers.
    experiences_specifiques: tuple[ExigenceSpecifique, ...] = ()
    pieces_requises: frozenset[str] = field(default_factory=frozenset)
    # Groupes de pieces liees par « toutes » ou « au moins une ». Vides,
    # seule `pieces_requises` s'applique — l'ancien comportement, inchange.
    groupes_pieces: tuple[GroupePieces, ...] = ()
    langues_requises: frozenset[str] = field(default_factory=frozenset)
    # Ce que l'avis dit souhaiter en plus du diplôme. Jamais éliminatoire — un
    # souhait n'est pas une exigence — mais notable si le barème du poste lui
    # accorde des points.
    formation_complementaire: str = ""
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

    @property
    def specifiques(self) -> tuple[ExigenceSpecifique, ...]:
        """Les exigences spécifiques à évaluer, forme ancienne comprise.

        Un poste qui n'en déclare aucune en a tout de même une : celle que
        portent `annees_experience_specifique_min` et `domaines_experience`.
        Tout le moteur travaille donc sur une liste, et le cas à une exigence
        — de loin le plus courant — reste noté exactement comme avant.
        """
        if self.experiences_specifiques:
            return self.experiences_specifiques
        return (
            ExigenceSpecifique(
                domaines=self.domaines_experience,
                annees_min=self.annees_experience_specifique_min,
            ),
        )
