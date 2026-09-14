from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.exports.data import (
    HR_STATUS_LABELS,
    RECOMMENDATION_LABELS,
    ExportData,
    translate,
)

INK = colors.HexColor("#1f2933")
MUTED = colors.HexColor("#6b7280")
RULE = colors.HexColor("#d7dce2")
BAND = colors.HexColor("#f4f6f8")

SCORE_COLOURS = (
    (80, colors.HexColor("#1f7a4d")),
    (60, colors.HexColor("#2f7fb8")),
    (40, colors.HexColor("#b8860b")),
    (0, colors.HexColor("#a83232")),
)


def _score_colour(score: float | None):
    if score is None:
        return MUTED
    for threshold, colour in SCORE_COLOURS:
        if score >= threshold:
            return colour
    return MUTED


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TriTitle", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=22, leading=26, textColor=INK, alignment=TA_LEFT, spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "TriSubtitle", parent=base["Normal"], fontSize=12, leading=16,
            textColor=MUTED, spaceAfter=14,
        ),
        "h2": ParagraphStyle(
            "TriH2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=13, leading=17, textColor=INK, spaceBefore=14, spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "TriH3", parent=base["Heading3"], fontName="Helvetica-Bold",
            fontSize=10.5, leading=14, textColor=INK, spaceBefore=8, spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "TriBody", parent=base["Normal"], fontSize=9.5, leading=13.5, textColor=INK,
        ),
        "small": ParagraphStyle(
            "TriSmall", parent=base["Normal"], fontSize=8, leading=11, textColor=MUTED,
        ),
        "cell": ParagraphStyle(
            "TriCell", parent=base["Normal"], fontSize=8.5, leading=11, textColor=INK,
        ),
    }


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 12 * mm, "Kapi Consult · TriCV")
    canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, str(canvas.getPageNumber()))
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.4)
    canvas.line(18 * mm, 16 * mm, A4[0] - 18 * mm, 16 * mm)
    canvas.restoreState()


def _distribution_table(data: ExportData, styles) -> Table:
    scores = [c.score for c in data.candidates if c.score is not None]
    buckets = ((80, 100), (60, 79), (40, 59), (20, 39), (0, 19))
    widest = max(
        (sum(1 for s in scores if low <= s <= high) for low, high in buckets), default=0
    ) or 1

    rows = []
    for low, high in buckets:
        count = sum(1 for s in scores if low <= s <= high)
        bar = "█" * round(18 * count / widest) if count else ""
        rows.append([f"{low}–{high}", bar, str(count)])

    table = Table(rows, colWidths=[22 * mm, 90 * mm, 14 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle([
            ("FONT", (0, 0), (-1, -1), "Helvetica", 8.5),
            ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
            ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#2f7fb8")),
            ("ALIGN", (2, 0), (2, -1), "RIGHT"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
        ])
    )
    return table


def _criteria_table(data: ExportData, styles) -> Table:
    header = [data.label("criterion"), data.label("weight"), data.label("must_have")]
    rows = [[Paragraph(f"<b>{h}</b>", styles["cell"]) for h in header]]
    for criterion in data.criteria:
        name = criterion.name
        if criterion.description:
            name += f'<br/><font color="#6b7280" size="7.5">{criterion.description}</font>'
        rows.append([
            Paragraph(name, styles["cell"]),
            Paragraph(f"{criterion.weight}/10", styles["cell"]),
            Paragraph(
                data.label("yes") if criterion.is_must_have else data.label("no"), styles["cell"]
            ),
        ])

    table = Table(rows, colWidths=[128 * mm, 20 * mm, 26 * mm], repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BAND),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
            ("LINEBELOW", (0, 1), (-1, -1), 0.25, RULE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    return table


def _ranking_table(data: ExportData, styles) -> Table:
    header = [
        data.label("rank"),
        data.label("candidate"),
        data.label("score"),
        data.label("recommendation"),
        data.label("hr_status"),
    ]
    rows = [[Paragraph(f"<b>{h}</b>", styles["cell"]) for h in header]]
    styling = [
        ("BACKGROUND", (0, 0), (-1, 0), BAND),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
    ]

    for index, candidate in enumerate(data.candidates, start=1):
        identity = candidate.full_name
        if candidate.email:
            identity += f'<br/><font color="#6b7280" size="7.5">{candidate.email}</font>'
        if candidate.missing_must_haves:
            identity += (
                f'<br/><font color="#a83232" size="7.5">'
                f'{data.label("missing_must_haves")}: '
                f'{", ".join(candidate.missing_must_haves)}</font>'
            )
        score = "—" if candidate.score is None else f"{candidate.score:.0f}"
        if candidate.manual_score is not None:
            score += "*"

        rows.append([
            Paragraph(str(candidate.rank), styles["cell"]),
            Paragraph(identity, styles["cell"]),
            Paragraph(f"<b>{score}</b>", styles["cell"]),
            Paragraph(
                translate(RECOMMENDATION_LABELS, data.language, candidate.recommendation),
                styles["cell"],
            ),
            Paragraph(
                translate(HR_STATUS_LABELS, data.language, candidate.hr_status), styles["cell"]
            ),
        ])
        styling.append(("TEXTCOLOR", (2, index), (2, index), _score_colour(candidate.score)))
        styling.append(("LINEBELOW", (0, index), (-1, index), 0.25, RULE))

    table = Table(
        rows, colWidths=[12 * mm, 74 * mm, 16 * mm, 34 * mm, 38 * mm],
        repeatRows=1, hAlign="LEFT",
    )
    table.setStyle(TableStyle(styling))
    return table


def _candidate_detail(candidate, data: ExportData, styles) -> list:
    story: list = [
        Paragraph(f"{candidate.rank}. {candidate.full_name}", styles["h2"]),
    ]

    facts = [
        (data.label("score"), "—" if candidate.score is None else f"{candidate.score:.1f}/100"),
        (
            data.label("recommendation"),
            translate(RECOMMENDATION_LABELS, data.language, candidate.recommendation),
        ),
        (data.label("hr_status"), translate(HR_STATUS_LABELS, data.language, candidate.hr_status)),
        (data.label("email"), candidate.email or "—"),
        (data.label("phone"), candidate.phone or "—"),
        (
            data.label("experience"),
            f"{candidate.years_experience} {data.label('years')}"
            if candidate.years_experience is not None
            else "—",
        ),
        (data.label("education"), candidate.education_level or "—"),
    ]
    fact_rows = [
        [Paragraph(f"<b>{k}</b>", styles["small"]), Paragraph(str(v), styles["cell"])]
        for k, v in facts
    ]
    fact_table = Table(fact_rows, colWidths=[38 * mm, 136 * mm], hAlign="LEFT")
    fact_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ])
    )
    story.append(fact_table)

    if candidate.summary:
        story += [Paragraph(data.label("summary"), styles["h3"]),
                  Paragraph(candidate.summary, styles["body"])]

    if candidate.missing_must_haves:
        story.append(Paragraph(data.label("missing_must_haves"), styles["h3"]))
        story.append(
            Paragraph(
                '<font color="#a83232">' + " · ".join(candidate.missing_must_haves) + "</font>",
                styles["body"],
            )
        )

    for key, items in (("strengths", candidate.strengths), ("gaps", candidate.gaps)):
        if items:
            story.append(Paragraph(data.label(key), styles["h3"]))
            for item in items:
                story.append(Paragraph(f"• {item}", styles["body"]))

    if candidate.scores_by_criterion:
        story.append(Paragraph(data.label("criteria"), styles["h3"]))
        rows = []
        styling = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ]
        for index, criterion in enumerate(data.criteria):
            score = candidate.scores_by_criterion.get(criterion.id)
            label = criterion.name + (" *" if criterion.is_must_have else "")
            justification = candidate.justifications.get(criterion.id, "")
            rows.append([
                Paragraph(label, styles["cell"]),
                Paragraph("—" if score is None else f"<b>{score:.0f}</b>", styles["cell"]),
                Paragraph(justification or "—", styles["cell"]),
            ])
            styling.append(("TEXTCOLOR", (1, index), (1, index), _score_colour(score)))
            styling.append(("LINEBELOW", (0, index), (-1, index), 0.25, RULE))

        table = Table(rows, colWidths=[46 * mm, 14 * mm, 114 * mm], hAlign="LEFT")
        table.setStyle(TableStyle(styling))
        story.append(table)

    if candidate.hr_notes:
        story += [Paragraph(data.label("notes"), styles["h3"]),
                  Paragraph(candidate.hr_notes, styles["body"])]

    return story


