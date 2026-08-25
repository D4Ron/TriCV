"""Détection des doublons de candidature.

Un même dossier arrive facilement deux fois : le candidat postule par le
formulaire puis renvoie son CV par email, ou les RH déposent en lot un dossier
déjà saisi. Trois signaux, du plus sûr au plus faible :

1. **Fichier identique** — même empreinte SHA-256. Aucun doute possible.
2. **Même adresse email** — très probablement la même personne.
3. **Mêmes nom, prénom et date de naissance** — homonymie possible, donc
   signalé plus faiblement.

Le résultat *signale*, il ne bloque jamais. Un candidat qui renvoie une version
corrigée de son CV n'est pas un fraudeur, et c'est aux RH de trancher entre
« doublon à supprimer » et « dossier mis à jour ».
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Candidat, Candidature, PieceCandidature


class MotifDoublon(str, Enum):
    FICHIER_IDENTIQUE = "FICHIER_IDENTIQUE"
    MEME_EMAIL = "MEME_EMAIL"
    MEME_IDENTITE = "MEME_IDENTITE"

    @property
    def libelle(self) -> str:
        return {
            MotifDoublon.FICHIER_IDENTIQUE: "Fichier identique déjà reçu",
            MotifDoublon.MEME_EMAIL: "Même adresse email",
            MotifDoublon.MEME_IDENTITE: "Mêmes nom, prénom et date de naissance",
        }[self]

    @property
    def certitude(self) -> str:
        return "certaine" if self is MotifDoublon.FICHIER_IDENTIQUE else "probable"


@dataclass(frozen=True, slots=True)
class Doublon:
    candidature_id: str
    nom_complet: str
    motif: MotifDoublon

    @property
    def libelle(self) -> str:
        return self.motif.libelle


async def trouver_identique(
    db: AsyncSession, poste_id: str, empreintes: list[str]
) -> tuple[str, str] | None:
    """La candidature du même poste portant déjà l'un de ces fichiers.

    Sert à écarter un dépôt *avant* de le créer. Le critère est volontairement
    le seul qui soit certain : un fichier identique au bit près est la même
    pièce, sans information nouvelle. Une adresse email répétée, elle, désigne
    souvent un candidat qui renvoie une version corrigée — l'écarter ferait
    perdre la bonne version, donc ce cas reste un simple signalement.
    """
    if not empreintes:
        return None
    ligne = (
        await db.execute(
            select(Candidature.id, Candidat.nom, Candidat.prenom)
            .join(Candidat, Candidat.id == Candidature.candidat_id)
            .join(PieceCandidature, PieceCandidature.candidature_id == Candidature.id)
            .where(
                Candidature.poste_id == poste_id,
                PieceCandidature.empreinte.in_(empreintes),
            )
            .limit(1)
        )
    ).first()
    if ligne is None:
        return None
    identifiant, nom, prenom = ligne
    return identifiant, f"{nom.upper()} {prenom}".strip()


async def detecter(
    db: AsyncSession, candidature: Candidature, limite: int = 10
) -> list[Doublon]:
    """Les autres candidatures du même poste qui ressemblent à celle-ci.

    Le périmètre est le poste, pas la base entière : postuler à deux postes
    différents est normal et ne doit rien déclencher.
    """
    candidat = candidature.candidat
    trouves: dict[str, Doublon] = {}

    def retenir(candidature_id: str, nom: str, prenom: str, motif: MotifDoublon) -> None:
        # Le premier motif trouvé gagne : ils sont testés du plus sûr au plus
        # faible, donc un fichier identique n'est jamais rétrogradé.
        if candidature_id not in trouves:
            trouves[candidature_id] = Doublon(
                candidature_id=candidature_id,
                nom_complet=f"{nom.upper()} {prenom}".strip(),
                motif=motif,
            )

    empreintes = [p.empreinte for p in candidature.pieces if p.empreinte]
    if empreintes:
        lignes = await db.execute(
            select(Candidature.id, Candidat.nom, Candidat.prenom)
            .join(Candidat, Candidat.id == Candidature.candidat_id)
            .join(PieceCandidature, PieceCandidature.candidature_id == Candidature.id)
            .where(
                Candidature.poste_id == candidature.poste_id,
                Candidature.id != candidature.id,
                PieceCandidature.empreinte.in_(empreintes),
            )
            .limit(limite)
        )
        for identifiant, nom, prenom in lignes:
            retenir(identifiant, nom, prenom, MotifDoublon.FICHIER_IDENTIQUE)

    if candidat.email:
        lignes = await db.execute(
            select(Candidature.id, Candidat.nom, Candidat.prenom)
            .join(Candidat, Candidat.id == Candidature.candidat_id)
            .where(
                Candidature.poste_id == candidature.poste_id,
                Candidature.id != candidature.id,
                func.lower(Candidat.email) == candidat.email.lower(),
            )
            .limit(limite)
        )
        for identifiant, nom, prenom in lignes:
            retenir(identifiant, nom, prenom, MotifDoublon.MEME_EMAIL)

    # L'homonymie seule ne suffit pas : la date de naissance doit correspondre
    # aussi, faute de quoi deux « KOFI Kossi » distincts seraient confondus.
    if candidat.date_naissance is not None:
        lignes = await db.execute(
            select(Candidature.id, Candidat.nom, Candidat.prenom)
            .join(Candidat, Candidat.id == Candidature.candidat_id)
            .where(
                Candidature.poste_id == candidature.poste_id,
                Candidature.id != candidature.id,
                func.lower(Candidat.nom) == candidat.nom.lower(),
                func.lower(Candidat.prenom) == candidat.prenom.lower(),
                Candidat.date_naissance == candidat.date_naissance,
            )
            .limit(limite)
        )
        for identifiant, nom, prenom in lignes:
            retenir(identifiant, nom, prenom, MotifDoublon.MEME_IDENTITE)

    return list(trouves.values())[:limite]


async def compter_par_candidature(db: AsyncSession, poste_id: str) -> dict[str, int]:
    """Pour chaque candidature, combien d'*autres* partagent son adresse email.

    Le critère n'est plus le fichier : un dossier strictement identique est
    désormais écarté au dépôt, donc deux d'entre eux ne peuvent plus coexister.
    Restent les envois répétés depuis la même adresse avec des pièces
    différentes — typiquement un CV corrigé — qu'il faut signaler sans jamais
    les écarter d'office, puisque la seconde version est souvent la bonne.

    Une seule requête pour tout le poste : la liste d'un poste à deux cents
    dossiers doit rester utilisable.
    """
    lignes = await db.execute(
        select(func.lower(Candidat.email), Candidature.id)
        .join(Candidat, Candidat.id == Candidature.candidat_id)
        .where(Candidature.poste_id == poste_id, Candidat.email.is_not(None))
    )

    par_email: dict[str, set[str]] = {}
    for email, candidature_id in lignes:
        par_email.setdefault(email, set()).add(candidature_id)

    voisines: dict[str, int] = {}
    for identifiants in par_email.values():
        if len(identifiants) < 2:
            continue
        for identifiant in identifiants:
            voisines[identifiant] = len(identifiants) - 1
    return voisines
