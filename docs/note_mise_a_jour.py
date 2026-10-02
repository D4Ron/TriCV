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

    h.append(para("TriCV — mise à jour : taille des dépôts", "titre"))
    h.append(Spacer(1, 6))

    h.append(
        para(
            "Cette note décrit deux réglages à poser sur le serveur. Le premier "
            "concerne la taille des dossiers que les candidats déposent, le second "
            "est le déploiement de la mise à jour elle-même. Comptez une dizaine "
            "de minutes."
        )
    )

    # --- le pourquoi ---------------------------------------------------
    h.append(para("Ce qui est en cause", "section"))
    h.append(
        para(
            "Un dossier de candidature est fait de documents numérisés : diplômes, "
            "attestations, pièce d'identité. Numérisés en couleur, ils pèsent "
            "couramment plusieurs mégaoctets."
        )
    )
    h.append(
        para(
            "Le serveur frontal — celui qui reçoit les requêtes avant de les passer "
            "à l'application — limite par défaut à <b>un mégaoctet</b> la taille "
            "d'un envoi. Au-delà, il refuse la requête lui-même, avant que TriCV "
            "en voie quoi que ce soit. Le candidat reçoit alors une page d'erreur "
            "technique, et son dossier n'est pas enregistré."
        )
    )
    h.append(
        para(
            "TriCV, de son côté, accepte les dépôts jusqu'à 100 Mo. Ce n'est donc "
            "pas l'application qu'il faut régler, mais le serveur frontal."
        )
    )

    # --- réglage 1 -----------------------------------------------------
    h.append(para("Réglage 1 — lever la limite du serveur frontal", "section"))
    h.append(
        para(
            "Dans la configuration nginx du site <b>recrutement.kapiconsult.tg</b>, "
            "à l'intérieur du bloc <font face='Courier'>server { … }</font>, "
            "ajoutez la ligne :"
        )
    )
    h.extend(bloc_code(["client_max_body_size 0;"]))
    h.append(
        para(
            "<font face='Courier'>0</font> signifie « pas de limite ». "
            "Puis vérifiez la syntaxe et rechargez, sans interrompre le service :"
        )
    )
    h.extend(bloc_code(["nginx -t", "systemctl reload nginx"]))
    h.append(
        para(
            "Ce réglage prend effet immédiatement et ne demande aucun déploiement. "
            "Il suffit à lui seul pour que les dossiers volumineux passent."
        )
    )
    h.extend(
        encadre(
            "Si un autre service se trouve devant",
            "Cloudflare, un répartiteur de charge ou le panneau d'un hébergeur "
            "appliquent leur propre limite, indépendante de celle de nginx. Il faut "
            "alors la lever au même endroit. Chez Cloudflare, la taille maximale "
            "dépend de l'offre souscrite et ne se règle pas par configuration.",
        )
    )

    # --- réglage 2 -----------------------------------------------------
    h.append(PageBreak())
    h.append(para("Réglage 2 — déployer la mise à jour", "section"))
    h.append(
        para(
            "La mise à jour apporte, côté candidat, des messages d'erreur lisibles "
            "en français lorsqu'un envoi échoue — avec l'adresse à qui écrire — et "
            "l'affichage du poids total des pièces jointes avant l'envoi. Elle "
            "apporte aussi les autres travaux en cours sur l'application."
        )
    )
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
    h.append(
        para(
            "La première ligne sauvegarde la base avant toute chose. Les trois "
            "suivantes reconstruisent et redémarrent les conteneurs. La dernière "
            "applique les migrations de base de données, s'il y en a."
        )
    )
    h.extend(
        encadre(
            "Le nom du service",
            "Les commandes ci-dessus emploient <font face='Courier'>backend</font>, "
            "qui est le nom du service dans <font face='Courier'>docker-compose.yml</font>. "
            "D'anciennes notes mentionnent <font face='Courier'>api</font> : cette "
            "forme ne fonctionne pas.",
        )
    )

    # --- vérification --------------------------------------------------
    h.append(para("Vérifier que tout est en place", "section"))
    h.append(
        tableau(
            ["À faire", "Ce qu'on doit obtenir"],
            [
                [
                    "Ouvrir une page de candidature et joindre des documents "
                    "représentant une dizaine de mégaoctets",
                    "Le formulaire affiche le nombre de pièces et leur poids total.",
                ],
                [
                    "Envoyer la candidature",
                    "« Candidature enregistrée » s'affiche. Le dossier apparaît "
                    "sur le poste, dans TriCV.",
                ],
                [
                    "Si l'envoi échoue encore",
                    "Le message indique en français que le dossier dépasse ce que "
                    "le serveur accepte : c'est qu'une limite subsiste en amont de "
                    "nginx (voir l'encadré page précédente).",
                ],
            ],
            [70 * mm, 95 * mm],
        )
    )

    # --- la suite ------------------------------------------------------
    h.append(para("Ensuite, quand vous le souhaiterez", "section"))
    h.append(
        para(
            "La boîte de courriel du recrutement n'est pas encore configurée dans "
            "TriCV : l'adresse <b>recrutement@kapiconsult.tg</b> est affichée aux "
            "candidats, mais l'application ne relève pas encore cette boîte et "
            "n'envoie pas encore de messages depuis celle-ci."
        )
    )
    h.append(
        para(
            "Cela se règle dans <b>Paramètres › Courriel</b>. En choisissant "
            "« Microsoft 365 », une fenêtre s'ouvre et déroule la marche à suivre "
            "étape par étape, en fabriquant au passage le lien de consentement à "
            "ouvrir — ou à transmettre à qui administre l'annuaire Microsoft. Rien "
            "de ce qui précède n'en dépend."
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
