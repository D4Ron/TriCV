"""Un seul PDF à imprimer pour tout un poste.

Imprimer les dossiers d'un poste, c'était ouvrir chaque candidat, chaque pièce,
et lancer l'impression fichier par fichier — puis retrier la pile à la main.
Ici, un seul fichier, prêt pour l'imprimante :

- un **sommaire** : rang, nom, note, statut et page de départ de chaque dossier ;
- pour chaque candidat, dans l'ordre du classement, une **fiche** (note ligne
  par ligne, synthèse, points à vérifier) suivie de ses **pièces** telles que
  reçues ;
- un **pied de page** sur chaque feuille — rang, nom, page — pour remettre en
  ordre une pile tombée ;
- en **recto-verso**, chaque dossier commence sur une nouvelle feuille : on
  sépare les dossiers sans couper une page en deux.

Les pièces d'état civil (pièce d'identité, passeport, casier) ne s'impriment
pas par défaut : elles n'aident pas à juger un parcours et ne doivent pas
traîner sur une table de comité.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import fitz

from app.domain.referentiel import PieceDossier as P

A4 = fitz.paper_rect("a4")
MARGE = 48
_ENCRE = (0.12, 0.13, 0.35)
_GRIS = (0.45, 0.45, 0.5)
_ETAT_CIVIL = {
    P.PIECE_IDENTITE.value, P.PASSEPORT.value, P.CERTIFICAT_NATIONALITE.value,
    P.CASIER_JUDICIAIRE.value, P.CERTIFICAT_MEDICAL.value, P.PHOTO.value,
}
_IMAGES = {"image/jpeg": "jpg", "image/png": "png", "image/tiff": "tiff", "image/webp": "webp"}


@dataclass
class PieceAImprimer:
    nom: str
    type_piece: str
    type_mime: str
    donnees: bytes | None  # None : fichier purgé ou introuvable
    texte: str = ""


@dataclass
class DossierAImprimer:
    rang: int
    nom: str
    note: str
    statut: str
    lignes: list[tuple[str, str, str]] = field(default_factory=list)  # libellé, points, correction
    profil: str = ""
    notes: list[str] = field(default_factory=list)
    a_verifier: list[str] = field(default_factory=list)
    pieces: list[PieceAImprimer] = field(default_factory=list)


class _Ecrivain:
    """Écrit des lignes avec retour automatique, page après page."""

    def __init__(self, doc: fitz.Document):
        self.doc = doc
        self.page: fitz.Page | None = None
        self.y = 0.0

    def nouvelle_page(self) -> None:
        self.page = self.doc.new_page(width=A4.width, height=A4.height)
        self.y = MARGE

    def ecrire(self, texte: str, taille: float = 10, gras: bool = False, couleur=(0, 0, 0), avant: float = 0) -> None:
        police = "hebo" if gras else "helv"
        largeur = A4.width - 2 * MARGE
        self.y += avant
        for paragraphe in (texte or "").split("\n"):
            mots, ligne = paragraphe.split(" "), ""
            lignes: list[str] = []
            for mot in mots:
                essai = f"{ligne} {mot}".strip()
                if fitz.get_text_length(_latin(essai), fontname=police, fontsize=taille) > largeur and ligne:
                    lignes.append(ligne)
                    ligne = mot
                else:
                    ligne = essai
            lignes.append(ligne)
            for l in lignes:
                if self.page is None or self.y + taille * 1.4 > A4.height - MARGE:
                    self.nouvelle_page()
                self.page.insert_text((MARGE, self.y + taille), _latin(l), fontname=police, fontsize=taille, color=couleur)
                self.y += taille * 1.4


def _latin(texte: str) -> str:
    """Les polices de base du PDF ne connaissent que l'alphabet latin courant."""
    remplacements = {"’": "'", "‘": "'", "“": '"', "”": '"', "…": "...", "→": "->", "≥": ">="}
    texte = "".join(remplacements.get(c, c) for c in texte)
    return texte.encode("cp1252", "replace").decode("cp1252")


