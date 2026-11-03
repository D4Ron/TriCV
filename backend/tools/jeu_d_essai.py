"""Un jeu de dossiers « tordus », fabriqués, pour éprouver la lecture des pièces.

Ce que les candidats envoient vraiment : tout le dossier fusionné en un PDF au
nom quelconque, des diplômes scannés de travers, des photos prises au
téléphone, une lettre nommée « CV.pdf », un libellé d'expéditeur « Yahoo! »,
un PDF protégé, un logo de signature. Chaque cas est fabriqué ici avec sa
réponse attendue, puis passé dans la vraie chaîne de lecture (`decoupage`,
`identite`, `lecture_locale`), sans IA.

**Tout y est inventé** : noms, employeurs, numéros.

    cd backend
    .venv/Scripts/python.exe -m tools.jeu_d_essai          # fabrique et vérifie
    .venv/Scripts/python.exe -m tools.jeu_d_essai --garder # garde les fichiers

Les fichiers vont dans `tools/resultats/jeu_d_essai/` (non versionné) : on
peut les déposer dans l'application pour un essai à la main.
"""

from __future__ import annotations

import io
import random
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageFilter  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import getSampleStyleSheet  # noqa: E402
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer  # noqa: E402

from app.domain.referentiel import PieceDossier as P  # noqa: E402
from app.services import decoupage, extraction, identite, lecture_locale, ocr  # noqa: E402

SORTIE = Path(__file__).parent / "resultats" / "jeu_d_essai"
AUJOURD_HUI = date(2026, 11, 3)
random.seed(7)

_STYLES = getSampleStyleSheet()


# --- fabrication -------------------------------------------------------------


def _paragraphes(texte: str) -> list:
    """Une ligne = un paragraphe ; « # » grossit la ligne (nom, titre)."""
    elements = []
    for ligne in texte.strip("\n").splitlines():
        if ligne.strip() == "<saut>":
            elements.append(PageBreak())
        elif not ligne.strip():
            elements.append(Spacer(1, 8))
        elif ligne.startswith("# "):
            elements.append(Paragraph(ligne[2:], _STYLES["Title"]))
        elif ligne.startswith("## "):
            elements.append(Paragraph(ligne[3:], _STYLES["Heading2"]))
        else:
            echappee = ligne.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            elements.append(Paragraph(echappee, _STYLES["Normal"]))
    return elements


def pdf_texte(texte: str) -> bytes:
    tampon = io.BytesIO()
    SimpleDocTemplate(tampon, pagesize=A4).build(_paragraphes(texte))
    return tampon.getvalue()


def _image_de_page(pdf: bytes, numero: int = 0, dpi: int = 150) -> Image.Image:
    import fitz

    with fitz.open(stream=pdf, filetype="pdf") as doc:
        pix = doc[numero].get_pixmap(dpi=dpi)
        return Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")


def abimer(image: Image.Image, angle: float = 0.0, flou: float = 0.0, bruit: int = 0, contraste: float = 1.0) -> Image.Image:
    """Ce que fait un scanner bon marché ou un téléphone : de travers, flou, grain."""
    if contraste != 1.0:
        image = image.point(lambda v: int(128 + (v - 128) * contraste))
    if angle:
        image = image.rotate(angle, expand=True, fillcolor=255)
    if flou:
        image = image.filter(ImageFilter.GaussianBlur(flou))
    if bruit:
        pixels = image.load()
        for _ in range(image.width * image.height // 60):
            x, y = random.randrange(image.width), random.randrange(image.height)
            pixels[x, y] = max(0, min(255, pixels[x, y] + random.randint(-bruit, bruit)))
    return image


def jpeg(image: Image.Image, qualite: int = 70) -> bytes:
    tampon = io.BytesIO()
    image.convert("RGB").save(tampon, "JPEG", quality=qualite)
    return tampon.getvalue()


def pdf_d_images(images: list[Image.Image]) -> bytes:
    """Un PDF « scanné » : des pages qui ne sont que des images."""
    import fitz

    doc = fitz.open()
    for image in images:
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=jpeg(image, 75))
    return doc.tobytes()


