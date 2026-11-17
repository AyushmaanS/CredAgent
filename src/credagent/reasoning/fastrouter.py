"""FastRouter HTTP client for the LLM (chat completions).

Every outgoing payload passes through the Masker before it leaves the process.
The API key is only ever placed in the Authorization header and is registered
with the Masker so it cannot appear in any payload or error message.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from credagent.config.settings import Settings
from credagent.secrets.masking import Masker


class ServiceUnavailable(Exception):
    """FastRouter could not be reached or returned a server error."""


class ModelCallError(Exception):
    """FastRouter answered, but the request failed (4xx) or the output was unusable."""


class OutputTruncated(ModelCallError):
    """The model stopped at max_tokens, so structured output is incomplete."""


class FastRouterClient:
    def __init__(
        self,
        settings: Settings,
        masker: Masker,
        timeout_s: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not settings.fastrouter_api_key:
            raise ModelCallError("FASTROUTER_API_KEY is not set (see README: Local environment)")
        self._settings = settings
        self._masker = masker
        masker.register(settings.fastrouter_api_key, label="fastrouter_key")
        self._http = httpx.Client(
            base_url=settings.fastrouter_base_url,
            headers={"Authorization": f"Bearer {settings.fastrouter_api_key}"},
            timeout=timeout_s,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _post(self, path: str, body: dict[str, Any], timeout_s: float | None) -> dict[str, Any]:
        safe_body = self._masker.mask(body)
        try:
            resp = self._http.post(path, json=safe_body, timeout=timeout_s or httpx.USE_CLIENT_DEFAULT)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            raise ServiceUnavailable(f"{type(exc).__name__} calling FastRouter {path}") from None
        if resp.status_code >= 500:
            raise ServiceUnavailable(f"FastRouter {path} returned HTTP {resp.status_code}")
        if resp.status_code >= 400:
            detail = self._masker.mask_text(resp.text[:500])
            raise ModelCallError(f"FastRouter {path} returned HTTP {resp.status_code}: {detail}")
        try:
            return resp.json()
        except json.JSONDecodeError:
            raise ModelCallError(f"FastRouter {path} returned non-JSON body") from None

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "result",
        strict: bool = True,
        temperature: float = 0.0,
        max_tokens: int = 2000,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model or self._settings.llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": strict, "schema": json_schema},
            }
        started = time.monotonic()
        data = self._post("/chat/completions", body, timeout_s)
        latency_ms = round((time.monotonic() - started) * 1000)
        try:
            content = data["choices"][0]["message"]["content"] or ""
            finish = data["choices"][0].get("finish_reason")
        except (KeyError, IndexError, TypeError, AttributeError):
            raise ModelCallError("chat completion response missing choices[0].message") from None
        parsed = None
        if json_schema is not None:
            try:
                parsed = json.loads(_strip_fences(content))
            except json.JSONDecodeError:
                if finish in ("length", "max_tokens"):
                    raise OutputTruncated(
                        f"structured output cut off at max_tokens={max_tokens} ({len(content)} chars)") from None
                raise ModelCallError(f"structured output was not valid JSON (finish_reason={finish})") from None
        return {
            "content": content,
            "parsed": parsed,
            "model": data.get("model"),
            "finish_reason": finish,
            "usage": data.get("usage"),
            "latency_ms": latency_ms,
        }


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()
