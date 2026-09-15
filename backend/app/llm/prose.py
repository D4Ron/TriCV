"""Ramener à de la prose ce qu'un modèle rend quand on lui en demande.

Deux appels très différents partent vers le même fournisseur : l'un veut du
JSON — le parcours lu dans un dossier —, l'autre veut un paragraphe de français
administratif pour une section de rapport. Les fournisseurs, eux, ont un mode
« JSON » global qui s'active par requête, et il était armé pour les deux.

Un modèle contraint au JSON à qui l'on demande un paragraphe, sans schéma à
remplir, rend ce qu'il peut : `{}`, `{"texte": "..."}` avec des `\\n` échappés,
ou la phrase entre guillemets. C'est ce qui atterrissait dans les rapports.

La cause est corrigée en amont — le mode JSON ne s'arme plus que sur les appels
qui en veulent. Ce module est la seconde ligne : il rattrape ce qu'un modèle
enveloppe malgré tout, parce qu'aucune consigne ne les en empêche
complètement, et parce qu'un rapport remis à un client ne peut pas porter une
accolade orpheline.

Rien ici n'invente : on ne fait que déballer et nettoyer. Un contenu qui
n'était que du remplissage — `{}`, `null` — ressort vide, et l'écran présente
alors une section à écrire à la main, ce qui est la vérité.
"""

from __future__ import annotations

import json
import re
import unicodedata

# Les balises de bloc, en tête comme en queue.
_CLOTURE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")

# Le raisonnement à voix haute des modèles qui en font. Qwen, DeepSeek et les
# modèles locaux récents rendent leur réflexion avant leur réponse, entre
# balises. En mode JSON le format l'interdit, mais la prose n'a pas ce
# garde-fou : sans ce retrait, une section de rapport s'ouvrirait sur
# « L'utilisateur demande une section sur la publication... ».
_REFLEXION = re.compile(
    r"<(think|thinking|reasoning)>.*?</\1>\s*", re.DOTALL | re.IGNORECASE
)
# Une réflexion tronquée par la limite de jetons n'a pas de balise fermante :
# tout ce qui précède l'ouverture est alors la seule chose à garder.
_REFLEXION_OUVERTE = re.compile(
    r"<(?:think|thinking|reasoning)>.*\Z", re.DOTALL | re.IGNORECASE
)

# Ce qu'un modèle ajoute pour se présenter avant de répondre. Toujours sur la
# première ligne, toujours suivi d'un deux-points.
_PREAMBULE = re.compile(
    r"^\s*(?:voici|voilà|bien sûr|certainement|comme demandé|réponse|section)\b[^\n:]{0,60}:\s*",
    re.IGNORECASE,
)

# Le balisage Markdown que les modèles produisent par habitude. Le rapport part
# en DOCX, PDF et ODT, où `**` et `##` s'impriment tels quels.
_TITRE_MD = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_GRAS = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
_ITALIQUE = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_CODE = re.compile(r"`([^`\n]+)`")
_CITATION = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_PUCE = re.compile(r"^(\s*)[*+•]\s+", re.MULTILINE)
_FILET = re.compile(r"^\s*(?:[-*_]\s*){3,}\s*$", re.MULTILINE)

_LIGNES_VIDES = re.compile(r"\n{3,}")
_ESPACES_FIN = re.compile(r"[ \t]+$", re.MULTILINE)

# Une ligne de tableau Markdown : « | Nom | Note | » ou son filet « |---|---| ».
#
# Les tableaux du rapport sont produits par le code, à partir des notes
# réellement inscrites, et insérés sous la prose. Le modèle n'a donc aucun
# tableau à écrire — et la consigne le lui dit. Il en écrit quand même
# lorsqu'une section en annonce un : sommé de commenter un classement qui
# n'existe pas encore, un modèle a rendu dix lignes de candidats « [Nom 1] » à
# « [Nom 10] » avec des notes d'entretien inventées de bout en bout, sous un
# tableau vide produit par le code juste au-dessus.
#
# Le remède tient en deux temps : la consigne l'interdit, et ceci l'efface. Un
# tableau inventé n'a pas de version acceptable à récupérer.
_LIGNE_TABLEAU = re.compile(r"^[ \t]*\|.*\|[ \t]*$", re.MULTILINE)

# Une réponse qui ne portait aucun texte. Le modèle a rendu la coquille vide
# que le mode JSON l'obligeait à produire.
_VIDE = {"", "{}", "[]", "null", "none", '""', "{ }", "[ ]"}


