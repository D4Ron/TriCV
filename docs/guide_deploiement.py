"""Génère le guide de déploiement de TriCV.

Le PDF est un livrable : il sera suivi par la personne qui met l'application en
service, sans accès au code ni à cette conversation. Il est donc rédigé en
français, dit *pourquoi* à chaque fois que le pourquoi change ce qu'on fait, et
signale ce qui coince en pratique.

Le script est versionné avec le PDF pour que le guide se regénère quand la
procédure change, plutôt que de dériver en silence.

    python docs/guide_deploiement.py
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

SORTIE = Path(__file__).parent / "Guide-deploiement-TriCV.pdf"

ENCRE = colors.HexColor("#1f2933")
ENCRE_DOUCE = colors.HexColor("#4b5563")
DISCRET = colors.HexColor("#6b7280")
FILET = colors.HexColor("#d7dce2")
FOND = colors.HexColor("#f6f7f9")
ALERTE = colors.HexColor("#b45309")
ALERTE_FOND = colors.HexColor("#fffbeb")
DANGER = colors.HexColor("#b91c1c")
DANGER_FOND = colors.HexColor("#fef2f2")
MARQUE = colors.HexColor("#1E2299")


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "titre": ParagraphStyle(
            "titre", parent=base["Title"], fontSize=21, leading=25,
            textColor=ENCRE, spaceAfter=2,
        ),
        "sous_titre": ParagraphStyle(
            "sous_titre", parent=base["Normal"], fontSize=10.5, leading=15,
            textColor=DISCRET, spaceAfter=16,
        ),
        "section": ParagraphStyle(
            "section", parent=base["Heading1"], fontSize=14, leading=18,
            textColor=ENCRE, spaceBefore=18, spaceAfter=8, keepWithNext=True,
        ),
        "etape": ParagraphStyle(
            "etape", parent=base["Heading2"], fontSize=11.5, leading=15,
            textColor=ENCRE, spaceBefore=13, spaceAfter=5, keepWithNext=True,
        ),
        "corps": ParagraphStyle(
            "corps", parent=base["Normal"], fontSize=9.8, leading=14.5,
            textColor=ENCRE_DOUCE, alignment=TA_JUSTIFY, spaceAfter=6,
        ),
        "puce": ParagraphStyle(
            "puce", parent=base["Normal"], fontSize=9.8, leading=14,
            textColor=ENCRE_DOUCE, spaceAfter=3,
        ),
        "code": ParagraphStyle(
            "code", parent=base["Normal"], fontName="Courier", fontSize=8.6,
            leading=12.5, textColor=ENCRE, spaceAfter=5, spaceBefore=2,
        ),
        "alerte": ParagraphStyle(
            "alerte", parent=base["Normal"], fontSize=9.5, leading=14,
            textColor=ALERTE, alignment=TA_JUSTIFY,
        ),
        "cellule": ParagraphStyle(
            "cellule", parent=base["Normal"], fontSize=8.8, leading=12,
            textColor=ENCRE_DOUCE,
        ),
        "cellule_forte": ParagraphStyle(
            "cellule_forte", parent=base["Normal"], fontSize=8.8, leading=12,
            textColor=ENCRE, fontName="Helvetica-Bold",
        ),
    }


S = _styles()


def para(texte: str, style: str = "corps"):
    return Paragraph(texte, S[style])


def puces(elements: list[str]):
    return ListFlowable(
        [ListItem(para(e, "puce"), leftIndent=12) for e in elements],
        bulletType="bullet",
        bulletFontSize=9,
        bulletOffsetY=-1.5,
        leftIndent=14,
        spaceBefore=2,
        spaceAfter=4,
    )


def bloc_code(lignes: list[str]):
    """Une commande à recopier. Fond gris pour qu'on la distingue du texte."""
    contenu = Paragraph("<br/>".join(lignes), S["code"])
    t = Table([[contenu]], colWidths=[165 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), FOND),
                ("BOX", (0, 0), (-1, -1), 0.4, FILET),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return [Spacer(1, 2), t, Spacer(1, 7)]


def encadre(titre: str, texte: str, ton=ALERTE, fond=ALERTE_FOND):
    contenu = Paragraph(
        f'<font color="{ton.hexval()}"><b>{titre}</b></font><br/>{texte}', S["alerte"]
    )
    t = Table([[contenu]], colWidths=[165 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), fond),
                ("BOX", (0, 0), (-1, -1), 0.6, ton),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return [Spacer(1, 3), t, Spacer(1, 8)]


def tableau(entetes: list[str], lignes: list[list[str]], largeurs: list[float]):
    donnees = [[Paragraph(e, S["cellule_forte"]) for e in entetes]]
    donnees += [[Paragraph(c, S["cellule"]) for c in ligne] for ligne in lignes]
    t = Table(donnees, colWidths=largeurs, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), FOND),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, FILET),
                ("LINEBELOW", (0, 1), (-1, -2), 0.4, FILET),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


def _pied(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(DISCRET)
    canvas.drawString(20 * mm, 12 * mm, "TriCV — Guide de déploiement")
    canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, f"page {canvas.getPageNumber()}")
    canvas.setStrokeColor(FILET)
    canvas.setLineWidth(0.4)
    canvas.line(20 * mm, 16 * mm, A4[0] - 20 * mm, 16 * mm)
    canvas.restoreState()


