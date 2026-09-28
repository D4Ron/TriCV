"""La grille de sélection d'un poste, et ce que l'assistance peut y proposer.

La grille est la forme lisible du barème : les mêmes 3 / 7 / 5 / 15 points,
décomposés en sous-critères numérotés, chacun avec ses points, les seuils
éliminatoires signalés comme tels. C'est le tableau que le cabinet joint à ses
rapports et fait valider par le client (« Grille de notation — Assistant(e)
administratif(ve) »).

Elle est **dérivée** du barème et des exigences du poste, jamais saisie à
part : une grille écrite à la main et un barème réglé ailleurs finissent par
diverger, et c'est le barème qui note. Ce qui s'affiche ici est donc
exactement ce que la présélection applique.

L'assistance intervient à deux endroits, toujours en proposition :

- la **courbe** du barème (points au seuil, par année ou par niveau
  supplémentaire, certifications, formation complémentaire), à partir de la
  fiche de poste — les maxima 3 / 7 / 5 / 15 ne se discutent pas ;
- la **formation complémentaire souhaitée**, quand la fiche en laisse deviner
  une sans la nommer dans un champ.

Rien n'est enregistré par ce module : l'écran montre la proposition, et c'est
l'utilisateur qui l'applique.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, replace

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

from app.domain.bareme import Bareme, BaremeExperience, BaremeFormation
from app.domain.referentiel import NiveauDiplome
from app.llm.factory import get_provider
from app.models import Poste
from app.services.preselection import construire_bareme, construire_exigences

logger = logging.getLogger(__name__)

LONGUEUR_FICHE_MAX = 12000
ELIMINATOIRE = "Critère éliminatoire"


@dataclass(frozen=True, slots=True)
class LigneGrille:
    numero: str
    libelle: str
    points: float
    # 1 = rubrique (Formation académique), 2 = sous-rubrique (Expérience
    # générale), 3 = critère noté.
    niveau: int
    eliminatoire: bool = False

    def vers_dict(self) -> dict:
        return {
            "numero": self.numero,
            "libelle": self.libelle,
            "points": self.points,
            "niveau": self.niveau,
            "eliminatoire": self.eliminatoire,
        }


def _pts(valeur: float) -> str:
    """0,25 point ; 1 point ; 1,5 points — la forme des grilles remises."""
    texte = f"{round(valeur, 2):g}".replace(".", ",")
    return f"{texte} point" + ("s" if valeur >= 2 else "")


def _annees(n: int) -> str:
    return f"{n:02d}" if n < 10 else str(n)


def _liste(valeurs) -> str:
    valeurs = [v for v in valeurs if v]
    if not valeurs:
        return ""
    if len(valeurs) == 1:
        return valeurs[0]
    return ", ".join(valeurs[:-1]) + " ou " + valeurs[-1]


def _lignes_experience(
    numero: str,
    nature: str,
    annees_min: int,
    domaines: str,
    bareme: BaremeExperience,
    eliminatoire: bool,
) -> list[LigneGrille]:
    dans = f" dans {domaines}" if domaines else ""
    lignes: list[LigneGrille] = []
    if annees_min:
        lignes.append(
            LigneGrille(
                f"{numero}.1",
                f"Au moins {_annees(annees_min)} année(s) d'expérience {nature}{dans}",
                bareme.points_au_seuil,
                3,
                eliminatoire,
            )
        )
    else:
        lignes.append(
            LigneGrille(f"{numero}.1", f"Expérience {nature}{dans}", bareme.points_au_seuil, 3)
        )
    if bareme.points_par_annee_supplementaire:
        plafond = ""
        if bareme.annees_supplementaires_max is not None:
            plafond = f", dans la limite de {bareme.annees_supplementaires_max} an(s)"
        lignes.append(
            LigneGrille(
                f"{numero}.2",
                f"Au-delà : {_pts(bareme.points_par_annee_supplementaire)} par année "
                f"supplémentaire{plafond}, maximum {_pts(bareme.points_max)} au total",
                round(bareme.points_max - bareme.points_au_seuil, 2),
                3,
            )
        )
    return lignes


def lignes(poste: Poste, bareme: Bareme | None = None) -> list[LigneGrille]:
    """La grille détaillée, dans l'ordre et avec la numérotation du cabinet."""
    bareme = bareme or construire_bareme(poste)
    exigences = construire_exigences(poste)
    c, f = bareme.consistance, bareme.formation
    eg, es = bareme.experience_generale, bareme.experience_specifique

    grille = [
        LigneGrille("1", "Consistance du dossier (CD)", c.points_max, 1),
        LigneGrille("1.1", "Présence des différentes pièces demandées", c.points_dossier_complet, 3),
        LigneGrille(
            "1.2", "Cohérence du dossier (parcours, dates, pièces)", c.points_coherence, 3
        ),
        LigneGrille(
            "1.3", "Présentation et pertinence de la motivation du candidat",
            c.points_appreciation, 3,
        ),
        LigneGrille("2", "Formation académique (FA)", f.points_max, 1),
    ]

    niveau = NiveauDiplome(poste.niveau_min)
    domaines = _liste(sorted(exigences.domaines_acceptes))
    en = f" en {domaines}" if domaines else ""
    rang = 1
    grille.append(
        LigneGrille(
            f"2.{rang}",
            f"Diplôme de niveau {niveau.libelle} minimum{en} ou équivalent",
            f.points_niveau_requis,
            3,
            True,
        )
    )
    if f.points_par_niveau_superieur:
        rang += 1
        grille.append(
            LigneGrille(
                f"2.{rang}",
                f"Diplôme de niveau supérieur au {niveau.libelle} : "
                f"{_pts(f.points_par_niveau_superieur)} par niveau",
                round(f.points_max - f.points_niveau_requis, 2),
                3,
            )
        )
    if f.points_par_certification:
        rang += 1
        grille.append(
            LigneGrille(
                f"2.{rang}",
                "Certification professionnelle pertinente : "
                f"{_pts(f.points_par_certification)} par certification, "
                f"{f.certifications_max} au plus",
                round(f.points_par_certification * f.certifications_max, 2),
                3,
            )
        )
    if f.points_formation_complementaire and exigences.formation_complementaire:
        rang += 1
        grille.append(
            LigneGrille(
                f"2.{rang}",
                f"Formation complémentaire en {exigences.formation_complementaire}",
                f.points_formation_complementaire,
                3,
            )
        )

    grille.append(LigneGrille("3", "Expérience du candidat", eg.points_max + es.points_max, 1))
    grille.append(LigneGrille("3.1", "Expérience générale (EG)", eg.points_max, 2))
    grille += _lignes_experience(
        "3.1", "professionnelle générale", exigences.annees_experience_min, "", eg,
        bool(exigences.annees_experience_min),
    )

    grille.append(LigneGrille("3.2", "Expérience spécifique (ES)", es.points_max, 2))
    specifiques = exigences.specifiques
    poids = [e.poids if e.poids > 0 else 1.0 for e in specifiques]
    somme = sum(poids) or 1.0
    for index, (exigence, sien) in enumerate(zip(specifiques, poids), start=1):
        part = sien / somme
        echelle = replace(
            es,
            points_max=round(es.points_max * part, 2),
            points_au_seuil=round(es.points_au_seuil * part, 2),
            points_par_annee_supplementaire=round(es.points_par_annee_supplementaire * part, 2),
        )
        numero = "3.2" if len(specifiques) == 1 else f"3.2.{index}"
        nom = exigence.nom if (exigence.libelle or exigence.domaines) else ""
        lignes_es = _lignes_experience(
            numero, "spécifique", exigence.annees_min, nom, echelle, bool(exigence.annees_min)
        )
        if len(specifiques) > 1:
            grille.append(LigneGrille(numero, f"Expérience spécifique — {exigence.nom}",
                                      echelle.points_max, 2))
        grille += lignes_es

    if bareme.points_ajouts_max:
        grille.append(LigneGrille("4", "Critères additionnels", bareme.points_ajouts_max, 1))
    return grille


