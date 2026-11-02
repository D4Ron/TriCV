"""Regrouper des fichiers en dossiers de candidature.

Le cas réel : les RH vident une boîte email et se retrouvent avec cent
fichiers. Un candidat en a envoyé quatre — son CV, sa lettre, ses diplômes,
ses attestations. Traiter chaque fichier comme une candidature séparée
produisait quatre dossiers vides à recoller à la main, et une grille où le même
candidat apparaissait quatre fois.

Ce module propose un découpage à partir de ce qu'on a : le nom des fichiers, et
le dossier dont ils viennent quand le dépôt vient d'une arborescence. Deux
signaux, et l'un vaut mieux que l'autre.

**Le chemin l'emporte sur le nom.** Si les fichiers arrivent rangés dans un
sous-dossier par candidat — ce que produit une décompression, ou une sélection
de répertoire — ce classement est celui d'un humain, et il ne se discute pas.

**Le nom n'est qu'un indice.** « KODJO_Amina_CV.pdf » et « CV - Amina Kodjo.pdf »
désignent la même personne, mais rien ne le garantit : deux homonymes existent,
et un fichier nommé « CV.pdf » ne dit rien du tout. C'est pourquoi le découpage
est **proposé**, jamais appliqué d'office : l'interface le montre et le fait
corriger avant d'écrire quoi que ce soit. Un regroupement erroné mélangerait
les pièces de deux personnes, ce qui est bien pire qu'un dossier en trop.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from app.domain.referentiel import PieceDossier

# --- reconnaissance du type de pièce -----------------------------------------
#
# Les mots qu'on trouve réellement dans les noms de fichiers reçus. L'ordre
# compte : « lettre de recommandation » doit être vu avant « lettre », sans quoi
# une recommandation passerait pour une lettre de motivation ; « attestation de
# Master » avant « attestation », qui en ferait une attestation de travail ;
# « attestation de participation » avant « attestation » aussi, qui n'est pas
# une preuve d'emploi.
#
# Relevé en production sur un vrai dossier reçu par courriel : certificat de
# travail, passeport, carte d'identité et certificat de langue étaient tous
# rangés en « CV », faute d'une règle qui les reconnaisse.
_INDICES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        PieceDossier.LETTRE_RECOMMANDATION.value,
        ("recommandation", "recommendation", "reference", "referral"),
    ),
    (
        PieceDossier.LETTRE_MOTIVATION.value,
        ("motivation", "lettre", "lm", "coverletter", "cover letter"),
    ),
    (PieceDossier.CV.value, ("cv", "curriculum", "resume", "vitae")),
    (
        PieceDossier.COPIE_DIPLOMES.value,
        (
            "diplome", "diplomes", "master", "licence", "doctorat", "degree",
            "attestation reussite", "attestation de reussite", "releve de notes",
            "bac", "baccalaureat", "bts", "dut", "maitrise",
        ),
    ),
    # Ni diplôme ni preuve d'emploi : un « autre document », sous son nom.
    (
        f"{PieceDossier.AUTRE.value}:Certificat de langue",
        ("langue", "langues", "toefl", "toeic", "ielts", "delf", "dalf", "tcf", "cambridge"),
    ),
    (
        f"{PieceDossier.AUTRE.value}:Attestation de formation",
        (
            "participation", "formation", "seminaire", "atelier", "webinaire",
            "certification", "certifications",
        ),
    ),
    (
        PieceDossier.ATTESTATIONS_TRAVAIL.value,
        (
            "attestation", "attestations", "certificat travail", "certificat de travail",
            "travail", "stage", "emploi", "experience", "employeur",
        ),
    ),
    (PieceDossier.PASSEPORT.value, ("passeport", "passport")),
    (
        PieceDossier.PIECE_IDENTITE.value,
        ("cni", "carte identite", "carte nationale", "identite", "piece identite"),
    ),
    (
        PieceDossier.CERTIFICAT_NATIONALITE.value,
        ("nationalite", "certificat nationalite"),
    ),
)


def _sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte)
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def _normaliser(texte: str) -> str:
    """Minuscules, sans accents, séparateurs ramenés à l'espace."""
    plat = _sans_accents(texte).lower()
    return re.sub(r"[^a-z0-9]+", " ", plat).strip()


