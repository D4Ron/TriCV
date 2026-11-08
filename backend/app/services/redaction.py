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
# Une personne que cite le candidat - référent, signataire - et qui n'est pas lui.
REFERENT = "REFERENT"

DIRECT_IDENTIFIERS = (NAME, EMAIL, PHONE, ADDRESS, ID_NUMBER, URL, REFERENT)
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
    REFERENT: 2,
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

# Fenêtre dans laquelle une entité peut encore *être* l'état civil du candidat.
#
# Un CV met son nom et son adresse dans ses premières lignes ; passé cela, ce
# que le modèle NER appelle « personne » est presque toujours un employeur ou
# un intitulé de fonction — « Responsable », « Conducteur », « EBOMAF Togo »,
# « Cabinet Maître AGBO ». Ces faux positifs ne coûtaient pas qu'une ligne :
# le nom retenu était ensuite masqué dans tout le document, si bien qu'un CV
# entier perdait ses intitulés de poste. Restreindre la reconnaissance au bloc
# d'identité supprime la quasi-totalité de ces cas sans rien laisser passer de
# l'état civil, qui n'a jamais été écrit ailleurs.
BLOC_IDENTITE = 400

# Le bloc d'identité s'arrête aussi à la première rubrique, quelle que soit sa
# position : un CV court met sa première expérience avant le 400e caractère, et
# la borne fixe seule y laissait « Orabank Togo » se faire prendre pour l'état
# civil du candidat.
_TITRES_RUBRIQUE = re.compile(
    r"^[ \t]*(?:[IVX]+[.)]\s*)?(?:profil|objectif|r[ée]sum[ée]|synth[èe]se|parcours"
    r"|formations?|dipl[ôo]mes?|[ée]tudes|exp[ée]riences?|comp[ée]tences|langues"
    r"|certifications?|r[ée]f[ée]rences|loisirs|centres?\s+d|divers|autres|contact"
    r"|coordonn[ée]es|logiciels|informatique|education|skills|languages|employment"
    r"|work|professional|references)\b",
    re.IGNORECASE | re.MULTILINE,
)

# Un « CURRICULUM VITAE » ou un « PROFIL » en tête de page n'ouvre pas la
# première rubrique : il titre la feuille. En deçà de cette marge, un titre ne
# ferme donc pas le bloc d'identité — sinon il n'en resterait rien.
_MARGE_TITRE = 60


def _fin_du_bloc_identite(text: str) -> int:
    for titre in _TITRES_RUBRIQUE.finditer(text[:HEADER_CHARS]):
        if titre.start() >= _MARGE_TITRE:
            return min(titre.start(), BLOC_IDENTITE)
    return BLOC_IDENTITE


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
    # « Né(e) le » est la forme la plus courante des CV d'ici : la parenthèse
    # faisait échouer la reconnaissance et la date de naissance partait en clair.
    # « Né(e): 03/05/1979 », « Date de naissance : le 14/02/1990 », « Born in
    # ACCRA, Ghana, on 11 March 1979 » : trois formes qui passaient en clair.
    r"(?:date\s+de\s+naissance|\bn[ée]{1,2}\s*\(?e\)?\s*(?:le\b)?|\bn[ée]{1,2}\s+le"
    r"|\bborn(?:\s+in\s+[^\n\d]{2,60}?\bon|\s+on)?|date\s+of\s+birth|d\.?o\.?b\.?)"
    r"\s*[:\-]?\s*(?:le\s+)?"
    r"(?P<v>\d{1,2}[\s/.\-]\d{1,2}[\s/.\-]\d{2,4}"
    r"|\d{1,2}\s+[A-Za-zÀ-ÿ]{3,10}\.?\s+\d{4}"
    r"|[A-Za-zÀ-ÿ]{3,10}\s+\d{1,2},?\s+\d{4})",
    re.IGNORECASE,
)

