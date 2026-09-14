"""Le rapport de recrutement, rendu dans les formats que les clients demandent.

Quatre sorties depuis un seul contenu : DOCX pour la remise habituelle et pour
que le client puisse reprendre le texte, PDF pour la version qui fait foi, ODT
pour les administrations qui travaillent sous LibreOffice, TXT pour ceux qui
imposent un dépôt en texte brut.

Les sections arrivent déjà rédigées et relues. Ce module ne décide de rien ; il
met en page. C'est délibéré : le fond et la forme se sont séparés au moment où
un client a demandé sa propre trame, et les mélanger de nouveau obligerait à
réécrire la génération pour chaque format imposé.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Charte Kapi Consult : bleu de la marque, or des filets, gris du texte
# secondaire. Les mêmes valeurs que l'interface, pour qu'un rapport imprimé et
# un écran ne se contredisent pas.
BLEU = RGBColor(0x1E, 0x22, 0x99)
OR = RGBColor(0xB8, 0x89, 0x2A)
GRIS = RGBColor(0x6B, 0x70, 0x80)

BLEU_HEX = "#1E2299"
OR_HEX = "#B8892A"
GRIS_HEX = "#6B7080"

# Fonds des lignes remarquables. Assez pâles pour rester lisibles à
# l'impression en noir et blanc, où seule la graisse distinguera les lignes.
FOND_ENTETE = "E8E9F5"
FOND_RUBRIQUE = "F2F2F6"
FOND_TOTAL = "EDEEF8"

GENRE_RUBRIQUE = "rubrique"
GENRE_DETAIL = "detail"
GENRE_TOTAL = "total"


def _entete(titre: str, sous_titre: str, genere_le: datetime) -> list[str]:
    return [
        titre,
        sous_titre,
        f"Kapi Consult — {genere_le.strftime('%d/%m/%Y')}",
    ]


# --- lecture des tableaux structurés ----------------------------------------
#
# Une section calculée porte `tableaux` : colonnes, lignes, et le genre de
# chaque ligne. Un rapport produit avant que cette structure n'existe ne les a
# pas — il retombe alors sur `contenu`, son texte aligné à l'espace. C'est le
# seul cas où les colonnes se décalent, et il ne concerne que les rapports
# déjà en base.


def _tableaux_de(section: dict) -> list[dict]:
    tableaux = section.get("tableaux")
    return [t for t in tableaux if isinstance(t, dict)] if isinstance(tableaux, list) else []


def _colonnes(tableau: dict) -> list[dict]:
    return [c for c in (tableau.get("colonnes") or ()) if isinstance(c, dict)]


def _lignes(tableau: dict) -> list[dict]:
    return [l for l in (tableau.get("lignes") or ()) if isinstance(l, dict)]


def _cellules(ligne: dict, largeur: int) -> list[str]:
    valeurs = [str(c) for c in (ligne.get("cellules") or ())]
    # Une ligne plus courte que l'en-tête ne doit pas faire tomber l'export.
    return (valeurs + [""] * largeur)[:largeur]


def _niveau(section: dict) -> int:
    """1 ou 2. Le rapport remis est hiérarchisé, pas une liste de titres."""
    try:
        niveau = int(section.get("niveau") or 1)
    except (TypeError, ValueError):
        return 1
    return 2 if niveau >= 2 else 1


def _a_rendre(section: dict) -> bool:
    """Une section vide ne paraît pas — sauf si elle porte des sous-sections.

    « Méthodologie » n'a pas de texte à elle. La sauter laisserait
    « Présélection » et « Critères éliminatoires » sans rattachement, au même
    rang que tout le reste.
    """
    return bool(
        str(section.get("contenu") or "").strip()
        or _tableaux_de(section)
        or section.get("porteur")
    )


# La mention qui clôt le rapport du cabinet, sous le tableau des résultats.
NOTE_ANNEXE = (
    "NB : Le détail des notes obtenues par chaque candidat est annexé au "
    "présent rapport."
)


def _note_de_fin(section: dict) -> str:
    """La mention d'annexe, sous le dernier tableau de résultats."""
    return NOTE_ANNEXE if section.get("code") == "RESULTATS_ENTRETIENS" else ""


