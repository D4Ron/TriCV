"""La fiche de poste fournie par le client : lecture, dépôt, et ce qu'elle nourrit.

Une fiche de poste synthétique, bâtie sur la trame qu'emploient les clients —
rubriques numérotées, étiquettes « clé : valeur », responsabilités groupées
sous des intitulés lettrés suivis d'« Indicateurs clés ».
"""

from __future__ import annotations

import io

import docx
import pytest

from app.llm.base import LLMProvider
from app.services import fiche_poste, redaction_avis
from app.services.parametres import FOURNISSEUR_IMAP, _defauts

from tests.test_api_recrutement import API, monter_poste

pytestmark = pytest.mark.anyio


FICHE = """FICHE DE POSTE
Responsable Administratif et Financier
1. Identification du poste
Intitulé du poste : Responsable Administratif et Financier
Direction : Administration et Finances
Hiérarchique : Directeur Général
Localisation : Kara, Togo
2. Mission du poste
Le Responsable Administratif et Financier garantit la fiabilité des comptes et pilote la trésorerie.
3. Finalités du poste
Garantir la fiabilité des états financiers.
Optimiser la trésorerie.
4. Principales responsabilités
A. Comptabilité et reporting
Superviser la tenue de la comptabilité.
Indicateurs clés
Délai de clôture mensuelle.
B. Trésorerie
Établir le plan de trésorerie.
Indicateurs clés
Écart de prévision.
6. Profil requis
Formation
Bac+5 en :
Finance
Comptabilité
Contrôle de gestion
Expérience
Minimum 8 années d'expérience professionnelle.
Au moins 4 ans à un poste d'encadrement dans les secteurs :
Industrie
Banque
7. Compétences techniques
Normes SYSCOHADA
Fiscalité
8. Compétences comportementales
Rigueur
Discrétion
"""


def _docx(texte: str) -> bytes:
    document = docx.Document()
    for ligne in texte.splitlines():
        document.add_paragraph(ligne)
    tampon = io.BytesIO()
    document.save(tampon)
    return tampon.getvalue()


# --- lecture de la trame -----------------------------------------------------


def test_la_trame_livre_chaque_rubrique_telle_qu_ecrite():
    lu = fiche_poste.lire_trame(FICHE)

    assert lu["intitule"] == "Responsable Administratif et Financier"
    assert lu["departement"] == "Administration et Finances"
    assert lu["rattachement"] == "Directeur Général"
    assert lu["localisation"] == "Kara, Togo"
    assert lu["description"].startswith("Le Responsable Administratif")
    assert lu["missions"] == [
        "Garantir la fiabilité des états financiers.",
        "Optimiser la trésorerie.",
    ]
    assert lu["niveau_min"] == 5
    assert lu["domaines_acceptes"] == ["Finance", "Comptabilité", "Contrôle de gestion"]
    assert lu["annees_experience_min"] == 8
    assert lu["annees_experience_specifique_min"] == 4
    assert lu["domaines_experience"] == ["Industrie", "Banque"]
    assert lu["competences_techniques"] == ["Normes SYSCOHADA", "Fiscalité"]
    assert lu["competences_comportementales"] == ["Rigueur", "Discrétion"]


def test_les_pieces_a_fournir_ferment_la_rubrique_precedente():
    """Sans rubrique « pièces », leur liste grossissait les savoir-être.

    La fiche qui finit par « PIÈCES À FOURNIR / Une lettre de motivation / Un
    CV détaillé » les voyait proposées comme compétences comportementales — et
    enregistrées telles quelles par qui ne relisait pas la fenêtre.
    """
    lu = fiche_poste.lire_trame(
        "Intitulé du poste : Comptable\n"
        "COMPÉTENCES COMPORTEMENTALES\n"
        "Rigueur\n"
        "Discrétion professionnelle\n"
        "PIÈCES À FOURNIR\n"
        "Une lettre de motivation\n"
        "Un CV détaillé\n"
        "Les copies des diplômes\n"
        "Les attestations de travail\n"
        "Une lettre de recommandation (facultatif)\n"
    )
    assert lu["competences_comportementales"] == ["Rigueur", "Discrétion professionnelle"]
    assert lu["pieces_requises"] == [
        "LETTRE_MOTIVATION",
        "CV",
        "COPIE_DIPLOMES",
        "ATTESTATIONS_TRAVAIL",
    ]
    assert lu["pieces_facultatives"] == ["LETTRE_RECOMMANDATION"]


