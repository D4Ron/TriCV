"""L'IA en dernier recours pour ranger une pièce, et seulement là.

Les règles rangent presque tout, sans coût et sans que rien ne sorte. Ce qu'elles
ne savent pas nommer — un scan sans titre, un second « CV » — se montre au modèle
en un seul appel pour tout le dossier : le début de chaque pièce, expurgé, sans
nom de fichier. Une pièce d'identité ne part jamais, même rangée en « autre ».

Une pièce corrigée par un humain n'est jamais touchée, et une pièce déjà montrée
au modèle ne l'est pas deux fois.
"""

from __future__ import annotations

import logging

from app.domain.referentiel import PieceDossier as P
from app.llm.factory import get_provider
from app.models.recrutement import Candidature, PieceCandidature
from app.services import redaction
from app.services.decoupage import _plat

logger = logging.getLogger(__name__)

# Les types que le modèle peut proposer. L'état civil n'y figure pas : ces
# pièces ne doivent pas lui parvenir, il n'a donc pas à les nommer.
_TYPES = (
    P.CV, P.LETTRE_MOTIVATION, P.COPIE_DIPLOMES, P.ATTESTATIONS_TRAVAIL,
    P.LETTRE_RECOMMANDATION, P.AUTRE,
)
# Ce que les règles ont su nommer n'a rien d'incertain, même rangé en « autre ».
_AUTRES_NOMMES = frozenset({"Acte de naissance", "Attestation de formation", "Certificat de langue"})
_EXTRAIT = 700
_PIECES_PAR_APPEL = 6
_MIN_TEXTE = 40
_MARQUES_D_ETAT_CIVIL = (
    " ne le ", " nee le ", " nationalite ", " date de naissance ", " lieu de naissance ",
    " passeport ", " passport ", " carte nationale ", " carte d identite ", " casier judiciaire ",
    " date of birth ", " acte de naissance ",
)

CONSIGNE = (
    "Voici le début de plusieurs documents d'un dossier de candidature. Pour chacun, dites de "
    "quel type il s'agit. Répondez uniquement en JSON : "
    '{"pieces": [{"n": 1, "type": "CODE", "intitule": ""}]}. '
    "Les codes possibles sont : "
    + ", ".join(f"{t.value} ({t.libelle})" for t in _TYPES)
    + ". Pour AUTRE, « intitule » nomme le document en quelques mots. "
    'Si le texte ne permet pas de trancher, répondez "INCONNU" : ne devinez pas.'
)


def _ressemble_a_de_l_etat_civil(texte: str) -> bool:
    plat = _plat(texte)
    return "P<" in texte.replace(" ", "") or any(m in plat for m in _MARQUES_D_ETAT_CIVIL)


def pieces_incertaines(candidature: Candidature) -> list[PieceCandidature]:
    """Ce que les règles n'ont pas su nommer, et qui peut sortir."""
    incertaines: list[PieceCandidature] = []
    cv_vu = False
    for piece in sorted(candidature.pieces, key=lambda p: p.created_at):
        premier_cv = piece.type_piece == P.CV.value and not cv_vu
        cv_vu = cv_vu or piece.type_piece == P.CV.value
        if premier_cv or piece.type_source:
            continue
        texte = piece.texte_extrait or ""
        if len(texte.strip()) < _MIN_TEXTE or _ressemble_a_de_l_etat_civil(texte):
            continue
        second_cv = piece.type_piece == P.CV.value
        autre_inconnu = piece.type_piece == P.AUTRE.value and piece.intitule_libre not in _AUTRES_NOMMES
        if second_cv or autre_inconnu:
            incertaines.append(piece)
    return incertaines[:_PIECES_PAR_APPEL]


async def classer(candidature: Candidature) -> int:
    """Range ce qui est incertain. Rend le nombre de pièces changées.

    Ne commit pas. Laisse passer les erreurs du fournisseur : la file sait quoi
    en faire.
    """
    pieces = pieces_incertaines(candidature)
    if not pieces:
        return 0

    candidat = candidature.candidat
    connus = redaction.KnownValues(
        full_name=f"{candidat.nom} {candidat.prenom}".strip(),
        email=candidat.email,
        phone=candidat.telephone,
    )
    blocs: list[str] = []
    for numero, piece in enumerate(pieces, start=1):
        expurge = await redaction.redact(
            (piece.texte_extrait or "")[:_EXTRAIT], connus, redact_demographics=True
        )
        blocs.append(f"--- Document {numero} ---\n{expurge.text}")

    reponse = await get_provider().repondre_json(CONSIGNE, "\n\n".join(blocs))
    valides = {t.value for t in _TYPES}
    changees = 0
    for entree in reponse.get("pieces") or []:
        if not isinstance(entree, dict):
            continue
        try:
            piece = pieces[int(entree.get("n")) - 1]
        except (TypeError, ValueError, IndexError):
            continue
        code = str(entree.get("type") or "").strip()
        if code not in valides:
            continue
        intitule = str(entree.get("intitule") or "").strip()[:255]
        if code != piece.type_piece or (code == P.AUTRE.value and intitule):
            piece.type_piece = code
            piece.intitule_libre = (intitule or piece.intitule_libre) if code == P.AUTRE.value else None
            changees += 1
    # Montrées une fois : même sans réponse nette, on ne les renvoie pas.
    for piece in pieces:
        piece.type_source = "ia"
    return changees
