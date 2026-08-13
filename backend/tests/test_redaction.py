"""Acceptance checks for section 6.2 — the privacy control."""

from __future__ import annotations

import pytest

from app.services.redaction import KnownValues, redact_sync

CV_WITH_EVERYTHING = """KOSSI Amevi
Ingénieur logiciel

Email : kossi.amevi@example.tg
Téléphone : +228 90 12 34 56
Adresse : 15 rue des Palmiers, Quartier Tokoin, Lomé
Date de naissance : 12/03/1990
Sexe : Masculin
Situation familiale : Marié
Nationalité : Togolaise
LinkedIn : https://linkedin.com/in/kossiamevi
CNI n° AB1234567

EXPERIENCE
2019-2024  Ingenieur backend senior, Orabank Togo
   Conception d'une plateforme de paiement en Python/FastAPI.
2016-2019  Developpeur, CIB Lome

FORMATION
2016  Master en Informatique, Universite de Lome

COMPETENCES
Python, FastAPI, PostgreSQL, Docker, Kubernetes, React
"""

KNOWN = KnownValues(
    full_name="Amevi KOSSI",
    email="kossi.amevi@example.tg",
    phone="+22890123456",
)


def test_direct_identifiers_never_appear_in_the_payload():
    result = redact_sync(CV_WITH_EVERYTHING, KNOWN)
    lowered = result.text.lower()

    for leaked in (
        "kossi",
        "amevi",
        "kossi.amevi@example.tg",
        "90 12 34 56",
        "palmiers",
        "tokoin",
        "ab1234567",
        "linkedin.com/in",
    ):
        assert leaked not in lowered, f"{leaked!r} leaked into the provider payload"


def test_career_history_survives_redaction():
    """Removing employers or schools would destroy the analysis."""
    result = redact_sync(CV_WITH_EVERYTHING, KNOWN)
    for kept in ("Orabank", "CIB", "Universite de Lome", "FastAPI", "PostgreSQL", "2019-2024"):
        assert kept in result.text, f"{kept!r} was removed but is needed for scoring"


def test_demographics_redacted_by_default_but_still_extracted():
    result = redact_sync(CV_WITH_EVERYTHING, KNOWN, redact_demographics=True)

    assert "Masculin" not in result.text
    assert "Togolaise" not in result.text
    assert "12/03/1990" not in result.text

    # ...yet HR still sees them on the candidate record.
    assert result.demographics["gender"] == "Masculin"
    assert result.demographics["nationality"] == "Togolaise"
    assert result.demographics["date_of_birth"] == "12/03/1990"


def test_demographics_kept_when_the_deployment_opts_out():
    result = redact_sync(CV_WITH_EVERYTHING, KNOWN, redact_demographics=False)
    assert "Masculin" in result.text
    assert "Togolaise" in result.text
    # Direct identifiers are still removed — that switch governs demographics only.
    assert "kossi.amevi@example.tg" not in result.text


def test_every_form_of_the_name_maps_to_one_placeholder():
    result = redact_sync("KOSSI Amevi a travaillé avec Amevi KOSSI. Contact : Amevi.", KNOWN)
    assert result.text.count("[CANDIDATE_NAME]") == 3
    assert result.counts["CANDIDATE_NAME"] == 1


def test_distinct_values_of_the_same_type_get_distinct_placeholders():
    text = "Profils : https://linkedin.com/in/x et https://github.com/y"
    result = redact_sync(text, KnownValues())
    assert "[URL]" in result.text
    assert "[URL_2]" in result.text
    assert result.counts["URL"] == 2


def test_accent_and_case_variants_are_caught():
    result = redact_sync("Rapport rédigé par amévi kossi.", KnownValues(full_name="Amevi KOSSI"))
    assert "amévi" not in result.text.lower()
    assert "kossi" not in result.text.lower()


def test_pii_counts_never_contain_the_values():
    """`pii_detected` is an audit trail of types and counts, never a lookup table."""
    result = redact_sync(CV_WITH_EVERYTHING, KNOWN)
    serialised = str(result.counts)
    assert "kossi" not in serialised.lower()
    assert "example.tg" not in serialised
    assert all(isinstance(v, int) for v in result.counts.values())


@pytest.mark.parametrize(
    "number",
    ["+228 90 12 34 56", "0022890123456", "90 12 34 56", "+33 6 12 34 56 78", "07.12.34.56.78"],
)
def test_phone_formats(number: str):
    result = redact_sync(f"Contactez-moi au {number} pour convenir d'un entretien.", KnownValues())
    assert number not in result.text


def test_years_are_not_mistaken_for_phone_numbers():
    result = redact_sync("Experience 2019-2024 chez Orabank, 2016 diplome.", KnownValues())
    assert "2019-2024" in result.text
    assert "2016" in result.text


def _spacy_available() -> bool:
    from app.services import redaction

    return redaction._load_nlp("fr") is not None


@pytest.mark.skipif(
    not _spacy_available(), reason="requires the fr_core_news_md model (present in the Docker image)"
)
def test_ner_redacts_bare_places_but_never_schools_or_employers():
    """spaCy labels "Université de Lomé" as a single LOC because of the city
    inside it. Redacting it would strip a school — which spec 6.2 forbids,
    because schools and employers are what the criteria score against."""
    text = (
        "Komi AGBEKO\n"
        "Lomé, Togo\n"
        "Master en Génie Logiciel — Université de Lomé\n"
        "2019-2024 Ingénieur backend senior, Orabank Togo\n"
        "2016-2019 Développeur, CIB Lomé\n"
    )
    result = redact_sync(text, KnownValues(full_name="Komi AGBEKO"))

    # The bare city/country line is an address and goes.
    assert "[ADDRESS]" in result.text

    # Career history stays, whatever spaCy called it.
    for kept in ("Université de Lomé", "Orabank Togo", "CIB Lomé", "Génie Logiciel", "2019-2024"):
        assert kept in result.text, f"{kept!r} was redacted but is needed for scoring"

    assert "AGBEKO" not in result.text
