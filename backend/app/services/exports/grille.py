"""Exports tableur du poste : quatre documents, un producteur.

Le classeur complet reproduit le document de travail : un en-tête qui rappelle
le mandat, le poste et les paramètres du calcul, puis la grille, le tableau
d'élimination subdivisé par motif, le détail des entretiens et une synthèse.

Chacun de ces quatre s'exporte aussi **seul** (voir `TypeGrille`), parce qu'ils
ne s'adressent pas aux mêmes personnes : le classement part au client, le
tableau d'élimination se produit à un candidat qui conteste, les entretiens
servent à écrire le rapport, la synthèse tient dans une réunion.

L'en-tête n'est pas décoratif : une grille sans son seuil, sa date de clôture
et sa référence d'avis n'est pas relisable six mois plus tard, et c'est
précisément ce qu'on ressort quand une décision est contestée.
"""

from __future__ import annotations

import io
from datetime import date
from enum import Enum

from types import SimpleNamespace

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.domain.referentiel import NiveauDiplome
from app.models import Poste
from app.schemas.recrutement import GrilleOut, LigneGrille

# Identité Kapi Consult, relevée sur kapiconsult.tg : bleu profond #1E2299 et
# or #B8892A. La grille est remise au client sous le nom du cabinet — elle doit
# lui ressembler.
ENCRE = "0D0E1A"
BLEU_KAPI = "1E2299"
OR_KAPI = "B8892A"
REMPLISSAGE_ENTETE = PatternFill("solid", fgColor=BLEU_KAPI)
POLICE_ENTETE = Font(bold=True, color="FFFFFF", size=10)
POLICE_TITRE = Font(bold=True, size=14, color=BLEU_KAPI)
POLICE_SECTION = Font(bold=True, size=11, color=ENCRE)
POLICE_DISCRETE = Font(size=9, color="6B7080")
FILET = Side(style="thin", color="DCDFEC")
BORDURE = Border(bottom=FILET)

COLONNES = (
    # Le rang ouvre le tableau : le processus retient « les N premiers
    # candidats ayant obtenu les meilleures notes », c'est donc la première
    # chose que le lecteur cherche.
    ("Rang", 6),
    ("Nom", 18),
    ("Prénom", 16),
    ("Âge", 7),
    ("Nationalité", 16),
    ("Dernier diplôme", 30),
    ("École / Université", 26),
    ("Structure / Employeur", 26),
    ("Adresse", 22),
    ("Note /30", 10),
    # La présélection ne pèse que 30 % du total : afficher sa contribution
    # évite qu'une note sur 30 se lise comme une note finale.
    ("Sur 100", 9),
    # La seconde étape. Vide tant que le jury n'a pas siégé : « pas encore
    # reçu » et « n'a rien obtenu » ne doivent pas se lire pareil.
    ("Entretien", 10),
    ("Note finale /100", 15),
    ("Proposé", 10),
    ("Éliminé", 10),
    ("Motifs", 34),
)

# Colonnes centrées : rang, âge et les deux notes.
_CENTREES = (1, 4, 10, 11, 12, 13)

LIBELLE_TYPE_AVIS = {
    "NATIONAL": "Avis national",
    "INTERNATIONAL": "Avis international",
    "GRE_A_GRE": "Gré à gré",
}


def _styler_entete(feuille: Worksheet, ligne: int, nombre: int) -> None:
    for colonne in range(1, nombre + 1):
        cellule = feuille.cell(row=ligne, column=colonne)
        cellule.fill = REMPLISSAGE_ENTETE
        cellule.font = POLICE_ENTETE
        cellule.alignment = Alignment(vertical="center", wrap_text=True)
    feuille.row_dimensions[ligne].height = 28


def _largeurs(feuille: Worksheet) -> None:
    for index, (_, largeur) in enumerate(COLONNES, start=1):
        feuille.column_dimensions[get_column_letter(index)].width = largeur


