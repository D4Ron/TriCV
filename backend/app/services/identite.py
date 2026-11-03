"""Le nom et le prénom d'un candidat, devinés sans modèle.

Constaté en production : l'import par courriel inversait presque toujours nom et
prénom, écrivait le nom en minuscules, et a pris « Yahoo! » pour le nom d'un
candidat. La cause : le premier mot de l'expéditeur tenait lieu de nom — or une
messagerie affiche « Prénom Nom » —, tout était passé en casse de titre, ce qui
effaçait le seul indice sûr (le NOM en capitales), et rien ne filtrait les
libellés qui ne sont pas des personnes. Le CV, lui, n'était jamais consulté : le
texte part expurgé au modèle, sans le nom.

Trois sources, de la plus sûre à la moins sûre :

1. **Le CV** : les champs « Nom : » et « Prénoms : » quand il y en a, sinon la
   ligne d'en-tête choisie par score — à la façon du parseur d'OpenResume (la
   ligne en plus gros caractères, courte, en haut, faite de lettres, qui n'est
   ni une rubrique ni un intitulé de poste), adapté aux CV français : le NOM
   en capitales est un indice fort, l'accord avec l'adresse électronique aussi.
2. **Le libellé de l'expéditeur**, s'il désigne une personne.
3. **L'adresse** elle-même (afi.dossou@… → Afi / Dossou).

Le résultat reste une proposition — provenance EXTRAIT_IA — que la relecture
confirme ou corrige.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Ce qu'un libellé d'expéditeur peut être sans être une personne.
_LIBELLES_NON_PERSONNES = frozenset(
    {
        "yahoo", "yahoo mail", "gmail", "google", "outlook", "hotmail", "live", "msn",
        "orange", "free", "icloud", "apple", "mail", "messagerie", "webmail", "email",
        "e mail", "courriel", "candidat", "candidate", "candidature", "candidatures",
        "recrutement", "recruitment", "cv", "curriculum vitae", "info", "infos",
        "contact", "admin", "administrateur", "noreply", "no reply", "ne pas repondre",
        "service", "secretariat", "direction", "rh", "ressources humaines", "moi", "me",
        "utilisateur", "user", "owner", "mobile", "iphone", "android", "unknown", "inconnu",
        "dossier", "office", "bureau", "job", "jobs", "emploi", "travail", "postulant",
    }
)
# Les mots qui font d'une ligne une rubrique ou un intitulé, pas un nom.
_PAS_UN_NOM = frozenset(
    {
        "curriculum", "vitae", "cv", "resume", "profil", "profile", "contact", "contacts",
        "experience", "experiences", "professionnelle", "professionnelles", "professionnel",
        "formation", "formations", "education", "competences", "competence", "skills",
        "langues", "languages", "loisirs", "interets", "references", "objectif", "diplomes",
        "certifications", "informations", "personnelles", "adresse", "telephone", "tel",
        "email", "mail", "nationalite", "nee", "age", "ans", "celibataire", "lettre",
        "motivation", "objet", "madame", "monsieur", "messieurs", "attestation", "certificat",
        "republique", "ministere", "universite", "ecole", "institut", "ingenieur", "comptable",
        "assistant", "assistante", "manager", "directeur", "directrice", "charge", "chargee",
        "chef", "responsable", "analyste", "technicien", "developpeur", "developpeuse",
        "consultant", "stagiaire", "gestionnaire", "agent", "conseiller", "coordonnateur",
        "coordinateur", "superviseur", "secretaire", "auditeur", "logisticien", "juriste",
        "economiste", "medecin", "infirmier", "enseignant", "engineer", "software", "senior",
        "junior", "data", "scientist", "architecte", "lead", "head", "master", "licence",
        "doctorat", "bac", "page", "togo", "lome", "benin", "cotonou", "abidjan", "dakar",
        "kapi", "consult", "sarl", "sa", "group", "groupe", "projet", "candidature", "poste",
        "dossier", "piece", "pieces", "jointes", "date", "signature", "fait", "le", "a",
        "the", "and", "et", "de", "pour", "student", "etudiant", "etudiante", "summary",
    }
)
# Particules qui restent en minuscules au milieu d'un nom.
_PARTICULES = frozenset({"de", "du", "des", "da", "dos", "van", "von", "le", "la", "ben", "bin"})

_MOT = re.compile(r"^[^\W\d_]+(?:['’\-][^\W\d_]+)*\.?$", re.UNICODE)


def _plat(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte or "")
    sans = "".join(c for c in decompose if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", sans.lower()).strip()


def _capitaliser(mot: str) -> str:
    """« n'dri » → « N'Dri », « kouassi-bile » → « Kouassi-Bile », « DE » → « de »."""
    if mot.lower() in _PARTICULES:
        return mot.lower()
    morceaux = re.split(r"(['’\-])", mot.lower())
    return "".join(m[:1].upper() + m[1:] if m not in ("'", "’", "-") else m for m in morceaux)


def _est_capitales(mot: str) -> bool:
    lettres = [c for c in mot if c.isalpha()]
    return len(lettres) >= 2 and all(c.isupper() for c in lettres)


def _propres(mots: list[str]) -> list[str]:
    """Retire la ponctuation autour des mots ; garde le point d'une initiale (« A. »)."""
    propres = []
    for mot in mots:
        mot = mot.strip(" ,;:")
        if mot.endswith(".") and len(mot.rstrip(".")) > 1:
            mot = mot.rstrip(".")
        if mot and mot != ".":
            propres.append(mot)
    return propres


