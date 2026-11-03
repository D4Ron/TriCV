"""Lire les pièces sans IA : le nom, le découpage d'un PDF fusionné, le parcours.

Constaté en production : des noms inversés, écrits en minuscules, ou pris à
« Yahoo! » ; des dossiers entiers fusionnés en un PDF et comptés comme un CV ;
des scans sans texte ; une lecture qui ne donnait rien quand le fournisseur
d'IA gratuit saturait. Tout est fictif.
"""

from __future__ import annotations

import io
from datetime import date, datetime

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate
from sqlalchemy import select

from app.db import SessionLocal
from app.domain.referentiel import PieceDossier as P
from app.models import Candidat, DiplomeCandidat, ExperienceCandidat, PieceCandidature
from app.services import courriel, decoupage, extraction, identite, lecture_locale

pytestmark = pytest.mark.anyio


def pdf(*pages: str) -> bytes:
    """Un PDF texte, une page par argument, une ligne par paragraphe."""
    style = getSampleStyleSheet()["Normal"]
    elements = []
    for numero, page in enumerate(pages):
        if numero:
            elements.append(PageBreak())
        elements.extend(Paragraph(l, style) for l in page.strip().splitlines() if l.strip())
    tampon = io.BytesIO()
    SimpleDocTemplate(tampon, pagesize=A4).build(elements)
    return tampon.getvalue()


LETTRE = """Lomé, le 2 novembre 2026
Objet : candidature au poste de comptable
Madame,
Titulaire d'une licence en comptabilité, je vous adresse ma candidature pour le poste proposé.
Veuillez agréer, Madame, l'expression de mes salutations distinguées.
"""
CV_P1 = """KOUMA Essi Afi
essi.kouma92@example.fr
PROFIL
Comptable avec six ans d'expérience.
EXPÉRIENCES PROFESSIONNELLES
Comptable principale — Société Togolaise de Distribution SA
Lomé — Mars 2022 – à ce jour
Assistante comptable — Cabinet Fidex Conseil
Lomé — Janv. 2019 – Févr. 2022
"""
CV_P2 = """Saisie des pièces et rapprochements bancaires sur trois exercices successifs.
FORMATION
2018 : Licence en Comptabilité et Finance, Université de Lomé
LANGUES
Français, Anglais, Éwé
"""
ATTESTATION = """ATTESTATION DE TRAVAIL
Je soussigné, Directeur du Cabinet Fidex Conseil, certifie que Mademoiselle KOUMA Essi Afi
a travaillé dans notre cabinet en qualité d'assistante comptable du 7 janvier 2019 au 28 février 2022.
"""


# --- le nom ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("libelle", "adresse", "attendu"),
    [
        ("Amina Kodjo", "amina.kodjo@example.com", ("Kodjo", "Amina")),
        ("KODJO Amina", "x@example.com", ("Kodjo", "Amina")),
        ("Amina KODJO", "x@example.com", ("Kodjo", "Amina")),
        ("Jean de Souza", "x@example.com", ("de Souza", "Jean")),
        ("Yahoo!", "essi.kouma92@example.fr", ("Kouma", "Essi")),
        ("Gmail", "kossi_elom@example.com", ("Elom", "Kossi")),
        ("", "kofi.mensah@example.com", ("Mensah", "Kofi")),
        ("Candidature", "contact@example.com", ("", "")),
        ("Afi Dossou (via Google Drive)", "x@example.com", ("Dossou", "Afi")),
        ("jean-marc n'guessan", "x@example.com", ("N'Guessan", "Jean-Marc")),
    ],
)
def test_le_nom_de_l_expediteur(libelle, adresse, attendu):
    assert identite.depuis_entete(libelle, adresse) == attendu


def test_le_cv_dit_le_nom_par_ses_champs():
    texte = "CURRICULUM VITAE\nNom : AGBEKO\nPrénoms : Kossi Elom\nNationalité : Togolaise"
    assert identite.depuis_cv(texte) == ("Agbeko", "Kossi Elom")
    assert identite.depuis_cv("Nom et prénoms : DOSSOU Afi Mawuli") == ("Dossou", "Afi Mawuli")