def _bloc_identification(feuille: Worksheet, grille: GrilleOut, poste: Poste) -> int:
    """En-tête du document. Renvoie la première ligne libre."""
    feuille["A1"] = "KAPI CONSULT"
    feuille["A1"].font = Font(bold=True, size=10, color=OR_KAPI)
    feuille["A2"] = "Grille de présélection"
    feuille["A2"].font = POLICE_TITRE

    niveau = NiveauDiplome(poste.niveau_min).libelle
    lignes = [
        ("Client", grille.client_nom or "—"),
        ("Mandat", grille.mandat_intitule or "—"),
        ("Poste", grille.poste_intitule),
        (
            "Avis",
            " · ".join(
                filter(
                    None,
                    (
                        grille.reference_avis,
                        LIBELLE_TYPE_AVIS.get(
                            grille.type_avis.value if grille.type_avis else "", None
                        ),
                    ),
                )
            )
            or "—",
        ),
        (
            "Date de clôture",
            grille.date_reference.strftime("%d/%m/%Y") if grille.date_reference else "—",
        ),
        ("Profil exigé", f"{niveau}, {poste.annees_experience_min} an(s) d'expérience"),
        (
            "Dont expérience spécifique",
            f"{poste.annees_experience_specifique_min} an(s)",
        ),
        (
            "Barème de présélection",
            f"{grille.total_max:g} points, soit {grille.poids_preselection:g} % de la note finale "
            f"— les entretiens portent les {100 - grille.poids_preselection:g} % restants",
        ),
        ("Édité le", date.today().strftime("%d/%m/%Y")),
    ]

    if grille.seuil:
        lignes.insert(
            -1, ("Seuil de présélection", f"{grille.seuil:g} / {grille.total_max:g}")
        )
    if grille.nombre_a_proposer:
        lignes.insert(-1, ("Candidats à proposer", str(grille.nombre_a_proposer)))

    ligne = 4
    for intitule, valeur in lignes:
        feuille.cell(row=ligne, column=1, value=intitule).font = Font(bold=True, size=10)
        feuille.cell(row=ligne, column=2, value=valeur)
        ligne += 1

    if poste.seuil_justification:
        # Un seuil abaissé change qui est retenu : la raison voyage avec le
        # fichier plutôt que de rester dans le journal applicatif.
        feuille.cell(row=ligne, column=1, value="Seuil abaissé").font = Font(bold=True, size=10)
        feuille.cell(row=ligne, column=2, value=poste.seuil_justification)
        ligne += 1

    if poste.restriction_justification:
        feuille.cell(row=ligne, column=1, value="Poste restreint").font = Font(
            bold=True, size=10
        )
        feuille.cell(row=ligne, column=2, value=poste.restriction_justification)
        ligne += 1

    return ligne + 1


def _note_finale(item: LigneGrille) -> float | str | None:
    """La note sur 100, et le fait qu'elle soit provisoire.

    Un entretien partiellement noté donne un acquis, pas un résultat : l'écrire
    tel quel dans un fichier remis au client le ferait passer pour définitif.
    """
    if item.note_finale_sur_cent is None:
        return None
    if item.entretien_complet:
        return item.note_finale_sur_cent
    return f"{item.note_finale_sur_cent:g} (partiel)"


def _ecrire_lignes(feuille: Worksheet, depart: int, lignes: list[LigneGrille]) -> int:
    for decalage, item in enumerate(lignes):
        rang = depart + decalage
        valeurs = (
            item.rang,
            item.nom,
            item.prenom,
            item.age,
            item.nationalite,
            item.dernier_diplome,
            item.ecole_universite,
            item.structure_employeur,
            item.adresse,
            item.note,
            item.note_sur_cent,
            item.note_entretien_sur_cent,
            _note_finale(item),
            "Oui" if item.propose else ("Préqualifié" if item.preselectionne else ""),
            "Oui" if item.elimine else "",
            ", ".join(item.motifs),
        )
        for colonne, valeur in enumerate(valeurs, start=1):
            cellule = feuille.cell(row=rang, column=colonne, value=valeur)
            cellule.border = BORDURE
            if colonne in _CENTREES:
                cellule.alignment = Alignment(horizontal="center")
    return depart + len(lignes)


def _nouvelle_feuille(classeur: Workbook, titre: str) -> Worksheet:
    """La première feuille demandée occupe celle qu'openpyxl crée d'office.

    Sans cela, un classeur ne contenant qu'un tableau d'élimination s'ouvrirait
    sur un onglet « Sheet » vide, et le lecteur chercherait ce qu'il contient.
    """
    if classeur.sheetnames == ["Sheet"]:
        feuille = classeur.active
        feuille.title = titre
        return feuille
    return classeur.create_sheet(titre)


