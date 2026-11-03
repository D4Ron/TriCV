"""Préparer les pièces reçues : lire, découper un PDF fusionné, classer.

Le cas réel qui a tout fait échouer : un candidat fusionne son dossier en un
seul PDF — CV, lettre, diplômes, attestations, pièce d'identité — et le nomme
comme il veut (« Dossier.pdf », « KODJO.pdf », « scan_2026.pdf »). Le fichier
entier devenait « CV », le dossier semblait sans diplôme ni attestation, et la
lecture partait sur un texte où le CV n'occupait que deux pages sur douze.

On fait ici ce que font paperless-ngx et Docspell pour les envois postaux
numérisés en un bloc : **chaque page est classée**, et les pages consécutives
du même type forment une pièce. Une page qui ne ressemble à rien de connu
prolonge la pièce précédente — la deuxième page d'un CV n'a pas de titre.

Ce découpage reste une proposition : chaque pièce garde dans son nom les pages
d'où elle vient, et son type se corrige d'un clic dans le dossier.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.domain.referentiel import PieceDossier
from app.services import extraction, lots

logger = logging.getLogger(__name__)

CV = PieceDossier.CV.value
AUTRE = PieceDossier.AUTRE.value


@dataclass(slots=True)
class PiecePreparee:
    nom: str
    donnees: bytes
    type_mime: str
    # None : rien ne permet de le dire — l'appelant décide (CV par défaut, ou
    # « autre document »).
    type_piece: str | None
    intitule: str | None
    texte: str = ""
    # Pages d'origine (de 1 à n), quand la pièce vient d'un PDF découpé.
    pages: tuple[int, int] | None = None
    titre: str | None = None
    lisible: bool = True


def _plat(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte or "")
    sans = "".join(c for c in decompose if unicodedata.category(c) != "Mn")
    return " " + re.sub(r"[^a-z0-9<]+", " ", sans.lower()).strip() + " "


def rubriques_de_cv(texte: str) -> int:
    """Le nombre de rubriques de CV écrites en titre — seules sur leur ligne.

    C'est la détection de sections d'OpenResume : un titre de rubrique est une
    ligne courte. Compter les mots n'importe où faisait d'une lettre de
    motivation un CV, puisqu'elle parle de « formation » et d'« expérience
    professionnelle ».
    """
    from app.services.lecture_locale import rubrique_de

    vues = {rubrique_de(ligne) for ligne in (texte or "").splitlines()}
    vues.discard(None)
    # « Contact » ou « Profil » seuls ne font pas un CV : une lettre a aussi
    # des coordonnées. Les rubriques de parcours comptent double.
    return len(vues) + len(vues & {"formation", "experience"})


def _forme_de_lettre(texte: str) -> int:
    """Combien des trois marques d'une lettre on trouve : objet, appel, formule."""
    lignes = [_plat(l) for l in (texte or "").splitlines() if l.strip()]
    objet = any(l.startswith((" objet ", " object ", " re ")) for l in lignes)
    appel = any(
        len(l.split()) <= 4 and any(l.startswith(m) for m in (" madame ", " monsieur ", " messieurs ", " dear "))
        for l in lignes
    )
    t = " ".join(lignes)
    formule = any(
        m in t
        for m in (
            " veuillez agreer ", " veuillez recevoir ", " salutations ", " sentiments distingues ",
            " ma consideration ", " sincerely ", " yours faithfully ", " dans l attente ",
        )
    )
    return int(objet) + int(appel) + int(formule)


