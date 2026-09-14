"""Barème de présélection : la note sur 30, calculée et non estimée.

La répartition suit celle des documents du cabinet :

    Consistance du dossier        3
    Formation académique          7
    Expérience générale           5
    Expérience spécifique        15
                                 ──
                                 30

Ces 30 points ne sont pas la note finale : ils comptent pour **30 % d'un total
sur 100**, les entretiens structurés portant les 70 % restants (voir
`BAREME_ENTRETIEN`). La présélection classe les dossiers ; elle ne recrute
personne.

Deux choses distinguent ce barème de celui qui le précédait, et toutes deux
viennent des documents réels :

- **L'expérience spécifique pèse la moitié du total.** Quinze points sur trente
  pour l'expérience dans la fonction précise, contre cinq pour l'ancienneté
  générale : le cabinet cherche quelqu'un qui a déjà fait ce métier-là, pas
  quelqu'un qui a beaucoup travaillé.
- **La consistance du dossier est notée**, et non un simple contrôle de
  complétude. Un dossier complet, cohérent et correctement motivé vaut des
  points ; c'est pourquoi une part en est réservée à l'appréciation d'un
  humain (voir `BaremeConsistance`).

Ce qui vient des documents : les quatre maxima ci-dessus, et le partage
30/70. Ce qui reste un réglage : la *courbe* à l'intérieur de chaque critère —
combien de points au niveau exigé, combien par année supplémentaire. Ces
valeurs se changent par configuration, poste par poste, sans toucher au code.

Chaque ligne produit un point marqué, un maximum et une phrase qui explique le
calcul. La grille n'affiche donc pas un score opaque mais son détail, ce qui la
rend relisable par le client et opposable à un candidat qui conteste.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum

from app.domain.profil import (
    ExigenceSpecifique,
    ExigencesPoste,
    ProfilCandidat,
    fusionner_intervalles,
)
from app.domain.referentiel import CodeAjout, NiveauDiplome, normaliser_domaine


def _arrondir(valeur: float) -> float:
    """Arrondi au demi-point, comme une grille remplie à la main."""
    return round(valeur * 2) / 2


@dataclass(frozen=True, slots=True)
class BaremeConsistance:
    """Consistance du dossier — 3 points.

    Le critère porte sur la tenue du dossier : complétude, cohérence du
    parcours déclaré, qualité de la motivation et de l'expression écrite.

    Les deux premières se constatent ; la troisième se juge. Le barème sépare
    donc ce qui se calcule de ce qui demande une lecture. La part
    « appréciation » reste à zéro tant que personne n'a lu le dossier, et la
    ligne le dit explicitement — plutôt que de faire passer une absence de
    lecture pour un jugement défavorable.
    """

    points_max: float = 3.0
    points_dossier_complet: float = 1.0
    points_coherence: float = 1.0
    # Réservé au jugement humain : motivation, expression écrite.
    points_appreciation: float = 1.0
    # Au-delà, une interruption de parcours est signalée comme un trou.
    mois_trou_tolere: int = 24


@dataclass(frozen=True, slots=True)
class BaremeFormation:
    """Formation académique — 7 points dans le barème du cabinet.

    Les deux derniers champs valent zéro par défaut, et ce défaut compte : le
    barème du cabinet note le **diplôme**, et rien d'autre. Un client qui veut
    voir récompensées les certifications professionnelles ou la formation
    complémentaire demandée par l'avis les active poste par poste.

    Ces points se prennent **à l'intérieur des 7**, jamais au-dessus : la
    répartition 3/7/5/15 vient des documents du cabinet, et un total qui
    déborderait rendrait incomparables deux grilles du même mandat. Un
    candidat au niveau exigé exactement laisse 2 points sur la table ; ce sont
    ceux-là que les certifications viennent chercher.
    """

    points_max: float
    points_niveau_requis: float
    points_par_niveau_superieur: float = 0.0
    # Par certification professionnelle déclarée, dans la limite ci-dessous.
    points_par_certification: float = 0.0
    certifications_max: int = 3
    # Attribués si le candidat justifie de la formation complémentaire que
    # l'avis dit souhaiter. La comparaison est textuelle et large : c'est un
    # indice pour le relecteur, et la ligne dit sur quoi elle s'appuie.
    points_formation_complementaire: float = 0.0


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
    consistance: BaremeConsistance = field(default_factory=BaremeConsistance)
    # Le référentiel d'ajouts reste disponible pour un client qui en demande,
    # mais le barème du cabinet n'en comporte pas : les quatre critères
    # ci-dessus totalisent déjà les 30 points.
    ajouts: tuple[RegleAjout, ...] = ()
    points_ajouts_max: float = 0.0
    total_max: float = 30.0
    # Plancher optionnel. Zéro signifie « aucun plancher » : c'est le
    # classement qui sélectionne, conformément au processus du cabinet, qui
    # retient « les N premiers candidats ayant obtenu les meilleures notes ».
    seuil_preselection: float = 0.0
    # Part de la présélection dans la note finale sur 100.
    poids_note_finale: float = 30.0

    def __post_init__(self) -> None:
        plafond = (
            self.consistance.points_max
            + self.formation.points_max
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
        detail_consistance = (
            self.consistance.points_dossier_complet
            + self.consistance.points_coherence
            + self.consistance.points_appreciation
        )
        if round(detail_consistance, 2) != round(self.consistance.points_max, 2):
            raise ValueError(
                f"La consistance du dossier se décompose en {detail_consistance} points "
                f"pour un maximum annoncé de {self.consistance.points_max}."
            )
        if self.seuil_preselection > self.total_max:
            raise ValueError("Le seuil de présélection dépasse le total du barème.")


# Le barème du cabinet : 3 / 7 / 5 / 15.
#
# Les maxima viennent des documents. La courbe interne est un réglage : au
# niveau exactement exigé, un candidat obtient 5/7 en formation, 3/5 en
# expérience générale et 9/15 en expérience spécifique — le reste récompense ce
# qui dépasse l'exigence, puisque c'est là que se joue le classement.
BAREME_PAR_DEFAUT = Bareme(
    consistance=BaremeConsistance(
        points_max=3.0,
        points_dossier_complet=1.0,
        points_coherence=1.0,
        points_appreciation=1.0,
    ),
    formation=BaremeFormation(
        points_max=7.0, points_niveau_requis=5.0, points_par_niveau_superieur=1.0
    ),
    # Les pentes sont calibrées pour que le critère départage sur toute la
    # plage plausible plutôt que de saturer aussitôt le seuil franchi : avec
    # une pente trop raide, deux candidats à quinze et vingt-cinq ans
    # d'expérience obtiennent le même maximum, et les quinze points cessent de
    # classer quoi que ce soit — précisément là où se joue le classement.
    experience_generale=BaremeExperience(
        points_max=5.0,
        points_au_seuil=3.0,
        points_par_annee_supplementaire=0.1,
        annees_supplementaires_max=20,
    ),
    experience_specifique=BaremeExperience(
        points_max=15.0,
        points_au_seuil=9.0,
        points_par_annee_supplementaire=0.3,
        annees_supplementaires_max=20,
    ),
    total_max=30.0,
    seuil_preselection=0.0,
    poids_note_finale=30.0,
)


def note_de_conformite(bareme: Bareme = BAREME_PAR_DEFAUT) -> float:
    """La note d'un dossier qui satisfait exactement les exigences, sans plus.

    Utile comme plancher quand le cabinet en veut un : « au moins ce que vaut
    un candidat conforme » est une barre qui se défend, contrairement à un
    nombre rond choisi d'avance. L'appréciation humaine n'y entre pas, puisque
    le plancher doit pouvoir s'appliquer avant toute lecture.
    """
    return _arrondir(
        bareme.consistance.points_dossier_complet
        + bareme.consistance.points_coherence
        + bareme.formation.points_niveau_requis
        + bareme.experience_generale.points_au_seuil
        + bareme.experience_specifique.points_au_seuil
    )


# --- entretiens structurés ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class LigneEntretien:
    """Un critère d'entretien, éventuellement rattaché à une rubrique.

    `section` est facultative : la grille type du cabinet est plate, mais
    certaines grilles négociées avec un client s'organisent en rubriques
    numérotées dont le total est annoncé (« II. Expérience professionnelle et
    compétences : 50 »). Une seule structure porte donc les deux formes.
    """

    code: str
    libelle: str
    points_max: float
    section: str = ""


# La grille type du cabinet : 70 points, tels qu'ils figurent dans l'offre
# technique remise aux clients.
#
# L'application ne calcule rien de ceci : ces points sont attribués par un jury
# en séance. Ils sont définis ici pour que la note sur 100 ait une base
# explicite, et pour que la fiche annonce d'emblée ce qui reste à noter.
#
# ATTENTION — cette grille est une *proposition*. Les documents du cabinet la
# qualifient de « grille de notation indicative », dont « les critères et leur
# pondération seront validés par le client ». Un mandat réel peut donc s'écarter
# entièrement de cette répartition : c'est pourquoi elle se règle poste par
# poste (voir `Poste.bareme_entretien`) au lieu d'être figée dans le code.
BAREME_ENTRETIEN: tuple[LigneEntretien, ...] = (
    LigneEntretien("PRESENTATION", "Présentation", 2.0),
    LigneEntretien("MOTIVATION", "Motivation", 2.0),
    LigneEntretien("RELATIONNELLES", "Compétences relationnelles", 20.0),
    LigneEntretien("TECHNIQUES", "Compétences techniques", 25.0),
    LigneEntretien("POTENTIEL", "Potentiel", 20.0),
    LigneEntretien("CONNAISSANCES_CLIENT", "Connaissances sur l'organisation", 1.0),
)

TOTAL_ENTRETIEN = sum(ligne.points_max for ligne in BAREME_ENTRETIEN)


def sections_entretien(
    bareme: tuple[LigneEntretien, ...] = BAREME_ENTRETIEN,
) -> tuple[tuple[str, float], ...]:
    """Les rubriques d'une grille et leur total, dans l'ordre d'apparition.

    Une grille plate ne renvoie rien : il n'y a alors pas de rubrique à
    afficher, et l'écran présente simplement la liste des critères.
    """
    cumuls: dict[str, float] = {}
    for ligne in bareme:
        if ligne.section:
            cumuls[ligne.section] = cumuls.get(ligne.section, 0.0) + ligne.points_max
    return tuple(cumuls.items())


def grille_entretien_vers_liste(bareme: tuple[LigneEntretien, ...]) -> list[dict]:
    return [
        {
            "code": l.code,
            "libelle": l.libelle,
            "points_max": l.points_max,
            "section": l.section,
        }
        for l in bareme
    ]


def grille_entretien_depuis_liste(donnees: list[dict] | None) -> tuple[LigneEntretien, ...]:
    """Relit une grille enregistrée. Sans donnée, on retombe sur la grille type."""
    if not donnees:
        return BAREME_ENTRETIEN
    return tuple(
        LigneEntretien(
            code=str(d["code"]),
            libelle=str(d["libelle"]),
            points_max=float(d["points_max"]),
            section=str(d.get("section") or ""),
        )
        for d in donnees
    )


def valider_grille_entretien(bareme: tuple[LigneEntretien, ...]) -> None:
    """Refuse une grille inutilisable plutôt que de noter dessus.

    Deux critères de même code rendraient la fiche ambiguë ; un total nul
    empêcherait toute conversion en pourcentage.
    """
    if not bareme:
        raise ValueError("La grille d'entretien ne peut pas être vide.")
    codes = [l.code for l in bareme]
    doublons = {c for c in codes if codes.count(c) > 1}
    if doublons:
        raise ValueError(
            "Deux critères portent le même code : " + ", ".join(sorted(doublons))
        )
    for ligne in bareme:
        if ligne.points_max <= 0:
            raise ValueError(f"« {ligne.libelle} » doit valoir plus de zéro point.")


# --- classement remis au client ----------------------------------------------


class Qualification(StrEnum):
    """Les trois catégories que le cabinet remet au client.

    Distinctes du statut interne d'une candidature : celui-ci dit où en est le
    traitement (reçue, à vérifier, éliminée), celle-ci dit ce qu'on pense du
    profil. Un dossier peut être parfaitement traité et « non qualifié ».
    """

    FORTEMENT = "FORTEMENT_QUALIFIE"
    PARTIELLEMENT = "PARTIELLEMENT_QUALIFIE"
    NON = "NON_QUALIFIE"

    @property
    def libelle(self) -> str:
        return {
            Qualification.FORTEMENT: "Fortement qualifié",
            Qualification.PARTIELLEMENT: "Partiellement qualifié",
            Qualification.NON: "Non qualifié",
        }[self]


# Seuils par défaut, en proportion du total de la présélection. Le cabinet
# écrit dans son offre que « les personnes proposées remplissent au moins 85 %
# des critères retenus » : cette barre sert de frontière haute.
SEUIL_FORTEMENT = 0.85
SEUIL_PARTIELLEMENT = 0.60


def qualifier(
    notation: "Notation",
    seuil_fortement: float = SEUIL_FORTEMENT,
    seuil_partiellement: float = SEUIL_PARTIELLEMENT,
) -> Qualification:
    """Classe un dossier noté dans l'une des trois catégories du cabinet."""
    if not notation.total_max:
        return Qualification.NON
    part = notation.total / notation.total_max
    if part >= seuil_fortement:
        return Qualification.FORTEMENT
    if part >= seuil_partiellement:
        return Qualification.PARTIELLEMENT
    return Qualification.NON


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
    # Part de la présélection dans la note finale sur 100.
    poids_note_finale: float = 30.0
    # Un humain a-t-il apprécié la consistance du dossier ? Drapeau explicite
    # et non phrase à relire : une décision de l'interface ne doit pas dépendre
    # de la formulation d'un détail destiné à être lu.
    appreciation_portee: bool = False

    @property
    def atteint_le_seuil(self) -> bool:
        return self.total >= self.seuil

    @property
    def note_affichee(self) -> str:
        return f"{self.total:g}/{self.total_max:g}"

    @property
    def points_sur_cent(self) -> float:
        """Ce que la présélection apporte à la note finale sur 100.

        Le barème valant 30 points pour un poids de 30 %, la conversion est
        aujourd'hui l'identité — mais elle est calculée et non supposée, pour
        qu'un client qui pondère autrement n'oblige pas à toucher au code.
        """
        if not self.total_max:
            return 0.0
        return _arrondir(self.total / self.total_max * self.poids_note_finale)

    @property
    def attend_appreciation(self) -> bool:
        """Vrai tant qu'aucun humain n'a apprécié la consistance du dossier.

        Des points restent alors à prendre : la note affichée est un plancher,
        pas un jugement porté.
        """
        return not self.appreciation_portee


