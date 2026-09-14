"""Fabrique un jeu de dossiers fictifs à déposer dans TriCV.

Ces fichiers servent à montrer l'outil : on les dépose dans la grille du poste
« Directeur des Ressources Humaines » de la démonstration, et chacun y produit
une issue différente — préqualifié, sous le seuil, éliminé pour niveau
insuffisant, dossier incomplet, doublon.

Aucune de ces personnes n'existe. Les fichiers sont régénérés à volonté :

    python demo/creer_dossiers.py

Ils atterrissent dans demo/dossiers/, que le dépôt ignore. Les noms de
fichiers suivent la convention que le rattachement en lot sait lire —
NOM_Prenom_typedepiece.pdf — pour que quarante fichiers déposés d'un coup se
regroupent par personne sans intervention.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

SORTIE = Path(__file__).resolve().parent / "dossiers"

BLEU = HexColor("#1E2299")
OR = HexColor("#B8892A")
ENCRE = HexColor("#1f2933")
GRIS = HexColor("#6B7080")


# --- mise en page ------------------------------------------------------------


def _ecrire(chemin: Path, titre: str, blocs: list[tuple[str, list[str]]]) -> None:
    """Une page A4 sobre : un titre, puis des sections en gras et leurs lignes.

    Le rendu compte moins que le texte : c'est lui que la lecture automatique
    extraira, et un PDF dont le texte est illisible ne prouverait rien.
    """
    page = canvas.Canvas(str(chemin), pagesize=A4)
    largeur, hauteur = A4
    y = hauteur - 28 * mm

    page.setFillColor(BLEU)
    page.setFont("Helvetica-Bold", 16)
    page.drawString(22 * mm, y, titre)
    y -= 4 * mm
    page.setStrokeColor(OR)
    page.setLineWidth(1.2)
    page.line(22 * mm, y, largeur - 22 * mm, y)
    y -= 9 * mm

    for intitule, lignes in blocs:
        if y < 30 * mm:
            page.showPage()
            y = hauteur - 28 * mm
        if intitule:
            page.setFillColor(BLEU)
            page.setFont("Helvetica-Bold", 10.5)
            page.drawString(22 * mm, y, intitule.upper())
            y -= 6 * mm
        page.setFont("Helvetica", 9.5)
        for ligne in lignes:
            if y < 22 * mm:
                page.showPage()
                y = hauteur - 28 * mm
                page.setFont("Helvetica", 9.5)
            # Une ligne indentée est un détail rattaché à celle du dessus.
            decalage = 28 * mm if ligne.startswith("   ") else 22 * mm
            page.setFillColor(GRIS if ligne.startswith("   ") else ENCRE)
            page.drawString(decalage, y, ligne.strip())
            y -= 5 * mm
        y -= 4 * mm

    page.save()


# --- les personnes -----------------------------------------------------------
#
# Chacune est construite pour tomber dans une case précise de la grille. Le
# poste visé demande BAC+5 en RH / droit social / management, huit ans
# d'expérience dont cinq en gestion des ressources humaines, et trois pièces :
# lettre de motivation, CV, copie des diplômes.


class Dossier:
    def __init__(
        self,
        nom: str,
        prenom: str,
        email: str,
        telephone: str,
        naissance: str,
        attendu: str,
        formation: list[str],
        experience: list[str],
        divers: list[str],
        pieces: tuple[str, ...] = ("cv", "lettre_de_motivation", "diplomes", "attestations"),
        motivation: str = "",
        # À qui la lettre s'adresse et pour quel poste. Par défaut celui de
        # cette démonstration-ci ; un autre jeu de dossiers les redéfinit sans
        # avoir à recopier la mise en page.
        destinataire: str = "la Direction générale de Dogta-Lafiè",
        objet: str = "candidature au poste de Directeur des Ressources Humaines",
    ) -> None:
        self.nom = nom
        self.prenom = prenom
        self.email = email
        self.telephone = telephone
        self.naissance = naissance
        self.attendu = attendu
        self.formation = formation
        self.experience = experience
        self.divers = divers
        self.pieces = pieces
        self.motivation = motivation
        self.destinataire = destinataire
        self.objet = objet

    @property
    def racine(self) -> str:
        return f"{self.nom.upper()}_{self.prenom.replace(' ', '_')}"

    def ecrire(self, dossier: Path) -> list[Path]:
        produits: list[Path] = []
        entete = [
            f"{self.prenom} {self.nom.upper()}",
            f"Né(e) le {self.naissance} · de nationalité togolaise",
            f"{self.email} · {self.telephone} · Lomé, Togo",
        ]

        if "cv" in self.pieces:
            chemin = dossier / f"{self.racine}_cv.pdf"
            _ecrire(
                chemin,
                "Curriculum vitae",
                [
                    ("", entete),
                    ("Formation", self.formation),
                    ("Expérience professionnelle", self.experience),
                    ("Langues et divers", self.divers),
                ],
            )
            produits.append(chemin)

        if "lettre_de_motivation" in self.pieces:
            chemin = dossier / f"{self.racine}_lettre_de_motivation.pdf"
            _ecrire(
                chemin,
                "Lettre de motivation",
                [
                    ("", entete),
                    (
                        "",
                        [
                            f"À l'attention de {self.destinataire}",
                            f"Objet : {self.objet}",
                            "",
                            "Madame, Monsieur,",
                            "",
                            self.motivation
                            or "Je vous soumets ma candidature au poste ouvert par votre "
                            "établissement.",
                            "",
                            "Je me tiens à votre disposition pour un entretien.",
                            "",
                            "Veuillez agréer, Madame, Monsieur, l'expression de ma",
                            "considération distinguée.",
                            "",
                            f"{self.prenom} {self.nom.upper()}",
                        ],
                    ),
                ],
            )
            produits.append(chemin)

        if "diplomes" in self.pieces:
            chemin = dossier / f"{self.racine}_copie_des_diplomes.pdf"
            _ecrire(
                chemin,
                "Copie des diplômes",
                [("", entete), ("Diplômes présentés", self.formation)],
            )
            produits.append(chemin)

        if "attestations" in self.pieces:
            chemin = dossier / f"{self.racine}_attestations_de_travail.pdf"
            _ecrire(
                chemin,
                "Attestations de travail",
                [("", entete), ("Employeurs", self.experience)],
            )
            produits.append(chemin)

        return produits


DOSSIERS = [
    Dossier(
        nom="Agbodjan",
        prenom="Komlan",
        email="k.agbodjan@example.tg",
        telephone="+228 90 41 22 87",
        naissance="14 mars 1986",
        attendu="Préqualifié — dépasse toutes les conditions.",
        formation=[
            "2011 — Master 2 en gestion des ressources humaines",
            "   Université de Lomé · mention bien",
            "2009 — Licence en sciences de gestion",
            "   Université de Lomé",
        ],
        experience=[
            "2017 à ce jour — Directeur des ressources humaines",
            "   Centre hospitalier régional de Kara · 340 agents",
            "   Politique RH, paie, dialogue social, plan de formation.",
            "2013 – 2017 — Responsable du développement RH",
            "   Groupe Sarakawa, Lomé",
            "   Recrutement, gestion des carrières, évaluation annuelle.",
            "2011 – 2013 — Chargé d'études sociales",
            "   Cabinet Conseil & Stratégie, Lomé",
        ],
        divers=[
            "Français (langue de travail), éwé, anglais professionnel",
            "Certifié en droit du travail OHADA — 2019",
            "Membre de l'Association togolaise des DRH",
        ],
        motivation=(
            "Directeur des ressources humaines d'un centre hospitalier depuis neuf ans, "
            "je connais les contraintes propres au secteur de la santé : continuité du "
            "service, gestion des gardes, dialogue avec les corps soignants."
        ),
    ),
    Dossier(
        nom="Sodji",
        prenom="Ayélé",
        email="ayele.sodji@example.tg",
        telephone="+228 91 08 66 04",
        naissance="2 août 1988",
        attendu="Préqualifiée — remplit les conditions sans les dépasser.",
        formation=[
            "2013 — Master en droit social",
            "   Université de Kara",
            "2011 — Licence en droit privé",
            "   Université de Kara",
        ],
        experience=[
            "2019 à ce jour — Responsable des ressources humaines",
            "   Société togolaise des eaux, Lomé · 120 agents",
            "   Paie, contrats, contentieux social.",
            "2015 – 2019 — Juriste d'entreprise, pôle social",
            "   Compagnie d'assurances du Golfe, Lomé",
        ],
        divers=[
            "Français, anglais (lu, écrit)",
            "Formation continue en conduite du dialogue social — CIFOP, 2021",
        ],
        motivation=(
            "Juriste de formation devenue responsable RH, j'ai construit ma pratique "
            "sur le droit social appliqué au quotidien plutôt que sur la théorie."
        ),
    ),
    Dossier(
        nom="Amegan",
        prenom="Kossi",
        email="kossi.amegan@example.tg",
        telephone="+228 92 77 31 55",
        naissance="9 janvier 1997",
        attendu="Éliminé — BAC+3 pour un poste à BAC+5, et cinq ans au lieu de huit.",
        formation=[
            "2020 — Licence professionnelle en gestion des entreprises",
            "   Université de Lomé",
        ],
        experience=[
            "2023 à ce jour — Assistant RH",
            "   Clinique Biasa, Lomé",
            "   Suivi des dossiers du personnel, préparation de la paie.",
            "2021 – 2023 — Gestionnaire administratif",
            "   Entreprise Togo Fret, Lomé",
        ],
        divers=["Français, éwé", "Pack Office, logiciel de paie Sage"],
        motivation=(
            "Je souhaite évoluer vers une fonction de direction et me forme "
            "actuellement en parallèle de mon poste."
        ),
    ),
    Dossier(
        nom="Tetteh",
        prenom="Afi",
        email="afi.tetteh@example.tg",
        telephone="+228 93 12 40 19",
        naissance="27 juin 1989",
        attendu=(
            "Éliminée pour dossier incomplet — la copie des diplômes manque. "
            "Écartée dès le dépôt : cela se constate sans rien lire."
        ),
        formation=[
            "2014 — Master en management des organisations",
            "   Université catholique de l'Afrique de l'Ouest, Lomé",
        ],
        experience=[
            "2018 à ce jour — Chef du service du personnel",
            "   Hôpital de district de Tsévié · 95 agents",
            "2014 – 2018 — Chargée des ressources humaines",
            "   ONG Santé pour Tous, Lomé",
        ],
        divers=["Français, anglais courant, mina"],
        pieces=("cv", "lettre_de_motivation"),
        motivation=(
            "Onze ans dans la gestion du personnel hospitalier, dont huit à la tête "
            "d'un service."
        ),
    ),
    # Le même homme que le premier dossier, déposé une seconde fois sous son
    # nom complet — le cas ordinaire du candidat qui repostule sans le dire.
    # L'adresse email le trahit : la détection le signale, sans rien bloquer,
    # et c'est sur lui que se montre la suppression d'un dossier en trop.
    Dossier(
        nom="Agbodjan",
        prenom="Komlan Mensah",
        email="k.agbodjan@example.tg",
        telephone="+228 90 41 22 87",
        naissance="14 mars 1986",
        attendu=(
            "Doublon du premier dossier — même homme, nom complet. Rien ne le "
            "signale : c'est le lecteur qui le voit, et qui le supprime."
        ),
        formation=[
            "2011 — Master 2 en gestion des ressources humaines",
            "   Université de Lomé",
        ],
        experience=[
            "2017 à ce jour — Directeur des ressources humaines",
            "   Centre hospitalier régional de Kara",
            "2013 – 2017 — Responsable du développement RH",
            "   Groupe Sarakawa, Lomé",
        ],
        divers=["Français, éwé, anglais professionnel"],
        pieces=("cv", "lettre_de_motivation", "diplomes"),
        motivation="Je renouvelle ma candidature, ma première demande étant restée sans suite.",
    ),
]


MODE_D_EMPLOI = """JEU DE DÉMONSTRATION — TriCV
================================================================

