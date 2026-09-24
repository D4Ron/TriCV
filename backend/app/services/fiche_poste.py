"""Lire une fiche de poste fournie par le client, et en proposer les champs.

Le client remet presque toujours sa fiche de poste sous forme de document —
PDF ou Word — ou la colle dans un courriel. Jusqu'ici, tout se ressaisissait à
la main dans le formulaire du poste, rubrique par rubrique. Ce module lit le
document et **propose** de quoi préremplir ce formulaire. Il n'écrit rien : la
proposition revient à l'écran, quelqu'un la relit, et c'est l'enregistrement du
formulaire qui fait foi.

Deux lectures, dans cet ordre :

1. **Le document lui-même.** Les fiches de poste suivent une trame très
   stable — « Intitulé du poste : », « Localisation : », « Mission du poste »,
   « Principales responsabilités », « Profil requis », « Compétences
   techniques »… Ce qui se trouve sous une rubrique reconnue est recopié tel
   quel. C'est une citation : rien n'y est interprété.
2. **L'assistance**, pour ce que la trame n'a pas livré — une fiche rédigée en
   prose, des intitulés inhabituels. Ce qu'elle propose est signalé comme tel
   dans `origines`, pour que l'écran le montre.

Quand les deux lisent la même rubrique, le document l'emporte : une citation
vaut mieux qu'une reformulation, et c'est elle qu'on relira en cas de doute.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field

from app.llm.factory import get_provider
from app.services import extraction

logger = logging.getLogger(__name__)

# En dessous, le document est vide ou n'est qu'une image : il n'y a rien à lire.
TEXTE_MINIMUM = 40

# Les champs que l'on sait proposer. L'ordre est celui du formulaire.
CHAMPS = (
    "intitule",
    "departement",
    "rattachement",
    "localisation",
    "nombre_a_pourvoir",
    "description",
    "missions",
    "responsabilites",
    "competences_techniques",
    "competences_comportementales",
    "niveau_min",
    "domaines_acceptes",
    "annees_experience_min",
    "annees_experience_specifique_min",
    "domaines_experience",
    "langues_requises",
)

_LISTES = frozenset(
    {
        "missions",
        "responsabilites",
        "competences_techniques",
        "competences_comportementales",
        "domaines_acceptes",
        "domaines_experience",
        "langues_requises",
    }
)
_ENTIERS = frozenset(
    {
        "nombre_a_pourvoir",
        "niveau_min",
        "annees_experience_min",
        "annees_experience_specifique_min",
    }
)


class FicheIllisible(Exception):
    """Le document ne donne pas de texte exploitable. Message montré aux RH."""


@dataclass(slots=True)
class Proposition:
    """Ce que la fiche permet de préremplir. `None` ou vide = rien trouvé."""

    valeurs: dict[str, object] = field(default_factory=dict)
    # champ -> "document" ou "assistance".
    origines: dict[str, str] = field(default_factory=dict)
    texte: str = ""
    avertissement: str | None = None


# --- lecture du fichier ------------------------------------------------------


async def lire_document(donnees: bytes, nom_fichier: str) -> tuple[str, str]:
    """Le texte d'un PDF ou d'un Word, et son type. Lève `FicheIllisible`."""
    mime = extraction.sniff_mime(donnees, nom_fichier)
    if mime not in (extraction.PDF_MIME, extraction.DOCX_MIME):
        if mime == extraction.DOC_MIME:
            raise FicheIllisible(
                "Les fichiers Word anciens (.doc) ne se lisent pas. Enregistrez la "
                "fiche au format .docx ou PDF, puis déposez-la de nouveau."
            )
        raise FicheIllisible(
            f"« {nom_fichier[:60]} » n'est ni un PDF ni un document Word."
        )
    try:
        document = await extraction.extract(donnees, mime, nom_fichier, min_chars=0)
    except extraction.UnreadableDocument as exc:
        raise FicheIllisible(f"La fiche n'a pas pu être ouverte : {exc}") from exc
    if len(document.text.strip()) < TEXTE_MINIMUM:
        raise FicheIllisible(
            "Ce document ne contient pas de texte lisible — c'est probablement un "
            "scan. Demandez la fiche au format Word ou en PDF texte, ou collez son "
            "contenu dans la zone prévue."
        )
    return document.text, mime


# --- lecture de la trame ----------------------------------------------------


def _sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c)).lower()


# « 2. Mission du poste », « II) Profil », « 4 - Responsabilités »
_TITRE_NUMEROTE = re.compile(r"^\s*(?:\d{1,2}|[IVX]{1,5})\s*[.)\-–]\s*(\S.{1,90})$")
# « A. Pilotage stratégique de la Supply Chain »
_SOUS_TITRE_LETTRE = re.compile(r"^\s*([A-H])\s*[.)\-–]\s+(\S.{2,120})$")
_PUCE = re.compile(r"^\s*(?:[-–—•·▪■□◦●○*►➢✓✔]|\d{1,2}[.)])\s*")


def _rubrique(titre: str) -> str | None:
    """Le nom interne d'une rubrique, d'après son intitulé. None = à ignorer."""
    t = _sans_accents(titre)
    if "finalit" in t or "objectifs du poste" in t:
        return "missions"
    if "responsabilit" in t or "activites" in t or "taches" in t or "missions" in t:
        return "responsabilites"
    if "mission" in t or "raison d'etre" in t or "raison d’etre" in t:
        return "description"
    if "comportement" in t or "savoir-etre" in t or "savoir etre" in t or "qualites" in t:
        return "competences_comportementales"
    if "competence" in t or "savoir-faire" in t or "connaissances" in t:
        return "competences_techniques"
    if "profil" in t or "qualification" in t or "exigences" in t or "formation et experience" in t:
        return "profil"
    if "identification" in t or "description du poste" in t:
        return "identification"
    return None


def _titre_rubrique(ligne: str) -> str | None:
    """L'intitulé si la ligne ouvre une rubrique connue, sinon None.

    Les fiches numérotent leurs rubriques ; certaines se contentent de les
    écrire en capitales. Les deux formes sont reconnues, mais une ligne en
    capitales n'ouvre une rubrique que si son intitulé est connu — sinon le
    titre du document (« FICHE DE POSTE ») en ouvrirait une.
    """
    numerotee = _TITRE_NUMEROTE.match(ligne)
    if numerotee:
        return numerotee.group(1).strip()
    brute = ligne.strip().rstrip(":").strip()
    if not (3 <= len(brute) <= 60 and any(c.isalpha() for c in brute)):
        return None
    # Hors numérotation, seul un intitulé **connu** ouvre une rubrique. Une
    # fiche numérote ses rubriques, ou les crie en capitales, ou les écrit
    # simplement — « Principales responsabilités », « Profil requis » — et les
    # trois formes doivent être lues.
    #
    # Mais la reconnaissance reste adossée à `_rubrique` : accepter toute ligne
    # courte comme un intitulé a été essayé, et cela ferme les rubriques en
    # cours sur la moindre étiquette interne. Sur la vraie fiche, le profil et
    # les deux blocs de compétences disparaissaient entièrement.
    if _PUCE.match(ligne) or brute[-1] in ".,;":
        return None
    if brute != brute.upper() and len(brute.split()) > 6:
        return None
    return brute if _rubrique(brute) is not None else None


def _decouper(texte: str) -> dict[str, list[str]]:
    """Les lignes de chaque rubrique reconnue, dans l'ordre du document."""
    rubriques: dict[str, list[str]] = {}
    courante: str | None = "identification"
    for brute in texte.splitlines():
        ligne = brute.strip()
        if not ligne:
            continue
        titre = _titre_rubrique(ligne)
        if titre is not None:
            courante = _rubrique(titre)
            if courante is not None:
                rubriques.setdefault(courante, [])
            continue
        if courante is not None:
            rubriques.setdefault(courante, []).append(ligne)
    return rubriques