def test_le_cv_dit_le_nom_par_son_en_tete():
    texte = "Curriculum Vitae\nKOUMA Essi Afi\nComptable confirmée\nEXPÉRIENCES PROFESSIONNELLES"
    assert identite.depuis_cv(texte) == ("Kouma", "Essi Afi")
    # Une rubrique ou un intitulé de poste n'est pas un nom.
    assert identite.depuis_cv("PROFIL PROFESSIONNEL\nAssistante de direction\nFORMATION") is None
    # La plus grande police l'emporte, même écrite sur deux lignes.
    assert identite.depuis_cv("Mawuli\nGBEDEMAH\nJuriste", titre="Mawuli GBEDEMAH") == ("Gbedemah", "Mawuli")


def test_le_cv_corrige_un_nom_qui_n_est_pas_une_personne():
    proposition = identite.proposer("Yahoo!", "", "KOUMA Essi Afi\nComptable", "essi.kouma92@example.fr")
    assert (proposition.nom, proposition.prenom, proposition.avertissement) == ("Kouma", "Essi Afi", None)


def test_le_cv_ne_permute_pas_sans_indice_sur():
    """« Dossou Afi » sans capitales : rien ne dit lequel est le nom."""
    assert identite.proposer("Dossou", "Afi", "Afi Dossou\nComptable", "") is None


def test_un_cv_au_nom_d_un_autre_est_signale_sans_etre_applique():
    proposition = identite.proposer("Kodjo", "Amina", "MENSAH Kofi\nComptable", "amina.kodjo@example.com")
    assert (proposition.nom, proposition.prenom) == ("Kodjo", "Amina")
    assert "Kofi Mensah" in proposition.avertissement


# --- les dates et le parcours -------------------------------------------------


@pytest.mark.parametrize(
    ("ligne", "attendu"),
    [
        ("Lomé — Mars 2021 – à ce jour", ("2021-03", None)),
        ("Sept. 2013 - Févr. 2016", ("2013-09", "2016-02")),
        ("03/2018 – 06/2021", ("2018-03", "2021-06")),
        ("Du 01/03/2019 au 30/06/2021", ("2019-03", "2021-06")),
        ("2015 - 2018 : Comptable", ("2015-01", "2018-01")),
        ("Depuis janvier 2022", ("2022-01", None)),
        ("Accra · Jan 2019 – Present", ("2019-01", None)),
        ("Feb – Jun 2026", ("2026-02", "2026-06")),
    ],
)
def test_les_plages_de_dates(ligne, attendu):
    (plage,) = lecture_locale.plages(ligne, date(2026, 11, 3))
    assert (plage.debut, plage.fin) == attendu


def test_une_annee_seule_n_est_pas_une_plage():
    assert lecture_locale.plages("Licence en Droit, 2015", date(2026, 11, 3)) == []


def test_la_lecture_locale_d_un_cv():
    lu = lecture_locale.lire(CV_P1 + "\n" + CV_P2, ["comptabilite"], date(2026, 11, 3))
    assert [(d.niveau, d.annee, d.domaine) for d in lu.diplomes] == [(3, 2018, "comptabilite et finance")]
    assert [(e.poste, e.employeur, e.debut, e.fin) for e in lu.experiences] == [
        ("Comptable principale", "Société Togolaise de Distribution SA", "2022-03", None),
        ("Assistante comptable", "Cabinet Fidex Conseil", "2019-01", "2022-02"),
    ]
    assert lu.langues == ["Français", "Anglais", "Éwé"]


