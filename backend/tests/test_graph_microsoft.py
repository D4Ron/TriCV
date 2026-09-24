"""La boîte de recrutement chez Microsoft 365, par Microsoft Graph.

Deux chemins mènent à une boîte Microsoft, et ils ne coûtent pas la même chose
à mettre en service.

IMAP en XOAUTH2 — ce que couvre `test_boite_outlook.py` — suppose que
l'administrateur réactive SMTP AUTH sur le tenant, crée un principal de service
et le rattache à la boîte en PowerShell Exchange. Graph ne demande qu'une
inscription d'application, deux permissions d'application (Mail.ReadWrite et
Mail.Send) et un consentement administrateur. Pour un cabinet qui a déjà Entra
ID, c'est la seule des deux voies qui tienne en une réunion.

Ce fichier vérifie donc le client Graph — relevé, marquage, envoi — et surtout
**l'aiguillage** : que `messagerie` choisit bien Graph ou SMTP selon le
fournisseur réglé. Cet aiguillage a déjà été cassé une fois de façon invisible,
voir plus bas.
"""

from __future__ import annotations

import email.message

import httpx
import pytest

from app.services import graph_microsoft, messagerie, oauth_microsoft, parametres
from app.services.graph_microsoft import BoiteGraph, ErreurGraph
from app.services.oauth_microsoft import ConfigOAuth
from app.services.parametres import (
    FOURNISSEUR_IMAP,
    FOURNISSEUR_MICROSOFT365,
    _defauts,
)

pytestmark = pytest.mark.anyio

CONFIG = ConfigOAuth(
    tenant="11111111-2222-3333-4444-555555555555",
    client_id="app-de-recrutement",
    client_secret="secret",
)
BOITE = "recrutement@kapiconsult.tg"


@pytest.fixture(autouse=True)
def _jeton_et_cache(monkeypatch):
    """Un jeton sans réseau, et un cache propre entre deux tests."""
    oauth_microsoft.oublier_cache()
    monkeypatch.setattr(
        oauth_microsoft, "jeton", lambda config, compte, portee=None: "JETON"
    )
    yield
    oauth_microsoft.oublier_cache()


def _reponse(
    donnees: object = None, *, code: int = 200, contenu: bytes | None = None
) -> httpx.Response:
    requete = httpx.Request("GET", "https://graph.microsoft.com/v1.0/x")
    if contenu is not None:
        return httpx.Response(code, content=contenu, request=requete)
    return httpx.Response(code, json=donnees if donnees is not None else {}, request=requete)


class Graph:
    """Un Graph en carton : il note les appels et rend ce qu'on lui a dit."""

    def __init__(self, reponses: dict[tuple[str, str], httpx.Response]) -> None:
        self.reponses = reponses
        self.appels: list[tuple[str, str, dict]] = []

    def __call__(self, methode: str, url: str, **options) -> httpx.Response:
        self.appels.append((methode, url, options))
        for (m, fragment), reponse in self.reponses.items():
            if m == methode and fragment in url:
                return reponse
        return _reponse({"value": []})


def _brancher(monkeypatch, graph: Graph) -> None:
    monkeypatch.setattr(httpx.Client, "request", lambda self, m, u, **o: graph(m, u, **o))


def _mime(sujet: str, message_id: str) -> bytes:
    message = email.message.EmailMessage()
    message["Subject"] = sujet
    message["From"] = "Kwami Dogbe <kwami@example.tg>"
    message["To"] = BOITE
    message["Message-ID"] = message_id
    message.set_content("Bonjour, veuillez trouver ma candidature.")
    return message.as_bytes()


# --- le relevé ---------------------------------------------------------------


def test_le_releve_rend_les_messages_non_lus_au_format_mime(monkeypatch):
    """Graph rend du MIME comme l'IMAP : le même lecteur sert pour les deux.

    C'est tout l'intérêt de passer par `/$value` plutôt que par le JSON du
    message : pièces jointes comprises, `courriel.depuis_message` n'a pas à
    connaître Graph.
    """
    graph = Graph(
        {
            ("GET", "/mailFolders/inbox/messages"): _reponse(
                {"value": [{"id": "AAA", "internetMessageId": "<m1@example.tg>"}]}
            ),
            ("GET", "/messages/AAA/$value"): _reponse(
                contenu=_mime("Candidature DAF", "<m1@example.tg>")
            ),
        }
    )
    _brancher(monkeypatch, graph)

    with BoiteGraph(CONFIG, BOITE, "INBOX") as boite:
        messages = boite.relever()

    assert len(messages) == 1
    assert messages[0].sujet == "Candidature DAF"
    assert messages[0].expediteur == "kwami@example.tg"

    # Seuls les non-lus, et pas plus que la limite demandée.
    _, _, options = graph.appels[0]
    assert options["params"]["$filter"] == "isRead eq false"


