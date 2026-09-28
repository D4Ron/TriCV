from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, status

from app.config import settings


class SlidingWindowLimiter:
    """In-process IP limiter for the public endpoints.

    Single-process by design: the deployment target is one backend container,
    and the spec rules out Redis for this scale. Behind multiple replicas this
    limits per replica — put a reverse-proxy limit in front instead.
    """

    def __init__(self, limit: int, window_seconds: int = 3600) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            retry_after = int(self.window - (now - hits[0])) + 1
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many requests from this address. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)

    def prune(self) -> None:
        now = time.monotonic()
        for key in list(self._hits):
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if not hits:
                del self._hits[key]


public_limiter = SlidingWindowLimiter(settings.public_rate_limit_per_hour)
# Separate budget: a burst of failed signup attempts must not lock candidates
# out of applying, and vice versa.
signup_limiter = SlidingWindowLimiter(settings.signup_rate_limit_per_hour)


class LimiteurEchecs:
    """Compte les échecs seulement : une connexion réussie ne coûte rien.

    Deux budgets distincts : par adresse IP (un essai massif depuis une
    machine) et par compte (un essai lent, réparti, contre une adresse
    précise). Le message ne dit pas lequel a été atteint.
    """

    def __init__(self, limite: int, fenetre_secondes: int = 900) -> None:
        self._limiteur = SlidingWindowLimiter(limite, fenetre_secondes)

    def verifier(self, cle: str) -> None:
        limiteur = self._limiteur
        now = time.monotonic()
        hits = limiteur._hits.get(cle)
        if not hits:
            return
        while hits and now - hits[0] > limiteur.window:
            hits.popleft()
        if len(hits) >= limiteur.limit:
            retry_after = int(limiteur.window - (now - hits[0])) + 1
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Trop de tentatives de connexion. Réessayez dans quelques minutes.",
                headers={"Retry-After": str(retry_after)},
            )

    def echec(self, cle: str) -> None:
        self._limiteur._hits[cle].append(time.monotonic())

    def oublier(self, cle: str) -> None:
        self._limiteur._hits.pop(cle, None)


login_par_ip = LimiteurEchecs(settings.login_max_echecs_par_ip)
login_par_compte = LimiteurEchecs(settings.login_max_echecs_par_compte)