def fusionner(pdfs: list[bytes]) -> bytes:
    import fitz

    cible = fitz.open()
    for pdf in pdfs:
        with fitz.open(stream=pdf, filetype="pdf") as source:
            cible.insert_pdf(source)
    return cible.tobytes()


def scan(texte: str, **abimes) -> bytes:
    return pdf_d_images([abimer(_image_de_page(pdf_texte(texte)), **abimes)])


def docx_avec_entete(entete: str, lignes: list[str], tableau: list[tuple[str, str]]) -> bytes:
    import docx

    document = docx.Document()
    document.sections[0].header.paragraphs[0].text = entete
    for ligne in lignes:
        document.add_paragraph(ligne)
    table = document.add_table(rows=0, cols=2)
    for gauche, droite in tableau:
        cellules = table.add_row().cells
        cellules[0].text, cellules[1].text = gauche, droite
    tampon = io.BytesIO()
    document.save(tampon)
    return tampon.getvalue()


def pdf_protege(texte: str) -> bytes:
    import fitz

    with fitz.open(stream=pdf_texte(texte), filetype="pdf") as doc:
        return doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="secret2")


def logo() -> bytes:
    tampon = io.BytesIO()
    Image.new("RGB", (120, 40), (200, 30, 30)).save(tampon, "PNG")
    return tampon.getvalue()


# --- les textes --------------------------------------------------------------

LETTRE = """
Essi Afi KOUMA
Lomé, le 2 novembre 2026
À l'attention de Madame la Directrice
Objet : candidature au poste de Responsable administratif et financier
Madame,
Titulaire d'une licence en comptabilité et forte de six années d'expérience, je vous adresse ma candidature.
Mon parcours au sein de cabinets d'expertise m'a permis d'acquérir une solide maîtrise de la fiscalité.
Dans l'attente de votre réponse, veuillez agréer, Madame, l'expression de mes salutations distinguées.
Essi Afi KOUMA
"""

CV_KOUMA = """
# KOUMA Essi Afi
Comptable confirmée
essi.kouma92@example.fr | +228 90 11 22 33 | Lomé, Togo
## PROFIL
Comptable avec six ans d'expérience en cabinet et en entreprise.
## EXPÉRIENCES PROFESSIONNELLES
Comptable principale — Société Togolaise de Distribution SA
Lomé — Mars 2022 – à ce jour
• Tenue de la comptabilité générale et analytique de trois filiales.
• Préparation des déclarations fiscales mensuelles.
Assistante comptable — Cabinet Fidex Conseil
Lomé — Janv. 2019 – Févr. 2022
• Saisie des pièces et rapprochements bancaires.
<saut>
## FORMATION
2018 : Licence en Comptabilité et Finance, Université de Lomé
2015 : Baccalauréat série G2, Lycée de Bè
## LANGUES
Français : courant — Anglais : intermédiaire — Éwé : maternelle
## CERTIFICATIONS
SAGE Comptabilité i7 (2020)
"""

DIPLOME_LICENCE = """
RÉPUBLIQUE TOGOLAISE
Travail - Liberté - Patrie
UNIVERSITÉ DE LOMÉ
DIPLÔME DE LICENCE
Vu les procès-verbaux du jury de la session de juillet 2018,
Le grade de Licence est conféré à Mademoiselle KOUMA Essi Afi
Mention : Comptabilité et Finance
Délivré à Lomé, le 15 octobre 2018
Le Recteur
"""

ATTESTATION = """
CABINET FIDEX CONSEIL
ATTESTATION DE TRAVAIL
Je soussigné, Directeur du Cabinet Fidex Conseil, certifie que Mademoiselle KOUMA Essi Afi
a travaillé dans notre cabinet en qualité d'assistante comptable du 7 janvier 2019 au 28 février 2022.
En foi de quoi la présente attestation lui est délivrée pour servir et valoir ce que de droit.
Fait à Lomé, le 1er mars 2022
"""