def test_deux_pieces_au_choix_font_un_groupe_et_non_deux_exigences():
    """« La CNI ou le passeport » est un choix ; deux exigences éliminent.

    C'est la formule ordinaire des avis de la sous-région. Lue comme deux
    pièces obligatoires, elle écarte pour CNI manquante un candidat qui a joint
    son passeport — et l'écran affiche deux exigences, ce qui se relit comme une
    décision du cabinet plutôt que comme une erreur de lecture.
    """
    lu = fiche_poste.lire_trame(
        "Intitulé du poste : Comptable\n"
        "PIÈCES À FOURNIR\n"
        "Un CV détaillé\n"
        "Une copie de la carte nationale d'identité ou du passeport\n"
    )
    assert lu["pieces_requises"] == ["CV"]
    assert lu["groupes_pieces"] == [
        {
            "codes": ["PIECE_IDENTITE", "PASSEPORT"],
            "mode": "AU_MOINS_UNE",
            "libelle": "Une copie de la carte nationale d'identité ou du passeport",
        }
    ]


def test_deux_pieces_liees_par_et_restent_deux_exigences():
    """Deux pièces indissociables se disent aussi bien séparément."""
    lu = fiche_poste.lire_trame(
        "Intitulé du poste : Comptable\n"
        "PIÈCES À FOURNIR\n"
        "Les copies des diplômes et les attestations de travail\n"
    )
    assert lu["pieces_requises"] == ["COPIE_DIPLOMES", "ATTESTATIONS_TRAVAIL"]
    assert "groupes_pieces" not in lu


def test_une_piece_hors_nomenclature_est_ignoree():
    """Le vocabulaire des pièces est fermé : un code inventé n'exigerait rien."""
    lu = fiche_poste.lire_trame(
        "Intitulé du poste : Comptable\n"
        "DOSSIER DE CANDIDATURE\n"
        "Un CV\n"
        "Une fiche de renseignements du candidat\n"
        "Trois photos d'identité\n"
    )
    assert lu["pieces_requises"] == ["CV"]
    assert "pieces_facultatives" not in lu


def test_le_nombre_entre_parentheses_se_lit_comme_une_duree():
    """« huit (08) années » est la forme courante des avis de la sous-région."""
    lu = fiche_poste.lire_trame(
        "Profil requis\n"
        "Justifier d'au moins huit (08) années d'expérience professionnelle, dont "
        "cinq (05) années au moins dans une fonction comptable en entreprise "
        "industrielle.\n"
    )
    assert lu["annees_experience_min"] == 8
    assert lu["annees_experience_specifique_min"] == 5
    assert lu["domaines_experience"] == ["fonction comptable en entreprise industrielle"]


def test_les_deux_durees_d_une_meme_phrase_se_lisent_toutes_les_deux():
    """« 10 ans, dont 5 en X » : lire la spécifique ne doit pas perdre la générale."""
    lu = fiche_poste.lire_trame(
        "Profil requis\n"
        "Minimum 10 années d'expérience, dont 5 ans dans la passation des marchés\n"
    )
    assert lu["annees_experience_min"] == 10
    assert lu["annees_experience_specifique_min"] == 5
    assert lu["domaines_experience"] == ["passation des marchés"]


def test_les_responsabilites_groupees_se_resument_a_leurs_intitules():
    """Quarante lignes ne se publient pas : les intitulés lettrés suffisent."""
    lu = fiche_poste.lire_trame(FICHE)
    assert lu["responsabilites"] == ["Comptabilité et reporting", "Trésorerie"]