RE_ID_NUMBER = re.compile(
    # \b de part et d'autre du libellé : sans eux, « nif » mordait dans
    # « planification » ou « significative », et la fin du mot passait pour un
    # numéro. Le numéro lui-même porte au moins un chiffre.
    r"\b(?:cni|carte\s+d['e]identit[ée]|num[ée]ro\s+(?:de\s+)?(?:passeport|cni|s[ée]curit[ée])"
    r"|passeport|passport(?:\s+(?:no|number))?|nif|cnss|ssn|social\s+security)\b"
    r"\s*(?:n[°o]|#|no\.?|:|-)?\s*(?P<v>(?=[A-Z\-]*\d)[A-Z0-9][A-Z0-9\-]{4,19})",
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

# Un mot de valeur : lettres, apostrophes et traits d'union, jamais un saut de
# ligne. Sert aux champs « Nationalité : … » et « Situation de famille : … »,
# dont la capture doit s'arrêter au champ suivant de la même ligne.
_MOT = r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’\-]{2,29}"

RE_GENDER = re.compile(
    r"(?:sexe|genre|gender)\s*[:\-]?\s*(?P<v>masculin|f[ée]minin|male|female|homme|femme|m|f)\b"
    r"|\b(?P<v2>masculin|f[ée]minin)\b",
    re.IGNORECASE,
)

# « 12 ans » tout court est un âge ; « 12 ans d'expérience » est l'argument
# central du CV. La forme nue exige donc que rien de professionnel ne suive :
# sans cette réserve, la phrase qui résume la carrière devenait
# « [AGE] d'expérience », et le modèle n'avait plus l'ancienneté sous les yeux.
# Une durée introduite par « pendant », « depuis » ou « plus de » n'est pas
# davantage un âge.
_APRES_DUREE = (
    r"(?!\s*(?:d[’']|de\s+)"
    r"(?:exp[ée]rience|exp[ée]riences|anciennet[ée]|pratique|m[ée]tier|carri[èe]re"
    r"|service|activit[ée]|exercice))"
    # « 11 ans en industrie », « 7 ans dans la logistique » : une carrière.
    r"(?!\s+(?:en|dans|chez|au|aux)\b)"
)
_AVANT_DUREE = r"(?<!pendant )(?<!depuis )(?<!durant )(?<!plus de )(?<!environ )(?<!soit )"

RE_AGE = re.compile(
    rf"{_AVANT_DUREE}\b(?P<v>\d{{2}})\s*ans\b{_APRES_DUREE}"
    # \b : « Dépannage : 22 10 00 00 » ou « entreposage\n10. » ne sont pas des âges.
    r"|\b(?:[âa]ge|age)\b[ \t]*[:\-]?[ \t]*(?P<v2>\d{2})\b(?![ \t]*\d)"
    r"|\b(?P<v3>\d{2})\s+years?\s+old\b",
    re.IGNORECASE,
)

RE_MARITAL = re.compile(
    r"(?:situation\s+(?:de\s+)?famill\w*|[ée]tat\s+civil|marital\s+status)[ \t]*[:\-]?[ \t]*"
    rf"(?P<v>{_MOT}(?:[ \t]+{_MOT})?)"
    r"|\b(?P<v2>c[ée]libataire|mari[ée]e?|divorc[ée]e?|veuf|veuve|pacs[ée]e?"
    r"|single|married|divorced|widowed)\b",
    re.IGNORECASE,
)

# Une nationalité est un adjectif d'un ou deux mots. Capturer « jusqu'au
# prochain saut de ligne » avalait le champ suivant de la même ligne
# — « Togolaise — Sexe : Masculin » — et faisait disparaître le sexe avec lui.
# [ \t]+ et non \s+ : \s englobe le saut de ligne, ce qui recollait la valeur
# avec le premier mot de la ligne suivante (« Togolaise\nLinkedIn »).
RE_NATIONALITY = re.compile(
    rf"(?:nationalit[ée]|nationality|citizenship)[ \t]*[:\-]?[ \t]*"
    rf"(?P<v>{_MOT}(?:[ \t]+{_MOT})?)",
    re.IGNORECASE,
)


