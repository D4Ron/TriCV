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
from dataclasses import dataclass

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
        # Un lien seul, posé en fin d'avis, se lit comme une référence et non
        # comme la marche à suivre : l'avis dit donc quoi en faire, jusqu'à
        # l'envoi du formulaire, avec les libellés exacts de la page.
        lignes.append(
            "Pour déposer votre dossier, cliquez sur le lien suivant (ou "
            "copiez-le dans la barre d'adresse de votre navigateur), remplissez "
            "le formulaire, joignez les pièces demandées, puis cliquez sur "
            f"« Envoyer ma candidature » : {lien}"
        )
        lignes.append(
            "Votre dossier n'est enregistré qu'une fois ce formulaire envoyé : "
            "attendez l'écran « Candidature enregistrée » avant de fermer la page."
        )
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


# --- l'avis, section par section --------------------------------------------
#
# Un seul appel demandant « l'avis complet » ne donne pas un avis complet. La
# consigne avait beau détailler cinq sections et leur développement, le modèle
# rendait quatre cents mots dont les responsabilités recopiées en puces — les
# intitulés de la fiche, sans une ligne sur ce qu'ils recouvrent. Une consigne
# longue laisse le choix de ce qu'on honore ; une consigne par appel ne le
# laisse pas.
#
# C'est déjà ainsi que se produisent les rapports du cabinet, et pour la même
# raison. L'avis suit.
#
# Deuxième principe, au moins aussi utile : le modèle n'écrit que ce qui se
# **décrit**. Les pièces à fournir, la date limite, la référence, le lien de
# candidature et l'adresse de contact sont écrits par le code, mot pour mot.
# Ce sont eux qu'un avis publié engage, et les faire recopier par un modèle
# était un risque pris sans rien gagner : un lien mal retranscrit est une
# candidature perdue.


@dataclass(frozen=True)
class SectionAvis:
    """Une section de l'avis, et ce qu'on demande au modèle pour elle."""

    titre: str
    consigne: str


def _sections_redigees(comptes: dict[str, int], avec_fiche: bool) -> list[SectionAvis]:
    # La fiche décrit, les éléments opposables exigent. Quand les deux se
    # contredisent — une fiche qui demande un BAC+5 là où le poste enregistré
    # exige un BAC+4 —, c'est le poste qui fait foi : c'est lui que la
    # présélection applique, et un avis qui annonce autre chose écarterait des
    # candidats sur une condition que personne n'a posée.
    appui = (
        " Servez-vous de la fiche de poste fournie : elle en dit plus long que "
        "le résumé des éléments opposables, et c'est là qu'est la matière. "
        "Mais pour les exigences — diplôme, années, pièces, conditions —, "
        "seuls les « ÉLÉMENTS OPPOSABLES » font foi : si la fiche en dit "
        "davantage ou autre chose, ne le reprenez pas."
        if avec_fiche
        else ""
    )

    def compte(cle: str) -> str:
        n = comptes.get(cle, 0)
        return "" if n == 0 else f" Les données en donnent {n} : traitez-les toutes, et seulement elles."

    return [
        SectionAvis(
            "Contexte",
            "Rédigez la section « Contexte » de l'avis : qui recrute, pour le "
            "compte de quelle organisation, quel poste est à pourvoir, où il "
            "est basé, à qui son titulaire rendra compte, et combien de postes "
            "sont ouverts. Deux paragraphes rédigés, sans liste." + appui,
        ),
        SectionAvis(
            "Mission et responsabilités",
            "Rédigez la section « Mission et responsabilités » de l'avis. "
            "C'est la section que lit un candidat pour savoir s'il se "
            "reconnaît dans le poste : c'est la plus longue de l'avis.\n"
            "Commencez par un paragraphe sur la raison d'être du poste — ce "
            "que son titulaire aura à obtenir, pas seulement à faire.\n"
            "Puis reprenez chaque responsabilité **une par une**, chacune dans "
            "son propre paragraphe de deux à quatre phrases : ce qu'elle "
            "recouvre concrètement, sur quel périmètre elle s'exerce, avec "
            "quels interlocuteurs, et ce qui sera attendu du titulaire à ce "
            "titre. Ne vous contentez jamais de recopier l'intitulé : il est "
            "écrit en style de note interne, et votre texte est publié."
            + compte("responsabilites")
            + appui,
        ),
        SectionAvis(
            "Profil recherché",
            "Rédigez la section « Profil recherché » de l'avis.\n"
            "Commencez par les exigences, recopiées telles quelles et sans "
            "commentaire : niveau de diplôme, domaines de formation acceptés, "
            "années d'expérience générale et spécifique. Ce sont des "
            "conditions opposables — ne les reformulez pas, ne les "
            "interprétez pas, n'en ajoutez aucune.\n"
            "Développez ensuite les compétences techniques attendues, puis les "
            "qualités personnelles, en phrases pleines : ce que chacune "
            "recouvre dans l'exercice de ce poste précis."
            + compte("techniques")
            + compte("qualites")
            + appui,
        ),
    ]


