"""Le CV d'un candidat, reconstitué dans une présentation uniforme.

Les clients demandent régulièrement que tous les dossiers proposés leur
arrivent sous la même forme — la leur, ou celle du cabinet. Recopier vingt CV à
la main dans un gabarit Word est le genre de tâche qui se fait mal et prend une
journée.

Ce module reconstruit le CV à partir des **données structurées du dossier** :
diplômes, expériences, langues, certifications. Pas à partir du fichier reçu :
on ne réécrit pas le document du candidat, on présente ce qui en a été relevé et
qui figure déjà dans la grille.

D'où la règle qui gouverne tout le reste : **on ne reconstitue pas un dossier
dont le parcours n'a pas été relu**. Un CV reconstitué a l'autorité du papier à
en-tête du cabinet ; y verser des données qu'une extraction automatique a
proposées et que personne n'a confirmées reviendrait à blanchir une supposition
en pièce officielle. L'appelant qui insiste doit le faire savoir explicitement,
et la mention apparaît alors sur le document.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date, datetime
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.models.enums import Provenance

BLEU = RGBColor(0x1E, 0x22, 0x99)
GRIS = RGBColor(0x6B, 0x70, 0x80)
BLEU_HEX = "#1E2299"
GRIS_HEX = "#6B7080"

MOIS = (
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


class DonneesNonVerifiees(RuntimeError):
    """Le parcours n'a pas été relu : on ne le met pas en forme sans le dire."""


def _periode(debut: date, fin: date | None) -> str:
    """« mars 2019 – aujourd'hui ». Le mois suffit : le jour ne dit rien ici."""
    depart = f"{MOIS[debut.month - 1]} {debut.year}"
    if fin is None:
        return f"{depart} – aujourd'hui"
    return f"{depart} – {MOIS[fin.month - 1]} {fin.year}"


@dataclass(slots=True)
class Section:
    titre: str
    # Chaque entrée : un intitulé fort, puis des lignes de détail.
    entrees: list[tuple[str, list[str]]] = field(default_factory=list)


@dataclass(slots=True)
class FicheCv:
    nom_complet: str
    coordonnees: list[str]
    sections: list[Section]
    # Vrai quand une partie du parcours vient d'une extraction non confirmée.
    non_verifie: bool = False


def construire(candidature, *, avec_coordonnees: bool = True) -> FicheCv:
    """La fiche à mettre en page, tirée du dossier.

    `avec_coordonnees` permet de livrer au client une version sans adresse ni
    téléphone : certains mandats veulent comparer les parcours avant de savoir
    qui est qui, et c'est une demande légitime qu'il vaut mieux servir ici que
    par un caviardage à la main.
    """
    candidat = candidature.candidat

    coordonnees: list[str] = []
    if avec_coordonnees:
        if candidat.email:
            coordonnees.append(candidat.email)
        if candidat.telephone:
            coordonnees.append(candidat.telephone)
        if candidat.adresse:
            coordonnees.append(candidat.adresse)

    sections: list[Section] = []

    experiences = sorted(
        candidat.experiences or (),
        key=lambda e: (e.fin is None, e.debut),
        reverse=True,
    )
    if experiences:
        section = Section("Expérience professionnelle")
        for experience in experiences:
            details = [_periode(experience.debut, experience.fin)]
            if experience.pays:
                details.append(experience.pays)
            if experience.domaines:
                details.append(", ".join(experience.domaines))
            section.entrees.append(
                (f"{experience.poste} — {experience.employeur}", details)
            )
        sections.append(section)

    diplomes = sorted(
        candidat.diplomes or (), key=lambda d: (d.annee or 0, d.niveau), reverse=True
    )
    if diplomes:
        section = Section("Formation")
        for diplome in diplomes:
            details = [f"BAC+{diplome.niveau} · {diplome.domaine}"]
            if diplome.etablissement:
                details.append(diplome.etablissement)
            if diplome.annee:
                details.append(str(diplome.annee))
            section.entrees.append((diplome.intitule, details))
        sections.append(section)

    if candidat.formations_complementaires:
        sections.append(
            Section(
                "Formations complémentaires",
                [(f, []) for f in candidat.formations_complementaires],
            )
        )
    if candidat.certifications:
        sections.append(
            Section("Certifications", [(c, []) for c in candidat.certifications])
        )
    if candidat.langues:
        sections.append(
            Section("Langues", [(", ".join(candidat.langues), [])])
        )

    # Une seule donnée non confirmée suffit à marquer la fiche : c'est le
    # document entier qui devient une proposition, pas la ligne concernée.
    provenances = [candidat.provenance]
    provenances += [d.provenance for d in candidat.diplomes or ()]
    provenances += [e.provenance for e in candidat.experiences or ()]
    non_verifie = any(p is Provenance.EXTRAIT_IA for p in provenances)

    return FicheCv(
        nom_complet=f"{candidat.nom.upper()} {candidat.prenom}".strip(),
        coordonnees=coordonnees,
        sections=sections,
        non_verifie=non_verifie,
    )


