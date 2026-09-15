"""Où le tableau s'insère dans la prose d'une section.

Le document du cabinet ne met pas ses tableaux en fin de section. Une phrase
les annonce — « L'analyse des dossiers de candidature a permis d'obtenir les
résultats suivants : » —, le tableau suit, et un commentaire des chiffres vient
après. Tout rendre avant le tableau plaçait ce commentaire au-dessus des
chiffres qu'il commente.

La rédaction pose donc une marque à l'endroit voulu, et la section garde deux
blocs de prose. Une marque oubliée ne doit jamais faire perdre du texte : tout
reste alors avant le tableau, ce qui est l'ancien comportement.
"""

from __future__ import annotations

import pytest

from app.services import rapports


def test_la_marque_separe_les_deux_blocs():
    avant, apres = rapports.decouper_autour_du_tableau(
        "L'analyse a permis d'obtenir les résultats suivants :\n"
        "[TABLEAU]\n"
        "Trente-trois (33) candidatures ont été préqualifiées."
    )
    assert avant == "L'analyse a permis d'obtenir les résultats suivants :"
    assert apres == "Trente-trois (33) candidatures ont été préqualifiées."


def test_une_marque_oubliee_ne_perd_aucun_texte():
    """Le modèle l'oublie une fois sur trois. Le rapport doit rester complet."""
    contenu = "Deux paragraphes.\n\nSans aucune marque."
    assert rapports.decouper_autour_du_tableau(contenu) == (contenu, "")


@pytest.mark.parametrize(
    "ligne", ["[TABLEAU]", "  [TABLEAU]  ", "**[TABLEAU]**", "[tableau]", "_[TABLEAU]_"]
)
def test_la_marque_se_reconnait_malgre_le_balisage(ligne):
    """Un modèle qui met une ligne en gras ne doit pas casser le découpage."""
    avant, apres = rapports.decouper_autour_du_tableau(f"Avant.\n{ligne}\nAprès.")
    assert (avant, apres) == ("Avant.", "Après.")


def test_une_marque_au_fil_d_une_phrase_est_retiree_sans_decouper():
    """Elle ne doit en aucun cas s'imprimer dans le document remis."""
    avant, apres = rapports.decouper_autour_du_tableau(
        "Les résultats [TABLEAU] figurent ci-après."
    )
    assert "[TABLEAU]" not in avant
    assert apres == ""


def test_un_contenu_vide_reste_vide():
    assert rapports.decouper_autour_du_tableau("") == ("", "")
