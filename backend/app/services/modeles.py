"""Les trames imposées par les clients : ingestion et correspondance.

Certains commanditaires fournissent leur propre modèle — de rapport, d'avis, de
CV. Le cabinet doit produire dans ce format, sans qu'on recode un gabarit par
client.

La démarche tient en trois temps :

1. **On stocke le fichier tel qu'il est reçu.** Il fait référence ; c'est lui
   qu'on rouvre en cas de désaccord sur le format.
2. **On en extrait le texte**, et on repère les titres qui structurent la
   trame. Un rapport imposé se reconnaît à ses intertitres, pas à sa mise en
   page.
3. **On propose une correspondance** entre ces titres et les sections que
   l'application sait produire — puis quelqu'un la corrige une fois. Elle est
   enregistrée, et les productions suivantes s'y conforment sans nouvelle
   intervention.

Le troisième temps est le seul où l'assistance automatique intervient, et son
résultat n'est qu'une proposition : la correspondance est relue avant d'être
enregistrée. Une trame mal reconnue produirait des rapports mal découpés pour
tout un client, ce qui coûte plus cher à réparer qu'à vérifier une fois.
"""

from __future__ import annotations

import logging
import re

from app.llm.factory import get_provider
from app.services import extraction, rapports

logger = logging.getLogger(__name__)

# Un titre de section, dans un document bureautique converti en texte : ligne
# courte, sans ponctuation finale, souvent numérotée ou en capitales. Le repère
# est grossier — il sert à proposer, pas à trancher.
_NUMEROTATION = re.compile(r"^\s*(?:[IVXLC]+[.)]|\d+(?:\.\d+)*[.)]?)\s+")


def titres_probables(texte: str, limite: int = 40) -> list[str]:
    """Les lignes qui ressemblent à des intertitres.

    Volontairement permissif : mieux vaut proposer un titre de trop, que
    quelqu'un écartera d'un clic, que d'en manquer un et de livrer un rapport
    amputé d'une section que le client attendait.
    """
    titres: list[str] = []
    for ligne_brute in texte.splitlines():
        ligne = ligne_brute.strip()
        if not (3 <= len(ligne) <= 90):
            continue
        if ligne.endswith((".", ";", ",", ":")) and not _NUMEROTATION.match(ligne):
            continue
        numerotee = bool(_NUMEROTATION.match(ligne))
        sans_numero = _NUMEROTATION.sub("", ligne).strip()
        if not sans_numero:
            continue
        capitales = sans_numero == sans_numero.upper() and any(
            c.isalpha() for c in sans_numero
        )
        # Un titre fait rarement plus d'une douzaine de mots.
        court = len(sans_numero.split()) <= 12
        if (numerotee or capitales) and court:
            if sans_numero not in titres:
                titres.append(sans_numero)
        if len(titres) >= limite:
            break
    return titres


async def lire_gabarit(donnees: bytes, mime: str, nom: str) -> str:
    """Le texte du fichier fourni, ou une chaîne vide s'il est illisible."""
    try:
        document = await extraction.extract(donnees, mime, nom)
    except Exception:
        logger.exception("gabarit illisible : %s", nom)
        return ""
    return document.text or ""


_CONSIGNE_CORRESPONDANCE = (
    "Voici les intertitres relevés dans un modèle de rapport de recrutement "
    "imposé par un client, puis la liste des sections que notre application "
    "sait produire.\n"
    "\n"
    "Pour chaque intertitre du modèle, indiquez à quelle section de "
    "l'application il correspond, ou `null` si aucune ne convient.\n"
    "\n"
    "Répondez uniquement par un objet JSON de la forme :\n"
    '{\"sections\": [{\"titre\": \"<intertitre du modèle>\", '
    '\"code\": \"<CODE_SECTION ou null>\"}]}\n'
    "\n"
    "N'inventez aucun code : n'utilisez que ceux de la liste fournie."
)


async def proposer_correspondance(titres: list[str]) -> dict:
    """Rapproche les intertitres du client des sections que l'on sait produire.

    Renvoie `{"sections": [{"code", "titre", "consigne", "calculee"}]}`, prêt à
    être stocké dans `ModeleDocument.structure` après relecture. Une section
    sans correspondance garde le titre du client et reçoit une consigne
    générique : elle sera rédigée, simplement sans modèle de référence.
    """
    connues = {s.code: s for s in rapports.TRAME}
    catalogue = "\n".join(f"- {code} : {s.titre}" for code, s in connues.items())
    contexte = (
        "Intertitres du modèle client :\n"
        + "\n".join(f"- {t}" for t in titres)
        + "\n\nSections disponibles dans l'application :\n"
        + catalogue
    )

    appariements: dict[str, str | None] = {}
    try:
        # `repondre_json` et non `rediger` : c'est un objet JSON qu'on attend
        # ici, pas un paragraphe, et les deux ne demandent pas le même mode au
        # fournisseur.
        charge = await get_provider().repondre_json(_CONSIGNE_CORRESPONDANCE, contexte)
        for element in charge.get("sections") or ():
            if isinstance(element, dict) and element.get("titre"):
                code = element.get("code")
                appariements[str(element["titre"])] = (
                    str(code) if code and str(code) in connues else None
                )
    except Exception:
        # Sans assistance, la correspondance est à faire à la main dans
        # l'interface. La trame est tout de même rendue, titres du client
        # compris : le travail restant est de la relecture, pas de la saisie.
        logger.exception("correspondance de trame indisponible")

    sections = []
    for index, titre in enumerate(titres):
        code = appariements.get(titre)
        reference = connues.get(code) if code else None
        sections.append(
            {
                "code": code or f"SECTION_{index + 1}",
                "titre": titre,
                "consigne": (
                    reference.consigne
                    if reference is not None and reference.consigne
                    else f"Rédigez la section « {titre} » du rapport de recrutement."
                ),
                "calculee": bool(reference is not None and reference.calculee),
                # Ce que le modèle a proposé, pour que le relecteur voie ce
                # qu'il valide plutôt qu'un résultat déjà fondu dans la trame.
                "correspondance_proposee": code,
            }
        )
    return {"sections": sections, "titres_releves": titres}


async def analyser(donnees: bytes, mime: str, nom: str) -> tuple[str, dict]:
    """Ingestion complète d'un gabarit : texte, titres, correspondance."""
    texte = await lire_gabarit(donnees, mime, nom)
    if not texte.strip():
        return "", {"sections": [], "titres_releves": []}
    titres = titres_probables(texte)
    if not titres:
        return texte, {"sections": [], "titres_releves": []}
    return texte, await proposer_correspondance(titres)
