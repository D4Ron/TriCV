"""La chaîne de secours : quand elle bascule, et quand elle refuse de basculer.

Le cabinet a deux clés gratuites. Épuiser l'une au milieu d'un mandat affichait
« Extraction indisponible » alors que la seconde dormait à côté.

Ce qui se teste ici n'est pas tant la bascule que sa **retenue**. Deux modèles
ne lisent pas un CV de la même façon : changer de lecteur est une décision, pas
un réflexe. Elle ne se prend que sur un quota épuisé — jamais sur une réponse
illisible, jamais sur une clé refusée, qui sont des pannes à voir et à corriger.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.llm import factory
from app.llm.base import (
    DossierExtrait,
    LLMConfigError,
    LLMError,
    LLMIndisponible,
    LLMProvider,
    LLMQuotaError,
    modele_configure,
)
from app.llm.chaine import ChaineFournisseurs

pytestmark = pytest.mark.anyio


class Faux(LLMProvider):
    """Un fournisseur qui rend ce qu'on lui dit, et compte ses appels."""

    def __init__(self, nom: str, erreur: Exception | None = None) -> None:
        self.name = nom
        self.erreur = erreur
        self.appels = 0

    async def analyze_cv(self, cv, fiche):  # pragma: no cover - hors sujet
        raise NotImplementedError

    async def structure_fiche(self, raw_text, language="fr"):  # pragma: no cover
        raise NotImplementedError

    async def rediger(self, consigne, contexte, systeme="", titre="", cloture=""):
        self.appels += 1
        if self.erreur:
            raise self.erreur
        return f"prose de {self.name}"

    async def extraire_dossier(self, texte, domaines=()):
        self.appels += 1
        if self.erreur:
            raise self.erreur
        return DossierExtrait(langues=[self.name])


# --- ce qui fait basculer ---------------------------------------------------


async def test_un_quota_epuise_passe_au_suivant():
    premier = Faux("mistral", LLMQuotaError("plus de quota"))
    second = Faux("gemini")

    rendu = await ChaineFournisseurs([premier, second]).rediger("Rédigez.", "…")

    assert rendu == "prose de gemini"
    assert (premier.appels, second.appels) == (1, 1)


async def test_le_dépouillement_bascule_aussi():
    premier = Faux("mistral", LLMQuotaError("plus de quota"))
    second = Faux("gemini")

    dossier = await ChaineFournisseurs([premier, second]).extraire_dossier("texte")

    assert dossier.langues == ["gemini"]


async def test_la_bascule_est_journalisee_en_nommant_les_deux(caplog):
    """Un mandat lu par deux modèles doit laisser une trace.

    Un candidat qui conteste son élimination a le droit de savoir quel lecteur
    a lu son dossier ; une bascule muette rendrait la question insoluble.
    """
    chaine = ChaineFournisseurs([Faux("mistral", LLMQuotaError("vide")), Faux("gemini")])

    with caplog.at_level("WARNING"):
        await chaine.rediger("Rédigez.", "…", titre="Publication")

    journal = caplog.text
    assert "mistral" in journal and "gemini" in journal
    assert "même modèle" in journal, "la trace doit dire ce que la bascule change"


# --- ce qui ne fait pas basculer --------------------------------------------


async def test_une_reponse_illisible_ne_fait_pas_changer_de_fournisseur():
    """Elle ne dit rien de l'allocation : la relancer ailleurs masque la panne."""
    premier = Faux("mistral", LLMError("réponse illisible"))
    second = Faux("gemini")

    with pytest.raises(LLMError, match="illisible"):
        await ChaineFournisseurs([premier, second]).rediger("Rédigez.", "…")

    assert second.appels == 0, "le second n'aurait pas dû être sollicité"


async def test_une_cle_refusee_ne_se_contourne_pas():
    """Sinon une configuration fausse se découvre des semaines plus tard."""
    premier = Faux("mistral", LLMConfigError("clé refusée"))
    second = Faux("gemini")

    with pytest.raises(LLMConfigError):
        await ChaineFournisseurs([premier, second]).rediger("Rédigez.", "…")

    assert second.appels == 0


async def test_le_premier_qui_repond_arrete_la_chaine():
    premier = Faux("mistral")
    second = Faux("gemini")

    assert await ChaineFournisseurs([premier, second]).rediger("R.", "…") == "prose de mistral"
    assert second.appels == 0


