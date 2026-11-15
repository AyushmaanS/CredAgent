"""Tavily search/extract client. Results are untrusted data and are masked on return."""

from __future__ import annotations

import time
from typing import Any

import httpx

from credagent.config.settings import Settings
from credagent.secrets.masking import Masker

TAVILY_BASE_URL = "https://api.tavily.com"


class TavilyError(Exception):
    pass


class TavilyClient:
    def __init__(
        self,
        settings: Settings,
        masker: Masker,
        timeout_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not settings.tavily_api_key:
            raise TavilyError("TAVILY_API_KEY is not set (see README: Local environment)")
        self._masker = masker
        masker.register(settings.tavily_api_key, label="tavily_key")
        self._http = httpx.Client(
            base_url=TAVILY_BASE_URL,
            headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
            timeout=timeout_s,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            resp = self._http.post(path, json=body)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            raise TavilyError(f"{type(exc).__name__} calling Tavily {path}") from None
        if resp.status_code >= 400:
            raise TavilyError(
                f"Tavily {path} returned HTTP {resp.status_code}: "
                f"{self._masker.mask_text(resp.text[:300])}"
            )
        data = self._masker.mask(resp.json())
        data["latency_ms"] = round((time.monotonic() - started) * 1000)
        return data

    def search(self, query: str, *, max_results: int = 5, depth: str = "basic") -> dict[str, Any]:
        return self._post(
            "/search",
            {"query": query, "max_results": max_results, "search_depth": depth,
             "include_answer": False, "include_raw_content": False},
        )

    def extract(self, urls: list[str], *, depth: str = "basic") -> dict[str, Any]:
        # Markdown keeps headings, which section selection uses. "advanced" depth returned identical
        # text for official docs at twice the cost (DECISIONS D-038), so "basic" is the default.
        return self._post("/extract", {"urls": urls[:5], "extract_depth": depth, "format": "markdown"})