def type_de_page(texte: str) -> tuple[str | None, str | None]:
    """(type, intitulé) qu'une page laisse penser, ou (None, None).

    Les titres officiels — « carte nationale d'identité », « casier
    judiciaire » — ne comptent qu'en titre : une ligne courte, en haut de la
    page. Une lettre qui énumère « pièces jointes : CV, casier judiciaire,
    certificat de nationalité » n'est ni un casier ni un certificat.
    """
    t = _plat(texte[:5000])
    if len(t.strip()) < 25:
        return None, None
    lignes_du_haut = [l for l in (texte or "").splitlines() if l.strip()][:15]
    tete = " ".join(_plat(l) for l in lignes_du_haut if len(l.split()) <= 9)
    brut = (texte or "")[:5000]

    # Pièces officielles, reconnues à leur titre ou à leur bande lisible.
    if re.search(r"P<[A-Z]{3}", brut.replace(" ", "")) or (
        (" passeport " in tete or " passport " in tete)
        and any(m in t for m in (" nationalite ", " nationality ", " date d expiration ", " date of expiry "))
    ):
        return PieceDossier.PASSEPORT.value, None
    if any(m in tete for m in (" carte nationale d identite ", " carte d identite ", " identity card ", " carte d identite nationale ")):
        return PieceDossier.PIECE_IDENTITE.value, None
    if " certificat de nationalite " in tete:
        return PieceDossier.CERTIFICAT_NATIONALITE.value, None
    if " casier judiciaire " in tete or " bulletin n 3 " in tete:
        return PieceDossier.CASIER_JUDICIAIRE.value, None
    if " certificat medical " in tete or " certificat d aptitude physique " in tete:
        return PieceDossier.CERTIFICAT_MEDICAL.value, None
    if any(m in tete for m in (" acte de naissance ", " extrait d acte de naissance ", " jugement suppletif ")):
        return AUTRE, "Acte de naissance"

    rubriques = rubriques_de_cv(texte)
    if rubriques >= 3 or " curriculum vitae " in tete:
        return CV, None

    lettre = _forme_de_lettre(texte)
    if " recommandation " in tete or (lettre >= 1 and " recommande " in t and " sans reserve " in t):
        return PieceDossier.LETTRE_RECOMMANDATION.value, None
    if " lettre de motivation " in tete or lettre >= 2:
        return PieceDossier.LETTRE_MOTIVATION.value, None

    atteste = re.search(r" (certifi|attest)\w* ", t)
    if " attestation de travail " in tete or " certificat de travail " in tete or " attestation d emploi " in tete:
        return PieceDossier.ATTESTATIONS_TRAVAIL.value, None
    if atteste and any(m in t for m in (" a participe ", " participation ", " seminaire ", " atelier ", " a suivi ", " webinaire ")):
        return AUTRE, "Attestation de formation"
    if (
        atteste
        and any(
            m in t
            for m in (
                " travaille ", " stage ", " emploi ", " en qualite de ", " occupe ", " employe ",
                " a servi ", " exerce ", " fonction de ", " poste de ", " stagiaire ", " a ete nomme ",
                " en tant que ", " ses fonctions ", " contrat de travail ",
            )
        )
    ):
        return PieceDossier.ATTESTATIONS_TRAVAIL.value, None
    if any(m in tete for m in (" toefl ", " ielts ", " toeic ", " delf ", " dalf ", " test of english ")):
        return AUTRE, "Certificat de langue"
    if rubriques >= 2:
        return CV, None
    if any(
        m in tete
        for m in (
            " diplome ", " grade de ", " releve de notes ", " attestation de reussite ", " baccalaureat ",
            " brevet de technicien ", " degree ", " diploma ", " awarded ", " conferred ",
        )
    ) and any(
        m in t
        for m in (
            " universite ", " jury ", " recteur ", " ecole ", " delivre ", " ministere ", " session ",
            " mention ", " institut ", " university ", " college ", " institute ", " school ",
        )
    ):
        return PieceDossier.COPIE_DIPLOMES.value, None
    return None, None


def _segments(types: list[tuple[str | None, str | None]]) -> list[tuple[int, int, str | None, str | None]]:
    """Regroupe les pages consécutives : (début, fin, type, intitulé), pages de 0 à n-1.

    Une première page sans type — page de garde, scan illisible — rejoint la
    pièce qui la suit plutôt que de faire une pièce à elle seule.
    """
    segments: list[list] = []
    for numero, (type_page, intitule) in enumerate(types):
        if segments and (type_page is None or (type_page, intitule) == (segments[-1][2], segments[-1][3])):
            segments[-1][1] = numero
            continue
        if segments and segments[-1][2] is None and len(segments) == 1:
            segments[-1][1:] = [numero, type_page, intitule]
            continue
        segments.append([numero, numero, type_page, intitule])
    # Une page « autre document » prise entre deux pages du même type — la
    # page d'un CV qui énumère ses certificats de langue — en fait partie.
    i = 1
    while i < len(segments) - 1:
        avant, page, apres = segments[i - 1], segments[i], segments[i + 1]
        if page[2] == AUTRE and avant[2] is not None and (avant[2], avant[3]) == (apres[2], apres[3]):
            avant[1] = apres[1]
            del segments[i : i + 2]
            continue
        i += 1
    return [tuple(s) for s in segments]  # type: ignore[misc]