def sections_du_modele(structure: dict | None) -> list[str] | None:
    """L'ordre des sections imposé par un client, s'il en a fourni un.

    Une section que le modèle nomme mais dont le dossier n'a rien à dire est
    omise : un titre suivi de blanc se lit comme un oubli du cabinet.
    """
    sections = (structure or {}).get("sections")
    if not isinstance(sections, list) or not sections:
        return None
    return [str(s.get("titre")) for s in sections if isinstance(s, dict) and s.get("titre")]


def _ordonner(fiche: FicheCv, ordre: list[str] | None) -> list[Section]:
    if not ordre:
        return fiche.sections
    par_titre = {s.titre.lower(): s for s in fiche.sections}
    retenues: list[Section] = []
    for titre in ordre:
        section = par_titre.pop(titre.lower(), None)
        if section is not None:
            retenues.append(section)
    # Ce que le modèle n'a pas prévu vient après : mieux vaut une section en
    # trop qu'un parcours amputé parce que le gabarit ne l'attendait pas.
    retenues.extend(par_titre.values())
    return retenues


AVERTISSEMENT = (
    "Document reconstitué à partir de données extraites automatiquement et non "
    "encore confirmées par un relecteur."
)


# --- rendus ------------------------------------------------------------------


def rendre_docx(fiche: FicheCv, ordre: list[str] | None, genere_le: datetime) -> bytes:
    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.paragraph_format.space_after = Pt(4)

    entete = document.add_paragraph()
    entete.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    marque = entete.add_run("KAPI CONSULT")
    marque.font.size = Pt(9)
    marque.font.color.rgb = GRIS

    titre = document.add_paragraph()
    run = titre.add_run(fiche.nom_complet)
    run.font.size = Pt(18)
    run.font.bold = True
    run.font.color.rgb = BLEU

    if fiche.coordonnees:
        ligne = document.add_paragraph()
        run = ligne.add_run(" · ".join(fiche.coordonnees))
        run.font.size = Pt(9.5)
        run.font.color.rgb = GRIS

    if fiche.non_verifie:
        alerte = document.add_paragraph()
        run = alerte.add_run(AVERTISSEMENT)
        run.font.size = Pt(8.5)
        run.font.italic = True
        run.font.color.rgb = GRIS

    for section in _ordonner(fiche, ordre):
        titre_section = document.add_paragraph()
        run = titre_section.add_run(section.titre.upper())
        run.font.size = Pt(11)
        run.font.bold = True
        run.font.color.rgb = BLEU
        titre_section.paragraph_format.space_before = Pt(12)

        for intitule, details in section.entrees:
            ligne = document.add_paragraph()
            run = ligne.add_run(intitule)
            run.font.bold = True
            if details:
                detail = document.add_paragraph()
                run = detail.add_run(" · ".join(details))
                run.font.size = Pt(9.5)
                run.font.color.rgb = GRIS

    pied = document.add_paragraph()
    run = pied.add_run(f"Établi le {genere_le.strftime('%d/%m/%Y')} — Kapi Consult")
    run.font.size = Pt(8)
    run.font.color.rgb = GRIS

    tampon = io.BytesIO()
    document.save(tampon)
    return tampon.getvalue()


