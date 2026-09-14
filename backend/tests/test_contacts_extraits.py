"""L'adresse et le téléphone lus dans le dossier.

L'expurgation les repérait déjà — c'est elle qui les retire du texte avant
qu'il ne parte — mais personne ne les recueillait : détectés, masqués, puis
oubliés. Un dossier déposé en lot restait sans adresse, donc injoignable, et
la colonne « E-mail » du tableau remis au client restait vide.

La détection est locale. Le modèle ne voit ni l'une ni l'autre.
"""

from __future__ import annotations

import pytest

from app.models import Provenance
from app.services import depouillement, redaction

pytestmark = pytest.mark.anyio


class Faux:
    """Un candidat réduit à ce que la fonction touche."""

    def __init__(self, provenance, email=None, telephone=None):
        self.provenance = provenance
        self.email = email
        self.telephone = telephone


def appliquer(candidat, texte: str) -> depouillement.ResultatDepouillement:
    expurge = redaction.redact_sync(texte, redaction.KnownValues())
    resultat = depouillement.ResultatDepouillement()
    depouillement._appliquer_contacts(candidat, expurge.contacts, resultat)
    return resultat


CV = (
    "ATTIOGBE Sena\n"
    "s.attiogbe@example.tg · +228 90 33 71 25 · Lomé\n"
    "FORMATION\n2012 Master en comptabilité, Université de Lomé\n"
)


def test_l_adresse_du_cv_remplit_un_dossier_vide():
    candidat = Faux(Provenance.EXTRAIT_IA)
    resultat = appliquer(candidat, CV)

    assert candidat.email == "s.attiogbe@example.tg"
    assert candidat.telephone
    assert resultat.email_trouve == "s.attiogbe@example.tg"


def test_un_champ_vide_se_remplit_meme_sur_un_dossier_relu():
    """Confirmer un parcours n'est pas se prononcer sur l'absence d'adresse.

    Refuser de la renseigner laissait le dossier injoignable sans que personne
    ne l'ait voulu.
    """
    candidat = Faux(Provenance.VERIFIE_RH)
    appliquer(candidat, CV)
    assert candidat.email == "s.attiogbe@example.tg"


@pytest.mark.parametrize(
    "provenance", [Provenance.DECLARE, Provenance.VERIFIE_RH, Provenance.SAISI_RH]
)
def test_une_adresse_humaine_n_est_jamais_remplacee(provenance):
    candidat = Faux(provenance, email="saisie@example.tg", telephone="90 00 00 00")
    resultat = appliquer(candidat, CV)

    assert candidat.email == "saisie@example.tg"
    assert candidat.telephone == "90 00 00 00"
    assert resultat.email_trouve is None


def test_un_dossier_extrait_se_rafraichit():
    """Relancer un dépouillement corrige ce que le précédent avait mal lu."""
    candidat = Faux(Provenance.EXTRAIT_IA, email="ancienne@example.tg")
    resultat = appliquer(candidat, CV)

    assert candidat.email == "s.attiogbe@example.tg"
    assert resultat.email_trouve == "s.attiogbe@example.tg"


def test_un_cv_sans_adresse_ne_fabrique_rien():
    candidat = Faux(Provenance.EXTRAIT_IA)
    resultat = appliquer(candidat, "FORMATION\n2012 Master, Université de Lomé\n")

    assert candidat.email is None
    assert resultat.email_trouve is None


async def test_le_modele_ne_recoit_pas_l_adresse_qu_on_vient_de_lire():
    """La garantie ne change pas : l'adresse est lue *avant* l'expurgation,
    et c'est le texte expurgé qui part."""
    expurge = redaction.redact_sync(CV, redaction.KnownValues())
    assert "s.attiogbe@example.tg" not in expurge.text
    assert expurge.contacts["email"] == "s.attiogbe@example.tg"
