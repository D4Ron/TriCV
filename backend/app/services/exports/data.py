"""One dataset, three renderers.

PDF, Excel and DocX all read the same `ExportData`, so a shortlist exported in
one format cannot disagree with the same shortlist in another.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Candidate, Criterion, HrStatus, RecruitmentSession
from app.models.base import utcnow

Scope = Literal["all", "shortlisted", "above_threshold"]


@dataclass(slots=True)
class ExportCriterion:
    id: str
    name: str
    description: str | None
    weight: int
    is_must_have: bool


@dataclass(slots=True)
class ExportCandidate:
    rank: int
    full_name: str
    email: str | None
    phone: str | None
    source: str
    score: float | None
    ai_score: float | None
    manual_score: float | None
    recommendation: str | None
    hr_status: str
    hr_notes: str | None
    years_experience: int | None
    education_level: str | None
    summary: str | None
    strengths: list[str]
    gaps: list[str]
    missing_must_haves: list[str]
    scores_by_criterion: dict[str, float]
    justifications: dict[str, str]
    submitted_at: datetime
    cv_storage_path: str | None
    cv_filename: str | None
    cv_mime_type: str | None

    @property
    def last_first(self) -> tuple[str, str]:
        parts = [p for p in re.split(r"\s+", self.full_name.strip()) if p]
        if len(parts) < 2:
            return (parts[0] if parts else "candidat", "")
        return (parts[-1], " ".join(parts[:-1]))


@dataclass(slots=True)
class ExportData:
    session: RecruitmentSession
    criteria: list[ExportCriterion]
    candidates: list[ExportCandidate]
    scope: Scope
    generated_at: datetime
    total_in_session: int
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def language(self) -> str:
        return self.session.language.value

    def label(self, key: str) -> str:
        return self.labels.get(key, key)


LABELS = {
    "fr": {
        "title": "Rapport de présélection",
        "position": "Poste",
        "department": "Département",
        "generated": "Généré le",
        "scope": "Périmètre",
        "scope_all": "Tous les candidats",
        "scope_shortlisted": "Candidats présélectionnés",
        "scope_above_threshold": "Candidats au-dessus du seuil",
        "threshold": "Seuil de score",
        "criteria": "Critères d'évaluation",
        "criterion": "Critère",
        "weight": "Poids",
        "must_have": "Indispensable",
        "yes": "Oui",
        "no": "Non",
        "ranking": "Classement",
        "rank": "Rang",
        "candidate": "Candidat",
        "email": "Email",
        "phone": "Téléphone",
        "score": "Score",
        "ai_score": "Score IA",
        "manual_score": "Score manuel",
        "recommendation": "Recommandation",
        "hr_status": "Statut RH",
        "notes": "Notes RH",
        "strengths": "Points forts",
        "gaps": "Lacunes",
        "missing_must_haves": "Critères indispensables non satisfaits",
        "summary": "Synthèse",
        "experience": "Expérience",
        "education": "Formation",
        "source": "Source",
        "submitted": "Reçu le",
        "years": "ans",
        "detail": "Fiches candidats",
        "justification": "Justification",
        "distribution": "Répartition des scores",
        "candidates": "Candidats",
        "average": "Moyenne",
        "synthesis": "Synthèse",
        "disclaimer": (
            "Ce rapport est une aide à la décision produite par une analyse automatisée. "
            "Les scores classent et recommandent ; la décision de recrutement appartient "
            "à l'équipe RH."
        ),
        "no_candidates": "Aucun candidat ne correspond à ce périmètre.",
        "metric": "Indicateur",
        "value": "Valeur",
        "manual_note": "Score ajusté manuellement par l'équipe RH.",
    },
    "en": {
        "title": "Screening report",
        "position": "Position",
        "department": "Department",
        "generated": "Generated on",
        "scope": "Scope",
        "scope_all": "All candidates",
        "scope_shortlisted": "Shortlisted candidates",
        "scope_above_threshold": "Candidates above the threshold",
        "threshold": "Score threshold",
        "criteria": "Evaluation criteria",
        "criterion": "Criterion",
        "weight": "Weight",
        "must_have": "Must have",
        "yes": "Yes",
        "no": "No",
        "ranking": "Ranking",
        "rank": "Rank",
        "candidate": "Candidate",
        "email": "Email",
        "phone": "Phone",
        "score": "Score",
        "ai_score": "AI score",
        "manual_score": "Manual score",
        "recommendation": "Recommendation",
        "hr_status": "HR status",
        "notes": "HR notes",
        "strengths": "Strengths",
        "gaps": "Gaps",
        "missing_must_haves": "Missing must-haves",
        "summary": "Summary",
        "experience": "Experience",
        "education": "Education",
        "source": "Source",
        "submitted": "Submitted",
        "years": "years",
        "detail": "Candidate profiles",
        "justification": "Justification",
        "distribution": "Score distribution",
        "candidates": "Candidates",
        "average": "Average",
        "synthesis": "Summary",
        "disclaimer": (
            "This report is decision support produced by automated analysis. The scores "
            "rank and recommend; the hiring decision rests with the HR team."
        ),
        "no_candidates": "No candidate matches this scope.",
        "metric": "Metric",
        "value": "Value",
        "manual_note": "Score manually adjusted by the HR team.",
    },
}

RECOMMENDATION_LABELS = {
    "fr": {
        "STRONG_FIT": "Très bon profil",
        "FIT": "Bon profil",
        "MAYBE": "À examiner",
        "NOT_FIT": "Non retenu",
    },
    "en": {
        "STRONG_FIT": "Strong fit",
        "FIT": "Fit",
        "MAYBE": "Maybe",
        "NOT_FIT": "Not a fit",
    },
}

HR_STATUS_LABELS = {
    "fr": {
        "NEW": "Nouveau",
        "SHORTLISTED": "Présélectionné",
        "MAYBE": "À examiner",
        "REJECTED": "Écarté",
    },
    "en": {
        "NEW": "New",
        "SHORTLISTED": "Shortlisted",
        "MAYBE": "Maybe",
        "REJECTED": "Rejected",
    },
}

SOURCE_LABELS = {
    "fr": {"PUBLIC_FORM": "Formulaire public", "HR_UPLOAD": "Import RH"},
    "en": {"PUBLIC_FORM": "Public form", "HR_UPLOAD": "HR upload"},
}


def translate(mapping: dict, language: str, key: str | None) -> str:
    if key is None:
        return "—"
    return mapping.get(language, mapping["en"]).get(key, key)


def safe_filename(text: str) -> str:
    """ASCII, no separators — used for the CV filenames inside the ZIP."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_text).strip("._-")
    return cleaned or "candidat"