def _fiche(doc: fitz.Document, dossier: DossierAImprimer, poste: str) -> None:
    e = _Ecrivain(doc)
    e.nouvelle_page()
    e.ecrire(poste, 9, couleur=_GRIS)
    e.ecrire(f"{dossier.rang:03d} · {dossier.nom}", 18, gras=True, couleur=_ENCRE, avant=4)
    e.ecrire(f"Note de présélection : {dossier.note}   ·   {dossier.statut}", 11, avant=4)
    if dossier.lignes:
        e.ecrire("Notation", 12, gras=True, couleur=_ENCRE, avant=12)
        for libelle, points, correction in dossier.lignes:
            e.ecrire(f"{libelle} : {points}", 10, avant=2)
            if correction:
                e.ecrire(f"    Corrigé : {correction}", 9, couleur=_GRIS)
    if dossier.profil:
        e.ecrire("En bref", 12, gras=True, couleur=_ENCRE, avant=12)
        e.ecrire(dossier.profil, 10, avant=2)
        for note in dossier.notes:
            e.ecrire(f"• {note}", 9, avant=1)
    if dossier.a_verifier:
        e.ecrire("À vérifier", 12, gras=True, couleur=_ENCRE, avant=12)
        for point in dossier.a_verifier:
            e.ecrire(f"• {point}", 9, avant=1)
    e.ecrire("Pièces", 12, gras=True, couleur=_ENCRE, avant=12)
    for piece in dossier.pieces:
        etat = "" if piece.donnees is not None else " (fichier indisponible)"
        e.ecrire(f"• {piece.nom}{etat}", 9, avant=1)


def _ajouter_piece(doc: fitz.Document, piece: PieceAImprimer) -> None:
    """La pièce telle que reçue ; à défaut, son texte lu."""
    if piece.donnees is not None:
        try:
            if piece.type_mime == "application/pdf":
                with fitz.open(stream=piece.donnees, filetype="pdf") as source:
                    doc.insert_pdf(source)
                return
            if piece.type_mime in _IMAGES:
                with fitz.open(stream=piece.donnees, filetype=_IMAGES[piece.type_mime]) as image:
                    with fitz.open("pdf", image.convert_to_pdf()) as source:
                        doc.insert_pdf(source)
                return
        except Exception:  # noqa: BLE001 - un fichier abîmé ne doit pas arrêter l'impression
            pass
    if piece.texte.strip():
        e = _Ecrivain(doc)
        e.nouvelle_page()
        e.ecrire(piece.nom, 11, gras=True, couleur=_ENCRE)
        e.ecrire(piece.texte, 9, avant=6)


def composer(
    dossiers: list[DossierAImprimer],
    poste: str,
    *,
    avec_pieces: bool = True,
    recto_verso: bool = True,
    avec_etat_civil: bool = False,
) -> bytes:
    corps = fitz.open()
    debuts: list[int] = []
    for dossier in dossiers:
        debut = corps.page_count
        debuts.append(debut)
        _fiche(corps, dossier, poste)
        if avec_pieces:
            for piece in dossier.pieces:
                if piece.type_piece in _ETAT_CIVIL and not avec_etat_civil:
                    continue
                _ajouter_piece(corps, piece)
        fin = corps.page_count
        for numero in range(debut, fin):
            page = corps[numero]
            pied = _latin(f"{dossier.rang:03d} · {dossier.nom} · p. {numero - debut + 1}/{fin - debut}")
            page.insert_text((24, page.rect.height - 14), pied, fontname="helv", fontsize=7, color=_GRIS)
        if recto_verso and (fin - debut) % 2:
            corps.new_page(width=A4.width, height=A4.height)

    # Les numéros de page du sommaire dépendent de sa propre longueur : on
    # l'écrit, on compte ses pages, et on recommence si le compte a changé.
    pages_sommaire = 1
    while True:
        sommaire = _sommaire(dossiers, debuts, poste, pages_sommaire)
        compte = sommaire.page_count + (sommaire.page_count % 2 if recto_verso else 0)
        if compte == pages_sommaire:
            break
        pages_sommaire = compte
    while sommaire.page_count < pages_sommaire:
        sommaire.new_page(width=A4.width, height=A4.height)
    sommaire.insert_pdf(corps)
    return sommaire.tobytes(garbage=3, deflate=True)


def _sommaire(dossiers: list[DossierAImprimer], debuts: list[int], poste: str, decalage: int) -> fitz.Document:
    sommaire = fitz.open()
    e = _Ecrivain(sommaire)
    e.nouvelle_page()
    e.ecrire(poste, 16, gras=True, couleur=_ENCRE)
    e.ecrire(f"{len(dossiers)} dossier(s), dans l'ordre du classement.", 10, couleur=_GRIS, avant=4)
    e.ecrire("", 6)
    for dossier, debut in zip(dossiers, debuts):
        e.ecrire(
            f"{dossier.rang:03d}   {dossier.nom}   ·   {dossier.note}   ·   {dossier.statut}   ·   page {debut + decalage + 1}",
            10,
            avant=2,
        )
    return sommaire