Cinq dossiers fictifs, taillés pour le poste « Directeur des Ressources
Humaines » (client Dogta-Lafiè) de la base de démonstration. Ce poste exige un
BAC+5 en RH, droit social ou management, huit ans d'expérience dont cinq en
gestion des ressources humaines, et trois pièces : lettre de motivation, CV,
copie des diplômes.

Aucune de ces personnes n'existe.


CE QUE CHAQUE DOSSIER MONTRE
----------------------------------------------------------------
{tableau}


COMMENT LES DÉPOSER
----------------------------------------------------------------
1. Ouvrir le poste : Mandats › Dogta-Lafiè › Directeur des Ressources
   Humaines.

2. Dans « Rattachement en lot », déposer les fichiers de demo/dossiers/ —
   ou l'archive lot-candidatures.zip, qui contient les mêmes. L'écran
   propose un regroupement par personne, déduit des noms de fichiers :
   le vérifier avant de valider.

3. Cocher « Dépouiller aussitôt » avant de valider : les CV sont lus et le
   parcours proposé. Sans cette case, les dossiers arrivent vides et tout
   est à saisir.

4. Les dossiers arrivent « à vérifier » : ce qui vient d'être lu n'engage
   encore personne. Ouvrir chacun, relire, puis « Confirmer les données ».
   Tant que ce n'est pas fait, aucun motif tiré du parcours ne peut les
   éliminer — c'est voulu.

   TETTEH, elle, est écartée sans attendre : sa copie des diplômes manque, et
   un dossier incomplet se constate sans rien lire.

