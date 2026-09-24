"""Envoi de courriels : convocations, refus, accès client.

Le cabinet écrit déjà à ses candidats — convocation à l'entretien, demande de
pièce manquante, réponse négative. Le faire depuis l'application plutôt que
depuis une boîte personnelle change deux choses : le message part avec les
bonnes données du dossier (donc sans erreur de copier-coller), et il laisse une
trace attachée à la candidature, ce qui vaut preuve d'envoi.

Trois précautions structurent ce module :

1. **Rien ne part sans relecture.** `preparer()` rend le message rédigé ;
   `envoyer()` ne fait qu'expédier ce qui lui est donné. L'appelant montre
   toujours le texte avant. Un courriel n'est pas rattrapable.
2. **Un envoi raté se voit.** Les erreurs SMTP remontent en `ErreurEnvoi`
   plutôt que d'être avalées : un candidat non convoqué parce que le serveur
   refusait la connexion est une faute grave, silencieuse.
3. **Les modèles sont modifiables.** Les formulations changent d'un cabinet à
   l'autre et d'une campagne à l'autre ; celles d'ici sont des points de départ
   enregistrés en base au premier démarrage, pas des constantes.
"""

from __future__ import annotations

import asyncio
import base64
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr

from app.services import graph_microsoft, oauth_microsoft
from app.services.courriel import _est_microsoft
from app.services.parametres import Reglages


class ErreurEnvoi(RuntimeError):
    """L'envoi n'a pas abouti. Le message n'est pas parti."""


@dataclass(slots=True)
class Message:
    """Un courriel rédigé, prêt à être relu puis expédié."""

    destinataire: str
    sujet: str
    corps: str
    nom_destinataire: str = ""
    copie: list[str] = field(default_factory=list)


# --- modèles ---------------------------------------------------------------
#
# Le format des variables est volontairement le plus simple possible :
# `{nom_de_variable}`. Une syntaxe de gabarit complète (conditions, boucles)
# donnerait aux RH un langage de programmation à déboguer dans un champ de
# formulaire ; ici, une variable inconnue est laissée telle quelle et signalée,
# ce qui se répare en la lisant.

MOTIF_VARIABLE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


def variables_utilisees(gabarit: str) -> set[str]:
    return set(MOTIF_VARIABLE.findall(gabarit))


def rendre(gabarit: str, valeurs: dict[str, object]) -> str:
    """Remplace `{variable}` par sa valeur.

    Une variable absente du contexte est laissée telle quelle : mieux vaut un
    message visiblement incomplet, que le relecteur corrigera, qu'un trou
    silencieux au milieu d'une phrase.
    """

    def remplacer(correspondance: re.Match[str]) -> str:
        cle = correspondance.group(1)
        if cle not in valeurs or valeurs[cle] is None:
            return correspondance.group(0)
        return str(valeurs[cle])

    return MOTIF_VARIABLE.sub(remplacer, gabarit)


@dataclass(frozen=True, slots=True)
class ModeleCourriel:
    code: str
    libelle: str
    sujet: str
    corps: str
    description: str = ""
    # À qui ce modèle s'adresse. L'écran des candidatures ne doit pas proposer
    # d'envoyer à un candidat le message d'accès destiné au commanditaire :
    # l'erreur serait facile à commettre et impossible à rattraper.
    destinataire: str = "CANDIDAT"