def render(data: ExportData) -> bytes:
    buffer = io.BytesIO()
    styles = _styles()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title=f"{data.label('title')} — {data.session.title}",
        author="Kapi Consult",
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=22 * mm,
    )

    scores = [c.score for c in data.candidates if c.score is not None]
    average = sum(scores) / len(scores) if scores else None

    story: list = [
        Paragraph(data.label("title"), styles["title"]),
        Paragraph(data.session.title, styles["subtitle"]),
    ]

    summary_rows = [
        (data.label("position"), data.session.position),
        (data.label("department"), data.session.department or "—"),
        (data.label("generated"), data.generated_at.strftime("%d/%m/%Y %H:%M UTC")),
        (data.label("scope"), data.label(f"scope_{data.scope}")),
        (data.label("candidates"), f"{len(data.candidates)} / {data.total_in_session}"),
        (data.label("threshold"), f"{data.session.score_threshold}/100"),
        (data.label("average"), f"{average:.1f}/100" if average is not None else "—"),
    ]
    table = Table(
        [[Paragraph(f"<b>{k}</b>", styles["small"]), Paragraph(str(v), styles["cell"])]
         for k, v in summary_rows],
        colWidths=[40 * mm, 134 * mm],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ])
    )
    story.append(table)

    if data.session.description:
        story += [Spacer(1, 8), Paragraph(data.session.description, styles["body"])]

    if scores:
        story += [Paragraph(data.label("distribution"), styles["h2"]),
                  _distribution_table(data, styles)]

    story += [Paragraph(data.label("criteria"), styles["h2"]), _criteria_table(data, styles)]
    story += [Spacer(1, 10), Paragraph(data.label("disclaimer"), styles["small"])]

    story.append(PageBreak())
    story.append(Paragraph(data.label("ranking"), styles["h2"]))
    if data.candidates:
        story.append(_ranking_table(data, styles))
        if any(c.manual_score is not None for c in data.candidates):
            story += [
                Spacer(1, 4),
                Paragraph(f"* {data.label('manual_note')}", styles["small"]),
            ]
    else:
        story.append(Paragraph(data.label("no_candidates"), styles["body"]))

    detailed = [c for c in data.candidates if c.hr_status == "SHORTLISTED"] or data.candidates[:10]
    if detailed:
        story.append(PageBreak())
        story.append(Paragraph(data.label("detail"), styles["h2"]))
        for index, candidate in enumerate(detailed):
            if index:
                story.append(Spacer(1, 12))
            flowables = _candidate_detail(candidate, data, styles)
            # Keep the heading with the fact table so a name never dangles alone
            # at the foot of a page.
            story.append(KeepTogether(flowables[:2]))
            story += flowables[2:]

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
