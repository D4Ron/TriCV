from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx

from app.config import settings
from app.llm.base import LLMError

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 1s, 2s, 4s, 8s — four attempts total, as specified.
BACKOFF_SECONDS = (1, 2, 4, 8)
MAX_ATTEMPTS = 4
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


async def post_json(
    url: str,
    *,
    json: dict[str, Any],
    headers: dict[str, str] | None = None,
    provider: str = "llm",
) -> dict[str, Any]:
    """POST with exponential backoff on 429 and 5xx.

    Errors that will not fix themselves — a bad key, a malformed request — are
    raised on the first attempt rather than retried four times.
    """
    last_error: Exception | None = None

    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = await client.post(url, json=json, headers=headers or {})
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                logger.warning("[%s] transport error on attempt %d: %s", provider, attempt + 1, exc)
            else:
                if response.status_code < 400:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise LLMError(
                            f"{provider} returned a non-JSON body: {response.text[:300]}"
                        ) from exc

                body = response.text[:500]
                if response.status_code not in RETRY_STATUS:
                    raise LLMError(f"{provider} returned HTTP {response.status_code}: {body}")

                last_error = LLMError(f"HTTP {response.status_code}: {body}")
                logger.warning(
                    "[%s] HTTP %d on attempt %d/%d",
                    provider, response.status_code, attempt + 1, MAX_ATTEMPTS,
                )

            if attempt < MAX_ATTEMPTS - 1:
                # Jitter so a batch of CVs uploaded together does not retry in lockstep.
                delay = BACKOFF_SECONDS[attempt] * (1 + random.random() * 0.25)
                await asyncio.sleep(delay)

    raise LLMError(f"{provider} unreachable after {MAX_ATTEMPTS} attempts: {last_error}")


async def retry_async(
    call: Callable[[], Awaitable[T]],
    *,
    is_retryable: Callable[[Exception], bool],
    provider: str = "llm",
) -> T:
    """Same backoff schedule as `post_json`, for providers that use an SDK.

    Keeping one schedule means switching LLM_PROVIDER does not change how the
    system behaves under rate limiting.
    """
    last_error: Exception | None = None

    for attempt in range(MAX_ATTEMPTS):
        try:
            return await call()
        except Exception as exc:
            if not is_retryable(exc):
                raise
            last_error = exc
            logger.warning(
                "[%s] retryable error on attempt %d/%d: %s",
                provider, attempt + 1, MAX_ATTEMPTS, exc,
            )
            if attempt < MAX_ATTEMPTS - 1:
                await asyncio.sleep(BACKOFF_SECONDS[attempt] * (1 + random.random() * 0.25))

    raise LLMError(f"{provider} unreachable after {MAX_ATTEMPTS} attempts: {last_error}")