def vers_dict(poste: Poste, bareme: Bareme | None = None) -> dict:
    bareme = bareme or construire_bareme(poste)
    return {
        "intitule": poste.intitule,
        "total": bareme.total_max,
        "lignes": [l.vers_dict() for l in lignes(poste, bareme)],
    }


# --- Word -------------------------------------------------------------------

BLEU = RGBColor(0x1E, 0x22, 0x99)
BORDEAUX = RGBColor(0x8B, 0x1A, 0x1A)


def docx(poste: Poste) -> bytes:
    """La grille en Word, prête à joindre à un rapport ou à faire valider."""
    bareme = construire_bareme(poste)
    document = Document()
    style = document.styles["Normal"]
    style.font.name = "Garamond"
    style.font.size = Pt(11)

    titre = document.add_paragraph()
    run = titre.add_run(f"Grille de notation - {poste.intitule}")
    run.bold = True
    run.font.size = Pt(13)

    table = document.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    entete = table.rows[0].cells
    entete[1].text = "CRITÈRES"
    entete[2].text = "NOTE"
    for cellule in entete:
        for p in cellule.paragraphs:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for r in p.runs:
                r.bold = True

    for ligne in lignes(poste, bareme):
        cellules = table.add_row().cells
        cellules[0].text = ligne.numero
        paragraphe = cellules[1].paragraphs[0]
        texte = paragraphe.add_run(ligne.libelle)
        if ligne.niveau == 1:
            texte.bold = True
            texte.font.color.rgb = BLEU
        elif ligne.niveau == 2:
            texte.bold = True
        if ligne.eliminatoire:
            texte.italic = True
            marque = paragraphe.add_run(f"  {ELIMINATOIRE}")
            marque.bold = True
            marque.font.color.rgb = BORDEAUX
        note = cellules[2].paragraphs[0]
        note.alignment = WD_ALIGN_PARAGRAPH.CENTER
        valeur = note.add_run(f"{round(ligne.points, 2):g}".replace(".", ","))
        valeur.italic = True
        if ligne.niveau < 3:
            valeur.bold = True
            valeur.font.color.rgb = BLEU

    total = table.add_row().cells
    total[1].paragraphs[0].add_run("TOTAL").bold = True
    t = total[2].paragraphs[0]
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run(f"{bareme.total_max:g}")
    r.bold = True
    r.font.color.rgb = BLEU

    tampon = io.BytesIO()
    document.save(tampon)
    return tampon.getvalue()