def contenu() -> list:
    h: list = []

    # --- couverture ---------------------------------------------------------
    h.append(para("Mettre TriCV en service", "titre"))
    h.append(
        para(
            "Guide de déploiement — Kapi Consult · "
            f"version du {date.today().strftime('%d/%m/%Y')}",
            "sous_titre",
        )
    )
    h.append(HRFlowable(width="100%", thickness=0.8, color=FILET, spaceAfter=14))

    h.append(
        para(
            "Ce document s'adresse à la personne qui installe et met TriCV en service. "
            "Il suppose un accès administrateur au serveur, et aucune connaissance du "
            "code de l'application. Chaque étape dit ce qu'il faut faire et, quand cela "
            "change la décision, pourquoi."
        )
    )
    h.append(
        para(
            "Deux documents l'accompagnent. Le <b>guide de configuration de la boîte de "
            "candidatures</b> détaille le paramétrage IMAP, qui est la partie la plus "
            "délicate ; il est cité au bon endroit. Le fichier "
            "<b>.env.example</b>, à la racine du dépôt, liste toutes les variables lues "
            "par l'application, chacune commentée."
        )
    )

    # --- 1. architecture ----------------------------------------------------
    h.append(para("1. Ce qu'il faut installer, et où", "section"))
    h.append(
        para(
            "TriCV se découpe en deux moitiés qui n'ont ni le même public ni les mêmes "
            "exigences. Les séparer n'est pas une commodité technique : c'est ce qui "
            "permet d'exposer à Internet uniquement ce qui doit l'être."
        )
    )
    h.append(
        tableau(
            ["Moitié", "Qui l'utilise", "Où la placer"],
            [
                [
                    "<b>Faces publiques</b><br/>page des avis, formulaire de candidature, "
                    "espace de suivi du promoteur",
                    "Les candidats et les clients, depuis Internet",
                    "Un petit serveur hébergé, joignable publiquement, avec un nom de "
                    "domaine et un certificat HTTPS",
                ],
                [
                    "<b>Outil interne</b><br/>grilles, dossiers, notes, entretiens, "
                    "rapports",
                    "Les chargés de recrutement du cabinet",
                    "Le réseau du cabinet, ou le même serveur derrière une "
                    "restriction d'accès",
                ],
            ],
            [52 * mm, 48 * mm, 65 * mm],
        )
    )
    h.append(Spacer(1, 8))
    h.append(
        para(
            "Les deux moitiés sont un seul programme et partagent une seule base de "
            "données : il n'y a qu'une installation à faire. Ce qui se sépare est "
            "<b>l'exposition</b> — quelles adresses sont ouvertes depuis Internet."
        )
    )
    h.extend(
        encadre(
            "Ce qui ne doit jamais être exposé",
            "Les adresses commençant par <b>/api/v1/</b> autres que "
            "<b>/api/v1/public/</b> et <b>/api/v1/espace-client/</b> donnent accès aux "
            "dossiers de tous les candidats. Si l'outil interne est mis en ligne, il doit "
            "l'être derrière une restriction — VPN, filtrage par adresse IP, ou "
            "authentification du serveur web en amont. Un mot de passe applicatif seul "
            "ne suffit pas à justifier d'ouvrir cette surface à Internet.",
            DANGER,
            DANGER_FOND,
        )
    )

    h.append(para("Prérequis", "etape"))
    h.append(
        puces(
            [
                "<b>Docker et Docker Compose</b> — la voie recommandée : tout est fourni, "
                "y compris PostgreSQL et les modèles de reconnaissance d'entités.",
                "<b>Ou bien</b> Python 3.12, Node 20 et PostgreSQL 15, pour une "
                "installation sans Docker.",
                "Un <b>nom de domaine</b> pointant sur le serveur, et un certificat "
                "HTTPS. Les candidats déposent des pièces d'identité : le chiffrement du "
                "transport n'est pas optionnel.",
            ]
        )
    )
    h.extend(
        encadre(
            "Python 3.13 : à éviter",
            "spaCy 3.8 ne le prend pas en charge. L'application fonctionne, mais "
            "l'expurgation des données personnelles retombe sur des expressions "
            "régulières et laisse passer certains noms de villes isolés. Utilisez "
            "Python 3.12, ou l'image Docker qui embarque la bonne version.",
        )
    )


    # --- 2. installation ----------------------------------------------------
    h.append(para("2. Installation", "section"))

    h.append(para("2.1 — Récupérer le dépôt et préparer la configuration", "etape"))
    h.extend(
        bloc_code(
            [
                "git clone &lt;adresse-du-depot&gt; tricv",
                "cd tricv",
                "cp .env.example .env",
            ]
        )
    )
    h.append(
        para(
            "Le fichier <b>.env</b> n'est jamais versionné : il contient les secrets de "
            "cette installation. Le <b>.env.example</b> reste la référence de ce qui "
            "existe."
        )
    )

    h.append(para("2.2 — Poser les secrets", "etape"))
    h.append(
        para(
            "Trois valeurs livrées avec le dépôt doivent changer avant toute mise en "
            "service. Le contrôle de l'étape 5 refuse de valider tant qu'elles sont en "
            "place."
        )
    )
    h.append(
        tableau(
            ["Variable", "Ce qu'elle protège", "Comment la produire"],
            [
                [
                    "<b>JWT_SECRET</b>",
                    "Les jetons de session. Qui le connaît peut se faire passer pour "
                    "n'importe quel utilisateur et lire tous les dossiers.",
                    "<font face='Courier'>python -c \"import secrets; "
                    "print(secrets.token_urlsafe(48))\"</font>",
                ],
                [
                    "<b>SEED_ADMIN_PASSWORD</b>",
                    "Le premier compte administrateur.",
                    "Un mot de passe long, choisi pour cette installation, transmis à "
                    "son titulaire hors du fichier.",
                ],
                [
                    "<b>POSTGRES_PASSWORD</b><br/>et <b>DATABASE_URL</b>",
                    "L'accès direct à la base.",
                    "Un mot de passe propre, recopié à l'identique dans les deux "
                    "variables.",
                ],
            ],
            [38 * mm, 62 * mm, 65 * mm],
        )
    )
    h.append(Spacer(1, 8))
    h.extend(
        encadre(
            "Changer JWT_SECRET déconnecte tout le monde",
            "C'est sans gravité, mais cela se produit une fois : faites-le avant "
            "d'ouvrir l'application à l'équipe, pas après.",
        )
    )

    h.append(para("2.3 — Adresses et exposition", "etape"))
    h.append(
        puces(
            [
                "<b>URL_PUBLIQUE</b> — l'adresse par laquelle candidats et clients "
                "atteignent l'application, par exemple "
                "<font face='Courier'>https://recrutement.kapiconsult.tg</font>. Elle sert "
                "à construire les liens envoyés par courriel. Le serveur ne connaît que "
                "son adresse d'écoute et ne peut pas la deviner : sans cette variable, "
                "l'ouverture d'un accès client n'a pas de lien à envoyer.",
                "<b>CORS_ORIGINS</b> — la liste, séparée par des virgules, des adresses "
                "depuis lesquelles l'interface appelle l'API. Elle doit inclure "
                "l'adresse publique, et le site du cabinet si le formulaire de "
                "candidature y est intégré.",
                "<b>VITE_API_URL</b> — l'adresse de l'API, inscrite dans l'interface au "
                "moment de sa construction. La changer demande de reconstruire "
                "l'interface.",
            ]
        )
    )

    h.append(para("2.4 — Démarrer", "etape"))
    h.extend(bloc_code(["docker compose up -d", "docker compose exec api alembic upgrade head"]))
    h.append(
        para(
            "La seconde commande crée le schéma de la base. Elle est <b>obligatoire</b> "
            "et se rejoue sans risque : elle n'applique que ce qui manque."
        )
    )
    h.extend(
        encadre(
            "Sans Docker",
            "Créez la base PostgreSQL, installez les dépendances "
            "(<font face='Courier'>pip install -r backend/requirements.txt</font>), puis "
            "lancez <font face='Courier'>alembic upgrade head</font> depuis "
            "<font face='Courier'>backend/</font>. L'interface se construit avec "
            "<font face='Courier'>npm ci &amp;&amp; npm run build</font> depuis "
            "<font face='Courier'>frontend/</font> ; servez le contenu de "
            "<font face='Courier'>frontend/dist</font> avec le serveur web de votre choix.",
        )
    )


    # --- 3. courriel --------------------------------------------------------
    h.append(para("3. Le courriel", "section"))
    h.append(
        para(
            "TriCV lit une boîte pour y récupérer les candidatures, et en écrit une pour "
            "les convocations et les accès clients."
        )
    )
    h.append(
        para(
            "<b>Posez-les au déploiement</b>, dans <font face='Courier'>.env</font>, avec "
            "le reste de la configuration serveur — c'est le moment où l'on a déjà les "
            "identifiants en main et un accès à la machine. L'écran <b>Paramètres</b> "
            "reste disponible pour les corriger ensuite sans rouvrir cet accès : une "
            "adresse de recrutement peut changer avec les campagnes, et un mot de passe "
            "peut être révoqué. Ce qui est enregistré dans l'application <b>prime</b> sur "
            "le fichier, qui ne sert alors plus qu'à amorcer une installation neuve."
        )
    )

    h.append(para("3.1 — Réception (IMAP)", "etape"))
    h.append(
        para(
            "Le paramétrage complet, fournisseur par fournisseur, et la façon de vérifier "
            "que le relevé fonctionne, font l'objet d'un document séparé : "
            "<b>Guide-configuration-boite-candidatures.pdf</b>. Suivez-le avant de "
            "revenir ici."
        )
    )
    h.extend(
        encadre(
            "Boîte Microsoft : prévoyez un administrateur, et du délai",
            "Une adresse Outlook ou Microsoft 365 ne s'ouvre plus avec un mot de passe — "
            "Microsoft a supprimé l'authentification de base sur IMAP, POP et SMTP, y "
            "compris les « mots de passe d'application ». Il faut déclarer TriCV dans "
            "Entra ID et lui accorder l'accès à cette boîte, ce qui demande des droits "
            "d'administrateur. Ce n'est pas long, mais cela dépend de quelqu'un d'autre : "
            "à lancer en début d'installation, pas la veille de la mise en service. Le "
            "guide de la boîte contient, à l'étape M4, une demande à transmettre telle "
            "quelle à l'administrateur. Côté application, le chemin se choisit dans "
            "<b>Paramètres → Courriel → Par où passe le courriel</b> : « Microsoft 365 "
            "(Graph) » remplace alors les champs IMAP par les trois valeurs de "
            "l'inscription Entra.",
        )
    )

    h.append(para("3.2 — Envoi (SMTP)", "etape"))
    h.append(
        para(
            "Dans <b>Paramètres → Courriel → Envoi de courriels</b>, renseignez le serveur, le "
            "compte et le mot de passe, puis l'adresse d'expédition — celle que les "
            "candidats verront. Le bouton <b>Tester l'envoi</b> ouvre une session sans "
            "rien expédier : une erreur d'identifiants doit se découvrir là, et non au "
            "moment où trente convocations partent."
        )
    )
    h.append(
        tableau(
            ["Fournisseur", "Serveur", "Port", "Mot de passe"],
            [
                [
                    "Gmail / Google Workspace",
                    "smtp.gmail.com",
                    "587",
                    "Un <b>mot de passe d'application</b>, jamais celui du compte. "
                    "Il se crée dans Compte Google › Sécurité, après avoir activé la "
                    "validation en deux étapes.",
                ],
                [
                    "<b>Microsoft 365 / Outlook</b>",
                    "smtp.office365.com",
                    "587",
                    "<b>Aucun mot de passe ne fonctionne</b>, pas même un « mot de passe "
                    "d'application » : Microsoft a retiré l'authentification de base de "
                    "SMTP comme d'IMAP. Renseignez l'accès OAuth (tenant, application, "
                    "secret) — le même que pour la réception.",
                ],
                [
                    "Hébergeur du domaine",
                    "Fourni par l'hébergeur",
                    "587 ou 465",
                    "Le mot de passe de la boîte. Le port 465 chiffre dès l'ouverture "
                    "et ignore le réglage STARTTLS.",
                ],
            ],
            [38 * mm, 38 * mm, 15 * mm, 74 * mm],
        )
    )
    h.append(Spacer(1, 8))
    h.extend(
        encadre(
            "Sans configuration d'envoi, rien ne se perd",
            "Les convocations se rédigent quand même dans l'application et se recopient "
            "à la main ; l'ouverture d'un accès client affiche le lien d'activation à "
            "transmettre soi-même. L'application <b>refuse</b> d'envoyer plutôt que de "
            "faire disparaître un message en silence.",
        )
    )

    # --- 4. comptes ---------------------------------------------------------
    h.append(para("4. Les comptes", "section"))
    h.append(
        para(
            "Un compte donne accès aux dossiers de <b>tous</b> les candidats de "
            "<b>tous</b> les mandats. Il n'existe pas de cloisonnement par chargé de "
            "recrutement : c'est un choix assumé pour un cabinet de cette taille, mais "
            "il rend la création de comptes une décision, pas une formalité."
        )
    )
    h.append(
        puces(
            [
                "Le premier compte administrateur est créé au démarrage à partir de "
                "<b>SEED_ADMIN_EMAIL</b> et <b>SEED_ADMIN_PASSWORD</b>.",
                "Les suivants se créent dans <b>Paramètres → Utilisateurs</b> : nom, "
                "adresse, mot de passe initial, rôle. Le mot de passe est choisi par "
                "l'administrateur et transmis par lui — l'application ne l'envoie pas.",
                "L'inscription libre n'est donc plus nécessaire pour monter l'équipe. "
                "Laissez-la décochée dans <b>Paramètres → Général</b> : ouverte sans "
                "code, elle laisse quiconque atteint la page lire tous les dossiers.",
                "La ligne de commande reste pour le dépannage — le jour où plus aucun "
                "administrateur ne peut se connecter.",
            ]
        )
    )
    h.append(para("Gérer les comptes en ligne de commande", "etape"))
    h.extend(
        bloc_code(
            [
                "docker compose exec api python comptes.py lister",
                "docker compose exec api python comptes.py promouvoir adresse@exemple.tg",
                "docker compose exec api python comptes.py desactiver adresse@exemple.tg",
            ]
        )
    )
    h.append(
        para(
            "L'outil refuse de retirer le dernier administrateur actif : sans cette "
            "garde, une erreur de manipulation fermerait définitivement l'accès aux "
            "réglages."
        )
    )


    # --- 5. contrôle avant usage -------------------------------------------
    h.append(para("5. Le contrôle avant mise en service", "section"))
    h.append(
        para(
            "Une installation qui démarre n'est pas une installation prête. Un serveur "
            "peut démarrer parfaitement avec le secret du dépôt, le mot de passe "
            "administrateur d'origine et onze candidats fictifs en base — et perdre les "
            "données du premier candidat réel qui se présente. Le contrôle répond à une "
            "seule question : <b>cette installation peut-elle recevoir de vrais "
            "dossiers ?</b>"
        )
    )
    h.extend(bloc_code(["docker compose exec api python preflight.py"]))
    h.append(
        tableau(
            ["Niveau", "Ce que cela veut dire"],
            [
                [
                    "<b>BLOQUANT</b>",
                    "À corriger avant de recevoir un dossier réel. Le contrôle sort en "
                    "erreur tant qu'il en reste un.",
                ],
                [
                    "<b>À VOIR</b>",
                    "Acceptable si c'est un choix ; à connaître sinon. Par exemple une "
                    "clé Gemini gratuite, dont les conditions autorisent "
                    "l'entraînement sur ce qui est envoyé.",
                ],
                ["<b>OK</b>", "Vérifié."],
            ],
            [28 * mm, 137 * mm],
        )
    )
    h.append(Spacer(1, 8))
    h.extend(
        encadre(
            "Les données de démonstration sont bloquantes",
            "Le dépôt installe onze candidats fictifs pour la prise en main. Mélangés à "
            "de vrais dossiers, ils faussent les grilles et le vivier. Le contrôle les "
            "détecte à leur adresse en <font face='Courier'>@example.com</font> et "
            "refuse de valider tant qu'ils sont là.",
        )
    )

    # --- 6. confidentialité -------------------------------------------------
    h.append(para("6. Ce qui sort de la machine, et ce qui n'en sort pas", "section"))
    h.append(
        para(
            "Le classement des dossiers est entièrement calculé sur place : barème, "
            "éligibilité, notes, grilles. Aucun modèle de langage n'y intervient. "
            "L'assistance automatique sert à quatre choses seulement — lire un CV pour "
            "en proposer le parcours, juger l'équivalence d'un diplôme, rédiger un "
            "brouillon d'avis, proposer un texte de rapport — et ce qu'elle produit "
            "porte une provenance qui l'empêche d'éliminer quiconque sans relecture."
        )
    )
    h.append(
        tableau(
            ["Réglage", "Effet", "Recommandation"],
            [
                [
                    "<b>PII_REDACTION</b>",
                    "À <font face='Courier'>true</font>, le texte est extrait sur place "
                    "et les identifiants — nom, adresse, téléphone, courriel — sont "
                    "retirés avant tout envoi. À <font face='Courier'>false</font>, le "
                    "fichier d'origine part tel quel.",
                    "<b>true</b>. Le passer à false est une décision à documenter.",
                ],
                [
                    "<b>REDACT_DEMOGRAPHICS</b>",
                    "Retire l'âge, le sexe, la date de naissance et la nationalité du "
                    "contenu envoyé pour la notation. Ces données restent visibles des "
                    "chargés de recrutement et servent aux conditions d'âge ou de "
                    "nationalité, qui sont évaluées sur place.",
                    "<b>true</b>. Noter sur ces attributs est discriminatoire dans la "
                    "plupart des droits applicables.",
                ],
                [
                    "<b>LLM_PROVIDER</b>",
                    "Le fournisseur qui lit les dossiers. "
                    "<font face='Courier'>gemini</font>, "
                    "<font face='Courier'>anthropic</font>, "
                    "<font face='Courier'>ollama</font> (local) ou "
                    "<font face='Courier'>openai</font> — ce dernier désignant une "
                    "adresse, pas une marque : Mistral, Groq, OpenRouter, un serveur "
                    "vLLM du cabinet.",
                    "Voir la section 6 bis. Toute offre gratuite s'entraîne sur ce "
                    "qu'on lui envoie, sauf à le refuser quand c'est possible.",
                ],
                [
                    "<b>LLM_FALLBACK</b>",
                    "Le fournisseur de secours, essayé quand le principal ne peut "
                    "pas servir : allocation épuisée, ou service en panne après "
                    "quatre tentatives. Dans ces deux cas seulement — une réponse "
                    "illisible ou une clé refusée sont des défauts à voir, pas à "
                    "contourner.",
                    "Utile si le cabinet dispose de deux clés. Lire la réserve de "
                    "confidentialité en section 6 bis avant de l'activer.",
                ],
                [
                    "<b>LLM_PROSE_PROVIDER</b>",
                    "Le fournisseur qui <b>rédige</b> les rapports, quand ce n'est pas "
                    "celui qui dépouille.",
                    "Le plus sobre en invention. Un rapport part au client sous la "
                    "signature du cabinet.",
                ],
                [
                    "<b>LLM_MAX_CONCURRENCY</b>",
                    "Le nombre d'appels simultanés au fournisseur.",
                    "<b>1</b> sur une offre gratuite limitée à une requête par "
                    "seconde — au-delà, les appels partent en rafale, se font "
                    "refuser, et attendent la reprise.",
                ],
            ],
            # Première colonne élargie : « LLM_MAX_CONCURRENCY » se coupait en
            # « LLM_MAX_CONCURREN / CY », et un nom de variable coupé au milieu
            # se recopie faux.
            [50 * mm, 62 * mm, 53 * mm],
        )
    )

    # --- 6 bis. le choix du fournisseur ------------------------------------
    h.append(para("6 bis. Choisir le fournisseur du modèle", "section"))
    h.append(
        para(
            "Le chiffre qui décide n'est pas le nombre de requêtes par jour. Un "
            "dépouillement envoie jusqu'à 24 000 caractères de CV, soit environ "
            "7 000 jetons : une offre généreuse en requêtes mais plafonnée en "
            "<b>jetons par jour</b> s'épuise bien avant d'avoir consommé ses requêtes. "
            "La rédaction, elle, coûte quelques centaines de jetons par section."
        )
    )
    h.append(
        tableau(
            ["Fournisseur", "Offre gratuite", "Dossiers par jour"],
            [
                [
                    "<b>Mistral</b>",
                    "1 requête/s. La famille <font face='Courier'>ministral</font> "
                    "seule est allouée : <font face='Courier'>mistral-small</font> et "
                    "<font face='Courier'>medium</font> sont à zéro et répondent 429.",
                    "Plusieurs milliers",
                ],
                ["Gemini 2.5 Flash-Lite", "15 req/min, 1 000 req/jour", "~1 000"],
                ["Gemini 2.5 Flash", "10 req/min, 250 req/jour", "~250"],
                [
                    "Groq <font face='Courier'>llama-3.3-70b</font>",
                    "30 req/min mais <b>100 000 jetons/jour</b>",
                    "~13",
                ],
                [
                    "Ollama, sur place",
                    "Aucune limite, et rien ne sort des murs. Mais "
                    "<b>52 s par dossier</b> mesurées avec "
                    "<font face='Courier'>qwen3:8b</font>, modèle entièrement "
                    "chargé en carte graphique.",
                    "Illimité, mais plus de 2 h pour 150",
                ],
            ],
            [38 * mm, 72 * mm, 55 * mm],
        )
    )
    h.extend(
        encadre(
            "Le modèle sur place est un secours, pas un choix de tous les jours",
            "Mesuré le 15 septembre 2026 sur le corpus du cabinet, "
            "<font face='Courier'>qwen3:8b</font> lit 13 diplômes sur 14 et 17 "
            "expériences sur 18, contre 14 et 18 pour Gemini comme pour Mistral. "
            "Les deux écarts sont la même faute, et ce n'est pas une invention : le "
            "modèle retient la première date qu'il voit — « depuis mars 2018 » "
            "devient janvier 2018. Le <i>niveau</i> du diplôme, seul élément que le "
            "barème note, reste juste.<br/><br/>"
            "Ce n'est donc pas la lecture qui le disqualifie, c'est l'horloge : "
            "52 s par dossier, plus de deux heures pour un mandat de 150. "
            "Gardez-le pour les deux cas où rien d'autre ne répond — les quotas "
            "épuisés en cours de mandat, ou un client qui refuse que les dossiers "
            "sortent de chez lui.",
        )
    )
    h.extend(
        encadre(
            "Mesurer avant de faire confiance",
            "Un fournisseur qui coûte moins et lit moins bien n'est pas une économie : "
            "l'exactitude du dépouillement est ce sur quoi repose toute la "
            "présélection. Après chaque changement de fournisseur ou de modèle, "
            "lancer les deux contrôles ci-dessous. Le premier vérifie qu'une section "
            "de rapport revient en prose française et n'invente aucun nom ; le second "
            "mesure la lecture de six dossiers et se compare au repère inscrit dans "
            "le script (14/14 diplômes, 18/18 expériences).",
        )
    )
    h.extend(
        bloc_code(
            [
                "cd backend",
                ".venv/Scripts/python.exe tools/verifier_prose.py",
                ".venv/Scripts/python.exe -m tools.evaluer_extraction essai",
            ]
        )
    )
    h.append(
        para(
            "<b>La confidentialité n'est pas la même partout.</b> L'offre gratuite de "
            "Google s'entraîne sur ce qui lui est envoyé, sans réglage pour le "
            "refuser ; celle de Mistral aussi, mais le refus se pose dans la console "
            "(Admin &gt; Privacy) sans changer d'offre. C'est à faire avant le premier "
            "dossier réel. Un secours qui descend de l'un vers l'autre déplace donc de "
            "vrais parcours d'un fournisseur qui les oublie vers un fournisseur qui "
            "les conserve : c'est une décision à prendre une fois, en connaissance de "
            "cause. Dans tous les cas, l'expurgation retire le nom, l'adresse, le "
            "téléphone, le courriel et la date de naissance avant l'envoi."
        )
    )
    h.append(
        para(
            "<b>Deux clés valent mieux qu'une, et pas seulement pour le quota.</b> "
            "Un fournisseur tombe en panne comme il s'épuise : un « 503, forte "
            "demande » qui survit aux quatre tentatives laisse l'application sans "
            "modèle, alors qu'une seconde clé en état de marche ne servirait à "
            "rien. Le secours prend le relais dans les deux cas, et le fournisseur "
            "écarté est mis de côté un quart d'heure plutôt que réinterrogé à "
            "chaque dossier. Le journal dit lequel des deux motifs a joué."
        )
    )
    h.extend(
        encadre(
            "Ce qu'une bascule change, et qu'il faut savoir",
            "Deux modèles ne lisent pas un dossier de la même façon. Un mandat "
            "dépouillé moitié par l'un, moitié par l'autre produit une grille dont "
            "les lignes ne viennent pas du même lecteur, et un candidat qui "
            "conteste son élimination a le droit de savoir lequel a lu son "
            "dossier. Chaque bascule est donc journalisée en nommant les deux "
            "fournisseurs.",
        )
    )
    h.append(
        para(
            "<b>Le modèle sur place.</b> "
            "<font face='Courier'>LLM_PROVIDER=ollama</font> est la seule "
            "configuration où le dossier d'un candidat ne sort pas du bâtiment : ni "
            "clé, ni quota, ni conditions à relire. Le coût est en matériel et en "
            "temps de réponse. Un modèle de 7 à 8 milliards de paramètres en 4 bits "
            "occupe environ 5 Go de mémoire vive graphique ; sans carte, il tourne "
            "sur le processeur, plusieurs fois plus lentement."
        )
    )
    h.extend(
        encadre(
            "Ce qui coûte du temps n'est pas la machine, c'est le modèle",
            "Mesuré le 15 septembre 2026 : <b>52 s par dossier</b> avec "
            "<font face='Courier'>qwen3:8b</font> — et le modèle tenait "
            "<b>entièrement</b> dans la carte graphique d'un portable. Le matériel "
            "n'est donc pas en cause. "
            "<font face='Courier'>qwen3</font> est un modèle qui <i>raisonne</i> "
            "avant de répondre : il rédige son cheminement, que l'application jette "
            "ensuite. On paie ce cheminement à chaque dossier.<br/><br/>"
            "Si le modèle sur place doit servir à autre chose qu'un secours, "
            "essayez-en un qui ne raisonne pas à voix haute — "
            "<font face='Courier'>llama3.1:8b</font>, "
            "<font face='Courier'>mistral:7b</font> — et mesurez-le avec "
            "<font face='Courier'>tools.evaluer_extraction</font> avant de le "
            "retenir. La vitesse ne vaut rien si la lecture se dégrade.",
        )
    )
    h.extend(
        bloc_code(
            [
                "docker compose --profile local-llm up -d ollama",
                "docker compose exec ollama ollama pull qwen3:8b",
                "",
                "# puis dans .env :",
                "LLM_PROVIDER=ollama",
                "OLLAMA_MODEL=qwen3:8b",
                "OLLAMA_BASE_URL=http://ollama:11434",
            ]
        )
    )
    h.append(
        para(
            "Pour une carte NVIDIA, décommenter le bloc "
            "<font face='Courier'>deploy</font> du service "
            "<font face='Courier'>ollama</font> dans "
            "<font face='Courier'>docker-compose.yml</font> — il exige le NVIDIA "
            "Container Toolkit. Le laisser actif sans carte empêche le service de "
            "démarrer, d'où sa mise en commentaire par défaut."
        )
    )


    # --- 7. exploitation ----------------------------------------------------
    h.append(para("7. Sauvegardes et exploitation", "section"))
    h.append(
        para(
            "Deux choses sont à sauvegarder, et perdre l'une sans l'autre laisse un "
            "système incohérent : la base de données, et les fichiers déposés."
        )
    )
    h.append(
        puces(
            [
                "<b>La base</b> — dossiers, notes, grilles, échanges, rapports. "
                "Sauvegarde quotidienne recommandée.",
                "<b>Les pièces</b> — le répertoire désigné par "
                "<font face='Courier'>STORAGE_PATH</font>, ou le compartiment S3 si "
                "<font face='Courier'>STORAGE_BACKEND=s3</font>.",
            ]
        )
    )
    h.extend(
        bloc_code(
            [
                "# Base",
                "docker compose exec -T db pg_dump -U tricv tricv &gt; sauvegarde-$(date +%F).sql",
                "",
                "# Pièces (stockage local)",
                "tar czf pieces-$(date +%F).tar.gz /chemin/vers/STORAGE_PATH",
            ]
        )
    )
    h.extend(
        encadre(
            "Une sauvegarde jamais restaurée n'est pas une sauvegarde",
            "Restaurez-la une fois sur une installation d'essai, avant d'en avoir "
            "besoin. C'est le seul moyen de savoir qu'elle est complète.",
        )
    )

    h.append(para("Maîtriser l'espace disque", "etape"))
    h.append(
        para(
            "Les pièces s'accumulent. Il n'existe aucune limite de taille au dépôt : "
            "refuser un dossier valable parce qu'un scan de diplômes est volumineux n'a "
            "pas de sens. L'espace se maîtrise autrement — en <b>purgeant les fichiers "
            "des mandats archivés</b> depuis <b>Archives › Purger les fichiers</b>. Les "
            "dossiers, les notes et les profils restent ; seuls les fichiers "
            "disparaissent, et le vivier garde de quoi retrouver une personne."
        )
    )

    h.append(para("Mises à jour", "etape"))
    h.extend(
        bloc_code(
            [
                "git pull",
                "docker compose build",
                "docker compose up -d",
                "docker compose exec api alembic upgrade head",
            ]
        )
    )
    h.append(
        para(
            "La dernière commande est celle qu'on oublie. Sans elle, le code attend des "
            "colonnes que la base n'a pas, et les écritures échouent sans rien "
            "expliquer. Sauvegardez avant."
        )
    )

    # --- 8. première utilisation -------------------------------------------
    h.append(para("8. La première mise en service", "section"))
    h.append(
        para(
            "Dans l'ordre, une fois l'installation faite :"
        )
    )
    h.append(
        puces(
            [
                "Effacer les données de démonstration et repartir d'une base vide.",
                "Relancer <b>preflight.py</b> jusqu'à n'avoir plus aucun point bloquant.",
                "Créer les comptes de l'équipe, puis refermer l'inscription libre.",
                "Configurer la boîte de candidatures, et faire un <b>aperçu</b> du "
                "relevé — il montre ce qu'un relevé ferait, sans rien créer.",
                "Configurer l'envoi, et le tester.",
                "Saisir un premier mandat réel, un poste, un avis — et vérifier que le "
                "lien de candidature s'ouvre depuis un appareil extérieur au réseau du "
                "cabinet.",
            ]
        )
    )
    h.extend(
        encadre(
            "Le point de non-retour",
            "Dès qu'un candidat réel a déposé un dossier, l'installation n'est plus "
            "réinitialisable sans perte. Tout ce qui précède doit être fait avant de "
            "diffuser le premier lien de candidature.",
            DANGER,
            DANGER_FOND,
        )
    )

    h.extend(_annexe_configuration())

    h.append(Spacer(1, 10))
    h.append(HRFlowable(width="100%", thickness=0.6, color=FILET, spaceAfter=8))
    h.append(
        para(
            "<font size=8 color='#6b7280'>TriCV classe et recommande ; les chargés de "
            "recrutement de Kapi Consult décident. Aucun dossier n'est écarté sur une "
            "donnée qu'une personne n'a pas confirmée.</font>",
            "corps",
        )
    )
    return h