def test_marquer_traite_passe_le_message_en_lu(monkeypatch):
    graph = Graph(
        {
            ("GET", "/mailFolders/inbox/messages"): _reponse(
                {"value": [{"id": "AAA", "internetMessageId": "<m1@example.tg>"}]}
            ),
            ("GET", "/messages/AAA/$value"): _reponse(contenu=_mime("Sujet", "<m1@example.tg>")),
            ("PATCH", "/messages/AAA"): _reponse({"id": "AAA"}),
        }
    )
    _brancher(monkeypatch, graph)

    with BoiteGraph(CONFIG, BOITE) as boite:
        boite.marquer_traite(boite.relever()[0].message_id)

    patch = [a for a in graph.appels if a[0] == "PATCH"]
    assert patch and patch[0][2]["json"] == {"isRead": True}


def test_un_message_inconnu_ne_se_marque_pas(monkeypatch):
    """Rien ne doit partir vers Graph pour un identifiant jamais relevé."""
    graph = Graph({})
    _brancher(monkeypatch, graph)

    with BoiteGraph(CONFIG, BOITE) as boite:
        boite.marquer_traite("<jamais-vu@example.tg>")

    assert graph.appels == []


def test_un_dossier_nomme_se_cherche_par_son_libelle(monkeypatch):
    graph = Graph(
        {
            ("GET", "/mailFolders?"): _reponse({"value": [{"id": "DOSSIER-42"}]}),
            ("GET", "/mailFolders"): _reponse({"value": [{"id": "DOSSIER-42"}]}),
        }
    )
    _brancher(monkeypatch, graph)

    with BoiteGraph(CONFIG, BOITE, "Candidatures") as boite:
        assert boite._dossier() == "/mailFolders/DOSSIER-42"


def test_un_dossier_absent_le_dit_en_francais(monkeypatch):
    _brancher(monkeypatch, Graph({}))  # toute recherche rend une liste vide

    with BoiteGraph(CONFIG, BOITE, "Inexistant") as boite, pytest.raises(ErreurGraph) as erreur:
        boite.verifier()

    assert "Inexistant" in str(erreur.value)
    assert "INBOX" in str(erreur.value)


# --- ce qu'un refus doit apprendre -------------------------------------------
#
# Un 403 sur Graph veut presque toujours dire que le consentement
# administrateur n'a pas été donné. Le dire évite de chercher du côté du mot de
# passe, qui n'existe pas ici.


@pytest.mark.parametrize(
    ("code", "attendu"),
    [
        (401, "jeton"),
        (403, "consentement"),
        (404, "boîte"),
    ],
)
def test_un_refus_explique_la_cause(monkeypatch, code, attendu):
    _brancher(monkeypatch, Graph({("GET", ""): _reponse({"error": {}}, code=code)}))

    with BoiteGraph(CONFIG, BOITE) as boite, pytest.raises(ErreurGraph) as erreur:
        boite.verifier()

    assert attendu.casefold() in str(erreur.value).casefold()


# --- l'envoi -----------------------------------------------------------------


def test_l_envoi_passe_par_sendmail_et_garde_une_trace(monkeypatch):
    graph = Graph({("POST", "/sendMail"): _reponse({}, code=202)})
    _brancher(monkeypatch, graph)

    graph_microsoft.envoyer(
        CONFIG,
        BOITE,
        "kwami@example.tg",
        "Convocation à un entretien",
        "Bonjour,",
        nom_destinataire="Kwami Dogbe",
    )

    methode, url, options = graph.appels[0]
    assert methode == "POST" and url.endswith("/sendMail")
    envoi = options["json"]
    # Sans cela, le cabinet ne retrouve pas ce qu'il a envoyé depuis Outlook.
    assert envoi["saveToSentItems"] is True
    assert envoi["message"]["subject"] == "Convocation à un entretien"
    assert envoi["message"]["toRecipients"][0]["emailAddress"]["address"] == "kwami@example.tg"


