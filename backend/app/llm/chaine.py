"""Plusieurs fournisseurs à la file, pour qu'une allocation épuisée n'arrête rien.

Le cabinet dispose de deux clés gratuites. Chacune a son plafond, et celui de
l'offre gratuite se touche vite : un dépouillement coûte un appel, une section
de rapport aussi. Épuiser le sien au milieu d'un mandat — ou devant un client —
affiche « Extraction indisponible » et arrête le travail alors qu'une seconde
clé dort à côté.

La chaîne essaie les fournisseurs dans l'ordre déclaré et ne passe au suivant
que lorsque celui-ci **ne peut pas servir** — quota épuisé, ou service en panne
après les quatre tentatives. Ce sont les deux seules bascules légitimes :

- une réponse illisible se relance chez le même fournisseur, elle ne dit rien
  de son état ;
- une clé refusée est une erreur de configuration, que masquer chez le voisin
  ferait découvrir des semaines plus tard.

Basculer pour autre chose reviendrait à changer de lecteur pour une raison qui
n'a rien à voir avec la lecture.

La panne compte au même titre que le quota, et l'expérience l'a montré : un
« 503, forte demande » de Gemini qui survit aux quatre tentatives laissait le
rapport sans rédacteur pendant qu'une seconde clé, en état de marche, ne
servait à rien. Un 5xx passager se dissipe dans les quinze secondes du repli ;
celui qui y survit est une indisponibilité.

**Ce que la bascule coûte, et pourquoi elle se trace.** Deux modèles ne lisent
pas un CV de la même façon. Un mandat dépouillé moitié par l'un, moitié par
l'autre, produit une grille dont les lignes ne viennent pas du même lecteur —
et un candidat qui conteste son élimination a le droit de savoir lequel a lu
son dossier. Chaque bascule est donc journalisée en `WARNING`, nommant les deux
fournisseurs. Le reste — inscrire le lecteur sur chaque dossier — demanderait
une colonne en base ; le journal dit déjà quand la question se pose.

**Ce que la bascule ne doit pas faire silencieusement.** Les offres gratuites
n'ont pas la même politique de confidentialité. Celle de Mistral se règle pour
refuser l'entraînement ; celle de Google entraîne sur ce qu'on lui envoie, sans
réglage. Descendre de l'une à l'autre sans le savoir ferait passer de vrais
parcours d'un fournisseur qui les oublie à un fournisseur qui les retient.
`preflight.py` le signale à la configuration : c'est une décision à prendre
une fois, en connaissance de cause, pas une surprise un mardi soir.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence

from app.llm.base import (
    AnalysisResult,
    CriterionDraft,
    CvPayload,
    DossierExtrait,
    FichePayload,
    LLMError,
    LLMIndisponible,
    LLMProvider,
    LLMQuotaError,
)

logger = logging.getLogger(__name__)

# Combien de temps un fournisseur épuisé est laissé de côté avant d'être
# retenté. Sans ce repos, chaque appel repayait le prix de la découverte :
# quatre tentatives et quinze secondes d'attente, pour réapprendre ce qu'on
# savait déjà. Sur un lot de vingt dossiers, cinq minutes perdues à interroger
# une porte fermée.
#
# Quinze minutes est un compromis : assez long pour que le coût devienne
# négligeable, assez court pour qu'une allocation revenue — une limite horaire,
# un plafond relevé, une vérification enfin faite — se retrouve toute seule
# sans qu'on ait à redémarrer quoi que ce soit.
REPOS_SECONDES = 900


class ChaineFournisseurs(LLMProvider):
    """Des fournisseurs essayés dans l'ordre, jusqu'à ce que l'un réponde."""

    def __init__(
        self,
        fournisseurs: Sequence[LLMProvider],
        repos_secondes: int = REPOS_SECONDES,
        prose: Sequence[LLMProvider] | None = None,
    ) -> None:
        if not fournisseurs:
            raise ValueError("Une chaîne de fournisseurs ne peut pas être vide.")
        self.fournisseurs = list(fournisseurs)
        # Qui rédige, quand ce n'est pas qui dépouille. Même mécanique de
        # secours et de repos : c'est l'ordre qui change, pas les règles.
        self.prose = list(prose) if prose else self.fournisseurs
        self.name = " → ".join(f.name for f in self.fournisseurs)
        if self.prose is not self.fournisseurs:
            self.name += " (prose : " + " → ".join(f.name for f in self.prose) + ")"
        self.repos_secondes = repos_secondes
        # Nom du fournisseur -> instant (monotone) avant lequel on ne le
        # sollicite plus. En mémoire seulement : un redémarrage remet tout le
        # monde en lice, ce qui est le bon réflexe après un changement de clé.
        self._au_repos: dict[str, float] = {}

    def _disponibles(self, ordre: Sequence[LLMProvider]) -> list[LLMProvider]:
        maintenant = time.monotonic()
        eveilles = [f for f in ordre if self._au_repos.get(f.name, 0.0) <= maintenant]
        # Tous au repos : on réessaie quand même, dans l'ordre. Mieux vaut
        # quinze secondes perdues qu'un refus sans avoir frappé à la porte.
        return eveilles or list(ordre)

    def _mettre_au_repos(self, fournisseur: LLMProvider) -> None:
        self._au_repos[fournisseur.name] = time.monotonic() + self.repos_secondes

    @property
    def supports_documents(self) -> bool:
        """Le premier décide : c'est lui qui répond tant qu'il a du quota."""
        return getattr(self.fournisseurs[0], "supports_documents", False)

    async def _essayer(self, operation: str, appel, defaut=None, ordre=None):
        """Appelle chaque fournisseur à son tour, tant que le quota est en cause."""
        ordre = ordre or self.fournisseurs
        candidats = self._disponibles(ordre)
        if len(candidats) < len(ordre):
            logger.debug(
                "[chaîne] %s au repos, non sollicité(s) pour « %s ».",
                ", ".join(f.name for f in ordre if f not in candidats),
                operation,
            )

        epuises: list[str] = []
        for rang, fournisseur in enumerate(candidats):
            try:
                resultat = await appel(fournisseur)
            except LLMIndisponible as exc:
                epuises.append(fournisseur.name)
                # Inutile de redécouvrir son indisponibilité au dossier suivant.
                self._mettre_au_repos(fournisseur)
                reste = candidats[rang + 1 :]
                if not reste:
                    raise LLMIndisponible(
                        f"Aucun fournisseur disponible pour « {operation} » : "
                        f"{' ni '.join(epuises)}. Quota épuisé ou service en panne — "
                        f"réessayez plus tard, ou saisissez à la main."
                    ) from exc
                logger.warning(
                    "[chaîne] %s indisponible pour « %s » (%s) ; bascule sur %s, et "
                    "mise au repos %d min. Les dossiers de ce mandat ne sont donc "
                    "plus tous lus par le même modèle.",
                    fournisseur.name,
                    operation,
                    "quota épuisé" if isinstance(exc, LLMQuotaError) else "service en panne",
                    reste[0].name,
                    self.repos_secondes // 60,
                )
                continue

            if epuises:
                logger.warning(
                    "[chaîne] « %s » a été traité par %s, en remplacement de %s.",
                    operation,
                    fournisseur.name,
                    " et ".join(epuises),
                )
            return resultat

        return defaut  # pragma: no cover - la boucle sort toujours avant

    async def analyze_cv(self, cv: CvPayload, fiche: FichePayload) -> AnalysisResult:
        return await self._essayer("analyse d'un CV", lambda f: f.analyze_cv(cv, fiche))

    async def structure_fiche(
        self, raw_text: str, language: str = "fr"
    ) -> list[CriterionDraft]:
        return await self._essayer(
            "structuration d'une fiche",
            lambda f: f.structure_fiche(raw_text, language),
        )

    async def extraire_dossier(
        self, texte: str, domaines: Sequence[str] = ()
    ) -> DossierExtrait:
        return await self._essayer(
            "dépouillement d'un dossier",
            lambda f: f.extraire_dossier(texte, domaines),
            defaut=DossierExtrait(),
        )

    async def rediger(
        self, consigne: str, contexte: str, systeme: str = "", titre: str = ""
    ) -> str:
        # La prose part au client sous la signature du cabinet : elle suit son
        # propre ordre de fournisseurs quand on en a déclaré un.
        return await self._essayer(
            f"rédaction de « {titre or 'une section'} »",
            lambda f: f.rediger(consigne, contexte, systeme, titre),
            defaut="",
            ordre=self.prose,
        )

    async def repondre_json(
        self, consigne: str, contexte: str, systeme: str = ""
    ) -> dict:
        return await self._essayer(
            "correspondance de trame",
            lambda f: f.repondre_json(consigne, contexte, systeme),
            defaut={},
        )


__all__ = ["ChaineFournisseurs", "LLMError"]
