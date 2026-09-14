"""Gestion des comptes depuis la ligne de commande.

Un compte créé par inscription libre est toujours RECRUITER, jamais ADMIN :
la page d'inscription est ouverte sur le réseau, et quiconque l'atteint ne doit
pas pouvoir se donner les droits sur les réglages du cabinet.

La contrepartie est qu'il faut bien un moyen de promouvoir quelqu'un. Ce moyen
est délibérément ici, et non dans l'interface : accorder les droits
d'administration suppose un accès à la machine où tourne l'application, ce qui
est exactement la garantie recherchée.

    python comptes.py                              liste les comptes
    python comptes.py promouvoir alice@exemple.tg  passe le compte en ADMIN
    python comptes.py retrograder bob@exemple.tg   repasse le compte en RECRUITER
    python comptes.py desactiver bob@exemple.tg    coupe l'accès sans effacer
    python comptes.py reactiver bob@exemple.tg

Ce que fait un ADMIN de plus qu'un RECRUITER : modifier les réglages du cabinet
— seuil par défaut, expurgation des données démographiques, inscription libre,
boîte de candidatures. Tout le reste du travail de recrutement est ouvert aux
deux rôles.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User, UserRole


async def _lister() -> int:
    async with SessionLocal() as db:
        comptes = list(
            (await db.execute(select(User).order_by(User.created_at))).scalars()
        )

    if not comptes:
        print("\n  Aucun compte. Lancez le démarrage habituel pour créer le compte")
        print("  administrateur défini dans .env.\n")
        return 0

    largeur = max(len(c.email) for c in comptes)
    print()
    print(f"  {'Compte'.ljust(largeur)}  Rôle       État")
    print(f"  {'-' * largeur}  ---------  --------")
    for compte in comptes:
        etat = "actif" if compte.is_active else "désactivé"
        print(f"  {compte.email.ljust(largeur)}  {compte.role.value.ljust(9)}  {etat}")

    admins = [c for c in comptes if c.role is UserRole.ADMIN and c.is_active]
    print()
    if admins:
        print(f"  {len(admins)} administrateur(s) : seuls eux peuvent modifier les réglages.")
    else:
        print("  ATTENTION : aucun administrateur actif. Personne ne peut modifier")
        print("  les réglages du cabinet. Promouvez un compte :")
        print("      python comptes.py promouvoir adresse@exemple.tg")
    print()
    return 0


async def _trouver(db, email: str) -> User | None:
    resultat = await db.execute(select(User).where(User.email == email.strip().lower()))
    return resultat.scalar_one_or_none()


async def _changer(email: str, *, role: UserRole | None = None, actif: bool | None = None) -> int:
    async with SessionLocal() as db:
        compte = await _trouver(db, email)
        if compte is None:
            print(f"\n  Aucun compte pour « {email} ».")
            print("  Liste des comptes :  python comptes.py\n")
            return 1

        # Retirer le dernier administrateur laisserait les réglages du cabinet
        # inaccessibles à tout le monde, sans moyen de revenir en arrière depuis
        # l'interface. On refuse plutôt que de le découvrir après coup.
        retire_les_droits = (role is not None and role is not UserRole.ADMIN) or actif is False
        if compte.role is UserRole.ADMIN and compte.is_active and retire_les_droits:
            autres = list(
                (
                    await db.execute(
                        select(User).where(
                            User.role == UserRole.ADMIN,
                            User.is_active.is_(True),
                            User.id != compte.id,
                        )
                    )
                ).scalars()
            )
            if not autres:
                print(f"\n  « {email} » est le dernier administrateur actif.")
                print("  Promouvez d'abord quelqu'un d'autre, sinon plus personne ne")
                print("  pourra modifier les réglages du cabinet.\n")
                return 1

        avant = (compte.role.value, compte.is_active)
        if role is not None:
            compte.role = role
        if actif is not None:
            compte.is_active = actif
        await db.commit()

        apres = (compte.role.value, compte.is_active)
        if avant == apres:
            print(f"\n  « {email} » était déjà dans cet état. Rien changé.\n")
            return 0

        etat = "actif" if compte.is_active else "désactivé"
        print(f"\n  « {email} » : {compte.role.value}, {etat}.")
        if role is UserRole.ADMIN:
            print("  Ce compte peut désormais modifier les réglages du cabinet.")
            print("  Il faut se déconnecter et se reconnecter pour que l'écran le voie.")
        print()
        return 0


def _usage() -> int:
    print(__doc__)
    return 1


async def principal(arguments: list[str]) -> int:
    if not arguments:
        return await _lister()

    action, *reste = arguments
    if action in {"-h", "--help", "aide"}:
        return _usage()
    if action == "lister":
        return await _lister()

    if not reste:
        print(f"\n  « {action} » attend une adresse email.\n")
        return _usage()

    email = reste[0]
    if action == "promouvoir":
        return await _changer(email, role=UserRole.ADMIN)
    if action == "retrograder":
        return await _changer(email, role=UserRole.RECRUITER)
    if action == "desactiver":
        return await _changer(email, actif=False)
    if action == "reactiver":
        return await _changer(email, actif=True)

    print(f"\n  Action inconnue : « {action} ».\n")
    return _usage()


if __name__ == "__main__":
    # Le script se lance depuis backend/ ; app.config trouve le .env à la
    # racine du dépôt quel que soit le répertoire courant.
    os.chdir(Path(__file__).resolve().parent)
    sys.exit(asyncio.run(principal(sys.argv[1:])))
