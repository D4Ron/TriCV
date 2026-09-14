"""Le domaine renommé, et le domaine élargi.

Donner au modèle le vocabulaire du poste règle un vrai problème : « gestion du
personnel » et « ressources humaines » sont le même métier, et la grille ne le
devinait pas — un même parcours passait ou tombait selon le mot choisi.

Mais cela le pousse aussi à ranger sous l'intitulé attendu ce qui n'en est que
voisin. Éprouvé sur dix CV réels, le défaut s'est montré : une « Licence en
mathématiques appliquées » est ressortie en « informatique », domaine du poste.
Un élargissement de ce genre vaut au candidat les points d'un domaine qu'il n'a
pas étudié — et une qualification inventée voyage plus loin qu'une élimination
injuste.

Le rapprochement n'est pas annulé : le modèle a parfois raison, et le refuser
d'office rendrait la grille aveugle aux synonymes. Il devient **visible**.
"""

from __future__ import annotations

import pytest

from app.llm import prompts
from app.llm.base import DiplomeExtrait, DossierExtrait
from app.models import Provenance
from app.services import depouillement


class FauxCandidat:
    id = "c1"


def appliquer(diplomes: list[DiplomeExtrait]):
    resultat = depouillement.ResultatDepouillement()
    lignes = depouillement._appliquer_parcours(
        FauxCandidat(), DossierExtrait(diplomes=diplomes), resultat
    )
    return lignes, resultat


# --- la consigne -------------------------------------------------------------


def test_la_consigne_dit_de_renommer_et_non_d_elargir():
    consigne = prompts.extraction_system_prompt(["ressources humaines", "informatique"])

    assert "renommer" in consigne and "élargir" in consigne
    # Le contre-exemple tiré des dossiers réels doit y figurer : une règle sans
    # exemple se relit comme une nuance, pas comme une limite.
    assert "mathématiques" in consigne
    assert "domaine_dossier" in consigne


def test_sans_vocabulaire_la_consigne_ne_parle_pas_de_rapprochement():
    """Rien à renommer : la règle n'a pas lieu d'être."""
    assert "renommer" not in prompts.extraction_system_prompt([])


# --- ce que le dépouillement en dit -----------------------------------------


def test_un_rapprochement_est_signale_au_relecteur():
    """« mathématiques appliquées » compté en « informatique » doit se voir."""
    lignes, resultat = appliquer(
        [
            DiplomeExtrait(
                intitule="Licence en mathématiques appliquées",
                niveau=3,
                domaine="informatique",
                domaine_dossier="mathématiques appliquées",
            )
        ]
    )

    assert len(lignes) == 1
    assert lignes[0].domaine == "informatique", "la proposition est conservée"

    avertissement = " ".join(resultat.avertissements)
    assert "mathematiques appliquees" in avertissement
    assert "informatique" in avertissement
    assert "voisin" in avertissement


def test_un_domaine_inchange_ne_dit_rien():
    """Ne pas noyer le relecteur sous des avertissements sans objet."""
    _, resultat = appliquer(
        [
            DiplomeExtrait(
                intitule="Licence en informatique",
                niveau=3,
                domaine="informatique",
                domaine_dossier="informatique",
            )
        ]
    )
    assert resultat.avertissements == []


def test_une_simple_variation_d_ecriture_ne_dit_rien():
    """« Informatique » et « informatique » sont le même mot.

    La comparaison passe par le référentiel, comme le stockage : sans quoi
    chaque majuscule produirait un avertissement.
    """
    _, resultat = appliquer(
        [
            DiplomeExtrait(
                intitule="Master en Génie Logiciel",
                niveau=5,
                domaine="informatique",
                domaine_dossier="Informatique",
            )
        ]
    )
    assert resultat.avertissements == []


def test_un_raccourcissement_ne_dit_rien():
    """« mathématiques appliquées » compté en « mathématiques » est le même
    domaine, dit plus court.

    Le signaler noierait les vrais écarts sous des avertissements que personne
    ne lirait plus.
    """
    _, resultat = appliquer(
        [
            DiplomeExtrait(
                intitule="Licence en mathématiques appliquées",
                niveau=3,
                domaine="mathematiques",
                domaine_dossier="mathématiques appliquées",
            )
        ]
    )
    assert resultat.avertissements == []


def test_un_veritable_ecart_le_dit_toujours():
    """« data science » compté en « informatique » n'a aucun mot commun."""
    _, resultat = appliquer(
        [
            DiplomeExtrait(
                intitule="Master en Data Science",
                niveau=5,
                domaine="informatique",
                domaine_dossier="data science",
            )
        ]
    )
    assert any("data science" in a for a in resultat.avertissements)


def test_un_dossier_muet_sur_son_domaine_ne_dit_rien():
    """Un modèle qui ne rend pas le champ ne doit pas produire de bruit."""
    _, resultat = appliquer(
        [DiplomeExtrait(intitule="Licence en gestion", niveau=3, domaine="gestion")]
    )
    assert resultat.avertissements == []


def test_le_renommage_legitime_est_signale_aussi():
    """« gestion du personnel » → « ressources humaines » est un bon
    rapprochement, et il se signale quand même.

    On ne sait pas distinguer le bon du mauvais sans lire : les deux partagent
    la même forme — deux mots différents pour ce qui est peut-être un seul
    domaine. Les montrer tous les deux laisse trancher qui peut.
    """
    _, resultat = appliquer(
        [
            DiplomeExtrait(
                intitule="Master en gestion du personnel",
                niveau=5,
                domaine="ressources humaines",
                domaine_dossier="gestion du personnel",
            )
        ]
    )
    assert any("ressources humaines" in a for a in resultat.avertissements)


def test_la_provenance_reste_celle_d_une_proposition():
    lignes, _ = appliquer(
        [
            DiplomeExtrait(
                intitule="Licence en mathématiques",
                niveau=3,
                domaine="informatique",
                domaine_dossier="mathématiques",
            )
        ]
    )
    assert lignes[0].provenance is Provenance.EXTRAIT_IA