# --- DOCX -------------------------------------------------------------------


def _ombrer(cellule, fond: str) -> None:
    """Un fond de cellule. python-docx ne l'expose pas : on pose le XML."""
    proprietes = cellule._tc.get_or_add_tcPr()
    ombre = OxmlElement("w:shd")
    ombre.set(qn("w:val"), "clear")
    ombre.set(qn("w:fill"), fond)
    proprietes.append(ombre)


def _ecrire_cellule(
    cellule, texte: str, *, gras: bool, droite: bool, retrait: bool
) -> None:
    paragraphe = cellule.paragraphs[0]
    paragraphe.paragraph_format.space_after = Pt(2)
    paragraphe.paragraph_format.space_before = Pt(2)
    if droite:
        paragraphe.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    if retrait:
        paragraphe.paragraph_format.left_indent = Pt(12)
    run = paragraphe.add_run(texte)
    run.font.size = Pt(9.5)
    run.font.bold = gras


def _table_docx(document, tableau: dict) -> None:
    colonnes = _colonnes(tableau)
    lignes = _lignes(tableau)
    if not colonnes or not lignes:
        return

    table = document.add_table(rows=1, cols=len(colonnes))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    # `autofit` laisse Word répartir les colonnes sur le contenu réel, ce qui
    # évite d'imposer des largeurs qui coupent un intitulé long.
    table.autofit = True

    for index, colonne in enumerate(table.rows[0].cells):
        _ombrer(colonne, FOND_ENTETE)
        _ecrire_cellule(
            colonne,
            str(colonnes[index].get("libelle") or ""),
            gras=True,
            droite=bool(colonnes[index].get("numerique")),
            retrait=False,
        )

    for ligne in lignes:
        genre = str(ligne.get("genre") or "")
        cellules = table.add_row().cells
        for index, valeur in enumerate(_cellules(ligne, len(colonnes))):
            if genre == GENRE_RUBRIQUE:
                _ombrer(cellules[index], FOND_RUBRIQUE)
            elif genre == GENRE_TOTAL:
                _ombrer(cellules[index], FOND_TOTAL)
            _ecrire_cellule(
                cellules[index],
                valeur,
                gras=genre in (GENRE_RUBRIQUE, GENRE_TOTAL),
                droite=bool(colonnes[index].get("numerique")),
                # Le sous-critère se lit sous sa rubrique, pas à côté d'elle.
                retrait=genre == GENRE_DETAIL and index == 0,
            )


def _section_docx(document, section: dict) -> None:
    """Le corps d'une section : sa prose, puis ses tables.

    Dans cet ordre, parce que c'est celui du document remis : une phrase
    annonce le tableau, le tableau suit.
    """
    for paragraphe in str(section.get("contenu") or "").split("\n"):
        if paragraphe.strip():
            document.add_paragraph(paragraphe.strip())

    for tableau in _tableaux_de(section):
        legende = str(tableau.get("titre") or "").strip()
        if legende:
            for ligne in legende.split("\n"):
                paragraphe = document.add_paragraph()
                paragraphe.paragraph_format.space_after = Pt(3)
                run = paragraphe.add_run(ligne)
                run.font.bold = True
                run.font.size = Pt(10)
        _table_docx(document, tableau)
        document.add_paragraph()

    note = _note_de_fin(section)
    if note:
        paragraphe = document.add_paragraph()
        run = paragraphe.add_run(note)
        run.font.size = Pt(9)
        run.font.italic = True
        run.font.color.rgb = GRIS


