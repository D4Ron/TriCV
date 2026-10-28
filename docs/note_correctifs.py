"""Les correctifs de la production, en gestes seulement.

    python docs/note_correctifs.py

Une page, sans explication : les commandes et les écrans, dans l'ordre. La
limite de taille de nginx, réglée sur le serveur le 28/10, n'y figure plus.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Spacer

from guide_deploiement import DISCRET, FILET, bloc_code, para

SORTIE = Path(__file__).parent / "Note-correctifs.pdf"


def _pied(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(DISCRET)
    canvas.drawString(20 * mm, 12 * mm, "TriCV — correctifs de la production")
    canvas.setStrokeColor(FILET)
    canvas.setLineWidth(0.4)
    canvas.line(20 * mm, 16 * mm, A4[0] - 20 * mm, 16 * mm)
    canvas.restoreState()


def contenu() -> list:
    h: list = []

    h.append(para("TriCV — correctifs", "titre"))
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

    h.append(para("2. Choisir le modèle d'IA et coller sa clé", "section"))
    h.append(
        para(
            "<b>Paramètres › Général › Modèle d'IA</b> : fournisseur « Google Gemini », "
            "coller la clé (aistudio.google.com › Get API key), enregistrer. Aucun "
            "accès au serveur."
        )
    )

    h.append(para("3. Brancher la boîte de recrutement", "section"))
    h.append(
        para(
            "<b>Paramètres › Courriel</b> : la fenêtre de la marche à suivre s'ouvre ; "
            "la suivre. Puis cocher <i>Relever la boîte</i> et <i>Envoyer les "
            "courriels</i>, et enregistrer."
        )
    )

    h.append(para("4. Contrôler", "section"))
    h.append(
        para(
            "<b>Paramètres › État</b> : chaque ligne doit afficher « En place ». "
            "Cliquer « Essayer » sur la ligne Modèle d'IA."
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
        title="TriCV — correctifs",
        author="TriCV",
        subject="Correctifs de la production",
    )
    document.build(contenu(), onFirstPage=_pied, onLaterPages=_pied)
    print(f"écrit : {SORTIE}")


if __name__ == "__main__":
    main()
