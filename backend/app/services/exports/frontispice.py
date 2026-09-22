"""La page de garde, le sommaire et la numérotation des titres.

Le rapport que Kapi Consult remet ne commence pas à « Introduction ». Relevé
sur « Rapport des entretiens - WAPP 2025 », il commence par :

1. une **page de garde** à l'en-tête du cabinet — la marque, l'objet du mandat
   en capitales, le titre du document, le mois, et au pied les coordonnées du
   cabinet avec la mention « Confidentiel » ;
2. un **sommaire**, table des matières dressée sur les titres du document, avec
   leurs numéros de page ;
3. le corps, dont les titres sont **numérotés** — « I. Démarche », « II.
   Objectifs de la mission », « 3.1. Présélection ». L'introduction, elle, ne
   porte pas de numéro.

Les exports produisaient le corps seul. Un document qui s'ouvre sur
« Introduction » n'est pas celui que le client attend : il lui manque ce par
quoi il reconnaît le cabinet, et ce par quoi on s'y repère.

Ce module ne met rien en page. Il tient ce qui est commun aux quatre formats —
les coordonnées, la marque, la règle de numérotation, la liste des entrées du
sommaire — pour que le DOCX, le PDF, l'ODT et le TXT disent la même chose.
Chacun le dessine ensuite avec ses propres moyens : un champ TOC pour Word, un
`text:table-of-content` pour LibreOffice, une vraie table des matières calculée
en deux passes pour le PDF, une liste simple pour le texte brut.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

# --- l'identité du cabinet ---------------------------------------------------
#
# Relevées sur le papier à en-tête du cabinet, celui qui sert de fond à la
# première page de ses rapports. Elles figurent au pied de la page de garde.

NOM_CABINET = "KAPI CONSULT"

ADRESSE: tuple[str, ...] = (
    "5330 route de Kpalimé, Avénou (Adidogomé) Lomé",
    "08 BP : 8535 Lomé — TOGO",
    "Tél. : +228 251 89 69 — Fax : +228 251 54 93",
    "info@kapiconsult.com — www.kapiconsult.com",
    "RCCM : 2006 B0741",
)

MENTION_CONFIDENTIEL = "Confidentiel"

# Charte : bleu de la marque, or des filets.
BLEU_CLAIR = (0x6B, 0x7F, 0xE8)
BLEU_FONCE = (0x1E, 0x22, 0x99)
OR = (0xB8, 0x89, 0x2A)

_MOIS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def mois_de(quand: datetime) -> str:
    """« Mai 2025 » — la datation employée sur la page de garde du cabinet.

    Le corps du rapport, lui, porte la date complète : la page de garde situe
    la mission, le pied de page situe le document.
    """
    return f"{_MOIS[quand.month - 1].capitalize()} {quand.year}"


@dataclass(frozen=True, slots=True)
class Couverture:
    """Ce qu'il faut savoir pour dresser la première page.

    Rien ici ne se déduit des sections : l'objet du mandat, le commanditaire et
    la référence vivent dans `donnees`, figés au moment de la génération comme
    le reste des chiffres. Un rapport réexporté six mois plus tard doit rendre
    la même page de garde.
    """

    titre: str
    # L'objet du mandat, en capitales au centre de la page — « RECRUTEMENT DE
    # DEUX (2) POSTES POUR … ». C'est lui qui dit de quoi il s'agit ; le titre
    # ne dit que l'étape.
    objet: str = ""
    client: str = ""
    reference: str = ""
    mois: str = ""

    @property
    def objet_affiche(self) -> str:
        return self.objet.upper() if self.objet else ""

    @property
    def titre_document(self) -> str:
        """Le titre, débarrassé du nom du mandat que l'objet dit déjà.

        Un rapport s'intitule « Rapport final de recrutement — Cadres 2026 » :
        c'est ce qu'il faut dans la liste des rapports, où il n'y a rien
        d'autre pour savoir de quel mandat il s'agit. Sur la page de garde,
        l'objet est écrit en capitales juste au-dessus, et le lire deux fois de
        suite fait bafouiller le document.
        """
        titre = self.titre.strip()
        objet = self.objet.strip()
        if not objet or not titre.casefold().endswith(objet.casefold()):
            return titre
        reste = titre[: -len(objet)].rstrip()
        # Le séparateur que la génération pose entre les deux.
        return reste.rstrip("—-–:·").rstrip() or titre


def couverture_par_defaut(titre: str, sous_titre: str, genere_le: datetime) -> Couverture:
    """La page de garde d'un appel qui n'en fournit pas.

    Les exports se rendent aussi depuis un test ou un script, qui n'ont que le
    titre et le sous-titre sous la main. Plutôt que de leur refuser la page de
    garde — et de leur faire produire un document qui ne ressemble pas à celui
    des clients — on la dresse avec ce qu'on a.
    """
    return Couverture(titre=titre, client=sous_titre, mois=mois_de(genere_le))


# --- la numérotation des titres ---------------------------------------------
#
# Le document remis numérote ses sections en chiffres romains et ses
# sous-sections en décimal sous leur section — « III. Méthodologie », puis
# « 3.1. Présélection ». L'introduction fait exception : elle n'en porte pas.
#
# La numérotation se calcule ici, à partir des sections effectivement rendues,
# et non à l'enregistrement. C'est ce qui permet à un rapport dont une section
# est restée vide — donc non rendue — de garder une suite continue plutôt
# qu'un trou à la place du II.

SANS_NUMERO = frozenset({"INTRODUCTION"})

_ROMAINS = (
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
)


def romain(n: int) -> str:
    if n <= 0:
        return ""
    reste, sortie = n, []
    for valeur, signe in _ROMAINS:
        while reste >= valeur:
            sortie.append(signe)
            reste -= valeur
    return "".join(sortie)


@dataclass(frozen=True, slots=True)
class Entree:
    """Une ligne du sommaire, et le titre tel qu'il paraîtra dans le corps."""

    numero: str
    titre: str
    niveau: int

    @property
    def titre_complet(self) -> str:
        return f"{self.numero} {self.titre}" if self.numero else self.titre


