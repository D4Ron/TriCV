"""Envoie un CV fictif « Test » à la boîte de recrutement, pour éprouver la chaîne.

Le trajet éprouvé est celui d'un vrai candidat : un courriel avec un CV en
pièce jointe arrive dans la boîte, et « Relever la boîte » doit en faire une
candidature. L'envoi passe par la boîte d'envoi réglée dans l'application
(Paramètres › Courriel), par Microsoft Graph, avec les mêmes identifiants
que les convocations. Un envoi qui aboutit ici valide donc aussi l'accès
dont se sert l'application.

    cd backend
    python -m tools.envoyer_cv_test                    # vers recrutement@kapiconsult.tg
    python -m tools.envoyer_cv_test --reference DRH-01 # rattaché à un avis
    python -m tools.envoyer_cv_test --eml cv-test.eml  # écrit le message sans l'envoyer
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import sys
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DESTINATAIRE = "recrutement@kapiconsult.tg"
NOM_FICHIER = "TEST_Test_cv.pdf"


def cv_test() -> bytes:
    """Un CV d'une page au nom de « Test TEST ». Personne de réel."""
    tampon = io.BytesIO()
    page = canvas.Canvas(tampon, pagesize=A4)
    page.setTitle("CV - Test TEST")
    x, y = 20 * mm, A4[1] - 25 * mm
    page.setFont("Helvetica-Bold", 18)
    page.drawString(x, y, "Test TEST")
    y -= 8 * mm
    page.setFont("Helvetica", 10)
    page.drawString(x, y, "test.candidat@example.com  -  +228 90 00 00 00  -  Lomé, Togo")
    blocs = [
        ("FORMATION", ["2018 - Master en Gestion des Ressources Humaines (BAC+5), Université de Lomé"]),
        (
            "EXPÉRIENCE PROFESSIONNELLE",
            [
                "2019 - 2025 : Chargé des ressources humaines, Société Exemple SA, Lomé",
                "Gestion de la paie, recrutement, suivi de la formation du personnel.",
            ],
        ),
        ("LANGUES", ["Français (courant), Anglais (intermédiaire)"]),
        ("MENTION", ["Document de test généré par TriCV - candidat fictif."]),
    ]
    for titre, lignes in blocs:
        y -= 12 * mm
        page.setFont("Helvetica-Bold", 11)
        page.drawString(x, y, titre)
        page.setFont("Helvetica", 10)
        for ligne in lignes:
            y -= 6 * mm
            page.drawString(x, y, ligne)
    page.showPage()
    page.save()
    return tampon.getvalue()


def _sujet(reference: str) -> str:
    sujet = "Candidature - Test TEST (envoi de test)"
    return f"[{reference}] {sujet}" if reference else sujet


def _corps() -> str:
    return (
        "Bonjour,\n\n"
        "Veuillez trouver ci-joint mon CV.\n\n"
        "Ce message est un envoi de test de TriCV : le candidat « Test TEST » est "
        "fictif et la candidature peut être supprimée après vérification.\n\n"
        "Test TEST\n"
    )


def construire(expediteur: str, destinataire: str, reference: str, pdf: bytes) -> EmailMessage:
    courriel = EmailMessage()
    courriel["From"] = formataddr(("Test TEST", expediteur))
    courriel["To"] = destinataire
    courriel["Subject"] = _sujet(reference)
    courriel["Date"] = formatdate(localtime=True)
    courriel["Message-ID"] = make_msgid(domain=expediteur.rpartition("@")[2] or None)
    courriel.set_content(_corps())
    courriel.add_attachment(pdf, maintype="application", subtype="pdf", filename=NOM_FICHIER)
    return courriel


def _envoyer_graph(reglages, destinataire: str, reference: str, pdf: bytes) -> None:
    from app.services import graph_microsoft

    client = graph_microsoft.ClientGraph(
        graph_microsoft.config_graph(
            reglages.oauth_tenant, reglages.oauth_client_id, reglages.oauth_client_secret
        ),
        reglages.expediteur,
    )
    message = {
        "subject": _sujet(reference),
        "body": {"contentType": "Text", "content": _corps()},
        "toRecipients": [{"emailAddress": {"address": destinataire}}],
        "attachments": [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": NOM_FICHIER,
                "contentType": "application/pdf",
                "contentBytes": base64.b64encode(pdf).decode(),
            }
        ],
    }
    try:
        client.appeler("POST", "/sendMail", json={"message": message, "saveToSentItems": True})
    finally:
        client.fermer()


async def _reglages():
    from app.db import SessionLocal
    from app.services import parametres

    async with SessionLocal() as db:
        return await parametres.lire(db)


def main() -> int:
    arguments = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    arguments.add_argument("--a", dest="destinataire", default=DESTINATAIRE)
    arguments.add_argument("--reference", default="", help="référence d'avis à mettre dans l'objet")
    arguments.add_argument("--eml", type=Path, help="écrire le message dans ce fichier, sans l'envoyer")
    arguments.add_argument("--de", default="", help="expéditeur, à défaut celui de l'application")
    options = arguments.parse_args()

    pdf = cv_test()
    if options.eml:
        reglages = None
        expediteur = options.de or "test.candidat@example.com"
    else:
        reglages = asyncio.run(_reglages())
        if not reglages.envoi_utilisable:
            print(
                "L'envoi de courriels n'est pas configuré dans l'application "
                "(Paramètres › Courriel).",
                file=sys.stderr,
            )
            return 2
        expediteur = options.de or reglages.expediteur

    courriel = construire(expediteur, options.destinataire, options.reference, pdf)
    if options.eml:
        options.eml.write_bytes(bytes(courriel))
        print(f"Message écrit dans {options.eml} ({len(pdf)} octets de PDF joints).")
        return 0

    _envoyer_graph(reglages, options.destinataire, options.reference, pdf)
    print(f"CV « Test » envoyé à {options.destinataire} depuis {expediteur} (Microsoft 365).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
