"""Corpus de CV avec vérité terrain, pour mesurer l'extraction.

Écrits à la main dans le style des dossiers reçus au Togo : intitulés en
capitales, dates à la française, mois abrégés, postes toujours occupés,
mentions « X ans d'expérience », établissements locaux. Six mises en page,
choisies parce que chacune cassait autre chose : une colonne, deux colonnes,
un tableau Word recollé, des mois abrégés, un CV anglais, un CV dense.

**Tout y est inventé.** Aucun nom, employeur ou coordonnée ne renvoie à une
personne réelle : ce fichier est versionné, et un dossier de candidature
véritable n'a rien à faire dans un dépôt.

`verite` est ce qu'un recruteur lirait sur la page. C'est la seule référence :
le score du modèle se mesure contre elle, jamais contre une sortie antérieure
du modèle. Voir `evaluer_extraction.py`.
"""

from __future__ import annotations

CVS: dict[str, dict] = {}


CVS["classique"] = {
    "texte": """
KOSSI Amevi
Cadre en gestion des ressources humaines
Adresse : 45, rue de la Kozah, Tokoin, Lomé — BP 3421 Lomé
Téléphone : +228 90 12 34 56 | Email : amevi.kossi@example.tg
Né le 12/04/1985 à Kpalimé — Nationalité : Togolaise — Sexe : Masculin
Situation de famille : Marié, 2 enfants

PROFIL
Professionnel des ressources humaines fort de 12 ans d'expérience dans la
gestion administrative du personnel, la paie et le dialogue social.

FORMATION
2010 : Master 2 en Gestion des Ressources Humaines, Université de Lomé
2008 : Licence en Sciences de Gestion, Université de Lomé
2005 : Baccalauréat série D, Lycée de Tokoin

EXPERIENCE PROFESSIONNELLE
Depuis mars 2018 — Chef du service du personnel, Orabank Togo, Lomé
  Pilotage de la paie de 240 agents, gestion des carrières, relations avec les
  délégués du personnel.
Janvier 2014 à février 2018 — Responsable administratif RH, SOTOCO, Atakpamé
  Suivi des dossiers du personnel, recrutement des saisonniers.
Septembre 2010 à décembre 2013 — Assistant RH, Cabinet Alpha Conseil, Lomé
  Appui au recrutement et à la formation.

LANGUES
Français (langue maternelle), Anglais (courant), Ewé

CERTIFICATIONS
Certificat en droit du travail OHADA (2019)
""",
    "verite": {
        "diplomes": [
            {"niveau": 5, "annee": 2010, "domaine": "gestion des ressources humaines"},
            {"niveau": 3, "annee": 2008, "domaine": "sciences de gestion"},
            {"niveau": 0, "annee": 2005, "domaine": "baccalaureat"},
        ],
        "experiences": [
            {"employeur": "Orabank", "debut": "2018-03", "fin": None},
            {"employeur": "SOTOCO", "debut": "2014-01", "fin": "2018-02"},
            {"employeur": "Alpha Conseil", "debut": "2010-09", "fin": "2013-12"},
        ],
        "langues": 3,
        "certifications": 1,
    },
}