# --- annexe : le paramétrage complet ----------------------------------------
#
# Le corps du guide dit quoi faire dans l'ordre. Cette annexe dit *tout* ce qui
# se règle, pour la personne qui reprend une installation existante et doit
# savoir ce qu'elle a sous les yeux. Rien n'y est implicite : une variable
# absente du tableau est une variable que l'application ne lit pas.
#
# Trois colonnes, et la troisième est la seule qui compte vraiment : ce qu'il
# faut y mettre *ici*, pas ce que la variable signifie en général.

# Chaque entrée : (nom, effet, à renseigner)
_ENV_BASE = [
    ("DATABASE_URL", "L'adresse de la base.", "Fournie par Compose. À ne changer que pour une base externe — le pilote doit être <font face='Courier'>asyncpg</font>."),
    ("POSTGRES_USER / _PASSWORD / _DB", "Les identifiants que le service de base crée à sa première mise en route.", "À garder cohérents avec DATABASE_URL. Changer le mot de passe après coup demande de refaire le volume."),
]

_ENV_SECURITE = [
    ("JWT_SECRET", "Signe les jetons de session. Qui le connaît peut se faire passer pour n'importe qui.", "<b>Obligatoire.</b> Une chaîne aléatoire longue, propre à cette installation. Jamais celle du dépôt."),
    ("ACCESS_TOKEN_MINUTES", "Durée d'une session avant renouvellement.", "30. À baisser sur un poste partagé."),
    ("REFRESH_TOKEN_DAYS", "Durée avant reconnexion complète.", "7."),
    ("SEED_ADMIN_EMAIL / _PASSWORD", "Le premier compte, créé au peuplement initial.", "<b>À changer avant toute mise en service.</b> Le mot de passe du dépôt est public."),
    ("ALLOW_SELF_REGISTRATION", "Autorise la création de comptes depuis la page de connexion.", "<font face='Courier'>true</font> le temps de créer l'équipe, puis <font face='Courier'>false</font>. Un compte recruteur lit tous les dossiers."),
    ("SIGNUP_CODE", "Code exigé à l'inscription libre.", "Une chaîne connue de l'équipe seule, tant que l'inscription est ouverte."),
    ("SIGNUP_RATE_LIMIT_PER_HOUR", "Inscriptions par heure et par adresse IP.", "10."),
]

