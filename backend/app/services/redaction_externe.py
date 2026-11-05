"""Faire rédiger un rapport ou un avis ailleurs, et en reprendre la prose.

Même idée que `lecture_externe`, même garde-fous, un format à part : ici on
n'extrait pas, on écrit. Ce qui sort, ce sont les consignes et les données déjà
préparées pour le modèle : les chiffres d'un rapport sans aucun nom de candidat,
ou les éléments d'un poste. Ce qui revient, c'est de la prose, section par section.

Ce qui engage le cabinet ne sort pas et ne revient pas. Les tableaux d'un rapport
et les rubriques opposables d'un avis — pièces, date limite, liens — sont produits
ici à l'import, mot pour mot, quoi que dise le fichier.

Une section écrite par un humain n'est jamais remplacée. Ce qui entre reste une
proposition à relire, comme ce que rédige le serveur.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.llm import prompts, prose
from app.models import Avis, Mandat, Poste
from app.models.base import utcnow
from app.models.collaboration import Rapport
from app.services import rapports, redaction_avis
from app.services.parametres import Reglages

FORMAT = "tricv-redaction/1"
# Une section tient en quelques paragraphes : au-delà, ce n'est plus une section.
TEXTE_MAX = 30_000
CONSIGNE_DE_RETOUR = (
    "Pour chaque tâche, rendez son code et le texte demandé, en prose. Suivez « systeme » et "
    "« demande » : ils disent quoi écrire, et avec quelles données. N'ajoutez rien qu'elles ne "
    "contiennent pas. Aucun nom de personne, aucune recommandation sur un candidat."
)


class ResultatInvalide(ValueError):
    """Le fichier ne peut pas être repris tel quel."""


class Section(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str = Field(min_length=1, max_length=120)
    texte: str = Field(max_length=TEXTE_MAX)


class Retour(BaseModel):
    model_config = ConfigDict(extra="ignore")

    format: str
    lecteur: str = Field(default="rédaction externe", max_length=120)
    document: dict
    sections: list[Section]


def _empreinte(*morceaux: str) -> str:
    return hashlib.sha256("\x00".join(morceaux).encode()).hexdigest()[:32]


def _lot(type_document: str, identifiant: str, titre: str, empreinte: str, taches: list[dict]) -> dict:
    return {
        "format": FORMAT,
        "genere_le": utcnow().isoformat(timespec="seconds"),
        "document": {"type": type_document, "id": identifiant, "titre": titre, "empreinte": empreinte},
        "reponse_attendue": CONSIGNE_DE_RETOUR,
        "taches": taches,
    }


def lire_retour(contenu: bytes, type_document: str, identifiant: str, empreinte: str) -> Retour:
    """Contrôle le fichier : le bon format, le bon document, dans le même état."""
    try:
        brut = json.loads(contenu.decode("utf-8-sig"))
        retour = Retour.model_validate(brut)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise ResultatInvalide("Ce fichier n'est pas un résultat de rédaction lisible.") from exc
    if retour.format != FORMAT:
        raise ResultatInvalide(f"Ce fichier n'est pas un résultat de rédaction ({FORMAT}).")
    if retour.document.get("type") != type_document or retour.document.get("id") != identifiant:
        raise ResultatInvalide("Ce résultat concerne un autre document.")
    if retour.document.get("empreinte") != empreinte:
        raise ResultatInvalide(
            "Le document a changé depuis l'export : exportez-le de nouveau pour que le texte "
            "corresponde à ce qu'il dit aujourd'hui."
        )
    return retour


# --- rapport -----------------------------------------------------------------


def _a_rediger(section: dict) -> bool:
    """Vide, ou proposée et jamais retouchée. Ce qu'un humain a écrit est à lui."""
    if not (section.get("contenu") or section.get("contenu_apres")):
        return True
    return section.get("origine") == rapports.ORIGINE_PROPOSEE


