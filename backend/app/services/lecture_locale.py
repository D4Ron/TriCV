"""Lire un CV sans modèle : rubriques, diplômes, expériences, langues.

Le fournisseur d'IA est gratuit, donc rationné et parfois saturé. Tout ce
qu'une règle sait lire doit l'être ici, sur le serveur, en quelques
millisecondes — et sans rien envoyer à personne. Le modèle, quand il répond,
complète ou corrige ; quand il ne répond pas, le dossier n'est plus vide.

La méthode est celle des parseurs ouverts les plus utilisés :

- **OpenResume** : le texte est découpé en rubriques à partir des lignes de
  titre (courtes, connues), puis chaque rubrique est lue avec ses propres
  règles, et chaque champ retenu est celui qui obtient le meilleur score.
- **pyresparser / Resume Matcher** : listes de diplômes, de langues et de
  certifications reconnues par mots-clés à frontières de mots, dates lues par
  expressions régulières.

Adapté aux dossiers d'Afrique de l'Ouest francophone : diplômes du système
LMD et des BTS/DUT, « Ingénieur des travaux » (BAC+3), mois abrégés en
français, « à ce jour », villes et pays de la sous-région.

Tout ce qui sort d'ici est une proposition (provenance EXTRAIT_IA).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from app.llm.base import DiplomeExtrait, DossierExtrait, ExperienceExtraite


def plat(texte: str) -> str:
    """Minuscules sans accents ; la ponctuation devient espace, sauf + et /."""
    decompose = unicodedata.normalize("NFD", texte or "")
    sans = "".join(c for c in decompose if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9+/]+", " ", sans.lower()).split())


# --- rubriques ---------------------------------------------------------------

_RUBRIQUES: dict[str, tuple[str, ...]] = {
    "formation": (
        "formation", "formations", "formation academique", "formations academiques",
        "education", "etudes", "diplomes", "diplomes obtenus", "cursus", "cursus academique",
        "parcours academique", "parcours scolaire", "parcours scolaire et universitaire",
        "titres et diplomes", "qualifications academiques", "academic background",
        "formation et diplomes", "diplomes et formations", "etudes et diplomes",
        "formation universitaire", "etudes et formations",
    ),
    "experience": (
        "experience", "experiences", "experience professionnelle", "experiences professionnelles",
        "parcours professionnel", "work experience", "professional experience", "emplois",
        "historique professionnel", "employment history", "experiences et stages",
        "stages et experiences", "experience de travail", "stages", "stage",
        "employment", "career", "carriere", "experiences cles", "principales experiences",
        "experiences professionnelles et stages",
    ),
    "competences": (
        "competences", "competences techniques", "competences cles", "skills", "technical skills",
        "aptitudes", "connaissances", "connaissances informatiques", "informatique",
        "outils", "savoir faire", "atouts", "qualites", "competences professionnelles",
    ),
    "langues": ("langues", "langue", "languages", "langues parlees", "competences linguistiques"),
    "certifications": (
        "certifications", "certification", "certificats", "formations complementaires",
        "formations continues", "formation continue", "seminaires", "seminaires et formations",
        "autres formations", "stages et formations", "trainings", "licenses certifications",
        "certifications et formations",
    ),
    "projets": ("projets", "projects", "realisations", "realisations cles", "travaux"),
    "references": ("references", "referents", "referees", "personnes de reference"),
    "loisirs": ("loisirs", "centres d interet", "centres d interets", "interets", "hobbies", "divers", "activites"),
    "profil": ("profil", "profile", "resume", "summary", "objectif", "objectif professionnel", "a propos"),
    "etat_civil": ("etat civil", "informations personnelles", "renseignements personnels", "contact", "coordonnees"),
}
_TITRE_VERS_RUBRIQUE = {titre: cle for cle, titres in _RUBRIQUES.items() for titre in titres}
_TITRES_PAR_LONGUEUR = sorted(_TITRE_VERS_RUBRIQUE.items(), key=lambda x: -len(x[0]))


def rubrique_de(ligne: str) -> str | None:
    """La rubrique qu'annonce une ligne de titre, ou None.

    Un titre est court, et se lit tel quel après retrait des puces, des deux
    points et des numéros (« II. EXPÉRIENCES PROFESSIONNELLES : »).
    """
    texte = re.sub(r"^[\W\d_]*(?:[ivxIVX]+[.)]\s+)?", "", ligne.strip())
    texte = texte.rstrip(" :.-–—")
    p = plat(texte)
    if not p or len(p.split()) > 5:
        return None
    if p in _TITRE_VERS_RUBRIQUE:
        return _TITRE_VERS_RUBRIQUE[p]
    # « Expériences professionnelles récentes », « Formation & diplômes »
    for titre, cle in _TITRES_PAR_LONGUEUR:
        if p.startswith(titre + " ") and len(p.split()) <= len(titre.split()) + 2:
            return cle
    return None


def rubriques(texte: str) -> dict[str, list[str]]:
    """Les lignes de chaque rubrique. « debut » reçoit ce qui précède le premier titre."""
    sections: dict[str, list[str]] = {"debut": []}
    courante = "debut"
    for ligne in (texte or "").splitlines():
        if not ligne.strip():
            continue
        cle = rubrique_de(ligne)
        if cle:
            courante = cle
            sections.setdefault(cle, [])
            continue
        # Un titre suivi de son contenu sur la même ligne : une cellule de
        # tableau (« LANGUES   Français, Anglais ») ou un « Titre : contenu ».
        tete = re.match(r"^\s*(.{3,40}?)(?:\s{2,}|\s*:\s+)(\S.*)$", ligne)
        if tete and (cle := rubrique_de(tete.group(1))):
            courante = cle
            sections.setdefault(cle, []).append(tete.group(2).strip())
            continue
        sections.setdefault(courante, []).append(ligne.strip())
    return sections


# --- dates -------------------------------------------------------------------

_MOIS = (
    ("janvier", 1), ("janv", 1), ("jan", 1), ("january", 1),
    ("fevrier", 2), ("fevr", 2), ("fev", 2), ("february", 2), ("feb", 2),
    ("mars", 3), ("march", 3), ("mar", 3),
    ("avril", 4), ("avr", 4), ("april", 4), ("apr", 4),
    ("mai", 5), ("may", 5),
    ("juin", 6), ("june", 6), ("jun", 6),
    ("juillet", 7), ("juil", 7), ("july", 7), ("jul", 7),
    ("aout", 8), ("august", 8), ("aug", 8),
    ("septembre", 9), ("sept", 9), ("september", 9), ("sep", 9),
    ("octobre", 10), ("october", 10), ("oct", 10),
    ("novembre", 11), ("november", 11), ("nov", 11),
    ("decembre", 12), ("december", 12), ("dec", 12),
)
_NOMS_MOIS = "|".join(sorted({m for m, _ in _MOIS}, key=len, reverse=True))
_NUMERO_MOIS = dict(_MOIS)
_PRESENT = (
    r"(?:a ce jour|a nos jours|ce jour|aujourd hui|present|now|current|currently|en cours|"
    r"actuellement|actuel|date|today|nos jours)"
)
_DATE = (
    r"(?:(?P<mois{n}>" + _NOMS_MOIS + r") ?(?P<annee{n}>(?:19|20)\d\d)"
    # « 03/2019 », et « 01/03/2019 » dont le jour ne compte pas.
    r"|(?:[0-3]?\d ?/ ?)?(?P<num{n}>0?[1-9]|1[0-2]) ?/ ?(?P<an{n}>(?:19|20)\d\d)"
    r"|(?P<seule{n}>(?:19|20)\d\d))"
)
# Les tirets disparaissent à la normalisation : le mot de liaison est facultatif.
_LIAISON = r" ?(?:(?:a|au|to|until|jusqu a|jusqu au|/) )?"
_PLAGE = re.compile(
    r"(?:\b(?P<depuis>de|du|from|depuis|since) )?\b" + _DATE.format(n=1)
    + r"(?:" + _LIAISON + r"(?:\b" + _DATE.format(n=2) + r"|\b(?P<present>" + _PRESENT + r")))?\b"
)
_DEUX_MOIS = re.compile(
    r"\b(?P<m1>" + _NOMS_MOIS + r") (?:(?:a|au|to) )?(?P<m2>" + _NOMS_MOIS + r") ?(?P<annee>(?:19|20)\d\d)\b"
)


@dataclass(slots=True)
class Plage:
    debut: str
    fin: str | None
    approximative: bool


def _date_de(m: re.Match, n: int) -> tuple[int, int | None] | None:
    if m.group(f"mois{n}"):
        return int(m.group(f"annee{n}")), _NUMERO_MOIS[m.group(f"mois{n}")]
    if m.group(f"num{n}"):
        return int(m.group(f"an{n}")), int(m.group(f"num{n}"))
    if m.group(f"seule{n}"):
        return int(m.group(f"seule{n}")), None
    return None


def plages(ligne: str, aujourd_hui: date | None = None) -> list[Plage]:
    """Les plages de dates d'une ligne : « Mars 2021 – aujourd'hui », « 2015-2018 »…

    Une date seule ne fait une plage que précédée de « depuis » : une année
    isolée est plus souvent celle d'un diplôme ou d'un projet que la durée
    d'un emploi.
    """
    aujourd_hui = aujourd_hui or date.today()
    limite = aujourd_hui.year + 1
    p = plat(ligne)
    resultats: list[Plage] = []
    # « Fév. – Juin 2026 » : deux mois qui partagent une année.
    for m in _DEUX_MOIS.finditer(p):
        an = int(m.group("annee"))
        d, f = _NUMERO_MOIS[m.group("m1")], _NUMERO_MOIS[m.group("m2")]
        if d <= f and 1950 <= an <= limite:
            resultats.append(Plage(f"{an:04d}-{d:02d}", f"{an:04d}-{f:02d}", False))
    if resultats:
        return resultats
    for m in _PLAGE.finditer(p):
        debut, fin = _date_de(m, 1), _date_de(m, 2)
        en_cours = bool(m.group("present"))
        depuis = m.group("depuis") in ("depuis", "since")
        if debut is None or (fin is None and not en_cours and not depuis):
            continue
        an_d, mois_d = debut
        if not 1950 <= an_d <= limite:
            continue
        approximative = mois_d is None
        fin_txt = None
        if fin is not None:
            an_f, mois_f = fin
            approximative = approximative or mois_f is None
            if an_f < an_d or an_f > limite:
                continue
            if mois_f is None:
                # « 2015 – 2018 » : d'un janvier au suivant, soit trois ans.
                mois_f = 12 if an_f == an_d else 1
            fin_txt = f"{an_f:04d}-{mois_f:02d}"
        resultats.append(Plage(f"{an_d:04d}-{(mois_d or 1):02d}", fin_txt, approximative))
    return resultats


def _annees(ligne: str) -> list[int]:
    return [int(a) for a in re.findall(r"\b((?:19|20)\d\d)\b", ligne)]


_MOIS_ORIGINE = (
    r"janvier|janv|jan|f[ée]vrier|f[ée]vr|f[ée]v|mars|mar|avril|avr|mai|juin|juillet|juil|"
    r"ao[uû]t|septembre|sept|sep|octobre|oct|novembre|nov|d[ée]cembre|d[ée]c|january|"
    r"february|feb|march|april|apr|may|june|jun|july|jul|august|aug|september|october|"
    r"november|december"
)
_DATE_ORIGINE = re.compile(
    r"\(?\b(?:(?:de|du|from|depuis|since)\s+)?(?:(?:" + _MOIS_ORIGINE + r")\.?\s*|(?:0?[1-9]|1[0-2])\s*/\s*)?"
    r"(?:19|20)\d\d\b\)?"
    r"|\b(?:" + _MOIS_ORIGINE + r")\.?(?=\s*[-–—/]\s*(?:" + _MOIS_ORIGINE + r"))",
    re.IGNORECASE,
)
_PRESENT_ORIGINE = re.compile(
    r"\b(?:[àa] ce jour|aujourd[’']hui|pr[ée]sent|en cours|actuellement|now|current|today)\b",
    re.IGNORECASE,
)


def retirer_dates(ligne: str) -> str:
    """La ligne sans ses dates, pour garder le poste et l'employeur qui l'entourent."""
    texte = _PRESENT_ORIGINE.sub(" ", _DATE_ORIGINE.sub(" ", ligne))
    texte = re.sub(r"(\s*[-–—|,/]\s*){2,}", " — ", texte)
    return " ".join(texte.split()).strip(" ,;:-–—|()/")


# --- diplômes ----------------------------------------------------------------

# (motif, niveau) — testés dans l'ordre, à frontières de mots.
_DIPLOMES: tuple[tuple[str, int], ...] = (
    (r"doctorat|phd|ph d|doctorate|these de doctorat", 8),
    (r"bac ?\+ ?8", 8),
    (r"bac ?\+ ?5", 5),
    (r"bac ?\+ ?4", 4),
    (r"bac ?\+ ?3", 3),
    (r"bac ?\+ ?2", 2),
    (r"bac ?\+ ?1", 1),
    (r"master ?(?:1|i|one)|m1|maitrise", 4),
    (r"master ?(?:2|ii)|m2|master|mastere|mba|msc|m sc|dess|dea|dscg|diplome d etudes superieures specialisees", 5),
    (r"(?:diplome d )?ingenieur des travaux", 3),
    (r"diplome d ingenieur|ingenieur|cycle ingenieur|engineering degree", 5),
    (r"licence|bachelor|bsc|b sc|dcg", 3),
    (r"bts|dut|deug|duel|dts|hnd|brevet de technicien superieur|diplome universitaire de technologie", 2),
    (r"baccalaureat|bac", 0),
)
_DIPLOME = [(re.compile(r"\b(?:" + motif + r")\b"), niveau) for motif, niveau in _DIPLOMES]

_ETABLISSEMENTS = frozenset(
    {
        "universite", "university", "univ", "ecole", "school", "institut", "institute", "faculte",
        "faculty", "college", "lycee", "polytechnique", "academie", "academy", "centre", "iut",
        "esgis", "ucad", "esp", "ism", "cesag", "iaec", "ipnet", "ena", "ensi", "insa", "ucao",
        "fass", "faseg", "ul", "enset", "inp", "ufhb", "uac", "isca", "esa", "esae", "ensea",
        "issic", "hec", "essec", "dauphine", "sorbonne", "ecobank",
    }
)
_COUPURES = re.compile(r"\s*[,;|•·(]\s*|\s+[-–—]\s+|\s*[–—]\s*")


def _niveau_de(ligne_plate: str) -> tuple[int, re.Match] | None:
    for motif, niveau in _DIPLOME:
        m = motif.search(ligne_plate)
        if m:
            return niveau, m
    return None


def _est_etablissement(morceau: str) -> bool:
    return bool(set(plat(morceau).split()) & _ETABLISSEMENTS)


def _domaine_apres(p: str, m: re.Match) -> str:
    """« master en gestion des ressources humaines » → « gestion des ressources humaines »."""
    reste = p[m.end():]
    trouve = re.match(
        r"\s*(?:(?:professionnelle?|pro|recherche|fondamentale|specialise|of science|of arts|of business administration)\s+)?"
        r"(?:en|de|d|des|in|of|option|specialite)\s+(.*)",
        reste,
    )
    if trouve:
        suite = trouve.group(1)
    else:
        # « BSc Computer Science » : le domaine suit sans préposition.
        suite = re.sub(r"^\s*(?:(?:professionnelle?|pro|recherche|fondamentale|1|2|i|ii)\s+)*", "", reste)
        if re.match(r"\s*(?:19|20)\d\d", suite):
            return ""
    domaine = re.split(
        r"\b(?:universite|university|ecole|institut|institute|faculte|college|option|obtenu|en cours|(?:19|20)\d\d)\b",
        suite,
    )[0]
    return " ".join(domaine.split()[:8]).strip()


def diplomes(sections: dict[str, list[str]], texte: str) -> list[DiplomeExtrait]:
    lignes = sections.get("formation") or []
    if not lignes:
        # Sans rubrique « Formation », seules les lignes qui portent un
        # diplôme, une année et un établissement sont crues.
        lignes = [
            l for l in (texte or "").splitlines()
            if _annees(l) and _est_etablissement(l) and _niveau_de(plat(l))
        ]
    trouves: list[DiplomeExtrait] = []
    for i, ligne in enumerate(lignes):
        morceaux = [m for m in _COUPURES.split(ligne) if m and m.strip()]
        if not morceaux or len(plat(ligne).split()) > 25:
            continue
        # Le morceau qui nomme le diplôme : « Licence en Droit », dans
        # « 2018 – Licence en Droit, Université de Lomé ».
        reconnu = None
        for index, morceau in enumerate(morceaux):
            p = plat(morceau)
            niveau = _niveau_de(p)
            if niveau is not None:
                reconnu = (index, p, *niveau)
                break
        if reconnu is None:
            continue
        index, p, niveau, m = reconnu
        intitule = retirer_dates(morceaux[index]).strip()
        if not plat(intitule):
            continue
        domaine = _domaine_apres(p, m)
        # L'établissement : dans la même ligne, ou sur la suivante.
        voisines: list[str] = []
        for v in lignes[i + 1 : i + 3]:
            if _niveau_de(plat(v)):
                break
            voisines.append(v)
        etablissement = None
        candidats = [x for j, x in enumerate(morceaux) if j != index]
        candidats += [x for v in voisines for x in _COUPURES.split(v) if x and x.strip()]
        for morceau in candidats:
            if _est_etablissement(morceau):
                etablissement = retirer_dates(morceau)[:255] or None
                break
        annees = _annees(ligne) or [a for v in voisines[:1] for a in _annees(v)]
        trouves.append(
            DiplomeExtrait(
                intitule=intitule[:512],
                niveau=niveau,
                domaine=domaine,
                domaine_dossier=domaine,
                etablissement=etablissement,
                annee=max(annees) if annees else None,
            )
        )
    # Un même diplôme cité deux fois (en-tête et rubrique) ne compte qu'une fois.
    uniques: dict[tuple, DiplomeExtrait] = {}
    for d in trouves:
        uniques.setdefault((d.niveau, d.domaine, d.annee), d)
    return list(uniques.values())


_MENTION_DOMAINE = re.compile(
    r"^\s*(?:mention|sp[ée]cialit[ée]|option|parcours|domaine|fili[èe]re|field of study|major)\s*[:：]?\s*(.+)$",
    re.IGNORECASE,
)


def diplome_d_une_copie(texte: str, aujourd_hui: date | None = None) -> DiplomeExtrait | None:
    """Le diplôme qu'atteste une copie scannée, ou None.

    Une copie de diplôme ne se lit pas comme un CV : le grade est en gros sur
    une ligne, l'université sur une autre, l'année dans « session de juin
    2015 ». On prend le grade le plus élevé nommé — « titulaire du
    baccalauréat » figure aussi sur un diplôme de licence —, la mention ou
    spécialité, l'établissement et l'année la plus récente.
    """
    limite = (aujourd_hui or date.today()).year + 1
    meilleur: tuple[int, str, re.Match, str] | None = None
    etablissement = None
    domaine = ""
    for ligne in (texte or "").splitlines()[:80]:
        p = plat(ligne)
        if not p:
            continue
        if etablissement is None and _est_etablissement(ligne) and len(p.split()) <= 12:
            etablissement = retirer_dates(ligne)[:255] or None
        if not domaine and (m := _MENTION_DOMAINE.match(ligne)):
            domaine = " ".join(plat(m.group(1)).split()[:8])
        reconnu = _niveau_de(p)
        if reconnu and len(p.split()) <= 15 and (meilleur is None or reconnu[0] > meilleur[0]):
            meilleur = (reconnu[0], p, reconnu[1], ligne)
    if meilleur is None:
        return None
    niveau, p, m, ligne = meilleur
    domaine = domaine or _domaine_apres(p, m)
    annees = [a for a in _annees(texte or "") if a <= limite]
    return DiplomeExtrait(
        intitule=retirer_dates(ligne)[:512],
        niveau=niveau,
        domaine=domaine,
        domaine_dossier=domaine,
        etablissement=etablissement,
        annee=max(annees) if annees else None,
    )


# --- expériences -------------------------------------------------------------

_PUCE = re.compile(r"^\s*(?:[•●▪■◦○◆➢➤►✓✔\-–—*·]|\d+[.)]\s)\s*")
_MARQUES_EMPLOYEUR = frozenset(
    {
        "sa", "sarl", "sas", "suarl", "ltd", "limited", "inc", "llc", "plc", "group", "groupe",
        "banque", "bank", "ong", "ngo", "ministere", "ministry", "projet", "project", "societe",
        "cabinet", "agence", "agency", "universite", "university", "hopital", "hospital", "office",
        "fondation", "foundation", "programme", "program", "pnud", "undp", "unicef", "usaid",
        "giz", "afd", "bad", "boad", "ecobank", "orabank", "togocom", "moov", "mtn",
        "assurances", "assurance", "consulting", "consult", "services", "solutions", "company",
        "entreprise", "corporation", "corp", "mairie", "prefecture", "ambassade",
        "association", "cooperative", "clinique", "lycee", "ecole", "institut", "port", "autonome",
        "international", "afrique", "africa", "digital", "technologies", "industries", "analytics",
        "retail", "telecom", "microfinance", "finance", "bureau", "direction", "centre",
    }
)
_MARQUES_POSTE = frozenset(
    {
        "assistant", "assistante", "charge", "chargee", "responsable", "directeur", "directrice",
        "ingenieur", "comptable", "stagiaire", "consultant", "consultante", "manager",
        "chef", "analyste", "developpeur", "developpeuse", "gestionnaire", "agent", "coordonnateur",
        "coordinateur", "coordinatrice", "auditeur", "auditrice", "technicien", "technicienne",
        "secretaire", "juriste", "architecte", "scientist", "engineer", "officer", "intern",
        "specialist", "specialiste", "superviseur", "conseiller", "conseillere", "caissier",
        "caissiere", "commercial", "commerciale", "enseignant", "enseignante", "professeur",
        "logisticien", "operateur", "administrateur", "administratrice", "controleur", "expert",
        "experte", "senior", "junior", "lead", "head", "director", "associate", "volontaire",
        "animateur", "animatrice", "formateur", "formatrice", "infirmier", "infirmiere", "medecin",
        "economiste", "statisticien", "chauffeur", "magasinier", "vendeur", "vendeuse",
        "receptionniste", "delegue", "representant", "attache", "inspecteur", "adjoint",
        "adjointe", "principal", "president", "fondateur", "dg", "daf", "drh", "rrh", "raf",
        "stage", "developer", "accountant", "trainee",
    }
)
_VILLES = {
    "lome": "Togo", "kara": "Togo", "sokode": "Togo", "kpalime": "Togo", "atakpame": "Togo",
    "dapaong": "Togo", "tsevie": "Togo", "aneho": "Togo", "cotonou": "Bénin", "porto novo": "Bénin",
    "parakou": "Bénin", "abidjan": "Côte d'Ivoire", "yamoussoukro": "Côte d'Ivoire",
    "dakar": "Sénégal", "accra": "Ghana", "kumasi": "Ghana", "lagos": "Nigeria", "abuja": "Nigeria",
    "ouagadougou": "Burkina Faso", "bamako": "Mali", "niamey": "Niger", "conakry": "Guinée",
    "douala": "Cameroun", "yaounde": "Cameroun", "libreville": "Gabon", "kinshasa": "RD Congo",
    "nairobi": "Kenya", "paris": "France", "lyon": "France", "montreal": "Canada",
}
_PAYS = {
    "togo": "Togo", "benin": "Bénin", "cote d ivoire": "Côte d'Ivoire", "senegal": "Sénégal",
    "ghana": "Ghana", "nigeria": "Nigeria", "burkina faso": "Burkina Faso", "mali": "Mali",
    "niger": "Niger", "guinee": "Guinée", "cameroun": "Cameroun", "cameroon": "Cameroun",
    "gabon": "Gabon", "kenya": "Kenya", "france": "France", "canada": "Canada",
    "maroc": "Maroc", "tunisie": "Tunisie", "rdc": "RD Congo",
}
_MOTS_DE_LIEU = frozenset(w for nom in [*_VILLES, *_PAYS] for w in nom.split()) | {"d", "remote", "teletravail"}


_ENTETES_DE_TABLEAU = frozenset(
    {
        "periode", "periodes", "poste", "postes", "employeur", "employeurs", "diplome", "diplomes",
        "etablissement", "date", "dates", "fonction", "fonctions", "structure", "annee", "annees",
        "lieu", "entreprise", "organisme", "intitule", "duree", "taches", "missions", "pays", "de", "a",
    }
)


def _est_entete_de_tableau(ligne: str) -> bool:
    mots = plat(ligne).split()
    return len(mots) >= 2 and all(m in _ENTETES_DE_TABLEAU for m in mots)


def _est_puce(ligne: str) -> bool:
    """Une ligne de description : puce, phrase longue, ou suite d'une phrase.

    Une puce trop longue se poursuit sur la ligne suivante, sans puce : cette
    suite commence par une minuscule ou finit par un point, ce qu'un titre ne
    fait pas.
    """
    propre = ligne.strip()
    return (
        bool(_PUCE.match(propre))
        or len(propre.split()) > 16
        or (propre[:1].islower())
        or (propre.endswith(".") and len(propre.split()) > 3)
        or _est_entete_de_tableau(propre)
    )


def _pays(texte: str) -> str | None:
    p = f" {plat(texte)} "
    for nom, pays in _PAYS.items():
        if f" {nom} " in p:
            return pays
    for ville, pays in _VILLES.items():
        if f" {ville} " in p:
            return pays
    return None


def _n_est_qu_un_lieu(morceau: str) -> bool:
    mots = plat(morceau).split()
    return not mots or all(m in _MOTS_DE_LIEU for m in mots)


def _score(morceau: str, marques: frozenset[str]) -> int:
    score = sum(1 for m in plat(morceau).split() if m in marques)
    if marques is _MARQUES_EMPLOYEUR and re.search(r"\b[A-Z]{2,}\b", morceau) and not morceau.isupper():
        score += 1
    return score


def _morceaux_utiles(lignes: list[str]) -> list[str]:
    utiles: list[str] = []
    for ligne in lignes:
        for part in re.split(r"\s+[—–|@]\s+|\s+-\s+|\s+chez\s+|\s+at\s+|,\s+|\s*[|•·]\s*|\s{2,}|\s+:\s+", ligne):
            part = retirer_dates(part).strip(" ,;:-–—|()")
            if part and not _n_est_qu_un_lieu(part) and re.search(r"[^\W\d_]{2,}", part):
                utiles.append(part)
    return utiles


def _poste_et_employeur(utiles: list[str]) -> tuple[str, str]:
    """Range des morceaux de texte en (poste, employeur)."""
    if not utiles:
        return "", ""
    if len(utiles) == 1:
        seul = utiles[0]
        if _score(seul, _MARQUES_EMPLOYEUR) > _score(seul, _MARQUES_POSTE):
            return "", seul
        return seul, ""
    premiers = utiles[:3]
    # À égalité, l'ordre « Poste — Employeur », le plus courant.
    poste = max(premiers, key=lambda x: (_score(x, _MARQUES_POSTE) - _score(x, _MARQUES_EMPLOYEUR), -premiers.index(x)))
    restants = [u for u in premiers if u is not poste]
    employeur = max(restants, key=lambda x: (_score(x, _MARQUES_EMPLOYEUR) - _score(x, _MARQUES_POSTE), -restants.index(x)))
    return poste, employeur


def _domaines(texte: str, vocabulaire: list[str]) -> list[str]:
    """Les domaines du poste que le texte de l'expérience nomme en toutes lettres."""
    mots_texte = plat(texte).split()
    retenus = []
    for domaine in vocabulaire:
        mots = [m for m in plat(domaine).split() if len(m) > 2 and m not in ("des", "les", "aux", "and")]
        # Un mot du domaine se retrouve en tête d'un mot du texte :
        # « logistique » dans « logistiques », « gestion » dans « gestion ».
        if mots and all(any(t.startswith(m[: max(4, len(m) - 2)]) for t in mots_texte) for m in mots):
            retenus.append(domaine)
    return list(dict.fromkeys(retenus))