def test_les_dates_avant_le_poste():
    texte = (
        "EXPERIENCE PROFESSIONNELLE\nDepuis janvier 2022\nConducteur de travaux\nCECO BTP\n"
        "03/2018 – 06/2021\nIngénieur travaux\nEBOMAF Togo"
    )
    lu = lecture_locale.lire(texte, aujourd_hui=date(2026, 11, 3))
    assert [(e.poste, e.employeur, e.debut) for e in lu.experiences] == [
        ("Conducteur de travaux", "CECO BTP", "2022-01"),
        ("Ingénieur travaux", "EBOMAF Togo", "2018-03"),
    ]


def test_un_master_1_n_est_pas_un_bac_plus_5():
    lu = lecture_locale.lire("FORMATION\nMaster 1 en Économie, Université de Kara, 2016")
    assert [d.niveau for d in lu.diplomes] == [4]


def test_la_copie_d_un_diplome():
    texte = (
        "RÉPUBLIQUE TOGOLAISE\nUNIVERSITÉ DE LOMÉ\nDIPLÔME DE LICENCE\n"
        "Le grade de Licence est conféré à Mademoiselle KOUMA Essi Afi, titulaire du baccalauréat\n"
        "Mention : Comptabilité et Finance\nDélivré à Lomé, le 15 octobre 2018"
    )
    diplome = lecture_locale.diplome_d_une_copie(texte, date(2026, 11, 3))
    assert (diplome.niveau, diplome.annee, diplome.domaine) == (3, 2018, "comptabilite et finance")
    assert diplome.etablissement == "UNIVERSITÉ DE LOMÉ"


def test_l_ia_prime_et_la_lecture_locale_comble():
    from app.llm.base import DossierExtrait

    locale = lecture_locale.lire(CV_P1 + "\n" + CV_P2, aujourd_hui=date(2026, 11, 3))
    ia = DossierExtrait.model_validate({"diplomes": [{"intitule": "Licence", "niveau": 3, "annee": 2018}]})
    fusion, notes = lecture_locale.fusionner(locale, ia)
    assert [d.intitule for d in fusion.diplomes] == ["Licence"]
    assert len(fusion.experiences) == 2
    assert any("Expériences" in n for n in notes)


# --- le découpage ------------------------------------------------------------


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [
        (LETTRE, P.LETTRE_MOTIVATION.value),
        (CV_P1, P.CV.value),
        (ATTESTATION, P.ATTESTATIONS_TRAVAIL.value),
        ("RÉPUBLIQUE TOGOLAISE\nCARTE NATIONALE D'IDENTITÉ\nNom : KOUMA", P.PIECE_IDENTITE.value),
        ("MINISTÈRE DE LA JUSTICE\nBULLETIN N° 3 DU CASIER JUDICIAIRE\nNÉANT", P.CASIER_JUDICIAIRE.value),
        ("UNIVERSITY OF GHANA\nwas awarded the degree of Master of Business Administration", P.COPIE_DIPLOMES.value),
    ],
)
def test_le_type_d_une_page(texte, attendu):
    assert decoupage.type_de_page(texte)[0] == attendu


def test_une_lettre_qui_cite_ses_pieces_n_est_pas_un_casier():
    texte = LETTRE + "\nPièces jointes : CV, copie des diplômes, casier judiciaire, certificat de nationalité"
    assert decoupage.type_de_page(texte)[0] == P.LETTRE_MOTIVATION.value


def test_un_dossier_fusionne_est_decoupe_en_pieces():
    donnees = pdf(LETTRE, CV_P1, CV_P2, ATTESTATION)
    pieces = decoupage.preparer_sync("Dossier.pdf", donnees, extraction.PDF_MIME)
    assert [(p.type_piece, p.pages, p.nom) for p in pieces] == [
        (P.LETTRE_MOTIVATION.value, (1, 1), "Dossier (p. 1).pdf"),
        # La deuxième page du CV n'a pas de titre : elle prolonge la première.
        (P.CV.value, (2, 3), "Dossier (p. 2-3).pdf"),
        (P.ATTESTATIONS_TRAVAIL.value, (4, 4), "Dossier (p. 4).pdf"),
    ]
    import fitz

    assert [fitz.open(stream=p.donnees, filetype="pdf").page_count for p in pieces] == [1, 2, 1]
    assert "Licence en Comptabilité" in pieces[1].texte