def _nettoyer_element(ligne: str) -> str:
    return _PUCE.sub("", ligne).strip().rstrip(";").strip()


def _elements(lignes: list[str]) -> list[str]:
    """Une ligne = un élément. Les puces tombent, les doublons aussi."""
    vus: list[str] = []
    for ligne in lignes:
        propre = _nettoyer_element(ligne)
        if propre and propre not in vus:
            vus.append(propre)
    return vus


# Les étiquettes « clé : valeur » de la rubrique d'identification.
_ETIQUETTES = (
    ("intitule", re.compile(r"^intitul[eé]\s+(?:du\s+)?poste\s*:\s*(.+)$", re.I)),
    ("departement", re.compile(r"^(?:direction|d[ée]partement|service|entit[ée])\s*:\s*(.+)$", re.I)),
    (
        "rattachement",
        re.compile(
            r"^(?:rattachement(?:\s+hi[ée]rarchique)?|hi[ée]rarchique|sup[ée]rieur\s+hi[ée]rarchique"
            r"|n\s*\+\s*1|rend\s+compte\s+[àa])\s*:\s*(.+)$",
            re.I,
        ),
    ),
    (
        "localisation",
        re.compile(
            r"^(?:localisation|lieu\s+(?:d['’]affectation|de\s+travail|d['’]exercice)|"
            r"poste\s+bas[ée]\s+[àa]|lieu)\s*:?\s*(.+)$",
            re.I,
        ),
    ),
    (
        "nombre_a_pourvoir",
        re.compile(r"^(?:nombre\s+de\s+postes?(?:\s+[àa]\s+pourvoir)?|effectif\s+recherch[ée])\s*:\s*(\d{1,3})", re.I),
    ),
)


