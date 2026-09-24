"""Purge des fichiers d'un mandat terminé.

Une fois la présélection rendue, les fichiers eux-mêmes n'ont plus d'usage :
ce qui compte est ce qu'on en a tiré — le parcours saisi, la note et son
détail, les motifs d'élimination avec leur arithmétique. Ce sont eux qui
permettent de justifier une décision des mois plus tard, pas le PDF.

Purger supprime donc les documents et conserve tout le reste. La ligne
`PieceCandidature` survit — son type, son nom d'origine, sa taille, son
empreinte — pour deux raisons : le contrôle de complétude repose sur la
*présence* d'une pièce et non sur celle d'un fichier, donc une grille
recalculée après purge donne exactement le même résultat ; et le dossier garde
la trace de ce qui avait été reçu.

C'est la bonne façon de maîtriser le stockage : borner ce qu'on garde dans le
temps, plutôt que refuser au dépôt un scan de diplômes un peu lourd.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Candidature, Mandat, PieceCandidature, Poste
from app.models.base import utcnow
from app.services import storage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ResultatPurge:
    fichiers: int = 0
    octets: int = 0
    candidatures: int = 0
    # Les fiches de poste déposées, comptées à part : ce ne sont pas des
    # dossiers de candidats et leur poids n'est pas enregistré en base.
    fiches: int = 0

    @property
    def mo(self) -> float:
        return round(self.octets / 1_048_576, 1)


async def _pieces_du_mandat(db: AsyncSession, mandat_id: str) -> list[PieceCandidature]:
    resultat = await db.execute(
        select(PieceCandidature)
        .join(Candidature, Candidature.id == PieceCandidature.candidature_id)
        .join(Poste, Poste.id == Candidature.poste_id)
        .where(
            Poste.mandat_id == mandat_id,
            PieceCandidature.chemin_stockage.is_not(None),
        )
    )
    return list(resultat.scalars())


async def _fiches_du_mandat(db: AsyncSession, mandat_id: str) -> list[Poste]:
    """Les postes dont la fiche déposée a encore un fichier.

    La fiche est le document du client, pas celui d'un candidat ; elle n'entre
    donc pas dans le compte des dossiers. Mais c'est un fichier sur le disque,
    et rien ne le supprimait : ni la purge, ni la suppression du mandat.
    """
    resultat = await db.execute(
        select(Poste).where(
            Poste.mandat_id == mandat_id, Poste.fiche_chemin.is_not(None)
        )
    )
    return list(resultat.scalars())


async def estimer(db: AsyncSession, mandat_id: str) -> ResultatPurge:
    """Ce qu'une purge libérerait, sans rien supprimer."""
    pieces = await _pieces_du_mandat(db, mandat_id)
    return ResultatPurge(
        fichiers=len(pieces),
        octets=sum(p.taille_octets or 0 for p in pieces),
        candidatures=len({p.candidature_id for p in pieces}),
        fiches=len(await _fiches_du_mandat(db, mandat_id)),
    )


async def purger_mandat(db: AsyncSession, mandat_id: str) -> ResultatPurge:
    """Supprime les fichiers, garde les dossiers. Ne commit pas."""
    pieces = await _pieces_du_mandat(db, mandat_id)
    depot = storage.get_storage()
    resultat = ResultatPurge(candidatures=len({p.candidature_id for p in pieces}))

    for piece in pieces:
        try:
            await depot.delete(piece.chemin_stockage)
        except OSError as exc:
            # Un fichier déjà absent n'est pas un échec : l'objectif est qu'il
            # ne soit plus là, et la ligne doit être marquée dans tous les cas.
            logger.warning("purge : %s introuvable (%s)", piece.chemin_stockage, exc)
        resultat.fichiers += 1
        resultat.octets += piece.taille_octets or 0
        piece.chemin_stockage = None
        piece.purge_le = utcnow()

    # Les fiches de poste suivent la même règle que les pièces : le fichier
    # s'en va, ce qu'on en a tiré reste. Le texte relevé est conservé —
    # c'est lui que la rédaction d'un avis relit, et il ne pèse rien.
    for poste in await _fiches_du_mandat(db, mandat_id):
        try:
            await depot.delete(poste.fiche_chemin)
        except OSError as exc:
            logger.warning("purge : %s introuvable (%s)", poste.fiche_chemin, exc)
        poste.fiche_chemin = None
        resultat.fiches += 1

    await db.flush()
    return resultat


async def mandat_purgeable(db: AsyncSession, mandat_id: str) -> Mandat | None:
    """Un mandat n'est purgeable qu'une fois archivé.

    Purger un mandat en cours priverait les RH des pièces au moment précis où
    elles en ont besoin : relire un CV, vérifier une donnée extraite, répondre
    à un candidat qui conteste.
    """
    mandat = await db.get(Mandat, mandat_id)
    if mandat is None or mandat.archive_le is None:
        return None
    return mandat
