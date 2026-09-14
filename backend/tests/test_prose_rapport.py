"""Ce que le rapport reçoit du modèle, et ce qu'il en imprime.

Un rapport partait au client avec des accolades vides en guise de sections.
La cause n'était pas dans le modèle : les fournisseurs armaient leur mode JSON
sur *toutes* les requêtes, y compris celles qui demandaient un paragraphe de
français. Contraint au JSON sans schéma à remplir, un modèle rend `{}`.

Deux séries de tests : le mode n'est plus armé sur la prose (`test_mode_json`),
et ce qu'un modèle emballe malgré tout est déballé (`test_nettoyage`).
"""

from __future__ import annotations

import pytest

from app.llm import prose
from app.llm.base import Attachment, BaseLLMProvider

pytestmark = pytest.mark.anyio


# --- le déballage -----------------------------------------------------------


@pytest.mark.parametrize(
    "brut",
    ["{}", "  {}  ", "[]", "null", '""', "```json\n{}\n```"],
)
def test_une_coquille_vide_ne_devient_pas_une_section(brut):
    """`{}` imprimé dans un rapport remis se lit comme une erreur de logiciel.

    Vide, l'écran présente la section à écrire — ce qui est la vérité.
    """
    assert prose.nettoyer(brut) == ""


def test_la_prose_emballee_dans_un_objet_est_deballee():
    brut = '{"texte": "Le cabinet a été mandaté le 3 mars 2026."}'
    assert prose.nettoyer(brut) == "Le cabinet a été mandaté le 3 mars 2026."


def test_les_retours_a_la_ligne_echappes_redeviennent_des_retours():
    brut = '{"contenu": "Premier paragraphe.\\n\\nSecond paragraphe."}'
    assert prose.nettoyer(brut) == "Premier paragraphe.\n\nSecond paragraphe."


def test_on_ne_parie_pas_sur_le_nom_de_la_cle():
    """Chaque modèle a le sien — `texte`, `section`, `response`, `output`."""
    for cle in ("section", "response", "output", "resultat"):
        assert prose.nettoyer(f'{{"{cle}": "Douze dossiers ont été reçus."}}') == (
            "Douze dossiers ont été reçus."
        )


def test_un_objet_imbrique_se_recolle_dans_l_ordre():
    brut = '{"sections": [{"titre": "Contexte"}, {"corps": "Le mandat porte sur un poste."}]}'
    assert prose.nettoyer(brut) == "Contexte\n\nLe mandat porte sur un poste."


def test_les_nombres_ne_sont_pas_de_la_prose():
    """Un objet qui ne portait que du remplissage ressort vide, pas « 0 »."""
    assert prose.nettoyer('{"score": 0, "ok": true}') == ""


def test_une_phrase_qui_cite_une_accolade_n_est_pas_decoupee():
    """Le déballage ne s'ouvre que sur un texte délimité de bout en bout."""
    texte = "Le gabarit impose un champ {nom} dans l'en-tête."
    assert prose.nettoyer(texte) == texte


# --- le raisonnement à voix haute -------------------------------------------
#
# Les modèles récents — Qwen, DeepSeek, la plupart de ce qui tourne sous Ollama
# — rendent leur réflexion avant leur réponse. En mode JSON le format l'interdit ;
# la prose n'a pas ce garde-fou.


def test_la_reflexion_du_modele_ne_part_pas_dans_le_rapport():
    brut = (
        "<think>L'utilisateur veut une section sur la publication. Les données "
        "donnent 5 candidatures.</think>\n"
        "Le cabinet a réceptionné cinq candidatures."
    )
    assert prose.nettoyer(brut) == "Le cabinet a réceptionné cinq candidatures."


def test_une_reflexion_tronquee_ne_laisse_pas_sa_queue():
    """Coupée par la limite de jetons, elle n'a pas de balise fermante."""
    brut = "Le cabinet a réceptionné cinq candidatures.\n<think>Il faudrait aussi"
    assert prose.nettoyer(brut) == "Le cabinet a réceptionné cinq candidatures."


def test_une_reflexion_qui_contient_des_accolades_ne_fait_pas_prendre_la_prose_pour_du_json():
    """Elle est retirée avant le test « cela ressemble-t-il à du JSON ? »."""
    brut = '<think>Le schéma attendu est {"texte": ...}</think>\nCinq candidatures.'
    assert prose.nettoyer(brut) == "Cinq candidatures."