def classer(nom_fichier: str) -> tuple[str | None, str | None]:
    """(type, intitulé) que le nom du fichier laisse penser, ou (None, None).

    L'intitulé n'est rempli que pour un « autre document » — un certificat de
    langue, une attestation de formation —, pour qu'il ne s'affiche pas
    comme un « Autre » muet.
    """
    mots = _normaliser(PurePosixPath(nom_fichier).stem)
    if not mots:
        return None, None
    jetons = set(mots.split())
    for code, indices in _INDICES:
        for indice in indices:
            morceaux = indice.split()
            trouve = indice in mots if len(morceaux) > 1 else morceaux[0] in jetons
            if trouve:
                type_piece, _, intitule = code.partition(":")
                return type_piece, intitule or None
    return None, None


def type_devine(nom_fichier: str) -> str | None:
    """Le type de pièce que le nom du fichier laisse penser, ou None.

    Renvoie None plutôt qu'un défaut : « Dossier_KODJO.pdf » ne dit pas ce
    qu'il contient, et le classer d'office en CV donnerait une complétude
    fausse — un dossier compté complet alors que le CV manque.
    """
    return classer(nom_fichier)[0]


# --- le contenu, quand le nom ne dit rien ------------------------------------

_CV = (
    "curriculum vitae", "experiences professionnelles", "experience professionnelle",
    "parcours professionnel", "competences", "centres d interet", "langues",
    "formation academique", "formations", "references", "profil",
)


def type_par_contenu(texte: str) -> str | None:
    """Le type que le texte d'un document laisse penser, ou None.

    Ne sert que quand le nom du fichier ne dit rien (« scan001.pdf ») : on lit
    le début du document et on y cherche ce qui ne trompe guère — « certifie
    que… a travaillé », la bande d'un passeport, les rubriques d'un CV. Un
    document scanné n'a pas de texte : il reste sans type.
    """
    t = " " + _normaliser(texte[:4000]) + " "
    if len(t.strip()) < 40:
        return None
    if (" passeport " in t or " passport " in t) and (" p " in t or " nationalite " in t):
        return PieceDossier.PASSEPORT.value
    if " carte nationale d identite " in t or " carte d identite " in t:
        return PieceDossier.PIECE_IDENTITE.value
    # « certifie », « certifions », « atteste », « attestons »… : toutes les formes.
    if re.search(r" (certifi|attest)\w* ", t) and any(
        m in t for m in (" travaille ", " stage ", " emploi ", " en qualite de ", " occupe ")
    ):
        return PieceDossier.ATTESTATIONS_TRAVAIL.value
    rubriques = sum(1 for r in _CV if f" {r} " in t)
    if rubriques >= 3:
        return PieceDossier.CV.value
    if (" lettre de motivation " in t or (" objet " in t and " candidature " in t)) and (
        " madame " in t or " monsieur " in t
    ):
        return PieceDossier.LETTRE_MOTIVATION.value
    if (" diplome " in t or " grade de " in t) and any(
        m in t for m in (" universite ", " jury ", " recteur ", " ecole ", " delivre ")
    ):
        return PieceDossier.COPIE_DIPLOMES.value
    if rubriques >= 2:
        return PieceDossier.CV.value
    return None


# Les mots à retirer d'un nom de fichier pour retrouver l'identité qu'il porte.
_BRUIT = frozenset(
    mot
    for _, indices in _INDICES
    for indice in indices
    for mot in indice.split()
) | {
    "dossier",
    "candidature",
    "copie",
    "scan",
    "scanne",
    "signe",
    "final",
    "def",
    "vf",
    "v1",
    "v2",
    "1",
    "2",
    "3",
    "pdf",
    "doc",
    "docx",
    # Les mots de liaison. Sans eux, « lettre_de_motivation » laissait traîner
    # un « de » dans la clé, et « ABALO_Kossi_lettre_de_motivation.pdf » formait
    # un dossier distinct de « ABALO_Kossi_CV.pdf ». Un regroupement raté sépare
    # les pièces d'une même personne — l'erreur la plus coûteuse à réparer, car
    # elle ne se voit qu'en rouvrant les dossiers un à un.
    "de",
    "du",
    "des",
    "le",
    "la",
    "les",
    "et",
    "pour",
    "par",
    "au",
    "aux",
    "sur",
    "of",
    "the",
    "for",
}