_ENV_MODELE = [
    ("LLM_PROVIDER", "Qui lit les dossiers : <font face='Courier'>gemini</font>, <font face='Courier'>anthropic</font>, <font face='Courier'>ollama</font>, <font face='Courier'>openai</font>.", "Voir la section 6 bis. <font face='Courier'>openai</font> désigne une adresse, pas une marque."),
    ("LLM_MODEL", "Le modèle du fournisseur principal.", "Obligatoire pour <font face='Courier'>openai</font>, qui n'a pas de défaut. Ex. <font face='Courier'>ministral-14b-latest</font>."),
    ("LLM_BASE_URL", "L'adresse du fournisseur, avec <font face='Courier'>openai</font>.", "<font face='Courier'>https://api.mistral.ai/v1</font> pour Mistral."),
    ("LLM_API_KEY", "Sa clé.", "Créée chez le fournisseur. Jamais dans un dépôt."),
    ("GEMINI_API_KEY / ANTHROPIC_API_KEY", "Les clés de ces deux fournisseurs.", "Selon celui qu'on emploie, principal ou secours."),
    ("OLLAMA_BASE_URL", "L'adresse du serveur local.", "<font face='Courier'>http://ollama:11434</font> sous Compose."),
    ("GEMINI_MODEL, OPENAI_MODEL,<br/>ANTHROPIC_MODEL, OLLAMA_MODEL", "Le modèle propre à chaque fournisseur.", "<b>Nécessaire dès qu'une chaîne existe</b> : LLM_MODEL ne nomme que le modèle du principal, et « ministral-14b-latest » n'a aucun sens pour Google."),
    ("LLM_FALLBACK", "Le secours, quand le principal ne peut pas servir — quota épuisé ou panne.", "Ex. <font face='Courier'>gemini</font>. Vide : aucun secours. Lire la réserve de confidentialité en 6 bis."),
    ("LLM_PROSE_PROVIDER", "Qui <b>rédige</b> les rapports, quand ce n'est pas qui dépouille.", "Le plus sobre en invention : un rapport part au client sous la signature du cabinet."),
    ("LLM_MAX_CONCURRENCY", "Appels simultanés au fournisseur.", "<b>1</b> sur une offre limitée à une requête par seconde."),
    ("LLM_TIMEOUT_SECONDS", "Délai avant d'abandonner un appel.", "120. Un modèle local lent peut demander davantage."),
    ("LLM_LOG_PAYLOAD", "Écrit dans le journal le texte envoyé au modèle.", "<font face='Courier'>true</font> pour vérifier l'expurgation une fois, <b>puis false</b> : le journal contient sinon des parcours réels."),
]

