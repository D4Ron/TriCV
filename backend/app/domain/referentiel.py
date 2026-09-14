"""Référentiel : les échelles et nomenclatures partagées par tout le domaine.

Ce module ne contient aucune logique de calcul et aucune dépendance à la base
de données. Il définit le vocabulaire sur lequel s'appuient l'éligibilité
(`eligibilite.py`) et la notation (`bareme.py`).
"""

from __future__ import annotations

from enum import Enum, IntEnum


class NiveauDiplome(IntEnum):
    """Échelle BAC+N, telle qu'employée dans les avis.

    IntEnum et non StrEnum : la comparaison ordonnée est le coeur de la règle
    « formation inférieure au niveau demandé ». La valeur est le N de BAC+N,
    ce qui rend `NiveauDiplome.BAC_PLUS_5 >= NiveauDiplome.BAC_PLUS_4` vrai
    sans table de correspondance.
    """

    BAC = 0
    BAC_PLUS_1 = 1
    BAC_PLUS_2 = 2
    BAC_PLUS_3 = 3
    BAC_PLUS_4 = 4
    BAC_PLUS_5 = 5
    BAC_PLUS_8 = 8

    @property
    def libelle(self) -> str:
        return _LIBELLES_NIVEAU[self]

    @classmethod
    def depuis_texte(cls, texte: str) -> NiveauDiplome | None:
        """Reconnaît « BAC+5 », « Bac + 5 », « Master », « Licence »...

        Renvoie None plutôt que de deviner : un niveau non reconnu doit
        remonter à un humain, pas être arrondi au plus proche.

        Les accents sont retirés avant comparaison : « Ingénieur » et
        « Maîtrise » s'écrivent toujours ainsi dans les CV, et la table
        d'alias, elle, est sans accents. Sans cette réduction, les deux
        diplômes les plus courants du pays n'étaient pas reconnus.
        """
        normalise = "".join(normaliser_domaine(texte).split())
        for cle, niveau in _ALIAS_NIVEAU.items():
            if cle in normalise:
                return niveau
        return None


_LIBELLES_NIVEAU: dict[NiveauDiplome, str] = {
    NiveauDiplome.BAC: "BAC",
    NiveauDiplome.BAC_PLUS_1: "BAC+1",
    NiveauDiplome.BAC_PLUS_2: "BAC+2 (DUT, BTS)",
    NiveauDiplome.BAC_PLUS_3: "BAC+3 (Licence)",
    NiveauDiplome.BAC_PLUS_4: "BAC+4 (Maîtrise, Master 1)",
    NiveauDiplome.BAC_PLUS_5: "BAC+5 (Master, Ingénieur, DEA, DESS)",
    NiveauDiplome.BAC_PLUS_8: "BAC+8 (Doctorat)",
}

# Ordre d'insertion signifiant : « bac+5 » doit être testé avant « bac ».
_ALIAS_NIVEAU: dict[str, NiveauDiplome] = {
    "bac+8": NiveauDiplome.BAC_PLUS_8,
    "doctorat": NiveauDiplome.BAC_PLUS_8,
    "phd": NiveauDiplome.BAC_PLUS_8,
    "bac+5": NiveauDiplome.BAC_PLUS_5,
    "master2": NiveauDiplome.BAC_PLUS_5,
    "master": NiveauDiplome.BAC_PLUS_5,
    "ingenieur": NiveauDiplome.BAC_PLUS_5,
    "dea": NiveauDiplome.BAC_PLUS_5,
    "dess": NiveauDiplome.BAC_PLUS_5,
    "bac+4": NiveauDiplome.BAC_PLUS_4,
    "maitrise": NiveauDiplome.BAC_PLUS_4,
    "master1": NiveauDiplome.BAC_PLUS_4,
    "bac+3": NiveauDiplome.BAC_PLUS_3,
    "licence": NiveauDiplome.BAC_PLUS_3,
    "bachelor": NiveauDiplome.BAC_PLUS_3,
    "bac+2": NiveauDiplome.BAC_PLUS_2,
    "dut": NiveauDiplome.BAC_PLUS_2,
    "bts": NiveauDiplome.BAC_PLUS_2,
    "bac+1": NiveauDiplome.BAC_PLUS_1,
    "bac": NiveauDiplome.BAC,
}


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - confort d'affichage
        return self.value


class Sexe(StrEnum):
    MASCULIN = "M"
    FEMININ = "F"

    @property
    def libelle(self) -> str:
        return "Masculin" if self is Sexe.MASCULIN else "Féminin"