def _noter_consistance(
    profil: ProfilCandidat,
    exigences: ExigencesPoste,
    bareme: BaremeConsistance,
    appreciation: float | None,
) -> LigneNote:
    """Complétude et cohérence se constatent ; la motivation se lit."""
    points = 0.0
    constats: list[str] = []

    manquantes = exigences.pieces_requises - profil.pieces_fournies
    if manquantes:
        constats.append(f"dossier incomplet ({len(manquantes)} pièce(s) manquante(s))")
    else:
        points += bareme.points_dossier_complet
        constats.append("dossier complet")

    trous, incoherences = _analyser_chronologie(profil, exigences.date_reference, bareme)
    if incoherences:
        constats.append(incoherences)
    elif trous:
        constats.append(trous)
    else:
        points += bareme.points_coherence
        constats.append("parcours chronologiquement cohérent")

    if appreciation is None:
        constats.append(
            f"appréciation non portée (jusqu'à {bareme.points_appreciation:g} pt "
            "pour la motivation et l'expression écrite)"
        )
    else:
        retenue = max(0.0, min(appreciation, bareme.points_appreciation))
        points += retenue
        constats.append(f"appréciation du dossier : {retenue:g}")

    return LigneNote(
        code="CONSISTANCE",
        libelle="Consistance du dossier",
        points=_arrondir(min(points, bareme.points_max)),
        points_max=bareme.points_max,
        detail=" ; ".join(constats) + ".",
    )