async def build(
    db: AsyncSession, session_id: str, scope: Scope = "all"
) -> ExportData:
    session = await db.get(RecruitmentSession, session_id)
    if session is None:
        raise ValueError("Recruitment session not found")

    criteria = list(
        (
            await db.execute(
                select(Criterion)
                .where(Criterion.session_id == session_id)
                .order_by(Criterion.display_order)
            )
        ).scalars()
    )

    query = select(Candidate).where(Candidate.session_id == session_id)
    if scope == "shortlisted":
        query = query.where(Candidate.hr_status == HrStatus.SHORTLISTED)
    elif scope == "above_threshold":
        query = query.where(
            func.coalesce(Candidate.manual_score, Candidate.ai_score) >= session.score_threshold
        )

    effective = func.coalesce(Candidate.manual_score, Candidate.ai_score)
    rows = list(
        (
            await db.execute(query.order_by(effective.desc().nulls_last(), Candidate.submitted_at))
        ).scalars()
    )

    total = (
        await db.execute(
            select(func.count()).select_from(Candidate).where(Candidate.session_id == session_id)
        )
    ).scalar_one()

    candidates: list[ExportCandidate] = []
    for index, row in enumerate(rows, start=1):
        scores = {s.criterion_id: float(s.score) for s in row.criterion_scores}
        justifications = {
            s.criterion_id: (s.justification or "") for s in row.criterion_scores
        }
        candidates.append(
            ExportCandidate(
                rank=index,
                full_name=row.full_name or (row.cv_filename or "—"),
                email=row.email,
                phone=row.phone,
                source=row.source.value,
                score=row.effective_score,
                ai_score=float(row.ai_score) if row.ai_score is not None else None,
                manual_score=float(row.manual_score) if row.manual_score is not None else None,
                recommendation=row.ai_recommendation.value if row.ai_recommendation else None,
                hr_status=row.hr_status.value,
                hr_notes=row.hr_notes,
                years_experience=row.years_experience,
                education_level=row.education_level,
                summary=row.ai_summary,
                strengths=list(row.ai_strengths or []),
                gaps=list(row.ai_gaps or []),
                missing_must_haves=list(row.missing_must_haves or []),
                scores_by_criterion=scores,
                justifications=justifications,
                submitted_at=row.submitted_at,
                cv_storage_path=row.cv_storage_path,
                cv_filename=row.cv_filename,
                cv_mime_type=row.cv_mime_type,
            )
        )

    language = session.language.value
    return ExportData(
        session=session,
        criteria=[
            ExportCriterion(c.id, c.name, c.description, c.weight, c.is_must_have)
            for c in criteria
        ],
        candidates=candidates,
        scope=scope,
        generated_at=utcnow(),
        total_in_session=total,
        labels=LABELS.get(language, LABELS["en"]),
    )
