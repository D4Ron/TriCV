"""Mesure de bout en bout du dépouillement : CV -> expurgation -> modèle -> parcours.

Ce script n'est pas un test : il appelle le vrai fournisseur et consomme du
quota. Il sert à *régler*. Un test dit qu'une règle tient ; celui-ci dit si le
dossier ressort juste, ce qu'aucune assertion locale ne peut établir.

    cd backend
    .venv/Scripts/python.exe -m tools.evaluer_extraction avant
    …modification…
    .venv/Scripts/python.exe -m tools.evaluer_extraction apres

Chaque passage écrit `tools/resultats/<étiquette>.json` : le texte expurgé, la
réponse du modèle et le détail des écarts, pour comparer deux réglages ligne à
ligne plutôt que sur une impression.

Le corpus vit dans `corpus_cv.py`. Il est **entièrement fictif** — le dossier
d'un vrai candidat n'a rien à faire dans un dépôt. En ajouter un cas est le
geste attendu chaque fois qu'un CV réel se dépouille mal : on en écrit
l'équivalent inventé, on le mesure, et la correction cesse d'être une
supposition.

Repères mesurés le 5 septembre 2026, gemini-2.5-flash, six dossiers :

    avant les correctifs   diplômes  7/14   expériences  7/18
    après                  diplômes 14/14   expériences 18/18

Comparaison de fournisseurs, 11 septembre 2026, même corpus :

    gemini-2.5-flash       diplômes 14/14   expériences 18/18   certifs 6/7
    ministral-14b-latest   diplômes 14/14   expériences 18/18   certifs 5/7

Égalité sur ce qui décide d'une note. Le choix s'est fait sur le quota — 30
requêtes/minute contre 250 par jour — et non sur la lecture.

Modèle local, 15 septembre 2026, même corpus :

    qwen3:8b (ollama)      diplômes 13/14   expériences 17/18   certifs 6/6

Les deux écarts sont la **même faute**, et ce n'est pas une invention : le
modèle retient la première date qu'il voit au lieu de la bonne.

    « Depuis mars 2018 »                          lu 2018-01
    « 2006 - 2008 : Master … (BAC+5) »            lu 2006

Rien n'est inventé et rien n'est perdu : les trois diplômes et les trois
expériences du cas « dense » sont là, et le *niveau* du Master — le seul
élément que le barème note — est juste. Le compteur le sanctionne parce qu'il
compare aussi l'année. Ce que cela coûte en pratique : deux mois d'expérience
générale en trop, une année de diplôme erronée dans le parcours affiché — que
les RH confirment avant qu'elle ne compte, puisqu'un `EXTRAIT_IA` non confirmé
force `A_VERIFIER`.

Reste la durée, et c'est elle qui tranche. Un fil, trois dossiers chronométrés :
**52 s en moyenne** (30 s, 89 s, 37 s), soit **plus de deux heures pour cent
cinquante dossiers**.

Ce n'est pas la machine : `ollama ps` annonce le modèle à **100 % sur la carte
graphique**. C'est le modèle. `qwen3` *raisonne* avant de répondre — il rédige
son cheminement entre balises `<think>`, que `app/llm/prose.py` jette ensuite.
Ce cheminement se paie à chaque dossier.

D'où l'emploi : `ollama` n'est pas le fournisseur d'un mandat courant, c'est
celui qui permet de continuer quand les deux quotas sont épuisés ou qu'un
client refuse que les dossiers sortent de ses murs. À garder en secours, pas en
principal.

Si l'on veut lui en demander davantage, essayer un modèle qui ne raisonne pas à
voix haute — `llama3.1:8b`, `mistral:7b` — et le mesurer ici avant de le
retenir : la vitesse ne vaut rien si la lecture se dégrade.

À noter : `mistral-small-latest` et `mistral-medium-latest` sont à **zéro**
requête/minute sur l'offre gratuite de Mistral. Seule la famille `ministral`
y est allouée. Un 429 immédiat sur une clé neuve vient de là, pas du compte.

Les trois causes, dans l'ordre où elles coûtaient : l'expurgation effaçait les
intitulés de poste, les employeurs et les langues ; un champ nul rendait tout
le dossier invalide ; l'échelle des diplômes donnée au modèle s'arrêtait à la
Licence.
"""

from __future__ import annotations

import asyncio
import json
import sys
import unicodedata
from pathlib import Path

# Exécutable depuis `backend/` sans installation : `python -m tools.evaluer_extraction`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.llm.factory import get_provider  # noqa: E402
from app.services import redaction  # noqa: E402
from app.services.depouillement import _niveau_du_diplome  # noqa: E402
from tools.corpus_cv import CVS  # noqa: E402

SORTIE = Path(__file__).parent / "resultats"


def plat(texte: str) -> str:
    sans = "".join(
        c for c in unicodedata.normalize("NFD", texte.lower()) if unicodedata.category(c) != "Mn"
    )
    return " ".join(sans.replace("-", " ").replace("'", " ").split())


