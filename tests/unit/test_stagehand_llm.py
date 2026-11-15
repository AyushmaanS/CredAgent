import asyncio
import json

import httpx
import pytest
from stagehand._generated.models import LLMGenerateParams

from credagent.browser.stagehand_llm import RefusedModelInput, make_generate
from credagent.config.settings import Settings
from credagent.reasoning.fastrouter import FastRouterClient
from credagent.secrets.masking import Masker

SCHEMA = {"type": "object", "properties": {"elements": {"type": "array", "items": {}}},
          "required": ["elements"]}


def params(content):
    return LLMGenerateParams.model_validate({
        "messages": [{"role": "user", "content": content}],
        "system_prompt": "sys",
        "response_format": {"type": "json_schema", "name": "Observation", "schema": SCHEMA},
    }).root


def run(handler, p, masker=None):
    m = masker or Masker()
    key = "fr-fake-key-0123456789"  # fake; secret-scan: allow
    client = FastRouterClient(Settings(fastrouter_api_key=key), m,
                              transport=httpx.MockTransport(handler))
    return asyncio.run(make_generate(client, "anthropic/claude-haiku-5.5")(p))


def test_routes_through_masking_and_returns_structured():
    seen = {}
    shown = "Pq7Lm2-fake-registered-secret-x9"

    def handler(req):
        seen["body"] = req.content.decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"elements": []}'}}]})

    m = Masker([shown])
    out = run(handler, params({"type": "text", "text": f"tree ... StaticText: {shown}"}), m)
    assert shown not in seen["body"]
    body = json.loads(seen["body"])
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["response_format"]["json_schema"]["strict"] is False
    assert out.model_dump(mode="json", by_alias=True)["structured_content"] == {"elements": []}


def test_image_input_refused_before_any_request():
    called = []

    def handler(req):
        called.append(1)
        return httpx.Response(200, json={})

    p = params([{"type": "image", "data": "AAAA", "mime_type": "image/png"}])
    with pytest.raises(RefusedModelInput):
        run(handler, p)
    assert not called