def test_sans_groupes_les_indicateurs_ne_deviennent_pas_des_responsabilites():
    lu = fiche_poste.lire_trame(
        "Intitulé du poste : Comptable\n"
        "Principales responsabilités\n"
        "- Tenir les journaux\n"
        "- Préparer les déclarations\n"
        "Indicateurs clés\n"
        "- Nombre de rejets\n"
    )
    assert lu["responsabilites"] == ["Tenir les journaux", "Préparer les déclarations"]


async def test_le_document_prime_sur_l_assistance(monkeypatch):
    """Une citation vaut mieux qu'une reformulation : le modèle ne comble que les vides."""

    class Lecteur(LLMProvider):
        async def analyze_cv(self, cv, fiche):  # pragma: no cover
            raise NotImplementedError

        async def structure_fiche(self, raw_text, language="fr"):  # pragma: no cover
            return []

        async def repondre_json(self, consigne, contexte, systeme=""):
            return {"intitule": "Titre réécrit", "nombre_a_pourvoir": 2, "langues_requises": "français, anglais"}

    monkeypatch.setattr(fiche_poste, "get_provider", lambda: Lecteur())
    proposition = await fiche_poste.proposer(FICHE)

    assert proposition.valeurs["intitule"] == "Responsable Administratif et Financier"
    assert proposition.origines["intitule"] == "document"
    assert proposition.valeurs["nombre_a_pourvoir"] == 2
    assert proposition.origines["nombre_a_pourvoir"] == "assistance"
    assert proposition.valeurs["langues_requises"] == ["français", "anglais"]


async def test_une_panne_de_l_assistance_laisse_la_lecture_du_document(monkeypatch):
    def en_panne():
        raise RuntimeError("fournisseur indisponible")

    monkeypatch.setattr(fiche_poste, "get_provider", en_panne)
    proposition = await fiche_poste.proposer(FICHE)
    assert proposition.valeurs["niveau_min"] == 5
    assert "assistance" not in proposition.origines.values()


async def test_une_experience_specifique_superieure_est_signalee():
    proposition = await fiche_poste.proposer(
        "Intitulé du poste : Chef de projet\n"
        "Profil requis\n"
        "Minimum 3 années d'expérience professionnelle.\n"
        "Dont 5 ans en gestion de projet.\n",
        avec_assistance=False,
    )
    assert proposition.avertissement and "5 an(s)" in proposition.avertissement


async def test_un_texte_trop_court_est_refuse():
    with pytest.raises(fiche_poste.FicheIllisible):
        await fiche_poste.proposer("Comptable", avec_assistance=False)


# --- API : lecture -----------------------------------------------------------


async def test_lire_une_fiche_word_propose_sans_rien_enregistrer(client, auth):
    reponse = await client.post(
        f"{API}/fiches/lecture",
        files={"fichier": ("fiche.docx", _docx(FICHE), "application/octet-stream")},
        data={"avec_assistance": "false"},
        headers=auth,
    )
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["valeurs"]["localisation"] == "Kara, Togo"
    assert corps["origines"]["niveau_min"] == "document"


async def test_lire_un_texte_colle(client, auth):
    reponse = await client.post(
        f"{API}/fiches/lecture",
        data={"texte": FICHE, "avec_assistance": "false"},
        headers=auth,
    )
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["valeurs"]["annees_experience_min"] == 8


async def test_un_fichier_qui_n_est_pas_une_fiche_est_refuse(client, auth):
    reponse = await client.post(
        f"{API}/fiches/lecture",
        files={"fichier": ("photo.png", b"\x89PNG\r\n\x1a\n" + b"0" * 100, "image/png")},
        headers=auth,
    )
    assert reponse.status_code == 422
    assert "ni un PDF ni un document Word" in reponse.json()["detail"]


async def test_lire_sans_rien_fournir_est_refuse(client, auth):
    reponse = await client.post(f"{API}/fiches/lecture", data={}, headers=auth)
    assert reponse.status_code == 422