def rendre_docx(
    titre: str,
    sous_titre: str,
    sections: list[dict],
    genere_le: datetime,
) -> bytes:
    document = Document()

    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(8)

    # Heading 1 = le titre du rapport ; 2 = une section ; 3 = une sous-section.
    for nom, taille in (("Heading 1", 18), ("Heading 2", 13), ("Heading 3", 11.5)):
        style = document.styles[nom]
        style.font.name = "Calibri"
        style.font.size = Pt(taille)
        style.font.color.rgb = BLEU
        style.font.bold = True

    entete = document.add_paragraph()
    entete.alignment = WD_ALIGN_PARAGRAPH.CENTER
    marque = entete.add_run("KAPI CONSULT")
    marque.font.size = Pt(12)
    marque.font.bold = True
    marque.font.color.rgb = OR

    document.add_heading(titre, level=1)
    if sous_titre:
        ligne = document.add_paragraph()
        run = ligne.add_run(sous_titre)
        run.font.size = Pt(12)
        run.font.color.rgb = GRIS

    date = document.add_paragraph()
    run = date.add_run(f"Établi le {genere_le.strftime('%d/%m/%Y')}")
    run.font.size = Pt(9)
    run.font.color.rgb = GRIS

    for section in sections:
        # Une section vide n'est pas rendue : mieux vaut un rapport plus court
        # qu'un titre suivi de blanc, qui se lit comme un oubli. Sauf un titre
        # porteur, dont les sous-sections dépendent.
        if not _a_rendre(section):
            continue
        document.add_heading(
            str(section.get("titre") or ""), level=1 + _niveau(section)
        )
        _section_docx(document, section)

    tampon = io.BytesIO()
    document.save(tampon)
    return tampon.getvalue()


# --- PDF --------------------------------------------------------------------


# A4 moins les marges posées sur le SimpleDocTemplate plus bas.
LARGEUR_UTILE = A4[0] - 40 * mm


def _largeurs(tableau: dict, largeur_totale: float) -> list[float]:
    """Répartit la largeur sur les colonnes, au prorata de leur contenu.

    Bornée : une colonne de notes n'a pas besoin de plus que sa légende, et
    une colonne d'adresses ne doit pas écraser toutes les autres. Le reste se
    replie sur plusieurs lignes, ce que `Paragraph` sait faire dans une cellule.
    """
    colonnes = _colonnes(tableau)
    besoins = []
    for index, colonne in enumerate(colonnes):
        longueurs = [len(str(colonne.get("libelle") or ""))]
        longueurs += [
            len(_cellules(ligne, len(colonnes))[index]) for ligne in _lignes(tableau)
        ]
        besoins.append(max(6, min(46, max(longueurs))))

    total = sum(besoins) or 1
    return [largeur_totale * besoin / total for besoin in besoins]


def _table_pdf(tableau: dict, styles: dict, largeur_totale: float) -> list:
    colonnes = _colonnes(tableau)
    lignes = _lignes(tableau)
    legende = str(tableau.get("titre") or "").strip()

    elements: list = []
    for ligne in legende.split("\n") if legende else []:
        elements.append(Paragraph(escape(ligne), styles["legende"]))
    if not colonnes or not lignes:
        return elements

    def cellule(texte: str, *, style: str) -> Paragraph:
        return Paragraph(escape(texte), styles[style])

    donnees = [
        [
            cellule(
                str(c.get("libelle") or ""),
                style="entete_droite" if c.get("numerique") else "entete",
            )
            for c in colonnes
        ]
    ]
    decorations = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(f"#{FOND_ENTETE}")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9CBD8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]

    for rang, ligne in enumerate(lignes, start=1):
        genre = str(ligne.get("genre") or "")
        gras = genre in (GENRE_RUBRIQUE, GENRE_TOTAL)
        valeurs = _cellules(ligne, len(colonnes))
        rendues = []
        for index, valeur in enumerate(valeurs):
            droite = bool(colonnes[index].get("numerique"))
            if genre == GENRE_DETAIL and index == 0:
                style = "cellule_retrait"
            elif gras:
                style = "cellule_grasse_droite" if droite else "cellule_grasse"
            else:
                style = "cellule_droite" if droite else "cellule"
            rendues.append(cellule(valeur, style=style))
        donnees.append(rendues)

        if genre == GENRE_RUBRIQUE:
            decorations.append(
                ("BACKGROUND", (0, rang), (-1, rang), colors.HexColor(f"#{FOND_RUBRIQUE}"))
            )
        elif genre == GENRE_TOTAL:
            decorations.append(
                ("BACKGROUND", (0, rang), (-1, rang), colors.HexColor(f"#{FOND_TOTAL}"))
            )

    table = Table(
        donnees,
        colWidths=_largeurs(tableau, largeur_totale),
        # L'en-tête se répète en haut de chaque page : un tableau de vingt
        # préqualifiés se lit sur deux pages, et la seconde sans en-tête
        # oblige à revenir en arrière pour savoir quelle colonne est laquelle.
        repeatRows=1,
    )
    table.setStyle(TableStyle(decorations))
    elements.append(table)
    elements.append(Spacer(1, 10))
    # Une légende ne doit pas rester seule en bas de page, séparée de sa table.
    return [KeepTogether(elements)] if len(donnees) <= 12 else elements


