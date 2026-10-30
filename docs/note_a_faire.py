"""Ce qu'il reste à faire, côté administrateur, et rien d'autre.

    python docs/note_a_faire.py

Une demi-page : les gestes, sans explication.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Spacer

from guide_deploiement import DISCRET, FILET, bloc_code, para

SORTIE = Path(__file__).parent / "A-faire-administrateur.pdf"


def _pied(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(DISCRET)
    canvas.drawString(20 * mm, 12 * mm, "TriCV — à faire")
    canvas.setStrokeColor(FILET)
    canvas.setLineWidth(0.4)
    canvas.line(20 * mm, 16 * mm, A4[0] - 20 * mm, 16 * mm)
    canvas.restoreState()


def contenu() -> list:
    h: list = []
    h.append(para("TriCV — à faire", "titre"))
    h.append(Spacer(1, 4))

    h.append(para("1. Mettre à jour l'application", "section"))
    h.extend(
        bloc_code(
            [
                "git pull",
                "docker compose build",
                "docker compose up -d",
                "docker compose exec backend alembic upgrade head",
            ]
        )
    )

    h.append(para("2. Accorder le consentement Microsoft", "section"))
    h.append(
        para(
            "<b>entra.microsoft.com</b> › Inscriptions d'applications › l'application de "
            "TriCV › <b>Autorisations de l'API</b> :"
        )
    )
    h.append(
        para(
            "• Microsoft Graph › <b>Autorisations d'application</b> (pas déléguées) : "
            "<font face='Courier'>Mail.ReadWrite</font> et "
            "<font face='Courier'>Mail.Send</font>.<br/>"
            "• Cliquer <b>Accorder un consentement d'administrateur</b> — les deux "
            "lignes doivent passer au vert."
        )
    )
    return h


def main() -> None:
    document = SimpleDocTemplate(
        str(SORTIE),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=22 * mm,
        title="TriCV — à faire",
        author="TriCV",
        subject="Gestes restants côté administrateur",
    )
    document.build(contenu(), onFirstPage=_pied, onLaterPages=_pied)
    print(f"écrit : {SORTIE}")


if __name__ == "__main__":
    main()