def experiences(
    sections: dict[str, list[str]], vocabulaire: list[str], aujourd_hui: date | None = None
) -> list[ExperienceExtraite]:
    lignes = sections.get("experience") or []
    if not lignes:
        # Pas de rubrique reconnue : tout ce qui n'est ni formation ni diplôme.
        lignes = [
            l
            for cle, contenu in sections.items()
            if cle not in ("formation", "certifications", "references", "langues", "competences")
            for l in contenu
            if not _niveau_de(plat(l))
        ]
    entrees: list[tuple[int, Plage, list[str]]] = []
    dernier_utilise = -1
    for i, ligne in enumerate(lignes):
        if _est_puce(ligne) and len(ligne.split()) > 16:
            continue
        trouvees = plages(ligne, aujourd_hui)
        if not trouvees:
            continue
        morceaux = [ligne]
        # Les lignes de titre juste au-dessus, non encore prises — sauf si la
        # ligne datée dit déjà le poste et l'employeur : la ligne d'au-dessus
        # est alors la suite de l'expérience précédente.
        if len(_morceaux_utiles(morceaux)) < 2:
            j, dessus = i - 1, []
            while (
                j > dernier_utilise
                and len(dessus) < 2
                and not _est_puce(lignes[j])
                and not plages(lignes[j], aujourd_hui)
                and not lignes[j].rstrip().endswith(",")
            ):
                dessus.insert(0, lignes[j])
                j -= 1
            morceaux = dessus + morceaux
        fin_bloc = i
        # Format « dates », puis « Poste », puis « Employeur » : on lit dessous.
        k = i + 1
        while (
            len(_morceaux_utiles(morceaux)) < 2
            and k < len(lignes)
            and k <= i + 2
            and not _est_puce(lignes[k])
            and not plages(lignes[k], aujourd_hui)
        ):
            morceaux.append(lignes[k])
            fin_bloc = k
            k += 1
        dernier_utilise = fin_bloc
        entrees.append((i, trouvees[0], morceaux))

    resultats: list[ExperienceExtraite] = []
    for n, (i, plage, morceaux) in enumerate(entrees):
        poste, employeur = _poste_et_employeur(_morceaux_utiles(morceaux))
        if not poste and not employeur:
            continue
        suivante = entrees[n + 1][0] - 2 if n + 1 < len(entrees) else len(lignes)
        bloc = " ".join(morceaux + lignes[i + 1 : max(i + 1, suivante)])
        resultats.append(
            ExperienceExtraite(
                poste=poste[:512] or "poste non précisé",
                employeur=employeur[:512] or "employeur non précisé",
                debut=plage.debut,
                fin=plage.fin,
                domaines=_domaines(bloc, vocabulaire),
                pays=_pays(" ".join(morceaux)),
            )
        )
    return resultats