# Une adresse coupée par un retour à la ligne, ou lue par l'OCR avec des
# espaces : « prenom.nom\n@gmail.com », « nom_et 73@yahoo de », « nom3@gma ».
RE_EMAIL_LOOSE = re.compile(
    r"[A-Za-z0-9._%+\-]{3,}(?:[ \t][A-Za-z0-9._%+\-]{1,10})?[ \t]*\n?[ \t]*@[ \t]?"
    r"[A-Za-z0-9\-]{2,}(?:[.\s][A-Za-z]{2,4}\b)?"
)

# Le lieu de naissance suit la date : « né le 3 mai 1979 à Aného (Préf. des
# Lacs) », « Born in ACCRA », « Lieu de naissance : Lomé ».
_LIEU = r"[A-ZÀ-Þ][A-Za-zÀ-ÿ'’\-]+(?:[ \t]*[(/\-]?[ \t]*[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’\-.)]*){0,3}"
RE_BIRTHPLACE = re.compile(
    r"(?:\bn[ée]{1,2}(?:\s*\(e\))?|\bborn)\b[^\n]{0,40}?\d{4}[ \t,]*(?:[àa]|at|in)[ \t]+(?P<v>" + _LIEU + r")"
    r"|(?:lieu\s+de\s+naissance|place\s+of\s+birth|\bborn\s+in)[ \t]*[:\-]?[ \t]*(?:[àa][ \t]+)?(?P<v2>"
    + _LIEU
    + r")",
    re.IGNORECASE,
)

# Le nom d'épouse : « Afi épse AMEGAN », « Madame X Epouse Y ».
RE_NOM_MARITAL = re.compile(
    r"\b(?:[ée]p(?:ou)?se|[ée]pse|ep\.|veuve)\s+(?P<v>[A-ZÀ-Þ][A-Za-zÀ-ÿ'’\-]+)"
)

# Les référents : une rubrique « Références », puis des lignes de noms, de
# fonctions et de contacts, jusqu'à la première qui reprend le parcours.
_TITRE_REFERENCES = re.compile(
    r"^\W*(?:quelques\s+)?(?:r[ée]f[ée]rences?(?:\s+professionnelles)?"
    r"|personnes?\s+(?:de\s+r[ée]f[ée]rences?|ressources?)|adresses?\s+de\s+r[ée]f[ée]rences?)\W*$",
    re.IGNORECASE,
)
# « Prénom NOM » ou « NOM Prénom », civilité facultative.
_PERSONNE = re.compile(
    r"(?:\b(?:M\.|Mr\.?|Mme|Mlle|Monsieur|Madame|Dr\.?|Pr\.?)\s+)?"
    r"(?:[A-ZÀ-Þ][a-zà-ÿ'’]+(?:[ \-][A-ZÀ-Þ][a-zà-ÿ'’]+){0,2}\s+[A-ZÀ-Þ][A-ZÀ-Þ'’\-]{2,}(?:\s+[A-ZÀ-Þ][A-ZÀ-Þ'’\-]{2,})?"
    r"|[A-ZÀ-Þ][A-ZÀ-Þ'’\-]{2,}(?:\s+[A-ZÀ-Þ][A-ZÀ-Þ'’\-]{2,})?\s+[A-ZÀ-Þ][a-zà-ÿ'’]+(?:[ \-][A-ZÀ-Þ][a-zà-ÿ'’]+){0,2})"
)
_LIGNES_DE_REFERENCES = 15
# « Groupe SOLARIS », « Cabinet KAPI » : un organisme, pas une personne.
_MOTS_D_ORGANISME = frozenset(
    """groupe societe cabinet entreprise entreprises banque universite institut ministere compagnie
    agence direction port office centre ecole lycee hotel clinique hopital fondation association
    projet programme bureau service departement cooperation union conseil commission""".split()
)