def _feuille_grille(classeur: Workbook, grille: GrilleOut, poste: Poste) -> None:
    feuille = _nouvelle_feuille(classeur, "Grille de présélection")
    _largeurs(feuille)

    ligne = _bloc_identification(feuille, grille, poste)

    for titre, lot in (
        ("Classement des dossiers recevables", grille.preselectionnes),
        ("Non retenus", grille.non_retenus),
    ):
        feuille.cell(row=ligne, column=1, value=f"{titre} ({len(lot)})").font = POLICE_SECTION
        ligne += 1

        for index, (intitule, _) in enumerate(COLONNES, start=1):
            feuille.cell(row=ligne, column=index, value=intitule)
        _styler_entete(feuille, ligne, len(COLONNES))
        ligne += 1

        if lot:
            ligne = _ecrire_lignes(feuille, ligne, lot)
        else:
            feuille.cell(row=ligne, column=1, value="Aucun dossier").font = POLICE_DISCRETE
            ligne += 1
        ligne += 1

    # Les en-têtes restent visibles au défilement : une grille de deux cents
    # lignes se lit mal autrement.
    feuille.freeze_panes = "A3"


def _feuille_elimination(classeur: Workbook, grille: GrilleOut) -> None:
    feuille = _nouvelle_feuille(classeur, "Tableau d'élimination")
    _largeurs(feuille)

    feuille["A1"] = "Tableau d'élimination"
    feuille["A1"].font = POLICE_TITRE
    feuille["A2"] = (
        "Un dossier peut figurer sous plusieurs motifs : chaque motif est une règle distincte."
    )
    feuille["A2"].font = POLICE_DISCRETE

    ligne = 4
    if not grille.elimines:
        feuille.cell(row=ligne, column=1, value="Aucun dossier éliminé").font = POLICE_DISCRETE
        return

    for groupe in grille.elimines:
        feuille.cell(
            row=ligne, column=1, value=f"{groupe.libelle} ({len(groupe.lignes)})"
        ).font = POLICE_SECTION
        ligne += 1

        for index, (intitule, _) in enumerate(COLONNES, start=1):
            feuille.cell(row=ligne, column=index, value=intitule)
        _styler_entete(feuille, ligne, len(COLONNES))
        ligne += 1

        ligne = _ecrire_lignes(feuille, ligne, groupe.lignes) + 1


def _feuille_synthese(classeur: Workbook, grille: GrilleOut) -> None:
    feuille = _nouvelle_feuille(classeur, "Synthèse")
    feuille.column_dimensions["A"].width = 34
    feuille.column_dimensions["B"].width = 16

    feuille["A1"] = "Synthèse"
    feuille["A1"].font = POLICE_TITRE

    lignes = [
        ("Candidatures reçues", grille.nombre_candidatures),
        ("Préqualifiés", grille.nombre_preselectionnes),
        ("Proposés au client", grille.nombre_proposes),
        ("Entretiens saisis", grille.nombre_entretiens),
        ("Non retenus", len(grille.non_retenus)),
        ("Éliminés", grille.nombre_elimines),
        ("En attente de vérification", grille.nombre_a_verifier),
    ]
    ligne = 3
    for intitule, valeur in lignes:
        feuille.cell(row=ligne, column=1, value=intitule).font = Font(bold=True, size=10)
        feuille.cell(row=ligne, column=2, value=valeur).alignment = Alignment(
            horizontal="center"
        )
        ligne += 1

    ligne += 1
    feuille.cell(row=ligne, column=1, value="Répartition des motifs").font = POLICE_SECTION
    ligne += 1
    for groupe in grille.elimines:
        feuille.cell(row=ligne, column=1, value=groupe.libelle)
        feuille.cell(row=ligne, column=2, value=len(groupe.lignes)).alignment = Alignment(
            horizontal="center"
        )
        ligne += 1

    if grille.nombre_a_verifier:
        ligne += 1
        cellule = feuille.cell(
            row=ligne,
            column=1,
            value=(
                f"{grille.nombre_a_verifier} dossier(s) reposent sur des données extraites "
                "automatiquement et non confirmées. Ils ne sont éliminés par personne tant "
                "qu'un relecteur ne les a pas validés."
            ),
        )
        cellule.font = POLICE_DISCRETE
        cellule.alignment = Alignment(wrap_text=True, vertical="top")


