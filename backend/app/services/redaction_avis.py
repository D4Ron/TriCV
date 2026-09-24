"""Rédaction de l'avis de recrutement à partir de la fiche de poste.

Deux voies, et le choix appartient à l'utilisateur :

- **texte libre** : l'assistance propose un avis à partir de la fiche, dans la
  présentation habituelle du cabinet ;
- **modèle imposé** : un client fournit sa trame, et l'avis s'y coule.

Aucune des deux n'est obligatoire — un avis peut toujours être écrit
entièrement à la main dans l'éditeur. C'est une aide à la rédaction, pas un
passage obligé.

Le squelette de l'avis est construit ici, en Python, à partir des champs de la
fiche : intitulé, niveau exigé, expérience, pièces à fournir, date de clôture,
et la façon de candidater. Ces éléments sont opposables une fois publiés — une
condition inventée devient une condition réelle, une adresse inventée fait
perdre sa candidature à qui l'emploie — donc ils ne sont jamais laissés à la
rédaction automatique. Celle-ci n'intervient que sur la prose qui les entoure.

**La fiche de poste fournie par le client**, quand elle est jointe au poste,
est donnée à lire en entier. C'est elle qui dit ce qu'est le poste : sa
mission, ses responsabilités, son contexte. Sans elle, le modèle n'avait que
l'intitulé et quelques listes, et comblait le reste avec des généralités.
"""

from __future__ import annotations

import logging

from app.domain.referentiel import PieceDossier
from app.llm import prompts
from app.llm.factory import get_provider
from app.models import Avis, Mandat, Poste
from app.services.parametres import Reglages

logger = logging.getLogger(__name__)

# Le texte d'une fiche de poste tient en quelques pages ; au-delà, c'est un
# document annexe qui s'est glissé dans le dépôt, et il n'éclaire pas l'avis.
LONGUEUR_FICHE_MAX = 15000

TITRE_AIDE = "En cas de difficulté"


def _libelle_piece(code: str) -> str:
    try:
        return PieceDossier(code).libelle
    except ValueError:
        return code


def _lien_candidature(avis: Avis | None, reglages: Reglages | None) -> str:
    if avis is None or reglages is None or not reglages.url_publique:
        return ""
    return f"{reglages.url_publique}/apply/{avis.cle_publique}"


def _lien_aide(reglages: Reglages | None) -> str:
    if reglages is None or not reglages.url_publique:
        return ""
    return f"{reglages.url_publique}/aide"


def modalites(avis: Avis | None, reglages: Reglages | None) -> list[str]:
    """Comment candidater — les seuls canaux que le cabinet relève réellement."""
    lignes: list[str] = []
    lien = _lien_candidature(avis, reglages)
    if lien:
        lignes.append(f"Candidature en ligne : {lien}")
    boite = reglages.boite if reglages is not None else ""
    if boite:
        objet = f" en indiquant « [{avis.reference}] » dans l'objet" if avis and avis.reference else ""
        lignes.append(f"Ou par courriel à {boite}{objet}.")
    return lignes


def aide(reglages: Reglages | None) -> list[str]:
    """La section « En cas de difficulté » : qui écrire, et où trouver l'aide."""
    contact = reglages.contact if reglages is not None else ""
    lignes: list[str] = []
    if contact:
        lignes.append(
            f"Pour toute difficulté lors du dépôt de votre dossier, écrivez à {contact} "
            "en précisant l'intitulé du poste."
        )
    lien = _lien_aide(reglages)
    if lien:
        lignes.append(f"Les réponses aux questions fréquentes : {lien}")
    return lignes