# --- l'aiguillage, et la panne qu'il a déjà causée ---------------------------


def _reglages(fournisseur: str):
    reglages = _defauts()
    reglages.fournisseur_courriel = fournisseur
    reglages.oauth_tenant = CONFIG.tenant
    reglages.oauth_client_id = CONFIG.client_id
    reglages.oauth_client_secret = CONFIG.client_secret
    reglages.smtp_actif = True
    reglages.smtp_host = "smtp.office365.com"
    reglages.smtp_port = 587
    reglages.smtp_user = BOITE
    reglages.smtp_expediteur = BOITE
    reglages.imap_user = BOITE
    return reglages


async def test_microsoft365_envoie_par_graph_et_non_par_smtp(monkeypatch):
    graph = Graph({("POST", "/sendMail"): _reponse({}, code=202)})
    _brancher(monkeypatch, graph)

    def pas_de_smtp(*_a, **_k):  # pragma: no cover - ne doit pas être appelé
        raise AssertionError("SMTP ne doit pas servir en Microsoft 365")

    monkeypatch.setattr(messagerie, "_expedier_smtp", pas_de_smtp)

    await messagerie.envoyer(
        messagerie.Message(
            destinataire="kwami@example.tg", sujet="Objet", corps="Corps"
        ),
        _reglages(FOURNISSEUR_MICROSOFT365),
    )

    assert any(url.endswith("/sendMail") for _m, url, _o in graph.appels)


async def test_le_chemin_smtp_dispose_de_ses_dependances():
    """Régression : l'envoi Outlook par SMTP levait `NameError`.

    `messagerie` appelait `oauth_microsoft.jeton`, `.chaine_xoauth2`,
    `.ErreurOAuth` et `_est_microsoft` sans les importer. Le code se chargeait
    sans broncher — rien n'est évalué à l'import — et ne cassait qu'au moment
    d'envoyer un message depuis une boîte Outlook, c'est-à-dire en
    exploitation. Les tests du relevé ne touchaient pas cette branche.

    Ce test ne vérifie pas un comportement mais une présence : que les noms
    dont dépend la branche SMTP existent bien dans le module.
    """
    for nom in ("oauth_microsoft", "graph_microsoft", "_est_microsoft"):
        assert hasattr(messagerie, nom), f"{nom} manque à messagerie"

    assert callable(messagerie._est_microsoft)
    assert messagerie._est_microsoft("smtp.office365.com")
    assert not messagerie._est_microsoft("smtp.gmail.com")


# --- le fournisseur par défaut -----------------------------------------------


def test_une_installation_imap_existante_ne_bascule_pas(monkeypatch):
    """Un cabinet déjà en IMAP ne doit pas se réveiller en Microsoft 365.

    Le fournisseur par défaut se décide à la lecture des réglages, d'après ce
    que porte le fichier de configuration — pas d'après l'objet `Reglages`, qui
    est déjà construit à ce moment-là.
    """
    monkeypatch.setattr(parametres.settings, "imap_host", "imap.gmail.com")
    monkeypatch.setattr(parametres.settings, "smtp_host", "")
    assert _defauts().fournisseur_courriel == FOURNISSEUR_IMAP


def test_une_installation_neuve_part_sur_microsoft365(monkeypatch):
    """Sans rien de réglé, c'est la messagerie que le cabinet emploie."""
    monkeypatch.setattr(parametres.settings, "imap_host", "")
    monkeypatch.setattr(parametres.settings, "smtp_host", "")
    assert _defauts().fournisseur_courriel == FOURNISSEUR_MICROSOFT365


def test_le_tenant_commun_ne_suffit_pas_a_graph():
    """`common` et `consumers` ne portent pas de permission d'application.

    Un compte personnel outlook.com ne peut pas servir de boîte de cabinet par
    ce chemin, et l'écran doit le dire plutôt que de laisser essayer.
    """
    reglages = _reglages(FOURNISSEUR_MICROSOFT365)
    for tenant in ("common", "consumers", ""):
        reglages.oauth_tenant = tenant
        assert not reglages.graph_utilisable

    reglages.oauth_tenant = CONFIG.tenant
    assert reglages.graph_utilisable
