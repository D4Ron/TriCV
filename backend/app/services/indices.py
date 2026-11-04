"""Avant de dire « absent » : chercher dans tout le dossier.

Un motif se calcule sur ce qui a été extrait et rangé. Or ce qui n'a pas été
extrait n'est pas forcément absent : un mot de secteur dans une attestation, un
diplôme voisin de celui demandé, une pièce rangée sous un autre type. Dire
« n'a pas démontré X » quand X est sous les yeux du recruteur fait perdre
confiance en tout le reste, et peut écarter quelqu'un à tort.

Ce module ne change aucun motif : il cherche ce qui pourrait le contredire, et
le dit. Tant qu'un humain n'a pas relu le dossier, un motif accompagné d'un
indice n'élimine pas. Le recruteur tranche, en sachant où regarder.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.domain import familles
from app.domain.profil import ExigencesPoste, ProfilCandidat
from app.domain.referentiel import MotifElimination, PieceDossier
from app.models.recrutement import Candidature
from app.services.decoupage import _plat

P = PieceDossier
# Ces pièces ne disent rien d'un parcours.
_ETAT_CIVIL = frozenset(
    {
        P.PIECE_IDENTITE.value, P.PASSEPORT.value, P.CERTIFICAT_NATIONALITE.value,
        P.CASIER_JUDICIAIRE.value, P.CERTIFICAT_MEDICAL.value, P.PHOTO.value,
    }
)
# Comment une pièce se nomme dans son propre titre.
_TITRES: dict[str, tuple[str, ...]] = {
    P.CV.value: (" curriculum vitae ",),
    P.LETTRE_MOTIVATION.value: (" lettre de motivation ",),
    P.COPIE_DIPLOMES.value: (" diplome ", " baccalaureat ", " grade de ", " degree ", " diploma "),
    P.ATTESTATIONS_TRAVAIL.value: (" attestation de travail ", " certificat de travail ", " attestation d emploi "),
    P.PIECE_IDENTITE.value: (" carte nationale d identite ", " carte d identite ", " identity card "),
    P.PASSEPORT.value: (" passeport ", " passport "),
    P.CASIER_JUDICIAIRE.value: (" casier judiciaire ",),
    P.CERTIFICAT_NATIONALITE.value: (" certificat de nationalite ",),
    P.CERTIFICAT_MEDICAL.value: (" certificat medical ",),
}


def _nom(piece) -> str:
    return piece.nom_fichier or piece.intitule_libre or piece.type_piece


def _lues(candidature: Candidature, *, etat_civil: bool = False) -> list[tuple[object, str]]:
    return [
        (p, p.texte_extrait)
        for p in candidature.pieces
        if p.texte_extrait and (etat_civil or p.type_piece not in _ETAT_CIVIL)
    ]


def _chercher(
    lues: Iterable[tuple[object, str]], domaine: str, lexique: dict[str, list[str]]
) -> str | None:
    for piece, texte in lues:
        terme = familles.terme_present(texte, domaine, lexique.get(domaine, ()))
        if terme:
            return f"« {terme} » figure dans « {_nom(piece)} »"
    return None


def _indice_formation(
    profil: ProfilCandidat,
    exigences: ExigencesPoste,
    candidature: Candidature,
    lexique: dict[str, list[str]],
) -> str | None:
    attendus = sorted(exigences.domaines_acceptes)
    for diplome in profil.diplomes:
        for attendu in attendus:
            if familles.apparente(diplome.domaine, attendu) or familles.apparente(
                diplome.intitule, attendu
            ):
                return f"« {diplome.intitule} » est un domaine voisin de « {attendu} »"
    # Seules les pièces de formation : un CV parle de tout.
    copies = [(p, t) for p, t in _lues(candidature) if p.type_piece == P.COPIE_DIPLOMES.value]
    for attendu in attendus:
        trouve = _chercher(copies, attendu, lexique)
        if trouve:
            return trouve
    return None


def _indice_experience_specifique(
    exigences: ExigencesPoste, candidature: Candidature, lexique: dict[str, list[str]]
) -> str | None:
    lues = _lues(candidature)
    for exigence in exigences.specifiques:
        for domaine in sorted(exigence.domaines):
            trouve = _chercher(lues, domaine, lexique)
            if trouve:
                return trouve
    return None


def _indice_pieces(candidature: Candidature, exigences: ExigencesPoste) -> str | None:
    fournies = {p.type_piece for p in candidature.pieces}
    manquantes = set(exigences.pieces_requises - fournies)
    for groupe in exigences.groupes_pieces:
        manquantes.update(groupe.manquantes(fournies))
    for code in sorted(manquantes):
        for piece, texte in _lues(candidature, etat_civil=True):
            lignes = [l for l in texte.splitlines() if l.strip()]
            titres = " ".join(_plat(l) for l in lignes if len(l.split()) <= 9)
            if any(m in titres for m in _TITRES.get(code, ())):
                libelle = P(code).libelle if code in P._value2member_map_ else code
                return f"« {_nom(piece)} » semble contenir : {libelle}"
    return None


def indices_des_motifs(
    motifs: Iterable,
    profil: ProfilCandidat,
    exigences: ExigencesPoste,
    candidature: Candidature,
    lexique: dict[str, list[str]] | None = None,
) -> dict[MotifElimination, str]:
    """Pour chaque motif, ce qui dans le dossier pourrait le contredire."""
    lexique = lexique or {}
    indices: dict[MotifElimination, str] = {}
    for elimination in motifs:
        motif = elimination.motif
        indice: str | None = None
        if motif is MotifElimination.FORMATION_NON_CONFORME:
            indice = _indice_formation(profil, exigences, candidature, lexique)
        elif motif is MotifElimination.FORMATION_INSUFFISANTE and not profil.diplomes:
            if any(p.type_piece == P.COPIE_DIPLOMES.value for p in candidature.pieces):
                indice = "Une copie de diplôme a été reçue, sans qu'il en soit lu un"
        elif motif is MotifElimination.EXPERIENCE_SPECIFIQUE_INSUFFISANTE:
            indice = _indice_experience_specifique(exigences, candidature, lexique)
        elif motif is MotifElimination.EXPERIENCE_INSUFFISANTE:
            recues = sum(1 for p in candidature.pieces if p.type_piece == P.ATTESTATIONS_TRAVAIL.value)
            if recues:
                indice = f"{recues} attestation(s) de travail à rapprocher du parcours"
        elif motif is MotifElimination.DOSSIER_INCOMPLET:
            indice = _indice_pieces(candidature, exigences)
        if indice:
            indices[motif] = indice[:500]
    return indices