def faits(
    poste: Poste,
    avis: Avis | None,
    mandat: Mandat | None,
    reglages: Reglages | None = None,
) -> str:
    """Les éléments opposables de l'avis, tels qu'ils doivent figurer.

    Rendus en texte pour servir à la fois de contexte au modèle et de squelette
    au brouillon écrit à la main.
    """
    lignes: list[str] = [f"Intitulé du poste : {poste.intitule}"]
    if mandat is not None and mandat.client is not None:
        lignes.append(f"Pour le compte de : {mandat.client.nom}")
    if poste.departement:
        lignes.append(f"Direction / département : {poste.departement}")
    if poste.rattachement:
        lignes.append(f"Rattachement hiérarchique : {poste.rattachement}")
    if poste.localisation:
        lignes.append(f"Lieu d'affectation : {poste.localisation}")
    lignes.append(f"Nombre de postes à pourvoir : {poste.nombre_a_pourvoir}")

    if poste.description:
        lignes.append(f"Mission du poste : {poste.description}")
    if poste.missions:
        lignes.append("Finalités du poste :")
        lignes += [f"  - {m}" for m in poste.missions]
    if poste.responsabilites:
        lignes.append("Principales responsabilités :")
        lignes += [f"  - {r}" for r in poste.responsabilites]

    lignes.append(f"Niveau de diplôme minimum exigé : BAC+{poste.niveau_min}")
    if poste.domaines_acceptes:
        lignes.append(f"Domaines de formation acceptés : {', '.join(poste.domaines_acceptes)}")
    if poste.formation_complementaire_souhaitee:
        lignes.append(
            "Formation complémentaire souhaitée : "
            f"{poste.formation_complementaire_souhaitee}"
        )
    if poste.annees_experience_min:
        lignes.append(
            f"Expérience professionnelle minimale : {poste.annees_experience_min} an(s)"
        )
    if poste.experiences_specifiques:
        for exigence in poste.experiences_specifiques:
            domaines = ", ".join(exigence.get("domaines") or ()) or "le domaine du poste"
            nom = exigence.get("libelle") or domaines
            if exigence.get("annees_min"):
                lignes.append(
                    f"Dont expérience spécifique : {exigence['annees_min']} an(s) en {nom}"
                )
    elif poste.annees_experience_specifique_min:
        domaines = ", ".join(poste.domaines_experience or ()) or "le domaine du poste"
        lignes.append(
            f"Dont expérience spécifique : {poste.annees_experience_specifique_min} "
            f"an(s) en {domaines}"
        )
    if poste.competences_techniques:
        lignes.append(f"Compétences techniques : {', '.join(poste.competences_techniques)}")
    if poste.competences_comportementales:
        lignes.append(
            f"Qualités attendues : {', '.join(poste.competences_comportementales)}"
        )
    if poste.langues_requises:
        lignes.append(f"Langues exigées : {', '.join(poste.langues_requises)}")

    requises = [_libelle_piece(c) for c in (poste.pieces_requises or ())]
    if requises:
        lignes.append("Pièces à fournir :")
        lignes += [f"  - {p}" for p in requises]
    for groupe in poste.groupes_pieces or ():
        codes = [_libelle_piece(c) for c in (groupe.get("codes") or ())]
        if not codes:
            continue
        if (groupe.get("mode") or "TOUTES") == "AU_MOINS_UNE":
            lignes.append(f"  - {' ou '.join(codes)}")
        else:
            lignes += [f"  - {c}" for c in codes]
    facultatives = [_libelle_piece(c) for c in (poste.pieces_facultatives or ())]
    if facultatives:
        lignes.append(f"Pièces facultatives : {', '.join(facultatives)}")
    if poste.pieces_libres_autorisees:
        lignes.append(
            "Le candidat peut joindre tout autre document utile à sa candidature."
        )
    for code, formats in (poste.formats_pieces or {}).items():
        if formats:
            lignes.append(
                f"Format imposé pour « {_libelle_piece(code)} » : "
                f"{', '.join(f.upper() for f in formats)}"
            )

    if avis is not None:
        if avis.reference:
            lignes.append(f"Référence de l'avis : {avis.reference}")
        lignes.append(f"Type d'avis : {avis.type_avis.value}")
        if avis.date_publication:
            lignes.append(f"Date de l'avis : {avis.date_publication.strftime('%d/%m/%Y')}")
        if avis.date_cloture:
            lignes.append(
                f"Date limite de dépôt des candidatures : "
                f"{avis.date_cloture.strftime('%d/%m/%Y')}"
            )

    depot = modalites(avis, reglages)
    if depot:
        lignes.append("Modalités de dépôt :")
        lignes += [f"  - {d}" for d in depot]
    difficulte = aide(reglages)
    if difficulte:
        lignes.append(f"{TITRE_AIDE} :")
        lignes += [f"  - {d}" for d in difficulte]
    return "\n".join(lignes)


