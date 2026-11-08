"""Ce qui part au modèle : chaque document à sa place, l'état civil à l'écart, rien qui nomme.

Tout y est inventé. Les cas reprennent des formes vues dans de vrais dossiers :
un PDF qui met huit attestations bout à bout, un passeport rangé en CV, un nom
que la fiche découpe autrement que les pièces.
"""

from __future__ import annotations

from app.domain.referentiel import PieceDossier as P
from app.services import decoupage, depouillement
from app.services.redaction import KnownValues, redact_sync


def expurge(texte: str, nom: str = "KOFFI Ama") -> str:
    return redact_sync(texte, KnownValues(full_name=nom), redact_demographics=True).text


# --- découpage d'une pièce en documents -----------------------------------------


def attestation(employeur: str, poste: str, annees: str) -> str:
    return (
        f"{employeur} SA\nZone portuaire, Lomé\n\nCERTIFICAT DE TRAVAIL\n\n"
        f"Nous soussignés, {employeur} SA, certifions que la nommée a été employée en qualité de "
        f"{poste} du {annees}.\nEn foi de quoi le présent certificat est délivré pour servir et valoir "
        "ce que de droit.\nLe Directeur général\n\n"
    )


def test_huit_attestations_d_un_meme_fichier_deviennent_huit_documents():
    texte = "".join(attestation(f"Société {n}", f"logisticien {n}", f"0{n}/01/2010 au 0{n}/01/2011") for n in range(1, 9))

    documents = decoupage.documents_du_texte(texte, P.ATTESTATIONS_TRAVAIL.value)

    assert len(documents) == 8
    assert {t for t, _ in documents} == {P.ATTESTATIONS_TRAVAIL.value}


def test_toutes_les_attestations_arrivent_au_modele():
    texte = "".join(attestation(f"Société {n}", f"logisticien {n}", f"0{n}/01/2010 au 0{n}/01/2011") for n in range(1, 9))

    envoi = depouillement.composer_pour_ia([(P.CV.value, "x" * 20_000), (P.ATTESTATIONS_TRAVAIL.value, texte)])

    for n in range(1, 9):
        assert f"logisticien {n}" in envoi
    assert len(envoi) < 40_000


def test_un_cv_ne_se_coupe_pas_sur_sa_rubrique_formation():
    cv = (
        "PROFIL\nLogisticien depuis dix ans.\n\nEXPÉRIENCE PROFESSIONNELLE\n2015 - 2020 : Chef de quai, Port Sec\n"
        "Encadrement de vingt agents et suivi des flux de conteneurs vers l'hinterland.\n\n"
        "FORMATION\nMASTER\nMaster en logistique, Université de Lomé, 2014\n\nLANGUES\nFrançais, anglais\n"
    )

    documents = decoupage.documents_du_texte(cv, P.CV.value)

    assert len(documents) == 1
    assert documents[0][0] == P.CV.value


def test_un_diplome_ne_garde_que_son_en_tete():
    programme = "Mastère spécialisé en direction logistique\nUniversité privée\nLe diplôme est conféré.\n" + (
        "Module : gestion des achats, prévision de la demande, entreposage.\n" * 400
    )

    envoi = depouillement.composer_pour_ia([(P.COPIE_DIPLOMES.value, programme)])

    assert "Mastère spécialisé" in envoi
    assert len(envoi) < 1_200


# --- l'état civil ne part pas --------------------------------------------------


PASSEPORT = (
    "RÉPUBLIQUE TOGOLAISE\nPASSEPORT\nType P Code TGO\nNom KOFFI\nPrénoms AMA\n"
    "P<TGOKOFFI<<AMA<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<\nAB1234567<8TGO8001011F3001012<<<<<<<<<<<<<<06\n"
)
CARTE_DE_SEJOUR = (
    "RÉPUBLIQUE DE GUINÉE\nTRAVAIL JUSTICE SOLIDARITÉ\nCARTE DE SÉJOUR AFRIQUE NON CEDEAO\n"
    "Nom: KOFFI\nPrénom(s): Ama\nNé(e): 01/01/1980\nProfession: DIRECTRICE LOGISTIQUE\nDélivrée le: 18/05/2026\n"
    "Expire le: 18/05/2027\n"
)
PERMIS = "RÉPUBLIQUE TOGOLAISE\nNUMERO 000 111 222\nNom KOFFI\nPRENOM AMA\nDATE DE DELIVRANCE 18-01-2023\n"


