from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.value


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    RECRUITER = "RECRUITER"


class SessionStatus(StrEnum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class CandidateSource(StrEnum):
    PUBLIC_FORM = "PUBLIC_FORM"
    HR_UPLOAD = "HR_UPLOAD"


class AnalysisStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    ANALYZED = "ANALYZED"
    FAILED = "FAILED"


class Recommendation(StrEnum):
    STRONG_FIT = "STRONG_FIT"
    FIT = "FIT"
    MAYBE = "MAYBE"
    NOT_FIT = "NOT_FIT"


class HrStatus(StrEnum):
    NEW = "NEW"
    SHORTLISTED = "SHORTLISTED"
    MAYBE = "MAYBE"
    REJECTED = "REJECTED"


class Language(StrEnum):
    FR = "fr"
    EN = "en"


# --- chaîne de recrutement --------------------------------------------------


class Provenance(StrEnum):
    """D'où vient une donnée du dossier.

    Décisif pour la règle centrale : une donnée seulement proposée par
    l'assistance automatique ne peut pas, à elle seule, éliminer quelqu'un.
    """

    DECLARE = "DECLARE"  # saisi par le candidat dans le formulaire
    EXTRAIT_IA = "EXTRAIT_IA"  # proposé par l'extraction, non confirmé
    VERIFIE_RH = "VERIFIE_RH"  # relu et confirmé par un humain
    SAISI_RH = "SAISI_RH"  # saisi directement par les RH

    @property
    def fiable(self) -> bool:
        """Vrai si la donnée peut fonder une élimination sans relecture."""
        return self is not Provenance.EXTRAIT_IA


class SourceCandidature(StrEnum):
    EMAIL = "EMAIL"
    FORMULAIRE = "FORMULAIRE"
    IMPORT_MANUEL = "IMPORT_MANUEL"


class StatutCandidature(StrEnum):
    RECUE = "RECUE"
    A_VERIFIER = "A_VERIFIER"  # éliminable, mais sur des données non confirmées
    ELIGIBLE = "ELIGIBLE"
    ELIMINEE = "ELIMINEE"
    PRESELECTIONNEE = "PRESELECTIONNEE"
    NON_RETENUE = "NON_RETENUE"
    RETENUE = "RETENUE"


class StatutMandat(StrEnum):
    PROSPECT = "PROSPECT"
    AMI_SOUMIS = "AMI_SOUMIS"
    OFFRE_SOUMISE = "OFFRE_SOUMISE"
    GAGNE = "GAGNE"
    PERDU = "PERDU"
    CLOTURE = "CLOTURE"


class StatutAvis(StrEnum):
    BROUILLON = "BROUILLON"
    PUBLIE = "PUBLIE"
    CLOTURE = "CLOTURE"


# --- collaboration : courriels, espace client, rapports ---------------------


class StatutEnvoi(StrEnum):
    ENVOYE = "ENVOYE"
    ECHEC = "ECHEC"


class AuteurEchange(StrEnum):
    CABINET = "CABINET"
    CLIENT = "CLIENT"


class TypeEchange(StrEnum):
    MESSAGE = "MESSAGE"
    # Une demande de modification se suit jusqu'à son traitement : elle n'est
    # pas close par une réponse polie, mais par un changement effectif.
    DEMANDE_MODIFICATION = "DEMANDE_MODIFICATION"
    # Le cabinet soumet quelque chose à validation — une trame d'avis, une
    # liste de candidats proposés.
    VALIDATION = "VALIDATION"


class EtatEtape(StrEnum):
    A_VENIR = "A_VENIR"
    EN_COURS = "EN_COURS"
    TERMINEE = "TERMINEE"


class UsageModele(StrEnum):
    """Ce qu'un gabarit imposé sert à produire."""

    AVIS = "AVIS"
    RAPPORT = "RAPPORT"
    CV = "CV"
    COURRIEL = "COURRIEL"


class StatutRapport(StrEnum):
    BROUILLON = "BROUILLON"
    EN_RELECTURE = "EN_RELECTURE"
    VALIDE = "VALIDE"
