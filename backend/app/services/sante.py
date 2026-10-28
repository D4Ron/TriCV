"""L'état de l'application : ce qui est branché, et si les candidats arrivent.

L'administrateur n'avait aucun moyen de savoir, depuis l'écran, si le site
tournait vraiment. Les pannes étaient muettes : la rédaction d'un avis
renvoyait un squelette sans dire que la clé du modèle manquait, le courriel ne
partait pas, et un serveur frontal refusait les dossiers de plus d'un
mégaoctet sans que rien, dans l'application, n'en garde trace. Il a fallu
relire la configuration du serveur pour l'apprendre.

Ce module rassemble ces constats en un endroit, chacun avec son état, une
phrase qui dit pourquoi, et l'endroit où le régler. Il dit aussi ce qu'il ne
sait pas : la limite du serveur frontal ne se voit que depuis un navigateur,
et l'écran la mesure lui-même.

La fréquentation complète le tableau. Les candidatures se lisent en base ; les
visites et les dépôts refusés, que le serveur ne voit pas, sont signalés par
le navigateur du visiteur et comptés par jour — sans rien qui identifie qui
que ce soit.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import date, timedelta

import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models import (
    Avis,
    Candidature,
    Frequentation,
    Poste,
    SourceCandidature,
    StatutAvis,
    User,
)
from app.models.base import utcnow
from app.security import verify_password
from app.services import parametres

logger = logging.getLogger(__name__)

# Les états d'une vérification, du meilleur au pire.
OK = "ok"
INFO = "info"
A_VERIFIER = "a_verifier"  # ne se mesure que depuis le navigateur
A_REGLER = "a_regler"


@dataclass
class Verification:
    code: str
    libelle: str
    etat: str
    detail: str
    # Où le régler : un onglet des paramètres (« courriel », « comptes »…), ou
    # « serveur » quand cela se fait hors de l'application.
    ou: str = ""


# --- les compteurs -----------------------------------------------------------


async def compter(evenement: str, poste_id: str = "") -> None:
    """Incrémente le compteur du jour, sans jamais faire échouer l'appelant.

    Une session à part : sur PostgreSQL, une écriture ratée laisse la session
    dans un état d'échec, et compter une visite ne doit pas pouvoir faire
    tomber la page qu'on visite.
    """
    jour = utcnow().date()
    try:
        async with SessionLocal() as db:
            dialecte = db.bind.dialect.name if db.bind is not None else ""
            if dialecte == "postgresql":
                from sqlalchemy.dialects.postgresql import insert
            else:
                from sqlalchemy.dialects.sqlite import insert

            requete = insert(Frequentation).values(
                id=str(uuid.uuid4()),
                jour=jour,
                evenement=evenement,
                poste_id=poste_id or "",
                compte=1,
            )
            requete = requete.on_conflict_do_update(
                index_elements=["jour", "evenement", "poste_id"],
                set_={"compte": Frequentation.compte + 1},
            )
            await db.execute(requete)
            await db.commit()
    except Exception:
        logger.exception("compteur de fréquentation indisponible (%s)", evenement)


async def poste_de_la_cle(db: AsyncSession, cle: str) -> str:
    """Le poste d'un avis désigné par sa clé publique ou son code court."""
    cle = (cle or "").strip()
    if not cle or len(cle) > 64:
        return ""
    trouve = (
        await db.execute(
            select(Avis.poste_id).where(
                sa.or_(Avis.cle_publique == cle, Avis.code_court == cle)
            )
        )
    ).scalar_one_or_none()
    return trouve or ""


# --- les vérifications ---------------------------------------------------------


def _masquer(texte: str) -> str:
    """Retire d'un message d'erreur ce qui pourrait ressembler à une clé.

    Certains fournisseurs passent la clé dans l'adresse (`?key=…`), et une
    erreur réseau la recopie volontiers. Ce texte s'affiche à l'écran.
    """
    texte = re.sub(r"(key|token|secret|apikey|api_key)=[^&\s\"']+", r"\1=…", texte, flags=re.I)
    return re.sub(r"\b[A-Za-z0-9_\-]{32,}\b", "…", texte)[:300]


