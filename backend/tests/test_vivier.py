"""Le vivier : ce que la purge préserve doit rester trouvable.

Le test central est `test_un_profil_reste_trouvable_apres_purge` : c'est la
promesse faite au cabinet — supprimer les CV d'un mandat terminé ne fait pas
disparaître les personnes. Les autres vérifient que les filtres portent sur ce
qu'ils annoncent, et que rien de sensible ne se consulte sans laisser de trace.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.domain.referentiel import PieceDossier, Sexe
from app.models import (
    Avis,
    Candidat,
    Candidature,
    Client,
    DiplomeCandidat,
    ExperienceCandidat,
    Mandat,
    PieceCandidature,
    Poste,
    Provenance,
)

pytestmark = pytest.mark.anyio

API = "/api/v1"
PDF = b"%PDF-1.4\n" + b"0" * 400


async def monter_vivier() -> dict[str, str]:
    """Trois profils contrastés, rattachés à un mandat réel."""
    async with SessionLocal() as db:
        client = Client(nom="CHU de Lomé")
        db.add(client)
        await db.flush()
        mandat = Mandat(client_id=client.id, intitule="Cadres hospitaliers")
        db.add(mandat)
        await db.flush()
        poste = Poste(
            mandat_id=mandat.id,
            intitule="Directeur financier",
            niveau_min=4,
            pieces_requises=[PieceDossier.CV.value],
        )
        db.add(poste)
        await db.flush()
        db.add(Avis(poste_id=poste.id, reference="AVIS-2026-001"))

        identifiants: dict[str, str] = {"poste": poste.id, "mandat": mandat.id}

        # 1. Contrôleuse de gestion confirmée, état civil relu par un humain.
        amina = Candidat(
            nom="Kodjo",
            prenom="Amina",
            email="amina.kodjo@example.com",
            telephone="+228 90 00 00 01",
            date_naissance=date(1986, 3, 12),
            sexe=Sexe.FEMININ,
            nationalites=["Togolaise"],
            provenance=Provenance.VERIFIE_RH,
        )
        db.add(amina)
        await db.flush()
        db.add(
            DiplomeCandidat(
                candidat_id=amina.id,
                intitule="Master en contrôle de gestion",
                niveau=5,
                domaine="gestion financière",
                etablissement="Université de Lomé",
                annee=2010,
                provenance=Provenance.VERIFIE_RH,
            )
        )
        db.add(
            ExperienceCandidat(
                candidat_id=amina.id,
                poste="Contrôleuse de gestion",
                employeur="Groupe Sarakawa",
                debut=date(2011, 1, 1),
                fin=date(2024, 1, 1),
                domaines=["gestion financière"],
                provenance=Provenance.VERIFIE_RH,
            )
        )
        identifiants["amina"] = amina.id

        # 2. Jeune diplômé, peu d'expérience, nationalité différente.
        kofi = Candidat(
            nom="Mensah",
            prenom="Kofi",
            email="kofi.mensah@example.com",
            date_naissance=date(2000, 6, 1),
            sexe=Sexe.MASCULIN,
            nationalites=["Ghanéenne"],
            provenance=Provenance.DECLARE,
        )
        db.add(kofi)
        await db.flush()
        db.add(
            DiplomeCandidat(
                candidat_id=kofi.id,
                intitule="Licence en informatique",
                niveau=3,
                domaine="informatique",
                provenance=Provenance.DECLARE,
            )
        )
        db.add(
            ExperienceCandidat(
                candidat_id=kofi.id,
                poste="Développeur",
                employeur="Startup",
                debut=date.today() - timedelta(days=365),
                fin=None,
                provenance=Provenance.DECLARE,
            )
        )
        identifiants["kofi"] = kofi.id

        # 3. Dossier arrivé par email : identité seulement devinée.
        devine = Candidat(nom="CV_Dupont", prenom="", provenance=Provenance.EXTRAIT_IA)
        db.add(devine)
        await db.flush()
        identifiants["devine"] = devine.id

        for candidat_id in (amina.id, kofi.id, devine.id):
            candidature = Candidature(poste_id=poste.id, candidat_id=candidat_id)
            db.add(candidature)
            await db.flush()
            db.add(
                PieceCandidature(
                    candidature_id=candidature.id,
                    type_piece=PieceDossier.CV.value,
                    nom_fichier="cv.pdf",
                    chemin_stockage=f"cv/{candidat_id}.pdf",
                    taille_octets=len(PDF),
                )
            )

        await db.commit()
    return identifiants


async def test_le_vivier_liste_les_profils_connus(client, auth):
    await monter_vivier()

    corps = (await client.get(f"{API}/vivier", headers=auth)).json()
    assert corps["total"] == 3
    noms = {f"{i['prenom']} {i['nom']}".strip() for i in corps["items"]}
    assert "Amina Kodjo" in noms


async def test_les_chiffres_du_profil_sont_calcules_et_non_stockes(client, auth):
    ids = await monter_vivier()

    corps = (await client.get(f"{API}/vivier?recherche=Kodjo", headers=auth)).json()
    assert corps["total"] == 1
    profil = corps["items"][0]

    assert profil["id"] == ids["amina"]
    assert profil["niveau_max"] == 5
    assert profil["niveau_libelle"]
    # 2011 → 2024 : treize ans, arrondis au dixième.
    assert 12.5 <= profil["annees_experience"] <= 13.5
    assert profil["age"] and profil["age"] >= 39
    assert profil["dernier_employeur"] == "Groupe Sarakawa"
    assert profil["nombre_candidatures"] == 1


async def test_la_provenance_suit_le_profil(client, auth):
    """Une identité devinée ne doit pas s'afficher comme un fait établi."""
    await monter_vivier()

    corps = (await client.get(f"{API}/vivier?recherche=Dupont", headers=auth)).json()
    assert corps["items"][0]["provenance"] == "EXTRAIT_IA"
    assert corps["items"][0]["verifie"] is False


