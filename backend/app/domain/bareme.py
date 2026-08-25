"""Barème de présélection : la note sur 30, calculée et non estimée.

Chaque ligne du barème produit un point marqué, un maximum, et une phrase qui
explique le calcul. La grille de présélection n'affiche donc pas un score
opaque mais son détail, ce qui la rend relisable par le client et opposable à
un candidat qui conteste.

Le barème par défaut ci-dessous est une hypothèse de travail tant que la
grille réelle n'a pas été fournie : la répartition des 30 points entre
formation, expérience et ajouts se règle par configuration, sans toucher au
code.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

from app.domain.profil import ExigencesPoste, ProfilCandidat
from app.domain.referentiel import CodeAjout, NiveauDiplome


def _arrondir(valeur: float) -> float:
    """Arrondi au demi-point, comme une grille remplie à la main."""
    return round(valeur * 2) / 2


@dataclass(frozen=True, slots=True)
class BaremeFormation:
    points_max: float
    points_niveau_requis: float
    points_par_niveau_superieur: float = 0.0


@dataclass(frozen=True, slots=True)
class BaremeExperience:
    points_max: float
    points_au_seuil: float
    points_par_annee_supplementaire: float = 0.0
    annees_supplementaires_max: int | None = None


@dataclass(frozen=True, slots=True)
class RegleAjout:
    code: CodeAjout
    points: float
    # Nombre maximum de fois que la règle peut se déclencher (langues,
    # certifications). None = une seule fois.
    repetitions_max: int | None = None


@dataclass(frozen=True, slots=True)
class Bareme:
    formation: BaremeFormation
    experience_generale: BaremeExperience
    experience_specifique: BaremeExperience
    ajouts: tuple[RegleAjout, ...] = ()
    points_ajouts_max: float = 0.0
    total_max: float = 30.0
    seuil_preselection: float = 20.0

    def __post_init__(self) -> None:
        plafond = (
            self.formation.points_max
            + self.experience_generale.points_max
            + self.experience_specifique.points_max
            + self.points_ajouts_max
        )
        if round(plafond, 2) != round(self.total_max, 2):
            raise ValueError(
                f"Le barème plafonne à {plafond} points alors que le total annoncé "
                f"est {self.total_max}. Les deux doivent coïncider pour que la note "
                f"sur {self.total_max:g} ait un sens."
            )
        if self.seuil_preselection > self.total_max:
            raise ValueError("Le seuil de présélection dépasse le total du barème.")


# Hypothèse de travail : 10 / 8 / 8 / 4. À remplacer par la grille réelle.
BAREME_PAR_DEFAUT = Bareme(
    formation=BaremeFormation(
        points_max=10.0, points_niveau_requis=8.0, points_par_niveau_superieur=1.0
    ),
    experience_generale=BaremeExperience(
        points_max=8.0, points_au_seuil=5.0, points_par_annee_supplementaire=0.5
    ),
    experience_specifique=BaremeExperience(
        points_max=8.0, points_au_seuil=5.0, points_par_annee_supplementaire=0.5
    ),
    ajouts=(
        RegleAjout(CodeAjout.EXPERIENCE_INTERNATIONALE, points=1.5),
        RegleAjout(CodeAjout.DIPLOME_SUPERIEUR, points=1.0),
        RegleAjout(CodeAjout.LANGUE_SUPPLEMENTAIRE, points=0.5, repetitions_max=2),
        RegleAjout(CodeAjout.CERTIFICATION, points=0.5, repetitions_max=2),
    ),
    points_ajouts_max=4.0,
    total_max=30.0,
    seuil_preselection=20.0,
)


@dataclass(frozen=True, slots=True)
class LigneNote:
    code: str
    libelle: str
    points: float
    points_max: float
    detail: str


@dataclass(frozen=True, slots=True)
class Notation:
    lignes: tuple[LigneNote, ...]
    total: float
    total_max: float
    seuil: float

    @property
    def atteint_le_seuil(self) -> bool:
        return self.total >= self.seuil

    @property
    def note_affichee(self) -> str:
        return f"{self.total:g}/{self.total_max:g}"


def _noter_formation(
    profil: ProfilCandidat, exigences: ExigencesPoste, bareme: BaremeFormation
) -> LigneNote:
    pertinents = profil.diplomes_dans(exigences.domaines_acceptes) or profil.diplomes
    if not pertinents:
        return LigneNote(
            code="FORMATION",
            libelle="Formation académique",
            points=0.0,
            points_max=bareme.points_max,
            detail="Aucun diplôme déclaré.",
        )

    atteint: NiveauDiplome = max(d.niveau for d in pertinents)
    ecart = int(atteint) - int(exigences.niveau_min)
    if ecart < 0:
        # Ce cas est normalement éliminatoire ; on le note tout de même à zéro
        # pour que la grille reste calculable quand les RH lèvent le motif.
        points = 0.0
        detail = f"{atteint.libelle}, inférieur au {exigences.niveau_min.libelle} demandé."
    else:
        points = bareme.points_niveau_requis + ecart * bareme.points_par_niveau_superieur
        detail = f"{atteint.libelle} pour un {exigences.niveau_min.libelle} demandé."
        if ecart:
            detail += f" Soit {ecart} niveau(x) au-dessus."

    return LigneNote(
        code="FORMATION",
        libelle="Formation académique",
        points=_arrondir(min(points, bareme.points_max)),
        points_max=bareme.points_max,
        detail=detail,
    )


def _noter_experience(
    code: str,
    libelle: str,
    mois: int,
    annees_requises: int,
    bareme: BaremeExperience,
) -> LigneNote:
    annees = mois / 12
    if annees_requises and annees < annees_requises:
        return LigneNote(
            code=code,
            libelle=libelle,
            points=0.0,
            points_max=bareme.points_max,
            detail=f"{annees:.1f} an(s) pour {annees_requises} an(s) demandé(s).",
        )

    supplementaires = max(annees - annees_requises, 0.0)
    if bareme.annees_supplementaires_max is not None:
        supplementaires = min(supplementaires, bareme.annees_supplementaires_max)

    points = bareme.points_au_seuil + supplementaires * bareme.points_par_annee_supplementaire
    detail = f"{annees:.1f} an(s) pour {annees_requises} an(s) demandé(s)."
    if supplementaires >= 1:
        detail += f" Soit {supplementaires:.1f} an(s) au-delà du seuil."

    return LigneNote(
        code=code,
        libelle=libelle,
        points=_arrondir(min(points, bareme.points_max)),
        points_max=bareme.points_max,
        detail=detail,
    )


def _compter_ajout(
    code: CodeAjout, profil: ProfilCandidat, exigences: ExigencesPoste
) -> tuple[int, str]:
    """Combien de fois une règle d'ajout se déclenche, et pourquoi."""
    if code is CodeAjout.EXPERIENCE_INTERNATIONALE:
        pays = {
            e.pays.strip()
            for e in profil.experiences
            if e.pays and e.pays.strip().casefold() not in _PAYS_LOCAUX
        }
        return (1 if pays else 0), ", ".join(sorted(pays)) if pays else "aucune"

    if code is CodeAjout.DIPLOME_SUPERIEUR:
        niveau = profil.niveau_max()
        superieur = niveau is not None and niveau > exigences.niveau_min
        return (1 if superieur else 0), niveau.libelle if niveau else "aucun"

    if code is CodeAjout.LANGUE_SUPPLEMENTAIRE:
        requises = frozenset(x.casefold() for x in exigences.langues_requises)
        extra = {x for x in profil.langues if x.casefold() not in requises}
        return len(extra), ", ".join(sorted(extra)) if extra else "aucune"

    if code is CodeAjout.CERTIFICATION:
        return len(profil.certifications), ", ".join(profil.certifications) or "aucune"

    if code is CodeAjout.EXPERIENCE_SECTEUR:
        concernees = [e for e in profil.experiences if e.concerne(exigences.domaines_experience)]
        return (1 if concernees else 0), ", ".join(e.employeur for e in concernees) or "aucune"

    return 0, "non évalué"


