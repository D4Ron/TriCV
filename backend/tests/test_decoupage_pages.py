"""Où finit une pièce et où commence la suivante, dans un PDF fusionné.

Une pièce de plusieurs pages suivie d'une autre : le cas qui compte. Le contenu
seul ne suffit pas ; les pages portent aussi des signes de continuité.
"""

from __future__ import annotations

import fitz
import pytest

from app.domain.referentiel import PieceDossier as P
from app.services import decoupage
from app.services.decoupage import SignesDePage, numero_de_page, signes_de_page, type_de_page

CV_DEBUT = (
    "Afi DOSSOU\nExpérience professionnelle\n2018 - 2023 Responsable logistique, Port de Lomé\n"
    "Formation\nMaster en logistique\nCompétences\nExcel, SAP\nLangues\nFrançais"
)
CV_SUITE = (
    "2015 - 2018 Chef de quai chez Togo Transit\n"
    "- suivi des arrivages et des stocks de la zone sous douane du port\n"
    "- gestion de quinze agents sur deux sites"
)
CV_FIN = (
    "Certifications\nAttestation de participation au séminaire sur la sécurité portuaire, "
    "atelier de 2019\nCentres d'intérêt\nLecture"
)
LETTRE = (
    "Afi DOSSOU\nLomé, le 3 mars 2026\nObjet : candidature\nMadame,\n"
    "Je vous adresse ma candidature pour ce poste.\n"
    "Veuillez agréer, Madame, mes salutations distinguées."
)
ATTESTATION = (
    "ATTESTATION DE TRAVAIL\nJe soussigné, directeur de la société Togo Transit, atteste que "
    "Mme Afi DOSSOU a travaillé en qualité de chef de quai du 1er mars 2015 au 30 juin 2018."
)
SIGNATURE = "Fait à Lomé. Le Directeur Général."
AUTRE_ATTESTATION = (
    "ATTESTATION DE TRAVAIL\nNous certifions que Mme Afi DOSSOU occupe le poste de responsable "
    "logistique au Port de Lomé depuis juillet 2018 et à ce jour."
)
DIPLOME = (
    "UNIVERSITÉ DE LOMÉ\nDIPLÔME DE MASTER\nLe jury délivre le grade de master en logistique "
    "à Afi DOSSOU, session de juin 2014, mention bien."
)
RELEVE = "Semestre 1 UE gestion des flux 14/20 ; UE droit des transports 12/20 ; moyenne générale 13,8"
RAPPORT = (
    "Rapport de stage sur la modernisation du terminal à conteneurs de la zone franche et le "
    "suivi des marchandises en transit vers les pays de l'hinterland"
)


def decouper(pages, **signes_par_page):
    types = [type_de_page(p) for p in pages]
    signes = [
        signes_de_page(p, types[i][0], **signes_par_page.get(f"p{i}", {}))
        for i, p in enumerate(pages)
    ]
    return [(a + 1, b + 1, t) for a, b, t, _ in decoupage._segments(types, signes)]


def test_un_cv_de_trois_pages_reste_entier_meme_s_il_cite_ses_certificats():
    assert decouper([CV_DEBUT, CV_SUITE, CV_FIN]) == [(1, 3, P.CV.value)]


def test_un_scan_sans_titre_apres_le_cv_ne_disparait_pas_dedans():
    assert decouper([CV_DEBUT, CV_SUITE, RAPPORT, RAPPORT], p2={"scan": True}, p3={"scan": True}) == [
        (1, 2, P.CV.value),
        (3, 4, None),
    ]


def test_une_page_scannee_au_milieu_d_un_cv_en_reste_une_page():
    assert decouper([CV_DEBUT, RAPPORT, CV_SUITE, CV_DEBUT], p1={"scan": True}) == [(1, 4, P.CV.value)]


def test_une_page_en_paysage_apres_le_cv_est_autre_chose():
    a4 = {"format": (595, 842)}
    assert decouper(
        [CV_DEBUT, CV_SUITE, RAPPORT], p0=a4, p1=a4, p2={"format": (842, 595)}
    ) == [(1, 2, P.CV.value), (3, 3, None)]


def test_a4_et_letter_sont_la_meme_feuille():
    assert decouper(
        [CV_DEBUT, CV_SUITE], p0={"format": (595, 842)}, p1={"format": (612, 792)}
    ) == [(1, 2, P.CV.value)]


def test_ce_qui_suit_une_lettre_signee_n_en_est_plus():
    assert decouper([LETTRE, RAPPORT]) == [(1, 1, P.LETTRE_MOTIVATION.value), (2, 2, None)]


def test_une_lettre_inachevee_continue_sur_la_page_suivante():
    debut = "Objet : candidature\nMadame,\nJe vous adresse ma candidature pour ce poste."
    fin = "Je reste à votre disposition pour tout entretien que vous jugeriez utile à votre décision."
    assert decouper([debut, fin]) == [(1, 2, P.LETTRE_MOTIVATION.value)]


def test_deux_attestations_de_deux_pages_font_deux_pieces():
    assert decouper([ATTESTATION, SIGNATURE, AUTRE_ATTESTATION, SIGNATURE]) == [
        (1, 2, P.ATTESTATIONS_TRAVAIL.value),
        (3, 4, P.ATTESTATIONS_TRAVAIL.value),
    ]


def test_deux_diplomes_font_deux_pieces_et_le_releve_suit_le_sien():
    assert decouper([DIPLOME, RELEVE, DIPLOME]) == [
        (1, 2, P.COPIE_DIPLOMES.value),
        (3, 3, P.COPIE_DIPLOMES.value),
    ]


def test_une_page_de_signature_prolonge_meme_scannee():
    assert decouper([ATTESTATION, SIGNATURE], p1={"scan": True}) == [
        (1, 2, P.ATTESTATIONS_TRAVAIL.value)
    ]


def test_un_folio_qui_se_suit_garde_la_page_quoi_qu_elle_dise():
    page_1 = CV_DEBUT + "\nPage 1/2"
    page_2 = ATTESTATION + "\nPage 2/2"
    assert decouper([page_1, page_2]) == [(1, 2, P.CV.value)]


@pytest.mark.parametrize(
    ("ligne", "attendu"),
    [
        ("Page 2 sur 3", (2, 3)),
        ("page 2/3", (2, 3)),
        ("- 2 / 3 -", (2, 3)),
        ("2 of 3", (2, 3)),
        ("03/2024", None),
        ("4/3", None),
        ("Sur 3 ans", None),
    ],
)
def test_le_folio_se_lit_seul_sur_sa_ligne(ligne, attendu):
    assert numero_de_page(f"Un texte\n{ligne}") == attendu


def test_une_note_isolee_ne_passe_pas_pour_une_suite():
    avant = SignesDePage()
    assert not decoupage._suite_numerotee(avant, SignesDePage(numero=(12, 20)))


def test_le_format_vient_du_pdf_et_decoupe_le_fichier():
    doc = fitz.open()
    for texte, largeur, hauteur in (
        (CV_DEBUT, 595, 842),
        (CV_SUITE, 595, 842),
        (RAPPORT, 842, 595),
    ):
        page = doc.new_page(width=largeur, height=hauteur)
        page.insert_textbox(fitz.Rect(40, 40, largeur - 40, hauteur - 40), texte, fontsize=11)
    pieces = decoupage.preparer_sync("dossier.pdf", doc.tobytes(), "application/pdf")

    assert [(p.pages, p.type_piece) for p in pieces] == [((1, 2), P.CV.value), ((3, 3), None)]
