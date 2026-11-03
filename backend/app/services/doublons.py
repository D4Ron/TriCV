"""Détection des doublons de candidature.

Un même dossier arrive facilement deux fois : le candidat postule par le
formulaire puis renvoie son CV par email, ou les RH déposent en lot un dossier
déjà saisi. Trois signaux, du plus sûr au plus faible :

1. **Fichier identique** — même empreinte SHA-256. Aucun doute possible.
2. **Même adresse email** — très probablement la même personne.
3. **Mêmes nom, prénom et date de naissance** — homonymie possible, donc
   signalé plus faiblement.

Un doublon n'est plus créé pour être signalé : à l'arrivée, ses pièces
**nouvelles** sont versées au dossier existant (`absorber`), les pièces
identiques sont écartées, et rien d'autre n'est ouvert. Un candidat qui
renvoie un CV corrigé ou les diplômes oubliés complète ainsi son dossier, sans
qu'un second dossier encombre la grille. `fusionner_poste` fait de même pour
les doublons déjà présents — sauf quand les deux dossiers portent un travail
humain (entretien, données confirmées) : ceux-là restent à trancher.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Candidat, Candidature, PieceCandidature, Provenance
from app.models.boite import MessageTraite


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
    db: AsyncSession, poste_id: str | None, empreintes: list[str]
) -> tuple[str, str] | None:
    """La candidature du même poste portant déjà l'un de ces fichiers.

    Sert à écarter un dépôt *avant* de le créer. Le critère est volontairement
    le seul qui soit certain : un fichier identique au bit près est la même
    pièce, sans information nouvelle. Une adresse email répétée, elle, désigne
    souvent un candidat qui renvoie une version corrigée — l'écarter ferait
    perdre la bonne version, donc ce cas reste un simple signalement.

    `poste_id=None` compare aux candidatures spontanées entre elles : elles ne
    se rattachent à aucun poste, mais un même CV envoyé deux fois reste un
    doublon.
    """
    if not empreintes:
        return None
    ligne = (
        await db.execute(
            select(Candidature.id, Candidat.nom, Candidat.prenom)
            .join(Candidat, Candidat.id == Candidature.candidat_id)
            .join(PieceCandidature, PieceCandidature.candidature_id == Candidature.id)
            .where(
                Candidature.poste_id.is_(None)
                if poste_id is None
                else Candidature.poste_id == poste_id,
                PieceCandidature.empreinte.in_(empreintes),
            )
            .limit(1)
        )
    ).first()
    if ligne is None:
        return None
    identifiant, nom, prenom = ligne
    return identifiant, f"{nom.upper()} {prenom}".strip()


def _meme_poste(candidature: Candidature):
    # `= NULL` n'est jamais vrai en SQL : les candidatures sans poste se
    # comparent avec IS NULL.
    if candidature.poste_id is None:
        return Candidature.poste_id.is_(None)
    return Candidature.poste_id == candidature.poste_id


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
                _meme_poste(candidature),
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
                _meme_poste(candidature),
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
                _meme_poste(candidature),
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


# --- ne pas garder de doublon ---------------------------------------------------


def _travail_humain(candidature: Candidature) -> bool:
    """Un dossier qu'une personne du cabinet a déjà travaillé : on n'y renonce pas."""
    return bool(
        candidature.entretiens
        or candidature.candidat.provenance in (Provenance.VERIFIE_RH, Provenance.SAISI_RH)
        or candidature.statut.value in ("PRESELECTIONNEE", "RETENUE")
    )


def _a_garder(une: Candidature, autre: Candidature) -> bool:
    """`une` vaut-elle mieux qu'`autre` comme dossier gardé ?

    Le travail du cabinet d'abord, puis ce que le candidat a déclaré lui-même
    dans le formulaire, plus sûr qu'une lecture automatique. À égalité, le
    premier arrivé (l'ordre d'appel).
    """
    def rang(c: Candidature) -> tuple[int, int]:
        return (int(_travail_humain(c)), int(c.candidat.provenance is Provenance.DECLARE))

    return rang(une) >= rang(autre)


async def verser(
    db: AsyncSession, source: Candidature, cible: Candidature, raison: str
) -> Candidature:
    """Verse `source` dans `cible` : pièces nouvelles, coordonnées manquantes,
    traces de courriel. Puis retire `source`. Ne commit pas.

    Les pièces identiques au bit près sont écartées, leur fichier effacé. Le
    dossier gardé est relu (sans IA) s'il n'a pas été confirmé, pour profiter
    des pièces reçues.
    """
    from app.services import storage
    from app.services.preselection import charger_candidature, evaluer_candidature

    source = await charger_candidature(db, source.id)
    cible = await charger_candidature(db, cible.id)
    deja = {p.empreinte for p in cible.pieces if p.empreinte}
    deplacees: list[str] = []
    a_effacer: list[str] = []
    for piece in list(source.pieces):
        if piece.empreinte and piece.empreinte in deja:
            if piece.chemin_stockage:
                a_effacer.append(piece.chemin_stockage)
            await db.delete(piece)
        else:
            deplacees.append(piece.id)
            if piece.empreinte:
                deja.add(piece.empreinte)
    await db.flush()
    if deplacees:
        await db.execute(
            update(PieceCandidature)
            .where(PieceCandidature.id.in_(deplacees))
            .values(candidature_id=cible.id)
        )
    await db.execute(
        update(MessageTraite)
        .where(MessageTraite.candidature_id == source.id)
        .values(candidature_id=cible.id)
    )

    ancien, neuf = cible.candidat, source.candidat
    if neuf.id != ancien.id:
        for champ in ("email", "telephone"):
            if not getattr(ancien, champ) and getattr(neuf, champ):
                setattr(ancien, champ, getattr(neuf, champ))
    note = f"{len(deplacees)} pièce(s) reçue(s) en double versée(s) ici ({raison})."
    cible.notes_rh = f"{cible.notes_rh}\n{note}" if cible.notes_rh else note

    autres = await db.scalar(
        select(func.count()).select_from(Candidature).where(
            Candidature.candidat_id == neuf.id, Candidature.id != source.id
        )
    )
    await db.refresh(source, ["pieces"])
    await db.delete(source)
    if not autres and neuf.id != ancien.id:
        await db.delete(neuf)
    await db.flush()
    depot = storage.get_storage()
    for chemin in a_effacer:
        try:
            await depot.delete(chemin)
        except OSError:
            pass

    cible = await charger_candidature(db, cible.id)
    if deplacees and cible.candidat.provenance is Provenance.EXTRAIT_IA:
        from app.services import depouillement

        try:
            await depouillement.depouiller(db, cible, ia=False)
            return await charger_candidature(db, cible.id)
        except Exception:  # noqa: BLE001 — la fusion est faite, la relecture est un plus
            pass
    await evaluer_candidature(db, cible)
    return cible


async def absorber(db: AsyncSession, nouvelle: Candidature) -> tuple[Candidature, Doublon] | None:
    """Si `nouvelle` double un dossier existant, l'y verse et rend (dossier gardé, motif).

    Appelée juste après la création d'un dossier — courriel, dépôt en lot —,
    une fois ses pièces lues : c'est là que l'adresse du CV et la date de
    naissance sont connues.
    """
    trouves = await detecter(db, nouvelle)
    if not trouves:
        return None
    doublon = trouves[0]
    cible = await db.get(Candidature, doublon.candidature_id)
    if cible is None:
        return None
    gardee = await verser(db, nouvelle, cible, doublon.libelle.lower())
    return gardee, doublon


@dataclass(slots=True)
class Fusion:
    fusionnes: list[str]
    a_trancher: list[str]


async def fusionner_poste(db: AsyncSession, poste_id: str | None) -> Fusion:
    """Ne laisse aucun doublon sur un poste (ou parmi les candidatures sans poste).

    Le dossier gardé est celui qu'une personne a travaillé, sinon le plus
    ancien. Deux dossiers travaillés l'un et l'autre ne se fusionnent pas
    d'office : ils restent signalés, à trancher.
    """
    from app.services.preselection import charger_candidature

    condition = Candidature.poste_id.is_(None) if poste_id is None else Candidature.poste_id == poste_id
    identifiants = list(
        (await db.execute(select(Candidature.id).where(condition).order_by(Candidature.recue_le, Candidature.id))).scalars()
    )
    fusion = Fusion([], [])
    retires: set[str] = set()
    signales: set[frozenset[str]] = set()
    for identifiant in identifiants:
        if identifiant in retires:
            continue
        courante = await charger_candidature(db, identifiant)
        for doublon in await detecter(db, courante):
            if doublon.candidature_id in retires:
                continue
            autre = await charger_candidature(db, doublon.candidature_id)
            garder, retirer = (courante, autre) if _a_garder(courante, autre) else (autre, courante)
            if _travail_humain(autre) and _travail_humain(courante):
                paire = frozenset((courante.id, autre.id))
                if paire in signales:
                    continue
                signales.add(paire)
                fusion.a_trancher.append(
                    f"{courante.candidat.nom.upper()} {courante.candidat.prenom} ({doublon.libelle.lower()})"
                )
                continue
            nom = f"{retirer.candidat.nom.upper()} {retirer.candidat.prenom}".strip()
            await verser(db, retirer, garder, doublon.libelle.lower())
            retires.add(retirer.id)
            fusion.fusionnes.append(nom)
            if retirer.id == courante.id:
                break
            courante = await charger_candidature(db, garder.id)
    return fusion