def brouillon_manuel(
    poste: Poste,
    avis: Avis | None,
    mandat: Mandat | None,
    reglages: Reglages | None = None,
) -> str:
    """Le squelette, sans assistance : les faits, sous leurs intertitres.

    Ce qu'on présente quand aucun fournisseur n'est configuré, ou quand
    l'assistance est refusée. Il n'y manque que la prose.
    """
    client = mandat.client.nom if mandat is not None and mandat.client else ""
    entete = "AVIS DE RECRUTEMENT"
    if avis is not None and avis.reference:
        entete += f"\nRéf. : {avis.reference}"
    entete += f"\n\n{poste.intitule.upper()}"
    if client:
        entete += f"\nPour le compte de {client}"
    return f"{entete}\n\n{faits(poste, avis, mandat, reglages)}"


def _consigne(avec_fiche: bool, avec_gabarit: bool, avec_aide: bool) -> str:
    consigne = (
        "Rédigez un avis de recrutement complet et publiable à partir des "
        "éléments ci-dessous. Structurez-le avec des intertitres : contexte, "
        "mission et responsabilités, profil recherché, dossier de candidature, "
        "modalités de dépôt"
    )
    consigne += f", « {TITRE_AIDE} »." if avec_aide else "."
    consigne += (
        " Reprenez sans les modifier les exigences, les intitulés de pièces, les "
        "dates, les adresses et les liens."
    )
    if avec_fiche:
        consigne += (
            "\n\nLa fiche de poste remise par le commanditaire figure sous "
            "« FICHE DE POSTE FOURNIE ». Appuyez-vous sur elle pour décrire le "
            "poste — contexte, mission, responsabilités, lieu, rattachement — en "
            "restant fidèle à ce qu'elle dit. Pour les exigences (diplôme, "
            "expérience, pièces, conditions), seuls les « ÉLÉMENTS OPPOSABLES » "
            "font foi : si la fiche en dit davantage ou autre chose, ne le "
            "reprenez pas."
        )
    if avec_gabarit:
        consigne += (
            "\n\nUn modèle imposé par le commanditaire figure à la fin des "
            "données, sous « MODÈLE IMPOSÉ ». Reprenez sa structure et ses "
            "intertitres. Si le modèle contient des exigences qui ne figurent "
            "pas dans les éléments opposables, ignorez-les."
        )
    if avec_aide:
        consigne += (
            f"\n\nTerminez par la section « {TITRE_AIDE} », qui reprend mot pour "
            "mot l'adresse de contact et le lien d'aide donnés."
        )
    return consigne


async def rediger(
    poste: Poste,
    avis: Avis | None,
    mandat: Mandat | None,
    gabarit: str = "",
    reglages: Reglages | None = None,
) -> str:
    """Propose le texte de l'avis. Chaîne vide si l'assistance est indisponible.

    `gabarit` est le texte du modèle imposé par le client, quand il y en a un.
    On le donne à lire pour la présentation, jamais pour le contenu : les
    exigences viennent des champs de la fiche, et d'eux seuls.
    """
    fiche = (poste.fiche_texte or "").strip()
    avec_aide = bool(aide(reglages))

    contexte = "ÉLÉMENTS OPPOSABLES :\n---\n" + faits(poste, avis, mandat, reglages) + "\n---"
    if fiche:
        contexte += "\n\nFICHE DE POSTE FOURNIE :\n---\n" + fiche[:LONGUEUR_FICHE_MAX] + "\n---"
    if gabarit.strip():
        contexte += "\n\nMODÈLE IMPOSÉ :\n---\n" + gabarit.strip()[:8000] + "\n---"

    try:
        texte = await get_provider().rediger(
            _consigne(bool(fiche), bool(gabarit.strip()), avec_aide),
            contexte,
            systeme=prompts.avis_system_prompt(),
        )
    except Exception:
        # Sans assistance, l'utilisateur récupère le squelette et écrit
        # lui-même. Une panne de fournisseur ne bloque pas une publication.
        logger.exception("rédaction d'avis indisponible pour le poste %s", poste.id)
        return ""
    return completer_aide(texte, reglages)


def completer_aide(texte: str, reglages: Reglages | None) -> str:
    """Garantit que la section d'aide figure, avec la bonne adresse.

    Le modèle est invité à l'écrire, mais une consigne n'est pas une garantie :
    s'il l'a omise, ou s'il a écrit l'aide sans l'adresse, on l'ajoute. Un
    candidat bloqué qui ne trouve personne à qui écrire abandonne.
    """
    if not texte.strip():
        return texte
    contact = reglages.contact if reglages is not None else ""
    lignes = aide(reglages)
    if not lignes or (contact and contact in texte):
        return texte
    return texte.rstrip() + f"\n\n{TITRE_AIDE.upper()}\n" + "\n".join(lignes) + "\n"
