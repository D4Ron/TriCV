"""Télécharge un gros fichier en reprenant où il s'est arrêté.

L'installeur d'Ollama fait 1,5 Go. Sur une liaison qui coupe, un téléchargement
d'un seul tenant recommence à zéro à chaque fois — et `Invoke-WebRequest` rend
un fichier tronqué sans rien signaler, si bien que l'installation échoue en
silence. Ici chaque reprise repart de l'octet suivant, et la taille attendue
est vérifiée à la fin.

    python tools/telecharger_reprise.py <url> <destination>
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

MORCEAU = 1 << 20  # 1 Mo
ESSAIS = 40


def taille_attendue(client: httpx.Client, url: str) -> int:
    reponse = client.head(url, follow_redirects=True, timeout=60)
    reponse.raise_for_status()
    return int(reponse.headers.get("content-length", 0))


def telecharger(url: str, destination: Path) -> int:
    with httpx.Client(follow_redirects=True) as client:
        total = taille_attendue(client, url)
        print(f"attendu : {total / 1048576:.1f} Mo", flush=True)

        for essai in range(1, ESSAIS + 1):
            deja = destination.stat().st_size if destination.exists() else 0
            if total and deja >= total:
                break
            entetes = {"Range": f"bytes={deja}-"} if deja else {}
            try:
                with client.stream(
                    "GET", url, headers=entetes, timeout=httpx.Timeout(60, read=120)
                ) as flux:
                    if deja and flux.status_code == 200:
                        # Le serveur ignore la reprise : on repart à zéro.
                        print("reprise refusée, on recommence", flush=True)
                        destination.unlink(missing_ok=True)
                        deja = 0
                    flux.raise_for_status()
                    mode = "ab" if deja else "wb"
                    dernier = time.monotonic()
                    with destination.open(mode) as sortie:
                        for bloc in flux.iter_bytes(MORCEAU):
                            sortie.write(bloc)
                            if time.monotonic() - dernier > 15:
                                recu = destination.stat().st_size if False else sortie.tell()
                                print(
                                    f"  {recu / 1048576:7.1f} Mo"
                                    + (f" / {total / 1048576:.1f}" if total else ""),
                                    flush=True,
                                )
                                dernier = time.monotonic()
            except (httpx.HTTPError, OSError) as exc:
                obtenu = destination.stat().st_size if destination.exists() else 0
                print(
                    f"essai {essai} interrompu à {obtenu / 1048576:.1f} Mo : "
                    f"{type(exc).__name__}",
                    flush=True,
                )
                time.sleep(min(2 * essai, 20))
                continue

        obtenu = destination.stat().st_size if destination.exists() else 0
        if total and obtenu < total:
            print(f"INCOMPLET : {obtenu / 1048576:.1f} / {total / 1048576:.1f} Mo")
            return 1
        print(f"COMPLET : {obtenu / 1048576:.1f} Mo")
        return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(telecharger(sys.argv[1], Path(sys.argv[2])))