# --- assistance ---------------------------------------------------------------


def _contexte(poste: Poste) -> str:
    exigences = construire_exigences(poste)
    lignes_ctx = [
        f"Intitulé du poste : {poste.intitule}",
        f"Niveau de diplôme minimum exigé : {NiveauDiplome(poste.niveau_min).libelle}",
    ]
    if exigences.domaines_acceptes:
        lignes_ctx.append(f"Domaines de formation acceptés : {', '.join(sorted(exigences.domaines_acceptes))}")
    lignes_ctx.append(f"Expérience générale minimale : {exigences.annees_experience_min} an(s)")
    for e in exigences.specifiques:
        lignes_ctx.append(f"Expérience spécifique : {e.annees_min} an(s) en {e.nom}")
    if poste.formation_complementaire_souhaitee:
        lignes_ctx.append(f"Formation complémentaire souhaitée : {poste.formation_complementaire_souhaitee}")
    if poste.competences_techniques:
        lignes_ctx.append(f"Compétences techniques : {', '.join(poste.competences_techniques)}")
    if poste.responsabilites:
        lignes_ctx.append("Responsabilités : " + " ; ".join(poste.responsabilites))
    fiche = (poste.fiche_texte or "").strip()
    texte = "\n".join(lignes_ctx)
    if fiche:
        texte += "\n\nFICHE DE POSTE FOURNIE :\n---\n" + fiche[:LONGUEUR_FICHE_MAX] + "\n---"
    return texte


def _nombre(valeur, defaut: float, minimum: float, maximum: float) -> float:
    try:
        nombre = float(valeur)
    except (TypeError, ValueError):
        return defaut
    return round(min(max(nombre, minimum), maximum), 2)


CONSIGNE_BAREME = (
    "Proposez le réglage du barème de présélection de ce poste. Les maxima sont "
    "fixes et ne se discutent pas : formation académique 7 points, expérience "
    "générale 5 points, expérience spécifique 15 points. Vous réglez seulement "
    "la répartition à l'intérieur de chacun :\n"
    "- formation : points au niveau de diplôme exigé (entre 3 et 6), points par "
    "niveau de diplôme au-dessus, points par certification professionnelle "
    "pertinente et nombre maximum de certifications comptées, points pour la "
    "formation complémentaire souhaitée (0 si le poste n'en mentionne aucune). "
    "Les points au-delà du niveau exigé se prennent dans les 7 : leur somme "
    "possible ne doit pas dépasser 7 moins les points au niveau exigé ;\n"
    "- expérience générale et spécifique : points au seuil exigé, points par "
    "année supplémentaire, nombre maximum d'années supplémentaires comptées. "
    "Au seuil, un candidat obtient autour de 60 % du maximum ; le reste "
    "récompense ce qui dépasse l'exigence.\n"
    "Appuyez-vous sur la fiche : un poste qui insiste sur les certifications "
    "leur donne des points, un poste où l'ancienneté compte peu reste sobre.\n"
    "Répondez par un objet JSON de la forme :\n"
    '{"formation": {"points_niveau_requis": 4, "points_par_niveau_superieur": 1, '
    '"points_par_certification": 0.5, "certifications_max": 2, '
    '"points_formation_complementaire": 1}, '
    '"experience_generale": {"points_au_seuil": 3, "points_par_annee_supplementaire": 1, '
    '"annees_supplementaires_max": 2}, '
    '"experience_specifique": {"points_au_seuil": 10, "points_par_annee_supplementaire": 2, '
    '"annees_supplementaires_max": 2}, '
    '"justification": "deux ou trois phrases sur les choix faits"}'
)