CNI = """
RÉPUBLIQUE TOGOLAISE
CARTE NATIONALE D'IDENTITÉ
Nom : KOUMA
Prénoms : Essi Afi
Né(e) le : 14/06/1996 à Lomé
Sexe : F    Taille : 1,65 m
Profession : Comptable
"""

CV_CHAMPS = """
CURRICULUM VITAE
ÉTAT CIVIL
Nom : AGBEKO
Prénoms : Kossi Elom
Date de naissance : 03/02/1990
Nationalité : Togolaise
FORMATION ACADÉMIQUE
2014 : Master 2 en Logistique et Transport, Université de Kara
2011 : Licence en Économie, Université de Kara
EXPÉRIENCES PROFESSIONNELLES
Depuis janvier 2021 : Responsable logistique, Port Autonome de Lomé
03/2016 - 12/2020 : Chargé des opérations, Bolloré Transport & Logistics Togo
LANGUES
Français, Anglais
"""

CV_SCANNE = """
ADJOA-MENSAH Yawa
Gestionnaire des ressources humaines
yawa.adjoa@example.tg   Tél. 91 00 00 01
FORMATION
2016 : Master en Gestion des Ressources Humaines, Université de Lomé
EXPÉRIENCE PROFESSIONNELLE
2019 - 2026 : Gestionnaire RH, Ecobank Togo, Lomé
2016 - 2018 : Assistante RH, Groupe Ramco, Lomé
LANGUES
Français, Anglais
"""

CV_DATES_DABORD = """
# Komlan DZIFA
Ingénieur génie civil
komlan.dzifa@example.tg
## EXPERIENCE PROFESSIONNELLE
Depuis janvier 2022
Conducteur de travaux principal
CECO BTP
03/2018 – 06/2021
Ingénieur travaux
EBOMAF Togo
2015-2018
Ingénieur stagiaire
Bureau d'études Technoplan
## FORMATION
2015 : Diplôme d'Ingénieur de conception en Génie Civil, ENSI, Université de Lomé
## LANGUES
Français, Anglais
"""

LETTRE_SEULE = """
Jean-Marc N'GUESSAN
Abidjan, le 30 octobre 2026
Objet : candidature spontanée
Monsieur,
Je me permets de vous adresser ma candidature pour un poste d'auditeur interne.
Veuillez recevoir, Monsieur, mes salutations distinguées.
"""

CV_NGUESSAN = """
N'GUESSAN Kouadio Jean-Marc
Auditeur interne
jm.nguessan@example.com
FORMATION
2012 : Master en Audit et Contrôle de Gestion, Université Félix Houphouët-Boigny
EXPÉRIENCE
Avril 2017 – Present : Auditeur senior, NSIA Banque, Abidjan
Sept 2012 – Mars 2017 : Auditeur junior, KPMG Côte d'Ivoire, Abidjan
LANGUES
Français, Anglais
"""

CV_ANGLAIS = """
# Ama Serwaa BOATENG
Finance Officer
ama.boateng@example.com
## WORK EXPERIENCE
Finance Officer — Ghana Cocoa Board
Accra · Jan 2019 – Present
Accounts Assistant — Kumasi Breweries Ltd
Kumasi · June 2016 – Dec 2018
## EDUCATION
MBA in Finance, University of Ghana · 2018
BSc in Accounting, KNUST · 2015
## LANGUAGES
English, Twi, French
"""

CV_SANS_RUBRIQUES = """
Kodjo Mawuena AFANOU
afanou.kodjo@example.tg
Licence en Sociologie, Université de Lomé, 2017
2018 - 2022 : Animateur communautaire, ONG Plan Togo, Dapaong
Depuis 2023 : Chargé de suivi-évaluation, Projet PASA, Lomé
"""

PASSEPORT = """
RÉPUBLIQUE TOGOLAISE
PASSEPORT / PASSPORT
Type P   Code TGO   N° B0123456
Nom / Surname : BOATENG
Prénoms / Given names : AMA SERWAA
Nationalité / Nationality : TOGOLAISE
Date de naissance : 21 AVR 1993
Date d'expiration : 20 AVR 2031
P<TGOBOATENG<<AMA<SERWAA<<<<<<<<<<<<<<<<<<<
B0123456<8TGO9304214F3104208<<<<<<<<<<<<<<06
"""

