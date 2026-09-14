"""Ce que le candidat déclare lui-même, en plus de son dossier.

Un dépôt par le formulaire public ne portait que nom, prénom, adresse et
téléphone. Tout le reste — date de naissance, nationalité, diplômes,
expériences — n'existait qu'à l'intérieur du CV, et n'entrait dans la base
qu'après un dépouillement assisté puis sa confirmation par un humain.

Trois conséquences, toutes silencieuses :

**Les conditions éliminatoires étaient inertes.** L'âge ne s'évalue que si une
date de naissance est connue (`age is not None`), la nationalité que si le
dossier en porte une. Un poste ouvert « aux candidats de 45 ans au plus »
n'écartait donc personne au dépôt : tout le monde passait, et la condition ne
s'appliquait qu'aux dossiers déjà dépouillés. Deux candidats du même âge
pouvaient connaître deux sorts différents selon qu'on avait eu le temps de lire
leur CV.

**Les notes étaient fausses.** Formation, expérience générale et expérience
spécifique pèsent 27 des 30 points. Sans diplôme ni expérience en base, un
dossier fraîchement déposé valait 3 sur 30 — non parce que le candidat était
faible, mais parce que personne ne l'avait encore lu.

**Tout reposait sur le modèle.** Un quota épuisé, un CV scanné illisible, et le
dossier restait vide.

Demander ces éléments au candidat coûte quelques champs de formulaire et les
rend *déclarés* : `Provenance.DECLARE`, la même que son nom. C'est plus fiable
qu'une extraction — l'intéressé sait sa date de naissance — et cela n'exige
aucune relecture avant de compter. Le CV reste joint et fait toujours foi : le
dépouillement assisté vient compléter et confronter, il n'est plus le seul
chemin.
"""

from __future__ import annotations

import json
from datetime import date

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.domain.referentiel import NiveauDiplome, Sexe, normaliser_domaine
from app.models import Candidat, DiplomeCandidat, ExperienceCandidat, Provenance

# Un dossier déclaré reste un dossier : ces plafonds arrêtent un envoi absurde
# sans gêner personne. Le record connu au cabinet est de onze expériences.
MAX_DIPLOMES = 15
MAX_EXPERIENCES = 25
MAX_LISTE = 30


class DiplomeDeclare(BaseModel):
    intitule: str = Field(min_length=1, max_length=512)
    # Le N de BAC+N. Le candidat le choisit dans une liste : lui laisser saisir
    # « Master » obligerait à deviner, ce qui est précisément le travail qu'on
    # cherche à ne plus faire deviner.
    niveau: int = Field(ge=0, le=8)
    domaine: str = Field(min_length=1, max_length=255)
    etablissement: str | None = Field(default=None, max_length=255)
    annee: int | None = Field(default=None, ge=1940, le=2100)

    @field_validator("intitule", "domaine", "etablissement", mode="before")
    @classmethod
    def _nettoyer(cls, v: object) -> object:
        return " ".join(str(v).split()) if v is not None else None

    @field_validator("annee")
    @classmethod
    def _pas_dans_le_futur(cls, v: int | None) -> int | None:
        if v is not None and v > date.today().year:
            raise ValueError("une année d'obtention ne peut pas être à venir")
        return v


class ExperienceDeclaree(BaseModel):
    poste: str = Field(min_length=1, max_length=512)
    employeur: str = Field(min_length=1, max_length=512)
    debut: date
    # Absente = poste toujours occupé. La durée s'arrête alors à la clôture.
    fin: date | None = None
    domaines: list[str] = Field(default_factory=list, max_length=8)
    pays: str | None = Field(default=None, max_length=128)

    @field_validator("poste", "employeur", "pays", mode="before")
    @classmethod
    def _nettoyer(cls, v: object) -> object:
        return " ".join(str(v).split()) if v is not None else None

    @field_validator("domaines", mode="before")
    @classmethod
    def _en_liste(cls, v: object) -> object:
        if isinstance(v, str):
            return [m.strip() for m in v.split(",") if m.strip()]
        return v or []

    @model_validator(mode="after")
    def _periode_coherente(self) -> "ExperienceDeclaree":
        aujourdhui = date.today()
        if self.debut > aujourdhui:
            raise ValueError("une expérience ne peut pas commencer dans le futur")
        if self.fin is not None:
            if self.fin < self.debut:
                raise ValueError("la fin d'une expérience précède son début")
            if self.fin > aujourdhui:
                raise ValueError("une expérience ne peut pas se terminer dans le futur")
        return self

    @property
    def mois(self) -> int:
        fin = self.fin or date.today()
        return (fin.year - self.debut.year) * 12 + (fin.month - self.debut.month)


class ParcoursDeclare(BaseModel):
    """Ce que le candidat dit de lui-même, au-delà de son état civil."""

    diplomes: list[DiplomeDeclare] = Field(default_factory=list, max_length=MAX_DIPLOMES)
    experiences: list[ExperienceDeclaree] = Field(
        default_factory=list, max_length=MAX_EXPERIENCES
    )
    langues: list[str] = Field(default_factory=list, max_length=MAX_LISTE)
    certifications: list[str] = Field(default_factory=list, max_length=MAX_LISTE)
    formations_complementaires: list[str] = Field(default_factory=list, max_length=MAX_LISTE)

    @field_validator(
        "langues", "certifications", "formations_complementaires", mode="before"
    )
    @classmethod
    def _en_liste(cls, v: object) -> object:
        if isinstance(v, str):
            v = [m.strip() for m in v.split(",")]
        return [" ".join(str(m).split()) for m in (v or []) if str(m).strip()]


class DeclarationInvalide(ValueError):
    """Ce que le candidat a envoyé ne se lit pas. Le message lui est montré."""