_ENV_CONFIDENTIALITE = [
    ("PII_REDACTION", "Extrait le texte sur place et retire nom, adresse, téléphone, courriel et date de naissance avant tout envoi.", "<b>true.</b> Le passer à false envoie le fichier d'origine tel quel : une décision à documenter."),
    ("REDACT_DEMOGRAPHICS", "Retire âge, sexe et nationalité du contenu servant à noter. Ces données restent visibles des RH et servent aux conditions.", "<b>true.</b> Noter sur ces attributs est discriminatoire dans la plupart des droits applicables."),
]

_ENV_STOCKAGE = [
    ("STORAGE_BACKEND", "<font face='Courier'>local</font> ou <font face='Courier'>s3</font>.", "<font face='Courier'>local</font> sauf besoin contraire."),
    ("STORAGE_PATH", "Le répertoire des pièces déposées.", "Doit être sur un volume sauvegardé. Les perdre, c'est perdre les dossiers."),
    ("S3_BUCKET, S3_ENDPOINT_URL,<br/>S3_REGION, S3_ACCESS_KEY,<br/>S3_SECRET_KEY", "Lus seulement si STORAGE_BACKEND=s3.", "Tout hébergeur compatible S3 convient."),
]

_ENV_RESEAU = [
    ("CORS_ORIGINS", "Les origines autorisées à appeler l'API.", "La liste exacte des adresses par lesquelles l'application est jointe. Pas d'astérisque."),
    ("PUBLIC_RATE_LIMIT_PER_HOUR", "Dépôts publics par heure et par IP.", "20. À relever pour une campagne à gros volume."),
    ("VITE_API_URL", "L'adresse de l'API, inscrite dans l'interface à la construction.", "L'adresse <b>publique</b>, pas localhost, dès que le serveur n'est pas le poste de travail."),
    ("URL_PUBLIQUE", "Sert à bâtir les liens envoyés par courriel.", "Sans elle, les messages partent sans lien plutôt qu'avec un lien vers « localhost »."),
]

