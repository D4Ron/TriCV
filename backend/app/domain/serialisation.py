"""Conversion barème ↔ dict, pour le stocker en base et le figer par notation.

Reste dans le domaine : aucune dépendance à SQLAlchemy, seulement des types
Python. C'est ce qui permet de rejouer une notation archivée sans base.
"""

from __future__ import annotations

from typing import Any

from app.domain.bareme import (
    Bareme,
    BaremeExperience,
    BaremeFormation,
    RegleAjout,
)
from app.domain.referentiel import CodeAjout


def bareme_vers_dict(bareme: Bareme) -> dict[str, Any]:
    return {
        "formation": {
            "points_max": bareme.formation.points_max,
            "points_niveau_requis": bareme.formation.points_niveau_requis,
            "points_par_niveau_superieur": bareme.formation.points_par_niveau_superieur,
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
    }


def _experience_vers_dict(exp: BaremeExperience) -> dict[str, Any]:
    return {
        "points_max": exp.points_max,
        "points_au_seuil": exp.points_au_seuil,
        "points_par_annee_supplementaire": exp.points_par_annee_supplementaire,
        "annees_supplementaires_max": exp.annees_supplementaires_max,
    }


def bareme_depuis_dict(donnees: dict[str, Any]) -> Bareme:
    """Reconstruit un barème. Lève si le total ne se referme pas (voir
    `Bareme.__post_init__`), plutôt que de noter sur un barème incohérent."""
    return Bareme(
        formation=BaremeFormation(**donnees["formation"]),
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
        seuil_preselection=donnees.get("seuil_preselection", 20.0),
    )