CVS["mois_abreges"] = {
    "texte": """
CURRICULUM VITAE

ADJOVI Afiwa
Née le 3 septembre 1990 — Togolaise — Célibataire
Tél. 91 23 45 67 — afiwa.adjovi@gmail.com
Adresse : Quartier Bè-Kpota, Lomé

DIPLOMES ET FORMATIONS
Sept. 2013 : Diplôme d'Ingénieur de conception en Génie Civil, ENSI Lomé
Juin 2010 : DUT Génie Civil, Université de Lomé

PARCOURS PROFESSIONNEL
Oct. 2019 – à ce jour     Ingénieur travaux, CECO BTP, Lomé
Mars 2016 – Sept. 2019    Conducteur de travaux, EBOMAF Togo, Kara
Nov. 2013 – Févr. 2016    Ingénieur stagiaire puis ingénieur d'études,
                          Bureau d'études TECHNIPLUS, Lomé

COMPETENCES LINGUISTIQUES
Français : excellent — Anglais : moyen

FORMATIONS COMPLEMENTAIRES
AutoCAD avancé (2015), Gestion de projet PMP niveau 1 (2018)
""",
    "verite": {
        "diplomes": [
            {"niveau": 5, "annee": 2013, "domaine": "genie civil"},
            {"niveau": 2, "annee": 2010, "domaine": "genie civil"},
        ],
        "experiences": [
            {"employeur": "CECO BTP", "debut": "2019-10", "fin": None},
            {"employeur": "EBOMAF", "debut": "2016-03", "fin": "2019-09"},
            {"employeur": "TECHNIPLUS", "debut": "2013-11", "fin": "2016-02"},
        ],
        "langues": 2,
        "certifications": 2,
    },
}


CVS["deux_colonnes"] = {
    # Ce que PyMuPDF rend d'une mise en page à deux colonnes : les blocs
    # arrivent dans l'ordre de lecture du PDF, pas dans l'ordre visuel.
    "texte": """
MENSAH Kodjo Elom
Gestionnaire financier

CONTACT
BP 1290 Lomé
(+228) 99 88 77 66
k.mensah@yahoo.fr
LinkedIn : linkedin.com/in/kodjo-mensah

INFOS
Age : 38 ans
Nationalité togolaise
Permis B

LANGUES
Français
Anglais
Allemand (notions)

FORMATION
2011 — DESS Finance d'entreprise
Université de Ouagadougou (Burkina Faso)
2009 — Maîtrise en Sciences Economiques
Université de Lomé

EXPERIENCES
2020 à ce jour
Directeur financier adjoint
GROUPE CIMTOGO, Lomé
Supervision de la comptabilité générale et analytique, élaboration du budget.

2015 - 2020
Contrôleur de gestion
BOA Togo, Lomé
Reporting mensuel, contrôle budgétaire.

2011 - 2015
Comptable
SGI Togo, Lomé

CERTIFICATIONS
IFRS — cabinet Deloitte, 2018
""",
    "verite": {
        "diplomes": [
            {"niveau": 5, "annee": 2011, "domaine": "finance"},
            {"niveau": 4, "annee": 2009, "domaine": "sciences economiques"},
        ],
        "experiences": [
            {"employeur": "CIMTOGO", "debut": "2020-01", "fin": None},
            {"employeur": "BOA", "debut": "2015-01", "fin": "2020-01"},
            {"employeur": "SGI", "debut": "2011-01", "fin": "2015-01"},
        ],
        "langues": 3,
        "certifications": 1,
    },
}


CVS["anglais"] = {
    "texte": """
CURRICULUM VITAE

Name: AGBEKO Yawo
Date of birth: 15 July 1988
Nationality: Togolese
Phone: +228 92 55 44 33
Email: yawo.agbeko@outlook.com
Address: 12 Avenue de la Liberation, Lome

EDUCATION
2014  MSc in Public Health, University of Ghana, Legon
2011  Bachelor of Science in Nursing, Universite de Lome

PROFESSIONAL EXPERIENCE
2021 - present   Programme Manager, Plan International Togo, Lome
2017 - 2021      Monitoring and Evaluation Officer, UNICEF Togo, Lome
2014 - 2017      Project Officer, Croix-Rouge Togolaise, Kara

LANGUAGES
English (fluent), French (native), Mina

CERTIFICATIONS
Project Management for Development Professionals (PMD Pro), 2019
""",
    "verite": {
        "diplomes": [
            {"niveau": 5, "annee": 2014, "domaine": "sante publique"},
            {"niveau": 3, "annee": 2011, "domaine": "soins infirmiers"},
        ],
        "experiences": [
            {"employeur": "Plan International", "debut": "2021-01", "fin": None},
            {"employeur": "UNICEF", "debut": "2017-01", "fin": "2021-01"},
            {"employeur": "Croix-Rouge", "debut": "2014-01", "fin": "2017-01"},
        ],
        "langues": 3,
        "certifications": 1,
    },
}


