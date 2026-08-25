"""Le vivier : les profils déjà passés par le cabinet, cherchables.

Un mandat se termine, ses fichiers se purgent — mais les personnes, elles,
restent connues. Une candidature écartée pour un poste de directeur financier
il y a deux ans reste un profil de directeur financier ; le retrouver en une
recherche vaut mieux que de relancer un avis et recommencer le dépouillement.

C'est précisément ce que la purge préserve. Elle efface le PDF, pas ce qu'on en
a tiré : identité, coordonnées, diplômes, parcours, notes obtenues. Le vivier
est la page qui rend cette distinction visible — et utile.

Deux précautions structurent le module :

- **La provenance suit le profil.** Un état civil deviné depuis un en-tête
  d'email n'a pas la valeur d'un état civil relu par un humain. Le vivier
  transporte donc la provenance jusqu'à l'écran, plutôt que de présenter les
  deux du même ton.
- **Rien n'est reconstruit.** Les années d'expérience et l'âge se recalculent
  depuis les mêmes fonctions du domaine que la présélection, pour qu'un chiffre
  affiché ici ne puisse pas contredire une grille.

Le filtrage se fait pour partie en SQL, pour partie en Python : nationalités et
durées d'expérience sont stockées de façon qui ne se filtre pas proprement en
SQL portable. C'est tenable parce que le vivier d'un cabinet se compte en
milliers de personnes, pas en millions ; si cela changeait, ces deux filtres
seraient les premiers à passer en colonnes calculées.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.profil import duree_mois
from app.domain.referentiel import NiveauDiplome, Sexe
from app.models import (
    Candidat,
    Candidature,
    Client,
    Mandat,
    PieceCandidature,
    Poste,
    Provenance,
)
from app.services.preselection import construire_profil


@dataclass(slots=True)
class Criteres:
    recherche: str = ""
    niveau_min: int | None = None
    domaine: str = ""
    annees_experience_min: float | None = None
    sexe: Sexe | None = None
    age_min: int | None = None
    age_max: int | None = None
    nationalite: str = ""


@dataclass(slots=True)
class LigneVivier:
    candidat: Candidat
    age: int | None
    annees_experience: float
    niveau_max: int | None
    diplome_principal: str | None
    domaine_principal: str | None
    dernier_poste: str | None
    dernier_employeur: str | None
    nombre_candidatures: int
    derniere_candidature: date | None
    postes_vises: list[str] = field(default_factory=list)
    pieces_conservees: int = 0
    pieces_purgees: int = 0
    # Tous les enregistrements de la même personne, le représentant compris.
    identifiants: list[str] = field(default_factory=list)
    # Diplômes et parcours réunis sur l'ensemble du groupe.
    diplomes: list = field(default_factory=list)
    experiences: list = field(default_factory=list)


def _normaliser(texte: str) -> str:
    return " ".join(texte.lower().split())


# --- regroupement d'une personne --------------------------------------------
#
# Chaque candidature crée son propre enregistrement d'état civil : c'est
# volontaire côté présélection, où figer les données au moment du dépôt garantit
# qu'une grille reste reproductible. Mais pour le vivier, quelqu'un qui a postulé
# trois fois est *une* personne, pas trois profils.
#
# On regroupe donc à l'affichage, sans jamais toucher aux enregistrements : la
# grille d'un mandat ancien continue de lire exactement ce qu'elle lisait.

# Ordre de confiance : c'est l'enregistrement le plus solide qui prête son
# identité au groupe. Un nom relu par les RH prime sur un nom deviné.
_CONFIANCE = {
    Provenance.VERIFIE_RH: 3,
    Provenance.SAISI_RH: 2,
    Provenance.DECLARE: 1,
    Provenance.EXTRAIT_IA: 0,
}


def _cle_identite(candidat: Candidat) -> str:
    """Ce qui fait dire « c'est la même personne ».

    L'email d'abord : c'est l'identifiant que le candidat fournit lui-même et
    qui sert déjà à lui répondre. À défaut, le nom complet et la date de
    naissance. Deux homonymes sans email ni date de naissance se retrouveront
    fusionnés — inconvénient assumé, largement préférable à un vivier où la même
    personne apparaît cinq fois.
    """
    if candidat.email:
        return f"email:{candidat.email.strip().lower()}"
    return (
        f"nom:{_normaliser(candidat.nom)}|{_normaliser(candidat.prenom)}"
        f"|{candidat.date_naissance or ''}"
    )


def _representant(groupe: list[Candidat]) -> Candidat:
    return max(
        groupe,
        key=lambda c: (
            _CONFIANCE.get(c.provenance, 0),
            c.verifie_le is not None,
            # À confiance égale, l'enregistrement le mieux rempli.
            sum(1 for v in (c.telephone, c.date_naissance, c.sexe, c.adresse) if v),
            c.created_at or date.min,
        ),
    )


def _fusionner(groupe: list[Candidat]) -> tuple[list, list]:
    """Diplômes et expériences du groupe, sans répétition à l'identique.

    Le même diplôme ressaisi à chaque candidature ne doit pas apparaître trois
    fois. Les durées, elles, ne risquent rien : `duree_mois` fusionne les
    intervalles, donc deux copies d'un même poste ne comptent pas double.
    """
    diplomes: dict[tuple, object] = {}
    experiences: dict[tuple, object] = {}
    for candidat in groupe:
        for d in candidat.diplomes:
            diplomes.setdefault(
                (_normaliser(d.intitule), d.niveau, _normaliser(d.domaine), d.annee), d
            )
        for e in candidat.experiences:
            experiences.setdefault(
                (_normaliser(e.poste), _normaliser(e.employeur), e.debut, e.fin), e
            )
    return list(diplomes.values()), list(experiences.values())


def _annees(profil, reference: date) -> float:
    # Les intervalles se recouvrent souvent (missions menées en parallèle) :
    # `duree_mois` les fusionne, donc deux postes simultanés ne comptent pas
    # double. Même fonction que la présélection, donc même résultat.
    return round(duree_mois(profil.experiences, reference) / 12, 1)


def _requete_tous():
    """Tous les enregistrements d'état civil, parcours compris.

    Le filtrage ne se fait plus en SQL : une personne se juge sur son groupe
    entier, et le groupe se forme en Python. Filtrer avant de regrouper ferait
    disparaître quelqu'un dont c'est *l'autre* candidature qui portait le
    diplôme recherché.
    """
    return (
        select(Candidat)
        .options(selectinload(Candidat.diplomes), selectinload(Candidat.experiences))
        .order_by(Candidat.nom, Candidat.prenom)
    )


def _texte_cherchable(ligne: LigneVivier) -> str:
    """Tout ce sur quoi la recherche libre porte, en une chaîne.

    Le vivier se cherche par métier autant que par nom : « comptable »,
    « hôpital » ou « Sarakawa » sont dans le parcours, pas dans l'état civil.
    """
    candidat = ligne.candidat
    morceaux = [
        candidat.nom,
        candidat.prenom,
        candidat.email or "",
        candidat.telephone or "",
        *(f"{d.intitule} {d.domaine} {d.etablissement or ''}" for d in ligne.diplomes),
        *(f"{e.poste} {e.employeur}" for e in ligne.experiences),
    ]
    return _normaliser(" ".join(morceaux))


def _domaines(ligne: LigneVivier) -> str:
    morceaux = [
        *(d.domaine for d in ligne.diplomes),
        *(f"{e.poste} {e.employeur}" for e in ligne.experiences),
        *(d for e in ligne.experiences for d in (e.domaines or ())),
    ]
    return _normaliser(" ".join(morceaux))


async def _resume_candidatures(
    db: AsyncSession, identifiants: list[str]
) -> dict[str, dict]:
    """Combien de dossiers, pour quels postes, et ce qu'il reste de fichiers.

    En une requête par agrégat plutôt qu'une par candidat : la liste peut
    afficher cinquante profils.
    """
    if not identifiants:
        return {}

    resultat = await db.execute(
        select(
            Candidature.candidat_id,
            func.count(Candidature.id),
            func.max(Candidature.recue_le),
        )
        .where(Candidature.candidat_id.in_(identifiants))
        .group_by(Candidature.candidat_id)
    )
    resume = {
        candidat_id: {
            "nombre": nombre,
            "derniere": derniere,
            "postes": [],
        }
        for candidat_id, nombre, derniere in resultat
    }

    postes = await db.execute(
        select(Candidature.candidat_id, Poste.intitule)
        .join(Poste, Poste.id == Candidature.poste_id)
        .where(Candidature.candidat_id.in_(identifiants))
        .order_by(Candidature.recue_le.desc())
    )
    for candidat_id, intitule in postes:
        entree = resume.setdefault(candidat_id, {"nombre": 0, "derniere": None, "postes": []})
        if intitule not in entree["postes"]:
            entree["postes"].append(intitule)

    return resume


async def _compte_pieces(db: AsyncSession, identifiants: list[str]) -> dict[str, tuple[int, int]]:
    """Pièces encore sur le disque, et pièces purgées, par candidat."""
    if not identifiants:
        return {}

    resultat = await db.execute(
        select(
            Candidature.candidat_id,
            func.count(PieceCandidature.id).filter(
                PieceCandidature.chemin_stockage.is_not(None)
            ),
            func.count(PieceCandidature.id).filter(PieceCandidature.purge_le.is_not(None)),
        )
        .join(PieceCandidature, PieceCandidature.candidature_id == Candidature.id)
        .where(Candidature.candidat_id.in_(identifiants))
        .group_by(Candidature.candidat_id)
    )
    return {ligne[0]: (ligne[1] or 0, ligne[2] or 0) for ligne in resultat}


def _retenu(ligne: LigneVivier, criteres: Criteres) -> bool:
    """Tous les filtres, appliqués au groupe et non à un enregistrement isolé."""
    if criteres.recherche:
        if _normaliser(criteres.recherche) not in _texte_cherchable(ligne):
            return False
    if criteres.niveau_min is not None:
        if ligne.niveau_max is None or ligne.niveau_max < criteres.niveau_min:
            return False
    if criteres.domaine:
        if _normaliser(criteres.domaine) not in _domaines(ligne):
            return False
    if criteres.sexe is not None and ligne.candidat.sexe != criteres.sexe:
        return False
    if criteres.annees_experience_min is not None:
        if ligne.annees_experience < criteres.annees_experience_min:
            return False
    if criteres.age_min is not None and (ligne.age is None or ligne.age < criteres.age_min):
        return False
    if criteres.age_max is not None and (ligne.age is None or ligne.age > criteres.age_max):
        return False
    if criteres.nationalite:
        voulue = _normaliser(criteres.nationalite)
        connues = [_normaliser(n) for n in (ligne.candidat.nationalites or ())]
        if not any(voulue in n for n in connues):
            return False
    return True


def _grouper(candidats: list[Candidat]) -> list[list[Candidat]]:
    groupes: dict[str, list[Candidat]] = {}
    for candidat in candidats:
        groupes.setdefault(_cle_identite(candidat), []).append(candidat)
    return list(groupes.values())


async def rechercher(
    db: AsyncSession,
    criteres: Criteres,
    *,
    page: int = 1,
    page_size: int = 50,
    reference: date | None = None,
) -> tuple[list[LigneVivier], int]:
    """Renvoie la page demandée et le nombre total de personnes retenues.

    Une personne, une ligne — même si elle a postulé cinq fois. L'âge et
    l'ancienneté sont calculés à la date du jour et non à la date de clôture
    d'un avis : ici on cherche qui est disponible *aujourd'hui*, on ne rejoue
    pas une présélection passée.
    """
    aujourdhui = reference or date.today()
    candidats = list((await db.execute(_requete_tous())).scalars().unique())
    groupes = _grouper(candidats)

    identifiants = [c.id for c in candidats]
    resume = await _resume_candidatures(db, identifiants)
    pieces = await _compte_pieces(db, identifiants)

    lignes = [
        ligne
        for ligne in (
            _construire_ligne(groupe, resume, pieces, aujourdhui) for groupe in groupes
        )
        if _retenu(ligne, criteres)
    ]
    lignes.sort(key=lambda l: (_normaliser(l.candidat.nom), _normaliser(l.candidat.prenom)))

    total = len(lignes)
    debut = max(page - 1, 0) * page_size
    return lignes[debut : debut + page_size], total


def _construire_ligne(
    groupe: list[Candidat],
    resume: dict[str, dict],
    pieces: dict[str, tuple[int, int]],
    aujourdhui: date,
) -> LigneVivier:
    """Une personne, vue à travers tous ses enregistrements."""
    representant = _representant(groupe)
    diplomes, experiences = _fusionner(groupe)

    # Le profil du domaine est construit sur l'union : c'est lui qui fournit
    # l'âge, le niveau et l'ancienneté, avec les mêmes règles que la grille.
    porteur = replace_donnees(representant, diplomes, experiences)
    profil = construire_profil(porteur, frozenset())
    principal = profil.diplome_principal
    niveau = profil.niveau_max()

    # « Dernière » expérience : celle qui finit le plus tard, un poste toujours
    # occupé (fin nulle) comptant comme finissant aujourd'hui.
    derniere_exp = max(
        experiences, key=lambda e: (e.fin or aujourdhui, e.debut), default=None
    )

    nombre = 0
    dernieres: list = []
    postes: list[str] = []
    conservees = purgees = 0
    for candidat in groupe:
        info = resume.get(candidat.id)
        if info:
            nombre += info["nombre"]
            if info["derniere"] is not None:
                dernieres.append(info["derniere"])
            for intitule in info["postes"]:
                if intitule not in postes:
                    postes.append(intitule)
        compte = pieces.get(candidat.id)
        if compte:
            conservees += compte[0]
            purgees += compte[1]

    derniere = max(dernieres) if dernieres else None
    return LigneVivier(
        candidat=representant,
        age=profil.age_au(aujourdhui),
        annees_experience=_annees(profil, aujourdhui),
        niveau_max=int(niveau) if niveau is not None else None,
        diplome_principal=principal.intitule if principal else None,
        domaine_principal=principal.domaine if principal else None,
        dernier_poste=derniere_exp.poste if derniere_exp else None,
        dernier_employeur=derniere_exp.employeur if derniere_exp else None,
        nombre_candidatures=nombre,
        derniere_candidature=derniere.date() if hasattr(derniere, "date") else derniere,
        postes_vises=postes[:5],
        pieces_conservees=conservees,
        pieces_purgees=purgees,
        identifiants=[c.id for c in groupe],
        diplomes=diplomes,
        experiences=experiences,
    )


class replace_donnees:
    """Vue en lecture d'un candidat, avec les diplômes et parcours du groupe.

    `construire_profil` ne lit que quelques attributs ; plutôt que de modifier
    l'enregistrement — ce qui l'écrirait en base à la prochaine synchronisation
    — on lui présente une façade.
    """

    def __init__(self, candidat: Candidat, diplomes: list, experiences: list) -> None:
        self._candidat = candidat
        self.diplomes = diplomes
        self.experiences = experiences

    def __getattr__(self, nom: str):
        return getattr(self._candidat, nom)


async def resumer(
    db: AsyncSession, candidat: Candidat, reference: date | None = None
) -> LigneVivier:
    """Les mêmes chiffres que la liste, pour une personne et son groupe."""
    aujourdhui = reference or date.today()
    candidats = list((await db.execute(_requete_tous())).scalars().unique())
    cle = _cle_identite(candidat)
    groupe = [c for c in candidats if _cle_identite(c) == cle] or [candidat]

    identifiants = [c.id for c in groupe]
    resume = await _resume_candidatures(db, identifiants)
    pieces = await _compte_pieces(db, identifiants)
    return _construire_ligne(groupe, resume, pieces, aujourdhui)



async def historique(db: AsyncSession, identifiants: list[str]) -> list[dict]:
    """Toutes les candidatures d'une personne, mandat et client compris.

    Prend la liste des enregistrements du groupe : quelqu'un ayant postulé à
    trois avis a trois états civils distincts en base, et son historique doit
    les réunir.
    """
    if not identifiants:
        return []

    resultat = await db.execute(
        select(Candidature, Poste, Mandat, Client)
        .join(Poste, Poste.id == Candidature.poste_id)
        .join(Mandat, Mandat.id == Poste.mandat_id)
        .join(Client, Client.id == Mandat.client_id)
        .options(selectinload(Candidature.notation), selectinload(Candidature.pieces))
        .where(Candidature.candidat_id.in_(identifiants))
        .order_by(Candidature.recue_le.desc())
    )

    lignes: list[dict] = []
    for candidature, poste, mandat, client in resultat:
        notation = candidature.notation
        lignes.append(
            {
                "candidature_id": candidature.id,
                "poste_id": poste.id,
                "poste": poste.intitule,
                "mandat": mandat.intitule,
                "client": client.nom,
                "recue_le": candidature.recue_le,
                "statut": candidature.statut,
                "source": candidature.source,
                "note": float(notation.note_retenue) if notation else None,
                "note_max": float(notation.total_max) if notation else None,
                "atteint_le_seuil": notation.atteint_le_seuil if notation else None,
                # Ce qui reste consultable, et ce qui a été purgé avec le mandat.
                "pieces_conservees": sum(
                    1 for p in candidature.pieces if p.chemin_stockage is not None
                ),
                "pieces_purgees": sum(1 for p in candidature.pieces if p.purge_le is not None),
                "mandat_archive": mandat.archive_le is not None,
            }
        )
    return lignes


async def charger(db: AsyncSession, candidat_id: str) -> Candidat | None:
    resultat = await db.execute(
        select(Candidat)
        .options(selectinload(Candidat.diplomes), selectinload(Candidat.experiences))
        .where(Candidat.id == candidat_id)
    )
    return resultat.scalar_one_or_none()


def libelle_niveau(niveau: int | None) -> str | None:
    if niveau is None:
        return None
    try:
        return NiveauDiplome(niveau).libelle
    except ValueError:
        return f"BAC+{niveau}"