def rendre_pdf(
    titre: str,
    sous_titre: str,
    sections: list[dict],
    genere_le: datetime,
) -> bytes:
    base = getSampleStyleSheet()
    styles = {
        "marque": ParagraphStyle(
            "marque",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=OR_HEX,
            spaceAfter=18,
        ),
        "titre": ParagraphStyle(
            "titre",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=BLEU_HEX,
            alignment=0,
            spaceAfter=6,
        ),
        "sous_titre": ParagraphStyle(
            "sous_titre",
            parent=base["Normal"],
            fontSize=11,
            textColor=GRIS_HEX,
            spaceAfter=2,
        ),
        "date": ParagraphStyle(
            "date", parent=base["Normal"], fontSize=8.5, textColor=GRIS_HEX, spaceAfter=20
        ),
        "section": ParagraphStyle(
            "section",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=BLEU_HEX,
            spaceBefore=14,
            spaceAfter=6,
        ),
        "corps": ParagraphStyle(
            "corps", parent=base["BodyText"], fontSize=10.5, leading=15, spaceAfter=6
        ),
        "sous_section": ParagraphStyle(
            "sous_section",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=BLEU_HEX,
            spaceBefore=10,
            spaceAfter=4,
            leftIndent=8,
        ),
        "legende": ParagraphStyle(
            "legende",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.5,
            leading=13,
            spaceBefore=6,
            spaceAfter=4,
        ),
        "note": ParagraphStyle(
            "note",
            parent=base["Normal"],
            fontSize=8.5,
            textColor=GRIS_HEX,
            spaceBefore=2,
            spaceAfter=8,
        ),
    }

    # Les styles de cellule. Passer par `Paragraph` plutôt que par des chaînes
    # nues est ce qui permet à un intitulé long de se replier dans sa colonne
    # au lieu de déborder sur la voisine.
    cellule = ParagraphStyle(
        "cellule", parent=base["Normal"], fontSize=8.5, leading=11
    )
    styles["cellule"] = cellule
    styles["cellule_droite"] = ParagraphStyle(
        "cellule_droite", parent=cellule, alignment=2
    )
    styles["cellule_grasse"] = ParagraphStyle(
        "cellule_grasse", parent=cellule, fontName="Helvetica-Bold"
    )
    styles["cellule_grasse_droite"] = ParagraphStyle(
        "cellule_grasse_droite", parent=styles["cellule_grasse"], alignment=2
    )
    styles["cellule_retrait"] = ParagraphStyle(
        "cellule_retrait", parent=cellule, leftIndent=10
    )
    styles["entete"] = ParagraphStyle(
        "entete", parent=cellule, fontName="Helvetica-Bold", textColor=BLEU_HEX
    )
    styles["entete_droite"] = ParagraphStyle(
        "entete_droite", parent=styles["entete"], alignment=2
    )

    elements: list = [
        Paragraph("KAPI CONSULT", styles["marque"]),
        Paragraph(escape(titre), styles["titre"]),
    ]
    if sous_titre:
        elements.append(Paragraph(escape(sous_titre), styles["sous_titre"]))
    elements.append(
        Paragraph(f"Établi le {genere_le.strftime('%d/%m/%Y')}", styles["date"])
    )

    for section in sections:
        if not _a_rendre(section):
            continue
        elements.append(
            Paragraph(
                escape(str(section.get("titre") or "")),
                styles["sous_section" if _niveau(section) == 2 else "section"],
            )
        )

        for paragraphe in str(section.get("contenu") or "").split("\n"):
            if paragraphe.strip():
                elements.append(Paragraph(escape(paragraphe.strip()), styles["corps"]))

        for tableau in _tableaux_de(section):
            elements.extend(_table_pdf(tableau, styles, LARGEUR_UTILE))

        note = _note_de_fin(section)
        if note:
            elements.append(Paragraph(escape(note), styles["note"]))

    tampon = io.BytesIO()
    document = SimpleDocTemplate(
        tampon,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=titre,
        author="Kapi Consult",
    )
    document.build(elements or [Spacer(1, 1)])
    return tampon.getvalue()


