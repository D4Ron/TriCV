"""Un mandat d'essai, large exprès, pour éprouver la lecture de vrais CV.

Le corpus de `backend/tools/evaluer_extraction.py` est inventé. C'est
délibéré — un dossier réel n'a rien à faire dans un dépôt — mais cela veut dire
qu'il ne couvre que les mises en page auxquelles quelqu'un a pensé. Un CV réel
mal lu est le seul défaut qui compte vraiment ici, et il ne se découvre pas
contre ses propres suppositions.

Ce script monte donc un poste **volontairement permissif** : niveau bas,
domaines nombreux, une seule pièce exigée. Ce n'est pas un poste réaliste, et
il ne doit pas l'être. Un poste étroit éliminerait tout le monde sur le domaine
et ne dirait rien de la lecture ; ici, chaque dossier est lu, noté, et l'on voit
ce que l'extraction a compris.

    python demo/banc_essai_cv.py            # monte le mandat
    python demo/banc_essai_cv.py --deposer  # y verse les CV du dossier

Les CV se déposent dans « Example docs/CV-test/ », qui est exclu de git comme
tout le répertoire « Example docs ». Rien de ce qui y entre ne peut partir dans
un dépôt.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

BASE = "http://localhost:8000/api/v1"
RACINE = Path(__file__).resolve().parent.parent
DOSSIER_CV = RACINE / "Example docs" / "CV-test"

IDENTIFIANTS = {"email": "admin@tricv.example", "password": "TriCV-NEbTdCIpi18qXm"}

# Les extensions que l'application sait lire, et le type qu'elles annoncent.
# Le contrôle de dépôt vérifie les octets d'en-tête : annoncer un PDF pour un
# .docx le ferait refuser, et le lot entier paraîtrait cassé.
TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
}
EXTENSIONS = set(TYPES)


def jeton(client: httpx.Client) -> dict[str, str]:
    reponse = client.post(f"{BASE}/auth/login", json=IDENTIFIANTS)
    reponse.raise_for_status()
    return {"Authorization": f"Bearer {reponse.json()['access_token']}"}


def monter(client: httpx.Client, auth: dict[str, str]) -> str:
    """Le mandat, le poste et l'avis. Rend l'identifiant du poste."""
    client_id = client.post(
        f"{BASE}/clients",
        json={"nom": "Banc d'essai — lecture de CV", "secteur": "Interne"},
        headers=auth,
    ).json()["id"]

    mandat_id = client.post(
        f"{BASE}/mandats",
        json={
            "client_id": client_id,
            "intitule": "Éprouver la lecture de dossiers réels",
            "reference": "ESSAI-CV",
        },
        headers=auth,
    ).json()["id"]

    poste = client.post(
        f"{BASE}/mandats/{mandat_id}/postes",
        json={
            "intitule": "Cadre — poste d'essai",
            # Bas exprès : c'est la lecture qu'on éprouve, pas la sélection.
            "niveau_min": 2,
            "domaines_acceptes": [
                "gestion",
                "finance",
                "comptabilite",
                "administration",
                "ressources humaines",
                "droit",
                "economie",
                "informatique",
                "ingenierie",
                "commerce",
                "marketing",
                "logistique",
                "communication",
                "sante",
                "education",
            ],
            "annees_experience_min": 1,
            "annees_experience_specifique_min": 0,
            "domaines_experience": [],
            # Une seule pièce : un CV seul doit suffire à faire un dossier.
            "pieces_requises": ["CV"],
        },
        headers=auth,
    )
    poste.raise_for_status()
    poste_id = poste.json()["id"]

    avis = client.post(
        f"{BASE}/postes/{poste_id}/avis",
        json={"type_avis": "NATIONAL", "date_cloture": "2027-12-31"},
        headers=auth,
    ).json()
    client.post(f"{BASE}/avis/{avis['id']}/publier", headers=auth)

    print(f"mandat  : {mandat_id}")
    print(f"poste   : {poste_id}")
    print(f"avis    : publié, clé {avis['cle_publique']}")
    return poste_id


def deposer(client: httpx.Client, auth: dict[str, str], poste_id: str) -> None:
    """Verse en lot les CV du dossier d'essai sur le poste.

    Un fichier par dossier : personne n'a rien saisi, l'état civil se réduit au
    nom du fichier et le dossier arrive « à vérifier ». C'est exactement la
    situation qu'on veut éprouver — celle d'un CV qui tombe et qu'il faut lire.
    """
    fichiers = sorted(
        f for f in DOSSIER_CV.iterdir() if f.suffix.lower() in EXTENSIONS
    ) if DOSSIER_CV.exists() else []

    if not fichiers:
        print(f"Aucun CV dans {DOSSIER_CV}")
        print("Déposez-y des fichiers .pdf, .docx ou .doc, puis relancez.")
        return

    print(f"{len(fichiers)} fichier(s) à verser :")
    envoi = []
    for chemin in fichiers:
        mime = TYPES[chemin.suffix.lower()]
        envoi.append(("fichiers", (chemin.name, chemin.read_bytes(), mime)))
        print(f"   {chemin.name}")

    # `depouiller_aussitot` : c'est tout l'objet du banc. Sans lui les dossiers
    # arriveraient vides et l'on n'aurait rien éprouvé.
    reponse = client.post(
        f"{BASE}/postes/{poste_id}/candidatures/depot-multiple",
        data={"depouiller_aussitot": "true"},
        files=envoi,
        headers=auth,
        timeout=900,
    )
    if reponse.status_code >= 400:
        print(f"ÉCHEC HTTP {reponse.status_code} : {reponse.text[:600]}")
        return

    rendu = reponse.json()
    print(
        f"\ndossiers : {rendu.get('deposes', '?')}   "
        f"pièces : {rendu.get('pieces', '?')}   "
        f"refusés : {rendu.get('refuses', '?')}   "
        f"doublons ignorés : {rendu.get('doublons_ignores', '?')}"
    )
    print("\nlecture de chaque dossier :")
    for ligne in rendu.get("resultats", []):
        nom = str(ligne.get("fichier", "?"))[:38]
        if not ligne.get("accepte"):
            print(f"   {nom:40} REFUSÉ — {ligne.get('erreur', '')[:60]}")
            continue
        print(f"   {nom:40} {ligne.get('lecture') or 'non dépouillé'}")


def main() -> int:
    analyse = argparse.ArgumentParser(description=__doc__)
    analyse.add_argument("--deposer", action="store_true", help="verser les CV du dossier")
    analyse.add_argument("--poste", default="", help="poste existant, avec --deposer")
    options = analyse.parse_args()

    with httpx.Client(timeout=120) as client:
        try:
            auth = jeton(client)
        except httpx.HTTPError as exc:
            print(f"API injoignable ({exc}). Lancez .\\start-dev.ps1 d'abord.")
            return 1

        poste_id = options.poste or monter(client, auth)
        if options.deposer:
            deposer(client, auth, poste_id)
        else:
            print(f"\nDéposez vos CV dans :\n   {DOSSIER_CV}")
            print(f"\npuis :\n   python demo/banc_essai_cv.py --deposer --poste {poste_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