def _analyser_chronologie(
    profil: ProfilCandidat, reference: date, bareme: BaremeConsistance
) -> tuple[str, str]:
    """Repère les dates impossibles et les interruptions de parcours.

    Renvoie (description des trous, description des incohérences). Une date de
    fin antérieure au début est une incohérence — un dossier mal rempli ou
    recopié à la hâte ; un intervalle sans emploi est un trou, qui n'est pas
    une faute mais mérite d'être vu par le lecteur de la grille.
    """
    if not profil.experiences:
        return "", "aucune expérience déclarée"

    impossibles = [e for e in profil.experiences if e.fin is not None and e.fin < e.debut]
    if impossibles:
        return "", f"{len(impossibles)} période(s) aux dates impossibles"

    periodes = fusionner_intervalles(
        [e.intervalle(reference) for e in profil.experiences]
    )
    trous: list[int] = []
    for precedent, suivant in zip(periodes, periodes[1:]):
        mois = (suivant[0].year - precedent[1].year) * 12 + (
            suivant[0].month - precedent[1].month
        )
        if mois > bareme.mois_trou_tolere:
            trous.append(mois)

    if trous:
        plus_long = max(trous)
        return f"interruption de {plus_long} mois dans le parcours", ""
    return "", ""


def _mots_utiles(texte: str) -> set[str]:
    """Les mots d'un intitulé qui portent du sens : quatre lettres au moins."""
    return {m for m in normaliser_domaine(texte).split() if len(m) >= 4}