# --- ODT --------------------------------------------------------------------
#
# Écrit à la main plutôt qu'avec une bibliothèque. Un ODT est un zip contenant
# quelques fichiers XML ; le rapport n'a besoin que de titres et de paragraphes,
# ce qui tient en une soixantaine de lignes. Ajouter une dépendance pour cela
# reviendrait à faire porter au déploiement le coût d'un besoin marginal — et
# l'ODT n'est demandé que par certaines administrations.

_STYLES_ODT = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
  xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
  office:version="1.2">
 <office:styles>
  <style:style style:name="Titre" style:family="paragraph">
   <style:text-properties fo:font-size="20pt" fo:font-weight="bold" fo:color="#1E2299"/>
  </style:style>
  <style:style style:name="Section" style:family="paragraph">
   <style:text-properties fo:font-size="13pt" fo:font-weight="bold" fo:color="#1E2299"/>
   <style:paragraph-properties fo:margin-top="0.5cm"/>
  </style:style>
  <style:style style:name="Discret" style:family="paragraph">
   <style:text-properties fo:font-size="9pt" fo:color="#6B7080"/>
  </style:style>
  <style:style style:name="SousSection" style:family="paragraph">
   <style:text-properties fo:font-size="11pt" fo:font-weight="bold" fo:color="#1E2299"/>
   <style:paragraph-properties fo:margin-top="0.35cm" fo:margin-left="0.3cm"/>
  </style:style>
  <style:style style:name="Legende" style:family="paragraph">
   <style:text-properties fo:font-size="10pt" fo:font-weight="bold"/>
   <style:paragraph-properties fo:margin-top="0.3cm" fo:margin-bottom="0.1cm"/>
  </style:style>
  <style:style style:name="Cellule" style:family="paragraph">
   <style:text-properties fo:font-size="9pt"/>
  </style:style>
  <style:style style:name="CelluleD" style:family="paragraph">
   <style:text-properties fo:font-size="9pt"/>
   <style:paragraph-properties fo:text-align="end"/>
  </style:style>
  <style:style style:name="CelluleG" style:family="paragraph">
   <style:text-properties fo:font-size="9pt" fo:font-weight="bold"/>
  </style:style>
  <style:style style:name="CelluleGD" style:family="paragraph">
   <style:text-properties fo:font-size="9pt" fo:font-weight="bold"/>
   <style:paragraph-properties fo:text-align="end"/>
  </style:style>
  <style:style style:name="CelluleR" style:family="paragraph">
   <style:text-properties fo:font-size="9pt"/>
   <style:paragraph-properties fo:margin-left="0.4cm"/>
  </style:style>
  <style:style style:name="Entete" style:family="paragraph">
   <style:text-properties fo:font-size="9pt" fo:font-weight="bold" fo:color="#1E2299"/>
  </style:style>
  <style:style style:name="EnteteD" style:family="paragraph">
   <style:text-properties fo:font-size="9pt" fo:font-weight="bold" fo:color="#1E2299"/>
   <style:paragraph-properties fo:text-align="end"/>
  </style:style>
 </office:styles>