def rendre_pdf(fiche: FicheCv, ordre: list[str] | None, genere_le: datetime) -> bytes:
    base = getSampleStyleSheet()
    styles = {
        "marque": ParagraphStyle(
            "marque", parent=base["Normal"], fontSize=8, textColor=GRIS_HEX, alignment=2
        ),
        "nom": ParagraphStyle(
            "nom",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=BLEU_HEX,
            alignment=0,
            spaceAfter=2,
        ),
        "coord": ParagraphStyle(
            "coord", parent=base["Normal"], fontSize=9.5, textColor=GRIS_HEX, spaceAfter=4
        ),
        "alerte": ParagraphStyle(
            "alerte",
            parent=base["Normal"],
            fontSize=8.5,
            textColor=GRIS_HEX,
            spaceAfter=10,
        ),
        "section": ParagraphStyle(
            "section",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=BLEU_HEX,
            spaceBefore=12,
            spaceAfter=4,
        ),
        "entree": ParagraphStyle(
            "entree", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=10.5
        ),
        "detail": ParagraphStyle(
            "detail", parent=base["BodyText"], fontSize=9.5, textColor=GRIS_HEX, spaceAfter=4
        ),
        "pied": ParagraphStyle(
            "pied", parent=base["Normal"], fontSize=8, textColor=GRIS_HEX, spaceBefore=18
        ),
    }

    elements: list = [
        Paragraph("KAPI CONSULT", styles["marque"]),
        Paragraph(escape(fiche.nom_complet), styles["nom"]),
    ]
    if fiche.coordonnees:
        elements.append(
            Paragraph(escape(" · ".join(fiche.coordonnees)), styles["coord"])
        )
    if fiche.non_verifie:
        elements.append(Paragraph(escape(AVERTISSEMENT), styles["alerte"]))

    for section in _ordonner(fiche, ordre):
        elements.append(Paragraph(escape(section.titre.upper()), styles["section"]))
        for intitule, details in section.entrees:
            elements.append(Paragraph(escape(intitule), styles["entree"]))
            if details:
                elements.append(
                    Paragraph(escape(" · ".join(details)), styles["detail"])
                )

    elements.append(
        Paragraph(
            f"Établi le {genere_le.strftime('%d/%m/%Y')} — Kapi Consult", styles["pied"]
        )
    )

    tampon = io.BytesIO()
    SimpleDocTemplate(
        tampon,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"CV — {fiche.nom_complet}",
        author="Kapi Consult",
    ).build(elements or [Spacer(1, 1)])
    return tampon.getvalue()


def rendre_txt(fiche: FicheCv, ordre: list[str] | None, genere_le: datetime) -> bytes:
    morceaux = [fiche.nom_complet]
    if fiche.coordonnees:
        morceaux.append(" · ".join(fiche.coordonnees))
    if fiche.non_verifie:
        morceaux += ["", AVERTISSEMENT]
    for section in _ordonner(fiche, ordre):
        morceaux += ["", section.titre.upper(), "-" * len(section.titre)]
        for intitule, details in section.entrees:
            morceaux.append(intitule)
            if details:
                morceaux.append("    " + " · ".join(details))
    morceaux += ["", f"Établi le {genere_le.strftime('%d/%m/%Y')} — Kapi Consult"]
    return "\n".join(morceaux).encode("utf-8")


FORMATS: dict[str, tuple[str, str]] = {
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
    ),
    "pdf": ("application/pdf", "pdf"),
    "txt": ("text/plain; charset=utf-8", "txt"),
}

_RENDUS = {"docx": rendre_docx, "pdf": rendre_pdf, "txt": rendre_txt}


def rendre(
    format_demande: str,
    fiche: FicheCv,
    ordre: list[str] | None = None,
    genere_le: datetime | None = None,
) -> tuple[bytes, str, str]:
    """Rend le CV. Renvoie (octets, type MIME, extension)."""
    cle = format_demande.lower().lstrip(".")
    if cle not in _RENDUS:
        raise ValueError(
            f"Format inconnu : {format_demande}. Formats disponibles : "
            f"{', '.join(sorted(FORMATS))}."
        )
    mime, extension = FORMATS[cle]
    return (
        _RENDUS[cle](fiche, ordre, genere_le or datetime.now()),
        mime,
        extension,
    )


def nom_fichier(fiche: FicheCv, extension: str) -> str:
    base = "".join(
        c if c.isalnum() or c in " -_" else "_" for c in fiche.nom_complet
    ).strip()
    return f"CV - {base or 'candidat'}.{extension}"
