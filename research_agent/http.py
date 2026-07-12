"""Shared HTTP client with polite defaults and network-only retries.

All external providers (arXiv, Semantic Scholar, OpenAlex, GROBID, PDF/HTML
fetch) go through this so retry/timeout/user-agent policy lives in one place and
so tests can inject an ``httpx.MockTransport``.
"""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

USER_AGENT = "research-agent/0.1 (+https://github.com/rndubs/research-agent)"

_RETRYABLE = (httpx.TransportError, httpx.TimeoutException)


class HttpClient:
    """Thin wrapper over ``httpx.Client`` with exponential-backoff retries.

    Only network/transport errors are retried; HTTP 4xx/5xx are surfaced via
    ``raise_for_status`` at the call site so callers can decide (e.g. a 404 from
    S2 for a brand-new arXiv id is expected, not retryable).
    """

    def __init__(
        self,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        headers: dict[str, str] | None = None,
        max_attempts: int = 4,
    ) -> None:
        hdrs = {"User-Agent": USER_AGENT}
        if headers:
            hdrs.update(headers)
        self._client = httpx.Client(timeout=timeout, transport=transport, headers=hdrs)
        self.max_attempts = max_attempts

    def _retrying(self):
        return retry(
            reraise=True,
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential(multiplier=1, min=2, max=16),
            retry=retry_if_exception_type(_RETRYABLE),
        )

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._retrying()(self._client.get)(url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._retrying()(self._client.post)(url, **kwargs)

    def get_json(self, url: str, **kwargs: Any) -> Any:
        resp = self.get(url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def get_text(self, url: str, **kwargs: Any) -> str:
        resp = self.get(url, **kwargs)
        resp.raise_for_status()
        return resp.text

    def get_bytes(self, url: str, **kwargs: Any) -> bytes:
        resp = self.get(url, **kwargs)
        resp.raise_for_status()
        return resp.content

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