_ENV_COURRIEL = [
    ("IMAP_HOST, IMAP_PORT,<br/>IMAP_USER, IMAP_PASSWORD,<br/>IMAP_FOLDER", "La boîte relevée.", "<b>Amorçage seulement.</b> Le réglage courant vit en base et se change dans Paramètres. Éditer ce fichier après le premier démarrage n'a plus d'effet."),
    ("SMTP_HOST, SMTP_PORT,<br/>SMTP_USER, SMTP_PASSWORD,<br/>SMTP_TLS, SMTP_EXPEDITEUR", "L'envoi.", "Même remarque. Chez Microsoft, laisser SMTP_PASSWORD vide : aucun mot de passe n'y est accepté."),
    ("OAUTH_TENANT,<br/>OAUTH_CLIENT_ID,<br/>OAUTH_CLIENT_SECRET", "L'accès à une boîte Microsoft — réception <i>et</i> envoi. Microsoft a supprimé le mot de passe d'IMAP et de SMTP : sans ces valeurs, une boîte Outlook ne s'ouvre pas.", "<b>À poser au déploiement</b>, contrairement aux deux lignes ci-dessus : ces valeurs ne se révoquent pas d'elles-mêmes. Fournies par l'administrateur Entra — guide de la boîte, étape M4. L'écran Paramètres reste là pour les corriger, et ce qui y est saisi prime."),
    ("OAUTH_REFRESH_TOKEN", "Le même accès, pour une adresse <font face='Courier'>outlook.com</font> personnelle.", "Seulement dans ce cas : Microsoft n'y autorise pas le flux application. Inutile avec une adresse Microsoft 365, où le secret suffit."),
]