def _formation_complementaire_justifiee(
    profil: ProfilCandidat, souhaitee: str
) -> str | None:
    """Ce que le dossier oppose à la formation complémentaire souhaitée.

    Le rapprochement est textuel et volontairement approximatif : il **propose
    une correspondance**, il ne la constate pas. La ligne de notation nomme
    donc toujours l'élément retenu, pour que le relecteur puisse la refuser —
    ce qui est le seul usage honnête d'un appariement de mots.
    """
    attendus = _mots_utiles(souhaitee)
    if not attendus:
        return None
    candidats = [*profil.certifications, *(d.intitule for d in profil.diplomes)]
    for element in candidats:
        communs = attendus & _mots_utiles(element)
        if len(communs) / len(attendus) >= 0.6:
            return element
    return None


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

    # Certifications et formation complémentaire : zéro tant que le poste ne
    # leur accorde rien, ce qui est le barème du cabinet par défaut.
    if bareme.points_par_certification and profil.certifications:
        retenues = list(profil.certifications)[: bareme.certifications_max]
        points += len(retenues) * bareme.points_par_certification
        detail += (
            f" {len(retenues)} certification(s) retenue(s) : "
            f"{', '.join(retenues)}."
        )

    if bareme.points_formation_complementaire and exigences.formation_complementaire:
        justifiee = _formation_complementaire_justifiee(
            profil, exigences.formation_complementaire
        )
        if justifiee:
            points += bareme.points_formation_complementaire
            detail += (
                f" Formation complémentaire souhaitée "
                f"(« {exigences.formation_complementaire} ») rapprochée de "
                f"« {justifiee} » — à confirmer."
            )
        else:
            detail += (
                f" Rien au dossier ne répond à la formation complémentaire "
                f"souhaitée (« {exigences.formation_complementaire} »)."
            )

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


