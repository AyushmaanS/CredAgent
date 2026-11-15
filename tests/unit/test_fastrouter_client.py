import json

import httpx
import pytest

from credagent.config.settings import Settings
from credagent.reasoning.fastrouter import FastRouterClient, ModelCallError, ServiceUnavailable
from credagent.secrets.masking import Masker

KEY = "fr-fake-key-0123456789"


def client(handler):
    return FastRouterClient(Settings(fastrouter_api_key=KEY), Masker(),
                            transport=httpx.MockTransport(handler))


def test_payload_is_masked_before_sending():
    seen = {}
    secret = "Vq3xLm9-fake-shown-once-secret"  # fake; secret-scan: allow

    def handler(req):
        seen["body"] = req.content.decode()
        seen["auth"] = req.headers["authorization"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    c = client(handler)
    c._masker.register(secret)
    c.chat([{"role": "user", "content": f"page shows {secret} and key {KEY}"}])
    assert secret not in seen["body"]
    assert KEY not in seen["body"]
    assert seen["auth"] == f"Bearer {KEY}"


def test_structured_output_parsed():
    def handler(req):
        body = json.loads(req.content)
        assert body["response_format"]["type"] == "json_schema"
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"a": 1}'}}]})

    out = client(handler).chat([{"role": "user", "content": "x"}], json_schema={"type": "object"})
    assert out["parsed"] == {"a": 1}


def test_5xx_and_connect_errors_are_service_unavailable():
    with pytest.raises(ServiceUnavailable):
        client(lambda r: httpx.Response(503)).chat([])

    def boom(req):
        raise httpx.ConnectError("down")

    with pytest.raises(ServiceUnavailable):
        client(boom).systemone("s", {})


def test_4xx_is_model_call_error_without_key():
    with pytest.raises(ModelCallError) as e:
        client(lambda r: httpx.Response(401, text=f"bad key {KEY}")).chat([])
    assert KEY not in str(e.value)


def test_missing_key_is_plain_error():
    with pytest.raises(ModelCallError):
        FastRouterClient(Settings(), Masker())