# Les réglages de l'écran Paramètres. Ils priment sur le fichier.
_PARAMETRES = [
    ("Expurger les données démographiques", "Retire âge, sexe et nationalité du contenu noté.", "Coché."),
    ("Inscription libre / Code", "Création de comptes depuis la page de connexion.", "Décoché une fois l'équipe créée."),
    ("Candidatures spontanées", "Ouvre le dépôt hors avis, qui alimente le vivier.", "Au choix du cabinet."),
    ("Relever la boîte", "Active le relevé et fait apparaître les boutons sur les postes.", "Coché une fois la boîte réglée."),
    ("Adresse, serveur, port, dossier", "Les coordonnées IMAP.", "<font face='Courier'>outlook.office365.com</font> : 993, INBOX."),
    ("Mot de passe (IMAP)", "Le secret de la boîte.", "<b>Vide pour une boîte Microsoft</b>, qui n'en accepte aucun. Un mot de passe d'application chez Google."),
    ("Tenant, ID d'application, Secret", "L'accès OAuth Microsoft, pour la réception <i>et</i> l'envoi.", "Normalement déjà posés dans <font face='Courier'>.env</font> au déploiement (A.7). À ne remplir ici que pour corriger, sans rouvrir un accès à la machine."),
    ("Envoi : serveur, port, compte,<br/>mot de passe, TLS, expéditeur", "La session d'envoi et l'adresse « De : ».", "L'adresse d'expédition est celle que les candidats voient et à laquelle ils répondront."),
    ("Adresse publique de l'application", "Bâtit les liens des courriels.", "L'adresse par laquelle un candidat joint l'application depuis l'extérieur."),
]


