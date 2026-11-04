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

Mais « une page inconnue prolonge la précédente » est trop confiant seul : un
scan sans titre placé après le CV y disparaissait, et deux attestations de deux
pages n'en faisaient qu'une. Chaque page porte donc aussi ses **signes de
continuité** (`SignesDePage`) : la numérotation imprimée, le passage d'un texte
numérique à un scan, le format, la lettre déjà signée, un nouveau titre.

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


@dataclass(frozen=True, slots=True)
class SignesDePage:
    """Ce qu'une page dit de sa place, en dehors de son contenu."""

    # (n, total) quand la page porte « 2/3 » ou « Page 2 sur 3 ».
    numero: tuple[int, int] | None = None
    # Lue par OCR : ce n'était pas du texte numérique.
    scan: bool = False
    format: tuple[int, int] | None = None
    # Assez de lettres pour dire quelque chose. Une page de signature n'en a
    # pas : elle prolonge ce qui précède, quel qu'en soit le support.
    consistante: bool = True
    # Une lettre s'y termine : ce qui suit n'en est plus.
    close: bool = False
    # Un titre de pièce en tête : une nouvelle attestation, un nouveau diplôme.
    titree: bool = False
    # Une rubrique de CV seule sur sa ligne : « Certifications », « Langues ».
    rubrique: bool = False
    # Commence comme un document : titre en capitales, sans date ni rubrique.
    entete: bool = False


_NUMERO = re.compile(
    r"^\W*(?:page|p\.)?\s*(\d{1,2})\s*(?:/|sur|of|de)\s*(\d{1,2})\W*$", re.IGNORECASE
)
_TITRES_DE_PIECE = {
    PieceDossier.ATTESTATIONS_TRAVAIL.value: (
        " attestation de travail ", " certificat de travail ", " attestation d emploi ",
        " attestation de stage ", " certificat de stage ",
    ),
    PieceDossier.COPIE_DIPLOMES.value: (
        " diplome ", " grade de ", " baccalaureat ", " brevet de technicien ", " degree ", " diploma ",
    ),
    PieceDossier.LETTRE_RECOMMANDATION.value: (" recommandation ",),
}
LETTRES = frozenset({PieceDossier.LETTRE_MOTIVATION.value, PieceDossier.LETTRE_RECOMMANDATION.value})
# En dessous, la page n'a rien d'un document : signature, cachet, page blanche.
_LETTRES_D_UNE_PAGE_CONSISTANTE = 80
_FORMULES_DE_FIN = (
    " salutations ", " sentiments distingues ", " ma consideration ", " ma haute consideration ",
    " sincerely ", " yours faithfully ", " respectueusement ",
)
# Écart de format à partir duquel ce n'est plus la même feuille : A4 et Letter
# diffèrent de 6 %, un scan recadré d'un peu moins.
_ECART_DE_FORMAT = 0.12


def numero_de_page(texte: str) -> tuple[int, int] | None:
    """Le « 2/3 » imprimé en haut ou en bas de la page, seul sur sa ligne."""
    lignes = [l for l in (texte or "").splitlines() if l.strip()]
    for ligne in [*lignes[:2], *lignes[-3:]]:
        m = _NUMERO.match(ligne.strip())
        if m:
            n, total = int(m.group(1)), int(m.group(2))
            # « 03/2024 » est une date, écartée par le motif. Une note isolée
            # comme « 12/20 » passerait, mais elle ne ferait suite à rien :
            # `_suite_numerotee` exige le folio précédent, ou un « 2/… ».
            if 1 <= n <= total <= 30:
                return n, total
    return None


def _commence_comme_un_document(texte: str) -> bool:
    from app.services.lecture_locale import plages

    lignes = [l.strip() for l in (texte or "").splitlines() if l.strip()]
    if not lignes:
        return False
    premiere = lignes[0]
    return (
        premiere.isupper()
        and len(premiere.split()) >= 2
        and not any(plages(l) for l in lignes)
    )