def _feuille_entretiens(classeur: Workbook, grille: GrilleOut, fiches: dict) -> None:
    """Le détail des entretiens : les points, et ce qui les motive.

    L'application ne rédige pas le rapport de recrutement — ce n'est pas son
    rôle. Elle en fournit la matière : pour chaque candidat reçu, la note de
    chaque critère et ce que le jury a observé, dans l'ordre du classement.
    C'est ce qui se recopie dans le rapport, et ce qui permet d'expliquer une
    note des mois plus tard.

    Un bloc par candidat plutôt qu'un tableau à plat : les commentaires sont
    des phrases, et une colonne de phrases ne se lit pas.
    """
    feuille = _nouvelle_feuille(classeur, "Entretiens")
    feuille.column_dimensions["A"].width = 42
    feuille.column_dimensions["B"].width = 8
    feuille.column_dimensions["C"].width = 8
    feuille.column_dimensions["D"].width = 62

    feuille["A1"] = "Entretiens structurés"
    feuille["A1"].font = POLICE_TITRE
    cellule = feuille.cell(
        row=2,
        column=1,
        value=(
            "Points attribués par le jury en séance. Ils comptent pour "
            f"{100 - grille.poids_preselection:g} % de la note finale, la présélection portant "
            f"les {grille.poids_preselection:g} % restants."
        ),
    )
    cellule.font = POLICE_DISCRETE

    ligne = 4
    # Ordre du classement : le lecteur retrouve les candidats dans l'ordre où
    # la grille les présente, pas dans celui où les fiches ont été saisies.
    for item in grille.preselectionnes:
        panel = fiches.get(item.candidature_id) or []
        if not panel:
            continue
        # Une ligne par critère, moyennée sur le panel : c'est le chiffre que
        # le client reçoit. Le détail par juré reste dans l'application.
        fiche = panel[0]

        titre = f"{item.nom} {item.prenom}".strip()
        if item.rang:
            titre = f"{item.rang}. {titre}"
        feuille.cell(row=ligne, column=1, value=titre).font = POLICE_SECTION
        if item.note_finale_sur_cent is not None:
            note = feuille.cell(row=ligne, column=4, value=_note_finale(item))
            note.font = POLICE_SECTION
            note.alignment = Alignment(horizontal="right")
        ligne += 1

        contexte = []
        if fiche.date_entretien:
            contexte.append(f"Reçu le {fiche.date_entretien:%d/%m/%Y}")
        if fiche.jury:
            contexte.append(f"Jury : {fiche.jury}")
        if len(panel) > 1:
            contexte.append(f"{len(panel)} fiches de notation")
        if contexte:
            cellule = feuille.cell(row=ligne, column=1, value=" · ".join(contexte))
            cellule.font = POLICE_DISCRETE
            ligne += 1

        for intitule, index in (("Critère", 1), ("Note", 2), ("Max", 3), ("Observations", 4)):
            feuille.cell(row=ligne, column=index, value=intitule)
        _styler_entete(feuille, ligne, 4)
        ligne += 1

        # Moyenne du panel, critère par critère.
        cumul: dict[str, list[float]] = {}
        commentaires: dict[str, list[str]] = {}
        for f in panel:
            for l in f.lignes:
                cumul.setdefault(l.code, []).append(float(l.points))
                if l.commentaire:
                    commentaires.setdefault(l.code, []).append(l.commentaire)

        for reference in fiche.bareme_utilise or []:
            code = reference["code"]
            valeurs = cumul.get(code)
            saisie = SimpleNamespace(
                points=round(sum(valeurs) / len(valeurs) * 2) / 2 if valeurs else None,
                commentaire=" · ".join(commentaires.get(code, ())) or None,
            ) if valeurs else None
            feuille.cell(row=ligne, column=1, value=reference["libelle"]).border = BORDURE
            note = feuille.cell(
                row=ligne, column=2, value=float(saisie.points) if saisie else None
            )
            note.alignment = Alignment(horizontal="center")
            note.border = BORDURE
            plafond = feuille.cell(row=ligne, column=3, value=reference["points_max"])
            plafond.alignment = Alignment(horizontal="center")
            plafond.border = BORDURE
            observation = feuille.cell(
                row=ligne,
                column=4,
                # « Non noté » plutôt qu'une case vide : le lecteur doit savoir
                # que le critère n'a pas été traité, pas se demander s'il l'a été.
                value=(saisie.commentaire if saisie else None) or ("" if saisie else "Non noté"),
            )
            observation.alignment = Alignment(wrap_text=True, vertical="top")
            observation.border = BORDURE
            ligne += 1

        totaux = [sum(float(l.points) for l in f.lignes) for f in panel]
        total = round(sum(totaux) / len(totaux) * 2) / 2
        intitule = "Total entretien"
        if len(panel) > 1:
            intitule = f"Moyenne du panel ({len(panel)} jurés)"
        feuille.cell(row=ligne, column=1, value=intitule).font = Font(bold=True, size=10)
        cellule = feuille.cell(row=ligne, column=2, value=total)
        cellule.font = Font(bold=True, size=10)
        cellule.alignment = Alignment(horizontal="center")
        maximum = sum(r["points_max"] for r in fiche.bareme_utilise or [])
        cellule = feuille.cell(row=ligne, column=3, value=maximum)
        cellule.alignment = Alignment(horizontal="center")
        if not item.entretien_complet:
            avertissement = feuille.cell(
                row=ligne,
                column=4,
                value="Tous les critères ne sont pas notés — total partiel.",
            )
            avertissement.font = POLICE_DISCRETE
        ligne += 1

        if fiche.observations:
            cellule = feuille.cell(row=ligne, column=1, value="Observations générales")
            cellule.font = Font(bold=True, size=10)
            cellule = feuille.cell(row=ligne, column=4, value=fiche.observations)
            cellule.alignment = Alignment(wrap_text=True, vertical="top")
            ligne += 1

        ligne += 1

    if ligne == 4:
        cellule = feuille.cell(
            row=4,
            column=1,
            value="Aucun entretien n'a encore été saisi pour ce poste.",
        )
        cellule.font = POLICE_DISCRETE