def _bloc(titre: str, entrees: list[tuple[str, str, str]]) -> list:
    return [
        para(titre, "etape"),
        tableau(
            ["Réglage", "Ce qu'il fait", "Ce qu'il faut y mettre"],
            [list(e) for e in entrees],
            [44 * mm, 52 * mm, 69 * mm],
        ),
        Spacer(1, 6),
    ]


def _annexe_configuration() -> list:
    h: list = [PageBreak(), para("Annexe — Tout ce qui se règle", "section")]
    h.append(
        para(
            "Le corps du guide dit quoi faire, dans l'ordre. Cette annexe dit <i>tout</i> ce "
            "qui existe, pour qui reprend une installation et doit savoir ce qu'il a sous "
            "les yeux. Une variable absente de ces tableaux est une variable que "
            "l'application ne lit pas."
        )
    )
    h.extend(
        encadre(
            "Deux endroits, et le second l'emporte",
            "Le fichier <font face='Courier'>.env</font> porte ce qui tient au serveur : "
            "base, secrets, stockage, modèle. L'écran <b>Paramètres</b> porte ce qui change "
            "en cours d'exploitation : la boîte de candidatures, l'envoi, l'ouverture des "
            "inscriptions. Pour ces réglages-là, <b>ce qui est enregistré dans "
            "l'application prime sur le fichier</b>, qui ne sert plus qu'à amorcer une "
            "installation neuve. Modifier <font face='Courier'>.env</font> après le premier "
            "démarrage n'a aucun effet sur eux — c'est la confusion la plus coûteuse.",
        )
    )
    h.extend(_bloc("A.1 — Base de données", _ENV_BASE))
    h.extend(_bloc("A.2 — Sécurité et comptes", _ENV_SECURITE))
    h.append(PageBreak())
    h.extend(_bloc("A.3 — Le modèle", _ENV_MODELE))
    h.append(PageBreak())
    h.extend(_bloc("A.4 — Confidentialité", _ENV_CONFIDENTIALITE))
    h.extend(_bloc("A.5 — Stockage des pièces", _ENV_STOCKAGE))
    h.extend(_bloc("A.6 — Réseau et adresses", _ENV_RESEAU))
    h.extend(_bloc("A.7 — Courriel (amorçage seulement)", _ENV_COURRIEL))
    h.append(PageBreak())
    h.extend(_bloc("B — L'écran Paramètres, dans l'application", _PARAMETRES))
    h.extend(
        encadre(
            "Les secrets ne se réaffichent jamais",
            "Mot de passe IMAP, mot de passe d'envoi, secret Microsoft, jeton de "
            "rafraîchissement : une fois enregistrés, ils ne ressortent plus du serveur. Le "
            "champ reste vide et indique « déjà défini ». Laisser un champ de secret vide "
            "veut donc dire « inchangé », et non « effacé » — sans quoi ouvrir puis "
            "enregistrer l'écran des paramètres déconnecterait la boîte.",
        )
    )
    return h


def main() -> None:
    document = SimpleDocTemplate(
        str(SORTIE),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=22 * mm,
        title="TriCV — Guide de déploiement",
        author="Kapi Consult",
    )
    document.build(contenu(), onFirstPage=_pied, onLaterPages=_pied)
    print(f"écrit : {SORTIE}")


if __name__ == "__main__":
    main()