def _noter_specifiques(
    profil: ProfilCandidat,
    exigences: ExigencesPoste,
    reference: date,
    bareme: BaremeExperience,
) -> list[LigneNote]:
    """Une ligne par expérience spécifique attendue.

    Les quinze points se partagent au prorata des poids : le total du critère
    ne bouge pas, quel que soit le nombre d'exigences. La courbe interne est
    mise à l'échelle avec lui — sans quoi deux exigences à sept points et demi
    chacune rapporteraient neuf points au seuil, et le critère vaudrait
    dix-huit points sur quinze.

    Une seule exigence garde le code `EXPERIENCE_SPECIFIQUE` et le libellé
    d'origine : les grilles déjà remises, les exports et les rapports lisent ce
    code, et le cas à une exigence reste la règle.
    """
    exigeances = exigences.specifiques
    # Un poids nul ou négatif n'a pas de sens et vaut 1, ici comme dans le
    # total : normaliser d'un côté seulement ferait dépasser le maximum du
    # critère, et quinze points en vaudraient vingt-deux.
    poids = [e.poids if e.poids > 0 else 1.0 for e in exigeances]
    total_poids = sum(poids)

    lignes: list[LigneNote] = []
    for rang, (exigence, sien) in enumerate(zip(exigeances, poids), start=1):
        part = sien / total_poids
        echelle = replace(
            bareme,
            points_max=bareme.points_max * part,
            points_au_seuil=bareme.points_au_seuil * part,
            points_par_annee_supplementaire=bareme.points_par_annee_supplementaire * part,
        )
        seule = len(exigeances) == 1
        lignes.append(
            _noter_experience(
                "EXPERIENCE_SPECIFIQUE" if seule else f"EXPERIENCE_SPECIFIQUE_{rang}",
                "Expérience spécifique" if seule else f"Expérience spécifique — {exigence.nom}",
                profil.mois_experience_specifique(reference, exigence.domaines),
                exigence.annees_min,
                echelle,
            )
        )
    return lignes


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
    appreciation_consistance: float | None = None,
) -> Notation:
    """Note un dossier éligible sur le total du barème.

    `appreciation_consistance` est la part humaine de la consistance du
    dossier — motivation, expression écrite. Laissée à None, elle ne rapporte
    rien et la ligne indique qu'elle reste à porter : le calcul ne se substitue
    pas à une lecture qui n'a pas eu lieu.
    """
    reference: date = exigences.date_reference

    lignes = [
        _noter_consistance(profil, exigences, bareme.consistance, appreciation_consistance),
        _noter_formation(profil, exigences, bareme.formation),
        _noter_experience(
            "EXPERIENCE_GENERALE",
            "Expérience générale",
            profil.mois_experience(reference),
            exigences.annees_experience_min,
            bareme.experience_generale,
        ),
        *_noter_specifiques(profil, exigences, reference, bareme.experience_specifique),
    ]
    # Ligne omise quand le barème ne prévoit pas d'ajouts — c'est le cas du
    # barème du cabinet. Une colonne toujours vide dans la grille remise au
    # client soulève une question à laquelle il n'y a rien à répondre.
    if bareme.points_ajouts_max:
        lignes.append(_noter_ajouts(profil, exigences, bareme))

    return Notation(
        lignes=tuple(lignes),
        total=_arrondir(sum(ligne.points for ligne in lignes)),
        total_max=bareme.total_max,
        seuil=bareme.seuil_preselection,
        poids_note_finale=bareme.poids_note_finale,
        appreciation_portee=appreciation_consistance is not None,
    )