async def test_recherche_par_metier_et_non_par_nom(client, auth):
    """« contrôle de gestion » n'est dans aucun nom : la recherche va au parcours."""
    await monter_vivier()

    par_diplome = (
        await client.get(f"{API}/vivier?recherche=contrôle de gestion", headers=auth)
    ).json()
    assert [i["nom"] for i in par_diplome["items"]] == ["Kodjo"]

    par_employeur = (await client.get(f"{API}/vivier?recherche=Sarakawa", headers=auth)).json()
    assert [i["nom"] for i in par_employeur["items"]] == ["Kodjo"]


async def test_filtre_par_niveau_et_par_experience(client, auth):
    await monter_vivier()

    niveau = (await client.get(f"{API}/vivier?niveau_min=5", headers=auth)).json()
    assert [i["nom"] for i in niveau["items"]] == ["Kodjo"]

    experience = (
        await client.get(f"{API}/vivier?annees_experience_min=10", headers=auth)
    ).json()
    assert [i["nom"] for i in experience["items"]] == ["Kodjo"]

    # Le jeune diplômé reste trouvable avec un critère à sa mesure.
    debutants = (await client.get(f"{API}/vivier?niveau_min=3", headers=auth)).json()
    assert {i["nom"] for i in debutants["items"]} == {"Kodjo", "Mensah"}


async def test_filtre_par_attributs_sensibles(client, auth):
    await monter_vivier()

    femmes = (await client.get(f"{API}/vivier?sexe=F", headers=auth)).json()
    assert [i["nom"] for i in femmes["items"]] == ["Kodjo"]

    togolaises = (await client.get(f"{API}/vivier?nationalite=togo", headers=auth)).json()
    assert [i["nom"] for i in togolaises["items"]] == ["Kodjo"]

    jeunes = (await client.get(f"{API}/vivier?age_max=30", headers=auth)).json()
    assert [i["nom"] for i in jeunes["items"]] == ["Mensah"]


async def test_une_recherche_sur_attribut_sensible_est_journalisee(client, auth):
    """Filtrer sur le sexe ou la nationalité est légitime, mais pas anodin."""
    from app.models import AuditLog

    await monter_vivier()
    await client.get(f"{API}/vivier?sexe=F", headers=auth)

    async with SessionLocal() as db:
        actions = [a.action for a in (await db.execute(select(AuditLog))).scalars()]
    assert "vivier.recherche_sensible" in actions


async def test_une_recherche_ordinaire_ne_l_est_pas(client, auth):
    """Sans quoi le journal se remplirait de bruit et perdrait sa valeur."""
    from app.models import AuditLog

    await monter_vivier()
    await client.get(f"{API}/vivier?recherche=Kodjo", headers=auth)

    async with SessionLocal() as db:
        actions = [a.action for a in (await db.execute(select(AuditLog))).scalars()]
    assert "vivier.recherche_sensible" not in actions


