"""Stagehand's model, routed through CredAgent's FastRouter client.

Stagehand is given this callback instead of a model name + provider key, so every
model request Stagehand makes passes through our Masker (FastRouterClient masks
the whole body). Stagehand never holds a model API key.

Image content is refused: screenshots cannot be masked, so no screenshot may
reach a model (PRD §5.5, §13).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from stagehand._generated.models import LLMStructuredGenerateResult

from credagent.reasoning.fastrouter import FastRouterClient


class RefusedModelInput(Exception):
    """Stagehand asked for something CredAgent will not send to a model."""


def _to_openai_messages(params: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if params.get("system_prompt"):
        messages.append({"role": "system", "content": params["system_prompt"]})
    for m in params.get("messages", []):
        content = m["content"]
        blocks = content if isinstance(content, list) else [content]
        texts = []
        for b in blocks:
            if b.get("type") != "text":
                raise RefusedModelInput(f"refusing non-text model input ({b.get('type')})")
            texts.append(b["text"])
        messages.append({"role": m["role"], "content": "\n".join(texts)})
    return messages


def make_generate(
    client: FastRouterClient, model: str, *, strict: bool = False, timeout_s: float = 60.0,
    on_request: Callable[[list[dict[str, Any]]], None] | None = None,
) -> Callable[[Any], Awaitable[LLMStructuredGenerateResult]]:
    """Build the async callback passed as `Stagehand.create(model=...)`."""

    async def generate(params: Any) -> LLMStructuredGenerateResult:
        dumped = params.model_dump(mode="json", by_alias=True)
        fmt = dumped.get("response_format") or {}
        if fmt.get("type") != "json_schema" or "schema" not in fmt:
            raise RefusedModelInput("CredAgent only serves structured Stagehand requests")
        messages = _to_openai_messages(dumped)
        if on_request is not None:
            on_request(messages)
        out = await asyncio.to_thread(
            client.chat, messages, model=model, json_schema=fmt["schema"],
            schema_name=fmt.get("name") or "stagehand", strict=strict, timeout_s=timeout_s,
        )
        structured = out["parsed"]
        return LLMStructuredGenerateResult.model_validate({
            "role": "assistant",
            "content": {"type": "text", "text": json.dumps(structured)},
            "output_format": "json_schema",
            "structured_content": structured,
        })

    return generate
