"""Les pièces qu'un poste demande : chacune une fois, à une seule place.

Quatre réglages se superposent sur la fiche — pièces exigées, pièces
facultatives, groupes (« la CNI ou le passeport », « le diplôme et
l'attestation ») et documents libres — et rien n'empêchait d'y nommer deux fois
la même pièce. Constaté sur un avis : la carte d'identité exigée seule *et*
dans « carte d'identité ou passeport ». L'avis la demandait deux fois, le
formulaire offrait deux champs pour le même document, et les deux règles se
contredisaient : l'une écartait le candidat venu avec son seul passeport,
l'autre l'acceptait.

`normaliser` rend une liste où chaque pièce a une place, choisie ainsi :

- **un groupe l'emporte sur une exigence simple.** « CNI ou passeport » est la
  règle la plus précise ; exiger aussi la CNI seule l'annulerait, et ce serait
  l'élimination silencieuse que le groupe existe pour empêcher. Dans « le
  diplôme et l'attestation », les deux sont exigés de toute façon ;
- **une exigence l'emporte sur « facultative »** ;
- **une pièce n'appartient qu'à un groupe** — le premier ;
- **« Autre document » n'est pas une pièce à exiger** : c'est ce que couvrent
  les documents libres.

Chaque correction est dite, pour que l'écran l'explique au lieu de la cacher.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.referentiel import PieceDossier

AUTRE = PieceDossier.AUTRE.value


def libelle(code: str) -> str:
    try:
        return PieceDossier(code).libelle
    except ValueError:
        return code


@dataclass(slots=True)
class PiecesDuPoste:
    requises: list[str]
    facultatives: list[str]
    groupes: list[dict]
    libres_autorisees: bool
    remarques: list[str] = field(default_factory=list)


def _uniques(codes) -> list[str]:
    return list(dict.fromkeys(c for c in (codes or ()) if c))


def normaliser(
    requises,
    facultatives,
    groupes,
    libres_autorisees: bool = True,
) -> PiecesDuPoste:
    remarques: list[str] = []
    requises = _uniques(requises)
    facultatives = _uniques(facultatives)
    libres = bool(libres_autorisees)

    # « Autre document » : un document que le candidat nomme lui-même.
    if AUTRE in requises or AUTRE in facultatives:
        requises = [c for c in requises if c != AUTRE]
        facultatives = [c for c in facultatives if c != AUTRE]
        if not libres:
            libres = True
        remarques.append(
            "« Autre document » n'est pas une pièce à demander : les documents libres "
            "le couvrent, et ils sont autorisés."
        )

    # Exigée l'emporte sur facultative.
    doubles = [c for c in facultatives if c in requises]
    if doubles:
        facultatives = [c for c in facultatives if c not in requises]
        remarques.append(
            f"{', '.join(libelle(c) for c in doubles)} : exigée et facultative à la fois — "
            "gardée exigée."
        )

    propres: list[dict] = []
    dans_un_groupe: set[str] = set()
    for brut in groupes or ():
        g = brut if isinstance(brut, dict) else dict(brut)
        mode = g.get("mode") or "TOUTES"
        nom = g.get("libelle") or ""
        codes = [c for c in _uniques(g.get("codes")) if c != AUTRE]
        deja = [c for c in codes if c in dans_un_groupe]
        if deja:
            codes = [c for c in codes if c not in dans_un_groupe]
            remarques.append(
                f"{', '.join(libelle(c) for c in deja)} : déjà dans un autre groupe, "
                f"retirée de « {nom or 'groupe'} »."
            )
        if mode == "AU_MOINS_UNE" and len(codes) < 2:
            # Un « au choix » d'une seule pièce est une exigence simple.
            if codes and codes[0] not in requises:
                requises.append(codes[0])
            if codes or g.get("codes"):
                remarques.append(
                    f"Le groupe « {nom or 'au choix'} » n'offrait plus de choix : "
                    + (f"{libelle(codes[0])} est exigée simplement." if codes else "retiré.")
                )
            continue
        if not codes:
            continue
        # Le groupe gouverne ses pièces : elles quittent les listes simples.
        exigees = [c for c in codes if c in requises]
        if exigees:
            requises = [c for c in requises if c not in codes]
            if mode == "AU_MOINS_UNE":
                remarques.append(
                    f"{', '.join(libelle(c) for c in exigees)} n'est plus exigée seule : "
                    f"le groupe « {nom or 'au choix'} » la demande, au choix avec "
                    f"{', '.join(libelle(c) for c in codes if c not in exigees)}."
                )
            else:
                remarques.append(
                    f"{', '.join(libelle(c) for c in exigees)} : déjà demandée par le groupe "
                    f"« {nom or 'groupe'} », retirée des pièces exigées."
                )
        couvertes = [c for c in codes if c in facultatives]
        if couvertes:
            facultatives = [c for c in facultatives if c not in codes]
            remarques.append(
                f"{', '.join(libelle(c) for c in couvertes)} : demandée par le groupe "
                f"« {nom or 'groupe'} », elle n'est plus facultative."
            )
        dans_un_groupe.update(codes)
        propres.append({"codes": codes, "mode": mode, "libelle": nom})

    return PiecesDuPoste(requises, facultatives, propres, libres, remarques)