def lire_parcours(brut: str | None) -> ParcoursDeclare:
    """Le parcours déclaré, transmis en JSON dans le formulaire multipart.

    Vide ou absent : un parcours vide, pas une erreur. Déclarer son parcours
    reste facultatif — le formulaire y invite, il ne l'impose pas, et un
    candidat pressé doit pouvoir déposer son CV et rien d'autre.
    """
    if not brut or not brut.strip():
        return ParcoursDeclare()
    try:
        charge = json.loads(brut)
    except json.JSONDecodeError as exc:
        raise DeclarationInvalide(
            "Le parcours déclaré n'a pas pu être lu. Rechargez la page et "
            "recommencez la saisie."
        ) from exc
    if not isinstance(charge, dict):
        raise DeclarationInvalide("Le parcours déclaré doit être un objet.")
    try:
        return ParcoursDeclare.model_validate(charge)
    except ValidationError as exc:
        raise DeclarationInvalide(_message_lisible(exc)) from exc


_CHAMPS_EN_FRANCAIS = {
    "diplomes": "diplôme",
    "experiences": "expérience",
    "intitule": "intitulé",
    "niveau": "niveau",
    "domaine": "domaine",
    "etablissement": "établissement",
    "annee": "année",
    "poste": "poste occupé",
    "employeur": "employeur",
    "debut": "date de début",
    "fin": "date de fin",
}


def _message_lisible(exc: ValidationError) -> str:
    """Un refus qu'un candidat peut corriger sans connaître le schéma.

    « experiences.1.debut : Input should be a valid date » ne dit rien à qui
    remplit un formulaire ; « 2ᵉ expérience, date de début : … » le renvoie au
    bon champ.
    """
    morceaux: list[str] = []
    for erreur in exc.errors()[:4]:
        chemin = [p for p in erreur["loc"] if p != "__root__"]
        libelle = []
        for element in chemin:
            if isinstance(element, int):
                libelle.append(f"n° {element + 1}")
            else:
                libelle.append(_CHAMPS_EN_FRANCAIS.get(str(element), str(element)))
        morceaux.append(f"{' '.join(libelle)} : {erreur['msg']}")
    return "Parcours déclaré incomplet ou incohérent — " + " ; ".join(morceaux)


def lire_nationalites(brut: str | None) -> list[str]:
    """« togolaise, ghanéenne » → deux entrées propres, sans doublon."""
    if not brut:
        return []
    vues: list[str] = []
    for morceau in brut.replace(";", ",").split(","):
        valeur = " ".join(morceau.split())
        if valeur and not any(v.casefold() == valeur.casefold() for v in vues):
            vues.append(valeur[:128])
    return vues[:5]


def lire_sexe(brut: str | None) -> Sexe | None:
    if not brut or not brut.strip():
        return None
    try:
        return Sexe(brut.strip().upper())
    except ValueError:
        # Un sexe non reconnu n'est pas une raison de refuser un dossier : il
        # ne sert qu'aux postes qui déclarent une condition, rares et justifiées.
        return None


def lire_date_naissance(brut: str | None) -> date | None:
    if not brut or not brut.strip():
        return None
    try:
        valeur = date.fromisoformat(brut.strip())
    except ValueError as exc:
        raise DeclarationInvalide(
            "La date de naissance doit être au format AAAA-MM-JJ."
        ) from exc
    aujourdhui = date.today()
    if valeur >= aujourdhui:
        raise DeclarationInvalide("La date de naissance doit être dans le passé.")
    if aujourdhui.year - valeur.year > 100:
        raise DeclarationInvalide("Vérifiez la date de naissance saisie.")
    if aujourdhui.year - valeur.year < 15:
        raise DeclarationInvalide(
            "Les candidatures sont réservées aux personnes de quinze ans révolus."
        )
    return valeur


def appliquer(candidat: Candidat, parcours: ParcoursDeclare) -> list[object]:
    """Pose le parcours déclaré sur le candidat et rend les lignes à ajouter.

    Tout est marqué `DECLARE` : c'est l'intéressé qui parle. Cette provenance
    compte sans relecture, là où une extraction force le dossier « à vérifier ».
    Le dépouillement assisté, lancé ensuite, ne l'écrasera pas — il ne remplace
    que ce qu'il a lui-même proposé.
    """
    lignes: list[object] = []

    for diplome in parcours.diplomes:
        lignes.append(
            DiplomeCandidat(
                candidat_id=candidat.id,
                intitule=diplome.intitule[:512],
                niveau=int(NiveauDiplome(diplome.niveau)),
                # Le même passage au référentiel que l'extraction : le barème
                # compare des domaines normalisés, et une déclaration qui
                # garderait sa casse et ses accents ne s'y retrouverait pas.
                domaine=normaliser_domaine(diplome.domaine)[:255],
                etablissement=diplome.etablissement or None,
                annee=diplome.annee,
                provenance=Provenance.DECLARE,
            )
        )

    for experience in parcours.experiences:
        lignes.append(
            ExperienceCandidat(
                candidat_id=candidat.id,
                poste=experience.poste[:512],
                employeur=experience.employeur[:512],
                debut=experience.debut,
                fin=experience.fin,
                domaines=[normaliser_domaine(d) for d in experience.domaines] or None,
                pays=experience.pays or None,
                provenance=Provenance.DECLARE,
            )
        )

    if parcours.langues:
        candidat.langues = [normaliser_domaine(l) for l in parcours.langues]
    if parcours.certifications:
        candidat.certifications = list(parcours.certifications)
    if parcours.formations_complementaires:
        candidat.formations_complementaires = list(parcours.formations_complementaires)

    return lignes