MODELES: tuple[ModeleCourriel, ...] = (
    ModeleCourriel(
        code="PRESELECTION_RETENU",
        libelle="Présélection — candidature retenue",
        description="Informe un candidat présélectionné et annonce la suite.",
        sujet="Votre candidature au poste de {poste} — suite du processus",
        corps=(
            "Madame, Monsieur {nom},\n"
            "\n"
            "Nous accusons réception de votre candidature au poste de {poste} "
            "pour le compte de {client}.\n"
            "\n"
            "Après examen de votre dossier, nous avons le plaisir de vous "
            "informer que votre candidature a été présélectionnée. Vous serez "
            "prochainement contacté(e) pour la suite du processus de "
            "recrutement.\n"
            "\n"
            "Nous vous remercions de l'intérêt porté à cette opportunité.\n"
            "\n"
            "Cordialement,\n"
            "{signature}"
        ),
    ),
    ModeleCourriel(
        code="CONVOCATION_ENTRETIEN",
        libelle="Convocation à l'entretien",
        description="Convoque un candidat. Date, heure et lieu sont à compléter.",
        sujet="Convocation à un entretien — poste de {poste}",
        corps=(
            "Madame, Monsieur {nom},\n"
            "\n"
            "Suite à l'examen de votre candidature au poste de {poste}, nous "
            "avons le plaisir de vous convier à un entretien.\n"
            "\n"
            "Date : {date_entretien}\n"
            "Heure : {heure_entretien}\n"
            "Lieu : {lieu_entretien}\n"
            "\n"
            "Merci de vous munir des originaux des pièces transmises lors de "
            "votre candidature.\n"
            "\n"
            "Nous vous prions de bien vouloir confirmer votre présence en "
            "réponse à ce message.\n"
            "\n"
            "Cordialement,\n"
            "{signature}"
        ),
    ),
    ModeleCourriel(
        code="PIECE_MANQUANTE",
        libelle="Demande de pièce manquante",
        description="Réclame une pièce absente du dossier avant instruction.",
        sujet="Votre candidature au poste de {poste} — pièce(s) manquante(s)",
        corps=(
            "Madame, Monsieur {nom},\n"
            "\n"
            "Nous avons bien reçu votre candidature au poste de {poste}.\n"
            "\n"
            "Après vérification, il apparaît que votre dossier est incomplet. "
            "Les pièces suivantes nous font défaut :\n"
            "\n"
            "{pieces_manquantes}\n"
            "\n"
            "Nous vous remercions de nous les faire parvenir en réponse à ce "
            "message dans les meilleurs délais, afin que votre dossier puisse "
            "être instruit.\n"
            "\n"
            "Cordialement,\n"
            "{signature}"
        ),
    ),
    ModeleCourriel(
        code="NON_RETENU",
        libelle="Candidature non retenue",
        description="Réponse négative, après présélection ou après entretien.",
        sujet="Votre candidature au poste de {poste}",
        corps=(
            "Madame, Monsieur {nom},\n"
            "\n"
            "Nous avons examiné avec attention votre candidature au poste de "
            "{poste}.\n"
            "\n"
            "Nous sommes au regret de vous informer que celle-ci n'a pas été "
            "retenue pour la suite du processus.\n"
            "\n"
            "Votre dossier est conservé dans notre base de profils et pourra "
            "être réexaminé à l'occasion d'un prochain recrutement "
            "correspondant à votre parcours.\n"
            "\n"
            "Nous vous remercions de la confiance accordée et vous souhaitons "
            "plein succès dans vos démarches.\n"
            "\n"
            "Cordialement,\n"
            "{signature}"
        ),
    ),
    ModeleCourriel(
        code="ACCUSE_RECEPTION",
        libelle="Accusé de réception",
        description="Confirme au candidat que son dossier est bien arrivé.",
        sujet="Accusé de réception — candidature au poste de {poste}",
        corps=(
            "Madame, Monsieur {nom},\n"
            "\n"
            "Nous accusons réception de votre candidature au poste de {poste}.\n"
            "\n"
            "Votre dossier sera examiné et vous serez informé(e) de la suite "
            "réservée à votre candidature.\n"
            "\n"
            "Cordialement,\n"
            "{signature}"
        ),
    ),
    ModeleCourriel(
        code="ACCES_CLIENT",
        libelle="Accès à l'espace de suivi (client)",
        description="Transmet au promoteur son lien d'activation à usage unique.",
        destinataire="CLIENT",
        sujet="Votre espace de suivi — recrutement {mandat}",
        corps=(
            "Madame, Monsieur {nom},\n"
            "\n"
            "Dans le cadre du mandat « {mandat} », nous mettons à votre "
            "disposition un espace de suivi en ligne. Vous y trouverez l'état "
            "d'avancement du recrutement et pourrez échanger directement avec "
            "notre équipe.\n"
            "\n"
            "Pour activer votre accès et choisir votre mot de passe, suivez ce "
            "lien :\n"
            "\n"
            "{lien_activation}\n"
            "\n"
            "Ce lien est personnel et ne peut être utilisé qu'une seule fois. "
            "Il expire le {expiration}.\n"
            "\n"
            "Cordialement,\n"
            "{signature}"
        ),
    ),
)