def _identification(lignes: list[str]) -> dict[str, object]:
    trouve: dict[str, object] = {}
    for ligne in lignes:
        for champ, motif in _ETIQUETTES:
            if champ in trouve:
                continue
            correspondance = motif.match(ligne)
            if correspondance:
                valeur = correspondance.group(1).strip().rstrip(".").strip()
                if valeur:
                    trouve[champ] = int(valeur) if champ == "nombre_a_pourvoir" else valeur[:255]
    return trouve


def _intitule_par_defaut(texte: str) -> str | None:
    """Faute d'étiquette, la première ligne utile qui n'est pas le titre du document."""
    for brute in texte.splitlines()[:8]:
        ligne = brute.strip()
        if not ligne or len(ligne) > 120:
            continue
        if _sans_accents(ligne).startswith(("fiche de poste", "fiche poste", "description de poste")):
            continue
        if _titre_rubrique(ligne) is not None or ":" in ligne:
            continue
        return ligne
    return None


def _responsabilites(lignes: list[str]) -> list[str]:
    """Les grands domaines de responsabilité, sinon les responsabilités elles-mêmes.

    Beaucoup de fiches regroupent leurs responsabilités sous des intitulés
    lettrés (« A. Pilotage stratégique »), chacun suivi de tâches et
    d'« Indicateurs clés ». Quarante lignes ne se publient pas dans un avis :
    on retient alors les intitulés, et le détail reste dans le texte de la
    fiche, que la rédaction de l'avis lit en entier.
    """
    lettres = [m.group(2).strip() for m in map(_SOUS_TITRE_LETTRE.match, lignes) if m]
    if len(lettres) >= 2:
        return _elements(lettres)

    retenues: list[str] = []
    dans_indicateurs = False
    for ligne in lignes:
        cle = _sans_accents(ligne)
        if cle.startswith(("indicateurs", "effectif", "kpi")):
            dans_indicateurs = True
            continue
        if _SOUS_TITRE_LETTRE.match(ligne):
            dans_indicateurs = False
            continue
        if not dans_indicateurs:
            retenues.append(ligne)
    return _elements(retenues)


_NIVEAUX_NOMMES = (
    ("doctorat", 8),
    ("phd", 8),
    ("master", 5),
    ("ingenieur", 5),
    ("dess", 5),
    ("dea", 5),
    ("maitrise", 4),
    ("licence", 3),
    ("bachelor", 3),
    ("bts", 2),
    ("dut", 2),
)
_BAC_PLUS = re.compile(r"bac\s*\+\s*(\d)", re.I)
# « Minimum 10 années d'expérience », « 7 ans d'expérience professionnelle »
_ANNEES_GENERALES = re.compile(
    r"(\d{1,2})\s*(?:ans|annees)\s+(?:d['’]\s*)?experience", re.I
)
# « Au moins 5 ans à un poste de management dans les secteurs : … »
_ANNEES_SPECIFIQUES = re.compile(
    r"(?:dont|au\s+moins|au\s+minimum|minimum)\s+(\d{1,2})\s*(?:ans|annees)\s+"
    r"(?:a|au|aux|dans|en|sur)\s+(.+)",
    re.I,
)


def _liste_apres_deux_points(lignes: list[str], depart: int) -> list[str]:
    """Les éléments qui suivent une ligne terminée par « : », jusqu'à la prochaine étiquette."""
    elements: list[str] = []
    for ligne in lignes[depart + 1 :]:
        cle = _sans_accents(ligne)
        if ligne.rstrip().endswith(":") or cle in ("formation", "experience", "langues", "diplome"):
            break
        if _ANNEES_GENERALES.search(cle) or _BAC_PLUS.search(cle):
            break
        elements.append(ligne)
    return _elements(elements)