5. Recalculer. La grille se remplit : trois préqualifiés — dont le doublon —
   et deux éliminés, avec le motif de chaque élimination.


CE QU'IL Y A À MONTRER ENSUITE
----------------------------------------------------------------
· Le doublon. AGBODJAN apparaît deux fois — une fois sous son prénom seul,
  une fois sous son nom complet. Rien ne le signale, et c'est normal : sur un
  dépôt en lot, les coordonnées sont retirées du texte avant la lecture
  assistée, si bien que ni l'adresse ni la date de naissance ne sont connues.
  L'outil ne peut pas rapprocher les deux fiches ; le lecteur, si. Ouvrir le
  tiroir, descendre en bas, « Supprimer ce dossier », écrire le motif — le
  dossier, ses pièces et sa note disparaissent ; le journal garde le motif.
  (Redéposer les mêmes fichiers, en revanche, est refusé sur-le-champ :
  l'empreinte est identique, et là il n'y a pas de doute possible.)

· Une pièce mal rattachée. Dans un dossier, « Retirer » à côté d'une pièce
  demande confirmation, puis l'efface et réévalue le dossier : la consistance
  retombe et le dossier redevient incomplet sous les yeux du lecteur.

· Ce que le tri ne décide pas. AGBODJAN et SODJI sortent tous deux
  préqualifiés, à deux points près, sur des parcours qui n'ont rien de
  comparable — un DRH d'hôpital et une juriste devenue RH. C'est là que
  l'outil s'arrête : il classe, il n'arbitre pas.