def _formation_depuis(proposition: dict, actuelle: BaremeFormation) -> BaremeFormation:
    maxi = actuelle.points_max
    requis = _nombre(proposition.get("points_niveau_requis"), actuelle.points_niveau_requis, 1, maxi)
    reste = round(maxi - requis, 2)
    superieur = _nombre(proposition.get("points_par_niveau_superieur"), 0, 0, reste)
    certification = _nombre(proposition.get("points_par_certification"), 0, 0, reste)
    nombre_certifications = int(_nombre(proposition.get("certifications_max"), 3, 1, 10))
    complementaire = _nombre(proposition.get("points_formation_complementaire"), 0, 0, reste)
    return replace(
        actuelle,
        points_niveau_requis=requis,
        points_par_niveau_superieur=superieur,
        points_par_certification=certification,
        certifications_max=nombre_certifications,
        points_formation_complementaire=complementaire,
    )


def _experience_depuis(proposition: dict, actuelle: BaremeExperience) -> BaremeExperience:
    maxi = actuelle.points_max
    seuil = _nombre(proposition.get("points_au_seuil"), actuelle.points_au_seuil, 0, maxi)
    par_an = _nombre(proposition.get("points_par_annee_supplementaire"), 0, 0, maxi - seuil)
    annees = proposition.get("annees_supplementaires_max")
    return replace(
        actuelle,
        points_au_seuil=seuil,
        points_par_annee_supplementaire=par_an,
        annees_supplementaires_max=(
            None if annees is None else int(_nombre(annees, 0, 0, 40))
        ),
    )


async def suggerer_bareme(poste: Poste) -> tuple[Bareme, str] | None:
    """Une courbe de barème proposée à partir de la fiche. None si indisponible.

    La réponse du modèle est bornée ici, champ par champ : les maxima restent
    ceux du barème en vigueur, et une valeur hors des bornes est ramenée
    dedans plutôt que de rendre le barème invalide.
    """
    actuel = construire_bareme(poste)
    try:
        reponse = await get_provider().repondre_json(CONSIGNE_BAREME, _contexte(poste))
    except Exception:
        logger.exception("proposition de barème indisponible pour le poste %s", poste.id)
        return None
    if not isinstance(reponse, dict) or not reponse.get("formation"):
        return None
    propose = replace(
        actuel,
        formation=_formation_depuis(reponse.get("formation") or {}, actuel.formation),
        experience_generale=_experience_depuis(
            reponse.get("experience_generale") or {}, actuel.experience_generale
        ),
        experience_specifique=_experience_depuis(
            reponse.get("experience_specifique") or {}, actuel.experience_specifique
        ),
    )
    return propose, str(reponse.get("justification") or "").strip()


CONSIGNE_COMPLEMENTAIRE = (
    "À partir de la fiche de poste et des éléments ci-dessous, proposez la ou "
    "les formations complémentaires qu'un avis de recrutement pourrait dire "
    "« souhaitées » pour ce poste : certificats, formations courtes ou "
    "spécialisations qui s'ajoutent au diplôme exigé. Pas le diplôme lui-même.\n"
    "Proposez-en trois au plus, chacune en quelques mots, sous la forme qui "
    "suivrait « Formation complémentaire en … » (par exemple « passation des "
    "marchés publics », « outils bureautiques et rédaction administrative »). "
    "Privilégiez ce que la fiche nomme ou décrit ; n'inventez pas de norme ou de "
    "certification qu'elle ne suggère pas.\n"
    'Répondez par un objet JSON : {"propositions": ["...", "..."], '
    '"justification": "une phrase"}'
)


async def suggerer_formation_complementaire(poste: Poste) -> tuple[list[str], str] | None:
    """Des formations complémentaires plausibles pour le poste. None si indisponible."""
    try:
        reponse = await get_provider().repondre_json(CONSIGNE_COMPLEMENTAIRE, _contexte(poste))
    except Exception:
        logger.exception(
            "proposition de formation complémentaire indisponible pour le poste %s", poste.id
        )
        return None
    brutes = reponse.get("propositions") if isinstance(reponse, dict) else None
    if not isinstance(brutes, list):
        return None
    propositions: list[str] = []
    for brute in brutes:
        texte = str(brute or "").strip().strip(".").strip()
        # « Formation complémentaire en … » est ajouté par l'avis et la grille.
        for prefixe in ("formation complémentaire en ", "formation en "):
            if texte.lower().startswith(prefixe):
                texte = texte[len(prefixe):]
        if texte and len(texte) <= 200 and texte not in propositions:
            propositions.append(texte)
    return propositions[:3], str(reponse.get("justification") or "").strip()