def _profil(lignes: list[str]) -> dict[str, object]:
    """Niveau, domaines et expérience, lus dans la rubrique « Profil requis »."""
    trouve: dict[str, object] = {}
    for index, ligne in enumerate(lignes):
        cle = _sans_accents(ligne)

        if "niveau_min" not in trouve:
            bac = _BAC_PLUS.search(cle)
            if bac:
                trouve["niveau_min"] = int(bac.group(1))
                # « Bac+5 en : » annonce la liste des domaines acceptés ;
                # « Bac+5 en finance ou gestion » la donne sur la même ligne.
                reste = cle[bac.end() :].strip()
                if ligne.rstrip().endswith(":"):
                    domaines = _liste_apres_deux_points(lignes, index)
                    if domaines:
                        trouve["domaines_acceptes"] = domaines
                elif reste.startswith(("en ", "dans ")):
                    brut = ligne[ligne.lower().find(" en ") + 4 :] if " en " in ligne.lower() else ""
                    domaines = [
                        d.strip(" .")
                        for d in re.split(r",|;|\bou\b|\bet\b", brut)
                        if d.strip(" .")
                    ]
                    if domaines:
                        trouve["domaines_acceptes"] = domaines
            else:
                for mot, niveau in _NIVEAUX_NOMMES:
                    if re.search(rf"\b{mot}\b", cle):
                        trouve["niveau_min"] = niveau
                        break

        # « Au moins 10 ans d'expérience » ne passe pas ici : après « ans »,
        # le motif spécifique veut une préposition (« à », « dans », « en »),
        # pas « d'expérience ». Il ne retient donc que les tournures qui
        # portent sur un domaine ou une fonction.
        specifique = _ANNEES_SPECIFIQUES.search(cle)
        if specifique and "annees_experience_specifique_min" not in trouve:
            trouve["annees_experience_specifique_min"] = int(specifique.group(1))
            if ligne.rstrip().endswith(":"):
                domaines = _liste_apres_deux_points(lignes, index)
            else:
                queue = ligne.split(":", 1)[1] if ":" in ligne else ""
                domaines = [d.strip(" .") for d in re.split(r",|;", queue) if d.strip(" .")]
            if domaines:
                trouve["domaines_experience"] = domaines
            continue

        if "annees_experience_min" not in trouve:
            general = _ANNEES_GENERALES.search(cle)
            if general:
                trouve["annees_experience_min"] = int(general.group(1))

    langues = [
        l
        for l in ("français", "anglais", "portugais", "espagnol", "arabe", "allemand")
        if _sans_accents(l) in _sans_accents(" ".join(lignes))
    ]
    if langues:
        trouve["langues_requises"] = langues
    return trouve


def lire_trame(texte: str) -> dict[str, object]:
    """Ce que la trame du document livre sans interprétation."""
    rubriques = _decouper(texte)
    trouve: dict[str, object] = {}

    trouve.update(_identification(rubriques.get("identification", []) + texte.splitlines()[:40]))
    if "intitule" not in trouve:
        intitule = _intitule_par_defaut(texte)
        if intitule:
            trouve["intitule"] = intitule[:512]

    if rubriques.get("description"):
        trouve["description"] = "\n".join(rubriques["description"]).strip()
    if rubriques.get("missions"):
        trouve["missions"] = _elements(rubriques["missions"])
    if rubriques.get("responsabilites"):
        trouve["responsabilites"] = _responsabilites(rubriques["responsabilites"])
    if rubriques.get("competences_techniques"):
        trouve["competences_techniques"] = _elements(rubriques["competences_techniques"])
    if rubriques.get("competences_comportementales"):
        trouve["competences_comportementales"] = _elements(
            rubriques["competences_comportementales"]
        )
    if rubriques.get("profil"):
        trouve.update(_profil(rubriques["profil"]))

    # Rien de vide : une clé présente veut dire « trouvé ». Un entier, même
    # nul, est une valeur lue — « 0 an d'expérience » n'est pas une absence.
    return {
        k: v for k, v in trouve.items() if k in _ENTIERS or v not in (None, "", [])
    }


# --- assistance -------------------------------------------------------------


