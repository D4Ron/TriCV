"""Les familles de métiers : ce qu'un mot veut dire, au-delà de son orthographe.

`domaine_correspond` compare des mots, et il le fait bien. Mais il ne peut pas
savoir que « supply chain management » est de la logistique, que « ressources
humaines » est la « gestion des ressources humaines » qu'un avis réclame, ni
qu'un poste chez un pétrolier relève du secteur « Pétrole & Gaz » sans jamais
écrire ces mots. Sur un lot réel, 8 expériences sur 75 comptaient pour le
secteur demandé, et un dossier sur trois seulement en avait une.

Une famille sépare deux liens, parce qu'ils n'ont pas la même force :

- **Même famille : c'est la même chose, dite autrement.** Le rapprochement est
  automatique. `noms` dit comment un poste désigne le champ, `termes` ce qui en
  relève. Un poste qui demande « finance d'entreprise » reste strict : ce n'est
  pas un nom de famille, seul le mot à mot joue.
- **Famille proche : c'est voisin, pas identique.** Rien n'est compté d'office :
  un audit n'est pas une comptabilité. Mais un voisinage ne doit pas éliminer
  sans qu'un humain l'ait vu ; il devient un indice à confirmer.

La table reste écrite à la main, et courte : elle est relue, s'explique à un
candidat qui conteste, et ne coûte aucun appel. Ce qui manque à un poste précis
se complète par son propre lexique (`Poste.lexique`), validé par les RH.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

_MOTS_VIDES = frozenset(
    "de du des la le les et en aux au a l d sur pour dans par avec and of the in".split()
)
# En deçà, un mot ne se rapproche que tel quel : « rh », « gaz », « port ».
_MOT_COURT = 6


@dataclass(frozen=True, slots=True)
class Famille:
    cle: str
    # Ce que dit la synthèse : « profil logistique et commerce ».
    libelle: str
    noms: tuple[str, ...]
    termes: tuple[str, ...]
    proches: tuple[str, ...] = ()
    # Le secteur se lit souvent à l'employeur seul. Seuls des noms sans
    # ambiguïté : « BP » est aussi une boîte postale, « Total » un mot courant.
    employeurs: tuple[str, ...] = ()


FAMILLES: tuple[Famille, ...] = (
    # --- fonctions ---------------------------------------------------------
    Famille(
        "logistique", "logistique",
        ("logistique", "supply chain", "chaine logistique", "chaine d'approvisionnement"),
        (
            "logistique", "logisticien", "logistics", "supply chain", "scm", "chaine logistique",
            "chaine d'approvisionnement", "gestion des stocks", "gestion de stocks", "entreposage",
            "transit", "freight", "warehouse", "magasinier",
        ),
        ("achats", "commerce_international", "transport", "operations"),
    ),
    Famille(
        "transport", "transport",
        ("transport", "transports"),
        ("transport", "transports", "transporteur", "fret", "affretement"),
        ("logistique",),
    ),
    Famille(
        "achats", "achats",
        ("achats", "procurement", "passation des marches", "marches publics"),
        (
            "achats", "acheteur", "procurement", "sourcing", "passation des marches",
            "passation de marches", "marches publics",
        ),
        ("logistique", "commerce"),
    ),
    Famille(
        "operations", "opérations",
        ("operations", "gestion des operations"),
        ("gestion des operations", "operations management", "directeur des operations", "production"),
        ("logistique", "gestion"),
    ),
    Famille(
        "commerce_international", "commerce international",
        ("commerce international", "trading", "negoce", "import export"),
        ("commerce international", "international trade", "trading", "trader", "negoce", "import export"),
        ("commerce", "logistique"),
    ),
    Famille(
        "commerce", "commerce",
        ("commerce", "commercial", "vente", "ventes"),
        (
            "commerce", "commercial", "commerciale", "action commerciale", "force de vente",
            "techniques de commercialisation", "vente", "ventes", "sales", "business development",
        ),
        ("marketing", "commerce_international", "gestion"),
    ),
    Famille(
        "marketing", "marketing",
        ("marketing", "mercatique"),
        ("marketing", "mercatique", "gestion de la marque", "brand management"),
        ("commerce", "communication"),
    ),
    Famille(
        "communication", "communication",
        ("communication", "relations publiques"),
        ("communication", "journalisme", "relations publiques", "public relations"),
        ("marketing",),
    ),
    Famille(
        "rh", "ressources humaines",
        ("ressources humaines", "gestion des ressources humaines", "grh", "gestion du personnel"),
        (
            "ressources humaines", "grh", "drh", "rrh", "gestion du personnel", "human resources",
            "administration du personnel", "gestion des talents", "recrutement", "paie",
        ),
        ("droit_social", "psychologie", "sociologie", "gestion"),
    ),
    Famille(
        "comptabilite", "comptabilité",
        ("comptabilite", "comptable", "sciences comptables"),
        (
            "comptabilite", "comptable", "comptables", "accounting", "cca", "dcg", "dscg",
            "expertise comptable",
        ),
        ("finance", "audit", "banque"),
    ),
    Famille(
        "finance", "finance",
        ("finance", "finances"),
        (
            "finance", "finances", "financier", "financiere", "gestion financiere",
            "corporate finance", "tresorerie",
        ),
        ("comptabilite", "banque", "audit", "economie"),
    ),
    Famille(
        "audit", "audit et contrôle",
        ("audit", "controle de gestion", "controle interne"),
        ("audit", "auditeur", "controle de gestion", "controleur de gestion", "controle interne"),
        ("comptabilite", "finance"),
    ),
    Famille(
        "banque", "banque et assurance",
        ("banque", "assurance", "banque et assurance", "microfinance"),
        ("banque", "bancaire", "assurance", "assurances", "microfinance"),
        ("finance", "comptabilite"),
    ),
    Famille(
        "economie", "économie",
        ("economie", "sciences economiques"),
        ("economie", "economiques", "economics", "econometrie", "economiste"),
        ("finance", "gestion", "statistique"),
    ),
    Famille(
        "gestion", "gestion",
        ("gestion", "management", "administration des entreprises"),
        (
            "gestion", "management", "administration des entreprises", "mba",
            "sciences de gestion", "business administration",
        ),
        ("commerce", "economie", "rh", "logistique", "operations", "projet"),
    ),
    Famille(
        "projet", "gestion de projet",
        ("gestion de projet", "gestion de projets", "management de projet"),
        ("gestion de projet", "gestion de projets", "management de projet", "chef de projet", "project management"),
        ("gestion",),
    ),
    Famille(
        "informatique", "informatique",
        ("informatique", "systemes d'information"),
        (
            "informatique", "genie logiciel", "computer science", "systemes d'information",
            "miage", "developpeur", "developpement logiciel", "software engineering",
        ),
        ("reseaux", "statistique", "mathematiques"),
    ),
    Famille(
        "reseaux", "réseaux et télécoms",
        ("reseaux", "telecommunications", "telecoms"),
        ("reseaux", "telecommunications", "telecoms", "telecom"),
        ("informatique", "electrique"),
    ),
    Famille(
        "statistique", "statistique",
        ("statistique", "statistiques", "data science"),
        ("statistique", "statistiques", "data science", "data analyst", "demographie"),
        ("mathematiques", "economie", "informatique"),
    ),
    Famille(
        "mathematiques", "mathématiques",
        ("mathematiques",),
        ("mathematiques", "maths"),
        ("statistique", "informatique"),
    ),
    Famille(
        "genie_civil", "génie civil",
        ("genie civil", "btp", "batiment"),
        ("genie civil", "btp", "batiment", "travaux publics", "topographie"),
        ("architecture",),
    ),
    Famille(
        "architecture", "architecture",
        ("architecture", "urbanisme"),
        ("architecture", "architecte", "urbanisme"),
        ("genie_civil",),
    ),
    Famille(
        "electrique", "génie électrique",
        ("genie electrique", "electrotechnique"),
        ("genie electrique", "electrotechnique", "electromecanique", "electronique"),
        ("mecanique", "energie", "reseaux"),
    ),
    Famille(
        "mecanique", "génie mécanique",
        ("genie mecanique", "mecanique", "maintenance industrielle"),
        ("genie mecanique", "mecanique", "maintenance industrielle"),
        ("electrique",),
    ),
    Famille(
        "droit_social", "droit social",
        ("droit social", "droit du travail"),
        ("droit social", "droit du travail"),
        ("rh",),
    ),
    Famille(
        "psychologie", "psychologie",
        ("psychologie",),
        ("psychologie", "psychologue"),
        ("rh", "sociologie"),
    ),
    Famille(
        "sociologie", "sociologie",
        ("sociologie",),
        ("sociologie", "sociologue", "anthropologie"),
        ("rh", "psychologie"),
    ),
    Famille(
        "medecine", "médecine",
        ("medecine", "sante"),
        ("medecine", "medecin", "pharmacie", "pharmacien", "soins infirmiers", "infirmier"),
        ("sante_publique",),
    ),
    Famille(
        "sante_publique", "santé publique",
        ("sante publique", "epidemiologie"),
        ("sante publique", "epidemiologie"),
        ("medecine",),
    ),
    Famille(
        "agriculture", "agriculture",
        ("agriculture", "agronomie"),
        (
            "agriculture", "agricole", "agronomie", "agronome", "sciences agronomiques",
            "agroeconomie", "agroalimentaire",
        ),
        ("environnement",),
    ),
    Famille(
        "environnement", "environnement",
        ("environnement", "hse", "qhse"),
        ("environnement", "hse", "qhse", "developpement durable"),
        ("agriculture",),
    ),
    # --- secteurs ----------------------------------------------------------
    Famille(
        "petrole_gaz", "pétrole et gaz",
        ("petrole gaz", "petrole", "gaz", "oil gas", "hydrocarbures"),
        (
            "petrole", "petrolier", "petroliere", "petroliers", "petrolieres", "petroleum",
            "hydrocarbures", "oil gas", "gaz naturel", "gnl", "gpl", "raffinerie", "carburant",
            "carburants", "lubrifiants", "station service", "downstream", "upstream",
        ),
        ("energie",),
        (
            "totalenergies", "total energies", "total togo", "total petroleum", "shell",
            "exxonmobil", "chevron", "vivo energy", "oryx energies", "puma energy", "rubis energie",
            "engen", "oando", "vitol", "trafigura", "gunvor", "mercuria", "sonatrach",
        ),
    ),
    Famille(
        "energie", "énergie",
        ("energie", "energies", "energy"),
        (
            "energie", "energies", "energy", "energetique", "electricite", "solaire",
            "photovoltaique", "energies renouvelables", "renewable energy",
        ),
        ("petrole_gaz", "electrique"),
        ("ceet", "contourglobal", "bboxx", "senelec", "engie"),
    ),
    Famille(
        "maritime", "maritime et portuaire",
        ("maritime", "portuaire", "shipping"),
        ("maritime", "portuaire", "shipping", "armateur", "consignataire", "terminal a conteneurs"),
        ("logistique",),
        ("port autonome de lome", "maersk", "cma cgm", "bollore", "msc togo"),
    ),
    Famille(
        "humanitaire", "humanitaire et développement",
        ("humanitaire", "ong", "developpement international"),
        ("humanitaire", "ong", "cooperation internationale", "developpement international"),
        (),
        ("pnud", "unicef", "giz", "usaid", "croix rouge"),
    ),
)

PAR_CLE: dict[str, Famille] = {f.cle: f for f in FAMILLES}


def _plat(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", (texte or "").lower())
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


@lru_cache(maxsize=8192)
def mots(texte: str) -> tuple[str, ...]:
    """Les mots qui portent le sens, sans accents ni mots de liaison."""
    return tuple(m for m in re.findall(r"[a-z0-9]+", _plat(texte)) if m not in _MOTS_VIDES)


def _meme_mot(cherche: str, mot: str) -> bool:
    """« petrolier » et « petrolieres », pas « informatique » et « information »."""
    if cherche == mot or cherche + "s" == mot:
        return True
    if len(cherche) < _MOT_COURT:
        return False
    commun = 0
    for a, b in zip(cherche, mot):
        if a != b:
            break
        commun += 1
    return commun >= max(_MOT_COURT, len(cherche) - 2)


def _position(expression: tuple[str, ...], texte: tuple[str, ...]) -> int | None:
    """Où l'expression commence dans le texte, ses mots se suivant."""
    n = len(expression)
    for debut in range(len(texte) - n + 1):
        if all(_meme_mot(attendu, mot) for attendu, mot in zip(expression, texte[debut : debut + n])):
            return debut
    return None