class TypeGrille(str, Enum):
    """Ce qu'on exporte, et pour qui.

    Le classeur complet reste la sortie par défaut, mais il mélange quatre
    documents dont les destinataires diffèrent : le classement part au client,
    le tableau d'élimination se produit à un candidat qui conteste, le détail
    des entretiens sert à écrire le rapport, la synthèse tient en une page pour
    une réunion. Les remettre ensemble oblige à envoyer plus que ce qu'on veut
    montrer, et à demander au lecteur d'ignorer trois onglets sur quatre.
    """

    PRESELECTION = "PRESELECTION"
    ELIMINATION = "ELIMINATION"
    ENTRETIENS = "ENTRETIENS"
    SYNTHESE = "SYNTHESE"
    COMPLET = "COMPLET"

    @property
    def libelle(self) -> str:
        return _LIBELLES_GRILLE[self]

    @property
    def fichier(self) -> str:
        return _FICHIERS_GRILLE[self]


_LIBELLES_GRILLE: dict[TypeGrille, str] = {
    TypeGrille.PRESELECTION: "Grille de présélection",
    TypeGrille.ELIMINATION: "Tableau d'élimination",
    TypeGrille.ENTRETIENS: "Détail des entretiens",
    TypeGrille.SYNTHESE: "Synthèse",
    TypeGrille.COMPLET: "Dossier complet",
}

_FICHIERS_GRILLE: dict[TypeGrille, str] = {
    TypeGrille.PRESELECTION: "grille-preselection",
    TypeGrille.ELIMINATION: "tableau-elimination",
    TypeGrille.ENTRETIENS: "entretiens",
    TypeGrille.SYNTHESE: "synthese",
    TypeGrille.COMPLET: "dossier-complet",
}


def construire_classeur(
    grille: GrilleOut,
    poste: Poste,
    fiches: dict | None = None,
    type_grille: TypeGrille = TypeGrille.COMPLET,
) -> bytes:
    """Le classeur demandé. Par défaut, celui qui contient tout.

    Chaque feuille est construite par la même fonction quel que soit le type :
    un tableau d'élimination exporté seul est mot pour mot celui de l'onglet du
    classeur complet. Deux chemins de production donneraient deux documents qui
    finiraient par diverger, et c'est précisément le genre d'écart qu'on ne
    découvre qu'une fois le fichier chez le client.
    """
    classeur = Workbook()

    if type_grille in (TypeGrille.PRESELECTION, TypeGrille.COMPLET):
        _feuille_grille(classeur, grille, poste)
    if type_grille in (TypeGrille.ELIMINATION, TypeGrille.COMPLET):
        _feuille_elimination(classeur, grille)
    # Dans le classeur complet, la feuille des entretiens n'apparaît que si
    # l'étape a eu lieu : un onglet vide dans un fichier remis au client
    # soulève une question inutile. Demandée explicitement, elle est produite
    # de toute façon — et dit alors qu'aucun entretien n'a été saisi, ce qui
    # est une réponse, là où un fichier sans feuille n'en serait pas une.
    if type_grille is TypeGrille.ENTRETIENS or (
        type_grille is TypeGrille.COMPLET and fiches
    ):
        _feuille_entretiens(classeur, grille, fiches or {})
    if type_grille in (TypeGrille.SYNTHESE, TypeGrille.COMPLET):
        _feuille_synthese(classeur, grille)

    tampon = io.BytesIO()
    classeur.save(tampon)
    return tampon.getvalue()