_CONSIGNE = (
    "Lisez la fiche de poste ci-dessous et renvoyez un objet JSON avec exactement "
    "ces clés : intitule, departement, rattachement, localisation, "
    "nombre_a_pourvoir, description, missions, responsabilites, "
    "competences_techniques, competences_comportementales, niveau_min, "
    "domaines_acceptes, annees_experience_min, annees_experience_specifique_min, "
    "domaines_experience, langues_requises.\n"
    "Règles :\n"
    "- Recopiez ce que dit la fiche ; n'inventez rien. Une information absente "
    "vaut null (ou [] pour une liste).\n"
    "- niveau_min est l'entier N de « BAC+N » (Licence = 3, Master ou Ingénieur = 5, "
    "Doctorat = 8).\n"
    "- Les années sont des entiers. annees_experience_specifique_min et "
    "domaines_experience portent sur une expérience dans un domaine ou une fonction "
    "précise, distincte de l'expérience générale.\n"
    "- description : la mission du poste en un ou deux paragraphes, tels qu'écrits.\n"
    "- missions : les finalités ou objectifs du poste.\n"
    "- responsabilites : les grands domaines de responsabilité, au plus dix, "
    "formulés comme dans la fiche.\n"
    "- Les listes sont des tableaux de chaînes courtes."
)


def _normaliser(champ: str, valeur: object) -> object:
    """Remet une valeur proposée par le modèle dans le type du formulaire."""
    if valeur is None:
        return None
    if champ in _LISTES:
        if isinstance(valeur, str):
            valeur = [v for v in re.split(r"[,;\n]", valeur)]
        if not isinstance(valeur, list):
            return None
        return _elements([str(v) for v in valeur if v is not None])[:30]
    if champ in _ENTIERS:
        try:
            nombre = int(float(str(valeur).lower().replace("bac+", "").strip()))
        except (TypeError, ValueError):
            return None
        if champ == "niveau_min":
            return nombre if 0 <= nombre <= 8 else None
        if champ == "nombre_a_pourvoir":
            return nombre if nombre >= 1 else None
        return nombre if 0 <= nombre <= 60 else None
    texte = " ".join(str(valeur).split()) if champ != "description" else str(valeur).strip()
    return texte or None


async def _assistance(texte: str) -> dict[str, object]:
    try:
        charge = await get_provider().repondre_json(_CONSIGNE, texte[:20000])
    except Exception:
        logger.exception("lecture assistée de la fiche de poste indisponible")
        return {}
    if not isinstance(charge, dict):
        return {}
    propose: dict[str, object] = {}
    for champ in CHAMPS:
        valeur = _normaliser(champ, charge.get(champ))
        if valeur not in (None, "", []):
            propose[champ] = valeur
    return propose


async def proposer(texte: str, *, avec_assistance: bool = True) -> Proposition:
    """La proposition de préremplissage pour ce texte de fiche."""
    texte = extraction.normalise(texte or "")
    if len(texte) < TEXTE_MINIMUM:
        raise FicheIllisible(
            "Le texte est trop court pour être une fiche de poste. Collez la fiche "
            "entière, ou déposez le document."
        )

    proposition = Proposition(texte=texte)
    for champ, valeur in lire_trame(texte).items():
        proposition.valeurs[champ] = valeur
        proposition.origines[champ] = "document"

    if avec_assistance:
        manquants = [c for c in CHAMPS if c not in proposition.valeurs]
        if manquants:
            for champ, valeur in (await _assistance(texte)).items():
                if champ not in proposition.valeurs:
                    proposition.valeurs[champ] = valeur
                    proposition.origines[champ] = "assistance"

    # Une expérience spécifique ne peut pas dépasser l'expérience générale : le
    # formulaire le refuserait. Mieux vaut le signaler ici que laisser la
    # relecture buter sur un refus sans explication.
    generale = proposition.valeurs.get("annees_experience_min")
    specifique = proposition.valeurs.get("annees_experience_specifique_min")
    if isinstance(generale, int) and isinstance(specifique, int) and specifique > generale:
        proposition.avertissement = (
            f"La fiche demande {specifique} an(s) d'expérience spécifique pour "
            f"{generale} an(s) d'expérience générale. Corrigez l'une des deux valeurs "
            "avant d'enregistrer."
        )
    elif not proposition.valeurs:
        proposition.avertissement = (
            "Aucune rubrique n'a été reconnue dans ce texte. Remplissez le formulaire "
            "à la main ; le texte reste joint au poste et servira à rédiger l'avis."
        )
    return proposition
