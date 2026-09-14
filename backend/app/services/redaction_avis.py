"""Rédaction de l'avis de recrutement à partir de la fiche de poste.

Deux voies, et le choix appartient à l'utilisateur :

- **texte libre** : l'assistance propose un avis à partir de la fiche, dans la
  présentation habituelle du cabinet ;
- **modèle imposé** : un client fournit sa trame, et l'avis s'y coule.

Aucune des deux n'est obligatoire — un avis peut toujours être écrit
entièrement à la main dans l'éditeur. C'est une aide à la rédaction, pas un
passage obligé.

Le squelette de l'avis est construit ici, en Python, à partir des champs de la
fiche : intitulé, niveau exigé, expérience, pièces à fournir, date de clôture.
Ces éléments sont opposables une fois publiés — une condition inventée devient
une condition réelle — donc ils ne sont jamais laissés à la rédaction
automatique. Celle-ci n'intervient que sur la prose qui les entoure.
"""

from __future__ import annotations

import logging

from app.domain.referentiel import PieceDossier
from app.llm import prompts
from app.llm.factory import get_provider
from app.models import Avis, Mandat, Poste

logger = logging.getLogger(__name__)


def _libelle_piece(code: str) -> str:
    try:
        return PieceDossier(code).libelle
    except ValueError:
        return code


def faits(poste: Poste, avis: Avis | None, mandat: Mandat | None) -> str:
    """Les éléments opposables de l'avis, tels qu'ils doivent figurer.

    Rendus en texte pour servir à la fois de contexte au modèle et de squelette
    au brouillon écrit à la main.
    """
    lignes: list[str] = [f"Intitulé du poste : {poste.intitule}"]
    if mandat is not None and mandat.client is not None:
        lignes.append(f"Pour le compte de : {mandat.client.nom}")
    if poste.departement:
        lignes.append(f"Département : {poste.departement}")
    lignes.append(f"Nombre de postes à pourvoir : {poste.nombre_a_pourvoir}")

    if poste.description:
        lignes.append(f"Description : {poste.description}")
    if poste.missions:
        lignes.append("Missions :")
        lignes += [f"  - {m}" for m in poste.missions]

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
    if poste.annees_experience_specifique_min:
        domaines = ", ".join(poste.domaines_experience or ()) or "le domaine du poste"
        lignes.append(
            f"Dont expérience spécifique : {poste.annees_experience_specifique_min} "
            f"an(s) en {domaines}"
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
        if avis.date_cloture:
            lignes.append(
                f"Date limite de dépôt des candidatures : "
                f"{avis.date_cloture.strftime('%d/%m/%Y')}"
            )
    return "\n".join(lignes)


def brouillon_manuel(poste: Poste, avis: Avis | None, mandat: Mandat | None) -> str:
    """Le squelette, sans assistance : les faits, sous leurs intertitres.

    Ce qu'on présente quand aucun fournisseur n'est configuré, ou quand
    l'assistance est refusée. Il n'y manque que la prose.
    """
    client = mandat.client.nom if mandat is not None and mandat.client else ""
    entete = f"AVIS DE RECRUTEMENT\n\n{poste.intitule.upper()}"
    if client:
        entete += f"\nPour le compte de {client}"
    return f"{entete}\n\n{faits(poste, avis, mandat)}"


async def rediger(
    poste: Poste,
    avis: Avis | None,
    mandat: Mandat | None,
    gabarit: str = "",
) -> str:
    """Propose le texte de l'avis. Chaîne vide si l'assistance est indisponible.

    `gabarit` est le texte du modèle imposé par le client, quand il y en a un.
    On le donne à lire pour la présentation, jamais pour le contenu : les
    exigences viennent de la fiche, et d'elle seule.
    """
    consigne = (
        "Rédigez un avis de recrutement complet et publiable à partir des "
        "éléments ci-dessous. Structurez-le avec des intertitres : contexte, "
        "missions, profil recherché, dossier de candidature, modalités de "
        "dépôt. Reprenez sans les modifier les exigences, les intitulés de "
        "pièces et les dates."
    )
    if gabarit.strip():
        consigne += (
            "\n\nUn modèle imposé par le commanditaire figure à la fin des "
            "données, sous « MODÈLE IMPOSÉ ». Reprenez sa structure et ses "
            "intertitres. Si le modèle contient des exigences qui ne figurent "
            "pas dans la fiche de poste, ignorez-les : la fiche fait foi."
        )

    contexte = faits(poste, avis, mandat)
    if gabarit.strip():
        contexte += "\n\nMODÈLE IMPOSÉ :\n---\n" + gabarit.strip()[:8000] + "\n---"

    try:
        return await get_provider().rediger(
            consigne, contexte, systeme=prompts.avis_system_prompt()
        )
    except Exception:
        # Sans assistance, l'utilisateur récupère le squelette et écrit
        # lui-même. Une panne de fournisseur ne bloque pas une publication.
        logger.exception("rédaction d'avis indisponible pour le poste %s", poste.id)
        return ""