def test_un_cv_de_plusieurs_pages_n_est_pas_decoupe():
    pieces = decoupage.preparer_sync("CV.pdf", pdf(CV_P1, CV_P2), extraction.PDF_MIME)
    assert [(p.type_piece, p.nom) for p in pieces] == [(P.CV.value, "CV.pdf")]


def test_une_lettre_nommee_cv_est_une_lettre():
    pieces = decoupage.preparer_sync("CV.pdf", pdf(LETTRE), extraction.PDF_MIME)
    assert pieces[0].type_piece == P.LETTRE_MOTIVATION.value


def test_un_logo_de_signature_n_est_pas_une_piece():
    from PIL import Image

    tampon = io.BytesIO()
    Image.new("RGB", (120, 40), (200, 30, 30)).save(tampon, "PNG")
    assert extraction.piece_retenue(tampon.getvalue(), "logo.png") is None


def test_le_nom_dans_l_en_tete_d_un_word_est_lu():
    import docx

    document = docx.Document()
    document.sections[0].header.paragraphs[0].text = "Afi Mawuli DOSSOU — afi.dossou@example.tg"
    document.add_paragraph("FORMATION")
    tampon = io.BytesIO()
    document.save(tampon)
    texte = extraction.extract_sync(tampon.getvalue(), extraction.DOCX_MIME, min_chars=0).text
    assert texte.startswith("Afi Mawuli DOSSOU")


@pytest.mark.ocr
def test_un_scan_est_lu_par_ocr():
    import fitz

    with fitz.open(stream=pdf(ATTESTATION), filetype="pdf") as source:
        image = source[0].get_pixmap(dpi=150).tobytes("png")
    scanne = fitz.open()
    scanne.new_page().insert_image(fitz.Rect(0, 0, 595, 842), stream=image)
    document = extraction.extract_sync(scanne.tobytes(), extraction.PDF_MIME, min_chars=0)
    assert document.pages_ocr == [0]
    assert decoupage.type_de_page(document.text)[0] == P.ATTESTATIONS_TRAVAIL.value


# --- de bout en bout : un courriel -------------------------------------------


async def test_un_courriel_yahoo_avec_un_dossier_fusionne(monkeypatch):
    """Le cas de production : « Yahoo! » pour libellé, tout le dossier en un PDF."""

    async def interdit(*args, **kwargs):
        raise AssertionError("l'import ne doit pas appeler l'IA")

    monkeypatch.setattr("app.services.depouillement.get_provider", lambda: type("X", (), {"extraire_dossier": interdit})())
    message = courriel.MessageEntrant(
        message_id="<fusion@example.tg>",
        expediteur="essi.kouma92@example.fr",
        nom_expediteur="Yahoo!",
        sujet="Candidature",
        recu_le=datetime(2026, 11, 2, 9, 0),
        pieces=[courriel.PieceJointe(nom="Dossier.pdf", donnees=pdf(LETTRE, CV_P1, CV_P2, ATTESTATION))],
    )

    class Boite:
        reste = False

        def relever(self, limite=50, exclure=frozenset()):
            return [message]

        def marquer_traite(self, message_id):
            pass

    async with SessionLocal() as db:
        await courriel.relever(db, Boite())
        await db.commit()
        candidat = (await db.execute(select(Candidat))).scalar_one()
        pieces = (await db.execute(select(PieceCandidature).order_by(PieceCandidature.nom_fichier))).scalars().all()
        diplomes = (await db.execute(select(DiplomeCandidat))).scalars().all()
        experiences = (await db.execute(select(ExperienceCandidat))).scalars().all()

    assert (candidat.nom, candidat.prenom) == ("Kouma", "Essi Afi")
    assert sorted(p.type_piece for p in pieces) == sorted(
        [P.LETTRE_MOTIVATION.value, P.CV.value, P.ATTESTATIONS_TRAVAIL.value]
    )
    assert all(p.texte_extrait for p in pieces)
    assert [(d.niveau, d.annee) for d in diplomes] == [(3, 2018)]
    assert len(experiences) == 2