class MotifElimination(StrEnum):
    """Motifs codés : le tableau d'élimination est subdivisé par ces codes.

    Les quatre premiers sont les motifs classiques de la présélection. Les
    trois `CONDITION_*` ne s'appliquent que si l'avis restreint explicitement
    le poste (voir `RestrictionPoste`), et portent toujours la justification
    déclarée sur le poste.
    """

    DOSSIER_INCOMPLET = "DOSSIER_INCOMPLET"
    FORMATION_INSUFFISANTE = "FORMATION_INSUFFISANTE"
    FORMATION_NON_CONFORME = "FORMATION_NON_CONFORME"
    EXPERIENCE_INSUFFISANTE = "EXPERIENCE_INSUFFISANTE"
    EXPERIENCE_SPECIFIQUE_INSUFFISANTE = "EXPERIENCE_SPECIFIQUE_INSUFFISANTE"
    CONDITION_AGE = "CONDITION_AGE"
    CONDITION_NATIONALITE = "CONDITION_NATIONALITE"
    CONDITION_SEXE = "CONDITION_SEXE"
    HORS_DELAI = "HORS_DELAI"

    @property
    def libelle(self) -> str:
        return _LIBELLES_MOTIF[self]


_LIBELLES_MOTIF: dict[MotifElimination, str] = {
    MotifElimination.DOSSIER_INCOMPLET: "Dossier incomplet",
    MotifElimination.FORMATION_INSUFFISANTE: "Formation inférieure au niveau demandé",
    MotifElimination.FORMATION_NON_CONFORME: "Formation non conforme au domaine demandé",
    MotifElimination.EXPERIENCE_INSUFFISANTE: "Expérience générale insuffisante",
    MotifElimination.EXPERIENCE_SPECIFIQUE_INSUFFISANTE: "Expérience spécifique insuffisante",
    MotifElimination.CONDITION_AGE: "Condition d'âge non remplie",
    MotifElimination.CONDITION_NATIONALITE: "Condition de nationalité non remplie",
    MotifElimination.CONDITION_SEXE: "Condition de sexe non remplie",
    MotifElimination.HORS_DELAI: "Candidature reçue hors délai",
}

# Ordre d'affichage du tableau d'élimination. Les motifs de dossier passent
# avant les motifs de fond : un dossier incomplet n'a pas pu être évalué.
ORDRE_MOTIFS: tuple[MotifElimination, ...] = (
    MotifElimination.HORS_DELAI,
    MotifElimination.DOSSIER_INCOMPLET,
    MotifElimination.CONDITION_AGE,
    MotifElimination.CONDITION_NATIONALITE,
    MotifElimination.CONDITION_SEXE,
    MotifElimination.FORMATION_NON_CONFORME,
    MotifElimination.FORMATION_INSUFFISANTE,
    MotifElimination.EXPERIENCE_INSUFFISANTE,
    MotifElimination.EXPERIENCE_SPECIFIQUE_INSUFFISANTE,
)


class TypeAvis(StrEnum):
    NATIONAL = "NATIONAL"
    INTERNATIONAL = "INTERNATIONAL"
    GRE_A_GRE = "GRE_A_GRE"

    @property
    def libelle(self) -> str:
        return {
            TypeAvis.NATIONAL: "Avis national",
            TypeAvis.INTERNATIONAL: "Avis international",
            TypeAvis.GRE_A_GRE: "Gré à gré",
        }[self]


class PieceDossier(StrEnum):
    """Pièces constitutives du dossier, telles qu'énumérées dans les avis.

    La liste effectivement exigée varie d'un avis à l'autre et se déclare sur
    le poste ; cette énumération n'est que le vocabulaire commun.
    """

    LETTRE_MOTIVATION = "LETTRE_MOTIVATION"
    CV = "CV"
    COPIE_DIPLOMES = "COPIE_DIPLOMES"
    ATTESTATIONS_TRAVAIL = "ATTESTATIONS_TRAVAIL"
    PIECE_IDENTITE = "PIECE_IDENTITE"
    PASSEPORT = "PASSEPORT"
    CERTIFICAT_NATIONALITE = "CERTIFICAT_NATIONALITE"
    CASIER_JUDICIAIRE = "CASIER_JUDICIAIRE"
    CERTIFICAT_MEDICAL = "CERTIFICAT_MEDICAL"
    PHOTO = "PHOTO"
    LETTRE_RECOMMANDATION = "LETTRE_RECOMMANDATION"
    # Fourre-tout assumé : le candidat nomme lui-même ce qu'il ajoute.
    AUTRE = "AUTRE"

    @property
    def libelle(self) -> str:
        return _LIBELLES_PIECE[self]


_LIBELLES_PIECE: dict[PieceDossier, str] = {
    PieceDossier.LETTRE_MOTIVATION: "Lettre de motivation",
    PieceDossier.CV: "CV détaillé",
    PieceDossier.COPIE_DIPLOMES: "Copie des diplômes",
    PieceDossier.ATTESTATIONS_TRAVAIL: "Copie des attestations de travail",
    PieceDossier.PIECE_IDENTITE: "Carte nationale d'identité",
    PieceDossier.PASSEPORT: "Passeport",
    PieceDossier.CERTIFICAT_NATIONALITE: "Certificat de nationalité",
    PieceDossier.CASIER_JUDICIAIRE: "Extrait de casier judiciaire",
    PieceDossier.CERTIFICAT_MEDICAL: "Certificat médical",
    PieceDossier.PHOTO: "Photo d'identité",
    PieceDossier.LETTRE_RECOMMANDATION: "Lettre de recommandation",
    PieceDossier.AUTRE: "Autre document",
}

