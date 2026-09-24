"""Génère le guide de configuration de la boîte de candidatures.

Le PDF est un livrable : il sera suivi par la personne qui fait le paramétrage
final chez Kapi Consult, sans accès au code. Il est donc rédigé en français,
comme le reste du produit.

Le script est versionné avec le PDF pour que le guide se regénère quand la
procédure change, plutôt que de dériver en silence.

    python docs/guide_boite_candidatures.py
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
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

SORTIE = Path(__file__).parent / "Guide-configuration-boite-candidatures.pdf"

# Palette reprise de l'interface, pour que le document et l'écran se ressemblent.
ENCRE = colors.HexColor("#1f2933")
ENCRE_DOUCE = colors.HexColor("#4b5563")
DISCRET = colors.HexColor("#6b7280")
FILET = colors.HexColor("#d7dce2")
FOND = colors.HexColor("#f6f7f9")
ALERTE = colors.HexColor("#b45309")
ALERTE_FOND = colors.HexColor("#fffbeb")
DANGER = colors.HexColor("#b91c1c")


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
            textColor=ENCRE, spaceBefore=18, spaceAfter=8,
        ),
        # keepWithNext sur l'étape seule : un intitulé ne doit pas finir une
        # page en laissant ses instructions sur la suivante. Le mettre aussi
        # sur les titres de partie faisait cascader tout le bloc suivant et
        # laissait une demi-page blanche.
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
        "pied": ParagraphStyle(
            "pied", parent=base["Normal"], fontSize=8, leading=11, textColor=DISCRET,
        ),
    }


S = _styles()


def para(texte: str, style: str = "corps"):
    return Paragraph(texte, S[style])


def puces(elements: list[str]):
    """Une liste à puces dont le point s'aligne sur la première ligne.

    Les valeurs par défaut de ReportLab placent une puce minuscule au-dessus de
    la ligne, ce qui se lit comme une poussière sur la page.
    """
    return ListFlowable(
        [ListItem(para(e, "puce"), leftIndent=12) for e in elements],
        bulletType="bullet",
        bulletFontSize=9,
        bulletOffsetY=-1.5,
        leftIndent=14,
        spaceBefore=2,
        spaceAfter=4,
    )


def encadre(titre: str, texte: str, ton=ALERTE, fond=ALERTE_FOND):
    """Un avertissement : ce qui coince en pratique, et pourquoi."""
    contenu = Paragraph(
        f'<font color="{ton.hexval()}"><b>{titre}</b></font><br/>{texte}', S["alerte"]
    )
    tableau = Table([[contenu]], colWidths=[165 * mm])
    tableau.setStyle(
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
    return [Spacer(1, 3), tableau, Spacer(1, 8)]


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
    canvas.drawString(20 * mm, 12 * mm, "TriCV — Configuration de la boîte de candidatures")
    canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, f"page {canvas.getPageNumber()}")
    canvas.setStrokeColor(FILET)
    canvas.setLineWidth(0.4)
    canvas.line(20 * mm, 16 * mm, A4[0] - 20 * mm, 16 * mm)
    canvas.restoreState()


def contenu() -> list:
    h = []

    # --- couverture ---------------------------------------------------------
    h.append(para("Configuration de la boîte de candidatures", "titre"))
    h.append(
        para(
            "TriCV — relevé automatique des dossiers reçus par email<br/>"
            f"Kapi Consult · document de paramétrage · {date.today():%d/%m/%Y}",
            "sous_titre",
        )
    )
    h.append(HRFlowable(width="100%", color=FILET, thickness=0.8, spaceAfter=14))

    h.append(para("À quoi sert ce paramétrage", "section"))
    h.append(
        para(
            "Les avis de recrutement demandent aux candidats d'envoyer leur dossier à une "
            "adresse email. Sans ce paramétrage, quelqu'un ouvre cette boîte, télécharge les "
            "pièces jointes et les redépose une par une dans TriCV. Une fois la boîte "
            "configurée, l'application fait ce trajet elle-même : elle lit les messages non "
            "lus, rattache chacun à son avis, en tire une candidature et marque le message "
            "traité."
        )
    )
    h.append(
        para(
            "<b>Ce paramétrage est facultatif.</b> Tant qu'il n'est pas fait, le dépôt à la "
            "main reste disponible sur chaque poste, via « Déposer des dossiers ». Rien ne "
            "cesse de fonctionner si vous décidez de ne pas l'activer."
        )
    )
    h.append(
        para(
            "Comptez une vingtaine de minutes. Il faut deux choses : un accès administrateur "
            "au compte Google de l'adresse de recrutement, et un compte <b>administrateur</b> "
            "dans TriCV — un compte recruteur voit les paramètres sans pouvoir les modifier."
        )
    )

    h.append(para("Ce dont vous avez besoin avant de commencer", "section"))
    h.append(
        puces(
            [
                "<b>Une adresse email dédiée au recrutement</b>, par exemple "
                "recrutement@kapiconsult.tg. Pas la boîte personnelle d'un collaborateur : "
                "l'application marque les messages comme lus et les traite, ce qui n'a pas sa "
                "place dans une messagerie privée.",
                "<b>De quoi ouvrir la boîte</b> — et cela dépend du fournisseur : un mot de "
                "passe d'application chez Google, un accès OAuth chez Microsoft. La section "
                "suivante dit lequel vous concerne.",
                "<b>Un compte administrateur TriCV.</b> Pour le vérifier : ouvrez "
                "« Paramètres ». Si les champs sont grisés et que la page indique « Réservé "
                "aux administrateurs », votre compte est un compte recruteur.",
                "<b>L'accès à la machine qui héberge TriCV</b>, uniquement si vous devez "
                "promouvoir un compte en administrateur (voir la dernière section).",
            ]
        )
    )

    # --- quel fournisseur ----------------------------------------------------
    h.append(para("Quel est votre fournisseur ? La suite en dépend", "section"))
    h.append(
        para(
            "Les deux grands fournisseurs ne se configurent plus de la même façon, et la "
            "différence n'est pas un détail de réglage : <b>chez Microsoft, aucun mot de "
            "passe ne fonctionne</b>. Repérez votre cas avant d'aller plus loin."
        )
    )
    h.append(
        tableau(
            ["Votre adresse", "Ce qu'il faut", "Où aller"],
            [
                [
                    "…@outlook.com, @hotmail.com, @live.com, ou une adresse de votre domaine "
                    "hébergée chez <b>Microsoft 365</b>",
                    "Un <b>accès OAuth</b> : identifiant d'application, tenant, secret. "
                    "Aucun mot de passe, pas même un « mot de passe d'application ».",
                    "Partie A-Microsoft",
                ],
                [
                    "…@gmail.com, ou une adresse de votre domaine hébergée chez "
                    "<b>Google Workspace</b>",
                    "Un <b>mot de passe d'application</b> Google.",
                    "Partie A-Google",
                ],
                [
                    "Une adresse hébergée ailleurs (serveur du cabinet, hébergeur local)",
                    "Le mot de passe de la boîte, en général.",
                    "Partie B directement",
                ],
            ],
            [52 * mm, 68 * mm, 38 * mm],
        )
    )
    h.extend(
        encadre(
            "Microsoft a supprimé les mots de passe sur IMAP",
            "Ce n'est pas un réglage à trouver ni une option à activer. La documentation de "
            "Microsoft est explicite : « Basic authentication is now disabled in all "
            "tenants », et personne — pas même le support Microsoft — ne peut la "
            "réactiver. Les « mots de passe d'application » reposaient dessus et ont "
            "disparu avec elle. Pour les adresses personnelles (outlook.com, hotmail.com, "
            "live.com), la bascule a eu lieu le 16 septembre 2024. Chercher un mot de "
            "passe qui marcherait est une heure perdue : il n'y en a pas.",
        )
    )

    # --- partie A Microsoft --------------------------------------------------
    h.append(para("Partie A-Microsoft — Déclarer TriCV auprès de Microsoft", "section"))
    h.append(
        para(
            "Le principe : on déclare TriCV comme une application auprès de Microsoft, on lui "
            "donne le droit de lire <i>cette</i> boîte, et l'application obtient ensuite "
            "toute seule un jeton d'accès à durée limitée. C'est plus long à mettre en place "
            "qu'un mot de passe, et cela ne se refait jamais."
        )
    )
    h.append(
        para(
            "<b>Deux cas, et il faut trancher avant de commencer.</b> Une adresse "
            "professionnelle (Microsoft 365, votre domaine, un administrateur) permet le "
            "flux dit « application » : TriCV s'authentifie seul, sans qu'aucun humain ne se "
            "connecte, et cela ne s'interrompt jamais. Une adresse personnelle outlook.com "
            "n'y a pas droit : Microsoft y exige un consentement humain, une fois, qui "
            "produit un jeton de rafraîchissement. Cela marche, mais ce jeton peut être "
            "révoqué — changement de mot de passe, expiration — et il faut alors "
            "recommencer. <b>Pour une boîte de recrutement qui doit tourner sans "
            "surveillance, une adresse professionnelle est nettement préférable.</b>"
        )
    )

    h.append(para("Étape M1 — Créer l'inscription d'application", "etape"))
    h.append(
        puces(
            [
                "Ouvrez <b>portal.azure.com</b> → <b>Microsoft Entra ID</b> → "
                "<b>Inscriptions d'applications</b> → <b>Nouvelle inscription</b>.",
                "Nom : <font face='Courier'>TriCV — boîte de candidatures</font>. "
                "Le nom n'a d'importance que pour vous y retrouver.",
                "Types de comptes : <b>ce répertoire organisationnel uniquement</b> pour une "
                "adresse professionnelle ; <b>comptes Microsoft personnels</b> pour une "
                "adresse outlook.com.",
                "Après création, relevez <b>ID d'application (client)</b> et <b>ID "
                "d'annuaire (tenant)</b> sur la page « Vue d'ensemble ». Ce sont deux des "
                "trois valeurs à saisir dans TriCV.",
            ]
        )
    )

    h.append(para("Étape M2 — Créer le secret", "etape"))
    h.append(
        puces(
            [
                "Dans l'application → <b>Certificats et secrets</b> → <b>Nouveau secret "
                "client</b>. Choisissez la durée la plus longue proposée.",
                "<b>Copiez la « Valeur » immédiatement.</b> Elle ne se réaffiche jamais "
                "après avoir quitté la page ; il faudrait en créer un autre.",
                "Ne confondez pas la <b>Valeur</b> et l'<b>ID du secret</b>, affichés côte à "
                "côte. C'est la valeur qu'attend TriCV — l'erreur la plus fréquente.",
            ]
        )
    )

    h.append(para("Étape M3 — Autoriser l'accès à la boîte", "etape"))
    h.append(
        para(
            "Pour une adresse <b>professionnelle</b>, un administrateur Microsoft 365 doit "
            "faire les deux gestes suivants. Sans le second, le jeton est délivré mais la "
            "boîte reste fermée."
        )
    )
    h.append(
        puces(
            [
                "Dans l'application → <b>API autorisées</b> → <b>Ajouter une autorisation</b> "
                "→ <b>Microsoft Graph</b> → <b>Autorisations d'application</b> → cochez "
                "<font face='Courier'>Mail.ReadWrite</font> et "
                "<font face='Courier'>Mail.Send</font> → <b>Accorder le consentement "
                "administrateur</b>.",
                "Puis restreindre l'application à la seule boîte de recrutement, par une "
                "<b>stratégie d'accès applicatif</b> Exchange. Ce second geste n'est pas "
                "optionnel : sans lui, ces autorisations portent sur "
                "<b>toutes les boîtes</b> de l'organisation.",
            ]
        )
    )
    h.append(
        para(
            "<font face='Courier' size='8'>"
            "New-ApplicationAccessPolicy -AppId &lt;ID application&gt; "
            "-PolicyScopeGroupId recrutement@kapiconsult.tg "
            "-AccessRight RestrictAccess "
            "-Description &quot;TriCV : boîte de recrutement uniquement&quot;"
            "</font>",
            "corps",
        )
    )
    h.extend(
        encadre(
            "Pourquoi Graph plutôt qu'IMAP",
            "Les deux chemins mènent à la boîte, et ils ne coûtent pas la même chose à "
            "ouvrir. Graph demande ce qui précède, et rien d'autre. La voie IMAP — "
            "<font face='Courier'>IMAP.AccessAsApp</font>, "
            "<font face='Courier'>SMTP.SendAsApp</font> — exige en plus de <b>réactiver "
            "SMTP AUTH</b> sur le tenant, puis de créer un principal de service et de le "
            "rattacher à la boîte en PowerShell "
            "(<font face='Courier'>New-ServicePrincipal</font>, puis "
            "<font face='Courier'>Add-MailboxPermission</font>). TriCV sait faire les deux, "
            "et le choix se fait à l'écran : <b>Paramètres → Courriel → Par où passe le "
            "courriel</b>. Une installation neuve part sur Graph.",
        )
    )
    h.append(
        para(
            "Pour une adresse <b>personnelle</b> outlook.com, il n'y a pas d'administrateur : "
            "la permission se demande au titulaire de la boîte par un consentement dans le "
            "navigateur, qui renvoie un <b>jeton de rafraîchissement</b>. C'est ce jeton, et "
            "non un secret, qui se colle dans TriCV. La personne qui installe l'application "
            "doit être devant l'écran pour ce geste."
        )
    )

    h.append(para("Étape M4 — Ce qu'il faut demander à l'administrateur", "etape"))
    h.append(
        para(
            "Les étapes M1 à M3 se font dans Entra ID et demandent des droits "
            "d'administrateur. Vous n'avez pas à les comprendre : il suffit de les faire "
            "faire, et de récupérer <b>trois valeurs</b>. Le texte ci-dessous peut être "
            "transmis tel quel à la personne qui administre Entra."
        )
    )
    h.extend(
        encadre(
            "À transmettre à l'administrateur Entra ID",
            "Bonjour,<br/><br/>"
            "Nous mettons en service une application interne (TriCV) qui doit "
            "<b>lire et écrire</b> la boîte de recrutement "
            "<font face='Courier'>recrutement@kapiconsult.tg</font> : y relever les "
            "candidatures reçues, et répondre aux candidats. Microsoft n'acceptant plus "
            "l'authentification par mot de passe, il lui faut un accès applicatif par "
            "Microsoft Graph. Pourriez-vous :<br/><br/>"
            "1. créer une inscription d'application nommée « TriCV — boîte de "
            "candidatures » (ce répertoire organisationnel uniquement) ;<br/>"
            "2. lui créer un secret client, de la durée la plus longue possible ;<br/>"
            "3. lui accorder les permissions <b>d'application</b> Microsoft Graph "
            "<font face='Courier'>Mail.ReadWrite</font> et "
            "<font face='Courier'>Mail.Send</font>, puis donner le "
            "<b>consentement administrateur</b> ;<br/>"
            "4. restreindre l'application à cette seule boîte par une stratégie d'accès "
            "applicatif :<br/>"
            "<font face='Courier' size='8'>New-ApplicationAccessPolicy "
            "-AppId &lt;ID application&gt; -PolicyScopeGroupId "
            "recrutement@kapiconsult.tg -AccessRight RestrictAccess</font><br/><br/>"
            "Le point 4 n'est pas facultatif : sans lui, les permissions du point 3 "
            "portent sur toutes les boîtes du tenant, ce que nous ne demandons pas.<br/><br/>"
            "Merci de nous transmettre <b>l'ID d'annuaire (tenant)</b>, <b>l'ID "
            "d'application (client)</b> et <b>la valeur du secret</b> — et non son ID.",
        )
    )
    h.extend(
        encadre(
            "Si votre organisation impose IMAP plutôt que Graph",
            "Remplacez le point 3 par les permissions "
            "<font face='Courier'>IMAP.AccessAsApp</font> et "
            "<font face='Courier'>SMTP.SendAsApp</font> sur Office 365 Exchange Online, et "
            "le point 4 par la création d'un principal de service rattaché à la boîte "
            "(<font face='Courier'>New-ServicePrincipal</font>, puis "
            "<font face='Courier'>Add-MailboxPermission</font>) — en sachant que SMTP AUTH "
            "doit alors être réactivé sur le tenant. Côté TriCV, il suffit de renseigner "
            "<font face='Courier'>outlook.office365.com</font> et "
            "<font face='Courier'>smtp.office365.com</font>.",
            ton=DISCRET,
            fond=FOND,
        )
    )

    # --- partie A Google -----------------------------------------------------
    h.append(para("Partie A-Google — Préparer le compte Google", "section"))
    h.append(
        para(
            "Gmail n'accepte plus le mot de passe habituel d'un compte pour ce type de "
            "connexion. Il faut créer un « mot de passe d'application » : un mot de passe "
            "distinct, réservé à TriCV, révocable seul et sans effet sur le reste du compte. "
            "Les trois étapes qui suivent servent à l'obtenir."
        )
    )

    h.append(para("Étape 1 — Activer la validation en deux étapes", "etape"))
    h.append(
        puces(
            [
                "Connectez-vous au compte Google de l'adresse de recrutement.",
                "Ouvrez <b>myaccount.google.com</b> → onglet <b>Sécurité</b>.",
                "Section « Comment vous connecter à Google » → <b>Validation en deux "
                "étapes</b> → suivez la procédure (Google demandera un numéro de téléphone).",
            ]
        )
    )
    h.extend(
        encadre(
            "Cette étape n'est pas contournable",
            "L'option « Mots de passe des applications » n'existe tout simplement pas tant "
            "que la validation en deux étapes n'est pas active. Si vous ne la trouvez pas à "
            "l'étape 2, c'est presque toujours que l'étape 1 n'est pas terminée.",
        )
    )

    h.append(para("Étape 2 — Créer le mot de passe d'application", "etape"))
    h.append(
        puces(
            [
                "Toujours dans <b>Sécurité</b>, cherchez « Mots de passe des applications » "
                "(la barre de recherche du compte Google y mène directement).",
                "Créez-en un et nommez-le <b>TriCV</b> — le nom ne sert qu'à vous y "
                "retrouver le jour où vous voudrez le révoquer.",
                "Google affiche <b>seize lettres, présentées par groupes de quatre</b>. "
                "Copiez-les.",
            ]
        )
    )
    h.extend(
        encadre(
            "Il ne sera plus jamais affiché",
            "Google ne le remontre pas après la fermeture de la fenêtre. Si vous le perdez, "
            "il faut en créer un autre — ce qui est sans conséquence, l'ancien se supprime. "
            "Les espaces entre les groupes de quatre n'ont pas d'importance : TriCV les "
            "retire automatiquement.",
        )
    )

    h.append(para("Étape 3 — Activer IMAP dans Gmail", "etape"))
    h.append(
        puces(
            [
                "Ouvrez <b>Gmail</b> avec ce compte → roue dentée → <b>Afficher tous les "
                "paramètres</b>.",
                "Onglet <b>Transfert et POP/IMAP</b> → section « Accès IMAP » → <b>Activer "
                "IMAP</b>.",
                "<b>Enregistrer les modifications</b> en bas de la page.",
            ]
        )
    )
    h.extend(
        encadre(
            "Compte Google Workspace : vérifiez la politique de l'organisation",
            "Si l'adresse appartient à un espace de travail Google d'entreprise, un "
            "administrateur peut avoir désactivé IMAP ou interdit les mots de passe "
            "d'application pour tout le domaine. Dans ce cas les réglages ci-dessus sont "
            "absents ou sans effet, et il faut passer par l'administrateur du domaine. Une "
            "adresse Gmail ordinaire n'est pas concernée.",
        )
    )

    # --- partie B -----------------------------------------------------------
    h.append(PageBreak())
    h.append(para("Partie B — Renseigner TriCV", "section"))

    h.append(para("Étape 4 — Ouvrir l'écran de configuration", "etape"))
    h.append(
        para(
            "Connectez-vous à TriCV avec un compte administrateur, puis ouvrez "
            "<b>Paramètres</b> et l'onglet <b>Courriel</b>."
        )
    )
    h.append(
        para(
            "La première question de l'onglet est <b>par où passe le courriel</b> : "
            "« IMAP et SMTP » ou « Microsoft 365 (Graph) ». Ce choix commande la suite — "
            "il fait apparaître les champs qui comptent et disparaître ceux qui ne servent "
            "à rien chez le fournisseur retenu. Choisissez-le avant de remplir quoi que ce "
            "soit, sans quoi vous renseignerez un serveur IMAP que personne n'interrogera."
        )
    )
    h.extend(
        encadre(
            "Microsoft : les champs IMAP disparaissent, et c'est voulu",
            "Sous « Microsoft 365 (Graph) », l'écran ne demande plus ni serveur, ni port, "
            "ni mot de passe : Graph n'en emploie aucun. Restent l'adresse de la boîte, le "
            "dossier à relever, l'adresse d'expédition, et les trois valeurs de "
            "l'inscription Entra ID — tenant, ID d'application, secret. Le bouton "
            "« Les étapes, côté Entra ID » rappelle sur place la marche à suivre décrite "
            "en partie A.",
        )
    )

    h.append(para("Étape 5 — Remplir les champs", "etape"))
    h.append(
        tableau(
            ["Champ", "Valeur", "Remarque"],
            [
                [
                    "Relever la boîte depuis l'application",
                    "coché",
                    "Décoché, les boutons de relevé n'apparaissent pas sur les postes.",
                ],
                [
                    "Adresse de la boîte",
                    "l'adresse de recrutement complète",
                    "Celle qui figure dans les avis publiés.",
                ],
                [
                    "Mot de passe",
                    "les 16 lettres de l'étape 2 — <b>Google seulement</b>",
                    "Le mot de passe d'application, jamais celui du compte. "
                    "<b>À laisser vide pour une boîte Microsoft</b>, qui n'en accepte aucun.",
                ],
                [
                    "Serveur IMAP",
                    "<font face='Courier'>outlook.office365.com</font> (Microsoft)<br/>"
                    "<font face='Courier'>imap.gmail.com</font> (Google)",
                    "Le même serveur pour une adresse Microsoft 365 et pour une adresse "
                    "outlook.com personnelle.",
                ],
                ["Port", "993", "Valeur par défaut, à ne changer que sur consigne."],
                [
                    "Dossier à relever",
                    "INBOX",
                    "La boîte de réception. Un libellé Gmail s'écrit tel quel, à la lettre.",
                ],
            ],
            [46 * mm, 52 * mm, 67 * mm],
        )
    )
    h.append(Spacer(1, 8))
    h.append(
        para(
            "<b>Pour une boîte Microsoft uniquement</b>, trois champs de plus, relevés en "
            "partie A-Microsoft. Ils remplacent le mot de passe ; ils ne s'y ajoutent pas.",
            "corps",
        )
    )
    h.append(
        tableau(
            ["Champ", "Valeur", "Remarque"],
            [
                [
                    "Tenant",
                    "l'ID d'annuaire (étape M1)",
                    "Pour une adresse outlook.com personnelle, écrivez "
                    "<font face='Courier'>consumers</font>.",
                ],
                [
                    "ID d'application",
                    "l'ID d'application (étape M1)",
                    "Visible en permanence sur la page « Vue d'ensemble ».",
                ],
                [
                    "Secret",
                    "la <b>valeur</b> du secret (étape M2)",
                    "Pas l'« ID du secret », affiché juste à côté. Pour une adresse "
                    "personnelle, c'est le jeton de rafraîchissement qui se colle ici.",
                ],
            ],
            [46 * mm, 52 * mm, 67 * mm],
        )
    )
    h.append(Spacer(1, 8))
    h.append(para("Cliquez sur <b>Enregistrer</b>.", "corps"))
    h.extend(
        encadre(
            "Le mot de passe ne se réaffiche jamais",
            "Une fois enregistré, il ne ressort plus du serveur : le champ indiquera « déjà "
            "défini » et restera vide. C'est voulu. Pour modifier un autre réglage — le "
            "dossier, par exemple — laissez ce champ vide et le mot de passe existant est "
            "conservé. Ne le remplissez que pour le remplacer.",
        )
    )

    h.append(para("Étape 6 — Tester la connexion", "etape"))
    h.append(
        para(
            "Cliquez sur <b>Tester la connexion</b>. Le bouton porte sur les réglages "
            "<b>enregistrés</b> : enregistrez d'abord. En cas de succès, TriCV affiche "
            "l'adresse, le dossier, le nombre de messages et le nombre de non lus. Si un "
            "message d'erreur apparaît, reportez-vous au tableau de la page suivante."
        )
    )

    # --- partie C -----------------------------------------------------------
    h.append(para("Partie C — Préparer les avis", "section"))
    h.append(
        para(
            "La connexion ne suffit pas. TriCV doit savoir <b>à quel poste rattacher chaque "
            "message</b>, et il s'appuie pour cela sur une référence entre crochets dans "
            "l'objet, par exemple <b>[AVIS-2026-014]</b>."
        )
    )

    h.append(para("Étape 7 — Donner une référence à chaque avis", "etape"))
    h.append(
        puces(
            [
                "Sur chaque poste, ouvrez l'avis et vérifiez qu'il porte bien une "
                "<b>référence</b>. Sans elle, aucun message ne pourra lui être rattaché.",
                "TriCV rappelle sous l'avis la phrase exacte à faire figurer, du type : "
                "« Les candidatures reçues par email sont rattachées à cet avis si l'objet "
                "contient [DL-2026-007]. »",
                "<b>Reprenez cette consigne dans le texte de l'avis publié</b>, en demandant "
                "explicitement aux candidats de mettre la référence dans l'objet de leur "
                "message.",
            ]
        )
    )
    h.extend(
        encadre(
            "Sans référence, rien n'est perdu — mais rien n'est créé",
            "Un message dont l'objet ne contient aucune référence connue est signalé comme "
            "« non rattaché » : TriCV ne crée aucune candidature et <b>laisse le message non "
            "lu</b>, pour qu'une personne s'en occupe. Prévoyez donc de relire régulièrement "
            "cette liste, surtout au début : c'est là qu'atterrissent les candidatures des "
            "personnes qui n'ont pas suivi la consigne.",
        )
    )

    h.append(para("Étape 8 — Faire un essai avant le premier vrai relevé", "etape"))
    h.append(
        puces(
            [
                "Envoyez-vous <b>un message de test</b> à l'adresse de recrutement, avec la "
                "référence d'un avis dans l'objet et un CV en pièce jointe (PDF ou Word).",
                "Sur le poste correspondant, cliquez sur <b>Aperçu</b>. Cet écran montre "
                "exactement ce qu'un relevé ferait — <b>sans rien créer ni marquer</b>.",
                "Vérifiez que votre message y apparaît comme « créerait une candidature ».",
                "Cliquez alors sur <b>Relever</b>. La candidature est créée.",
            ]
        )
    )

    # --- partie D -----------------------------------------------------------
    h.append(PageBreak())
    h.append(para("Ce qu'il faut savoir en usage courant", "section"))
    h.append(
        para(
            "Ces quatre points ne sont pas des erreurs de configuration, mais des "
            "comportements qui surprennent la première fois."
        )
    )

    h.append(
        tableau(
            ["Comportement", "Ce que cela implique au quotidien"],
            [
                [
                    "<b>Seuls les messages non lus</b> sont relevés.",
                    "Si quelqu'un ouvre la boîte dans Gmail et lit les messages avant le "
                    "relevé, TriCV les ignorera. Convenez d'une règle : soit on consulte "
                    "cette boîte sans l'ouvrir, soit on remet les messages en « non lu » "
                    "avant de relever.",
                ],
                [
                    "Le relevé <b>marque les messages comme lus</b>.",
                    "C'est ce qui évite de retraiter deux fois le même dossier. "
                    "Conséquence : une seule personne devrait déclencher les relevés, sinon "
                    "chacun voit une boîte déjà vidée par l'autre.",
                ],
                [
                    "Un message <b>sans pièce jointe exploitable</b> est ignoré.",
                    "Seuls les PDF et les fichiers Word sont retenus, et le format est "
                    "vérifié sur le contenu du fichier, pas sur son extension. Les accusés "
                    "de réception, les questions et les images de signature ne créent donc "
                    "aucune candidature.",
                ],
                [
                    "L'identité est <b>devinée</b>, jamais tenue pour acquise.",
                    "Le nom est déduit de l'en-tête du message. Les dossiers arrivent donc "
                    "en « À vérifier » : ils ne peuvent être ni éliminés ni présélectionnés "
                    "tant qu'une personne n'a pas relu et confirmé.",
                ],
            ],
            [58 * mm, 107 * mm],
        )
    )

    h.append(para("Si quelque chose ne marche pas", "section"))
    h.append(
        para(
            "Les messages d'erreur de TriCV sont volontairement explicites. Voici ce que "
            "chacun signifie."
        )
    )
    h.append(
        tableau(
            ["Message affiché", "Cause et correction"],
            [
                [
                    "« … n'accepte plus aucun mot de passe en IMAP »",
                    "Boîte Microsoft configurée avec un mot de passe. Il n'en existe aucun "
                    "qui fonctionnerait : renseignez le tenant, l'ID d'application et le "
                    "secret (partie A-Microsoft) et laissez le mot de passe vide.",
                ],
                [
                    "« Le secret de l'application est refusé »",
                    "C'est l'<b>ID</b> du secret qui a été collé au lieu de sa "
                    "<b>valeur</b> — Entra affiche les deux côte à côte. La valeur ne se "
                    "réaffiche pas : créez-en un nouveau et copiez-le tout de suite.",
                ],
                [
                    "« … refusé le jeton … IMAP.AccessAsApp »",
                    "Le jeton est délivré mais la boîte reste fermée : il manque l'étape M3. "
                    "L'administrateur doit accorder la permission <i>et</i> autoriser le "
                    "principal de service sur cette boîte précise.",
                ],
                [
                    "« Une adresse outlook.com personnelle n'accepte pas le flux "
                    "application »",
                    "Microsoft réserve ce flux aux comptes professionnels. Il faut le "
                    "consentement humain et le jeton de rafraîchissement (fin de la partie "
                    "A-Microsoft), ou passer sur une adresse professionnelle.",
                ],
                [
                    "« Le consentement a expiré ou a été révoqué »",
                    "Adresse personnelle : le jeton de rafraîchissement ne vaut plus — mot "
                    "de passe changé, ou trop de temps écoulé. Refaites le consentement. "
                    "C'est la faiblesse de ce flux, et la raison de préférer une adresse "
                    "professionnelle.",
                ],
                [
                    "« Gmail a refusé la connexion… »",
                    "Le mot de passe saisi est celui du compte, et non un mot de passe "
                    "d'application. Reprenez les étapes 1 et 2.",
                ],
                [
                    "« Identifiants refusés par… »",
                    "Adresse ou mot de passe incorrect, ou mot de passe d'application "
                    "révoqué. À noter : changer le mot de passe du compte Google, ou "
                    "désactiver la validation en deux étapes, <b>révoque tous les mots de "
                    "passe d'application</b>. Il faut alors en créer un nouveau.",
                ],
                [
                    "« Le dossier « … » n'existe pas »",
                    "Le nom du dossier est mal orthographié. Pour la boîte de réception, "
                    "écrivez exactement INBOX. Un libellé Gmail s'écrit tel qu'il apparaît "
                    "dans Gmail, accents et majuscules compris.",
                ],
                [
                    "« Impossible de joindre imap.gmail.com:993 »",
                    "Le serveur n'est pas joignable : coupure réseau, ou pare-feu de "
                    "l'entreprise qui bloque le port 993 en sortie. À voir avec la personne "
                    "qui gère le réseau.",
                ],
                [
                    "« Le relevé de la boîte est désactivé »",
                    "La case « Relever la boîte depuis l'application » n'est pas cochée, ou "
                    "l'enregistrement n'a pas été fait.",
                ],
                [
                    "« Boîte incomplète : il manque… »",
                    "Un champ obligatoire est vide. Le message nomme lequel.",
                ],
                [
                    "La connexion réussit mais aucun message n'est trouvé",
                    "IMAP n'est probablement pas activé côté Gmail (étape 3), ou tous les "
                    "messages ont déjà été lus (voir le tableau ci-dessus).",
                ],
                [
                    "Les champs des paramètres sont grisés",
                    "Votre compte TriCV est un compte recruteur. Seul un administrateur "
                    "modifie ces réglages — voir ci-dessous.",
                ],
                [
                    "L'écran ne montre ni serveur ni mot de passe",
                    "L'onglet Courriel est réglé sur « Microsoft 365 (Graph) », qui n'en "
                    "emploie pas. Si votre boîte est chez Google ou chez un hébergeur "
                    "classique, choisissez « IMAP et SMTP » : les champs reviennent.",
                ],
                [
                    "« Tester la connexion » reste grisé",
                    "Le bouton porte sur les réglages <i>enregistrés</i>, et il attend que "
                    "la configuration soit complète : boîte cochée, adresse renseignée, et "
                    "de quoi ouvrir une session. Enregistrez d'abord.",
                ],
            ],
            [52 * mm, 113 * mm],
        )
    )

    # --- annexe -------------------------------------------------------------
    h.append(PageBreak())
    h.append(para("Annexe — Les comptes de l'équipe", "section"))
    h.append(
        para(
            "Un administrateur ouvre, promeut et ferme les comptes depuis "
            "<b>Paramètres → Utilisateurs</b> : « Ajouter un compte » demande un nom, une "
            "adresse, un mot de passe initial et un rôle. Le mot de passe est celui que "
            "<i>vous</i> choisissez, et c'est à vous de le transmettre — l'application ne "
            "l'envoie à personne, ne le réaffiche jamais et ne l'inscrit pas au journal."
        )
    )
    h.extend(
        encadre(
            "Ajouter un collègue ne demande plus d'ouvrir l'inscription libre",
            "C'était le seul moyen jusqu'ici, et il revient à laisser n'importe qui "
            "atteignant l'adresse se créer un compte et consulter les dossiers de tous les "
            "candidats — le temps qu'on repense à refermer. Créez les comptes un à un "
            "depuis l'onglet Utilisateurs, et laissez « Autoriser la création de compte » "
            "décochée.",
        )
    )
    h.append(
        para(
            "Deux gestes restent impossibles, côté écran comme côté serveur : retirer ses "
            "propres droits d'administrateur, et retirer les siens au <b>dernier</b> "
            "administrateur actif. Dans les deux cas plus personne ne pourrait gérer les "
            "comptes ni les paramètres."
        )
    )
    h.append(
        para(
            "Un compte ne se supprime pas ; il se <b>désactive</b>. Son nom figure au "
            "journal d'audit sur chaque décision qu'il a prise, et l'effacer rendrait ces "
            "décisions anonymes. La désactivation ferme l'accès et garde la trace."
        )
    )
    h.append(para("Le tout premier administrateur", "etape"))
    h.append(
        para(
            "Un compte créé depuis la page d'inscription est <b>toujours un compte "
            "recruteur</b>, jamais administrateur. Ce n'est pas un oubli : la page "
            "d'inscription est accessible sur le réseau, et quiconque la trouve ne doit pas "
            "pouvoir s'attribuer le contrôle des réglages du cabinet."
        )
    )
    h.append(
        para(
            "Il faut donc amorcer le premier administrateur depuis la machine qui héberge "
            "TriCV — c'est précisément cette contrainte qui fait la garantie. Ensuite, "
            "l'onglet Utilisateurs suffit, et ces commandes ne resservent qu'en dépannage : "
            "le jour où plus aucun administrateur ne peut se connecter. Dans un terminal, à "
            "la racine du dossier de l'application :"
        )
    )
    h.append(
        tableau(
            ["Commande", "Effet"],
            [
                ["cd backend", "Se placer dans le dossier de l'application."],
                [
                    ".\\.venv\\Scripts\\python.exe comptes.py",
                    "Lister les comptes, leur rôle et leur état.",
                ],
                [
                    ".\\.venv\\Scripts\\python.exe comptes.py promouvoir adresse@exemple.tg",
                    "Passer un compte en administrateur.",
                ],
                [
                    ".\\.venv\\Scripts\\python.exe comptes.py desactiver adresse@exemple.tg",
                    "Retirer l'accès sans effacer le compte : ses actions passées gardent "
                    "un nom dans le journal.",
                ],
            ],
            [82 * mm, 83 * mm],
        )
    )
    h.append(Spacer(1, 8))
    h.append(
        para(
            "<b>Après une promotion, déconnectez-vous et reconnectez-vous</b> : l'écran lit "
            "le rôle depuis la session en cours."
        )
    )
    h.extend(
        encadre(
            "Refermez l'inscription libre une fois l'équipe créée",
            "Tant qu'elle est ouverte, toute personne atteignant la page peut se créer un "
            "compte et consulter les dossiers de tous les candidats. Une fois les comptes de "
            "l'équipe créés, décochez « Autoriser la création de compte » dans "
            "<b>Paramètres → Général</b>. Les comptes suivants s'ajoutent un à un depuis "
            "l'onglet Utilisateurs, sans jamais la rouvrir.",
            ton=DANGER,
            fond=colors.HexColor("#fef2f2"),
        )
    )

    h.append(para("Récapitulatif", "section"))
    h.append(
        KeepTogether(
            puces(
                [
                    "Validation en deux étapes activée sur le compte Google.",
                    "Mot de passe d'application créé et copié.",
                    "IMAP activé dans les paramètres Gmail.",
                    "Champs renseignés dans TriCV, case « Relever la boîte » cochée, "
                    "réglages enregistrés.",
                    "« Tester la connexion » renvoie le nombre de messages.",
                    "Chaque avis porte une référence, et le texte publié demande aux "
                    "candidats de la mettre en objet.",
                    "Un message de test a été vu dans « Aperçu » puis relevé avec succès.",
                    "Une seule personne est désignée pour déclencher les relevés.",
                    "Inscription libre refermée une fois l'équipe créée.",
                ]
            )
        )
    )

    return h


def main() -> None:
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(SORTIE),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=22 * mm,
        title="TriCV — Configuration de la boîte de candidatures",
        author="TriCV",
        subject="Guide de paramétrage du relevé automatique des candidatures",
    )
    document.build(contenu(), onFirstPage=_pied, onLaterPages=_pied)
    print(f"écrit : {SORTIE}")


if __name__ == "__main__":
    main()