def _sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte)
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def _ressemble_a_du_json(texte: str) -> bool:
    """Une prose française ne commence pas par une accolade.

    Le test est volontairement strict : n'ouvrir le déballage que sur un texte
    délimité de bout en bout évite de charcuter un paragraphe qui citerait une
    accolade au passage.
    """
    return (texte.startswith("{") and texte.endswith("}")) or (
        texte.startswith("[") and texte.endswith("]")
    )


def _textes_de(valeur: object) -> list[str]:
    """Toutes les chaînes d'une structure JSON, dans l'ordre de lecture.

    On ne devine pas quelle clé porte la prose : `texte`, `contenu`, `section`,
    `response` — chaque modèle a la sienne, et certains en imbriquent deux. Tout
    prendre et recoller est plus sûr que parier sur un nom.
    """
    if isinstance(valeur, str):
        return [valeur]
    if isinstance(valeur, dict):
        return [t for v in valeur.values() for t in _textes_de(v)]
    if isinstance(valeur, list):
        return [t for v in valeur for t in _textes_de(v)]
    # Un nombre ou un booléen isolé n'est pas de la prose : c'est du remplissage.
    return []


def _deballer(texte: str) -> str:
    if not _ressemble_a_du_json(texte):
        return texte
    try:
        charge = json.loads(texte)
    except json.JSONDecodeError:
        return texte
    morceaux = [t.strip() for t in _textes_de(charge) if t and t.strip()]
    return "\n\n".join(morceaux)


def _sans_balisage(texte: str) -> str:
    texte = _LIGNE_TABLEAU.sub("", texte)
    texte = _FILET.sub("", texte)
    texte = _TITRE_MD.sub("", texte)
    texte = _GRAS.sub(lambda m: m.group(1) or m.group(2) or "", texte)
    texte = _ITALIQUE.sub(r"\1", texte)
    texte = _CODE.sub(r"\1", texte)
    texte = _CITATION.sub("", texte)
    # Les puces se normalisent sur le tiret : c'est celle que le cabinet emploie
    # dans ses documents, et la seule qui survive au passage en DOCX.
    return _PUCE.sub(r"\1- ", texte)


def _sans_titre_repete(texte: str, titre: str) -> str:
    """Retire le titre de section que le modèle a recopié en tête.

    La consigne le lui interdit ; il le fait quand même une fois sur trois. Le
    document imprime alors son propre titre suivi du même titre en corps de
    texte.
    """
    if not titre:
        return texte
    lignes = texte.split("\n", 1)
    premiere = lignes[0].strip().strip("#*:—-").strip()
    attendu = _sans_accents(titre).casefold().strip()
    if premiere and _sans_accents(premiere).casefold().strip() == attendu:
        return lignes[1].lstrip("\n") if len(lignes) > 1 else ""
    return texte


def nettoyer(brut: str, titre: str = "") -> str:
    """Le texte de la section, débarrassé de son emballage.

    `titre` sert à reconnaître un titre recopié en tête ; il est facultatif.
    Une réponse qui ne contenait rien de rédigé ressort vide — l'appelant
    présente alors la section à écrire, plutôt qu'une accolade.
    """
    if not brut:
        return ""

    # La réflexion se retire avant tout le reste : ce qui suit ne s'applique
    # qu'à la réponse, et une réflexion contient volontiers des accolades qui
    # feraient prendre une prose pour du JSON.
    texte = _REFLEXION.sub("", brut.strip())
    texte = _REFLEXION_OUVERTE.sub("", texte)
    texte = _CLOTURE.sub("", texte.strip()).strip()
    if texte.casefold() in _VIDE:
        return ""

    texte = _deballer(texte).strip()

    # Un JSON illisible laisse ses échappements dans la chaîne. On ne les
    # traduit que s'il n'y a aucun vrai retour à la ligne : sinon le texte est
    # déjà correct et « \n » y serait littéral.
    if "\\n" in texte and "\n" not in texte:
        texte = texte.replace("\\n", "\n").replace('\\"', '"')

    texte = texte.strip().strip('"').strip()
    texte = _PREAMBULE.sub("", texte)
    texte = _sans_balisage(texte)
    texte = _sans_titre_repete(texte.strip(), titre)

    texte = _ESPACES_FIN.sub("", texte)
    texte = _LIGNES_VIDES.sub("\n\n", texte)
    texte = texte.strip()

    return "" if texte.casefold() in _VIDE else texte