# Le dossier le plus fréquemment demandé dans les avis publiés.
DOSSIER_STANDARD: frozenset[PieceDossier] = frozenset(
    {PieceDossier.LETTRE_MOTIVATION, PieceDossier.CV}
)


class CodeAjout(StrEnum):
    """Points additionnels du référentiel, au-delà des exigences de base."""

    EXPERIENCE_INTERNATIONALE = "EXPERIENCE_INTERNATIONALE"
    DIPLOME_SUPERIEUR = "DIPLOME_SUPERIEUR"
    LANGUE_SUPPLEMENTAIRE = "LANGUE_SUPPLEMENTAIRE"
    CERTIFICATION = "CERTIFICATION"
    EXPERIENCE_SECTEUR = "EXPERIENCE_SECTEUR"

    @property
    def libelle(self) -> str:
        return _LIBELLES_AJOUT[self]


_LIBELLES_AJOUT: dict[CodeAjout, str] = {
    CodeAjout.EXPERIENCE_INTERNATIONALE: "Expérience à l'étranger",
    CodeAjout.DIPLOME_SUPERIEUR: "Diplôme supérieur au niveau demandé",
    CodeAjout.LANGUE_SUPPLEMENTAIRE: "Langue supplémentaire",
    CodeAjout.CERTIFICATION: "Certification professionnelle",
    CodeAjout.EXPERIENCE_SECTEUR: "Expérience dans le secteur du client",
}


def normaliser_domaine(texte: str) -> str:
    """Réduit un domaine à une clé comparable.

    « Gestion Hôtelière » et « gestion hoteliere » doivent désigner le même
    domaine ; les avis n'ont aucune orthographe stable.
    """
    import unicodedata

    sans_accents = "".join(
        c
        for c in unicodedata.normalize("NFD", texte.strip().lower())
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(
        sans_accents.replace("-", " ").replace("'", " ").replace(",", " ").split()
    )


# Mots de liaison : présents ou absents, ils ne changent pas le domaine désigné.
_LIAISONS = frozenset(
    "de du des la le les et en aux au a l d en sur pour dans par avec".split()
)


def _mots_signifiants(domaine: str) -> frozenset[str]:
    return frozenset(m for m in normaliser_domaine(domaine).split() if m not in _LIAISONS)


# Longueur de racine commune à partir de laquelle deux mots désignent la même
# chose. « comptabilite » et « comptables » partagent « comptab » : sept
# lettres, et c'est bien le même métier. « gestion » et « gestation » n'en
# partagent que quatre. Six est le seuil qui sépare les deux, et il vaut mieux
# se tromper de ce côté-ci : un rapprochement de trop se relit — tout ce qui
# vient de l'extraction passe de toute façon devant un humain — alors qu'une
# élimination pour non-conformité, elle, écarte le dossier.
_RACINE_MINIMALE = 6


def _meme_mot(un: str, autre: str) -> bool:
    if un == autre:
        return True
    commun = 0
    for a, b in zip(un, autre):
        if a != b:
            break
        commun += 1
    return commun >= _RACINE_MINIMALE


def domaine_correspond(declare: str, attendu: str) -> bool:
    """Le domaine déclaré relève-t-il du domaine attendu ?

    La comparaison était l'égalité de deux chaînes, et c'était le défaut le
    plus coûteux de la présélection : « comptabilité et finance » ne valait pas
    « comptabilité, finance », « finance d'entreprise » ne valait pas
    « finance », et le dossier repartait avec un motif de non-conformité qu'un
    lecteur humain aurait refusé. Un avis n'a pas d'orthographe stable, et le
    parcours d'un candidat encore moins.

    La règle retenue : **le domaine attendu doit se retrouver en entier dans
    celui qui est déclaré**, mots de liaison exclus. « finance » se retrouve
    dans « finance d'entreprise », donc un diplôme de finance d'entreprise
    relève de la finance. L'inverse n'est pas vrai — un avis qui exige
    « finance d'entreprise » n'est pas satisfait par « finance » tout court,
    qui n'en dit pas assez.

    Elle reste donc **directionnelle et stricte sur le fond** : « droit » ne
    rencontre pas « comptabilité », et « droit social » ne rencontre pas
    « droit des affaires ». Ce qu'elle absorbe, ce sont les variations
    d'écriture, pas les différences de métier.
    """
    mots_attendus = _mots_signifiants(attendu)
    if not mots_attendus:
        return True
    mots_declares = _mots_signifiants(declare)
    return all(
        any(_meme_mot(attendu_mot, declare_mot) for declare_mot in mots_declares)
        for attendu_mot in mots_attendus
    )