def cle_identite(nom_fichier: str) -> str:
    """Ce qui, dans un nom de fichier, ressemble à l'identité du candidat.

    « KODJO_Amina_CV.pdf » et « CV - Amina KODJO.pdf » donnent la même clé : les
    mots sont triés, parce que l'ordre nom/prénom varie d'un envoi à l'autre et
    ne dit rien de plus.

    Chaîne vide quand il ne reste rien — « CV.pdf », « scan001.pdf ». Ces
    fichiers-là ne se regroupent avec personne, et c'est le bon résultat : les
    rattacher au hasard mélangerait des dossiers.
    """
    mots = [m for m in _normaliser(PurePosixPath(nom_fichier).stem).split() if m not in _BRUIT]
    # Un fragment d'une seule lettre est une initiale ou un reste de séparateur.
    mots = [m for m in mots if len(m) > 1]
    return " ".join(sorted(mots))


def libelle_identite(nom_fichier: str) -> str:
    """La même identité, présentée telle qu'elle se lit — pour l'écran."""
    mots = [
        m
        for m in re.split(r"[^0-9A-Za-zÀ-ÿ]+", PurePosixPath(nom_fichier).stem)
        if m and _normaliser(m) not in _BRUIT and len(m) > 1
    ]
    return " ".join(mots).strip()


def separer_identite(libelle: str) -> tuple[str, str]:
    """Sépare « AGBODJAN Komlan » en nom de famille et prénom.

    Le cabinet écrit le patronyme en capitales — c'est la convention de ses
    fichiers comme de ses grilles. Quand une partie est ainsi écrite, elle est
    le nom, quelle que soit sa position : « Komlan AGBODJAN » et
    « AGBODJAN Komlan » désignent le même homme.

    Sans capitales pour trancher, le premier mot est pris pour le nom. C'est
    l'usage local, et l'erreur reste rattrapable : ces valeurs portent la
    provenance EXTRAIT_IA et attendent une relecture.

    Tout dans le nom quand il n'y a qu'un mot : inventer un prénom serait pire
    que de laisser la case vide.
    """
    mots = libelle.split()
    if len(mots) < 2:
        return libelle.strip()[:255], ""

    capitales = [
        i for i, m in enumerate(mots) if m.isupper() and any(c.isalpha() for c in m)
    ]
    # Tout en capitales ne distingue rien : on retombe sur l'ordre.
    if capitales and len(capitales) < len(mots):
        nom = " ".join(mots[i] for i in capitales)
        prenom = " ".join(m for i, m in enumerate(mots) if i not in capitales)
    else:
        nom, prenom = mots[0], " ".join(mots[1:])
    return nom[:255], prenom[:255]


# --- archives ----------------------------------------------------------------
#
# Un ZIP par candidat est une forme courante — « Dossier_KODJO.zip ». Les
# limites ci-dessous ne sont pas décoratives : une archive est une entrée non
# fiable, et une bombe de décompression tient en quelques kilo-octets.

ENTREES_MAX = 40
TAILLE_DECOMPRESSEE_MAX = 200 * 1024 * 1024


class ArchiveRefusee(ValueError):
    """L'archive n'est pas exploitable, et on dit pourquoi."""


@dataclass(slots=True)
class FichierExtrait:
    nom: str
    donnees: bytes
    # Le chemin d'origine dans l'archive, quand il porte un classement.
    dossier: str = ""


def est_archive(nom_fichier: str, donnees: bytes) -> bool:
    return nom_fichier.lower().endswith(".zip") and donnees[:2] == b"PK"