</office:document-styles>
"""

# Styles de cellule : bordure partout, fond selon le genre de la ligne. Ils
# vivent dans les styles automatiques de content.xml, où ODF attend les styles
# propres à un document.
_STYLES_CELLULES_ODT = "".join(
    f'<style:style style:name="C{nom}" style:family="table-cell">'
    f'<style:table-cell-properties fo:border="0.02cm solid #C9CBD8" '
    f'fo:padding="0.08cm"'
    + (f' fo:background-color="#{fond}"' if fond else "")
    + "/></style:style>"
    for nom, fond in (
        ("Std", ""),
        ("Ent", FOND_ENTETE),
        ("Rub", FOND_RUBRIQUE),
        ("Tot", FOND_TOTAL),
    )
)

_MANIFESTE_ODT = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest
  xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
  manifest:version="1.2">
 <manifest:file-entry manifest:full-path="/"
   manifest:media-type="application/vnd.oasis.opendocument.text"/>
 <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
 <manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>
</manifest:manifest>
"""


def _table_odt(tableau: dict, nom: str) -> str:
    colonnes = _colonnes(tableau)
    lignes = _lignes(tableau)
    legende = str(tableau.get("titre") or "").strip()

    morceaux = [
        f'<text:p text:style-name="Legende">{escape(l)}</text:p>'
        for l in (legende.split("\n") if legende else [])
    ]
    if not colonnes or not lignes:
        return "".join(morceaux)

    def cellule(texte: str, style_cellule: str, style_texte: str) -> str:
        return (
            f'<table:table-cell table:style-name="C{style_cellule}" '
            f'office:value-type="string">'
            f'<text:p text:style-name="{style_texte}">{escape(texte)}</text:p>'
            "</table:table-cell>"
        )

    morceaux.append(f'<table:table table:name="{nom}">')
    morceaux.append(
        f'<table:table-column table:number-columns-repeated="{len(colonnes)}"/>'
    )

    morceaux.append("<table:table-header-rows><table:table-row>")
    for colonne in colonnes:
        morceaux.append(
            cellule(
                str(colonne.get("libelle") or ""),
                "Ent",
                "EnteteD" if colonne.get("numerique") else "Entete",
            )
        )
    morceaux.append("</table:table-row></table:table-header-rows>")

    for ligne in lignes:
        genre = str(ligne.get("genre") or "")
        gras = genre in (GENRE_RUBRIQUE, GENRE_TOTAL)
        fond = {GENRE_RUBRIQUE: "Rub", GENRE_TOTAL: "Tot"}.get(genre, "Std")
        morceaux.append("<table:table-row>")
        for index, valeur in enumerate(_cellules(ligne, len(colonnes))):
            droite = bool(colonnes[index].get("numerique"))
            if genre == GENRE_DETAIL and index == 0:
                style_texte = "CelluleR"
            elif gras:
                style_texte = "CelluleGD" if droite else "CelluleG"
            else:
                style_texte = "CelluleD" if droite else "Cellule"
            morceaux.append(cellule(valeur, fond, style_texte))
        morceaux.append("</table:table-row>")

    morceaux.append("</table:table><text:p/>")
    return "".join(morceaux)