# --- note finale sur 100 -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class NoteEntretien:
    """Les points attribués par le jury, ligne par ligne.

    Saisis après les entretiens : l'application ne les calcule pas et ne les
    devine pas. Elle sait seulement les additionner et les combiner à la
    présélection.
    """

    points: dict[str, float] = field(default_factory=dict)

    def total(self, bareme: tuple[LigneEntretien, ...] = BAREME_ENTRETIEN) -> float:
        acquis = 0.0
        for ligne in bareme:
            valeur = self.points.get(ligne.code)
            if valeur is None:
                continue
            acquis += max(0.0, min(float(valeur), ligne.points_max))
        return _arrondir(acquis)

    def complete(self, bareme: tuple[LigneEntretien, ...] = BAREME_ENTRETIEN) -> bool:
        return all(ligne.code in self.points for ligne in bareme)


@dataclass(frozen=True, slots=True)
class NoteFinale:
    preselection_sur_cent: float
    entretien_sur_cent: float
    total_sur_cent: float
    entretien_complet: bool

    @property
    def note_affichee(self) -> str:
        return f"{self.total_sur_cent:g}/100"


def note_finale(
    notation: Notation,
    entretien: NoteEntretien | None = None,
    bareme_entretien: tuple[LigneEntretien, ...] = BAREME_ENTRETIEN,
) -> NoteFinale:
    """Combine les deux étapes en une note sur 100.

    Tant que les entretiens n'ont pas eu lieu, la seconde part vaut zéro et
    `entretien_complet` est faux : la note affichée est donc un *acquis*, pas
    un résultat provisoire qu'on prendrait pour définitif.
    """
    preselection = notation.points_sur_cent
    if entretien is None:
        return NoteFinale(
            preselection_sur_cent=preselection,
            entretien_sur_cent=0.0,
            total_sur_cent=preselection,
            entretien_complet=False,
        )

    total_max = sum(ligne.points_max for ligne in bareme_entretien)
    poids = 100.0 - notation.poids_note_finale
    brut = entretien.total(bareme_entretien)
    part = _arrondir(brut / total_max * poids) if total_max else 0.0

    return NoteFinale(
        preselection_sur_cent=preselection,
        entretien_sur_cent=part,
        total_sur_cent=_arrondir(preselection + part),
        entretien_complet=entretien.complete(bareme_entretien),
    )