def note_diplomes(attendus: list[dict], obtenus: list[dict]) -> tuple[int, int, list[str]]:
    """Un diplôme compte pour juste si son niveau et son année sont retrouvés."""
    restants = list(obtenus)
    justes = 0
    remarques: list[str] = []
    for attendu in attendus:
        trouve = next(
            (
                o
                for o in restants
                if o.get("niveau") == attendu["niveau"] and o.get("annee") == attendu["annee"]
            ),
            None,
        )
        if trouve is None:
            proche = next((o for o in restants if o.get("annee") == attendu["annee"]), None)
            remarques.append(
                f"diplôme BAC+{attendu['niveau']} {attendu['annee']} manqué"
                + (f" (relevé BAC+{proche.get('niveau')})" if proche else "")
            )
        else:
            justes += 1
            restants.remove(trouve)
    for surplus in restants:
        remarques.append(f"diplôme en trop : {surplus.get('intitule')!r}")
    return justes, len(attendus), remarques


def note_experiences(attendues: list[dict], obtenues: list[dict]) -> tuple[int, int, list[str]]:
    """Juste = employeur reconnaissable, mois de début *et* mois de fin exacts.

    Les dates ne sont pas un détail : elles décident de l'ancienneté, donc du
    franchissement des seuils, donc de l'élimination.
    """
    restantes = list(obtenues)
    justes = 0
    remarques: list[str] = []
    for attendue in attendues:
        cle = plat(attendue["employeur"])
        trouvee = next(
            (o for o in restantes if cle in plat(str(o.get("employeur") or ""))), None
        )
        if trouvee is None:
            remarques.append(f"expérience {attendue['employeur']!r} absente")
            continue
        restantes.remove(trouvee)
        debut = str(trouvee.get("debut") or "")[:7]
        fin = trouvee.get("fin")
        fin = str(fin)[:7] if fin else None
        if debut != attendue["debut"]:
            remarques.append(
                f"{attendue['employeur']} : début {debut or 'vide'} au lieu de {attendue['debut']}"
            )
            continue
        if fin != attendue["fin"]:
            remarques.append(
                f"{attendue['employeur']} : fin {fin or 'vide'} au lieu de {attendue['fin']}"
            )
            continue
        justes += 1
    for surplus in restantes:
        remarques.append(f"expérience en trop : {surplus.get('employeur')!r}")
    return justes, len(attendues), remarques


async def un_cas(nom: str, cas: dict, avec_nom_connu: bool) -> dict:
    texte = cas["texte"]
    connus = redaction.KnownValues()
    if avec_nom_connu:
        # Ce que le formulaire public fournit : le nom saisi par le candidat.
        # Sans lui — un dépôt en lot —, l'expurgation n'a que le NER.
        premiere = [ligne for ligne in texte.strip().splitlines() if ligne.strip()][0]
        connus = redaction.KnownValues(full_name=premiere.strip())

    expurge = redaction.redact_sync(texte, connus)
    dossier = await get_provider().extraire_dossier(expurge.text)

    brut = dossier.model_dump()
    # Le niveau retenu est celui que le dépouillement écrira en base, repli du
    # référentiel compris : c'est lui qui compte, pas la valeur brute.
    for propose, sortie in zip(dossier.diplomes, brut["diplomes"]):
        niveau = _niveau_du_diplome(propose)
        sortie["niveau"] = int(niveau) if niveau is not None else None

    d_justes, d_total, d_notes = note_diplomes(cas["verite"]["diplomes"], brut["diplomes"])
    e_justes, e_total, e_notes = note_experiences(cas["verite"]["experiences"], brut["experiences"])

    return {
        "cas": nom,
        "diplomes": f"{d_justes}/{d_total}",
        "experiences": f"{e_justes}/{e_total}",
        "langues": f"{len(brut['langues'])}/{cas['verite']['langues']}",
        "certifications": f"{len(brut['certifications'])}/{cas['verite']['certifications']}",
        "remarques": d_notes + e_notes,
        "brut": brut,
        "expurge": expurge.text,
        "compteurs": expurge.counts,
    }


async def main() -> None:
    arguments = [a for a in sys.argv[1:] if not a.startswith("--")]
    etiquette = arguments[0] if arguments else "courant"
    avec_nom = "--sans-nom" not in sys.argv

    resultats = await asyncio.gather(
        *(un_cas(nom, cas, avec_nom) for nom, cas in CVS.items())
    )

    total_d = total_dm = total_e = total_em = 0
    print(f"\n=== {etiquette} (nom connu : {avec_nom}) ===")
    print(f"{'cas':16} {'diplômes':10} {'expériences':12} {'langues':9} {'certifs':9}")
    for r in resultats:
        print(
            f"{r['cas']:16} {r['diplomes']:10} {r['experiences']:12} "
            f"{r['langues']:9} {r['certifications']:9}"
        )
        for remarque in r["remarques"]:
            print(f"    · {remarque}")
        acquis, attendu = r["diplomes"].split("/")
        total_d += int(acquis)
        total_dm += int(attendu)
        acquis, attendu = r["experiences"].split("/")
        total_e += int(acquis)
        total_em += int(attendu)

    print(f"\nTOTAL diplômes {total_d}/{total_dm} · expériences {total_e}/{total_em}")

    SORTIE.mkdir(exist_ok=True)
    (SORTIE / f"{etiquette}.json").write_text(
        json.dumps(resultats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Détail : {SORTIE / f'{etiquette}.json'}")


if __name__ == "__main__":
    asyncio.run(main())
