"""Contrôle avant un usage réel.

Répond à une seule question : cette installation peut-elle recevoir de vrais
dossiers de candidature ? La réponse n'est pas « ça démarre » — un serveur qui
démarre avec un secret de développement, un mot de passe d'administrateur par
défaut et onze candidats fictifs en base démarre parfaitement, et perd les
données du premier candidat réel qui arrive.

Trois niveaux :

    BLOQUANT   à corriger avant de recevoir un dossier réel.
    À VOIR     acceptable si c'est un choix, à connaître sinon.
    OK         vérifié.

Le script ne corrige rien de lui-même. Chaque constat dit quoi faire, et le
code de sortie vaut 1 s'il reste un bloquant — de quoi l'enchaîner dans un
script de démarrage.

    python preflight.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal

# Valeurs livrées avec le dépôt. Les retrouver en production signifie que
# personne n'a ouvert le fichier de configuration.
SECRETS_CONNUS = {
    "dev-only-insecure-secret-change-me",
    "dev-only-secret",
    "change-me",
    "secret",
}
MOTS_DE_PASSE_CONNUS = {"admin1234", "admin", "password", "changeme"}

BLOQUANT = "BLOQUANT"
A_VOIR = "À VOIR"
OK = "OK"


class Rapport:
    def __init__(self) -> None:
        self.lignes: list[tuple[str, str, str]] = []

    def ajouter(self, niveau: str, sujet: str, detail: str = "") -> None:
        self.lignes.append((niveau, sujet, detail))

    @property
    def bloquants(self) -> int:
        return sum(1 for niveau, _, _ in self.lignes if niveau == BLOQUANT)

    def afficher(self) -> None:
        largeur = max(len(n) for n, _, _ in self.lignes)
        for niveau, sujet, detail in self.lignes:
            print(f"  {niveau.ljust(largeur)}  {sujet}")
            if detail:
                for ligne in detail.splitlines():
                    print(f"  {' ' * largeur}    {ligne}")


# --- contrôles ---------------------------------------------------------------


def controler_secrets(rapport: Rapport) -> None:
    if settings.jwt_secret in SECRETS_CONNUS or len(settings.jwt_secret) < 32:
        rapport.ajouter(
            BLOQUANT,
            "JWT_SECRET est celui du dépôt, ou trop court.",
            "Quiconque connaît ce dépôt peut forger un jeton et lire tous les dossiers.\n"
            "Générer :  python -c \"import secrets; print(secrets.token_urlsafe(48))\"\n"
            "puis le placer dans .env. Changer le secret déconnecte tout le monde une fois.",
        )
    else:
        rapport.ajouter(OK, "JWT_SECRET propre à cette installation.")

    if settings.seed_admin_password in MOTS_DE_PASSE_CONNUS:
        rapport.ajouter(
            BLOQUANT,
            "SEED_ADMIN_PASSWORD est un mot de passe de démonstration.",
            "Le compte administrateur voit tous les candidats de tous les mandats.\n"
            "Changer SEED_ADMIN_PASSWORD dans .env avant de créer le compte.",
        )
    else:
        rapport.ajouter(OK, "Mot de passe administrateur personnalisé.")

    # Qui peut se créer un compte est une question à poser avant un vrai test,
    # pas seulement dans le pire des cas : un compte RH voit tous les dossiers
    # de tous les mandats.
    if settings.allow_self_registration and not settings.signup_code:
        rapport.ajouter(
            BLOQUANT,
            "Inscription libre ouverte, sans code.",
            "Toute personne atteignant la page peut se créer un compte RH et lire les\n"
            "dossiers de tous les candidats. Poser un SIGNUP_CODE, ou mettre\n"
            "ALLOW_SELF_REGISTRATION=false et créer les comptes à la main.",
        )
    elif settings.allow_self_registration:
        rapport.ajouter(
            A_VOIR,
            "Inscription libre ouverte, protégée par un code.",
            "Acceptable le temps de créer les comptes de l'équipe. À refermer ensuite :\n"
            "ALLOW_SELF_REGISTRATION=false, ou le réglage dans Paramètres.",
        )
    else:
        rapport.ajouter(OK, "Inscription libre fermée.")


def controler_confidentialite(rapport: Rapport) -> None:
    if not settings.pii_redaction:
        rapport.ajouter(
            BLOQUANT,
            "PII_REDACTION=false — les fichiers partent tels quels au fournisseur.",
            "Mettre PII_REDACTION=true, sauf décision explicite et documentée.",
        )
    else:
        rapport.ajouter(OK, "Expurgation des identifiants active.")

    if not settings.redact_demographics:
        rapport.ajouter(
            A_VOIR,
            "REDACT_DEMOGRAPHICS=false — âge, sexe et nationalité partent au modèle.",
            "Ces données restent nécessaires localement pour les conditions restrictives ;\n"
            "les envoyer à un service externe est une décision distincte.",
        )

    try:
        from app.services.redaction import loaded_ner_models

        modeles = loaded_ner_models()
    except Exception:  # pragma: no cover - dépend de l'installation
        modeles = []
    if modeles:
        rapport.ajouter(OK, f"Reconnaissance d'entités chargée ({', '.join(modeles)}).")
    else:
        rapport.ajouter(
            A_VOIR,
            "Aucun modèle spaCy chargé.",
            "L'expurgation retombe sur les expressions régulières et les valeurs du\n"
            "formulaire : un nom de ville isolé peut survivre. Installer avec\n"
            "start-dev.ps1 -WithNer (Python 3.12) ou l'image Docker.",
        )


def controler_modele(rapport: Rapport) -> None:
    cles = {
        "gemini": settings.gemini_api_key,
        "anthropic": settings.anthropic_api_key,
        "ollama": "local",
        "openai": settings.llm_api_key,
    }
    cle = cles.get(settings.llm_provider, "")
    if not cle and settings.llm_fallback.strip():
        # Un secours est déclaré : la chaîne, contrôlée juste après, dira ce
        # qui tourne vraiment. Annoncer ici « aucun modèle » serait faux.
        rapport.ajouter(
            A_VOIR,
            f"Le fournisseur principal ({settings.llm_provider}) attend sa clé.",
            "Il est écarté tant qu'elle manque ; le secours prend le relais.\n"
            "Poser la clé suffit à le promouvoir, sans rien changer d'autre.",
        )
    elif not cle:
        rapport.ajouter(
            A_VOIR,
            f"Aucune clé pour {settings.llm_provider}.",
            "La présélection déterministe (barème, éligibilité, grille) fonctionne sans\n"
            "modèle. Seule l'aide à l'extraction des CV en a besoin.",
        )
    elif settings.llm_provider == "openai" and not settings.llm_base_url:
        rapport.ajouter(
            A_VOIR,
            "LLM_PROVIDER=openai sans LLM_BASE_URL.",
            "Ce fournisseur désigne une adresse, pas une marque : Groq, Mistral,\n"
            "OpenRouter, un vLLM local. Voir .env.example.",
        )
    elif settings.llm_provider == "gemini" and cle:
        rapport.ajouter(
            A_VOIR,
            "Fournisseur Gemini : vérifier qu'il s'agit d'une clé payante.",
            "L'offre gratuite de Google autorise l'entraînement sur ce qui est envoyé.\n"
            "Pour de vrais CV : clé payante, ou LLM_PROVIDER=ollama (rien ne sort).",
        )
    elif settings.llm_provider == "openai" and "mistral.ai" in settings.llm_base_url:
        # La même réserve que pour Gemini, avec une différence qui compte : chez
        # Mistral l'entraînement sur l'offre gratuite se refuse d'une case à
        # décocher, sans changer d'offre ni de carte.
        rapport.ajouter(
            A_VOIR,
            "Fournisseur Mistral : vérifier le refus d'entraînement.",
            "L'offre gratuite (Experiment) autorise par défaut l'entraînement sur\n"
            "ce qui est envoyé. Le refus se pose dans la console Mistral,\n"
            "Admin > Privacy. Sans ce geste, de vrais parcours y passent.",
        )
        if settings.llm_max_concurrency > 1:
            rapport.ajouter(
                A_VOIR,
                f"LLM_MAX_CONCURRENCY={settings.llm_max_concurrency} sur une offre à 1 requête/s.",
                "L'offre gratuite de Mistral plafonne à une requête par seconde.\n"
                "Au-delà de 1, les appels partent en rafale, se font refuser, et\n"
                "attendent la reprise. LLM_MAX_CONCURRENCY=1 va plus vite.",
            )
    else:
        rapport.ajouter(OK, f"Fournisseur {settings.llm_provider} configuré.")

    _controler_chaine(rapport)


def _controler_chaine(rapport: Rapport) -> None:
    """La chaîne de secours : ce qu'elle est, et ce qu'une bascule changerait."""
    if not settings.llm_fallback.strip():
        return

    from app.llm.factory import build_chain

    try:
        chaine = build_chain()
    except Exception as exc:  # LLMConfigError, et tout ce qui empêche de bâtir
        rapport.ajouter(A_VOIR, f"Chaîne de secours inutilisable : {exc}")
        return

    noms = [f.name for f in getattr(chaine, "fournisseurs", [chaine])]
    if len(noms) == 1:
        rapport.ajouter(
            A_VOIR,
            f"Secours déclaré, mais un seul fournisseur utilisable ({noms[0]}).",
            "Les autres manquent de clé et sont écartés. L'application marche,\n"
            "sans filet : un quota épuisé arrêtera le dépouillement.",
        )
        return

    rapport.ajouter(OK, "Chaîne de secours : " + " puis ".join(noms) + ".")

    # La réserve qui compte. Les offres gratuites n'ont pas la même politique :
    # celle de Mistral se règle pour refuser l'entraînement, celle de Google
    # entraîne sans réglage possible. Descendre de l'une à l'autre sans le
    # savoir ferait passer de vrais parcours d'un fournisseur qui les oublie à
    # un fournisseur qui les retient — et personne ne l'aurait décidé.
    if "gemini" in noms[1:] and settings.gemini_api_key:
        rapport.ajouter(
            A_VOIR,
            "Le secours Gemini n'a pas la même confidentialité que le principal.",
            "Sur l'offre gratuite, Google entraîne sur ce qui est envoyé, sans\n"
            "réglage pour le refuser. Une bascule y enverra donc des parcours\n"
            "réels — expurgés de toute identité, mais réels. À décider une fois :\n"
            "clé payante, ou LLM_FALLBACK vide et un quota épuisé qui s'assume.",
        )


def controler_stockage(rapport: Rapport) -> None:
    if settings.storage_backend != "local":
        rapport.ajouter(OK, f"Stockage {settings.storage_backend}.")
        return

    chemin = Path(settings.storage_path)
    try:
        chemin.mkdir(parents=True, exist_ok=True)
        temoin = chemin / ".preflight"
        temoin.write_bytes(b"ok")
        temoin.unlink()
        rapport.ajouter(OK, f"Stockage des pièces accessible en écriture ({chemin}).")
    except OSError as exc:
        rapport.ajouter(
            BLOQUANT,
            f"Impossible d'écrire dans {chemin} ({exc}).",
            "Les pièces jointes ne pourront pas être enregistrées.",
        )


async def controler_base(rapport: Rapport) -> None:
    from app.models import Candidat, Client, User

    try:
        async with SessionLocal() as db:
            clients = (await db.execute(select(func.count(Client.id)))).scalar_one()
            candidats = (await db.execute(select(func.count(Candidat.id)))).scalar_one()
            comptes = (await db.execute(select(func.count(User.id)))).scalar_one()
            exemples = (
                await db.execute(
                    select(func.count(Candidat.id)).where(
                        Candidat.email.like("%@example.com")
                    )
                )
            ).scalar_one()
    except Exception as exc:  # pragma: no cover - dépend du déploiement
        rapport.ajouter(
            BLOQUANT,
            f"Base inaccessible ({exc}).",
            "Lancer bootstrap_db.py, ou vérifier DATABASE_URL dans .env.",
        )
        return

    rapport.ajouter(OK, f"Base joignable — {comptes} compte(s), {clients} client(s).")

    if exemples:
        rapport.ajouter(
            BLOQUANT,
            f"{exemples} candidat(s) de démonstration en base (adresses @example.com).",
            "Mélanger des dossiers fictifs à de vrais dossiers fausse les grilles et le\n"
            "vivier. Repartir d'une base vide :\n"
            "  start-dev.ps1 -Fresh        (efface la base et les pièces, sans démo)",
        )
    elif candidats:
        rapport.ajouter(OK, f"{candidats} candidat(s) en base, aucun de démonstration.")
    else:
        rapport.ajouter(OK, "Base vide, prête à recevoir de vrais dossiers.")


async def controler_courriel(rapport: Rapport) -> None:
    from app.services import parametres

    try:
        async with SessionLocal() as db:
            reglages = await parametres.lire(db)
    except Exception:  # pragma: no cover
        return

    if reglages.courriel_utilisable:
        rapport.ajouter(OK, f"Boîte de candidatures configurée ({reglages.imap_user}).")
    elif reglages.courriel_actif:
        rapport.ajouter(
            A_VOIR,
            "Relevé activé mais boîte incomplète.",
            "Compléter dans Paramètres › Boîte de candidatures, puis « Tester la connexion ».",
        )
    else:
        rapport.ajouter(
            A_VOIR,
            "Relevé de la boîte désactivé.",
            "Les dossiers reçus par email se déposent à la main depuis le poste\n"
            "(« Déposer des dossiers »). Pour automatiser : Paramètres › Boîte de candidatures.",
        )


async def controler_envoi(rapport: Rapport) -> None:
    """L'envoi de courriels, et l'adresse publique dont dépendent les liens."""
    from app.services import parametres

    try:
        async with SessionLocal() as db:
            reglages = await parametres.lire(db)
    except Exception:  # pragma: no cover
        return

    if reglages.envoi_utilisable:
        rapport.ajouter(OK, f"Envoi de courriels configuré ({reglages.expediteur}).")
    elif reglages.smtp_actif:
        rapport.ajouter(
            A_VOIR,
            "Envoi activé mais incomplet.",
            "Compléter dans Paramètres › Envoi de courriels, puis « Tester l'envoi ».",
        )
    else:
        rapport.ajouter(
            A_VOIR,
            "Envoi de courriels désactivé.",
            "Les convocations et les réponses se rédigent quand même dans l'application,\n"
            "mais doivent être recopiées à la main. L'ouverture d'un accès client, elle,\n"
            "affichera son lien d'activation à transmettre soi-même.",
        )

    if not reglages.url_publique:
        rapport.ajouter(
            A_VOIR,
            "Adresse publique de l'application non renseignée.",
            "Sans elle, les liens d'activation envoyés aux clients ne peuvent pas être\n"
            "construits — le serveur ne connaît que son adresse d'écoute.\n"
            "À renseigner dans Paramètres › Envoi de courriels.",
        )


def controler_reseau(rapport: Rapport) -> None:
    origines = [o for o in settings.cors_origins if o]
    if any("*" == o for o in origines):
        rapport.ajouter(
            BLOQUANT,
            "CORS_ORIGINS autorise toutes les origines.",
            "Lister explicitement les adresses depuis lesquelles l'application est ouverte.",
        )
    else:
        rapport.ajouter(OK, f"CORS restreint à {len(origines)} origine(s).")


async def principal() -> int:
    rapport = Rapport()
    controler_secrets(rapport)
    controler_confidentialite(rapport)
    controler_modele(rapport)
    controler_stockage(rapport)
    controler_reseau(rapport)
    await controler_base(rapport)
    await controler_courriel(rapport)
    await controler_envoi(rapport)

    print()
    print("  TriCV — contrôle avant usage réel")
    print()
    rapport.afficher()
    print()

    if rapport.bloquants:
        print(f"  {rapport.bloquants} point(s) bloquant(s) à corriger avant de recevoir")
        print("  de vrais dossiers de candidature.")
        print()
        return 1

    print("  Aucun point bloquant.")
    print()
    return 0


if __name__ == "__main__":
    # Le script se lance depuis backend/ ; le .env est à la racine du dépôt.
    os.chdir(Path(__file__).resolve().parent)
    sys.exit(asyncio.run(principal()))