def numeroter(sections: list[dict]) -> list[Entree]:
    """Numérote les sections rendues, dans l'ordre.

    `sections` doit déjà être filtrée : une section vide ne paraît pas dans le
    document, elle ne doit donc pas consommer un numéro.
    """
    entrees: list[Entree] = []
    rang_section = 0
    rang_sous_section = 0

    for section in sections:
        titre = str(section.get("titre") or "")
        try:
            niveau = 2 if int(section.get("niveau") or 1) >= 2 else 1
        except (TypeError, ValueError):
            niveau = 1

        if niveau == 2:
            rang_sous_section += 1
            # Sans section porteuse avant elle — un modèle client qui ouvre sur
            # une sous-section — on numérote à plat plutôt que « 0.1 ».
            numero = (
                f"{rang_section}.{rang_sous_section}."
                if rang_section
                else f"{rang_sous_section}."
            )
        elif str(section.get("code") or "").upper() in SANS_NUMERO:
            numero = ""
            rang_sous_section = 0
        else:
            rang_section += 1
            rang_sous_section = 0
            numero = f"{romain(rang_section)}."

        entrees.append(Entree(numero=numero, titre=titre, niveau=niveau))

    return entrees


# --- les pièces de marque du cabinet -----------------------------------------
#
# Elles ne sont pas redessinées : elles sont **extraites des documents que le
# cabinet remet réellement**, et servies telles quelles.
#
# Le logo l'avait d'abord été — une grille de neuf carrés en dégradé, tracée
# pixel par pixel d'après le site. Le vrai logo en compte seize, en damier, et
# porte le mot « Kapi Consult » à côté : le document sortait donc sous une
# marque que le cabinet n'emploie pas. Approcher une identité visuelle ne sert
# à rien quand l'original est disponible.
#
# Ce que l'on embarque, et pourquoi :
#
#   entete_kapi.jpg    le papier à en-tête, page pleine. C'est la première
#                      page des rapports du cabinet : marque, filets,
#                      coordonnées et mention de confidentialité y sont déjà.
#   logo_kapi.png      le logo seul, avec son mot. Sert là où l'en-tête ne va
#                      pas — l'ODT, les formats sans image de fond.
#   bandeau_kapi.png   le bandeau « Nous développons vos métiers », qui court
#                      au pied de chaque page du document remis.
#
# Deux conséquences à connaître. L'en-tête est une image de 210 ppp : elle
# imprime correctement, sans plus, et l'adresse y est figée — si le cabinet
# déménage, c'est ce fichier qu'il faut remplacer, pas une constante. Et le
# bandeau porte la marque d'un partenaire (Profiles International) : si ce
# partenariat cesse, le fichier est à remplacer aussi.

ASSETS = Path(__file__).resolve().parent / "assets"

ENTETE = ASSETS / "entete_kapi.jpg"
LOGO = ASSETS / "logo_kapi.png"
BANDEAU = ASSETS / "bandeau_kapi.png"

# Proportions relevées sur les fichiers, pour dimensionner sans les rouvrir.
PROPORTION_LOGO = 267 / 881       # hauteur / largeur
PROPORTION_BANDEAU = 138 / 1191


@lru_cache(maxsize=8)
def _octets(chemin: Path) -> bytes:
    return chemin.read_bytes()


def logo_png() -> bytes:
    """Le logo du cabinet, avec son mot."""
    return _octets(LOGO)


def entete_jpg() -> bytes:
    """Le papier à en-tête, page pleine."""
    return _octets(ENTETE)


def bandeau_png() -> bytes:
    """Le bandeau de pied de page."""
    return _octets(BANDEAU)


def pieces_presentes() -> bool:
    """Les trois pièces sont-elles là ?

    Un dépôt incomplet ne doit pas faire échouer un export : sans elles, les
    rendus retombent sur une garde composée en texte, moins fidèle mais
    lisible. C'est ce que vérifie cette fonction.
    """
    return all(c.exists() for c in (ENTETE, LOGO, BANDEAU))