async def test_tous_epuises_le_dit_clairement():
    """Le message doit nommer les deux : « réessayez » serait un mensonge."""
    chaine = ChaineFournisseurs(
        [Faux("mistral", LLMQuotaError("vide")), Faux("gemini", LLMQuotaError("vide"))]
    )

    with pytest.raises(LLMIndisponible) as echec:
        await chaine.rediger("Rédigez.", "…")

    assert "mistral" in str(echec.value) and "gemini" in str(echec.value)


async def test_une_panne_fait_basculer_comme_un_quota():
    """Un 503 qui survit aux quatre tentatives est une indisponibilité.

    Le laisser passer pour une panne ordinaire privait le rapport de rédacteur
    pendant qu'une seconde clé, en état de marche, ne servait à rien.
    """
    premier = Faux("gemini", LLMIndisponible("HTTP 503: forte demande"))
    second = Faux("mistral")

    assert await ChaineFournisseurs([premier, second]).rediger("R.", "…") == (
        "prose de mistral"
    )


# --- le repos d'un fournisseur épuisé ---------------------------------------


async def test_un_fournisseur_epuise_n_est_pas_resollicite_au_dossier_suivant():
    """Redécouvrir l'épuisement coûte quinze secondes, à chaque fois.

    Sur un lot de vingt dossiers, cinq minutes passées à frapper à une porte
    dont on sait qu'elle est fermée.
    """
    premier = Faux("mistral", LLMQuotaError("plus de quota"))
    second = Faux("gemini")
    chaine = ChaineFournisseurs([premier, second])

    for _ in range(5):
        await chaine.rediger("Rédigez.", "…")

    assert premier.appels == 1, "une seule découverte, pas cinq"
    assert second.appels == 5


async def test_le_repos_expire_et_le_fournisseur_revient():
    """Une allocation revenue doit se retrouver seule, sans redémarrage."""
    premier = Faux("mistral", LLMQuotaError("plus de quota"))
    second = Faux("gemini")
    chaine = ChaineFournisseurs([premier, second], repos_secondes=0)

    await chaine.rediger("Rédigez.", "…")
    premier.erreur = None  # le quota est revenu
    rendu = await chaine.rediger("Rédigez.", "…")

    assert rendu == "prose de mistral"


async def test_tous_au_repos_on_frappe_quand_meme():
    """Refuser sans avoir essayé serait pire que quinze secondes perdues."""
    premier = Faux("mistral", LLMQuotaError("vide"))
    second = Faux("gemini", LLMQuotaError("vide"))
    chaine = ChaineFournisseurs([premier, second])

    with pytest.raises(LLMIndisponible):
        await chaine.rediger("Rédigez.", "…")

    premier.erreur = None
    assert await chaine.rediger("Rédigez.", "…") == "prose de mistral"


# --- qui dépouille, qui rédige ----------------------------------------------


async def test_la_prose_va_au_redacteur_et_le_depouillement_au_depouilleur():
    """Chacun là où il est bon.

    Dépouiller coûte un appel par dossier : c'est ce qui épuise un quota.
    Rédiger part au client sous la signature du cabinet : c'est là qu'une
    phrase inventée devient opposable. Les deux ne demandent pas le même
    fournisseur.
    """
    depouilleur = Faux("mistral")
    redacteur = Faux("gemini")
    chaine = ChaineFournisseurs([depouilleur], prose=[redacteur, depouilleur])

    dossier = await chaine.extraire_dossier("texte")
    prose = await chaine.rediger("Rédigez.", "…")

    assert dossier.langues == ["mistral"], "le dépouillement reste au dépouilleur"
    assert prose == "prose de gemini", "la rédaction va au rédacteur"


async def test_un_redacteur_epuise_retombe_sur_le_depouilleur():
    """Perdre le rédacteur ne doit pas faire perdre le rapport."""
    depouilleur = Faux("mistral")
    redacteur = Faux("gemini", LLMQuotaError("plus de quota"))
    chaine = ChaineFournisseurs([depouilleur], prose=[redacteur, depouilleur])

    assert await chaine.rediger("Rédigez.", "…") == "prose de mistral"