# L'expérience « à l'étranger » s'apprécie depuis le Togo.
_PAYS_LOCAUX = frozenset({"togo", "tg"})


def _noter_ajouts(
    profil: ProfilCandidat, exigences: ExigencesPoste, bareme: Bareme
) -> LigneNote:
    total = 0.0
    details: list[str] = []

    for regle in bareme.ajouts:
        occurrences, constat = _compter_ajout(regle.code, profil, exigences)
        if not occurrences:
            continue
        plafond = regle.repetitions_max or 1
        retenues = min(occurrences, plafond)
        points = retenues * regle.points
        total += points
        details.append(f"{regle.code.libelle} ({constat}) : +{points:g}")

    return LigneNote(
        code="AJOUTS",
        libelle="Ajouts (référentiel)",
        points=_arrondir(min(total, bareme.points_ajouts_max)),
        points_max=bareme.points_ajouts_max,
        detail=" ; ".join(details) if details else "Aucun ajout applicable.",
    )


def noter(
    profil: ProfilCandidat,
    exigences: ExigencesPoste,
    bareme: Bareme = BAREME_PAR_DEFAUT,
) -> Notation:
    """Note un dossier éligible sur le total du barème."""
    reference: date = exigences.date_reference

    lignes = (
        _noter_formation(profil, exigences, bareme.formation),
        _noter_experience(
            "EXPERIENCE_GENERALE",
            "Expérience générale",
            profil.mois_experience(reference),
            exigences.annees_experience_min,
            bareme.experience_generale,
        ),
        _noter_experience(
            "EXPERIENCE_SPECIFIQUE",
            "Expérience spécifique",
            profil.mois_experience_specifique(reference, exigences.domaines_experience),
            exigences.annees_experience_specifique_min,
            bareme.experience_specifique,
        ),
        _noter_ajouts(profil, exigences, bareme),
    )

    return Notation(
        lignes=lignes,
        total=_arrondir(sum(ligne.points for ligne in lignes)),
        total_max=bareme.total_max,
        seuil=bareme.seuil_preselection,
    )


