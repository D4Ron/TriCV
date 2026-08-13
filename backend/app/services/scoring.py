"""Deterministic scoring.

The model is never asked for the overall score — it scores each criterion and
the arithmetic happens here. That keeps scores consistent across candidates and
makes a ranking reproducible from the stored criterion scores.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.enums import Recommendation

# A must-have scoring below this counts as missing, whatever the average says.
MUST_HAVE_FLOOR = 40.0

BANDS = ((80.0, Recommendation.STRONG_FIT), (60.0, Recommendation.FIT), (40.0, Recommendation.MAYBE))


@dataclass(slots=True)
class CriterionInput:
    id: str
    name: str
    weight: int
    is_must_have: bool


@dataclass(slots=True)
class ScoringOutcome:
    ai_score: float
    recommendation: Recommendation
    missing_must_haves: list[str] = field(default_factory=list)


def band_for(score: float) -> Recommendation:
    for threshold, recommendation in BANDS:
        if score >= threshold:
            return recommendation
    return Recommendation.NOT_FIT


def compute(
    criteria: list[CriterionInput], scores_by_criterion: dict[str, float]
) -> ScoringOutcome:
    """Weighted average, then the must-have override.

    A candidate who fails a must-have is NOT_FIT regardless of the average —
    but the computed score is still returned, so HR can see how close they were.
    """
    graded = [c for c in criteria if c.id in scores_by_criterion]
    total_weight = sum(c.weight for c in graded)

    if total_weight == 0:
        ai_score = 0.0
    else:
        ai_score = sum(scores_by_criterion[c.id] * c.weight for c in graded) / total_weight
    ai_score = round(max(0.0, min(100.0, ai_score)), 2)

    missing = [
        c.name
        for c in criteria
        if c.is_must_have and scores_by_criterion.get(c.id, 0.0) < MUST_HAVE_FLOOR
    ]

    recommendation = Recommendation.NOT_FIT if missing else band_for(ai_score)
    return ScoringOutcome(ai_score=ai_score, recommendation=recommendation, missing_must_haves=missing)
