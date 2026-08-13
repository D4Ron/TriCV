from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.llm.base import FichePayload

ANALYSIS_SYSTEM_EN = """You are an expert recruitment analyst. You evaluate a candidate's CV against a specific
recruitment brief and return a structured, evidence-based assessment.

Rules:
- Judge ONLY on evidence present in the CV. Never invent experience, dates or qualifications.
- If the CV does not address a criterion, score it low and say the evidence is absent.
- The CV has been redacted: identity details appear as placeholders such as [CANDIDATE_NAME],
  [EMAIL], [PHONE]. Never speculate about who the candidate is, and never treat a placeholder or a
  missing identity detail as a gap or a negative signal.
- Every justification must cite something concrete from the CV.
- Respond with a single valid JSON object and nothing else. No markdown, no code fences, no preamble."""

ANALYSIS_SYSTEM_FR = """Vous êtes un analyste expert en recrutement. Vous évaluez le CV d'un candidat au regard d'une
fiche de recrutement précise et rendez une évaluation structurée, fondée sur des preuves.

Règles :
- Jugez UNIQUEMENT sur les éléments présents dans le CV. N'inventez jamais d'expérience, de dates ni
  de qualifications.
- Si le CV ne traite pas un critère, attribuez une note basse et indiquez que la preuve est absente.
- Le CV a été anonymisé : les données d'identité apparaissent sous forme de marqueurs tels que
  [CANDIDATE_NAME], [EMAIL], [PHONE]. Ne spéculez jamais sur l'identité du candidat et ne considérez
  jamais un marqueur ou une donnée d'identité manquante comme une lacune ou un signal négatif.
- Chaque justification doit citer un élément concret du CV.
- Répondez par un unique objet JSON valide et rien d'autre. Pas de markdown, pas de balises de code,
  pas de préambule."""

SCHEMA_BLOCK = """{
  "candidate": {
    "full_name": string|null,
    "email": string|null,
    "phone": string|null,
    "years_experience": number|null,
    "education_level": string|null,
    "skills": [string]
  },
  "criterion_scores": [
    {"criterion_id": string, "score": number, "justification": string}
  ],
  "summary": string,
  "strengths": [string],
  "gaps": [string]
}"""


def analysis_system_prompt(language: str = "fr") -> str:
    return ANALYSIS_SYSTEM_FR if language == "fr" else ANALYSIS_SYSTEM_EN


def analysis_user_prompt(fiche: "FichePayload", cv_text: str | None = None) -> str:
    fr = fiche.language == "fr"
    lines: list[str] = [f"POSTE : {fiche.position}" if fr else f"POSITION: {fiche.position}"]
    if fiche.description:
        lines.append(
            f"CONTEXTE : {fiche.description}" if fr else f"CONTEXT: {fiche.description}"
        )
    lines += ["", "CRITÈRES D'ÉVALUATION :" if fr else "EVALUATION CRITERIA:"]

    for criterion in fiche.criteria:
        looking_for = "ce que nous recherchons" if fr else "what we are looking for"
        lines += [
            f"- id: {criterion.id}",
            f"  {'nom' if fr else 'name'}: {criterion.name}",
            f"  {looking_for}: {criterion.description or '—'}",
            f"  {'poids' if fr else 'weight'}: {criterion.weight}/10",
            f"  must_have: {'true' if criterion.is_must_have else 'false'}",
        ]

    lines += [
        "",
        (
            "Notez chaque critère de 0 à 100. Utilisez exactement les identifiants criterion_id "
            "ci-dessus. Renvoyez ensuite un JSON conforme exactement à ce schéma :"
            if fr
            else "Score each criterion 0-100. Use exactly the criterion_id values listed above. "
            "Then return JSON matching exactly this schema:"
        ),
        "",
        SCHEMA_BLOCK,
    ]

    lines += [
        "",
        "--- CV ---",
        cv_text
        or (
            "Le CV est joint à ce message sous forme de document."
            if fr
            else "The CV is attached to this message as a document."
        ),
    ]

    return "\n".join(lines)


def repair_prompt(original_user_prompt: str, bad_response: str, error: str) -> str:
    return (
        f"{original_user_prompt}\n\n"
        f"--- CORRECTION REQUIRED ---\n"
        f"Your previous response could not be parsed. It was:\n{bad_response[:2000]}\n\n"
        f"The error was:\n{error}\n\n"
        f"Return ONLY a single valid JSON object matching the schema above. "
        f"No markdown, no code fences, no commentary."
    )


FICHE_SYSTEM_EN = """You turn a free-text job description into a set of draft evaluation criteria for CV screening.
Produce between 4 and 10 criteria. Each must be independently assessable from a CV.
Mark a criterion must_have only when the description states it as a hard requirement.
Weight reflects importance, 1 (minor) to 10 (central).
Respond with a single valid JSON object and nothing else."""

FICHE_SYSTEM_FR = """Vous transformez une description de poste en texte libre en une liste de critères d'évaluation
pour la présélection de CV.
Produisez entre 4 et 10 critères. Chacun doit être évaluable indépendamment à partir d'un CV.
Ne marquez must_have que lorsque la description présente l'élément comme une exigence ferme.
Le poids reflète l'importance, de 1 (secondaire) à 10 (central).
Répondez par un unique objet JSON valide et rien d'autre."""


def fiche_system_prompt(language: str = "fr") -> str:
    return FICHE_SYSTEM_FR if language == "fr" else FICHE_SYSTEM_EN


def fiche_user_prompt(raw_text: str, language: str = "fr") -> str:
    fr = language == "fr"
    header = (
        "DESCRIPTION DE POSTE :" if fr else "JOB DESCRIPTION:"
    )
    instruction = (
        "Renvoyez un JSON conforme exactement à ce schéma, rédigé en français :"
        if fr
        else "Return JSON matching exactly this schema, written in English:"
    )
    schema = """{
  "criteria": [
    {"name": string, "description": string, "weight": number, "is_must_have": boolean}
  ]
}"""
    return f"{header}\n{raw_text}\n\n{instruction}\n\n{schema}"