def rendre_odt(
    titre: str,
    sous_titre: str,
    sections: list[dict],
    genere_le: datetime,
) -> bytes:
    corps: list[str] = [
        '<text:p text:style-name="Discret">KAPI CONSULT</text:p>',
        f'<text:h text:outline-level="1" text:style-name="Titre">{escape(titre)}</text:h>',
    ]
    if sous_titre:
        corps.append(f"<text:p>{escape(sous_titre)}</text:p>")
    corps.append(
        f'<text:p text:style-name="Discret">Établi le '
        f"{genere_le.strftime('%d/%m/%Y')}</text:p>"
    )

    for index, section in enumerate(sections):
        if not _a_rendre(section):
            continue
        niveau = _niveau(section)
        corps.append(
            f'<text:h text:outline-level="{1 + niveau}" '
            f'text:style-name="{"SousSection" if niveau == 2 else "Section"}">'
            f'{escape(str(section.get("titre") or ""))}</text:h>'
        )
        for paragraphe in str(section.get("contenu") or "").split("\n"):
            if paragraphe.strip():
                corps.append(f"<text:p>{escape(paragraphe.strip())}</text:p>")
        for rang, tableau in enumerate(_tableaux_de(section)):
            corps.append(_table_odt(tableau, f"t{index}_{rang}"))
        note = _note_de_fin(section)
        if note:
            corps.append(f'<text:p text:style-name="Discret">{escape(note)}</text:p>')

    contenu_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<office:document-content"
        ' xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
        ' xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
        ' xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
        ' xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"'
        ' xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"'
        ' office:version="1.2">'
        f"<office:automatic-styles>{_STYLES_CELLULES_ODT}</office:automatic-styles>"
        "<office:body><office:text>" + "".join(corps) + "</office:text></office:body>"
        "</office:document-content>"
    )

    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as archive:
        # Le mimetype doit être la première entrée et rester non compressé :
        # c'est ainsi que les lecteurs reconnaissent le format sans lire le zip.
        archive.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/vnd.oasis.opendocument.text",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr("content.xml", contenu_xml)
        archive.writestr("styles.xml", _STYLES_ODT)
        archive.writestr("META-INF/manifest.xml", _MANIFESTE_ODT)
    return tampon.getvalue()


# --- texte brut -------------------------------------------------------------


def rendre_txt(
    titre: str,
    sous_titre: str,
    sections: list[dict],
    genere_le: datetime,
) -> bytes:
    morceaux = ["KAPI CONSULT", "", titre]
    if sous_titre:
        morceaux.append(sous_titre)
    morceaux += [f"Établi le {genere_le.strftime('%d/%m/%Y')}", ""]
    for section in sections:
        if not _a_rendre(section):
            continue
        titre_section = str(section.get("titre") or "")
        # Une sous-section se distingue par un soulignement plus discret : en
        # texte brut, c'est tout ce dont on dispose pour montrer un rang.
        if _niveau(section) == 2:
            morceaux += [titre_section, "-" * len(titre_section)]
        else:
            morceaux += [titre_section.upper(), "=" * len(titre_section)]
        contenu = str(section.get("contenu") or "").strip()
        if contenu:
            morceaux += [contenu]
        # Les tableaux, alignés à l'espace : ici la chasse est fixe, c'est le
        # bon outil. Un rapport ancien n'a pas ce champ et porte son texte
        # dans `contenu`.
        aligne = str(section.get("tableaux_texte") or "").strip()
        if aligne and aligne != contenu:
            morceaux += ["", aligne] if contenu else [aligne]
        note = _note_de_fin(section)
        if note:
            morceaux += ["", note]
        morceaux.append("")
    return "\n".join(morceaux).encode("utf-8")


FORMATS: dict[str, tuple[str, str]] = {
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
    ),
    "pdf": ("application/pdf", "pdf"),
    "odt": ("application/vnd.oasis.opendocument.text", "odt"),
    "txt": ("text/plain; charset=utf-8", "txt"),
}

_RENDUS = {
    "docx": rendre_docx,
    "pdf": rendre_pdf,
    "odt": rendre_odt,
    "txt": rendre_txt,
}


def rendre(
    format_demande: str,
    titre: str,
    sous_titre: str,
    sections: list[dict],
    genere_le: datetime,
) -> tuple[bytes, str, str]:
    """Rend le rapport. Renvoie (octets, type MIME, extension)."""
    cle = format_demande.lower().lstrip(".")
    if cle not in _RENDUS:
        raise ValueError(
            f"Format inconnu : {format_demande}. Formats disponibles : "
            f"{', '.join(sorted(FORMATS))}."
        )
    mime, extension = FORMATS[cle]
    return _RENDUS[cle](titre, sous_titre, sections, genere_le), mime, extension