PAR_CODE = {m.code: m for m in MODELES}


def modele(code: str) -> ModeleCourriel:
    try:
        return PAR_CODE[code]
    except KeyError as exc:
        raise ValueError(f"Modèle de courriel inconnu : {code}") from exc


def preparer(
    code: str,
    destinataire: str,
    valeurs: dict[str, object],
    nom_destinataire: str = "",
) -> Message:
    """Rédige un message à partir d'un modèle, sans l'envoyer."""
    gabarit = modele(code)
    return Message(
        destinataire=destinataire,
        nom_destinataire=nom_destinataire,
        sujet=rendre(gabarit.sujet, valeurs).strip(),
        corps=rendre(gabarit.corps, valeurs),
    )


# --- expédition ------------------------------------------------------------


def _construire(message: Message, expediteur: str, nom_expediteur: str) -> EmailMessage:
    courriel = EmailMessage()
    courriel["From"] = formataddr((nom_expediteur or "", expediteur))
    courriel["To"] = formataddr((message.nom_destinataire or "", message.destinataire))
    if message.copie:
        courriel["Cc"] = ", ".join(message.copie)
    courriel["Subject"] = message.sujet
    courriel.set_content(message.corps)
    return courriel


def _authentifier(serveur: smtplib.SMTP, reglages: Reglages) -> None:
    """Ouvre la session : jeton Microsoft si l'accès OAuth est réglé, sinon mot de passe."""
    if reglages.oauth_utilisable:
        # Microsoft a retiré l'authentification par mot de passe sur SMTP AUTH
        # comme sur IMAP. Le jeton se présente en base64, après AUTH XOAUTH2.
        acces = oauth_microsoft.jeton(reglages.config_oauth, reglages.smtp_user)
        chaine = oauth_microsoft.chaine_xoauth2(reglages.smtp_user, acces)
        code, reponse = serveur.docmd(
            "AUTH", "XOAUTH2 " + base64.b64encode(chaine.encode()).decode()
        )
        if code != 235:
            raise ErreurEnvoi(
                f"Le serveur d'envoi a refusé le jeton Microsoft "
                f"(code {code}) : {reponse.decode(errors='replace')[:200]}"
            )
    elif reglages.smtp_user:
        serveur.login(reglages.smtp_user, reglages.smtp_password)


def _ouvrir_smtp(reglages: Reglages, timeout: int) -> smtplib.SMTP:
    """Une session SMTP chiffrée et authentifiée, à fermer par l'appelant."""
    contexte = ssl.create_default_context()
    if reglages.smtp_port == 465:
        # Port historique : la session est chiffrée dès l'ouverture, il n'y a
        # pas de STARTTLS à négocier.
        serveur: smtplib.SMTP = smtplib.SMTP_SSL(
            reglages.smtp_host, reglages.smtp_port, timeout=timeout, context=contexte
        )
    else:
        serveur = smtplib.SMTP(reglages.smtp_host, reglages.smtp_port, timeout=timeout)
    try:
        if reglages.smtp_port != 465 and reglages.smtp_tls:
            serveur.starttls(context=contexte)
        _authentifier(serveur, reglages)
    except BaseException:
        serveur.close()
        raise
    return serveur


