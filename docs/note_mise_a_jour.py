"""Note de mise à jour : taille des dépôts de candidature.

    python docs/note_mise_a_jour.py

Deux pages, destinées à la personne qui administre le serveur. Elle reprend
les helpers de mise en page du guide de déploiement : même police, même pied
de page, même allure que les autres documents remis au cabinet.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, SimpleDocTemplate, Spacer

from guide_deploiement import (
    ALERTE,
    ALERTE_FOND,
    DISCRET,
    FILET,
    bloc_code,
    encadre,
    para,
    puces,
    tableau,
)

SORTIE = Path(__file__).parent / "Note-mise-a-jour-depots.pdf"


def _pied(canvas, doc):
    """Le même pied que les autres guides, à son propre titre près."""
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(DISCRET)
    canvas.drawString(20 * mm, 12 * mm, "TriCV — Note de mise à jour")
    canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, f"page {canvas.getPageNumber()}")
    canvas.setStrokeColor(FILET)
    canvas.setLineWidth(0.4)
    canvas.line(20 * mm, 16 * mm, A4[0] - 20 * mm, 16 * mm)
    canvas.restoreState()


def contenu() -> list:
    h: list = []

    h.append(para("TriCV — mise à jour", "titre"))
    h.append(Spacer(1, 6))

    h.append(para("1. Serveur frontal", "section"))
    h.append(
        para(
            "Dans le bloc <font face='Courier'>server</font> de la configuration "
            "nginx de <b>recrutement.kapiconsult.tg</b> :"
        )
    )
    h.extend(bloc_code(["client_max_body_size 0;", "", "nginx -t", "systemctl reload nginx"]))
    h.append(
        para(
            "Si Cloudflare ou un répartiteur de charge se trouve devant, y lever "
            "la même limite."
        )
    )

    h.append(para("2. Déploiement", "section"))
    h.append(para("Sur le serveur, dans le dossier de l'application :", "corps"))
    h.extend(
        bloc_code(
            [
                "docker compose exec -T db pg_dump -U tricv tricv > sauvegarde-$(date +%F).sql",
                "git pull",
                "docker compose build",
                "docker compose up -d",
                "docker compose exec backend alembic upgrade head",
            ]
        )
    )

    h.append(para("3. Vérification", "section"))
    h.append(
        para(
            "Déposer une candidature de test avec une dizaine de mégaoctets de "
            "pièces jointes. Elle doit s'enregistrer."
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
        title="TriCV — mise à jour : taille des dépôts de candidature",
        author="TriCV",
        subject="Réglages à poser sur le serveur",
    )
    document.build(contenu(), onFirstPage=_pied, onLaterPages=_pied)
    print(f"écrit : {SORTIE}")


if __name__ == "__main__":
    main()
