from __future__ import annotations

from app.models.enums import Recommendation
from app.services.scoring import CriterionInput, band_for, compute


def _criteria() -> list[CriterionInput]:
    return [
        CriterionInput("a", "Python", 9, True),
        CriterionInput("b", "PostgreSQL", 8, True),
        CriterionInput("c", "Docker", 5, False),
        CriterionInput("d", "Communication", 2, False),
    ]


def test_weighted_average_not_plain_average():
    """A high score on a weight-9 criterion must outweigh a low weight-2 one."""
    outcome = compute(_criteria(), {"a": 90.0, "b": 90.0, "c": 90.0, "d": 0.0})
    plain_average = (90 + 90 + 90 + 0) / 4
    assert outcome.ai_score > plain_average
    assert outcome.ai_score == round((90 * 9 + 90 * 8 + 90 * 5 + 0 * 2) / 24, 2)


def test_bands():
    assert band_for(80) is Recommendation.STRONG_FIT
    assert band_for(79.9) is Recommendation.FIT
    assert band_for(60) is Recommendation.FIT
    assert band_for(59.9) is Recommendation.MAYBE
    assert band_for(40) is Recommendation.MAYBE
    assert band_for(39.9) is Recommendation.NOT_FIT


def test_a_missing_must_have_forces_not_fit_but_keeps_the_score():
    """Spec 5: still store the computed score so HR sees how close they were."""
    outcome = compute(_criteria(), {"a": 95.0, "b": 30.0, "c": 95.0, "d": 95.0})

    assert outcome.recommendation is Recommendation.NOT_FIT
    assert outcome.missing_must_haves == ["PostgreSQL"]
    # The average is comfortably in FIT territory — the override is what demotes it.
    assert outcome.ai_score >= 60


def test_must_have_exactly_at_the_floor_passes():
    outcome = compute(_criteria(), {"a": 40.0, "b": 40.0, "c": 40.0, "d": 40.0})
    assert outcome.missing_must_haves == []
    assert outcome.recommendation is Recommendation.MAYBE


def test_several_missing_must_haves_are_all_named():
    outcome = compute(_criteria(), {"a": 10.0, "b": 5.0, "c": 100.0, "d": 100.0})
    assert outcome.missing_must_haves == ["Python", "PostgreSQL"]


def test_unscored_criteria_are_excluded_from_the_weighting():
    """A criterion the provider skipped must not silently count as zero."""
    outcome = compute(_criteria(), {"a": 80.0, "b": 80.0})
    assert outcome.ai_score == 80.0
    # ...but it does not become a missing must-have unless it is one.
    assert outcome.missing_must_haves == []


def test_a_skipped_must_have_counts_as_missing():
    outcome = compute(_criteria(), {"a": 80.0, "c": 80.0})
    assert "PostgreSQL" in outcome.missing_must_haves
    assert outcome.recommendation is Recommendation.NOT_FIT


def test_no_scores_at_all():
    outcome = compute(_criteria(), {})
    assert outcome.ai_score == 0.0
    assert outcome.recommendation is Recommendation.NOT_FIT
