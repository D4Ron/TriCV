"""Dossiers fictifs pour le poste « Chef comptable » de la démonstration.

Ce jeu-là existe pour montrer **une chose précise** : un avis qui énonce deux
expériences spécifiques — trois ans de comptabilité générale *et* deux ans
d'audit interne — les exige toutes les deux.

Réunies en un seul jeu de domaines, comme elles l'étaient avant, les deux
exigences n'en faisaient qu'une : douze ans de comptabilité couvraient à la
fois les trois ans de comptabilité et les deux ans d'audit, et un candidat
n'ayant jamais audité passait la barre. KOUMAKO est là pour cela, et DOSSEH
pour montrer que la règle vaut dans l'autre sens.

    python demo/creer_dossiers_comptables.py

Personne ici n'existe. Les fichiers atterrissent dans demo/dossiers-comptables/,
ignoré par git comme son voisin.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from creer_dossiers import Dossier, _ecrire  # noqa: F401  (mise en page partagée)

SORTIE = Path(__file__).resolve().parent / "dossiers-comptables"

DESTINATAIRE = "la Direction générale du Groupe Hôtelier Sarakawa"
OBJET = "candidature au poste de Chef comptable"


def _dossier(**champs) -> Dossier:
    champs.setdefault("destinataire", DESTINATAIRE)
    champs.setdefault("objet", OBJET)
    return Dossier(**champs)


# Le poste demande un BAC+4 en comptabilité ou finance, cinq ans d'expérience
# générale, dont trois en comptabilité générale et deux en audit interne, et
# n'accepte que les candidats de 45 ans au plus.
DOSSIERS = [
    _dossier(
        nom="Attiogbe",
        prenom="Sena",
        email="s.attiogbe@example.tg",
        telephone="+228 90 33 71 25",
        naissance="9 avril 1987",
        attendu="Préqualifiée — satisfait les deux exigences, et largement.",
        formation=[
            "2012 — Master en comptabilité, contrôle et audit",
            "   Université de Lomé · mention bien",
            "2010 — Licence en sciences comptables et financières",
            "   Université de Lomé",
        ],
        experience=[
            "2018 à ce jour — Chef comptable",
            "   Groupe Hôtelier Sarakawa, Lomé",
            "   Comptabilité générale : tenue des comptes, états financiers",
            "   annuels, liasse fiscale, relations avec le commissaire aux comptes.",
            "2014 – 2018 — Auditrice interne",
            "   Banque Atlantique Togo, Lomé",
            "   Audit interne des agences, cartographie des risques, suivi des",
            "   recommandations auprès du comité d'audit.",
            "2012 – 2014 — Comptable",
            "   Cabinet Fiduciaire du Golfe, Lomé",
        ],
        divers=[
            "Français, anglais professionnel, éwé",
            "Certifiée IFRS — cabinet Deloitte, 2019",
            "Maîtrise de Sage 100 et de SAP FI",
        ],
        motivation=(
            "Chef comptable du groupe depuis huit ans après quatre années d'audit "
            "interne en milieu bancaire, je connais les deux versants du poste : "
            "la tenue des comptes et le contrôle qui la fiabilise."
        ),
    ),
    _dossier(
        nom="Koumako",
        prenom="Edem",
        email="edem.koumako@example.tg",
        telephone="+228 91 45 08 12",
        naissance="21 janvier 1985",
        attendu="Écarté — douze ans de comptabilité générale, aucun audit interne.",
        formation=[
            "2011 — Master en finance d'entreprise",
            "   Université de Lomé",
            "2009 — Licence en sciences de gestion",
            "   Université de Lomé",
        ],
        experience=[
            "2016 à ce jour — Chef comptable",
            "   Société Togolaise de Distribution, Lomé",
            "   Comptabilité générale : supervision de quatre comptables,",
            "   arrêtés mensuels, déclarations fiscales, budget de trésorerie.",
            "2013 – 2016 — Comptable principal",
            "   Entreprise Générale du Bâtiment, Lomé",
            "   Comptabilité générale et analytique des chantiers.",
            "2011 – 2013 — Comptable",
            "   Cabinet Expertise & Conseil, Lomé",
            "   Comptabilité générale des dossiers clients.",
        ],
        divers=[
            "Français, anglais scolaire",
            "Maîtrise de Sage 100 et d'Excel avancé",
        ],
        motivation=(
            "Chef comptable depuis dix ans, j'ai construit et supervisé les "
            "comptes de deux entreprises de taille comparable à la vôtre."
        ),
    ),
    _dossier(
        nom="Dosseh",
        prenom="Akouvi",
        email="a.dosseh@example.tg",
        telephone="+228 92 17 63 40",
        naissance="3 juin 1990",
        attendu="Écartée — l'audit interne y est, la comptabilité générale non.",
        formation=[
            "2014 — Master en audit et contrôle de gestion",
            "   Université de Lomé",
            "2012 — Licence en comptabilité",
            "   Université de Lomé",
        ],
        experience=[
            "2016 à ce jour — Auditrice interne senior",
            "   Groupe CIMTOGO, Lomé",
            "   Audit interne des filiales, missions de conformité, rapports au",
            "   comité d'audit et suivi des plans d'action.",
            "2014 – 2016 — Chargée de missions d'audit interne",
            "   Cabinet Audit & Conseil International, Lomé",
            "2013 – 2014 — Comptable junior",
            "   Cabinet Audit & Conseil International, Lomé",
            "   Comptabilité générale de quelques dossiers clients.",
        ],
        divers=[
            "Français, anglais courant",
            "Formation aux normes internationales d'audit interne — IIA, 2021",
        ],
        motivation=(
            "Auditrice interne depuis douze ans, je souhaite passer du contrôle "
            "des comptes à leur tenue, dans un groupe que je connais de l'extérieur."
        ),
    ),
    _dossier(
        nom="Amouzouvi",
        prenom="Kodjo",
        email="k.amouzouvi@example.tg",
        telephone="+228 99 04 55 81",
        naissance="17 novembre 1992",
        attendu="Préqualifié — remplit les deux exigences, sans les dépasser.",
        formation=[
            "2016 — Maîtrise en sciences comptables",
            "   Université de Lomé",
            "2014 — Licence en comptabilité",
            "   Université de Lomé",
        ],
        experience=[
            "2021 à ce jour — Comptable principal",
            "   Hôtel du 2 Février, Lomé",
            "   Comptabilité générale : saisie, rapprochements bancaires,",
            "   préparation des états financiers.",
            "2018 – 2021 — Assistant d'audit interne",
            "   Groupe Hôtelier Sarakawa, Lomé",
            "   Audit interne des procédures d'encaissement et de stock.",
            "2016 – 2018 — Comptable",
            "   Pharmacie du Golfe, Lomé",
        ],
        divers=[
            "Français, anglais professionnel, mina",
            "Sage 100, Ciel Compta",
        ],
        motivation=(
            "Comptable principal depuis cinq ans après trois années passées à "
            "l'audit interne de votre groupe, je connais déjà vos procédures."
        ),
    ),
    _dossier(
        nom="Lawson-Body",
        prenom="Marc",
        email="m.lawsonbody@example.tg",
        telephone="+228 90 88 12 09",
        naissance="8 février 1975",
        attendu="Écarté — condition d'âge posée par l'avis, dossier par ailleurs solide.",
        formation=[
            "2003 — DESS en comptabilité et finance",
            "   Université de Lomé",
            "2001 — Maîtrise en sciences économiques",
            "   Université de Lomé",
        ],
        experience=[
            "2010 à ce jour — Directeur comptable et financier",
            "   Groupe Industriel de la Zone Franche, Lomé",
            "   Comptabilité générale, consolidation, contrôle budgétaire.",
            "2005 – 2010 — Responsable de l'audit interne",
            "   Ecobank Togo, Lomé",
            "   Audit interne du réseau et des systèmes de contrôle.",
            "2003 – 2005 — Auditeur",
            "   Cabinet international d'expertise comptable, Lomé",
        ],
        divers=[
            "Français, anglais courant, allemand (notions)",
            "Expert-comptable diplômé — 2008",
        ],
        motivation=(
            "Vingt-trois ans de comptabilité et d'audit, dont seize à la "
            "direction financière d'un groupe industriel."
        ),
    ),
]


def main() -> None:
    SORTIE.mkdir(parents=True, exist_ok=True)
    for ancien in SORTIE.iterdir():
        if ancien.is_file():
            ancien.unlink()

    produits: list[Path] = []
    for dossier in DOSSIERS:
        produits.extend(dossier.ecrire(SORTIE))

    archive = SORTIE / "lot-comptables.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for chemin in produits:
            zf.write(chemin, chemin.name)

    mode = SORTIE / "MODE D'EMPLOI.txt"
    mode.write_text(
        "\n".join(
            [
                "DOSSIERS DE DÉMONSTRATION — poste « Chef comptable »",
                "=" * 62,
                "",
                "Ce que ce jeu montre : un avis qui exige DEUX expériences",
                "spécifiques les exige toutes les deux.",
                "",
                "Le poste demande un BAC+4 en comptabilité ou finance, cinq ans",
                "d'expérience générale, dont TROIS en comptabilité générale ET",
                "DEUX en audit interne. Il n'accepte que les candidats de 45 ans",
                "au plus, condition justifiée par écrit sur la fiche.",
                "",
                "Déposez lot-comptables.zip, ou les fichiers en une seule fois :",
                "ils se regroupent par personne d'après leur nom.",
                "",
                "Ce que chaque dossier doit donner :",
                "",
                *(f"  {d.nom.upper()} {d.prenom}\n      {d.attendu}" for d in DOSSIERS),
                "",
                "Le dossier de KOUMAKO est celui qui compte : douze ans de",
                "comptabilité générale, zéro audit. Avec un seul jeu de domaines,",
                "son ancienneté couvrait les deux exigences et il passait la",
                "barre. La grille dit maintenant laquelle des deux manque.",
                "",
            ]
        ),
        encoding="utf-8-sig",
    )

    print(f"{len(produits)} fichier(s) dans {SORTIE}")
    print(f"archive : {archive.name}")


if __name__ == "__main__":
    main()