def _extraire_pages(donnees: bytes, debut: int, fin: int) -> bytes:
    import fitz

    with fitz.open(stream=donnees, filetype="pdf") as source, fitz.open() as cible:
        cible.insert_pdf(source, from_page=debut, to_page=fin)
        # Sans date ni identifiant neufs : le même envoi redécoupé donne les
        # mêmes octets, et un dossier renvoyé ne double pas ses pièces.
        cible.set_metadata({})
        return cible.tobytes(garbage=3, deflate=True, no_new_id=True)


def _nom_de_segment(nom: str, debut: int, fin: int) -> str:
    chemin = PurePosixPath(nom)
    pages = f"p. {debut + 1}" if debut == fin else f"p. {debut + 1}-{fin + 1}"
    return f"{chemin.stem} ({pages}){chemin.suffix or '.pdf'}"[:255]


def preparer_sync(nom: str, donnees: bytes, type_mime: str, type_impose: str | None = None) -> list[PiecePreparee]:
    """Lit une pièce reçue et la rend en une ou plusieurs pièces classées."""
    try:
        document = extraction.extract_sync(donnees, type_mime, nom, min_chars=0)
    except extraction.UnreadableDocument as exc:
        logger.info("pièce illisible %s : %s", nom, exc)
        type_nom, intitule = lots.classer(nom)
        return [PiecePreparee(nom, donnees, type_mime, type_impose or type_nom, intitule, lisible=False)]

    type_nom, intitule_nom = lots.classer(nom)
    if type_impose:
        return [PiecePreparee(nom, donnees, type_mime, type_impose, None, document.text, titre=document.titre)]

    if type_mime == extraction.PDF_MIME and len(document.pages) >= 2:
        types = [type_de_page(page) for page in document.pages]
        segments = _segments(types)
        reconnus = {s[2] for s in segments if s[2] is not None}
        if len(segments) >= 2 and reconnus:
            pieces: list[PiecePreparee] = []
            for debut, fin, type_page, intitule in segments:
                texte = "\n\n".join(document.pages[debut : fin + 1])
                # La pièce sans type reconnu garde l'indice du nom de fichier.
                if type_page is None and type_nom and type_nom not in reconnus:
                    type_page, intitule = type_nom, intitule_nom
                pieces.append(
                    PiecePreparee(
                        _nom_de_segment(nom, debut, fin),
                        _extraire_pages(donnees, debut, fin),
                        type_mime,
                        type_page,
                        intitule,
                        texte,
                        (debut + 1, fin + 1),
                        document.titre if debut == 0 else None,
                    )
                )
            return pieces

    type_contenu, intitule_contenu = type_de_page(document.text)
    if type_nom is not None:
        type_piece, intitule = type_nom, intitule_nom
    else:
        type_piece, intitule = type_contenu, intitule_contenu
    # « CV.pdf » qui contient une lettre, ou une pièce d'identité : le contenu
    # l'emporte quand il est net et que le document n'a rien d'un CV.
    if (
        type_nom == CV
        and type_contenu not in (None, CV)
        and rubriques_de_cv(document.text) < 2
    ):
        type_piece, intitule = type_contenu, intitule_contenu
    if type_piece is None and type_mime in extraction.IMAGE_MIME_TYPES:
        lettres = sum(1 for c in document.text if c.isalpha())
        if lettres < 15 and document.pages_ocr == [] and extraction.ocr.disponible():
            # Une image sans texte, une fois lue : une photo d'identité.
            type_piece = PieceDossier.PHOTO.value
    return [PiecePreparee(nom, donnees, type_mime, type_piece, intitule, document.text, titre=document.titre)]


async def preparer(nom: str, donnees: bytes, type_mime: str, type_impose: str | None = None) -> list[PiecePreparee]:
    import asyncio

    return await asyncio.to_thread(preparer_sync, nom, donnees, type_mime, type_impose)


def completer_types(pieces: list[PiecePreparee]) -> None:
    """Donne un type à ce qui n'en a pas.

    Un envoi sans CV reconnu prend sa première pièce restée sans type pour CV —
    c'est presque toujours ce qu'elle est (« scan001.pdf »). Les autres pièces
    inconnues deviennent des « autres documents » sous leur nom. Une image
    n'est jamais prise pour un CV par défaut.
    """
    cv_reconnu = any(p.type_piece == CV for p in pieces)
    for piece in pieces:
        if piece.type_piece is not None:
            continue
        if not cv_reconnu and piece.type_mime not in extraction.IMAGE_MIME_TYPES:
            piece.type_piece, cv_reconnu = CV, True
        else:
            piece.type_piece = AUTRE
            piece.intitule = piece.intitule or PurePosixPath(piece.nom).stem[:255]