def signes_de_page(
    texte: str, type_page: str | None, *, scan: bool = False, format: tuple[int, int] | None = None
) -> SignesDePage:
    lignes_du_haut = [l for l in (texte or "").splitlines() if l.strip()][:8]
    tete = " ".join(_plat(l) for l in lignes_du_haut if len(l.split()) <= 9)
    return SignesDePage(
        numero=numero_de_page(texte),
        scan=scan,
        format=format,
        consistante=sum(c.isalpha() for c in texte or "") >= _LETTRES_D_UNE_PAGE_CONSISTANTE,
        close=_forme_de_lettre(texte) >= 2
        and any(m in _plat(texte) for m in _FORMULES_DE_FIN),
        titree=any(m in tete for m in _TITRES_DE_PIECE.get(type_page or "", ())),
        rubrique=rubriques_de_cv(texte) >= 1,
        entete=_commence_comme_un_document(texte),
    )


def _suite_numerotee(avant: SignesDePage, page: SignesDePage) -> bool:
    """« 2/3 » après « 1/3 », ou après une page sans folio : même document."""
    if page.numero is None or page.numero[0] < 2:
        return False
    if avant.numero is None:
        return page.numero[0] == 2
    return avant.numero == (page.numero[0] - 1, page.numero[1])


def _formats_differents(un: tuple[int, int] | None, autre: tuple[int, int] | None) -> bool:
    if not un or not autre:
        return False
    # Paysage après portrait : un diplôme après un CV.
    if (un[0] > un[1]) != (autre[0] > autre[1]):
        return True
    return any(abs(a - b) / max(a, b, 1) > _ECART_DE_FORMAT for a, b in zip(un, autre))


def _rupture(avant: SignesDePage, page: SignesDePage, type_courant: str | None) -> bool:
    """Une page sans type commence-t-elle autre chose que ce qui précède ?"""
    if type_courant is None or not page.consistante:
        return False
    if type_courant in LETTRES and avant.close:
        return True
    if avant.scan != page.scan or _formats_differents(avant.format, page.format):
        return True
    return type_courant == CV and page.entete and not page.rubrique


def _segments(
    types: list[tuple[str | None, str | None]], signes: list[SignesDePage] | None = None
) -> list[tuple[int, int, str | None, str | None]]:
    """Regroupe les pages consécutives : (début, fin, type, intitulé), pages de 0 à n-1.

    Une première page sans type — page de garde, scan illisible — rejoint la
    pièce qui la suit plutôt que de faire une pièce à elle seule.

    Une page sans type prolonge la pièce en cours, sauf rupture ; un folio qui
    se suit l'y garde quoi qu'elle dise ; deux pièces du même type se séparent
    au titre de la seconde.
    """
    signes = signes or [SignesDePage() for _ in types]
    segments: list[list] = []
    for numero, (type_page, intitule) in enumerate(types):
        page = signes[numero]
        if segments:
            en_cours = segments[-1]
            avant = signes[numero - 1]
            meme = (type_page, intitule) == (en_cours[2], en_cours[3])
            if _suite_numerotee(avant, page):
                en_cours[1] = numero
                continue
            # La dernière page d'un CV qui énumère ses certificats en reste une.
            if en_cours[2] == CV and type_page == AUTRE and page.rubrique:
                en_cours[1] = numero
                continue
            if type_page is None and _rupture(avant, page, en_cours[2]):
                segments.append([numero, numero, None, None])
                continue
            if type_page is None or (meme and not page.titree):
                en_cours[1] = numero
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
        # Un scan glissé au milieu d'une pièce en reste une page, lui aussi.
        if page[2] in (AUTRE, None) and avant[2] is not None and (avant[2], avant[3]) == (apres[2], apres[3]):
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
        signes = [
            signes_de_page(
                page,
                types[numero][0],
                scan=numero in document.pages_ocr,
                format=document.formats[numero] if numero < len(document.formats) else None,
            )
            for numero, page in enumerate(document.pages)
        ]
        segments = _segments(types, signes)
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