def _refus_identifiants(reglages: Reglages) -> str:
    if _est_microsoft(reglages.smtp_host):
        return (
            "Le serveur d'envoi a refusé les identifiants. Microsoft n'accepte plus "
            "de mot de passe sur SMTP, ni de « mot de passe d'application » : "
            "choisissez « Microsoft 365 » dans Paramètres › Courriel."
        )
    return (
        "Le serveur d'envoi a refusé les identifiants. Vérifiez le compte et le mot "
        "de passe ; certains fournisseurs exigent un « mot de passe d'application » "
        "plutôt que le mot de passe du compte."
    )


def _expedier_smtp(message: Message, reglages: Reglages, nom_expediteur: str) -> None:
    """L'envoi par SMTP. Bloquant : appelé dans un fil séparé."""
    courriel = _construire(message, reglages.expediteur, nom_expediteur)
    try:
        with _ouvrir_smtp(reglages, timeout=30) as serveur:
            serveur.send_message(courriel)
    except oauth_microsoft.ErreurOAuth as exc:
        raise ErreurEnvoi(str(exc)) from exc
    except smtplib.SMTPAuthenticationError as exc:
        raise ErreurEnvoi(_refus_identifiants(reglages)) from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise ErreurEnvoi(
            f"Adresse refusée par le serveur : {message.destinataire}"
        ) from exc
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        raise ErreurEnvoi(f"Envoi impossible : {exc}") from exc


def _config_graph(reglages: Reglages):
    return graph_microsoft.config_graph(
        reglages.oauth_tenant, reglages.oauth_client_id, reglages.oauth_client_secret
    )


def _expedier_graph(message: Message, reglages: Reglages, nom_expediteur: str) -> None:
    """L'envoi par Microsoft Graph. Bloquant : appelé dans un fil séparé."""
    try:
        graph_microsoft.envoyer(
            _config_graph(reglages),
            reglages.expediteur,
            message.destinataire,
            message.sujet,
            message.corps,
            nom_destinataire=message.nom_destinataire,
            copie=message.copie,
            nom_expediteur=nom_expediteur,
        )
    except graph_microsoft.ErreurGraph as exc:
        raise ErreurEnvoi(str(exc)) from exc


async def envoyer(message: Message, reglages: Reglages, nom_expediteur: str = "") -> None:
    """Expédie un message déjà relu.

    L'envoi est synchrone et bloque le temps de la connexion ; l'exécuter dans
    un fil évite de figer la boucle pendant qu'un serveur lent répond.
    """
    if not reglages.envoi_utilisable:
        raise ErreurEnvoi(
            "L'envoi de courriels n'est pas configuré. Renseignez-le dans "
            "Paramètres › Courriel."
        )
    expedier = _expedier_graph if reglages.microsoft365 else _expedier_smtp
    await asyncio.to_thread(expedier, message, reglages, nom_expediteur)


async def verifier(reglages: Reglages) -> None:
    """Valide la configuration d'envoi sans rien expédier."""
    if not reglages.envoi_utilisable:
        raise ErreurEnvoi("L'envoi de courriels n'est pas configuré.")

    def _tester_graph() -> None:
        try:
            graph_microsoft.verifier_envoi(_config_graph(reglages), reglages.expediteur)
        except graph_microsoft.ErreurGraph as exc:
            raise ErreurEnvoi(str(exc)) from exc

    def _tester_smtp() -> None:
        # Même ouverture de session que l'envoi réel, jeton Microsoft compris :
        # un test qui s'authentifie autrement que l'envoi ne prouverait rien.
        try:
            with _ouvrir_smtp(reglages, timeout=20):
                pass
        except oauth_microsoft.ErreurOAuth as exc:
            raise ErreurEnvoi(str(exc)) from exc
        except smtplib.SMTPAuthenticationError as exc:
            raise ErreurEnvoi(_refus_identifiants(reglages)) from exc
        except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
            raise ErreurEnvoi(f"Connexion impossible : {exc}") from exc

    await asyncio.to_thread(_tester_graph if reglages.microsoft365 else _tester_smtp)
