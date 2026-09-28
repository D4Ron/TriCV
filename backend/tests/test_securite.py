"""Garde-fous contre les attaques courantes : essais de mots de passe,
adresses falsifiées, clé de signature publique, envois démesurés."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.config import settings
from app.deps import client_ip
from app.services.ratelimit import LimiteurEchecs
API = "/api/v1"


def _requete(xff: str | None, hote: str = "10.0.0.5") -> Request:
    entetes = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": entetes, "client": (hote, 1234)})


def test_l_adresse_ne_se_falsifie_pas_par_x_forwarded_for(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    # Le client invente « 1.2.3.4 » ; le proxy ajoute la vraie adresse en fin.
    assert client_ip(_requete("1.2.3.4, 203.0.113.9")) == "203.0.113.9"
    assert client_ip(_requete(None)) == "10.0.0.5"
    monkeypatch.setattr(settings, "trusted_proxy_hops", 0)
    assert client_ip(_requete("1.2.3.4")) == "10.0.0.5"
    monkeypatch.setattr(settings, "trusted_proxy_hops", 2)
    assert client_ip(_requete("1.2.3.4, 198.51.100.7, 172.16.0.2")) == "198.51.100.7"


def test_les_echecs_de_connexion_finissent_par_bloquer():
    limiteur = LimiteurEchecs(3)
    for _ in range(3):
        limiteur.verifier("a@b.tg")
        limiteur.echec("a@b.tg")
    with pytest.raises(HTTPException) as refus:
        limiteur.verifier("a@b.tg")
    assert refus.value.status_code == 429
    # Une autre adresse n'est pas touchée ; une réussite efface le compteur.
    limiteur.verifier("c@d.tg")
    limiteur.oublier("a@b.tg")
    limiteur.verifier("a@b.tg")


async def test_la_connexion_est_refusee_apres_trop_d_echecs(client, monkeypatch):
    from app.api import auth as module_auth

    monkeypatch.setattr(module_auth, "login_par_compte", LimiteurEchecs(2))
    corps = {"email": "admin@tricv.example", "password": "mauvais"}
    assert (await client.post(f"{API}/auth/login", json=corps)).status_code == 401
    assert (await client.post(f"{API}/auth/login", json=corps)).status_code == 401
    bloque = await client.post(
        f"{API}/auth/login", json={"email": "admin@tricv.example", "password": "password123"}
    )
    assert bloque.status_code == 429


async def test_les_reponses_portent_les_en_tetes_de_securite(client):
    reponse = await client.get("/health")
    assert reponse.headers["x-content-type-options"] == "nosniff"
    assert reponse.headers["x-frame-options"] == "DENY"


async def test_un_envoi_public_demesure_est_refuse_avant_lecture(client):
    reponse = await client.post(
        f"{API}/public/avis/xyz/candidater",
        content=b"x",
        headers={"content-length": str(10 * 1024 * 1024 * 1024)},
    )
    assert reponse.status_code == 413


def test_une_cle_de_signature_publique_est_remplacee(monkeypatch):
    from app import main

    monkeypatch.setattr(settings, "jwt_secret", "dev-only-insecure-secret-change-me")
    main._refuser_secret_public()
    assert settings.jwt_secret != "dev-only-insecure-secret-change-me"
    assert len(settings.jwt_secret) >= 32