def ordonner(mots: list[str], ordre_par_defaut: str = "prenom_nom") -> tuple[str, str]:
    """(nom, prénom) d'une suite de mots.

    Le mot en CAPITALES est le nom — c'est l'usage des CV et des formulaires
    francophones, et le seul indice qui ne trompe pas. Sans lui, l'ordre par
    défaut : « Prénom Nom » pour un libellé de messagerie ou un en-tête de CV,
    « Nom Prénom » pour un champ « Nom et prénoms ».
    """
    mots = _propres(mots)
    if not mots:
        return "", ""
    if len(mots) == 1:
        return _capitaliser(mots[0]), ""
    capitales = [m for m in mots if _est_capitales(m)]
    if capitales and len(capitales) < len(mots):
        nom = " ".join(_capitaliser(m) for m in capitales)
        prenom = " ".join(_capitaliser(m) if not m.endswith(".") else m for m in mots if m not in capitales)
        return nom, prenom
    if ordre_par_defaut == "nom_prenom":
        return _capitaliser(mots[0]), " ".join(_capitaliser(m) for m in mots[1:])
    # « Prénom Nom » : le dernier mot est le nom, avec ses particules.
    fin = len(mots) - 1
    while fin > 1 and mots[fin - 1].lower() in _PARTICULES:
        fin -= 1
    prenom = " ".join(_capitaliser(m) if not m.endswith(".") else m for m in mots[:fin])
    return " ".join(_capitaliser(m) for m in mots[fin:]), prenom


def _mots_de_personne(texte: str) -> list[str] | None:
    """Les mots d'un libellé s'il ressemble à un nom de personne, sinon None."""
    texte = re.sub(r"\(.*?\)|<.*?>|\[.*?\]|\bvia\b.*$", " ", texte or "", flags=re.IGNORECASE)
    texte = texte.replace('"', " ").replace("’", "'").strip(" ,;'")
    if not texte or "@" in texte or any(c.isdigit() for c in texte):
        return None
    if _plat(texte) in _LIBELLES_NON_PERSONNES:
        return None
    mots = _propres(re.split(r"[\s,]+", texte))
    if not mots or len(mots) > 5:
        return None
    if not all(_MOT.match(m) for m in mots):
        return None
    if any(_plat(m) in _LIBELLES_NON_PERSONNES for m in mots):
        return None
    if len(mots) == 1 and len(mots[0]) < 3:
        return None
    return mots


def est_une_personne(nom: str, prenom: str = "") -> bool:
    """Vrai si « prénom nom » ressemble à une personne — pas à « Yahoo! » ou « Dossier »."""
    mots = _mots_de_personne(f"{prenom} {nom}".strip())
    return bool(mots) and len(mots) >= 2


def depuis_adresse(adresse: str) -> tuple[str, str]:
    """« afi.dossou@… » → (Dossou, Afi) ; « contact@… » → ("", "")."""
    locale = (adresse or "").split("@")[0]
    mots = [m for m in re.split(r"[\s._\-+]+", re.sub(r"\d+", " ", locale)) if len(m) >= 2]
    mots = [m for m in mots if _plat(m) not in _LIBELLES_NON_PERSONNES]
    if not mots:
        return "", ""
    return ordonner(mots, "prenom_nom")