CASIER = """
RÉPUBLIQUE TOGOLAISE
MINISTÈRE DE LA JUSTICE
BULLETIN N° 3 DU CASIER JUDICIAIRE
Relevé des condamnations applicables à : DZIFA Komlan
Né le 12/09/1991 à Kpalimé
NÉANT
Délivré à Lomé le 20 octobre 2026
"""

CV_DATES_COMPLETES = """
CV de Kofi MENSAH
kofi.m@example.tg
EXPÉRIENCES
Du 01/03/2019 au 30/06/2021 : Chef comptable, Brasserie BB Lomé
Du 15/09/2015 au 28/02/2019 : Comptable, Cabinet Aurex
FORMATION
Master 1 en Comptabilité, Université de Lomé, 2015
"""

CV_NOM_SUR_DEUX_LIGNES = """
# Mawuli
# GBEDEMAH
Juriste d'affaires
contact : mawuli.g@example.tg
## PARCOURS PROFESSIONNEL
Juriste — Banque Atlantique Togo
Lomé — Févr. 2020 – aujourd'hui
## FORMATION
2019 : Master en Droit des Affaires, Université de Lomé
"""

MASTER = """
RÉPUBLIQUE DU GHANA
UNIVERSITY OF GHANA
MASTER OF BUSINESS ADMINISTRATION
This is to certify that BOATENG Ama Serwaa
having satisfied the requirements was awarded the degree of
Master of Business Administration in Finance
Session of June 2018
"""


# --- les cas -----------------------------------------------------------------


@dataclass
class Cas:
    nom: str
    pieces: list[tuple[str, bytes]]
    libelle: str
    adresse: str
    # Types attendus des pièces, dans l'ordre, après découpage.
    types: list[str]
    nom_attendu: tuple[str, str]
    diplomes: list[tuple[int, int]] = field(default_factory=list)  # (niveau, année)
    experiences: list[tuple[str, str | None]] = field(default_factory=list)  # (début, fin)
    ocr_requis: bool = False