# --- langues et certifications -----------------------------------------------

_LANGUES = {
    "francais": "Français", "french": "Français", "anglais": "Anglais", "english": "Anglais",
    "espagnol": "Espagnol", "spanish": "Espagnol", "allemand": "Allemand", "german": "Allemand",
    "portugais": "Portugais", "portuguese": "Portugais", "arabe": "Arabe", "arabic": "Arabe",
    "chinois": "Chinois", "mandarin": "Chinois", "chinese": "Chinois", "italien": "Italien",
    "italian": "Italien", "russe": "Russe", "ewe": "Éwé", "kabye": "Kabyè", "mina": "Mina",
    "yoruba": "Yoruba", "haoussa": "Haoussa", "hausa": "Haoussa", "wolof": "Wolof",
    "swahili": "Swahili", "fon": "Fon", "dioula": "Dioula", "bambara": "Bambara",
    "lingala": "Lingala", "twi": "Twi", "peul": "Peul", "fulfulde": "Peul", "baoule": "Baoulé",
    "kotokoli": "Tem", "igbo": "Igbo",
}
_CERTIFS = re.compile(
    r"\b(PMP|PRINCE2|ITIL|CISA|CISM|CISSP|CCNA|CCNP|ACCA|CPA|CFA|PSM|CSM|"
    r"TOEFL|TOEIC|IELTS|DELF|DALF|Six Sigma|Scrum Master|AWS Certified[\w ]{0,30}|"
    r"Google Cloud Certified[\w ]{0,30})\b"
)