# --- par l'API ---------------------------------------------------------------

API = "/api/v1"


async def _poste(client, auth) -> str:
    from tests.test_doublons import monter_poste

    return await monter_poste(client, auth)


async def test_un_depot_en_lot_decoupe_et_lit_sans_ia(client, auth, monkeypatch):
    from PIL import Image

    async def interdit(*args, **kwargs):
        raise AssertionError("le dépôt sans lecture demandée ne doit pas appeler l'IA")

    monkeypatch.setattr(
        "app.services.depouillement.get_provider", lambda: type("X", (), {"extraire_dossier": interdit})()
    )
    logo = io.BytesIO()
    Image.new("RGB", (120, 40), (200, 30, 30)).save(logo, "PNG")
    poste_id = await _poste(client, auth)
    reponse = await client.post(
        f"{API}/postes/{poste_id}/candidatures/depot-multiple",
        files=[
            ("fichiers", ("Dossier.pdf", pdf(LETTRE, CV_P1, CV_P2, ATTESTATION), "application/pdf")),
            ("fichiers", ("logo.png", logo.getvalue(), "image/png")),
        ],
        data={"groupes": ["Essi KOUMA", "Essi KOUMA"]},
        headers=auth,
    )
    assert reponse.status_code == 201, reponse.text
    corps = reponse.json()
    assert corps["deposes"] == 1 and corps["refuses"] == 1
    assert any("trop petite" in (r.get("erreur") or "") for r in corps["resultats"])

    candidature_id = next(r["candidature_id"] for r in corps["resultats"] if r["accepte"])
    dossier = (await client.get(f"{API}/candidatures/{candidature_id}", headers=auth)).json()
    assert sorted(p["type_piece"] for p in dossier["pieces"]) == sorted(
        [P.LETTRE_MOTIVATION.value, P.CV.value, P.ATTESTATIONS_TRAVAIL.value]
    )
    assert (dossier["candidat"]["nom"], dossier["candidat"]["prenom"]) == ("Kouma", "Essi Afi")
    assert len(dossier["candidat"]["experiences"]) == 2


async def test_decouper_un_ancien_pdf_fusionne(client, auth):
    poste_id = await _poste(client, auth)
    reponse = await client.post(
        f"{API}/postes/{poste_id}/candidatures/depot-multiple",
        files=[("fichiers", ("ancien.pdf", pdf(LETTRE, CV_P1, CV_P2, ATTESTATION), "application/pdf"))],
        # Le type imposé empêche le découpage : c'est l'état d'un dossier
        # importé avant que le découpage n'existe.
        data={"types_pieces": ["CV"]},
        headers=auth,
    )
    candidature_id = reponse.json()["resultats"][0]["candidature_id"]
    dossier = (await client.get(f"{API}/candidatures/{candidature_id}", headers=auth)).json()
    (piece,) = dossier["pieces"]

    apres = await client.post(
        f"{API}/candidatures/{candidature_id}/pieces/{piece['id']}/decouper", headers=auth
    )
    assert apres.status_code == 200, apres.text
    assert [(p["type_piece"], p["nom_fichier"]) for p in sorted(apres.json()["pieces"], key=lambda p: p["nom_fichier"])] == [
        (P.LETTRE_MOTIVATION.value, "ancien (p. 1).pdf"),
        (P.CV.value, "ancien (p. 2-3).pdf"),
        (P.ATTESTATIONS_TRAVAIL.value, "ancien (p. 4).pdf"),
    ]
    # Un CV seul ne se découpe pas.
    cv = next(p for p in apres.json()["pieces"] if p["type_piece"] == P.CV.value)
    refus = await client.post(f"{API}/candidatures/{candidature_id}/pieces/{cv['id']}/decouper", headers=auth)
    assert refus.status_code == 422 and "rien à découper" in refus.json()["detail"]