def test_une_reponse_qui_n_est_que_reflexion_ressort_vide():
    assert prose.nettoyer("<think>Je réfléchis encore.</think>") == ""


def test_le_mot_think_dans_une_phrase_ne_declenche_rien():
    texte = "Le rapport ne contient aucune balise think ni reasoning."
    assert prose.nettoyer(texte) == texte


# --- le balisage ------------------------------------------------------------


def test_le_markdown_ne_part_pas_dans_le_docx():
    """`**` et `##` s'impriment tels quels dans un Word remis au client."""
    brut = "## Méthodologie\n\nLa démarche **suivie** comprend `quatre` étapes."
    assert prose.nettoyer(brut) == "Méthodologie\n\nLa démarche suivie comprend quatre étapes."


def test_les_puces_se_normalisent_sur_le_tiret():
    brut = "* publication de l'avis\n* réception des dossiers"
    assert prose.nettoyer(brut) == "- publication de l'avis\n- réception des dossiers"


def test_le_titre_recopie_en_tete_disparait():
    """Le document imprime son propre titre : le voir deux fois est une faute."""
    brut = "Contexte et objet de la mission\n\nLe cabinet a été mandaté en mars."
    nettoye = prose.nettoyer(brut, titre="Contexte et objet de la mission")
    assert nettoye == "Le cabinet a été mandaté en mars."


def test_le_titre_se_reconnait_sans_les_accents_ni_le_balisage():
    brut = "## **CONTROLE D'ELIGIBILITE**\nQuatre dossiers ont été écartés."
    assert prose.nettoyer(brut, titre="Contrôle d'éligibilité") == (
        "Quatre dossiers ont été écartés."
    )


def test_une_phrase_qui_commence_comme_le_titre_est_conservee():
    """Seule une ligne *égale* au titre part. Une phrase qui l'ouvre reste."""
    brut = "Contexte et objet de la mission du cabinet, rappelés ci-après."
    assert prose.nettoyer(brut, titre="Contexte et objet de la mission") == brut


def test_le_preambule_de_politesse_est_retire():
    brut = "Voici la section demandée :\n\nLe mandat a été attribué en mars 2026."
    assert prose.nettoyer(brut) == "Le mandat a été attribué en mars 2026."


def test_le_texte_deja_propre_traverse_intact():
    texte = (
        "Le cabinet a publié l'avis le 3 mars 2026.\n\n"
        "Douze dossiers ont été reçus avant la clôture."
    )
    assert prose.nettoyer(texte) == texte


# --- le mode chez le fournisseur --------------------------------------------


class Espion(BaseLLMProvider):
    """Un fournisseur qui note ce qu'on lui demande et rend ce qu'on lui dit."""

    name = "espion"

    def __init__(self, reponse: str = "Texte rendu par le modèle.") -> None:
        self.reponse = reponse
        self.modes: list[bool] = []

    async def complete(
        self,
        system: str,
        user: str,
        attachment: Attachment | None = None,
        *,
        json_mode: bool = True,
    ) -> str:
        self.modes.append(json_mode)
        return self.reponse

    async def analyze_cv(self, cv, fiche):  # pragma: no cover - hors sujet ici
        raise NotImplementedError


async def test_une_demande_de_prose_n_arme_pas_le_mode_json():
    """La correction de fond. Le reste n'est que rattrapage."""
    espion = Espion()
    await espion.rediger("Rédigez la section.", "Poste : Chef comptable")
    assert espion.modes == [False]


async def test_une_demande_de_json_arme_toujours_le_mode():
    espion = Espion(reponse='{"sections": []}')
    await espion.repondre_json("Rapprochez les intertitres.", "…")
    assert espion.modes == [True]


async def test_l_extraction_arme_toujours_le_mode():
    espion = Espion(reponse='{"diplomes": [], "experiences": []}')
    await espion.extraire_dossier("Dossier expurgé")
    assert espion.modes == [True]


async def test_ce_que_rediger_rend_est_deja_nettoye():
    """L'appelant n'a rien à faire : il reçoit de la prose ou rien."""
    espion = Espion(reponse='{"texte": "Douze dossiers ont été reçus."}')
    assert await espion.rediger("Rédigez.", "…") == "Douze dossiers ont été reçus."

    coquille = Espion(reponse="{}")
    assert await coquille.rediger("Rédigez.", "…") == ""