# --- API : fiche jointe au poste ---------------------------------------------


async def test_joindre_telecharger_remplacer_puis_retirer_la_fiche(client, auth):
    poste_id = await monter_poste(client, auth)
    contenu = _docx(FICHE)

    reponse = await client.post(
        f"{API}/postes/{poste_id}/fiche",
        files={"fichier": ("Fiche RAF.docx", contenu, "application/octet-stream")},
        data={"proposer": "true", "avec_assistance": "false"},
        headers=auth,
    )
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["poste"]["fiche_nom_fichier"] == "Fiche RAF.docx"
    assert corps["poste"]["fiche_a_texte"] is True
    assert corps["proposition"]["valeurs"]["rattachement"] == "Directeur Général"

    telechargement = await client.get(f"{API}/postes/{poste_id}/fiche", headers=auth)
    assert telechargement.status_code == 200
    assert telechargement.content == contenu

    # Un texte collé remplace le document : l'ancien fichier ne doit plus
    # passer pour la source de l'avis.
    reponse = await client.post(
        f"{API}/postes/{poste_id}/fiche", data={"texte": FICHE}, headers=auth
    )
    assert reponse.status_code == 200
    assert reponse.json()["poste"]["fiche_nom_fichier"] is None
    assert reponse.json()["poste"]["fiche_a_texte"] is True
    assert (await client.get(f"{API}/postes/{poste_id}/fiche", headers=auth)).status_code == 404

    reponse = await client.delete(f"{API}/postes/{poste_id}/fiche", headers=auth)
    assert reponse.status_code == 204
    poste = (await client.get(f"{API}/postes/{poste_id}", headers=auth)).json()
    assert poste["fiche_a_texte"] is False


async def test_les_rubriques_de_presentation_s_enregistrent(client, auth):
    poste_id = await monter_poste(
        client,
        auth,
        localisation="Lomé, Togo",
        rattachement="Directeur Général",
        responsabilites=["Piloter la stratégie"],
        competences_techniques=["ERP"],
        competences_comportementales=["Leadership"],
    )
    poste = (await client.get(f"{API}/postes/{poste_id}", headers=auth)).json()
    assert poste["localisation"] == "Lomé, Togo"
    assert poste["responsabilites"] == ["Piloter la stratégie"]
    assert poste["a_completer"] is False


# --- poste « à compléter plus tard » ------------------------------------------


async def test_un_poste_a_completer_ne_publie_pas_son_avis(client, auth):
    poste_id = await monter_poste(client, auth, a_completer=True)
    avis = (await client.get(f"{API}/postes/{poste_id}/avis", headers=auth)).json()[0]

    refus = await client.post(f"{API}/avis/{avis['id']}/publier", headers=auth)
    assert refus.status_code == 409
    assert "pas encore complétée" in refus.json()["detail"]

    reponse = await client.patch(
        f"{API}/postes/{poste_id}", json={"a_completer": False}, headers=auth
    )
    assert reponse.status_code == 200
    assert reponse.json()["a_completer"] is False
    assert (await client.post(f"{API}/avis/{avis['id']}/publier", headers=auth)).status_code == 200


async def test_un_poste_se_cree_avec_son_seul_intitule(client, auth):
    reponse = await client.post(
        f"{API}/clients", json={"nom": "Client"}, headers=auth
    )
    mandat = await client.post(
        f"{API}/mandats",
        json={"client_id": reponse.json()["id"], "intitule": "Mandat"},
        headers=auth,
    )
    reponse = await client.post(
        f"{API}/mandats/{mandat.json()['id']}/postes",
        json={"intitule": "Comptable", "a_completer": True},
        headers=auth,
    )
    assert reponse.status_code == 201, reponse.text
    assert reponse.json()["a_completer"] is True


# --- rédaction de l'avis -------------------------------------------------------