def _section_factuelle(titre: str, lignes: list[str], introduction: str = "") -> str:
    """Une section écrite par le code : rien n'y passe par le modèle."""
    if not lignes:
        return ""
    corps = "\n".join(f"- {l}" for l in lignes)
    tete = f"{introduction}\n" if introduction else ""
    return f"{titre}\n{tete}{corps}"


def _pieces_du_dossier(poste: Poste) -> list[str]:
    """Les pièces exigées, y compris les alternatives, à l'intitulé près."""
    lignes = [_libelle_piece(c) for c in (poste.pieces_requises or ())]
    for groupe in poste.groupes_pieces or ():
        codes = [_libelle_piece(c) for c in (groupe.get("codes") or ())]
        if not codes:
            continue
        if (groupe.get("mode") or "TOUTES") == "AU_MOINS_UNE":
            lignes.append(" ou ".join(codes))
        else:
            lignes += codes
    return lignes


def _denombrer(poste: Poste) -> dict[str, int]:
    """Combien d'éléments la fiche donne, liste par liste."""
    return {
        "responsabilites": len(poste.responsabilites or ()),
        "techniques": len(poste.competences_techniques or ()),
        "qualites": len(poste.competences_comportementales or ()),
        "missions": len(poste.missions or ()),
    }


def _consigne(
    avec_fiche: bool,
    avec_gabarit: bool,
    avec_aide: bool,
    comptes: dict[str, int] | None = None,
) -> str:
    # Sans longueur annoncée, le modèle rendait une section par intertitre et
    # recopiait chaque responsabilité en une puce, mot pour mot. L'avis faisait
    # alors la longueur de la fiche de poste — une note interne en style
    # télégraphique — là où le cabinet publie un texte rédigé que des candidats
    # lisent pour décider s'ils postulent.
    #
    # Le repère n'est volontairement pas un nombre de mots : un quota se tient
    # en inventant, et un avis publié est opposable. Ce qui se tient
    # honnêtement, c'est un nombre d'**éléments** — celui que la fiche donne,
    # annoncé ici pour que le modèle le vérifie lui-même — assorti d'une
    # consigne de rédaction sur chacun. La longueur suit alors la matière au
    # lieu de la précéder : une fiche pauvre donne un avis court, et c'est
    # exact.
    comptes = comptes or {}
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
    def _exactement(cle: str) -> str:
        n = comptes.get(cle, 0)
        if n == 0:
            return ""
        return (
            f" La fiche en donne {n} : votre section en compte "
            f"{'exactement un' if n == 1 else f'exactement {n}'}, "
            f"{'ni plus ni moins' if n > 1 else 'et lui seul'}."
        )

    consigne += (
        "\n\nDéveloppement attendu, section par section. Développer veut dire "
        "**rédiger en phrases ce qui vous est donné en notes**, jamais ajouter "
        "à la liste :\n"
        "- Contexte : deux paragraphes. Qui recrute, pour le compte de qui, "
        "quel poste et où il est basé, à qui son titulaire rend compte.\n"
        "- Mission et responsabilités : la section la plus développée, et "
        "rédigée en paragraphes. Une phrase d'ouverture sur la raison d'être "
        "du poste, puis chaque responsabilité fournie reprise en une à trois "
        "phrases pleines — ce qu'elle recouvre concrètement, sur quoi et avec "
        "qui elle s'exerce, et ce qui sera attendu du titulaire à ce titre. "
        "Ne recopiez pas l'intitulé tel quel : il est écrit en style de note "
        "interne, et votre texte est publié. Quand une fiche est fournie, "
        "c'est là qu'elle sert le plus : allez y chercher le détail des "
        "tâches et des objectifs rattachés à chaque responsabilité."
        + _exactement("responsabilites")
        + "\n"
        "- Profil recherché : le diplôme, les domaines et les durées d'abord, "
        "recopiés tels quels et sans commentaire — ce sont des exigences. Puis "
        "les compétences techniques, chacune rédigée en une à deux phrases "
        "pleines plutôt qu'en puce recopiée."
        + _exactement("techniques")
        + " Puis les qualités attendues, de même."
        + _exactement("qualites")
        + "\n"
        "- Dossier de candidature : un paragraphe qui annonce la liste, puis "
        "la liste des pièces, à l'intitulé près.\n"
        "- Modalités de dépôt : la date limite, la référence à rappeler, et "
        "par où le dossier se dépose — sans rien inventer de ce qui suivra.\n"
        "\nNe fixez pas la longueur d'avance : elle suit ce que la fiche "
        "fournit. Une fiche qui donne trois responsabilités produit un avis "
        "plus court qu'une fiche qui en donne dix, et c'est ainsi que cela "
        "doit être. Allonger une liste pour étoffer l'avis décrit un autre "
        "poste que celui qu'on recrute."
    )
    if avec_fiche:
        # La fiche contient presque toujours plus que ce que l'extraction en a
        # tiré : des paragraphes de mission, le contexte de l'entité, le détail
        # des tâches sous chaque responsabilité, les conditions d'exercice. Ces
        # éléments-là n'ont pas de champ dans le formulaire, donc ils
        # n'arrivaient au modèle que comme décor — et l'avis publié en disait
        # moins sur le poste que le document dont il était tiré.
        consigne += (
            "\n\nLa fiche de poste remise par le commanditaire figure sous "
            "« FICHE DE POSTE FOURNIE ». C'est votre source principale pour "
            "**décrire** le poste, et elle contient davantage que le résumé "
            "des éléments opposables : lisez-la en entier et servez-vous-en.\n"
            "- Ce que le titulaire aura à faire, tâche par tâche : c'est le "
            "coeur de l'avis, et c'est ce qu'un candidat cherche pour savoir "
            "s'il se reconnaît dans le poste. Reprenez le détail que la fiche "
            "donne sous chaque grande responsabilité.\n"
            "- Ce sur quoi il sera attendu : objectifs, finalités, résultats "
            "que la fiche associe au poste, périmètre, moyens, équipe "
            "encadrée, interlocuteurs.\n"
            "- Le contexte de l'entité et de la direction, les conditions "
            "d'exercice, les normes et référentiels que la fiche nomme "
            "expressément.\n"
            "Restez fidèle à ce qu'elle dit : reformulez pour publier, "
            "n'extrapolez pas. Une norme, un logiciel, un chiffre ou un "
            "objectif qui ne figure pas dans la fiche ne figure pas dans "
            "l'avis.\n"
            "Pour les exigences en revanche (diplôme, expérience, pièces, "
            "conditions), seuls les « ÉLÉMENTS OPPOSABLES » font foi : si la "
            "fiche en dit davantage ou autre chose, ne le reprenez pas."
        )
    if avec_gabarit:
        consigne += (
            "\n\nUn modèle imposé par le commanditaire figure à la fin des "
            "données, sous « MODÈLE IMPOSÉ ». Reprenez sa structure et ses "
            "intertitres. Si le modèle contient des exigences qui ne figurent "
            "pas dans les éléments opposables, ignorez-les."
        )
    consigne += (
        "\n\nDans les modalités de dépôt, reprenez mot pour mot la consigne qui "
        "accompagne le lien de candidature : le candidat doit comprendre qu'il "
        "dépose son dossier en cliquant sur ce lien, en remplissant le "
        "formulaire et en validant l'envoi."
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

    Les sections descriptives — contexte, mission et responsabilités, profil —
    sont demandées **une par une** : un seul appel réclamant « l'avis complet »
    rendait quatre cents mots dont les responsabilités recopiées en puces.

    Les sections opposables — pièces, date limite, référence, liens, contact —
    sont écrites ici, en Python, et ne passent jamais par le modèle. Un lien
    mal retranscrit est une candidature perdue, et rien ne justifie de courir
    ce risque pour du texte que le code sait produire exactement.

    `gabarit` est le texte du modèle imposé par le client, quand il y en a un.
    Il impose alors la présentation d'ensemble, et l'avis se rédige en un seul
    appel — découper contre une trame imposée reviendrait à la défaire.
    """
    fiche = (poste.fiche_texte or "").strip()
    contexte = "ÉLÉMENTS OPPOSABLES :\n---\n" + faits(poste, avis, mandat, reglages) + "\n---"
    if fiche:
        contexte += "\n\nFICHE DE POSTE FOURNIE :\n---\n" + fiche[:LONGUEUR_FICHE_MAX] + "\n---"

    if gabarit.strip():
        return await _rediger_sur_gabarit(poste, contexte, gabarit, reglages)

    fournisseur = get_provider()
    systeme = prompts.avis_system_prompt()
    morceaux: list[str] = [_entete(poste, avis, mandat)]

    for section in _sections_redigees(_denombrer(poste), bool(fiche)):
        try:
            contenu = await fournisseur.rediger(
                section.consigne,
                contexte,
                systeme=systeme,
                titre=section.titre,
                cloture=prompts.CLOTURE_AVIS_SECTION,
            )
        except Exception:
            # Une section perdue fait tout abandonner, y compris les sections
            # déjà écrites. C'est voulu : un avis auquel il manque le profil
            # recherché ressemble à un avis fini, et se publierait comme tel.
            # L'appelant sert alors le squelette complet des faits, que son
            # allure inachevée désigne d'elle-même comme un brouillon.
            logger.exception(
                "rédaction de « %s » indisponible pour le poste %s",
                section.titre,
                poste.id,
            )
            return ""
        contenu = _borner(contenu, section.titre)
        if contenu:
            morceaux.append(f"{section.titre}\n{contenu}")

    if len(morceaux) == 1:
        # Que l'en-tête : aucune section n'a rien rendu. Mieux vaut le
        # squelette complet qu'un titre seul.
        return ""

    morceaux += _sections_factuelles(poste, avis, reglages)
    return "\n\n".join(m for m in morceaux if m.strip())


# Les rubriques que le code écrit lui-même. Quand le modèle les entame malgré
# la consigne, sa section s'arrête là : ce qui suit ferait doublon avec le
# texte exact produit plus bas, et c'est le texte exact qui doit rester.
_RUBRIQUES_RESERVEES = (
    "dossier de candidature",
    "pièces à fournir",
    "pieces à fournir",
    "modalités de dépôt",
    "modalites de depot",
    TITRE_AIDE.lower(),
)


def _borner(contenu: str, titre: str) -> str:
    """Coupe une section au premier titre qui ne lui appartient pas."""
    lignes = contenu.strip().splitlines()
    gardees: list[str] = []
    for ligne in lignes:
        nue = ligne.strip().strip("#*_ ").rstrip(":").lower()
        if nue in _RUBRIQUES_RESERVEES:
            break
        # Le titre de la section est ajouté par le code ; s'il le réécrit en
        # tête, on ne le garde pas deux fois.
        if not gardees and nue == titre.lower():
            continue
        gardees.append(ligne)
    return "\n".join(gardees).strip()


def _entete(poste: Poste, avis: Avis | None, mandat: Mandat | None) -> str:
    """Le bandeau de tête : intitulé, référence, commanditaire."""
    lignes = ["AVIS DE RECRUTEMENT"]
    if avis is not None and avis.reference:
        lignes[0] += f" — Réf. {avis.reference}"
    lignes.append(poste.intitule.upper())
    if mandat is not None and mandat.client is not None:
        lignes.append(f"Pour le compte de {mandat.client.nom}")
    return "\n".join(lignes)


def _sections_factuelles(
    poste: Poste, avis: Avis | None, reglages: Reglages | None
) -> list[str]:
    """Ce que le code écrit lui-même, mot pour mot."""
    sections: list[str] = []

    pieces = _pieces_du_dossier(poste)
    if pieces:
        sections.append(
            _section_factuelle(
                "Dossier de candidature",
                pieces,
                "Le dossier de candidature doit comprendre les pièces suivantes :",
            )
        )
        facultatives = [_libelle_piece(c) for c in (poste.pieces_facultatives or ())]
        extras: list[str] = []
        if facultatives:
            extras.append(
                "Pièces facultatives, dont l'absence ne pénalise pas le "
                f"dossier : {', '.join(facultatives)}."
            )
        if poste.pieces_libres_autorisees:
            extras.append(
                "Tout autre document que le candidat juge utile peut être joint."
            )
        if extras:
            sections[-1] += "\n" + "\n".join(extras)

    depot: list[str] = []
    if avis is not None and avis.date_cloture:
        depot.append(
            "Date limite de dépôt des candidatures : "
            f"{avis.date_cloture.strftime('%d/%m/%Y')}."
        )
    depot += modalites(avis, reglages)
    if depot:
        sections.append(_section_factuelle("Modalités de dépôt", depot))

    difficulte = aide(reglages)
    if difficulte:
        sections.append(_section_factuelle(TITRE_AIDE, difficulte))
    return sections


async def _rediger_sur_gabarit(
    poste: Poste, contexte: str, gabarit: str, reglages: Reglages | None
) -> str:
    """Un modèle imposé par le client : sa trame commande, donc un seul appel."""
    contexte += "\n\nMODÈLE IMPOSÉ :\n---\n" + gabarit.strip()[:8000] + "\n---"
    consigne = _consigne(
        bool((poste.fiche_texte or "").strip()),
        True,
        bool(aide(reglages)),
        _denombrer(poste),
    )
    try:
        texte = await get_provider().rediger(
            consigne,
            contexte,
            systeme=prompts.avis_system_prompt(),
            titre="l'avis de recrutement",
            cloture=prompts.CLOTURE_AVIS,
        )
    except Exception:
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