@dataclass(frozen=True, slots=True)
class DecisionSeuil:
    """Le résultat d'un abaissement de seuil, tracé.

    Le seuil de 20/30 se relâche pour les postes en tension. Comme cette
    décision change qui est présélectionné, elle ne peut pas être implicite :
    elle exige un seuil retenu et une justification, et les deux se retrouvent
    dans le journal d'audit.
    """

    seuil_retenu: float
    seuil_nominal: float
    justification: str

    def __post_init__(self) -> None:
        if self.seuil_retenu < self.seuil_nominal and not self.justification.strip():
            raise ValueError(
                "Abaisser le seuil de présélection exige une justification écrite."
            )


def appliquer_seuil(bareme: Bareme, decision: DecisionSeuil) -> Bareme:
    return replace(bareme, seuil_preselection=decision.seuil_retenu)


@dataclass(frozen=True, slots=True)
class Classement:
    """Le résultat de la présélection pour un poste."""

    retenus: tuple[tuple[str, Notation], ...] = field(default_factory=tuple)
    non_retenus: tuple[tuple[str, Notation], ...] = field(default_factory=tuple)


def classer(
    notations: dict[str, Notation],
    nombre_max: int | None = None,
) -> Classement:
    """Trie par note décroissante et applique le seuil, puis le quota.

    Les deux modes décrits par le processus coexistent : « tous ceux qui
    atteignent la barre » (nombre_max=None) et « les N meilleurs parmi eux ».
    Le tri secondaire sur l'identifiant rend l'ordre stable à note égale.
    """
    ordonnes = sorted(notations.items(), key=lambda item: (-item[1].total, item[0]))
    admissibles = [(i, n) for i, n in ordonnes if n.atteint_le_seuil]
    recales = [(i, n) for i, n in ordonnes if not n.atteint_le_seuil]

    if nombre_max is not None and len(admissibles) > nombre_max:
        recales = admissibles[nombre_max:] + recales
        admissibles = admissibles[:nombre_max]

    return Classement(retenus=tuple(admissibles), non_retenus=tuple(recales))