def _reglages(**valeurs):
    reglages = _defauts()
    reglages.fournisseur_courriel = FOURNISSEUR_IMAP
    for cle, valeur in valeurs.items():
        setattr(reglages, cle, valeur)
    return reglages


async def test_le_brouillon_dit_ou_candidater_et_qui_ecrire(client, auth):
    poste_id = await monter_poste(client, auth, localisation="Lomé, Togo")
    await client.patch(
        f"{API}/settings",
        json={
            "url_publique": "https://recrutement.kapi.tg",
            "imap_user": "recrutement@kapi.tg",
            "contact_candidats": "aide@kapi.tg",
        },
        headers=auth,
    )
    avis = (await client.get(f"{API}/postes/{poste_id}/avis", headers=auth)).json()[0]
    await client.patch(f"{API}/avis/{avis['id']}", json={"reference": "RAF-2026"}, headers=auth)

    reponse = await client.post(
        f"{API}/postes/{poste_id}/avis/redaction",
        json={"avis_id": avis["id"], "avec_assistance": False},
        headers=auth,
    )
    assert reponse.status_code == 200, reponse.text
    texte = reponse.json()["texte"]
    assert "Lieu d'affectation : Lomé, Togo" in texte
    assert f"https://recrutement.kapi.tg/apply/{avis['cle_publique']}" in texte
    assert "recrutement@kapi.tg en indiquant « [RAF-2026] »" in texte
    assert "En cas de difficulté" in texte
    assert "aide@kapi.tg" in texte
    assert "https://recrutement.kapi.tg/aide" in texte
    # Aucune fiche jointe : l'écran doit le dire.
    assert "aucune fiche de poste" in reponse.json()["avertissement"]


async def test_la_redaction_assistee_lit_la_fiche_jointe(client, auth, monkeypatch):
    poste_id = await monter_poste(client, auth)
    await client.post(f"{API}/postes/{poste_id}/fiche", data={"texte": FICHE}, headers=auth)
    avis = (await client.get(f"{API}/postes/{poste_id}/avis", headers=auth)).json()[0]

    # L'avis se rédige section par section : on retient tous les appels, pas
    # le dernier. Un seul appel réclamant « l'avis complet » rendait les
    # responsabilités recopiées en puces ; c'est ce découpage qui les fait
    # rédiger.
    appels: list[dict] = []

    class Redacteur(LLMProvider):
        async def analyze_cv(self, cv, fiche):  # pragma: no cover
            raise NotImplementedError

        async def structure_fiche(self, raw_text, language="fr"):  # pragma: no cover
            return []

        async def rediger(
            self, consigne, contexte, systeme="", titre="", cloture=""
        ):
            appels.append(
                {
                    "consigne": consigne,
                    "contexte": contexte,
                    "titre": titre,
                    "cloture": cloture,
                }
            )
            return f"Texte proposé pour {titre}."

    monkeypatch.setattr(redaction_avis, "get_provider", lambda: Redacteur())
    reponse = await client.post(
        f"{API}/postes/{poste_id}/avis/redaction",
        json={"avis_id": avis["id"], "avec_assistance": True},
        headers=auth,
    )
    assert reponse.status_code == 200, reponse.text

    titres = [a["titre"] for a in appels]
    assert titres == ["Contexte", "Mission et responsabilités", "Profil recherché"]

    # La fiche est donnée en entier à chaque section : c'est elle qui dit ce
    # qu'est le poste.
    for appel in appels:
        assert "FICHE DE POSTE FOURNIE" in appel["contexte"]
        assert "garantit la fiabilité des comptes" in appel["contexte"]
        assert "seuls les « ÉLÉMENTS OPPOSABLES » font foi" in appel["consigne"]
        assert "cette section, et elle seule" in appel["cloture"]

    texte = reponse.json()["texte"]
    assert reponse.json()["propose"] is True
    # Les rubriques opposables sont écrites par le code, jamais par le modèle :
    # un lien mal retranscrit est une candidature perdue.
    assert "Texte proposé pour Mission et responsabilités." in texte
    assert "Dossier de candidature" in texte
    assert "Lettre de motivation" in texte