def test_une_piece_d_identite_rangee_en_cv_ne_part_pas():
    cv = "EXPÉRIENCE PROFESSIONNELLE\n2015 - 2020 : Chef de quai, Port Sec\nFORMATION\n2014 : Master en logistique\n"

    envoi = depouillement.composer_pour_ia(
        [(P.CV.value, PASSEPORT), (P.CV.value, cv), (P.ATTESTATIONS_TRAVAIL.value, CARTE_DE_SEJOUR),
         (P.COPIE_DIPLOMES.value, PERMIS)]
    )

    assert "Chef de quai" in envoi
    for fragment in ("P<TGO", "AB1234567", "SÉJOUR", "Expire", "000 111 222"):
        assert fragment not in envoi


def test_une_attestation_avec_nom_et_prenom_n_est_pas_une_carte():
    texte = (
        "ATTESTATION DE TRAVAIL\nNom : KOFFI\nPrénom : Ama\nNous attestons que l'intéressée est employée "
        "en qualité de cheffe de quai.\nDélivrée le 02/03/2024\n"
    )

    assert decoupage.type_de_page(texte)[0] == P.ATTESTATIONS_TRAVAIL.value


def test_un_cv_qui_mentionne_son_permis_reste_un_cv():
    cv = (
        "KOFFI Ama\nPermis de conduire : catégorie B\n\nEXPÉRIENCE PROFESSIONNELLE\n2015 - 2020 : Chef de quai\n"
        "FORMATION\n2014 : Master en logistique\nLANGUES\nFrançais\n"
    )

    assert decoupage.type_de_page(cv)[0] == P.CV.value


# --- expurgation ---------------------------------------------------------------


def test_un_nom_decoupe_autrement_sur_la_fiche_est_reconnu():
    texte = "Je soussigné atteste que Monsieur AGBOKLA Yaovi a été employé."

    assert "AGBO" not in expurge(texte, "AG BOKLA Ya Ovi")
    assert "Yaovi" not in expurge(texte, "AG BOKLA Ya Ovi")


def test_un_nom_a_apostrophe_ou_espace_est_reconnu_sous_toutes_ses_graphies():
    for forme in ("N'DOSSOU Afi", "N’DOSSOU Afi", "NDOSSOU Afi", "N DOSSOU Afi"):
        assert "DOSSOU" not in expurge(forme, "N’DOSSOU Afi"), forme


def test_un_nom_en_lettres_espacees_est_reconnu():
    assert "SSOU" not in expurge("Certificat décerné à DO S SOU Afi", "DOSSOU Afi")


def test_le_nom_d_epouse_part_aussi():
    assert "AMEGAN" not in expurge("Madame KOFFI Ama épse AMEGAN a occupé le poste")


def test_date_et_lieu_de_naissance_sous_leurs_formes_courantes():
    for texte, absent in (
        ("Né le 3 Mai 1979 à Aného (Préf. des Lacs)", ("1979", "Aného")),
        ("Born in ACCRA, Ghana, on 11 March 1979, certifying", ("1979", "ACCRA")),
        ("Date de naissance : le 14/02/1990\nLieu de naissance : Tsévié (TOGO)", ("1990", "Tsévié")),
        ("Né(e): 03/05/1979", ("1979",)),
    ):
        sortie = expurge(texte)
        for mot in absent:
            assert mot not in sortie, (texte, sortie)


def test_une_adresse_email_coupee_ou_mal_lue_part_quand_meme():
    for texte in ("ama.koffi\n@gmail.com", "Courriel : ama_et 73@yahoo de", "Email : ama3@gma"):
        assert "@" not in expurge(texte), texte


def test_les_referents_sont_masques_mais_pas_les_employeurs():
    texte = (
        "RÉFÉRENCES\nAlain DOSSEH\nEx-DGA, Groupe SOLARIS\nM. KODJO Yao — Directeur\n"
        "Nov. 2020 – Sept. 2022\nResponsable logistique\nGroupe SOL-SOLARIS — Lomé"
    )

    sortie = expurge(texte)

    assert "DOSSEH" not in sortie and "KODJO" not in sortie
    assert "Groupe SOLARIS" in sortie
    assert "Groupe SOL-SOLARIS" in sortie


def test_les_mots_du_metier_ne_sont_plus_pris_pour_des_identifiants():
    texte = (
        "Conception des processus de planification, une expérience significative.\n"
        "Dépannage : 22 10 00 00\nCoûts d'entreposage\n10. Systèmes d'information\n"
        "Manager avec 11 ans en industrie."
    )

    sortie = expurge(texte)

    assert "planification" in sortie and "significative" in sortie
    assert "[AGE" not in sortie
    assert "11 ans en industrie" in sortie


def test_un_vrai_numero_reste_masque():
    sortie = expurge("NIF : 1000999111 ; passeport N° ZX904417")

    assert "1000999111" not in sortie and "ZX904417" not in sortie