def _empreinte_rapport(rapport: Rapport) -> str:
    return _empreinte(rapports._contexte_textuel(rapport.donnees or {}, rapports.TRAME[0]))


def exporter_rapport(rapport: Rapport, trame: tuple) -> dict:
    contexte = rapports._contexte_textuel(rapport.donnees or {}, rapports.TRAME[0])
    consignes = {t.code: t for t in trame if not t.calculee and t.consigne}
    taches = [
        {
            "code": section["code"],
            "titre": section.get("titre", ""),
            "systeme": prompts.REDACTION_SYSTEM,
            "demande": prompts.redaction_user_prompt(consignes[section["code"]].consigne, contexte),
        }
        for section in rapport.sections or ()
        if section.get("code") in consignes and _a_rediger(section)
    ]
    return _lot("rapport", rapport.id, rapport.titre, _empreinte_rapport(rapport), taches)


def verser_rapport(rapport: Rapport, trame: tuple, contenu: bytes) -> dict:
    """Remplit les sections à rédiger. Rend le compte de ce qui a été fait."""
    retour = lire_retour(contenu, "rapport", rapport.id, _empreinte_rapport(rapport))
    redigeables = {t.code for t in trame if not t.calculee and t.consigne}
    textes = {s.code: s.texte for s in retour.sections}
    versees = gardees = vides = 0
    sections = []
    for section in rapport.sections or ():
        code = section.get("code")
        if code not in textes or code not in redigeables:
            sections.append(section)
            continue
        if not _a_rediger(section):
            gardees += 1
            sections.append(section)
            continue
        texte = prose.nettoyer(textes[code], section.get("titre", ""))
        if not texte:
            vides += 1
            sections.append(section)
            continue
        avant, apres = rapports.decouper_autour_du_tableau(texte)
        nouvelle = {**section, "contenu": avant, "origine": rapports.ORIGINE_PROPOSEE}
        nouvelle.pop("contenu_apres", None)
        if apres:
            nouvelle["contenu_apres"] = apres
        sections.append(nouvelle)
        versees += 1
    # Réaffectation complète : SQLAlchemy ne voit pas une liste JSON modifiée sur place.
    rapport.sections = sections
    return {
        "lecteur": retour.lecteur,
        "versees": versees,
        "gardees": gardees,
        "vides": vides,
        "inconnues": len(set(textes) - redigeables),
    }


# --- avis --------------------------------------------------------------------


def exporter_avis(
    poste: Poste, avis: Avis | None, mandat: Mandat | None, gabarit: str, reglages: Reglages | None
) -> dict:
    taches = redaction_avis.taches(poste, avis, mandat, gabarit, reglages)
    return _lot(
        "avis",
        poste.id,
        poste.intitule,
        _empreinte(*(t["demande"] for t in taches)),
        taches,
    )


def verser_avis(
    poste: Poste,
    avis: Avis | None,
    mandat: Mandat | None,
    gabarit: str,
    reglages: Reglages | None,
    contenu: bytes,
) -> tuple[str, str]:
    """Rend (texte de l'avis, lecteur). Rien n'est enregistré : l'éditeur le fait relire."""
    taches = redaction_avis.taches(poste, avis, mandat, gabarit, reglages)
    retour = lire_retour(contenu, "avis", poste.id, _empreinte(*(t["demande"] for t in taches)))
    textes: dict[str, str] = {}
    for tache in taches:
        brut = next((s.texte for s in retour.sections if s.code == tache["code"]), "")
        texte = prose.nettoyer(brut, tache["titre"])
        # Comme sur le serveur : un avis auquel il manque une section ressemble à
        # un avis fini, et se publierait comme tel.
        if not texte:
            raise ResultatInvalide(f"Il manque la section « {tache['titre']} ».")
        textes[tache["code"]] = texte
    return redaction_avis.assembler(poste, avis, mandat, gabarit, reglages, textes), retour.lecteur
