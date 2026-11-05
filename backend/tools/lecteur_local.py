#!/usr/bin/env python3
"""Le lecteur local : Ollama sur ce poste lit les dossiers, la plateforme garde le reste.

Rien à installer hors Python et Ollama, et rien à ouvrir : ce script appelle la
plateforme, jamais l'inverse. Il prend un dossier, le fait lire, rend le résultat,
et recommence. Tant qu'il tourne, la plateforme lui laisse les lectures ; arrêté,
elle les reprend avec son fournisseur.

Reçoit le texte déjà expurgé. Rien n'est écrit sur le disque.

    # La clé se crée dans Paramètres › Général › Lecteur local.
    python lecteur_local.py --url https://recrutement.kapiconsult.tg --cle tricv-lecteur-…

Ou, sans connexion à la plateforme, sur un fichier exporté :

    python lecteur_local.py --fichier lecture.json --sortie result.json

Réglages possibles aussi par TRICV_URL, TRICV_CLE_LECTEUR, OLLAMA_URL, OLLAMA_MODELE.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

FORMAT = "tricv-lecture/1"
FORMAT_REDACTION = "tricv-redaction/1"
PAUSE_AU_REPOS = 20
PAUSE_APRES_ERREUR = 60
DELAI_OLLAMA = 600
# Assez pour un dossier entier : le réglage par défaut d'Ollama le couperait.
CONTEXTE = 16384


def appeler(url: str, *, corps: dict | None = None, entetes: dict | None = None, delai: int = 60) -> dict:
    donnees = json.dumps(corps).encode() if corps is not None else None
    requete = urllib.request.Request(
        url, data=donnees, headers={"content-type": "application/json", **(entetes or {})}
    )
    with urllib.request.urlopen(requete, timeout=delai) as reponse:
        return json.loads(reponse.read().decode())


def lire_json(brut: str) -> dict:
    """Les modèles qui réfléchissent écrivent avant de répondre."""
    texte = re.sub(r"<think>.*?</think>", "", brut, flags=re.S).strip()
    texte = re.sub(r"^```(?:json)?|```$", "", texte, flags=re.M).strip()
    debut, fin = texte.find("{"), texte.rfind("}")
    if debut == -1 or fin <= debut:
        raise ValueError("le modèle n'a pas rendu de JSON")
    return json.loads(texte[debut : fin + 1])


def lire_un_dossier(consigne: str, texte: str, ollama: str, modele: str) -> tuple[dict, int]:
    reponse = appeler(
        f"{ollama}/api/chat",
        corps={
            "model": modele,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2, "num_ctx": CONTEXTE},
            "messages": [
                {"role": "system", "content": consigne},
                {"role": "user", "content": texte},
            ],
        },
        delai=DELAI_OLLAMA,
    )
    contenu = (reponse.get("message") or {}).get("content", "")
    jetons = int(reponse.get("prompt_eval_count", 0)) + int(reponse.get("eval_count", 0))
    return lire_json(contenu), jetons


def verifier_ollama(ollama: str, modele: str) -> None:
    try:
        modeles = [m.get("name", "") for m in appeler(f"{ollama}/api/tags", delai=10).get("models", [])]
    except (urllib.error.URLError, OSError) as exc:
        sys.exit(f"Ollama ne répond pas sur {ollama} ({exc}). Lancez l'application Ollama.")
    if not any(m == modele or m.split(":")[0] == modele for m in modeles):
        sys.exit(f"Le modèle {modele} n'est pas installé. Faites : ollama pull {modele}")


def boucle(url: str, cle: str, ollama: str, modele: str) -> None:
    entetes = {"x-cle-lecteur": cle}
    lecteur = f"ollama:{modele}"
    print(f"Lecteur local en route : {url}, {lecteur}. Ctrl+C pour arrêter.")
    while True:
        try:
            lot = appeler(f"{url}/api/v1/lecteur/travaux?limite=1&modele={lecteur}", entetes=entetes)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                sys.exit("Clé refusée : créez-en une dans Paramètres › Général › Lecteur local.")
            print(f"La plateforme répond {exc.code} : nouvel essai dans une minute.")
            time.sleep(PAUSE_APRES_ERREUR)
            continue
        except (urllib.error.URLError, OSError) as exc:
            print(f"Plateforme injoignable ({exc}) : nouvel essai dans une minute.")
            time.sleep(PAUSE_APRES_ERREUR)
            continue

        dossiers = lot.get("dossiers", [])
        if not dossiers:
            time.sleep(PAUSE_AU_REPOS)
            continue

        for dossier in dossiers:
            debut = time.monotonic()
            retour: dict = {"travail_id": dossier["travail_id"], "lecteur": lecteur}
            try:
                lu, jetons = lire_un_dossier(dossier["consigne"], dossier["texte"], ollama, modele)
                retour["jetons"] = jetons
                retour["resultat"] = {
                    **lu,
                    "candidature_id": dossier["candidature_id"],
                    "empreinte": dossier["empreinte"],
                }
            except (ValueError, KeyError, OSError, urllib.error.URLError) as exc:
                retour["erreur"] = f"{type(exc).__name__} : {exc}"[:500]
            retour["secondes"] = round(time.monotonic() - debut, 1)
            try:
                compte = appeler(f"{url}/api/v1/lecteur/resultats", corps=retour, entetes=entetes)
                print(f"{retour['secondes']:>6} s  {compte.get('etat', '?')}")
            except (urllib.error.URLError, OSError) as exc:
                # La réservation expire seule : le dossier reviendra.
                print(f"Résultat non rendu ({exc}).")


def rediger_une_section(systeme: str, demande: str, ollama: str, modele: str) -> str:
    reponse = appeler(
        f"{ollama}/api/chat",
        corps={
            "model": modele,
            "stream": False,
            "options": {"temperature": 0.3, "num_ctx": CONTEXTE},
            "messages": [
                {"role": "system", "content": systeme},
                {"role": "user", "content": demande},
            ],
        },
        delai=DELAI_OLLAMA,
    )
    contenu = (reponse.get("message") or {}).get("content", "")
    return re.sub(r"<think>.*?</think>", "", contenu, flags=re.S).strip()


def traiter_redaction(lot: dict, sortie: str, ollama: str, modele: str) -> None:
    """Un rapport ou un avis : de la prose, section par section."""
    sections = []
    taches = lot.get("taches", [])
    for rang, tache in enumerate(taches, start=1):
        debut = time.monotonic()
        try:
            texte = rediger_une_section(tache["systeme"], tache["demande"], ollama, modele)
            sections.append({"code": tache["code"], "texte": texte})
            print(f"{rang}/{len(taches)}  {tache.get('titre', '')}  {round(time.monotonic() - debut, 1)} s")
        except (KeyError, OSError, urllib.error.URLError) as exc:
            print(f"{rang}/{len(taches)}  échec : {exc}")
    with open(sortie, "w", encoding="utf-8") as fichier:
        json.dump(
            {
                "format": FORMAT_REDACTION,
                "lecteur": f"ollama:{modele}",
                "document": lot.get("document", {}),
                "sections": sections,
            },
            fichier,
            ensure_ascii=False,
            indent=1,
        )
    print(f"{len(sections)} section(s) dans {sortie}. Importez-le depuis le rapport ou l'avis.")


def traiter_fichier(chemin: str, sortie: str, ollama: str, modele: str) -> None:
    with open(chemin, encoding="utf-8") as fichier:
        lot = json.load(fichier)
    if lot.get("format") == FORMAT_REDACTION:
        traiter_redaction(lot, sortie, ollama, modele)
        return
    if lot.get("format") != FORMAT:
        sys.exit(f"{chemin} n'est pas un lot de lecture ({FORMAT}).")
    rendus = []
    total = len(lot.get("dossiers", []))
    for rang, dossier in enumerate(lot.get("dossiers", []), start=1):
        debut = time.monotonic()
        try:
            lu, _ = lire_un_dossier(lot["consigne"], dossier["texte"], ollama, modele)
            rendus.append(
                {**lu, "candidature_id": dossier["candidature_id"], "empreinte": dossier["empreinte"]}
            )
            print(f"{rang}/{total}  {round(time.monotonic() - debut, 1)} s")
        except (ValueError, KeyError, OSError, urllib.error.URLError) as exc:
            print(f"{rang}/{total}  échec : {exc}")
    with open(sortie, "w", encoding="utf-8") as fichier:
        json.dump(
            {"format": FORMAT, "lecteur": f"ollama:{modele}", "dossiers": rendus},
            fichier,
            ensure_ascii=False,
            indent=1,
        )
    print(f"{len(rendus)} dossier(s) dans {sortie}. Importez-le depuis la page du poste.")


def main() -> None:
    p = argparse.ArgumentParser(description="Lit les dossiers TriCV avec Ollama, sur ce poste.")
    p.add_argument("--url", default=os.environ.get("TRICV_URL", ""))
    p.add_argument("--cle", default=os.environ.get("TRICV_CLE_LECTEUR", ""))
    p.add_argument("--ollama", default=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
    p.add_argument("--modele", default=os.environ.get("OLLAMA_MODELE", "qwen3:8b"))
    p.add_argument("--fichier", help="un lot exporté, à traiter sans connexion à la plateforme")
    p.add_argument("--sortie", default="result.json")
    a = p.parse_args()
    ollama = a.ollama.rstrip("/")
    verifier_ollama(ollama, a.modele)
    if a.fichier:
        traiter_fichier(a.fichier, a.sortie, ollama, a.modele)
        return
    if not a.url or not a.cle:
        sys.exit("Indiquez --url et --cle, ou --fichier pour traiter un lot exporté.")
    boucle(a.url.rstrip("/"), a.cle, ollama, a.modele)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nArrêté. La plateforme reprend les lectures.")