def _referent_spans(text: str) -> list[_Span]:
    """Les personnes citées sous une rubrique « Références »."""
    from app.services.lecture_locale import plages

    spans: list[_Span] = []
    position = 0
    restantes = 0
    for ligne in text.splitlines(keepends=True):
        propre = ligne.strip()
        if len(propre) <= 45 and _TITRE_REFERENCES.match(propre):
            restantes = _LIGNES_DE_REFERENCES
        elif restantes:
            if propre and (
                plages(propre) or len(propre) > 110 or (len(propre) <= 45 and _TITRES_RUBRIQUE.match(propre))
            ):
                restantes = 0
            else:
                restantes -= 1
                for m in _PERSONNE.finditer(ligne):
                    mots = m.group(0).split()
                    if strip_accents(mots[0]).lower() in _MOTS_D_ORGANISME or _mot_reserve(mots[-1]):
                        continue
                    spans.append(_Span(position + m.start(), position + m.end(), REFERENT, m.group(0)))
        position += len(ligne)
    return spans


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
    # cheaper mistake than leaking the candidate's surname — sauf quand ce mot
    # est du vocabulaire de CV. « Cabinet », « Responsable » ou « Français »
    # pris pour un morceau de nom effaçaient une rubrique entière.
    variants.extend(
        _loose_pattern(p) for p in parts if len(p) >= 3 and not _mot_reserve(p)
    )
    # La fiche ne découpe pas toujours le nom comme les pièces : « AGBO KLA
    # Ya Ovi » sur la fiche, « AGBOKLA Yaovi » sur l'attestation ; et un
    # certificat imprime « AG BO KLA », un autre « N'DOSSOU » ou « NDOSSOU ».
    # Chaque suite de morceaux consécutifs, lue lettre à lettre avec un
    # séparateur facultatif, couvre ces formes.
    lettres = [re.sub(r"[^a-z]", "", strip_accents(p).lower()) for p in parts]
    for debut in range(len(lettres)):
        for fin in range(debut + 1, len(lettres) + 1):
            mot = "".join(lettres[debut:fin])
            if len(mot) >= 4 and not _mot_reserve(mot):
                variants.append(_lettre_a_lettre(mot))
    return list(dict.fromkeys(variants))


def _lettre_a_lettre(mot: str) -> str:
    """« ndossou » → n'importe quelle graphie : N'DOSSOU, N DOSSOU, NDOSSOU, N-Dossou."""
    morceaux = [f"[{_ACCENT_CLASSES[c]}]" if c in _ACCENT_CLASSES else re.escape(c) for c in mot]
    return r"[ \t'’\-.]?".join(morceaux)


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
    """Les modèles NER *disponibles*, et non seulement ceux déjà en mémoire.

    Le chargement est paresseux : signaler le cache ferait dire à l'écran
    Paramètres qu'aucun modèle n'est installé tant qu'aucune expurgation n'a
    tourné, ce qui est faux et inquiétant à lire.
    """
    if _NLP_CACHE:
        return sorted(_NLP_CACHE)
    try:
        from spacy.util import get_installed_models

        attendus = {"fr_core_news_md", "en_core_web_md"}
        return sorted(attendus & set(get_installed_models()))
    except ImportError:
        return []


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


# Months and weekdays are routinely mislabelled as places by the French model
# ("Mars 2009" → LOC). Redacting them shreds every employment date.
_CALENDAR_WORDS = frozenset(
    """janvier fevrier février mars avril mai juin juillet aout août septembre
    octobre novembre decembre décembre lundi mardi mercredi jeudi vendredi
    samedi dimanche january february march april may june july august september
    october november december""".split()
)

# How far to look left of an entity for the institution it belongs to.
_LEFT_CONTEXT = 40


# Étiquettes et valeurs de champs que le modèle prend régulièrement pour des
# lieux ou des personnes : « Nationalité », « Sexe », « Masculin »… Les
# redacter détruit le champ voisin et fait disparaître la donnée réelle.
_CHAMPS_ET_VALEURS = """nationalite nationality citizenship sexe genre gender age
    adresse address telephone email courriel situation famille etat civil
    masculin feminin male female homme femme celibataire marie mariee divorce
    divorcee veuf veuve permis"""

# Titres de rubrique et vocabulaire de CV. Le modèle en fait régulièrement des
# lieux : « FORMATION », « LINGUISTIQUES », « Parcours ».
_RUBRIQUES = """curriculum vitae profil objectif resume synthese parcours
    formation formations diplome diplomes etudes experience experiences
    professionnelle professionnelles professionnel academique competences
    aptitudes langues langue certifications certification references loisirs
    interets divers autres contact contacts coordonnees informations
    personnelles logiciels outils stage stages education skills languages"""