def test_la_section_d_aide_est_ajoutee_si_le_modele_l_oublie():
    reglages = _reglages(contact_candidats="aide@kapi.tg", url_publique="https://r.kapi.tg")
    texte = redaction_avis.completer_aide("AVIS\nCorps de l'avis.", reglages)
    assert "EN CAS DE DIFFICULTÉ" in texte
    assert "aide@kapi.tg" in texte
    assert "https://r.kapi.tg/aide" in texte


def test_la_section_d_aide_n_est_pas_dupliquee():
    reglages = _reglages(contact_candidats="aide@kapi.tg")
    texte = "AVIS\nEn cas de difficulté, écrivez à aide@kapi.tg."
    assert redaction_avis.completer_aide(texte, reglages) == texte


def test_le_contact_retombe_sur_la_boite_de_recrutement():
    assert _reglages(imap_user="recrutement@kapi.tg").contact == "recrutement@kapi.tg"
    assert (
        _reglages(imap_user="recrutement@kapi.tg", contact_candidats="aide@kapi.tg").contact
        == "aide@kapi.tg"
    )


def test_plusieurs_experiences_specifiques_figurent_dans_l_avis():
    """L'avis ne reprenait que l'exigence unique : les suivantes disparaissaient."""
    from app.models import Poste

    poste = Poste(
        intitule="Chef de projet",
        niveau_min=5,
        nombre_a_pourvoir=1,
        annees_experience_min=10,
        experiences_specifiques=[
            {"libelle": "passation des marchés", "domaines": [], "annees_min": 5},
            {"libelle": "gestion de projet", "domaines": [], "annees_min": 3},
        ],
    )
    texte = redaction_avis.faits(poste, None, None)
    assert "5 an(s) en passation des marchés" in texte
    assert "3 an(s) en gestion de projet" in texte


# --- page publique ---------------------------------------------------------------


async def test_la_page_publique_donne_le_lieu_et_le_contact(client, auth):
    poste_id = await monter_poste(
        client, auth, localisation="Lomé, Togo", responsabilites=["Piloter la stratégie"]
    )
    await client.patch(
        f"{API}/settings", json={"contact_candidats": "aide@kapi.tg"}, headers=auth
    )
    avis = (await client.get(f"{API}/postes/{poste_id}/avis", headers=auth)).json()[0]
    await client.post(f"{API}/avis/{avis['id']}/publier", headers=auth)

    public = (await client.get(f"{API}/public/avis/{avis['cle_publique']}")).json()
    assert public["localisation"] == "Lomé, Togo"
    assert public["responsabilites"] == ["Piloter la stratégie"]
    assert public["contact"] == "aide@kapi.tg"

    aide = (await client.get(f"{API}/public/aide")).json()
    assert aide["contact"] == "aide@kapi.tg"


async def test_une_adresse_de_contact_invalide_est_refusee(client, auth):
    reponse = await client.patch(
        f"{API}/settings", json={"contact_candidats": "pas une adresse"}, headers=auth
    )
    assert reponse.status_code == 422


def test_l_avis_dit_de_cliquer_sur_le_lien_et_d_envoyer_le_formulaire():
    from types import SimpleNamespace

    avis = SimpleNamespace(cle_publique="abc123", reference="")
    lignes = redaction_avis.modalites(avis, _reglages(url_publique="https://r.kapi.tg"))
    consigne = lignes[0]
    assert "cliquez sur le lien" in consigne
    assert "« Envoyer ma candidature »" in consigne
    assert consigne.endswith("https://r.kapi.tg/apply/abc123")
    assert "« Candidature enregistrée »" in lignes[1]


def test_le_lien_candidat_pointe_par_defaut_sur_le_domaine_du_cabinet():
    from app.config import Settings

    assert Settings.model_fields["url_publique"].default == "https://recrutement.kapiconsult.tg"
