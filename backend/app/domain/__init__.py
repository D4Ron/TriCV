"""Coeur métier de la présélection.

Entièrement déterministe et hors-ligne : ni base de données, ni réseau, ni
modèle de langage. Tout ce qui décide du sort d'une candidature vit ici, et
peut donc être relu, testé et défendu ligne à ligne.
"""

from app.domain.bareme import (
    BAREME_PAR_DEFAUT,
    Bareme,
    BaremeExperience,
    BaremeFormation,
    Classement,
    DecisionSeuil,
    LigneNote,
    Notation,
    RegleAjout,
    appliquer_seuil,
    classer,
    noter,
)
from app.domain.eligibilite import Elimination, est_eligible, evaluer_eligibilite
from app.domain.profil import (
    SANS_RESTRICTION,
    Diplome,
    Experience,
    ExigencesPoste,
    ProfilCandidat,
    RestrictionPoste,
    duree_mois,
    fusionner_intervalles,
)
from app.domain.referentiel import (
    DOSSIER_STANDARD,
    CodeAjout,
    MotifElimination,
    NiveauDiplome,
    PieceDossier,
    Sexe,
    TypeAvis,
    normaliser_domaine,
)

__all__ = [
    "BAREME_PAR_DEFAUT",
    "DOSSIER_STANDARD",
    "SANS_RESTRICTION",
    "Bareme",
    "BaremeExperience",
    "BaremeFormation",
    "Classement",
    "CodeAjout",
    "DecisionSeuil",
    "Diplome",
    "Elimination",
    "ExigencesPoste",
    "Experience",
    "LigneNote",
    "MotifElimination",
    "Notation",
    "NiveauDiplome",
    "PieceDossier",
    "ProfilCandidat",
    "RegleAjout",
    "RestrictionPoste",
    "Sexe",
    "TypeAvis",
    "appliquer_seuil",
    "classer",
    "duree_mois",
    "est_eligible",
    "evaluer_eligibilite",
    "fusionner_intervalles",
    "normaliser_domaine",
    "noter",
]