@lru_cache(maxsize=1)
def _termes_par_longueur() -> tuple[tuple[tuple[str, ...], str], ...]:
    tous = [(mots(t), f.cle) for f in FAMILLES for t in (*f.termes, *f.employeurs)]
    return tuple(sorted(((m, c) for m, c in tous if m), key=lambda x: -len(x[0])))


@lru_cache(maxsize=4096)
def familles_de(texte: str) -> tuple[Famille, ...]:
    """Les familles que le texte nomme, l'expression la plus longue d'abord.

    « Gestion des stocks » est de la logistique et non de la gestion : les mots
    pris par une expression ne servent pas deux fois.
    """
    restants: list[str | None] = list(mots(texte))
    trouvees: list[str] = []
    for expression, cle in _termes_par_longueur():
        while True:
            pos = _position(expression, tuple(m or "\0" for m in restants))
            if pos is None:
                break
            for i in range(pos, pos + len(expression)):
                restants[i] = None
            if cle not in trouvees:
                trouvees.append(cle)
    return tuple(PAR_CLE[c] for c in trouvees)


@lru_cache(maxsize=1024)
def famille_nommee(attendu: str) -> Famille | None:
    """La famille que désigne un domaine de poste, s'il en est un nom exact."""
    cherche = mots(attendu)
    if not cherche:
        return None
    for famille in FAMILLES:
        if any(mots(nom) == cherche for nom in famille.noms):
            return famille
    return None


