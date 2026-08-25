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
    }
    cle = cles.get(settings.llm_provider, "")
    if not cle:
        rapport.ajouter(
            A_VOIR,
            f"Aucune clé pour {settings.llm_provider}.",
            "La présélection déterministe (barème, éligibilité, grille) fonctionne sans\n"
            "modèle. Seule l'aide à l'extraction des CV en a besoin.",
        )
    elif settings.llm_provider == "gemini" and cle:
        rapport.ajouter(
            A_VOIR,
            "Fournisseur Gemini : vérifier qu'il s'agit d'une clé payante.",
            "L'offre gratuite de Google autorise l'entraînement sur ce qui est envoyé.\n"
            "Pour de vrais CV : clé payante, ou LLM_PROVIDER=ollama (rien ne sort).",
        )
    else:
        rapport.ajouter(OK, f"Fournisseur {settings.llm_provider} configuré.")


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