def fabriquer() -> list[Cas]:
    a = _image_de_page
    cas = [
        Cas(
            "fusionne_yahoo",
            [(
                "Dossier.pdf",
                fusionner([
                    pdf_texte(LETTRE),
                    pdf_texte(CV_KOUMA),
                    pdf_d_images([abimer(a(pdf_texte(DIPLOME_LICENCE)), angle=1.5, bruit=40)]),
                    pdf_d_images([abimer(a(pdf_texte(ATTESTATION)), angle=90)]),
                    pdf_d_images([abimer(a(pdf_texte(CNI)), flou=0.6, contraste=0.7)]),
                ]),
            )],
            "Yahoo!", "essi.kouma92@example.fr",
            [P.LETTRE_MOTIVATION, P.CV, P.COPIE_DIPLOMES, P.ATTESTATIONS_TRAVAIL, P.PIECE_IDENTITE],
            ("Kouma", "Essi Afi"),
            [(3, 2018), (0, 2015)],
            [("2022-03", None), ("2019-01", "2022-02")],
            ocr_requis=True,
        ),
        Cas(
            "champs_nom_prenoms",
            [("Mon_CV_final_v2.pdf", pdf_texte(CV_CHAMPS)), ("signature.png", logo())],
            "kossi elom", "kossielom@example.com",
            [P.CV],
            ("Agbeko", "Kossi Elom"),
            [(5, 2014), (3, 2011)],
            [("2021-01", None), ("2016-03", "2020-12")],
        ),
        Cas(
            "cv_entierement_scanne",
            [("scan0001.pdf", scan(CV_SCANNE, angle=-1.2, bruit=35))],
            "Mensah", "yawa.adjoa@example.tg",
            [P.CV],
            ("Adjoa-Mensah", "Yawa"),
            [(5, 2016)],
            [("2019-01", "2026-01"), ("2016-01", "2018-01")],
            ocr_requis=True,
        ),
        Cas(
            "word_nom_dans_l_en_tete",
            [(
                "candidature.docx",
                docx_avec_entete(
                    "Afi Mawuli DOSSOU — afi.dossou@example.tg",
                    ["FORMATION", "2019 : Licence en Gestion des Ressources Humaines, Université de Lomé",
                     "EXPÉRIENCE PROFESSIONNELLE"],
                    [("Depuis 09/2020", "Assistante RH, Groupe Sotici"),
                     ("LANGUES", "Français, Anglais, Éwé")],
                ),
            )],
            "", "a.dossou@example.tg",
            [P.CV],
            ("Dossou", "Afi Mawuli"),
            [(3, 2019)],
            [("2020-09", None)],
        ),
        Cas(
            "photo_de_diplome",
            [("CV Ama BOATENG.pdf", pdf_texte(CV_ANGLAIS)),
             ("IMG_20261102_0912.jpg", jpeg(abimer(a(pdf_texte(MASTER), dpi=170), angle=2.5, contraste=0.75, bruit=30), 60)),
             ("WhatsApp Image 2026-11-02.jpeg", jpeg(abimer(a(pdf_texte(PASSEPORT), dpi=170), angle=-1.0), 65))],
            "Ama Serwaa Boateng", "ama.boateng@example.com",
            [P.CV, P.COPIE_DIPLOMES, P.PASSEPORT],
            ("Boateng", "Ama Serwaa"),
            [(5, 2018), (3, 2015)],
            [("2019-01", None), ("2016-06", "2018-12")],
            ocr_requis=True,
        ),
        Cas(
            "dates_avant_le_poste",
            [("DZIFA.pdf", fusionner([pdf_texte(CV_DATES_DABORD), scan(CASIER, angle=0.8)]))],
            "Komlan Dzifa", "komlan.dzifa@example.tg",
            [P.CV, P.CASIER_JUDICIAIRE],
            ("Dzifa", "Komlan"),
            [(5, 2015)],
            [("2022-01", None), ("2018-03", "2021-06"), ("2015-01", "2018-01")],
            ocr_requis=True,
        ),
        Cas(
            "lettre_nommee_cv",
            [("CV.pdf", pdf_texte(LETTRE_SEULE)), ("document.pdf", pdf_texte(CV_NGUESSAN))],
            "Jean-Marc N'Guessan", "jm.nguessan@example.com",
            [P.LETTRE_MOTIVATION, P.CV],
            ("N'Guessan", "Kouadio Jean-Marc"),
            [(5, 2012)],
            [("2017-04", None), ("2012-09", "2017-03")],
        ),
        Cas(
            "sans_rubriques",
            [("afanou.pdf", pdf_texte(CV_SANS_RUBRIQUES))],
            "AFANOU Kodjo", "afanou.kodjo@example.tg",
            [P.CV],
            ("Afanou", "Kodjo Mawuena"),
            [(3, 2017)],
            [("2018-01", "2022-01"), ("2023-01", None)],
        ),
        Cas(
            "dates_completes_et_cv_de",
            [("Kofi.pdf", pdf_texte(CV_DATES_COMPLETES))],
            "MENSAH Kofi", "kofi.m@example.tg",
            [P.CV],
            ("Mensah", "Kofi"),
            [(4, 2015)],
            [("2019-03", "2021-06"), ("2015-09", "2019-02")],
        ),
        Cas(
            "nom_sur_deux_lignes",
            [("cv.pdf", pdf_texte(CV_NOM_SUR_DEUX_LIGNES))],
            "", "mawuli.g@example.tg",
            [P.CV],
            ("Gbedemah", "Mawuli"),
            [(5, 2019)],
            [("2020-02", None)],
        ),
        Cas(
            "photo_du_cv",
            [("IMG-20261101-WA0004.jpg", jpeg(abimer(a(pdf_texte(CV_NGUESSAN), dpi=170), angle=-2.0, contraste=0.8), 65))],
            "Jean-Marc", "jm.nguessan@example.com",
            [P.CV],
            ("N'Guessan", "Kouadio Jean-Marc"),
            [(5, 2012)],
            [("2017-04", None), ("2012-09", "2017-03")],
            ocr_requis=True,
        ),
        Cas(
            "pdf_protege",
            [("CV_protege.pdf", pdf_protege(CV_CHAMPS))],
            "Kossi Agbeko", "kossi.agbeko@example.tg",
            [P.CV],
            ("Agbeko", "Kossi"),
        ),
    ]
    return cas


