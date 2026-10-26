"""État de la production après la mise à jour du 26/10/2026.

    python docs/note_etat_production.py

Une page. Ce qui reste à corriger, relevé en testant le site en ligne, et le
geste correspondant. Rien d'autre.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Spacer

from guide_deploiement import DISCRET, FILET, bloc_code, para, tableau

SORTIE = Path(__file__).parent / "Note-etat-production.pdf"


def _pied(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(DISCRET)
    canvas.drawString(20 * mm, 12 * mm, "TriCV — État de la production")
    canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, f"page {canvas.getPageNumber()}")
    canvas.setStrokeColor(FILET)
    canvas.setLineWidth(0.4)
    canvas.line(20 * mm, 16 * mm, A4[0] - 20 * mm, 16 * mm)
    canvas.restoreState()


def contenu() -> list:
    h: list = []

    h.append(para("TriCV — ce qu'il reste à faire", "titre"))
    h.append(Spacer(1, 4))
    h.append(
        para(
            "La mise à jour est bien déployée et le site fonctionne. Quatre points "
            "restent ouverts, relevés en testant le site en ligne le 26/10/2026."
        )
    )

    h.append(
        tableau(
            ["Problème", "Correctif"],
            [
                [
                    "<b>1. Aucune candidature ne passe.</b> Le serveur refuse tout "
                    "envoi de plus d'1 Mo. Un seul diplôme numérisé en couleur "
                    "dépasse cette taille. Mesuré : accepté à 900 Ko, refusé à 1 Mo.",
                    "Sur le serveur frontal (nginx), dans le bloc "
                    "<font face='Courier'>server</font> — voir les commandes "
                    "ci-dessous. Effet immédiat, aucun déploiement.",
                ],
                [
                    "<b>2. Pas de rédaction assistée.</b> La clé du modèle Gemini "
                    "n'est pas sur le serveur. Les avis et rapports arrivent en "
                    "squelette, à rédiger à la main. Ce n'est plus une erreur.",
                    "Ajouter <font face='Courier'>GEMINI_API_KEY</font> au fichier "
                    "<font face='Courier'>.env</font>, puis redémarrer.",
                ],
                [
                    "<b>3. Aucun courriel, ni reçu ni envoyé.</b> Les identifiants "
                    "Microsoft manquent (tenant, application, secret) et les deux "
                    "interrupteurs sont fermés.",
                    "<b>Paramètres › Courriel</b>, choix « Microsoft 365 » : une "
                    "fenêtre déroule la marche à suivre. Puis cocher "
                    "<i>Relever la boîte</i> et <i>Envoyer les courriels</i>.",
                ],
                [
                    "<b>4. La référence de l'avis est l'intitulé du poste</b> — "
                    "long, et avec une espace avant la virgule. C'est elle que les "
                    "candidats recopient dans l'objet de leur courriel.",
                    "Sur le poste, <b>Modifier le texte</b> de l'avis n'y touche "
                    "pas : la référence se change à la création d'un avis. Une "
                    "forme courte convient mieux.",
                ],
            ],
            [84 * mm, 81 * mm],
        )
    )

    h.append(para("Les deux commandes du serveur", "section"))
    h.append(para("Point 1 — lever la limite de taille :", "corps"))
    h.extend(
        bloc_code(
            [
                "# dans le bloc server { … } de la configuration nginx",
                "client_max_body_size 0;",
                "",
                "nginx -t && systemctl reload nginx",
            ]
        )
    )
    h.append(para("Point 2 — la clé du modèle :", "corps"))
    h.extend(
        bloc_code(
            [
                "# dans le fichier .env de l'application",
                "GEMINI_API_KEY=la-clé-fournie-par-Google",
                "",
                "docker compose up -d",
            ]
        )
    )

    h.append(para("Vérifier", "section"))
    h.append(
        para(
            "Déposer une candidature de test avec une dizaine de mégaoctets de "
            "pièces : elle doit s'enregistrer. Puis, sur un poste, « Rédiger avec "
            "l'IA » doit rendre un texte. Puis, dans Paramètres › Courriel, "
            "« Tester la connexion » et « Tester l'envoi » doivent aboutir."
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
        title="TriCV — état de la production",
        author="TriCV",
        subject="Points ouverts et correctifs",
    )
    document.build(contenu(), onFirstPage=_pied, onLaterPages=_pied)
    print(f"écrit : {SORTIE}")


if __name__ == "__main__":
    main()