· Le seuil. Le déplacer et voir la présélection se recomposer.

· L'export. « Exporter la grille (Excel) » pour le fichier de travail,
  « CV à en-tête (Word) » pour les dossiers remis au client.

· La page publique. L'avis publié est ouvert aux dépôts : un candidat peut
  déposer lui-même depuis /careers.
"""


def main() -> None:
    SORTIE.mkdir(parents=True, exist_ok=True)
    for ancien in SORTIE.iterdir():
        if ancien.is_file():
            ancien.unlink()

    produits: list[Path] = []
    for dossier in DOSSIERS:
        produits.extend(dossier.ecrire(SORTIE))

    archive = SORTIE / "lot-candidatures.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for chemin in produits:
            zf.write(chemin, chemin.name)

    tableau = "\n".join(
        f"{d.racine + ' (' + d.email + ')':<52}\n    {d.attendu}\n"
        f"    pièces : {', '.join(d.pieces)}\n"
        for d in DOSSIERS
    )
    # utf-8-sig : sans marque d'ordre, le Bloc-notes de Windows ouvre encore ce
    # fichier en ANSI sur certaines machines, et les accents y deviennent
    # illisibles. Le fichier est fait pour être ouvert d'un double-clic.
    (SORTIE / "MODE D'EMPLOI.txt").write_text(
        MODE_D_EMPLOI.format(tableau=tableau), encoding="utf-8-sig"
    )

    print(f"{len(produits)} fichier(s) dans {SORTIE}")
    for chemin in produits:
        print(f"   {chemin.name}")
    print(f"   {archive.name}  ({archive.stat().st_size // 1024} Ko)")
    print("   MODE D'EMPLOI.txt")


if __name__ == "__main__":
    main()
