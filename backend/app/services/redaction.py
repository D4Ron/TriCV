"""PII redaction — the control that keeps candidate identity out of third-party APIs.

This is not a filter bolted onto the analysis; it is how bias-blind scoring is
enforced structurally rather than by asking a model politely. Everything here
runs locally: regex, exact known values from the application form, and spaCy
NER. Nothing in this module makes a network call.

Design: every detector contributes *spans* over the original text. Overlapping
spans are resolved by priority, then the text is rebuilt once with stable
placeholders — the same value always becomes the same placeholder, so the CV
stays readable to the model.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

from app.config import settings

logger = logging.getLogger(__name__)

# --- placeholder types ------------------------------------------------------

NAME = "CANDIDATE_NAME"
EMAIL = "EMAIL"
PHONE = "PHONE"
ADDRESS = "ADDRESS"
DOB = "DOB"
ID_NUMBER = "ID_NUMBER"
URL = "URL"

GENDER = "GENDER"
AGE = "AGE"
MARITAL_STATUS = "MARITAL_STATUS"
NATIONALITY = "NATIONALITY"

DIRECT_IDENTIFIERS = (NAME, EMAIL, PHONE, ADDRESS, ID_NUMBER, URL)
# Per spec 6.2 date of birth is a demographic attribute, not a direct
# identifier, so it follows REDACT_DEMOGRAPHICS (which defaults to true).
DEMOGRAPHIC_TYPES = (GENDER, AGE, DOB, MARITAL_STATUS, NATIONALITY)

# Lower number wins when two detectors claim overlapping text. Emails and URLs
# come first because they are self-delimiting: a name match inside
# `firstname.lastname@corp.tg` must not be allowed to split the address.
PRIORITY = {
    EMAIL: 0,
    URL: 1,
    NAME: 2,
    ID_NUMBER: 3,
    DOB: 4,
    ADDRESS: 5,
    PHONE: 6,
    GENDER: 7,
    MARITAL_STATUS: 7,
    NATIONALITY: 7,
    AGE: 8,
}

HEADER_CHARS = 900  # the identity block of a CV lives at the top


# --- results ----------------------------------------------------------------


@dataclass(slots=True)
class KnownValues:
    """What we already know without looking at the document.

    PUBLIC_FORM applicants typed these into the form; for HR_UPLOAD the
    uploader may have supplied a name. These are the most reliable signal, so
    they are redacted first and everywhere.
    """

    full_name: str | None = None
    email: str | None = None
    phone: str | None = None


@dataclass(slots=True)
class RedactionResult:
    text: str
    applied: bool
    counts: dict[str, int] = field(default_factory=dict)
    contacts: dict[str, str] = field(default_factory=dict)
    demographics: dict[str, str] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


@dataclass(slots=True)
class _Span:
    start: int
    end: int
    kind: str
    value: str
    # spaCy is the least reliable of the three sources (spec 6.2 orders them
    # known values -> regex -> NER), so an NER guess must lose to any labelled
    # match it overlaps. Without this, `Nationalité : Togolaise` loses to
    # spaCy calling "Togolaise" a place, and the value is redacted as an
    # address even when REDACT_DEMOGRAPHICS is off.
    from_ner: bool = False


# --- accent-tolerant matching ----------------------------------------------

_ACCENT_CLASSES = {
    "a": "aàáâãäåAÀÁÂÃÄÅ",
    "c": "cçCÇ",
    "e": "eèéêëEÈÉÊË",
    "i": "iìíîïIÌÍÎÏ",
    "n": "nñNÑ",
    "o": "oòóôõöOÒÓÔÕÖ",
    "u": "uùúûüUÙÚÛÜ",
    "y": "yýÿYÝŸ",
}


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


def _loose_pattern(value: str) -> str:
    """A regex matching `value` regardless of case, accents or spacing."""
    out: list[str] = []
    for char in strip_accents(value).lower():
        if char.isspace():
            out.append(r"[\s\-_.]+")
        elif char in _ACCENT_CLASSES:
            out.append(f"[{_ACCENT_CLASSES[char]}]")
        else:
            out.append(re.escape(char))
    return "".join(out)


# --- detectors --------------------------------------------------------------

RE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

RE_URL = re.compile(
    r"(?:https?://|www\.)[^\s<>\"'()\[\]]{2,}"
    r"|(?:linkedin\.com/in/|github\.com/|gitlab\.com/|behance\.net/|twitter\.com/|x\.com/)"
    r"[A-Za-z0-9._\-/]+",
    re.IGNORECASE,
)

# Togolese numbers are 8 digits (+228 90 12 34 56); international forms and
# French-style national numbers are covered too. Matches are dropped below if
# they carry fewer than 8 digits, which keeps years and small amounts out.
RE_PHONE = re.compile(
    r"(?<![\w+])(?:\+|00)\s?\d{1,3}(?:[\s.\-]?\(?\d{1,4}\)?)?(?:[\s.\-]?\d){6,12}(?![\w])"
    r"|(?<![\w])0\d(?:[\s.\-]?\d){7,10}(?![\w])"
    r"|(?<![\w\d])[79]\d(?:[\s.\-]?\d){6}(?![\w\d])"
)

RE_PHONE_LABELLED = re.compile(
    r"(?:t[ée]l(?:[ée]phone)?|tel|phone|mobile|portable|gsm|whatsapp|cell)\s*[:.\-]?\s*"
    r"(?P<v>[+\d][\d\s.\-()]{6,20}\d)",
    re.IGNORECASE,
)

RE_DOB = re.compile(
    r"(?:date\s+de\s+naissance|n[ée]{1,2}\s+le|born(?:\s+on)?|date\s+of\s+birth|d\.?o\.?b\.?)"
    r"\s*[:\-]?\s*"
    r"(?P<v>\d{1,2}[\s/.\-]\d{1,2}[\s/.\-]\d{2,4}"
    r"|\d{1,2}\s+[A-Za-zÀ-ÿ]{3,10}\.?\s+\d{4}"
    r"|[A-Za-zÀ-ÿ]{3,10}\s+\d{1,2},?\s+\d{4})",
    re.IGNORECASE,
)

RE_ID_NUMBER = re.compile(
    r"(?:cni|carte\s+d['e]identit[ée]|num[ée]ro\s+(?:de\s+)?(?:passeport|cni|s[ée]curit[ée])"
    r"|passeport|passport(?:\s+(?:no|number))?|nif|cnss|ssn|social\s+security)"
    r"\s*(?:n[°o]|#|no\.?|:|-)?\s*(?P<v>[A-Z0-9][A-Z0-9\-]{4,19})",
    re.IGNORECASE,
)

RE_ADDRESS_LABELLED = re.compile(
    r"(?:adresse(?:\s+postale)?|address|domicile|r[ée]sidence)\s*[:\-]\s*(?P<v>[^\n]{5,120})",
    re.IGNORECASE,
)

RE_ADDRESS_STREET = re.compile(
    r"\d{1,4}[,\s]+(?:rue|avenue|av\.|bd|boulevard|impasse|route|quartier|all[ée]e|place|"
    r"street|st\.|road|rd\.|lane|drive)\s+[^\n,;]{2,60}",
    re.IGNORECASE,
)

RE_ADDRESS_POBOX = re.compile(r"\b(?:B\.?P\.?|P\.?O\.?\s*Box)\s*[:\-]?\s*\d{1,6}\b", re.IGNORECASE)

RE_POSTCODE_CITY = re.compile(r"\b\d{5}\s+[A-ZÀ-Þ][A-Za-zÀ-ÿ\-']{2,30}\b")

RE_GENDER = re.compile(
    r"(?:sexe|genre|gender)\s*[:\-]?\s*(?P<v>masculin|f[ée]minin|male|female|homme|femme|m|f)\b"
    r"|\b(?P<v2>masculin|f[ée]minin)\b",
    re.IGNORECASE,
)

RE_AGE = re.compile(
    r"\b(?P<v>\d{2})\s*ans\b|(?:[âa]ge|age)\s*[:\-]?\s*(?P<v2>\d{2})\b"
    r"|\b(?P<v3>\d{2})\s+years?\s+old\b",
    re.IGNORECASE,
)

RE_MARITAL = re.compile(
    r"(?:situation\s+(?:de\s+)?famill\w*|[ée]tat\s+civil|marital\s+status)\s*[:\-]?\s*"
    r"(?P<v>[^\n,;]{3,30})"
    r"|\b(?P<v2>c[ée]libataire|mari[ée]e?|divorc[ée]e?|veuf|veuve|pacs[ée]e?"
    r"|single|married|divorced|widowed)\b",
    re.IGNORECASE,
)

RE_NATIONALITY = re.compile(
    r"(?:nationalit[ée]|nationality|citizenship)\s*[:\-]?\s*(?P<v>[^\n,;]{3,30})",
    re.IGNORECASE,
)


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _spans_from(pattern: re.Pattern[str], text: str, kind: str) -> Iterable[_Span]:
    for match in pattern.finditer(text):
        # Named groups let a pattern anchor on a label but redact only the value.
        start, end, value = match.start(), match.end(), match.group(0)
        for group in ("v", "v2", "v3"):
            if group in pattern.groupindex and match.group(group) is not None:
                start, end = match.span(group)
                value = match.group(group)
                break
        if value.strip():
            yield _Span(start, end, kind, value.strip())


def _known_value_spans(text: str, known: KnownValues) -> list[_Span]:
    spans: list[_Span] = []

    if known.email:
        for match in re.finditer(re.escape(known.email), text, re.IGNORECASE):
            spans.append(_Span(match.start(), match.end(), EMAIL, match.group(0)))

    if known.phone and len(_digits(known.phone)) >= 6:
        # Match the same digits however the CV spaces or punctuates them.
        digits = _digits(known.phone)[-8:]
        loose = r"[\s.\-()]*".join(digits)
        for match in re.finditer(rf"\+?\d{{0,4}}[\s.\-()]*{loose}", text):
            spans.append(_Span(match.start(), match.end(), PHONE, match.group(0)))

    if known.full_name:
        for variant in _name_variants(known.full_name):
            for match in re.finditer(rf"(?<![\w]){variant}(?![\w])", text, re.IGNORECASE):
                spans.append(_Span(match.start(), match.end(), NAME, match.group(0)))

    return spans


def _name_variants(full_name: str) -> list[str]:
    """Regex fragments for a name: as given, reversed, and each part alone.

    CVs write the same name as `Prénom NOM`, `NOM Prénom`, and often just the
    surname in a footer — all of them have to go.
    """
    parts = [p for p in re.split(r"[\s,]+", full_name.strip()) if len(p) >= 2]
    if not parts:
        return []

    variants = [_loose_pattern(" ".join(parts))]
    if len(parts) > 1:
        variants.append(_loose_pattern(" ".join(reversed(parts))))
        variants.append(_loose_pattern(" ".join([parts[-1], *parts[:-1]])))
    # Individual parts of 3+ characters: over-redacting a common word is a far
    # cheaper mistake than leaking the candidate's surname.
    variants.extend(_loose_pattern(p) for p in parts if len(p) >= 3)
    return list(dict.fromkeys(variants))


# --- spaCy NER --------------------------------------------------------------

_NLP_CACHE: dict[str, object] = {}
_NLP_FAILED: set[str] = set()

_FR_MARKERS = {
    "et", "de", "la", "le", "les", "des", "un", "une", "pour", "avec", "en",
    "expérience", "compétences", "formation", "diplôme", "entreprise", "stage",
}
_EN_MARKERS = {
    "and", "the", "of", "for", "with", "in", "experience", "skills",
    "education", "degree", "company", "internship",
}


def detect_language(text: str) -> str:
    words = set(re.findall(r"[a-zà-ÿ]+", text.lower())[:400])
    return "fr" if len(words & _FR_MARKERS) >= len(words & _EN_MARKERS) else "en"


def _load_nlp(lang: str):
    model = "fr_core_news_md" if lang == "fr" else "en_core_web_md"
    if model in _NLP_CACHE:
        return _NLP_CACHE[model]
    if model in _NLP_FAILED:
        return None
    try:
        import spacy

        nlp = spacy.load(model, disable=["lemmatizer", "textcat"])
    except Exception as exc:
        _NLP_FAILED.add(model)
        logger.warning(
            "spaCy model %s unavailable (%s). Redaction continues with known values "
            "and regex only; install it with `python -m spacy download %s`.",
            model, exc, model,
        )
        return None
    _NLP_CACHE[model] = nlp
    return nlp


def loaded_ner_models() -> list[str]:
    return sorted(_NLP_CACHE)


# Institutions whose names contain a place name. spaCy labels "Université de
# Lomé" as a single LOC because of the city inside it — but a school or employer
# must never be redacted: those are exactly what the criteria score against.
INSTITUTION_MARKERS = re.compile(
    r"\b(?:universit[ée]|university|[ée]cole|school|coll[èe]ge|college|institut\w*"
    r"|lyc[ée]e|facult[ée]|faculty|acad[ée]mie|academy|h[ôo]pital|hospital|clinique"
    r"|banque|bank|groupe|group|soci[ée]t[ée]|entreprise|company|minist[èe]re|ministry"
    r"|centre|center|laboratoire|cabinet|agence|agency|fondation|foundation)\b",
    re.IGNORECASE,
)


def _is_bare_place(ent) -> bool:
    """True only for a plain place reference such as `Lomé` or `Togo`.

    Three guards, most reliable first. Each errs toward *keeping* text, because
    over-redacting career history destroys the analysis while leaving a city in
    costs almost nothing.
    """
    text = ent.text.strip()

    # 1. spaCy itself called an overlapping span an organisation.
    if any(
        other.label_ == "ORG" and other.start_char < ent.end_char and ent.start_char < other.end_char
        for other in ent.doc.ents
    ):
        return False

    # 2. The entity names an institution.
    if INSTITUTION_MARKERS.search(text):
        return False

    # 3. A bare city or country is short. "Orabank Togo" is not a place.
    return len(text.split()) <= 2


def _ner_spans(text: str) -> tuple[list[_Span], list[str]]:
    """PERSON and GPE entities in the header region.

    A PERSON found in the header is treated as the candidate and then redacted
    throughout the document — a name that appears once at the top usually
    reappears in a footer or an email address further down.
    """
    nlp = _load_nlp(detect_language(text))
    if nlp is None:
        return [], []

    header = text[:HEADER_CHARS]
    doc = nlp(header)
    spans: list[_Span] = []
    person_names: list[str] = []

    for ent in doc.ents:
        if ent.label_ in ("PER", "PERSON"):
            spans.append(_Span(ent.start_char, ent.end_char, NAME, ent.text, from_ner=True))
            if len(ent.text.strip()) >= 3:
                person_names.append(ent.text.strip())
        elif ent.label_ in ("GPE", "LOC") and _is_bare_place(ent):
            spans.append(
                _Span(ent.start_char, ent.end_char, ADDRESS, ent.text, from_ner=True)
            )

    return spans, person_names


# --- assembly ---------------------------------------------------------------


def _normalise_value(kind: str, value: str) -> str:
    if kind == PHONE:
        return _digits(value)[-9:]
    if kind == EMAIL:
        return value.lower()
    return re.sub(r"\s+", " ", strip_accents(value).lower()).strip()


NER_PENALTY = 100  # pushes every NER guess below every labelled detector


def _resolve(spans: list[_Span]) -> list[_Span]:
    """Greedy non-overlapping selection: priority first, then longest match.

    The penalty only decides *overlaps* — a non-overlapping NER span is still
    accepted, which is what catches a bare `Lomé, Togo` line.
    """
    ordered = sorted(
        spans,
        key=lambda s: (
            PRIORITY.get(s.kind, 99) + (NER_PENALTY if s.from_ner else 0),
            -(s.end - s.start),
            s.start,
        ),
    )
    accepted: list[_Span] = []
    for span in ordered:
        if any(span.start < a.end and a.start < span.end for a in accepted):
            continue
        accepted.append(span)
    return sorted(accepted, key=lambda s: s.start)


def redact_sync(
    text: str,
    known: KnownValues | None = None,
    *,
    redact_demographics: bool | None = None,
    enabled: bool = True,
) -> RedactionResult:
    known = known or KnownValues()
    if redact_demographics is None:
        redact_demographics = settings.redact_demographics

    contacts: dict[str, str] = {}
    demographics: dict[str, str] = {}

    detected: list[_Span] = list(_known_value_spans(text, known))

    for pattern, kind in (
        (RE_EMAIL, EMAIL),
        (RE_URL, URL),
        (RE_ID_NUMBER, ID_NUMBER),
        (RE_DOB, DOB),
        (RE_ADDRESS_LABELLED, ADDRESS),
        (RE_ADDRESS_STREET, ADDRESS),
        (RE_ADDRESS_POBOX, ADDRESS),
        (RE_POSTCODE_CITY, ADDRESS),
        (RE_PHONE_LABELLED, PHONE),
        (RE_PHONE, PHONE),
        (RE_GENDER, GENDER),
        (RE_AGE, AGE),
        (RE_MARITAL, MARITAL_STATUS),
        (RE_NATIONALITY, NATIONALITY),
    ):
        for span in _spans_from(pattern, text, kind):
            if kind == PHONE and len(_digits(span.value)) < 8:
                continue
            detected.append(span)

    ner_spans, person_names = _ner_spans(text)
    detected.extend(ner_spans)
    # A name spaCy found in the header applies to the whole document.
    for person in person_names:
        for variant in _name_variants(person):
            for match in re.finditer(rf"(?<![\w]){variant}(?![\w])", text, re.IGNORECASE):
                detected.append(_Span(match.start(), match.end(), NAME, match.group(0)))

    spans = _resolve(detected)

    # Harvest the values worth keeping before anything is replaced.
    for span in spans:
        if span.kind == EMAIL and "email" not in contacts:
            contacts["email"] = span.value
        elif span.kind == PHONE and "phone" not in contacts:
            contacts["phone"] = span.value
        elif span.kind == NAME and "full_name" not in contacts and " " in span.value.strip():
            contacts["full_name"] = span.value.strip()
        elif span.kind == DOB and "date_of_birth" not in demographics:
            demographics["date_of_birth"] = span.value
        elif span.kind == GENDER and "gender" not in demographics:
            demographics["gender"] = span.value
        elif span.kind == AGE and "age" not in demographics:
            demographics["age"] = span.value
        elif span.kind == MARITAL_STATUS and "marital_status" not in demographics:
            demographics["marital_status"] = span.value
        elif span.kind == NATIONALITY and "nationality" not in demographics:
            demographics["nationality"] = span.value

    if known.full_name:
        contacts["full_name"] = known.full_name
    if known.email:
        contacts["email"] = known.email
    if known.phone:
        contacts["phone"] = known.phone

    if not enabled:
        # Detection still ran: HR sees the extracted profile and the audit trail
        # records what was present, even though nothing is masked.
        return RedactionResult(
            text=text, applied=False, counts={}, contacts=contacts, demographics=demographics
        )

    replaceable = set(DIRECT_IDENTIFIERS)
    if redact_demographics:
        replaceable |= set(DEMOGRAPHIC_TYPES)

    placeholders: dict[tuple[str, str], str] = {}
    seen_per_kind: dict[str, int] = {}
    out: list[str] = []
    cursor = 0

    for span in spans:
        if span.kind not in replaceable:
            continue
        # Every surface form of the candidate's name — `KOSSI Amevi`, `Amevi`,
        # `A. KOSSI` — is the same person, so they all collapse to one
        # placeholder. Numbering only makes sense where there really are
        # several distinct values, as with two different profile URLs.
        key = (span.kind, "" if span.kind == NAME else _normalise_value(span.kind, span.value))
        token = placeholders.get(key)
        if token is None:
            index = seen_per_kind.get(span.kind, 0) + 1
            seen_per_kind[span.kind] = index
            token = f"[{span.kind}]" if index == 1 else f"[{span.kind}_{index}]"
            placeholders[key] = token
        out.append(text[cursor : span.start])
        out.append(token)
        cursor = span.end

    out.append(text[cursor:])

    return RedactionResult(
        text="".join(out),
        applied=True,
        counts=dict(seen_per_kind),
        contacts=contacts,
        demographics=demographics,
    )


async def redact(
    text: str,
    known: KnownValues | None = None,
    *,
    redact_demographics: bool | None = None,
    enabled: bool = True,
) -> RedactionResult:
    """spaCy is CPU-bound; keep it off the event loop."""
    return await asyncio.to_thread(
        redact_sync, text, known, redact_demographics=redact_demographics, enabled=enabled
    )


def describe(counts: dict[str, int], lang: str = "en") -> str:
    """Human phrasing for the dashboard indicator."""
    if not counts:
        return "nothing redacted" if lang == "en" else "aucune donnée masquée"

    labels_en = {
        NAME: "name", EMAIL: "email", PHONE: "phone", ADDRESS: "address",
        DOB: "date of birth", ID_NUMBER: "ID number", URL: "URL",
        GENDER: "gender", AGE: "age", MARITAL_STATUS: "marital status",
        NATIONALITY: "nationality",
    }
    labels_fr = {
        NAME: "nom", EMAIL: "email", PHONE: "téléphone", ADDRESS: "adresse",
        DOB: "date de naissance", ID_NUMBER: "numéro d'identité", URL: "URL",
        GENDER: "genre", AGE: "âge", MARITAL_STATUS: "situation familiale",
        NATIONALITY: "nationalité",
    }
    labels = labels_fr if lang == "fr" else labels_en

    parts: list[str] = []
    for kind, n in counts.items():
        label = labels.get(kind, kind.lower())
        parts.append(label if n <= 1 else f"{n} {label}{'s' if lang == 'en' else ''}")
    suffix = " masqués pour l'IA" if lang == "fr" else " hidden from the AI"
    return ", ".join(parts) + suffix
