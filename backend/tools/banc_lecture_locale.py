"""Mesure de la lecture locale (sans IA) sur le corpus fictif.

Le pendant de `evaluer_extraction.py`, sans fournisseur ni quota : la lecture
par règles (`lecture_locale`) est notée sur la même vérité terrain, avec les
mêmes règles de notation. À relancer après chaque retouche des règles.

    cd backend
    .venv/Scripts/python.exe -m tools.banc_lecture_locale
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import lecture_locale  # noqa: E402
from tools.corpus_cv import CVS  # noqa: E402
from tools.evaluer_extraction import note_diplomes, note_experiences  # noqa: E402

# Le corpus a été écrit en 2026 : « à ce jour » s'y lit à cette date.
AUJOURD_HUI = date(2026, 9, 5)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    totaux = {"diplomes": [0, 0], "experiences": [0, 0], "langues": [0, 0], "certifications": [0, 0]}
    for nom, cas in CVS.items():
        lu = lecture_locale.lire(cas["texte"], aujourd_hui=AUJOURD_HUI)
        verite = cas["verite"]
        dj, dn, dr = note_diplomes(verite["diplomes"], [d.model_dump() for d in lu.diplomes])
        ej, en, er = note_experiences(verite["experiences"], [e.model_dump() for e in lu.experiences])
        lj = min(len(lu.langues), verite["langues"])
        cj = min(len(lu.certifications), verite["certifications"])
        for cle, (j, n) in {
            "diplomes": (dj, dn), "experiences": (ej, en),
            "langues": (lj, verite["langues"]), "certifications": (cj, verite["certifications"]),
        }.items():
            totaux[cle][0] += j
            totaux[cle][1] += n
        print(f"— {nom}: diplômes {dj}/{dn}, expériences {ej}/{en}, langues {lj}/{verite['langues']}, "
              f"certifications {cj}/{verite['certifications']}")
        for remarque in dr + er:
            print(f"    {remarque}")
    print()
    print("  ".join(f"{cle} {j}/{n}" for cle, (j, n) in totaux.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
