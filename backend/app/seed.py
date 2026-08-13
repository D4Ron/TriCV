"""Demo data for an offline showcase.

Every seeded candidate carries complete analysis data written straight to the
database — criterion scores, justifications, strengths, gaps — so the dashboard,
the rankings and all three exports work with no network and no API key.

    docker compose exec backend python -m app.seed
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import random
from datetime import timedelta

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from sqlalchemy import delete, select

from app.config import settings
from app.db import SessionLocal
from app.logging_config import configure_logging
from app.models import (
    AnalysisStatus,
    AuditLog,
    Candidate,
    CandidateSource,
    Criterion,
    CriterionScore,
    HrStatus,
    Language,
    RecruitmentSession,
    SessionStatus,
    User,
    UserRole,
    new_public_key,
)
from app.models.base import utcnow
from app.security import hash_password
from app.services import redaction, scoring
from app.services.storage import get_storage

logger = logging.getLogger(__name__)
random.seed(20260810)  # a reproducible demo


# --- the fiche --------------------------------------------------------------

BACKEND_CRITERIA = [
    ("Expérience Python / FastAPI",
     "Au moins 3 ans de développement backend en Python, idéalement avec FastAPI ou Django.",
     9, True),
    ("Bases de données relationnelles",
     "Conception de schémas, optimisation de requêtes, PostgreSQL de préférence.",
     8, True),
    ("Conteneurisation et déploiement",
     "Docker, CI/CD, mise en production autonome.", 7, False),
    ("Architecture et qualité de code",
     "Découpage en services, tests automatisés, revue de code.", 8, False),
    ("Intégration d'APIs tierces",
     "Consommation d'APIs REST, gestion des erreurs et des limites de débit.", 6, False),
    ("Autonomie et gestion de projet",
     "Capacité à mener une fonctionnalité de bout en bout avec peu de supervision.", 7, False),
    ("Communication en français et en anglais",
     "Documentation écrite claire, échanges avec une équipe distribuée.", 5, False),
    ("Sensibilité produit",
     "Compréhension des enjeux métier, propositions d'amélioration.", 4, False),
]

RH_CRITERIA = [
    ("Expérience en recrutement", "Au moins 2 ans sur des postes de chargé(e) de recrutement.", 9, True),
    ("Maîtrise des outils ATS", "Utilisation quotidienne d'un ATS et de jobboards.", 7, False),
    ("Conduite d'entretiens", "Entretiens structurés, grilles d'évaluation.", 8, False),
    ("Droit du travail", "Connaissance du cadre légal togolais et des obligations employeur.", 6, False),
    ("Reporting et indicateurs", "Suivi des KPI de recrutement, restitution à la direction.", 5, False),
]


# --- candidate profiles -----------------------------------------------------
# Bands: the analysis fields are written directly, so scores span 0-100 and the
# must-have rule is exercised (two candidates fail one).

PROFILES = [
    # (name, email, years, education, band, source, hr_status, fails_must_have)
    ("Amevi KOSSI", "amevi.kossi@example.tg", 8, "Master en Informatique", "top", "HR_UPLOAD", "SHORTLISTED", False),
    ("Afiwa MENSAH", "afiwa.mensah@example.tg", 7, "Ingénieur logiciel", "top", "PUBLIC_FORM", "SHORTLISTED", False),
    ("Komi AGBEKO", "komi.agbeko@example.tg", 6, "Master en Génie Logiciel", "top", "PUBLIC_FORM", "SHORTLISTED", False),
    ("Yawa ADJOVI", "yawa.adjovi@example.tg", 5, "Licence Informatique", "good", "HR_UPLOAD", "MAYBE", False),
    ("Sena LAWSON", "sena.lawson@example.tg", 5, "Master Systèmes d'Information", "good", "PUBLIC_FORM", "NEW", False),
    ("Kodjo TETTEH", "kodjo.tetteh@example.tg", 4, "Licence Informatique", "good", "PUBLIC_FORM", "NEW", False),
    ("Akouvi DOSSEH", "akouvi.dosseh@example.tg", 4, "Master Data", "good", "HR_UPLOAD", "NEW", False),
    ("Mawuli AKAKPO", "mawuli.akakpo@example.tg", 3, "Licence Réseaux", "middle", "PUBLIC_FORM", "NEW", False),
    ("Edem SODJI", "edem.sodji@example.tg", 3, "BTS Informatique", "middle", "PUBLIC_FORM", "NEW", False),
    ("Ayaba KOUEVI", "ayaba.kouevi@example.tg", 2, "Licence Informatique", "middle", "HR_UPLOAD", "NEW", False),
    ("Kossi ATTIOGBE", "kossi.attiogbe@example.tg", 2, "BTS Développement", "middle", "PUBLIC_FORM", "NEW", False),
    ("Adjo BAWA", "adjo.bawa@example.tg", 1, "Licence Informatique", "low", "PUBLIC_FORM", "REJECTED", True),
    ("Selom AHIANYO", "selom.ahianyo@example.tg", 1, "BTS Gestion", "low", "PUBLIC_FORM", "REJECTED", True),
    ("Nadia FIAWOO", "nadia.fiawoo@example.tg", 0, "Licence Économie", "low", "PUBLIC_FORM", "NEW", False),
    ("Elom GBEDEMAH", "elom.gbedemah@example.tg", 6, "Master Informatique", "good", "HR_UPLOAD", "NEW", False),
]

BANDS = {"top": (78, 95), "good": (58, 77), "middle": (42, 62), "low": (10, 38)}

STRENGTHS = [
    "Expérience directe sur une stack Python/FastAPI en production",
    "A conçu et optimisé des schémas PostgreSQL sur des volumes importants",
    "Pipeline CI/CD mis en place et maintenu de façon autonome",
    "Pratique établie des tests automatisés et de la revue de code",
    "Intégrations d'APIs tierces documentées, avec gestion des erreurs",
    "A porté des fonctionnalités de bout en bout sans supervision",
    "Documentation technique claire en français et en anglais",
]

GAPS = [
    "Pas d'expérience Docker mentionnée dans le CV",
    "Aucune référence à des tests automatisés",
    "L'expérience backend reste inférieure au seuil attendu",
    "Aucun élément sur l'optimisation de bases de données",
    "Le CV ne précise pas le niveau d'anglais",
    "Pas d'exemple de mise en production autonome",
]

JUSTIFICATIONS = {
    "high": [
        "Le CV mentionne {n} ans sur cette technologie, avec des projets nommés.",
        "Expérience détaillée et directement transposable au poste.",
        "Plusieurs réalisations concrètes citées sur ce point.",
    ],
    "mid": [
        "Le CV évoque ce point sans détailler l'ampleur des réalisations.",
        "Expérience réelle mais partielle au regard de ce qui est attendu.",
        "Compétence citée dans la liste des outils, sans mise en situation.",
    ],
    "low": [
        "Aucune preuve de cette compétence dans le CV.",
        "Le CV ne traite pas ce critère.",
        "Mention indirecte seulement, sans expérience concrète.",
    ],
}


def build_cv_pdf(name: str, years: int, education: str, email: str, phone: str) -> bytes:
    """A plausible CV, generated locally so the demo needs no sample files."""
    buffer = io.BytesIO()
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm, title=name,
    )
    story = [
        Paragraph(f"<b>{name}</b>", styles["Title"]),
        Paragraph("Développeur backend", styles["Heading2"]),
        Paragraph(f"Email : {email}<br/>Tél : {phone}<br/>Lomé, Togo", styles["Normal"]),
        Spacer(1, 10),
        Paragraph("<b>EXPÉRIENCE PROFESSIONNELLE</b>", styles["Heading3"]),
    ]

    employers = ["Orabank Togo", "CIB Lomé", "Togocom", "Ecobank", "Groupe Kapi"]
    year = 2024
    remaining = max(years, 1)
    while remaining > 0:
        span = min(remaining, random.randint(2, 3))
        employer = random.choice(employers)
        story.append(
            Paragraph(
                f"<b>{year - span}–{year} · {employer}</b><br/>"
                f"Développement et maintenance d'applications backend en Python "
                f"(FastAPI, Django), base de données PostgreSQL, déploiement Docker. "
                f"Participation aux revues de code et à la mise en production.",
                styles["Normal"],
            )
        )
        story.append(Spacer(1, 6))
        year -= span
        remaining -= span

    story += [
        Paragraph("<b>FORMATION</b>", styles["Heading3"]),
        Paragraph(f"{education} — Université de Lomé", styles["Normal"]),
        Spacer(1, 8),
        Paragraph("<b>COMPÉTENCES</b>", styles["Heading3"]),
        Paragraph(
            "Python, FastAPI, Django, PostgreSQL, Docker, Git, REST, pytest, Linux",
            styles["Normal"],
        ),
        Spacer(1, 8),
        Paragraph("<b>LANGUES</b>", styles["Heading3"]),
        Paragraph("Français (langue maternelle), Anglais (professionnel)", styles["Normal"]),
    ]

    doc.build(story)
    return buffer.getvalue()


def _criterion_score(band: str, is_must_have: bool, fails_must_have: bool) -> float:
    if is_must_have and fails_must_have:
        return float(random.randint(12, 34))  # below the 40 floor, on purpose
    low, high = BANDS[band]
    return float(max(0, min(100, random.randint(low, high) + random.randint(-8, 8))))


def _justification(score: float, years: int) -> str:
    tier = "high" if score >= 65 else "mid" if score >= 40 else "low"
    return random.choice(JUSTIFICATIONS[tier]).format(n=years)


async def _wipe(db) -> None:
    """Idempotent: re-seeding replaces the demo rather than duplicating it."""
    await db.execute(delete(AuditLog))
    await db.execute(delete(CriterionScore))
    await db.execute(delete(Candidate))
    await db.execute(delete(Criterion))
    await db.execute(delete(RecruitmentSession))
    await db.commit()


async def seed() -> None:
    configure_logging()
    storage = get_storage()

    async with SessionLocal() as db:
        await _wipe(db)

        admin = (
            await db.execute(select(User).where(User.email == settings.seed_admin_email.lower()))
        ).scalar_one_or_none()
        if admin is None:
            admin = User(
                email=settings.seed_admin_email.lower(),
                password_hash=hash_password(settings.seed_admin_password),
                full_name="Administrateur TriCV",
                role=UserRole.ADMIN,
            )
            db.add(admin)
            logger.info("created admin %s", admin.email)

        recruiter = (
            await db.execute(select(User).where(User.email == "recruteur@tricv.example"))
        ).scalar_one_or_none()
        if recruiter is None:
            recruiter = User(
                email="recruteur@tricv.example",
                password_hash=hash_password(settings.seed_admin_password),
                full_name="Awa Recruteuse",
                role=UserRole.RECRUITER,
            )
            db.add(recruiter)

        await db.flush()

        # --- open session with a full ranking ------------------------------
        open_session = RecruitmentSession(
            title="Développeur Backend Senior — Lomé",
            position="Développeur Backend Senior",
            description=(
                "Renfort de l'équipe plateforme sur une application de paiement. "
                "Stack Python/FastAPI, PostgreSQL, Docker. Poste basé à Lomé, "
                "deux jours de télétravail par semaine."
            ),
            department="Technologie",
            status=SessionStatus.OPEN,
            language=Language.FR,
            score_threshold=60,
            accepts_public_applications=True,
            retention_days=180,
            created_by_id=admin.id,
            public_key=new_public_key(),
        )
        for order, (name, description, weight, must) in enumerate(BACKEND_CRITERIA):
            open_session.criteria.append(
                Criterion(
                    name=name, description=description, weight=weight,
                    is_must_have=must, display_order=order,
                )
            )
        db.add(open_session)

        draft_session = RecruitmentSession(
            title="Chargé(e) de recrutement — brouillon",
            position="Chargé(e) de recrutement",
            description=(
                "Fiche en cours de rédaction. Les critères sont à valider avec la "
                "direction avant ouverture."
            ),
            department="Ressources Humaines",
            status=SessionStatus.DRAFT,
            language=Language.FR,
            score_threshold=65,
            accepts_public_applications=False,
            created_by_id=admin.id,
            public_key=new_public_key(),
        )
        for order, (name, description, weight, must) in enumerate(RH_CRITERIA):
            draft_session.criteria.append(
                Criterion(
                    name=name, description=description, weight=weight,
                    is_must_have=must, display_order=order,
                )
            )
        db.add(draft_session)
        await db.flush()

        criteria = list(open_session.criteria)
        now = utcnow()

        for index, (
            name, email, years, education, band, source, hr_status, fails_must
        ) in enumerate(PROFILES):
            phone = f"+228 9{random.randint(0, 9)} {random.randint(10, 99)} "\
                    f"{random.randint(10, 99)} {random.randint(10, 99)}"
            pdf_bytes = build_cv_pdf(name, years, education, email, phone)

            from app.services.storage import build_key

            key = build_key("application/pdf")
            await storage.save(key, pdf_bytes)

            # Run the real redaction pipeline over the real generated CV, so the
            # privacy panel in the demo shows genuine numbers.
            extracted = (
                f"{name}\nEmail : {email}\nTél : {phone}\nLomé, Togo\n"
                f"{education} — Université de Lomé\n"
                "Python, FastAPI, PostgreSQL, Docker, Git, REST, pytest"
            )
            redacted = redaction.redact_sync(
                extracted,
                redaction.KnownValues(full_name=name, email=email, phone=phone),
            )

            scores = {
                c.id: _criterion_score(band, c.is_must_have, fails_must) for c in criteria
            }
            outcome = scoring.compute(
                [scoring.CriterionInput(c.id, c.name, c.weight, c.is_must_have) for c in criteria],
                scores,
            )

            submitted = now - timedelta(days=random.randint(1, 21), hours=random.randint(0, 23))
            candidate = Candidate(
                session_id=open_session.id,
                full_name=name,
                email=email,
                phone=phone,
                source=CandidateSource(source),
                cv_text_redacted=redacted.text,
                pii_detected=dict(redacted.counts),
                redaction_applied=True,
                demographics=dict(redacted.demographics) or None,
                cv_filename=f"CV_{name.replace(' ', '_')}.pdf",
                cv_storage_path=key,
                cv_mime_type="application/pdf",
                cv_hash=hashlib.sha256(pdf_bytes).hexdigest(),
                years_experience=years,
                education_level=education,
                extracted_skills=["Python", "FastAPI", "PostgreSQL", "Docker", "Git"],
                analysis_status=AnalysisStatus.ANALYZED,
                analysis_mode="redacted_text",
                ai_score=outcome.ai_score,
                ai_recommendation=outcome.recommendation,
                ai_summary=(
                    f"Profil avec {years} an(s) d'expérience backend. "
                    + (
                        "Correspond largement aux attentes du poste."
                        if outcome.ai_score >= 75
                        else "Correspond partiellement aux attentes du poste."
                        if outcome.ai_score >= 50
                        else "S'écarte nettement des attentes du poste."
                    )
                ),
                ai_strengths=random.sample(STRENGTHS, k=3 if band in ("top", "good") else 2),
                ai_gaps=random.sample(GAPS, k=2 if band in ("top", "good") else 3),
                missing_must_haves=outcome.missing_must_haves,
                hr_status=HrStatus(hr_status),
                hr_notes=(
                    "Entretien téléphonique effectué, très bon contact."
                    if hr_status == "SHORTLISTED"
                    else None
                ),
                submitted_at=submitted,
                analyzed_at=submitted + timedelta(minutes=random.randint(1, 6)),
            )
            # One manual override, so the demo shows HR outranking the model.
            if index == 3:
                candidate.manual_score = 82.0

            db.add(candidate)
            await db.flush()

            for criterion in criteria:
                db.add(
                    CriterionScore(
                        candidate_id=candidate.id,
                        criterion_id=criterion.id,
                        score=scores[criterion.id],
                        justification=_justification(scores[criterion.id], years),
                    )
                )

        db.add(
            AuditLog(
                action="candidate.override",
                entity_type="candidate",
                entity_id=None,
                user_id=recruiter.id,
                details={"note": "Score ajusté après entretien téléphonique."},
            )
        )
        await db.commit()

        logger.info("seeded 2 sessions and %d analysed candidates", len(PROFILES))
        logger.info("dashboard login: %s / %s", admin.email, settings.seed_admin_password)
        logger.info(
            "public application page: /apply/%s", open_session.public_key
        )


if __name__ == "__main__":
    asyncio.run(seed())