async def test_relire_les_noms_corrige_sans_toucher_au_reste(client, auth):
    poste_id = await _poste(client, auth)
    reponse = await client.post(
        f"{API}/postes/{poste_id}/candidatures/depot-multiple",
        files=[
            ("fichiers", ("cv_kouma.pdf", pdf(CV_P1, CV_P2), "application/pdf")),
            ("fichiers", ("cv_autre.pdf", pdf("MENSAH Kofi\nComptable\nFORMATION\n2015 : Licence en Droit"), "application/pdf")),
        ],
        data={"groupes": ["Yahoo", "Kodjo Amina"], "types_pieces": ["CV", "CV"]},
        headers=auth,
    )
    assert reponse.status_code == 201, reponse.text
    # Le dépôt a déjà lu le nom dans le CV ; on remet le mauvais pour
    # simuler un dossier arrivé avant cette lecture.
    async with SessionLocal() as db:
        for candidat in (await db.execute(select(Candidat))).scalars():
            if candidat.nom == "Kouma":
                candidat.nom, candidat.prenom = "Yahoo!", ""
        await db.commit()

    corps = (await client.post(f"{API}/candidatures/noms/relire", json={"poste_id": poste_id}, headers=auth)).json()
    assert [c["apres"] for c in corps["corriges"]] == ["Essi Afi Kouma"]
    # L'autre CV porte un tout autre nom : signalé, pas appliqué.
    assert [v["nom"] for v in corps["a_verifier"]] == ["Amina Kodjo"]


async def test_un_releve_trop_long_rend_la_main(monkeypatch):
    """Passé le budget, le relevé s'arrête et dit qu'il en reste : rien n'est perdu."""
    monkeypatch.setattr(courriel, "BUDGET_DU_RELEVE", -1)
    message = courriel.MessageEntrant(
        message_id="<budget@example.tg>",
        expediteur="afi.dossou@example.tg",
        nom_expediteur="Afi Dossou",
        sujet="Candidature",
        recu_le=datetime(2026, 11, 2, 9, 0),
        pieces=[courriel.PieceJointe(nom="CV.pdf", donnees=pdf(CV_P1))],
    )

    class Boite:
        reste = False

        def relever(self, limite=50, exclure=frozenset()):
            return [message]

        def marquer_traite(self, message_id):
            raise AssertionError("rien ne doit être marqué traité")

    async with SessionLocal() as db:
        resultat = await courriel.relever(db, Boite())
        assert resultat.reste is True and resultat.crees == 0 and resultat.spontanees == 0
        assert (await db.execute(select(Candidat))).scalars().all() == []


async def test_un_dossier_fusionne_renvoye_ne_double_pas_ses_pieces():
    """« Je vous renvoie mon dossier » : les morceaux déjà rangés ne reviennent pas."""
    from app.models import Candidature

    def message(identifiant):
        return courriel.MessageEntrant(
            message_id=identifiant,
            expediteur="afi.dossou@example.tg",
            nom_expediteur="Afi Dossou",
            sujet="Candidature",
            recu_le=datetime(2026, 11, 2, 9, 0),
            pieces=[courriel.PieceJointe(nom="Dossier.pdf", donnees=pdf(LETTRE, CV_P1, CV_P2, ATTESTATION))],
        )

    async with SessionLocal() as db:
        candidature = await courriel.creer_depuis_message(db, message("<a@example.tg>"), None)
        assert await courriel.enregistrer_pieces(db, candidature, message("<b@example.tg>")) == 0
        await db.commit()
        pieces = (await db.execute(select(PieceCandidature))).scalars().all()
        assert len(pieces) == 3
        assert len((await db.execute(select(Candidature))).scalars().all()) == 1
