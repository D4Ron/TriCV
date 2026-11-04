"""Mesure de l'IA sur des dossiers entiers, pas sur un CV propre.

`evaluer_extraction` plafonne : sur un CV seul, le modèle fait déjà 14/14 et
18/18. Ce qui se trompe en vrai, c'est le dossier complet : une attestation
comptée comme un second emploi, un poste souhaité dans la lettre pris pour un
poste tenu, un emploi que seule une attestation mentionne, repoussée au-delà de
la coupure par un long CV.

**Tout y est inventé.** Ce script appelle le vrai fournisseur et consomme du
quota : quatre appels par passage.

    cd backend
    .venv/Scripts/python.exe -m tools.evaluer_dossiers --ancien   # bout à bout
    .venv/Scripts/python.exe -m tools.evaluer_dossiers            # pièces annoncées
"""

from __future__ import annotations

import asyncio
import sys

from app.domain.referentiel import PieceDossier as P
from app.llm.factory import get_provider
from app.services import depouillement, lecture_locale, redaction

LETTRE = (
    "Objet : candidature\nMadame,\nDirecteur logistique depuis peu dans mes aspirations, je "
    "souhaite rejoindre votre groupe comme Directeur Supply Chain chez Global Trans. Mon "
    "expérience de Consultant senior chez Horizon Conseil de 2019 à 2021, que j'espère "
    "exercer demain, me motive.\nVeuillez agréer, Madame, mes salutations distinguées."
)
CV_COURT = """DOSSOU Afi
EXPÉRIENCE PROFESSIONNELLE
Janvier 2018 - Décembre 2022 : Responsable logistique, Port Sec de Lomé
- suivi des flux et des équipes de quai
Mars 2013 - Décembre 2017 : Chef de quai, Togo Transit
FORMATION
2012 : Master en logistique, Université de Lomé
LANGUES
Français, Anglais
"""
ATTESTATION_MEME = (
    "ATTESTATION DE TRAVAIL\nJe soussigné, directeur de Togo Transit, atteste que Mme Afi DOSSOU "
    "a travaillé en qualité de chef de quai du 1er mars 2013 au 31 décembre 2017."
)
ATTESTATION_NOUVELLE = (
    "ATTESTATION DE TRAVAIL\nNous certifions que Mme Afi DOSSOU a occupé le poste d'assistante "
    "transit à la société Sahel Fret de janvier 2010 à février 2013."
)
COPIE = "UNIVERSITÉ DE LOMÉ\nDIPLÔME DE MASTER\nLe jury délivre le grade de master en logistique, session 2012."
RELEVE = "RELEVÉ DE NOTES\nLicence 3, semestre 5 : gestion des flux 14/20 ; moyenne 13,2. Université de Lomé, 2010."
LONG_CV = CV_COURT + "\n".join(
    f"- mission {n} : coordination des expéditions, négociation des tarifs et suivi des indicateurs "
    f"de performance du dépôt, avec reporting mensuel à la direction régionale et audits internes."
    for n in range(1, 190)
)

# (nom, pièces, expériences attendues, diplômes attendus)
CAS = [
    ("attestation_du_meme_emploi", [(P.CV.value, CV_COURT), (P.ATTESTATIONS_TRAVAIL.value, ATTESTATION_MEME)], 2, 1),
    ("lettre_trompeuse", [(P.CV.value, CV_COURT), (P.LETTRE_MOTIVATION.value, LETTRE)], 2, 1),
    ("copie_et_releve", [(P.CV.value, CV_COURT), (P.COPIE_DIPLOMES.value, COPIE), (P.COPIE_DIPLOMES.value, RELEVE)], 2, 1),
    ("emploi_seulement_attesté_apres_long_cv", [(P.CV.value, LONG_CV), (P.ATTESTATIONS_TRAVAIL.value, ATTESTATION_NOUVELLE)], 3, 1),
]


async def un_cas(nom, pieces, attendues, diplomes, ancien):
    if ancien:
        texte = "\n\n".join(t for _, t in pieces)
    else:
        cv = next(t for ty, t in pieces if ty == P.CV.value)
        texte = depouillement.composer_pour_ia(pieces, lecture_locale.lire(cv))
    connus = redaction.KnownValues(full_name="Afi DOSSOU")
    expurge = redaction.redact_sync(texte, connus)
    lu = await get_provider().extraire_dossier(expurge.text)
    bon = len(lu.experiences) == attendues and len(lu.diplomes) == diplomes
    print(
        f"{'✓' if bon else '✗'} {nom:42} expériences {len(lu.experiences)}/{attendues} "
        f"diplômes {len(lu.diplomes)}/{diplomes}"
    )
    return bon


async def main():
    ancien = "--ancien" in sys.argv
    sys.stdout.reconfigure(encoding="utf-8")
    print("ancien envoi" if ancien else "pièces annoncées + brouillon")
    justes = 0
    for cas in CAS:
        justes += await un_cas(*cas, ancien)
        await asyncio.sleep(3)
    print(f"{justes}/{len(CAS)}")


if __name__ == "__main__":
    asyncio.run(main())
