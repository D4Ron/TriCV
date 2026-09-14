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
            "les convocations et les accès clients. Les deux se règlent depuis "
            "l'application — <b>Paramètres</b> — et non dans le fichier de "
            "configuration : l'adresse de recrutement change avec les campagnes, et un "
            "mot de passe d'application se révoque sans prévenir. Demander un accès au "
            "serveur à chaque fois condamnerait la fonction à ne pas servir."
        )
    )

    h.append(para("3.1 — Réception (IMAP)", "etape"))
    h.append(
        para(
            "Le paramétrage complet, avec les pièges de Gmail et la façon de vérifier "
            "que le relevé fonctionne, fait l'objet d'un document séparé : "
            "<b>Guide-configuration-boite-candidatures.pdf</b>. Suivez-le avant de "
            "revenir ici."
        )
    )

    h.append(para("3.2 — Envoi (SMTP)", "etape"))
    h.append(
        para(
            "Dans <b>Paramètres › Envoi de courriels</b>, renseignez le serveur, le "
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
                    "Microsoft 365",
                    "smtp.office365.com",
                    "587",
                    "Le compte doit avoir l'authentification SMTP autorisée par "
                    "l'administrateur du tenant ; elle est désactivée par défaut.",
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
                "Les suivants se créent en ligne de commande, ou via l'inscription "
                "libre si elle est ouverte temporairement.",
                "L'inscription libre se referme dans <b>Paramètres</b> dès que "
                "l'équipe a ses comptes. Ouverte sans code, elle laisse quiconque "
                "atteint la page lire tous les dossiers.",
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
                ["Ollama, sur place", "aucune limite", "illimité"],
            ],
            [38 * mm, 72 * mm, 55 * mm],
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
            "occupe environ 5 Go et demande autant de mémoire vive graphique pour "
            "répondre en quelques secondes ; sans carte graphique il tourne sur le "
            "processeur, ce qui reste utilisable pour un traitement de nuit."
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