# --- vérification ------------------------------------------------------------


def verifier(cas: Cas) -> list[str]:
    ecarts: list[str] = []
    preparees: list[decoupage.PiecePreparee] = []
    for nom, donnees in cas.pieces:
        mime = extraction.piece_retenue(donnees, nom)
        if mime is None:
            continue
        preparees.extend(decoupage.preparer_sync(nom, donnees, mime))
    decoupage.completer_types(preparees)
    types = [p.type_piece for p in preparees]
    attendus = [t.value if hasattr(t, "value") else t for t in cas.types]
    if types != attendus:
        ecarts.append(f"types {types} ≠ {attendus} ({[p.nom for p in preparees]})")

    nom, prenom = identite.depuis_entete(cas.libelle, cas.adresse)
    nom = nom or "Inconnu"
    cv = next((p for p in preparees if p.type_piece == P.CV.value and p.texte), None)
    if cv is not None:
        proposition = identite.proposer(nom, prenom, cv.texte, cas.adresse, cv.titre)
        if proposition is not None and not proposition.avertissement:
            nom, prenom = proposition.nom, proposition.prenom
    if (nom, prenom) != cas.nom_attendu:
        ecarts.append(f"nom ({nom!r}, {prenom!r}) ≠ {cas.nom_attendu}")

    if cv is not None:
        lu = lecture_locale.lire(cv.texte, aujourd_hui=AUJOURD_HUI)
        for piece in preparees:
            if piece.type_piece == P.COPIE_DIPLOMES.value:
                copie = lecture_locale.diplome_d_une_copie(piece.texte, AUJOURD_HUI)
                if copie and not any(d.niveau == copie.niveau for d in lu.diplomes):
                    lu.diplomes.append(copie)
        diplomes = sorted((d.niveau, d.annee) for d in lu.diplomes)
        if cas.diplomes and diplomes != sorted(cas.diplomes):
            ecarts.append(f"diplômes {diplomes} ≠ {sorted(cas.diplomes)}")
        experiences = [(e.debut, e.fin) for e in lu.experiences]
        if cas.experiences and sorted(experiences, key=str) != sorted(cas.experiences, key=str):
            ecarts.append(
                f"expériences {experiences} ≠ {cas.experiences} "
                f"({[(e.poste, e.employeur) for e in lu.experiences]})"
            )
    elif cas.diplomes or cas.experiences:
        ecarts.append("aucun CV lisible")
    return ecarts


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    garder = "--garder" in sys.argv
    if not ocr.disponible():
        print("Tesseract absent : les cas qui demandent l'OCR sont sautés.")
    tous = fabriquer()
    if garder:
        for cas in tous:
            dossier = SORTIE / cas.nom
            dossier.mkdir(parents=True, exist_ok=True)
            for nom, donnees in cas.pieces:
                (dossier / nom).write_bytes(donnees)
        print(f"Fichiers écrits dans {SORTIE}")
    reussis = 0
    for cas in tous:
        if cas.ocr_requis and not ocr.disponible():
            print(f"·  {cas.nom} (sauté)")
            continue
        ecarts = verifier(cas)
        if ecarts:
            print(f"✗  {cas.nom}")
            for ecart in ecarts:
                print(f"     {ecart}")
        else:
            reussis += 1
            print(f"✓  {cas.nom}")
    print(f"\n{reussis}/{len(tous)} cas justes")
    return 0 if reussis == len(tous) else 1


if __name__ == "__main__":
    raise SystemExit(main())
