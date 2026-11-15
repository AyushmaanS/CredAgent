"""OAuth metadata discovery + DCR shortcut against Fakeprov (HTTP only)."""

import httpx
from fake_provider.app import FakeProvider, Scenario

from credagent.metadata.dcr import register
from credagent.metadata.discovery import candidate_urls, discover
from credagent.orchestrator import fake_provider_plan
from credagent.secrets.masking import Masker
from credagent.secrets.store import SecretFileStore
from credagent.state.models import Plan


def test_metadata_without_registration_endpoint_not_eligible():
    with FakeProvider(Scenario(require_signin=False, terms="none")) as fp, httpx.Client() as http:
        res = discover(fake_provider_plan(fp.base_url), http, base_urls=[fp.base_url])
    assert res.metadata and res.metadata["token_endpoint"].endswith("/oauth/token")
    assert not res.dcr_eligible and "does not advertise" in res.reason


def test_registration_endpoint_without_documented_open_registration_not_used():
    with FakeProvider(Scenario(dcr=True)) as fp, httpx.Client() as http:
        plan = fake_provider_plan(fp.base_url).model_copy(update={"dynamic_registration": "unknown"})
        res = discover(plan, http, base_urls=[fp.base_url])
    assert res.registration_endpoint and not res.dcr_eligible and "did not establish" in res.reason


def test_dcr_eligible_and_register_stores_secret_outside_state(tmp_path):
    m = Masker()
    store = SecretFileStore(tmp_path / "secrets")
    with FakeProvider(Scenario(dcr=True)) as fp, httpx.Client() as http:
        res = discover(fake_provider_plan(fp.base_url), http, base_urls=[fp.base_url])
        assert res.dcr_eligible
        out = register(res.registration_endpoint, http, store, m, "run-1", client_name="credagent-demo",
                       redirect_uri="http://127.0.0.1:8976/callback")
        assert out.ok and out.credential and set(out.credential.parts) >= {"client_id", "client_secret"}
        secret = store.get(out.credential.parts["client_secret"].store_ref)
        assert secret.startswith("fpcs_") and m.contains_known(secret)
        assert secret not in out.credential.model_dump_json() and secret not in out.observed
        assert fp.audit("dcr_registered")


def test_discovery_stays_on_allowed_domains_and_https():
    plan = Plan(allowed_domains=["example.com"], metadata_url="https://evil.example/.well-known/x",
                console_url="https://console.example.com/apps")
    urls = candidate_urls(plan)
    assert urls and all(u.startswith("https://") and ".example.com" in u or "//example.com" in u for u in urls)
    assert not any("evil" in u for u in urls)
    assert candidate_urls(Plan(allowed_domains=["example.com"], metadata_url="http://example.com/x"))[0].startswith("https")
