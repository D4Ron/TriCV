"""Conversion barème ↔ dict, pour le stocker en base et le figer par notation.

Reste dans le domaine : aucune dépendance à SQLAlchemy, seulement des types
Python. C'est ce qui permet de rejouer une notation archivée sans base.

La lecture est tolérante aux barèmes écrits avant l'arrivée des documents du
cabinet : ceux-là n'avaient pas de ligne « consistance du dossier », et une
grille déjà remise ne doit pas devenir illisible parce que le barème a changé
depuis. Un barème sans consistance se relit donc tel qu'il a été enregistré,
avec ses 30 points répartis comme ils l'étaient ce jour-là.
"""

from __future__ import annotations

from typing import Any

from app.domain.bareme import (
    Bareme,
    BaremeConsistance,
    BaremeExperience,
    BaremeFormation,
    RegleAjout,
)
from app.domain.referentiel import CodeAjout


def bareme_vers_dict(bareme: Bareme) -> dict[str, Any]:
    return {
        "consistance": {
            "points_max": bareme.consistance.points_max,
            "points_dossier_complet": bareme.consistance.points_dossier_complet,
            "points_coherence": bareme.consistance.points_coherence,
            "points_appreciation": bareme.consistance.points_appreciation,
            "mois_trou_tolere": bareme.consistance.mois_trou_tolere,
        },
        "formation": {
            "points_max": bareme.formation.points_max,
            "points_niveau_requis": bareme.formation.points_niveau_requis,
            "points_par_niveau_superieur": bareme.formation.points_par_niveau_superieur,
            "points_par_certification": bareme.formation.points_par_certification,
            "certifications_max": bareme.formation.certifications_max,
            "points_formation_complementaire": (
                bareme.formation.points_formation_complementaire
            ),
        },
        "experience_generale": _experience_vers_dict(bareme.experience_generale),
        "experience_specifique": _experience_vers_dict(bareme.experience_specifique),
        "ajouts": [
            {
                "code": regle.code.value,
                "points": regle.points,
                "repetitions_max": regle.repetitions_max,
            }
            for regle in bareme.ajouts
        ],
        "points_ajouts_max": bareme.points_ajouts_max,
        "total_max": bareme.total_max,
        "seuil_preselection": bareme.seuil_preselection,
        "poids_note_finale": bareme.poids_note_finale,
    }


def _experience_vers_dict(exp: BaremeExperience) -> dict[str, Any]:
    return {
        "points_max": exp.points_max,
        "points_au_seuil": exp.points_au_seuil,
        "points_par_annee_supplementaire": exp.points_par_annee_supplementaire,
        "annees_supplementaires_max": exp.annees_supplementaires_max,
    }


def _consistance_depuis_dict(donnees: dict[str, Any] | None) -> BaremeConsistance:
    """Un barème d'avant la consistance vaut zéro point de consistance.

    Le relire avec les 3 points du barème actuel gonflerait rétroactivement des
    notes déjà communiquées, et ferait échouer le contrôle de cohérence du
    total. Zéro est la seule lecture fidèle à ce qui avait été calculé.
    """
    if donnees is None:
        return BaremeConsistance(
            points_max=0.0,
            points_dossier_complet=0.0,
            points_coherence=0.0,
            points_appreciation=0.0,
        )
    return BaremeConsistance(**donnees)


def bareme_depuis_dict(donnees: dict[str, Any]) -> Bareme:
    """Reconstruit un barème. Lève si le total ne se referme pas (voir
    `Bareme.__post_init__`), plutôt que de noter sur un barème incohérent."""
    return Bareme(
        consistance=_consistance_depuis_dict(donnees.get("consistance")),
        # Filtré sur les champs connus : un barème enregistré avant l'arrivée
        # des certifications n'a pas les clés correspondantes, et un barème
        # enregistré après une version ultérieure pourrait en avoir d'autres.
        # Ni l'un ni l'autre ne doit rendre une grille archivée illisible.
        formation=BaremeFormation(
            **{
                cle: valeur
                for cle, valeur in donnees["formation"].items()
                if cle in BaremeFormation.__slots__
            }
        ),
        experience_generale=BaremeExperience(**donnees["experience_generale"]),
        experience_specifique=BaremeExperience(**donnees["experience_specifique"]),
        ajouts=tuple(
            RegleAjout(
                code=CodeAjout(regle["code"]),
                points=regle["points"],
                repetitions_max=regle.get("repetitions_max"),
            )
            for regle in donnees.get("ajouts", ())
        ),
        points_ajouts_max=donnees.get("points_ajouts_max", 0.0),
        total_max=donnees.get("total_max", 30.0),
        seuil_preselection=donnees.get("seuil_preselection", 0.0),
        poids_note_finale=donnees.get("poids_note_finale", 30.0),
    )