def extraire(nom_archive: str, donnees: bytes) -> list[FichierExtrait]:
    """Le contenu d'un ZIP, bornes de sécurité comprises.

    Les chemins absolus et les « .. » sont écartés : le nom d'une entrée sert
    d'étiquette, jamais de chemin d'écriture, mais une entrée hostile n'a rien à
    faire dans un dossier de candidature.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(donnees))
    except zipfile.BadZipFile as exc:
        raise ArchiveRefusee(f"« {nom_archive} » n'est pas une archive lisible.") from exc

    entrees = [e for e in archive.infolist() if not e.is_dir()]
    if len(entrees) > ENTREES_MAX:
        raise ArchiveRefusee(
            f"« {nom_archive} » contient {len(entrees)} fichiers ; "
            f"{ENTREES_MAX} au plus sont traités."
        )
    total = sum(e.file_size for e in entrees)
    if total > TAILLE_DECOMPRESSEE_MAX:
        raise ArchiveRefusee(
            f"« {nom_archive} » dépasse "
            f"{TAILLE_DECOMPRESSEE_MAX // (1024 * 1024)} Mo une fois décompressée."
        )

    sortie: list[FichierExtrait] = []
    for entree in entrees:
        chemin = PurePosixPath(entree.filename.replace("\\", "/"))
        if chemin.is_absolute() or ".." in chemin.parts:
            continue
        if chemin.name.startswith(".") or "__MACOSX" in chemin.parts:
            continue
        sortie.append(
            FichierExtrait(
                nom=chemin.name,
                donnees=archive.read(entree),
                # Le dossier direct, pas toute l'arborescence : c'est lui qui
                # désigne le candidat quand l'archive en contient plusieurs.
                dossier=chemin.parent.name,
            )
        )
    if not sortie:
        raise ArchiveRefusee(f"« {nom_archive} » ne contient aucun fichier exploitable.")
    return sortie


# --- proposition de découpage ------------------------------------------------


@dataclass(slots=True)
class PieceProposee:
    nom: str
    type_piece: str | None
    # Indice de l'élément dans la liste envoyée, pour que l'interface puisse
    # renvoyer sa correction sans réenvoyer les fichiers.
    index: int


@dataclass(slots=True)
class DossierPropose:
    cle: str
    libelle: str
    pieces: list[PieceProposee] = field(default_factory=list)
    # Vrai quand le découpage vient d'un classement humain — sous-dossiers —
    # et non d'une lecture des noms de fichiers. L'écran le dit, parce que la
    # confiance à accorder n'est pas la même.
    depuis_arborescence: bool = False


def proposer(noms: list[str], chemins: list[str] | None = None) -> list[DossierPropose]:
    """Le découpage proposé pour une liste de fichiers.

    `chemins` porte, quand il existe, le chemin relatif d'origine — celui que
    donne la sélection d'un répertoire, ou l'arborescence d'une archive. Il
    l'emporte sur le nom du fichier : c'est un classement fait par quelqu'un.
    """
    chemins = chemins or [""] * len(noms)
    groupes: dict[str, DossierPropose] = {}

    for index, nom in enumerate(noms):
        chemin = (chemins[index] if index < len(chemins) else "") or ""
        dossier = PurePosixPath(chemin.replace("\\", "/")).parent.name if chemin else ""

        if dossier:
            cle = f"dossier:{_normaliser(dossier)}"
            libelle = dossier
            arborescence = True
        else:
            identite = cle_identite(nom)
            # Sans identité lisible, le fichier reste seul : le rattacher au
            # hasard mélangerait les pièces de deux personnes.
            cle = f"nom:{identite}" if identite else f"seul:{index}"
            libelle = libelle_identite(nom) or PurePosixPath(nom).stem
            arborescence = False

        groupe = groupes.get(cle)
        if groupe is None:
            groupe = DossierPropose(cle=cle, libelle=libelle, depuis_arborescence=arborescence)
            groupes[cle] = groupe
        groupe.pieces.append(
            PieceProposee(nom=nom, type_piece=type_devine(nom), index=index)
        )

    return list(groupes.values())
