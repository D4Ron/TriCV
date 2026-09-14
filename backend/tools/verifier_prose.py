"""Vérifie en direct qu'une section de rapport est utilisable telle quelle.

Deux contrôles, et le second compte autant que le premier.

**La forme.** La section doit revenir en prose française, pas en JSON, pas en
Markdown, pas vide. C'est le contrôle qui aurait attrapé les accolades vides
imprimées dans les rapports.

**Le fond.** La section ne doit rien nommer que les données ne nomment pas.
Un modèle de petite taille comble volontiers les blancs d'un rapport de
recrutement avec ce qui « va de soi » : des canaux de diffusion, des motifs
d'élimination, des noms de plateformes. Un essai a ainsi rendu « diffusion via
JobTogo, LinkedIn, Indeed » à partir de données qui ne mentionnaient aucun
support. C'est une phrase que le cabinet aurait signée, et qu'un candidat
écarté pouvait contester.

Le contrôle est grossier — il relève les noms propres absents des données — et
c'est assez : l'invention se trahit presque toujours par un nom.

    python tools/verifier_prose.py

Une requête au fournisseur configuré. À lancer après chaque changement de
fournisseur ou de modèle.
"""

from __future__ import annotations

import asyncio
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.llm.factory import get_provider  # noqa: E402
from app.services import rapports  # noqa: E402

CONTEXTE = (
    "Commanditaire : Groupe Hôtelier Sarakawa\n"
    "Mandat : Recrutement d'un Chef comptable\n"
    "\n"
    "Poste : Chef comptable\n"
    "  Postes à pourvoir : 1\n"
    "  Niveau minimum exigé : BAC+3\n"
    "  Avis publié le : 2026-09-15\n"
    "  Clôture des candidatures : 2026-10-31\n"
    "  Candidatures reçues : 5\n"
    "  Dossiers écartés à l'éligibilité : 3\n"
    "  Dossiers présélectionnés : 1\n"
)

# Ce qu'une phrase française met en majuscule sans rien inventer : le premier
# mot, les mois, et le vocabulaire du métier que la consigne emploie déjà.
_MAJUSCULES_LEGITIMES = {
    "le", "la", "les", "un", "une", "des", "ce", "cette", "ces", "il", "elle",
    "au", "aux", "en", "sur", "dans", "par", "pour", "cinq", "trois", "deux",
    "quatre", "six", "sept", "huit", "neuf", "dix", "janvier", "fevrier",
    "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre",
    "novembre", "decembre", "avis", "poste", "cabinet", "candidatures",
    "dossiers", "parmi", "toutefois", "enfin", "ainsi", "cependant", "a",
    "l", "d", "n", "s", "bac", "total", "aucun", "aucune", "chef",
}

_MOT = re.compile(r"\b[A-ZÀ-Þ][\wÀ-ÿ'’-]{1,}")


def _plat(texte: str) -> str:
    sans = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in sans if unicodedata.category(c) != "Mn")


def noms_inventes(texte: str, contexte: str) -> list[str]:
    """Les noms propres du texte qui ne figurent nulle part dans les données."""
    connus = set(_plat(contexte).replace("'", " ").replace("-", " ").split())
    suspects = []
    for brut in _MOT.findall(texte):
        plat = _plat(brut).strip("’'-")
        if plat in _MAJUSCULES_LEGITIMES or plat in connus:
            continue
        # Un mot en tête de phrase est majuscule par grammaire, pas par nature.
        if any(_plat(brut) == _plat(m) for m in re.findall(r"(?:^|[.!?]\s+)(\S+)", texte)):
            continue
        suspects.append(brut)
    return sorted(set(suspects))


async def main() -> int:
    print(f"Fournisseur : {settings.llm_provider} — modèle : {settings.llm_model or 'défaut'}\n")
    section = rapports.PAR_CODE["PUBLICATION"]

    texte = await get_provider().rediger(section.consigne, CONTEXTE, titre=section.titre)

    print("--- section rendue " + "-" * 51)
    print(texte or "(vide)")
    print("-" * 70)

    fautes = []
    if not texte.strip():
        fautes.append("la section est vide")
    if texte.lstrip().startswith(("{", "[")):
        fautes.append("la réponse est du JSON, pas de la prose")
    for marque in ("**", "```", "\\n"):
        if marque in texte:
            fautes.append(f"balisage résiduel : {marque!r}")

    inventes = noms_inventes(texte, CONTEXTE)
    if inventes:
        fautes.append(
            "noms absents des données — invention probable : " + ", ".join(inventes)
        )

    if fautes:
        print("\nÉCHEC")
        for faute in fautes:
            print(f"  - {faute}")
        print(
            "\nUn rapport engage le cabinet. Un modèle qui comble les blancs ne "
            "convient pas\npour la rédaction, même s'il convient pour le "
            "dépouillement : mesurez-le avec\n`python -m tools.evaluer_extraction`, "
            "et gardez l'autre fournisseur pour la prose."
        )
        return 1

    print(f"\nOK — {len(texte.split())} mots de prose française, sans nom inventé.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