async def test_un_profil_reste_trouvable_apres_purge(client, auth):
    """Le coeur de la promesse : purger les fichiers ne perd pas les personnes."""
    ids = await monter_vivier()

    avant = (await client.get(f"{API}/vivier/{ids['amina']}", headers=auth)).json()
    assert avant["pieces_conservees"] == 1
    assert avant["pieces_purgees"] == 0

    await client.post(f"{API}/mandats/{ids['mandat']}/archiver", headers=auth)
    purge = await client.post(f"{API}/mandats/{ids['mandat']}/purge", headers=auth)
    assert purge.status_code == 200, purge.text

    apres = (await client.get(f"{API}/vivier/{ids['amina']}", headers=auth)).json()

    # Le fichier est parti, la personne est entière.
    assert apres["pieces_conservees"] == 0
    assert apres["pieces_purgees"] == 1
    assert apres["nom"] == "Kodjo"
    assert apres["email"] == "amina.kodjo@example.com"
    assert apres["telephone"] == "+228 90 00 00 01"
    assert apres["sexe"] == "F"
    assert apres["age"] == avant["age"]
    assert apres["nationalites"] == ["Togolaise"]
    assert apres["annees_experience"] == avant["annees_experience"]
    assert [d["intitule"] for d in apres["diplomes"]] == ["Master en contrôle de gestion"]
    assert [e["employeur"] for e in apres["experiences"]] == ["Groupe Sarakawa"]

    # Et la recherche par métier fonctionne toujours.
    trouve = (
        await client.get(f"{API}/vivier?recherche=contrôle de gestion", headers=auth)
    ).json()
    assert trouve["total"] == 1


async def test_le_profil_porte_l_historique_des_candidatures(client, auth):
    ids = await monter_vivier()

    profil = (await client.get(f"{API}/vivier/{ids['amina']}", headers=auth)).json()
    assert len(profil["historique"]) == 1
    ligne = profil["historique"][0]
    assert ligne["poste"] == "Directeur financier"
    assert ligne["client"] == "CHU de Lomé"
    assert ligne["mandat"] == "Cadres hospitaliers"


async def test_une_personne_qui_a_postule_deux_fois_apparait_une_fois(client, auth):
    """Chaque candidature crée son propre état civil ; le vivier les réunit.

    Sans ce regroupement, quelqu'un ayant postulé à cinq avis occuperait cinq
    lignes, et la page manquerait son but : retrouver *une personne*.
    """
    ids = await monter_vivier()

    async with SessionLocal() as db:
        poste = await db.get(Poste, ids["poste"])
        # Second avis, second dossier, même personne : même email, état civil
        # ressaisi plus sommairement et cette fois seulement déclaré.
        autre_poste = Poste(
            mandat_id=poste.mandat_id, intitule="Directeur administratif", niveau_min=4
        )
        db.add(autre_poste)
        await db.flush()

        bis = Candidat(
            nom="KODJO",
            prenom="amina",
            email="Amina.Kodjo@example.com",  # même adresse, autre casse
            provenance=Provenance.DECLARE,
        )
        db.add(bis)
        await db.flush()
        db.add(
            DiplomeCandidat(
                candidat_id=bis.id,
                intitule="Certificat en audit",
                niveau=4,
                domaine="audit",
                provenance=Provenance.DECLARE,
            )
        )
        db.add(Candidature(poste_id=autre_poste.id, candidat_id=bis.id))
        await db.commit()

    corps = (await client.get(f"{API}/vivier?recherche=Kodjo", headers=auth)).json()
    assert corps["total"] == 1, "une personne, une ligne"

    profil = corps["items"][0]
    # L'identité affichée est la plus solide des deux, pas la dernière arrivée.
    assert profil["nom"] == "Kodjo"
    assert profil["provenance"] == "VERIFIE_RH"
    assert profil["nombre_candidatures"] == 2

    # Et le détail réunit les deux dossiers et les deux diplômes.
    complet = (await client.get(f"{API}/vivier/{profil['id']}", headers=auth)).json()
    assert len(complet["historique"]) == 2
    assert {d["intitule"] for d in complet["diplomes"]} == {
        "Master en contrôle de gestion",
        "Certificat en audit",
    }


async def test_le_meme_diplome_ressaisi_n_apparait_pas_deux_fois(client, auth):
    ids = await monter_vivier()

    async with SessionLocal() as db:
        bis = Candidat(
            nom="Kodjo",
            prenom="Amina",
            email="amina.kodjo@example.com",
            provenance=Provenance.DECLARE,
        )
        db.add(bis)
        await db.flush()
        db.add(
            DiplomeCandidat(
                candidat_id=bis.id,
                intitule="Master en contrôle de gestion",
                niveau=5,
                domaine="gestion financière",
                annee=2010,
                provenance=Provenance.DECLARE,
            )
        )
        db.add(Candidature(poste_id=ids["poste"], candidat_id=bis.id))
        await db.commit()

    complet = (await client.get(f"{API}/vivier/{ids['amina']}", headers=auth)).json()
    assert [d["intitule"] for d in complet["diplomes"]] == ["Master en contrôle de gestion"]


async def test_un_profil_inconnu_renvoie_404(client, auth):
    reponse = await client.get(f"{API}/vivier/inexistant", headers=auth)
    assert reponse.status_code == 404


async def test_le_vivier_exige_un_compte(client):
    """Coordonnées, âge, sexe, nationalité : jamais accessibles sans jeton."""
    assert (await client.get(f"{API}/vivier")).status_code == 401