async def test_le_nom_de_la_chaine_dit_qui_redige():
    """L'écran de démarrage doit montrer la répartition, pas la cacher."""
    chaine = ChaineFournisseurs([Faux("mistral")], prose=[Faux("gemini"), Faux("mistral")])
    assert "prose" in chaine.name and "gemini" in chaine.name


def test_le_redacteur_declare_se_bâtit_meme_hors_de_la_chaine(config):
    config(
        llm_provider="openai",
        llm_base_url="https://api.mistral.ai/v1",
        llm_api_key="une-cle-mistral",
        llm_model="ministral-14b-latest",
        llm_fallback="",
        llm_prose_provider="gemini",
        gemini_api_key="une-cle-gemini",
        gemini_model="gemini-2.5-flash",
    )

    chaine = factory.build_chain()
    assert [f.name for f in chaine.fournisseurs] == ["openai"]
    assert [f.name for f in chaine.prose] == ["gemini", "openai"]


def test_sans_redacteur_declare_la_prose_suit_la_chaine(config):
    config(
        llm_provider="gemini",
        gemini_api_key="une-cle",
        llm_fallback="",
        llm_prose_provider="",
    )

    fournisseur = factory.build_chain()
    assert fournisseur.name == "gemini"


# --- la construction de la chaîne -------------------------------------------


@pytest.fixture
def config(monkeypatch):
    def poser(**valeurs):
        for nom, valeur in valeurs.items():
            monkeypatch.setattr(settings, nom, valeur)
        factory.reset_provider()

    monkeypatch.setattr(settings, "llm_fallback", "")
    monkeypatch.setattr(settings, "llm_prose_provider", "")
    yield poser
    factory.reset_provider()


def test_un_fournisseur_sans_cle_est_ecarte_pas_fatal(config):
    """C'est ce qui permet de préparer une bascule avant d'avoir la clé.

    La configuration Mistral peut être posée d'avance : tant que la clé manque,
    la chaîne retombe sur Gemini et l'installation marche. Coller la clé suffit
    à promouvoir Mistral.
    """
    config(
        llm_provider="openai",
        llm_base_url="https://api.mistral.ai/v1",
        llm_api_key="",  # pas encore de clé
        llm_model="mistral-small-latest",
        llm_fallback="gemini",
        gemini_api_key="une-cle-gemini",
        gemini_model="gemini-2.5-flash",
    )

    fournisseur = factory.build_chain()
    assert fournisseur.name == "gemini"
    assert fournisseur.model == "gemini-2.5-flash"


def test_la_cle_posee_promeut_le_principal(config):
    config(
        llm_provider="openai",
        llm_base_url="https://api.mistral.ai/v1",
        llm_api_key="une-cle-mistral",
        llm_model="mistral-small-latest",
        llm_fallback="gemini",
        gemini_api_key="une-cle-gemini",
        gemini_model="gemini-2.5-flash",
    )

    fournisseur = factory.build_chain()
    assert fournisseur.name == "openai → gemini"
    assert [f.model for f in fournisseur.fournisseurs] == [
        "mistral-small-latest",
        "gemini-2.5-flash",
    ]


def test_sans_secours_declare_rien_ne_change(config):
    config(llm_provider="gemini", gemini_api_key="une-cle", llm_fallback="")

    fournisseur = factory.build_chain()
    assert fournisseur.name == "gemini"
    assert not hasattr(fournisseur, "fournisseurs")


def test_aucun_fournisseur_utilisable_est_une_erreur_de_configuration(config):
    config(llm_provider="gemini", gemini_api_key="", llm_fallback="")

    with pytest.raises(LLMConfigError):
        factory.build_chain()


# --- le modèle de chacun ----------------------------------------------------


def test_llm_model_ne_deborde_pas_sur_le_secours(config):
    """« mistral-small-latest » n'existe pas chez Google.

    Partager un seul nom de modèle cassait la chaîne au moment précis où elle
    devait sauver la mise.
    """
    config(llm_provider="openai", llm_model="mistral-small-latest", gemini_model="")

    assert modele_configure("openai") == "mistral-small-latest"
    assert modele_configure("gemini", "gemini-2.0-flash") == "gemini-2.0-flash"


def test_le_reglage_propre_prime_sur_le_reglage_commun(config):
    config(llm_provider="gemini", llm_model="gemini-2.5-flash", gemini_model="gemini-2.5-pro")

    assert modele_configure("gemini", "gemini-2.0-flash") == "gemini-2.5-pro"