def equivalents(declare: str, attendu: str) -> bool:
    """Deux façons de dire la même chose : le domaine déclaré vaut l'attendu."""
    famille = famille_nommee(attendu)
    return famille is not None and famille in familles_de(declare)


def apparente(declare: str, attendu: str) -> bool:
    """Un domaine voisin : à montrer à un humain, jamais à compter d'office."""
    famille = famille_nommee(attendu)
    if famille is None:
        return False
    return any(f.cle in famille.proches for f in familles_de(declare))


def terme_present(texte: str, attendu: str, lexique: tuple[str, ...] | list[str] = ()) -> str | None:
    """Le terme qui rattache ce texte au domaine attendu, ou None.

    `lexique` : les mots propres au poste, validés par les RH.
    """
    contenu = mots(texte)
    famille = famille_nommee(attendu)
    expressions = [*(lexique or ()), *((*famille.termes, *famille.employeurs) if famille else ())]
    for expression in sorted(expressions, key=lambda e: -len(mots(e))):
        cherche = mots(expression)
        if cherche and _position(cherche, contenu) is not None:
            # « Gestion des stocks » n'est pas de la gestion : il faut que le
            # mot serve bien cette famille-là, quand il en a une.
            if famille is None or expression in (lexique or ()) or famille in familles_de(texte):
                return expression
    return None