def _verifier_ia() -> Verification:
    from app.llm.factory import build_chain

    nom = settings.llm_provider or "aucun"
    try:
        build_chain()
    except Exception as exc:
        return Verification(
            "ia",
            "Modèle d'IA",
            A_REGLER,
            f"Le fournisseur « {nom} » ne peut pas être utilisé : {_masquer(str(exc))} "
            "Les avis et les rapports arrivent en squelette, à rédiger à la main.",
            "serveur",
        )
    return Verification(
        "ia",
        "Modèle d'IA",
        OK,
        f"Fournisseur « {nom} » configuré. Seul un essai réel dit si la clé est "
        "acceptée — bouton « Essayer ».",
        "serveur",
    )


async def _verifier_admin_par_defaut(db: AsyncSession) -> Verification | None:
    """Le compte créé au premier démarrage garde-t-il son mot de passe d'origine ?

    Ce mot de passe figure dans le code source : tant qu'il n'est pas changé,
    quiconque a lu le dépôt peut entrer.
    """
    compte = (
        await db.execute(select(User).where(User.email == settings.seed_admin_email.lower()))
    ).scalar_one_or_none()
    if compte is None or not compte.is_active:
        return None
    try:
        par_defaut = verify_password(settings.seed_admin_password, compte.password_hash)
    except Exception:
        return None
    if not par_defaut:
        return None
    return Verification(
        "admin_defaut",
        "Compte administrateur d'origine",
        A_REGLER,
        f"Le compte {compte.email} a toujours son mot de passe par défaut, publié "
        "dans le code source. Changez-le ou désactivez le compte.",
        "comptes",
    )


async def verifications(db: AsyncSession) -> list[Verification]:
    reglages = await parametres.lire(db)
    resultats: list[Verification] = []

    # La base répond, sinon cet appel lui-même aurait échoué.
    await db.execute(select(1))
    resultats.append(Verification("base", "Base de données", OK, "Elle répond."))

    resultats.append(_verifier_ia())

    # Le relevé et l'envoi du courriel.
    if reglages.courriel_utilisable:
        resultats.append(
            Verification(
                "releve",
                "Relevé de la boîte",
                OK,
                f"La boîte {reglages.boite} est relevable.",
                "courriel",
            )
        )
    else:
        manquants = parametres.ce_qui_manque(reglages)
        raisons = []
        if not reglages.courriel_actif:
            raisons.append("le relevé est désactivé")
        if manquants:
            raisons.append("il manque " + " et ".join(manquants))
        resultats.append(
            Verification(
                "releve",
                "Relevé de la boîte",
                A_REGLER,
                "Les candidatures envoyées par courriel ne sont pas récupérées : "
                + " ; ".join(raisons or ["la boîte n'est pas configurée"])
                + ".",
                "courriel",
            )
        )

    if reglages.envoi_utilisable:
        resultats.append(
            Verification(
                "envoi",
                "Envoi de courriels",
                OK,
                f"Les messages partent de {reglages.expediteur}.",
                "courriel",
            )
        )
    else:
        raison = (
            "l'envoi est désactivé"
            if not reglages.smtp_actif
            else "la configuration est incomplète"
        )
        resultats.append(
            Verification(
                "envoi",
                "Envoi de courriels",
                A_REGLER,
                f"Aucun message ne part aux candidats ni au client : {raison}.",
                "courriel",
            )
        )

    if reglages.url_publique.strip():
        resultats.append(
            Verification(
                "adresse",
                "Adresse publique",
                OK,
                reglages.url_publique.strip(),
                "courriel",
            )
        )
    else:
        resultats.append(
            Verification(
                "adresse",
                "Adresse publique",
                A_REGLER,
                "Non renseignée : les liens envoyés par courriel ne peuvent pas être écrits.",
                "courriel",
            )
        )

    if reglages.contact:
        resultats.append(
            Verification(
                "contact",
                "Contact des candidats",
                OK,
                f"{reglages.contact}, affiché sur les pages publiques.",
                "courriel",
            )
        )
    else:
        resultats.append(
            Verification(
                "contact",
                "Contact des candidats",
                A_REGLER,
                "Aucune adresse : un candidat bloqué n'a personne à qui écrire.",
                "courriel",
            )
        )

    # Les avis en ligne : ce que voit un visiteur.
    aujourd_hui = utcnow().date()
    publies = (
        await db.execute(
            select(Avis).where(
                Avis.statut == StatutAvis.PUBLIE, Avis.accepte_candidatures.is_(True)
            )
        )
    ).scalars().all()
    ouverts = [
        a for a in publies if a.date_cloture is None or a.date_cloture >= aujourd_hui
    ]
    echus = len(publies) - len(ouverts)
    if ouverts:
        detail = (
            "1 avis accepte des candidatures."
            if len(ouverts) == 1
            else f"{len(ouverts)} avis acceptent des candidatures."
        )
        if echus == 1:
            detail += " Un autre, toujours publié, a passé sa date de clôture."
        elif echus:
            detail += f" {echus} autres, toujours publiés, ont passé leur date de clôture."
        resultats.append(Verification("avis", "Avis en ligne", OK, detail))
    else:
        resultats.append(
            Verification(
                "avis",
                "Avis en ligne",
                INFO,
                "Aucun avis n'accepte de candidatures : la page des postes ouverts "
                "est vide.",
            )
        )

    # Mesurée par l'écran : le serveur ne voit pas ce que le frontal refuse.
    resultats.append(
        Verification(
            "depot",
            "Taille des dépôts",
            A_VERIFIER,
            "Se mesure depuis le navigateur : un serveur frontal trop restrictif "
            "refuse les dossiers avant que l'application les voie.",
            "serveur",
        )
    )

    securite = await _verifier_admin_par_defaut(db)
    if securite is not None:
        resultats.append(securite)

    return resultats