def depuis_entete(libelle: str, adresse: str) -> tuple[str, str]:
    """Le nom tiré de l'en-tête « From » : le libellé s'il est une personne, sinon l'adresse."""
    mots = _mots_de_personne(libelle)
    if mots and len(mots) >= 2:
        return ordonner(mots, "prenom_nom")
    nom, prenom = depuis_adresse(adresse)
    if prenom or (nom and not mots):
        return nom, prenom
    if mots:  # un seul mot plausible, faute de mieux
        return ordonner(mots)
    return nom, prenom


_CHAMP_NOM = re.compile(r"^\s*(?:nom(?:\s+de\s+famille)?|surname|last\s+name)\s*[:：]\s*(.+)$", re.IGNORECASE)
_CHAMP_PRENOM = re.compile(r"^\s*(?:pr[ée]noms?|first\s+names?|given\s+names?)\s*[:：]\s*(.+)$", re.IGNORECASE)
_CHAMP_COMPLET = re.compile(
    r"^\s*(?:nom\s+et\s+pr[ée]noms?|nom\s*&\s*pr[ée]noms?|nom\s+complet|full\s+name|name)\s*[:：]\s*(.+)$",
    re.IGNORECASE,
)
_CHAMP_COMPLET_INVERSE = re.compile(r"^\s*pr[ée]noms?\s+et\s+nom\s*[:：]\s*(.+)$", re.IGNORECASE)


def _champs(lignes: list[str]) -> tuple[str, str] | None:
    """« Nom : DOSSOU » et « Prénoms : Afi Mawuli », ou « Nom et prénoms : … »."""
    nom = prenom = None
    for ligne in lignes:
        if m := _CHAMP_COMPLET.match(ligne):
            mots = _mots_de_personne(m.group(1))
            if mots and len(mots) >= 2:
                return ordonner(mots, "nom_prenom")
        if m := _CHAMP_COMPLET_INVERSE.match(ligne):
            mots = _mots_de_personne(m.group(1))
            if mots and len(mots) >= 2:
                return ordonner(mots, "prenom_nom")
        if nom is None and (m := _CHAMP_NOM.match(ligne)):
            nom = _mots_de_personne(m.group(1))
        elif prenom is None and (m := _CHAMP_PRENOM.match(ligne)):
            prenom = _mots_de_personne(m.group(1))
    if nom and prenom:
        return (
            " ".join(_capitaliser(m) for m in _propres(nom)),
            " ".join(_capitaliser(m) for m in _propres(prenom)),
        )
    return None


def depuis_cv(texte: str, adresse: str = "", libelle: str = "", titre: str | None = None) -> tuple[str, str] | None:
    """Le nom que porte le CV ; None s'il ne se dégage pas."""
    lu = _lire_cv(texte, adresse, libelle, titre)
    return None if lu is None else (lu[0], lu[1])