# --- seuil et classement -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecisionSeuil:
    """Le résultat d'un abaissement de seuil, tracé.

    Le plancher se relâche pour les postes en tension. Comme cette décision
    change qui est présélectionné, elle ne peut pas être implicite : elle exige
    un seuil retenu et une justification, et les deux se retrouvent dans le
    journal d'audit.
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
    """Le résultat de la présélection, dans le vocabulaire du cabinet.

    Trois groupes, et non deux, parce que le processus en distingue trois :
    un dossier peut être **préqualifié** — il franchit le plancher — sans être
    **proposé** au client, qui n'en reçoit qu'un nombre convenu. Confondre les
    deux ferait disparaître de la grille les candidats recevables classés
    au-delà du quota, alors que ce sont précisément eux qu'on rappelle si un
    candidat proposé se désiste.
    """

    proposes: tuple[tuple[str, Notation], ...] = field(default_factory=tuple)
    prequalifies_non_proposes: tuple[tuple[str, Notation], ...] = field(default_factory=tuple)
    ecartes: tuple[tuple[str, Notation], ...] = field(default_factory=tuple)

    @property
    def prequalifies(self) -> tuple[tuple[str, Notation], ...]:
        """Tous ceux qui franchissent le plancher, proposés ou non."""
        return self.proposes + self.prequalifies_non_proposes


def classer(
    notations: dict[str, Notation],
    nombre_a_proposer: int | None = None,
) -> Classement:
    """Trie par note décroissante, applique le plancher, puis le quota.

    Le processus du cabinet retient « les N premiers candidats ayant obtenu les
    meilleures notes » : c'est le classement qui sélectionne, le plancher n'est
    qu'un filet — laissé à zéro, il ne retire personne. Le tri secondaire sur
    l'identifiant rend l'ordre stable à note égale, pour qu'une grille
    recalculée ne réordonne pas deux ex æquo.
    """
    ordonnes = sorted(notations.items(), key=lambda item: (-item[1].total, item[0]))
    admissibles = [(i, n) for i, n in ordonnes if n.atteint_le_seuil]
    ecartes = [(i, n) for i, n in ordonnes if not n.atteint_le_seuil]

    if nombre_a_proposer is None:
        return Classement(proposes=tuple(admissibles), ecartes=tuple(ecartes))

    return Classement(
        proposes=tuple(admissibles[:nombre_a_proposer]),
        prequalifies_non_proposes=tuple(admissibles[nombre_a_proposer:]),
        ecartes=tuple(ecartes),
    )