def langues(sections: dict[str, list[str]], texte: str) -> list[str]:
    lignes = list(sections.get("langues") or [])
    lignes += [l for l in (texte or "").splitlines() if plat(l).startswith(("langues", "langue ", "languages"))]
    vues: list[str] = []
    for ligne in lignes:
        for mot in plat(ligne).split():
            nom = _LANGUES.get(mot)
            if nom and nom not in vues:
                vues.append(nom)
    return vues


def certifications(sections: dict[str, list[str]], texte: str) -> list[str]:
    trouvees: list[str] = []
    for ligne in sections.get("certifications") or []:
        # « AutoCAD avancé (2015), Gestion de projet PMP (2018) » : deux.
        for morceau in re.split(r";\s*|,\s+(?=[A-ZÉÈÀ])", _PUCE.sub("", ligne)):
            propre = morceau.strip(" ,;.")
            if 2 <= len(propre.split()) <= 18 and propre not in trouvees:
                trouvees.append(propre[:200])
    for m in _CERTIFS.finditer(texte or ""):
        sigle = m.group(1).strip()
        if not any(sigle.lower() in t.lower() for t in trouvees):
            trouvees.append(sigle)
    return trouvees[:20]


# --- le tout -----------------------------------------------------------------


def lire(texte: str, vocabulaire: list[str] | None = None, aujourd_hui: date | None = None) -> DossierExtrait:
    """Ce qu'un CV dit de lui-même, lu par règles."""
    sections = rubriques(texte)
    return DossierExtrait(
        diplomes=diplomes(sections, texte),
        experiences=experiences(sections, list(vocabulaire or []), aujourd_hui),
        langues=langues(sections, texte),
        certifications=certifications(sections, texte),
    )


_FAMILLES = {
    "diplomes": "Diplômes",
    "experiences": "Expériences",
    "langues": "Langues",
    "certifications": "Certifications",
}


def fusionner(locale: DossierExtrait, ia: DossierExtrait | None) -> tuple[DossierExtrait, list[str]]:
    """Le modèle prime famille par famille ; la lecture locale comble ses vides.

    Rend aussi, pour le relecteur, ce qui vient de la lecture locale.
    """
    if ia is None:
        return locale, []
    notes: list[str] = []
    resultat = DossierExtrait()
    for famille, libelle in _FAMILLES.items():
        venues_ia = getattr(ia, famille)
        if venues_ia:
            setattr(resultat, famille, venues_ia)
        else:
            setattr(resultat, famille, getattr(locale, famille))
            if getattr(locale, famille):
                notes.append(f"{libelle} : lus par la lecture locale, l'IA n'en a pas trouvé.")
    return resultat, notes