# --- la fréquentation ------------------------------------------------------------


def _jour(valeur) -> str:
    """Une date SQL en « AAAA-MM-JJ », que le moteur rende une date ou un texte."""
    return valeur.isoformat() if isinstance(valeur, date) else str(valeur)[:10]


async def frequentation(db: AsyncSession, jours: int = 30) -> dict:
    debut = utcnow().date() - timedelta(days=jours - 1)
    serie = {
        (debut + timedelta(days=i)).isoformat(): {
            "visites": 0,
            "candidatures": 0,
            "refus_taille": 0,
            "echecs": 0,
        }
        for i in range(jours)
    }
    par_poste: dict[str, dict] = {}

    def ligne_poste(poste_id: str) -> dict:
        return par_poste.setdefault(
            poste_id,
            {"poste_id": poste_id, "visites": 0, "candidatures": 0, "refus_taille": 0},
        )

    compteurs = (
        await db.execute(
            select(
                Frequentation.jour,
                Frequentation.evenement,
                Frequentation.poste_id,
                Frequentation.compte,
            ).where(Frequentation.jour >= debut)
        )
    ).all()
    for jour, evenement, poste_id, compte in compteurs:
        cle = _jour(jour)
        if cle not in serie:
            continue
        if evenement.startswith("visite_"):
            serie[cle]["visites"] += compte
        elif evenement == "depot_refuse_taille":
            serie[cle]["refus_taille"] += compte
        elif evenement == "depot_echoue":
            serie[cle]["echecs"] += compte
        if poste_id:
            ligne = ligne_poste(poste_id)
            if evenement == "visite_avis":
                ligne["visites"] += compte
            elif evenement == "depot_refuse_taille":
                ligne["refus_taille"] += compte

    # Les candidatures déposées sur le site : en base, avec leur date.
    recues = (
        await db.execute(
            select(
                func.date(Candidature.recue_le),
                Candidature.poste_id,
                func.count(Candidature.id),
            )
            .where(
                Candidature.recue_le >= debut,
                Candidature.source == SourceCandidature.FORMULAIRE,
            )
            .group_by(func.date(Candidature.recue_le), Candidature.poste_id)
        )
    ).all()
    for jour, poste_id, nombre in recues:
        cle = _jour(jour)
        if cle in serie:
            serie[cle]["candidatures"] += nombre
        if poste_id:
            ligne_poste(poste_id)["candidatures"] += nombre

    # Les intitulés, pour un tableau qui se lit sans identifiants.
    if par_poste:
        intitules = dict(
            (
                await db.execute(
                    select(Poste.id, Poste.intitule).where(Poste.id.in_(par_poste))
                )
            ).all()
        )
        for poste_id, ligne in par_poste.items():
            ligne["intitule"] = intitules.get(poste_id, "Poste supprimé")

    jours_liste = [{"jour": cle, **valeurs} for cle, valeurs in serie.items()]
    totaux = {
        champ: sum(j[champ] for j in jours_liste)
        for champ in ("visites", "candidatures", "refus_taille", "echecs")
    }
    return {
        "debut": debut.isoformat(),
        "jours": jours_liste,
        "totaux": totaux,
        "par_poste": sorted(
            par_poste.values(), key=lambda l: (l["visites"], l["candidatures"]), reverse=True
        ),
    }


def en_dict(verification: Verification) -> dict:
    return asdict(verification)