# Intitulés de fonction. Ce sont les faux positifs les plus coûteux : pris pour
# un nom de personne, l'intitulé était masqué dans tout le document et chaque
# expérience perdait son poste.
_FONCTIONS = """responsable directeur directrice chef cheffe adjoint adjointe
    assistant assistante charge chargee consultant consultante ingenieur
    ingenieure technicien technicienne cadre gestionnaire comptable juriste
    specialiste expert experte analyste conseiller conseillere coordonnateur
    coordinateur coordinatrice superviseur controleur auditeur secretaire agent
    operateur conducteur animateur formateur enseignant professeur medecin
    infirmier infirmiere pharmacien commercial vendeur caissier magasinier
    logisticien informaticien developpeur administrateur maitre manager officer
    director head lead senior junior stagiaire apprenti reporting supervision
    pilotage suivi appui gestion direction"""

# Noms de langue. Le modèle français étiquette « Français », « Anglais »,
# « Mina » comme des lieux : la rubrique « Langues » disparaissait entièrement,
# et le barème comptait zéro langue là où le CV en déclarait trois.
_LANGUES = """francais anglais allemand espagnol portugais italien arabe chinois
    russe neerlandais japonais ewe mina kabye kabiye tem moba haoussa peul
    bambara wolof lingala swahili yoruba fon twi french english german spanish
    portuguese italian arabic"""

_NON_ENTITES = frozenset(
    strip_accents(mot)
    for mot in (
        f"{_CHAMPS_ET_VALEURS} {_RUBRIQUES} {_FONCTIONS} {_LANGUES}".lower().split()
    )
)


def _premiere_ligne(ent) -> tuple[int, int, str] | None:
    """Ramène une entité à sa première ligne, bornes comprises.

    Le modèle agrège volontiers par-dessus les sauts de ligne — « AGBEKO
    Yawo\\nDate », « Kara\\n\\nEXPERIENCE ». Rejeter l'entité entière, comme on
    le faisait, jetait le nom du candidat avec le titre de section qui le
    suivait : le CV partait alors au modèle avec l'état civil intact. La
    tronquer conserve la partie utile et n'expurge que ce qui a été reconnu.
    """
    texte = ent.text.split("\n", 1)[0]
    fin = ent.start_char + len(texte)
    rogne = texte.rstrip()
    fin -= len(texte) - len(rogne)
    texte = rogne.lstrip()
    debut = fin - len(texte)
    return (debut, fin, texte) if texte else None


def _mot_reserve(texte: str) -> bool:
    """Un seul mot de vocabulaire de CV suffit à disqualifier l'entité.

    Le contrôle porte sur chaque mot et non sur l'entité entière : « Cabinet
    Maître AGBO » et « Responsable administratif » ne se reconnaissent pas
    autrement, et tous deux se propageaient ensuite dans tout le document.
    """
    for mot in texte.split():
        nettoye = strip_accents(mot.lower()).strip(".,;:()[]«»\"'")
        if nettoye and (nettoye in _NON_ENTITES or nettoye in _CALENDAIRE):
            return True
    return False


_CALENDAIRE = frozenset(strip_accents(w) for w in _CALENDAR_WORDS)


def _entite_suspecte(doc_text: str, debut: int, texte: str) -> bool:
    """Filtres communs à PERSON et aux lieux.

    Chacun penche du côté de *conserver* le texte : sur-expurger un parcours
    détruit l'analyse, alors qu'une ville laissée en clair ne coûte presque
    rien.
    """
    if not texte:
        return True

    # Un mois, un titre de rubrique, un intitulé de fonction, un nom de langue :
    # rien de tout cela n'est un lieu ni une personne.
    if _mot_reserve(texte):
        return True

    # Un établissement nommé dans l'entité elle-même — « Université de Lomé »,
    # « Cabinet Maître AGBO » — doit rester intact : c'est ce que la grille note.
    if INSTITUTION_MARKERS.search(texte):
        return True

    # L'établissement est souvent juste à gauche : le modèle étiquette « Lomé »
    # dans « Université de Lomé », jamais le groupe entier. Expurger la queue
    # mutile le nom de l'école, qui doit rester intact.
    debut_ligne = doc_text.rfind("\n", 0, debut) + 1
    gauche = doc_text[max(debut_ligne, debut - _LEFT_CONTEXT) : debut]
    return bool(INSTITUTION_MARKERS.search(gauche))