CVS["dense"] = {
    "texte": """
TCHALLA Komi
Spécialiste en passation des marchés — 15 ans d'expérience
Tel : 90 00 11 22 / 70 33 44 55  •  komi.tchalla@example.com
Né(e) le 22-11-1979 — Nationalité : Togolaise — Sexe : Masculin — Marié

RESUME
Expert en passation de marchés publics avec 15 ans d'expérience dont 8 ans
d'expérience spécifique en passation des marchés sur financement Banque
Mondiale. A conduit plus de 60 procédures d'appel d'offres.

ETUDES
2006 - 2008 : Master en Droit des Affaires, Université de Lomé (BAC+5)
2003 - 2006 : Licence en Droit Privé, Université de Lomé
2003 : BAC A4

EXPERIENCES PROFESSIONNELLES
01/2017 à ce jour : Spécialiste en passation des marchés, Ministère de la Santé,
Unité de Gestion de Projet, Lomé — procédures Banque Mondiale
06/2012 - 12/2016 : Chargé de la passation des marchés, PNUD Togo, Lomé
09/2008 - 05/2012 : Juriste, Cabinet Maître AGBO, Lomé

AUTRES
Langues : Français, Anglais professionnel
Certifications : Certificat en passation des marchés publics (ISADE, 2014),
Formation Banque Mondiale sur les procédures de passation (2016)
""",
    "verite": {
        "diplomes": [
            {"niveau": 5, "annee": 2008, "domaine": "droit des affaires"},
            {"niveau": 3, "annee": 2006, "domaine": "droit prive"},
            {"niveau": 0, "annee": 2003, "domaine": "baccalaureat"},
        ],
        "experiences": [
            {"employeur": "Ministère de la Santé", "debut": "2017-01", "fin": None},
            {"employeur": "PNUD", "debut": "2012-06", "fin": "2016-12"},
            {"employeur": "AGBO", "debut": "2008-09", "fin": "2012-05"},
        ],
        "langues": 2,
        "certifications": 2,
    },
}


CVS["tableau"] = {
    # Rendu d'un CV en tableau Word : les cellules sont recollées sur une ligne.
    "texte": """
FIANYO Akouvi Sena
akouvi.fianyo@example.tg   |   +228 96 45 12 78   |   Lomé, Togo
Date de naissance : 07/02/1992   Sexe : Féminin   Nationalité : Togolaise

FORMATION ACADEMIQUE
Période  Diplôme  Etablissement
2015-2017  Master en Gestion Hôtelière et Tourisme  Institut Supérieur de Tourisme d'Abidjan
2012-2015  Licence Professionnelle en Hôtellerie-Restauration  Université de Lomé

EXPERIENCE PROFESSIONNELLE
Période  Poste  Employeur
Depuis 08/2021  Directrice d'hébergement  Hôtel Sarakawa, Lomé
02/2018 - 07/2021  Responsable de la réception  Hôtel 2 Février, Lomé
09/2017 - 01/2018  Stagiaire réception  Radisson Blu, Abidjan (Côte d'Ivoire)

LANGUES  Français (maternelle), Anglais (bon), Espagnol (notions)
LOGICIELS  Opera PMS, Microsoft Office
""",
    "verite": {
        "diplomes": [
            {"niveau": 5, "annee": 2017, "domaine": "gestion hoteliere"},
            {"niveau": 3, "annee": 2015, "domaine": "hotellerie restauration"},
        ],
        "experiences": [
            {"employeur": "Sarakawa", "debut": "2021-08", "fin": None},
            {"employeur": "2 Février", "debut": "2018-02", "fin": "2021-07"},
            {"employeur": "Radisson", "debut": "2017-09", "fin": "2018-01"},
        ],
        "langues": 3,
        "certifications": 0,
    },
}
