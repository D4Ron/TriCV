"""Note de mise en service : ce qu'il reste à configurer en production.

    python docs/note_mise_en_service.py

Écrite d'après l'état relevé sur https://recrutement.kapiconsult.tg : le
courriel et le modèle d'IA y sont déclarés mais sans identifiants, et les deux
interrupteurs du courriel sont fermés. Trois pages, pour la personne qui
administre le serveur.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, SimpleDocTemplate, Spacer

from guide_deploiement import (
    DISCRET,
    FILET,
    bloc_code,
    encadre,
    para,
    puces,
    tableau,
)

SORTIE = Path(__file__).parent / "Note-mise-en-service.pdf"


def _pied(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(DISCRET)
    canvas.drawString(20 * mm, 12 * mm, "TriCV — Mise en service")
    canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, f"page {canvas.getPageNumber()}")
    canvas.setStrokeColor(FILET)
    canvas.setLineWidth(0.4)
    canvas.line(20 * mm, 16 * mm, A4[0] - 20 * mm, 16 * mm)
    canvas.restoreState()


def contenu() -> list:
    h: list = []

    h.append(para("TriCV — mise en service", "titre"))
    h.append(Spacer(1, 6))
    h.append(
        para(
            "Relevé sur le site en ligne : le courriel et le modèle d'IA sont "
            "déclarés, mais leurs identifiants n'ont jamais été renseignés. Rien "
            "n'est cassé — il reste de la configuration à poser. Les quatre "
            "points ci-dessous se font dans cet ordre."
        )
    )

    h.append(
        tableau(
            ["Ce qui ne marche pas", "Pourquoi"],
            [
                [
                    "Aucun courriel ne part",
                    "Le fournisseur est réglé sur Microsoft 365, mais le tenant, "
                    "l'application et le secret sont vides. L'envoi et le relevé "
                    "sont par ailleurs désactivés.",
                ],
                [
                    "La rédaction d'un avis renvoie une erreur",
                    "Le fournisseur d'IA est réglé sur Gemini, mais sa clé "
                    "n'est pas dans le fichier de configuration du serveur.",
                ],
                [
                    "Un poste s'appelle « JOB DESCRIPTION »",
                    "La fiche importée s'annonçait par ce titre anglais. Corrigé "
                    "pour les imports à venir ; le poste existant se renomme à la main.",
                ],
            ],
            [62 * mm, 103 * mm],
        )
    )

    # --- 1 ---------------------------------------------------------------
    h.append(para("1. Déployer la mise à jour", "section"))
    h.append(
        para(
            "La version en ligne est antérieure aux correctifs. Sur le serveur, "
            "dans le dossier de l'application :"
        )
    )
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

    # --- 2 ---------------------------------------------------------------
    h.append(para("2. La clé du modèle d'IA", "section"))
    h.append(
        para(
            "Dans le fichier <font face='Courier'>.env</font> du serveur, ajoutez "
            "la clé Gemini :"
        )
    )
    h.extend(bloc_code(["GEMINI_API_KEY=la-clé-fournie-par-Google", "", "docker compose up -d"]))
    h.append(
        para(
            "Sans elle, la rédaction assistée d'un avis et des rapports reste "
            "indisponible : l'application rend alors le squelette des éléments, "
            "à rédiger à la main."
        )
    )

    # --- 3 ---------------------------------------------------------------
    h.append(PageBreak())
    h.append(para("3. La boîte de courriel", "section"))
    h.append(
        para(
            "C'est le point le plus long, et il dépend d'un administrateur de "
            "l'annuaire Microsoft. Tout se fait depuis l'application : "
            "<b>Paramètres › Courriel</b>, puis le choix "
            "<b>Microsoft 365 (Graph)</b>. Une fenêtre s'ouvre alors et déroule "
            "les étapes ; elle fabrique au passage le lien de consentement, à "
            "ouvrir soi-même ou à transmettre à qui détient les droits."
        )
    )
    h.append(para("Ce qu'il faut en rapporter :", "corps"))
    h.append(
        puces(
            [
                "l'<b>ID du locataire (tenant)</b> et l'<b>ID de l'application "
                "(client)</b>, relevés sur la page « Vue d'ensemble » de "
                "l'inscription ;",
                "la <b>valeur</b> du secret client — pas son identifiant, et elle "
                "ne se réaffiche jamais ;",
                "le <b>consentement administrateur</b> accordé sur les "
                "permissions d'application <font face='Courier'>Mail.ReadWrite</font> "
                "et <font face='Courier'>Mail.Send</font>.",
            ]
        )
    )
    h.extend(
        encadre(
            "Les deux interrupteurs, à ne pas oublier",
            "Même identifiants en place, rien ne partira tant que « Relever la "
            "boîte depuis l'application » et « Envoyer les courriels depuis "
            "l'application » restent décochés. Ils le sont aujourd'hui tous les "
            "deux.",
        )
    )
    h.append(
        para(
            "Enregistrez, puis employez <b>Tester la connexion</b> et "
            "<b>Tester l'envoi</b> : ce sont eux qui disent si le consentement "
            "est bien passé."
        )
    )
    h.extend(
        encadre(
            "Restreindre l'application à la seule boîte de recrutement",
            "Les permissions accordées portent sur toutes les boîtes de "
            "l'organisation. Un administrateur Exchange les y ramène avec "
            "<font face='Courier'>New-ApplicationAccessPolicy</font> ; la commande "
            "figure à l'étape 5 de la fenêtre. Vivement recommandé, et sans effet "
            "sur TriCV.",
        )
    )

    # --- 4 ---------------------------------------------------------------
    h.append(para("4. Le poste mal nommé", "section"))
    h.append(
        para(
            "Un poste porte « JOB DESCRIPTION » pour intitulé. Ouvrez-le, puis "
            "<b>Renommer</b>, à côté du titre. Le bon intitulé figure dans le nom "
            "du fichier de la fiche. Les imports suivants n'auront plus ce défaut."
        )
    )

    # --- vérification ----------------------------------------------------
    h.append(para("Vérifier", "section"))
    h.append(
        tableau(
            ["À faire", "Ce qu'on doit obtenir"],
            [
                [
                    "Paramètres › Courriel, « Tester la connexion »",
                    "Le nombre de messages de la boîte s'affiche.",
                ],
                [
                    "Paramètres › Courriel, « Tester l'envoi »",
                    "« Session ouverte » et l'adresse d'expédition.",
                ],
                [
                    "Sur un poste, « Rédiger avec l'IA »",
                    "Un texte d'avis s'affiche. Sans la clé, le squelette des "
                    "éléments s'affiche à la place — pas une erreur.",
                ],
                [
                    "Déposer une candidature de test",
                    "Elle s'enregistre, et apparaît sur le poste.",
                ],
            ],
            [70 * mm, 95 * mm],
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
        title="TriCV — mise en service du site en ligne",
        author="TriCV",
        subject="Ce qu'il reste à configurer en production",
    )
    document.build(contenu(), onFirstPage=_pied, onLaterPages=_pied)
    print(f"écrit : {SORTIE}")


if __name__ == "__main__":
    main()
