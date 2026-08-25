from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.criterion import Criterion
from app.models.criterion_score import CriterionScore
from app.models.enums import (
    AnalysisStatus,
    CandidateSource,
    HrStatus,
    Language,
    Provenance,
    Recommendation,
    SessionStatus,
    SourceCandidature,
    StatutAvis,
    StatutCandidature,
    StatutMandat,
    UserRole,
)
from app.models.recruitment_session import RecruitmentSession, new_public_key
from app.models.recrutement import (
    Avis,
    Candidat,
    Candidature,
    Client,
    DiplomeCandidat,
    Elimination,
    ExperienceCandidat,
    LigneNotation,
    Mandat,
    Notation,
    PieceCandidature,
    Poste,
    nouvelle_cle_publique,
)
from app.models.user import User

# Effet de bord : enregistre la table `parametre` dans les metadata.
from app.services.parametres import Parametre  # noqa: E402,F401

__all__ = [
    "AnalysisStatus",
    "AuditLog",
    "Avis",
    "Candidat",
    "Candidate",
    "CandidateSource",
    "Candidature",
    "Client",
    "Criterion",
    "CriterionScore",
    "DiplomeCandidat",
    "Elimination",
    "ExperienceCandidat",
    "HrStatus",
    "Language",
    "LigneNotation",
    "Mandat",
    "Notation",
    "PieceCandidature",
    "Poste",
    "Provenance",
    "RecruitmentSession",
    "Recommendation",
    "SessionStatus",
    "SourceCandidature",
    "StatutAvis",
    "StatutCandidature",
    "StatutMandat",
    "Parametre",
    "User",
    "UserRole",
    "new_public_key",
    "nouvelle_cle_publique",
]