def _is_bare_place(ent, debut: int, fin: int, texte: str) -> bool:
    """True only for a plain place reference such as `Lomé` or `Togo`."""
    if _entite_suspecte(ent.doc.text, debut, texte):
        return False

    # spaCy itself called an overlapping span an organisation.
    if any(
        other.label_ == "ORG" and other.start_char < fin and debut < other.end_char
        for other in ent.doc.ents
    ):
        return False

    # A bare city or country is short. "Orabank Togo" is not a place.
    return len(texte.split()) <= 2


def _ressemble_a_un_nom(texte: str) -> bool:
    """Deux mots au minimum, sinon ce n'est pas un état civil.

    Un CV écrit son nom en entier ; ce que le modèle isole en un seul mot est,
    dans les faits, un intitulé de poste ou une ville. Le nom saisi au
    formulaire, lui, passe par `KnownValues` et reste traqué sous toutes ses
    formes, y compris le patronyme seul en pied de page.
    """
    mots = [m for m in re.split(r"[\s,]+", texte.strip()) if len(m) >= 2]
    return len(mots) >= 2


def _ner_spans(text: str) -> tuple[list[_Span], list[str]]:
    """PERSON and GPE entities in the identity block.

    A PERSON found there is treated as the candidate and then redacted
    throughout the document — a name that appears once at the top usually
    reappears in a footer or an email address further down. Beyond that block,
    a « personne » est un employeur ou une fonction : voir `BLOC_IDENTITE`.
    """
    nlp = _load_nlp(detect_language(text))
    if nlp is None:
        return [], []

    header = text[:HEADER_CHARS]
    doc = nlp(header)
    bloc = _fin_du_bloc_identite(text)
    spans: list[_Span] = []
    person_names: list[str] = []

    for ent in doc.ents:
        if ent.label_ not in ("PER", "PERSON", "GPE", "LOC"):
            continue
        borne = _premiere_ligne(ent)
        if borne is None or borne[0] >= bloc:
            continue
        debut, fin, texte = borne

        if ent.label_ in ("PER", "PERSON"):
            if _entite_suspecte(doc.text, debut, texte) or not _ressemble_a_un_nom(texte):
                continue
            spans.append(_Span(debut, fin, NAME, texte, from_ner=True))
            person_names.append(texte)
        elif _is_bare_place(ent, debut, fin, texte):
            spans.append(_Span(debut, fin, ADDRESS, texte, from_ner=True))

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
        (RE_EMAIL_LOOSE, EMAIL),
        (RE_BIRTHPLACE, ADDRESS),
        (RE_NOM_MARITAL, NAME),
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

    detected.extend(_referent_spans(text))

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
        if span.kind == EMAIL and "email" not in contacts and RE_EMAIL.fullmatch(span.value):
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
        NATIONALITY: "nationality", REFERENT: "third party",
    }
    labels_fr = {
        NAME: "nom", EMAIL: "email", PHONE: "téléphone", ADDRESS: "adresse",
        DOB: "date de naissance", ID_NUMBER: "numéro d'identité", URL: "URL",
        GENDER: "genre", AGE: "âge", MARITAL_STATUS: "situation familiale",
        NATIONALITY: "nationalité", REFERENT: "tiers",
    }
    labels = labels_fr if lang == "fr" else labels_en

    parts: list[str] = []
    for kind, n in counts.items():
        label = labels.get(kind, kind.lower())
        parts.append(label if n <= 1 else f"{n} {label}{'s' if lang == 'en' else ''}")
    suffix = " masqués pour l'IA" if lang == "fr" else " hidden from the AI"
    return ", ".join(parts) + suffix