def _lire_cv(
    texte: str, adresse: str, libelle: str, titre: str | None
) -> tuple[str, str, bool] | None:
    """(nom, prénom, ordre sûr). L'ordre est sûr quand un champ « Nom : » ou un
    NOM en capitales le dit ; sinon il est supposé « Prénom Nom ».

    Inspiré du parseur d'OpenResume : chaque ligne du haut reçoit des points —
    la plus grande police, courte, faite de lettres, avec un NOM en capitales,
    en accord avec l'adresse électronique — et en perd si elle ressemble à une
    rubrique ou à un intitulé de poste.
    """
    lignes = [l.strip() for l in (texte or "").splitlines() if l.strip()]
    champs = _champs(lignes[:80])
    if champs:
        return (*champs, True)

    indices = {i for i in _plat(adresse.split("@")[0]).split() + _plat(libelle).split() if len(i) >= 3}
    titre_plat = _plat(titre or "")
    meilleure: tuple[float, list[str]] | None = None
    # La ligne en plus gros caractères concourt aussi telle quelle : un nom
    # écrit sur deux lignes (« Mawuli » / « GBEDEMAH ») s'y trouve recomposé.
    # Un CV à deux colonnes livre d'abord sa colonne latérale (contact,
    # compétences) : le nom peut venir bien après la 25e ligne.
    candidates = ([titre] if titre and titre.strip() not in lignes[:3] else []) + lignes[:60]
    # Sans la taille des polices (texte relu plus tard, OCR), deux mots seuls
    # en tête, l'un sous l'autre, se recomposent aussi.
    for i in range(min(4, len(lignes) - 1)):
        if len(lignes[i].split()) == 1 and len(lignes[i + 1].split()) == 1:
            candidates.insert(0, f"{lignes[i]} {lignes[i + 1]}")
            break
    for rang, ligne in enumerate(candidates):
        # « CV de Kofi MENSAH », « Curriculum vitae : … »
        ligne = re.sub(r"^\s*(?:cv|curriculum\s+vitae|resume)\s*(?:de|du|of|:|-|–|—)?\s+", "", ligne, flags=re.IGNORECASE)
        # « Afi DOSSOU — afi.dossou@… | +228 … » : le nom est le premier morceau.
        ligne = re.split(r"\s+[—–|•·-]\s+|\s*[|•·]\s*|\s{2,}|\S+@\S+|\+?\d[\d .]{6,}", ligne)[0]
        mots = _propres(re.split(r"[\s,|]+", ligne))
        if not 2 <= len(mots) <= 5:
            continue
        if not all(_MOT.match(m) for m in mots):
            continue
        plats = [_plat(m) for m in mots]
        if any(p in _PAS_UN_NOM or p in _LIBELLES_NON_PERSONNES for p in plats):
            continue
        score = max(0.5, 3.0 - rang * 0.25)
        if titre_plat and _plat(ligne) in titre_plat:
            score += 4
        capitales = [m for m in mots if _est_capitales(m)]
        if capitales and len(capitales) < len(mots):
            score += 3
        elif capitales:
            score += 1.5
        communs = sum(1 for p in plats if len(p) >= 3 and any(p in i or i in p for i in indices))
        score += 2.5 * communs
        if meilleure is None or score > meilleure[0]:
            meilleure = (score, mots)
    if meilleure is None or meilleure[0] < 2.5:
        return None
    mots = meilleure[1]
    capitales = [m for m in mots if _est_capitales(m)]
    return (*ordonner(mots, "prenom_nom"), bool(capitales) and len(capitales) < len(mots))


@dataclass(slots=True)
class Proposition:
    nom: str
    prenom: str
    # Ce qui est dit au relecteur quand le CV et l'en-tête ne s'accordent pas.
    avertissement: str | None = None


def proposer(
    nom_actuel: str,
    prenom_actuel: str,
    texte_cv: str,
    adresse: str = "",
    titre: str | None = None,
) -> Proposition | None:
    """Le nom à retenir au vu du CV, ou None s'il faut garder l'actuel.

    Le CV l'emporte quand le nom actuel n'est pas une personne (« Yahoo! »,
    « Dossier »), quand il partage un mot avec lui (même personne, CV plus
    complet ou mieux ordonné), ou quand il s'accorde avec l'adresse. Sinon, le
    nom actuel est gardé et l'écart signalé : deux noms qui n'ont rien en
    commun, c'est peut-être le CV d'un autre.
    """
    if not adresse:
        # L'adresse écrite dans le CV aide à reconnaître la ligne du nom.
        trouvee = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", texte_cv or "")
        adresse = trouvee.group(0) if trouvee else ""
    lu = _lire_cv(texte_cv, adresse, f"{prenom_actuel} {nom_actuel}", titre)
    if lu is None:
        return None
    nom, prenom, ordre_sur = lu
    mots_lus = set(_plat(f"{nom} {prenom}").split())
    mots_actuels = set(_plat(f"{nom_actuel} {prenom_actuel}").split())
    if mots_lus == mots_actuels and ((nom, prenom) == (nom_actuel, prenom_actuel) or not ordre_sur):
        # Les mêmes mots : on ne change l'ordre que si le CV le dit sûrement.
        return None
    adresse_plate = _plat((adresse or "").split("@")[0]).replace(" ", "")
    accord_adresse = any(len(m) >= 3 and m in adresse_plate for m in mots_lus)
    if not est_une_personne(nom_actuel, prenom_actuel) or mots_lus & mots_actuels or accord_adresse:
        return Proposition(nom, prenom)
    return Proposition(
        nom_actuel,
        prenom_actuel,
        f"Le CV semble au nom de « {prenom} {nom} » — vérifiez qu'il s'agit bien du même candidat.",
    )
