"""Sprint 5: plain-code capture classification, live verification labels, outcome mapping, `secret` CLI."""

import json

import httpx
import pytest
from click.testing import CliRunner

from credagent.browser.observe import Observation
from credagent.secrets.capture import classify, load_into_masker, store_capture
from credagent.secrets.masking import Masker
from credagent.secrets.store import SecretFileStore
from credagent.state.models import Plan, Run, VerificationResult, decide_outcome
from credagent.verification.verify import verify_run

CID = "fpcid_0123456789abcdef"
SEC = "fpcs_" + "Zx9" * 12


def obs(text="Client ID: [SECRET-ELEMENT] Client secret: [SECRET-ELEMENT]"):
    return Observation(url="http://127.0.0.1:1/apps/a", title="App", text=text, secret_xpaths=["/a", "/b"])


def items():
    return [{"value": CID, "own": "client-id", "label": "", "prev": "", "around": f"Client ID: {CID}"},
            {"value": SEC, "own": "client-secret", "label": "", "prev": "", "around": f"Client secret: {SEC}"}]


def test_classify_uses_own_attributes_then_context_and_never_guesses():
    assert classify({"own": "client-secret"}) == "client_secret"
    assert classify({"own": "", "around": "Your API key"}) == "api_key"
    assert classify({"own": "", "prev": "Client ID"}) == "client_id"
    assert classify({"own": "", "around": "Copy this value"}) is None


def test_store_capture_keeps_values_out_of_the_result(tmp_path):
    m, st = Masker(), SecretFileStore(tmp_path / "s")
    res = store_capture(items(), obs(), store=st, masker=m, run_id="r1", plan_kind="oauth_client")
    assert res.captured == ["client_id", "client_secret"] and res.has_secret and not res.secret_hidden
    dumped = res.credential.model_dump_json() + res.observed()
    assert SEC not in dumped and CID not in dumped
    assert st.get(res.credential.parts["client_secret"].store_ref) == SEC
    assert m.contains_known(SEC)  # registered before anything else could write it
    assert not m.contains_known(CID)  # an ID is not a secret: it may legitimately appear in URLs (D-062)


def test_unlabelled_and_ambiguous_values_are_not_stored(tmp_path):
    m, st = Masker(), SecretFileStore(tmp_path / "s")
    its = items() + [{"value": "Qq7" * 10, "own": "", "label": "", "prev": "", "around": "copy"},
                     {"value": "fpcs_" + "Ww3" * 12, "own": "client-secret", "around": ""}]
    res = store_capture(its, obs(), store=st, masker=m, run_id="r1", plan_kind="unknown")
    assert res.unlabelled == 1 and res.ambiguous == ["client_secret"]
    assert res.captured == ["client_id"] and res.credential.kind == "oauth_client"


def test_hidden_secret_and_limitations_are_observed(tmp_path):
    text = ("Client ID: [SECRET-ELEMENT] Client secret: •••••••• (hidden; it was shown once when created) "
            "This app is in testing mode: only test users you add can authorize it.")
    res = store_capture(items()[:1], obs(text), store=SecretFileStore(tmp_path / "s"), masker=Masker(),
                        run_id="r1", plan_kind="oauth_client")
    assert res.secret_hidden and not res.has_secret
    assert res.limitations and "testing mode" in res.limitations[0]


def run_with(tmp_path, *, token_ep="http://127.0.0.1:9/oauth/token", grants=("client_credentials",),  # noqa: S107
             parts=True):
    st = SecretFileStore(tmp_path / "s")
    run = Run(id="r1", app_input="x", plan=Plan(allowed_domains=["127.0.0.1"]))
    if parts:
        res = store_capture(items(), obs(), store=st, masker=Masker(), run_id="r1", plan_kind="oauth_client")
        run.credential = res.credential
    run.metadata_check = {"metadata": {"token_endpoint": token_ep, "grant_types_supported": list(grants),
                                       "token_endpoint_auth_methods_supported": ["client_secret_basic"]}}
    return run, st


def client(status, body):
    def handler(request):
        assert request.headers["Authorization"].startswith("Basic ")
        return httpx.Response(status, json=body)
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("status,body,label", [
    (200, {"access_token": "fpat_" + "T" * 30, "token_type": "bearer"}, "verified"),
    (401, {"error": "invalid_client"}, "invalid"),
    (400, {"error": "unauthorized_client"}, "client_recognized"),
    (400, {"error": "unsupported_grant_type"}, "inconclusive"),
    (503, {}, "inconclusive"),
])
def test_verification_labels(tmp_path, status, body, label):
    run, st = run_with(tmp_path)
    m = Masker()
    v = verify_run(run, st, m, client(status, body))
    assert v.label == label, v
    assert SEC not in v.model_dump_json() and "T" * 30 not in v.model_dump_json()
    if label == "verified":
        assert m.contains_known("fpat_" + "T" * 30)  # issued token masked everywhere afterwards


def test_untested_when_no_safe_test_exists(tmp_path):
    run, st = run_with(tmp_path, token_ep="http://evil.example/token")
    assert verify_run(run, st, Masker(), client(200, {})).label == "untested"  # off allow-list: secret not sent
    run, st = run_with(tmp_path / "b", grants=("authorization_code",))
    v = verify_run(run, st, Masker(), client(200, {}))
    assert v.label == "untested" and "authorization-code" in v.observed_result
    run, st = run_with(tmp_path / "c", parts=False)
    assert verify_run(run, st, Masker(), client(200, {})).label == "untested"


def test_unreachable_provider_is_untested_not_invalid(tmp_path):
    run, st = run_with(tmp_path)

    def boom(request):
        raise httpx.ConnectError("refused")
    v = verify_run(run, st, Masker(), httpx.Client(transport=httpx.MockTransport(boom)))
    assert v.label == "untested" and "Could not reach" in v.observed_result


@pytest.mark.parametrize("label,limits,outcome", [
    ("verified", [], "succeeded"), ("verified", ["testing mode"], "partial"),
    ("client_recognized", [], "partial"), ("inconclusive", [], "partial"), ("untested", [], "partial"),
    ("invalid", [], "failed"),
])
def test_only_verified_without_limits_succeeds(label, limits, outcome):
    v = VerificationResult(label=label, test_description="t", observed_result="o", production_limitations=limits)
    assert decide_outcome(credential_captured=True, verification=v)[0] == outcome


def test_load_into_masker_after_restart(tmp_path):
    run, st = run_with(tmp_path)
    m = Masker()
    assert load_into_masker(run.credential, st, m) == 1 and m.contains_known(SEC) and not m.contains_known(CID)


def _stored_run(tmp_path):
    from credagent.config.settings import load_settings
    from credagent.state.store import RunStore

    s = load_settings()
    st = SecretFileStore(s.secrets_dir)
    res = store_capture(items(), obs(), store=st, masker=Masker(), run_id="r-sec", plan_kind="oauth_client")
    run = Run(id="r-sec", app_input="x", plan=Plan(allowed_domains=["127.0.0.1"]), credential=res.credential)
    RunStore(s.runs_dir, Masker()).create(run)
    return s


def test_secret_command_is_masked_by_default(tmp_path):
    from credagent.cli.main import cli

    _stored_run(tmp_path)
    r = CliRunner().invoke(cli, ["secret", "r-sec"])
    assert r.exit_code == 0, r.output
    assert SEC not in r.output and CID not in r.output
    assert "owner-only" in r.output and "not encrypted" in r.output and "--reveal" in r.output


def test_secret_reveal_refuses_without_a_terminal(tmp_path):
    from credagent.cli.main import cli

    _stored_run(tmp_path)
    r = CliRunner().invoke(cli, ["secret", "r-sec", "--reveal", "client_secret", "--print"], input="client_secret\n")
    assert r.exit_code == 1 and "interactive terminal" in r.output and SEC not in r.output


def test_secret_reveal_needs_typed_confirmation(tmp_path, monkeypatch):
    from credagent.cli import main

    _stored_run(tmp_path)
    monkeypatch.setattr(main, "_interactive", lambda: True)
    r = CliRunner().invoke(main.cli, ["secret", "r-sec", "--reveal", "client_secret", "--print"], input="yes\n")
    assert r.exit_code == 1 and "Not confirmed" in r.output and SEC not in r.output


def test_secret_command_flags_widened_permissions(tmp_path):
    import os

    from credagent.cli.main import cli

    s = _stored_run(tmp_path)
    os.chmod(s.secrets_dir / "r-sec" / "client_secret.secret", 0o644)
    r = CliRunner().invoke(cli, ["secret", "r-sec"])
    assert "NOT SAFE" in r.output and SEC not in r.output
    assert json.dumps(r.output)  # printable


def test_secret_reveal_prints_only_after_confirmation(tmp_path, monkeypatch):
    from credagent.cli import main

    _stored_run(tmp_path)
    monkeypatch.setattr(main, "_interactive", lambda: True)
    r = CliRunner().invoke(main.cli, ["secret", "r-sec", "--reveal", "client_secret", "--print"],
                           input="client_secret\n")
    assert r.exit_code == 0 and SEC in r.output and "scrollback" in r.output


def test_researched_token_endpoint_used_when_no_metadata(tmp_path):
    run, st = run_with(tmp_path)
    run.metadata_check = {"metadata": None}
    run.plan = run.plan.model_copy(update={
        "allowed_domains": ["spotify.com"],
        "verification_procedure": "POST a client_credentials token request — endpoint https://accounts.spotify.com/api/token"})
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"access_token": "BQ" + "x9" * 20})
    v = verify_run(run, st, Masker(), httpx.Client(transport=httpx.MockTransport(handler)))
    assert v.label == "verified" and seen["url"] == "https://accounts.spotify.com/api/token"
    assert "sourced research" in v.test_description
    # an inferred endpoint is never used
    run.plan = run.plan.model_copy(update={"verification_procedure": run.plan.verification_procedure + " [inferred]"})
    assert verify_run(run, st, Masker(), client(200, {})).label == "untested"


def test_scope_from_sourced_procedure_is_sent(tmp_path):
    from credagent.verification.verify import researched_scope

    run, st = run_with(tmp_path)
    run.plan = run.plan.model_copy(update={"verification_procedure":
                                           "POST a client_credentials grant (scope 'identify') to the token endpoint"})
    assert researched_scope(run) == "identify"
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"access_token": "tok_" + "Q1" * 20})
    assert verify_run(run, st, Masker(), httpx.Client(transport=httpx.MockTransport(handler))).label == "verified"
    assert "scope=identify" in seen["body"] and SEC not in seen["body"]  # secret goes in the Basic header only
    run.plan = run.plan.model_copy(update={"verification_procedure": "scope 'admin' [inferred]"})
    assert researched_scope(run) is None


def test_numeric_client_id_is_captured_by_label(tmp_path):
    its = [{"value": "1234567890123456789", "own": "", "label": "", "prev": "Client ID", "around": "Client ID"},
           {"value": "aB3dE5fG7hI9jK1lM3nO5pQ7rS9tU1vW", "own": "", "label": "", "prev": "Client Secret",
            "around": "Client Secret Reset Secret"}]
    res = store_capture(its, obs(), store=SecretFileStore(tmp_path / "s"), masker=Masker(), run_id="r1",
                        plan_kind="oauth_client")
    assert res.captured == ["client_id", "client_secret"]


def test_label_two_levels_up_and_ids_not_registered(tmp_path):
    """Discord: <h2>Application ID</h2><div><div>1234…</div><button>Copy</button></div>"""
    m = Masker()
    its = [{"value": "1234567890123456789", "own": "", "label": "", "prev": "", "around": "Copy",
            "pprev": "Application ID", "up": "Application ID Copy"},
           {"value": "f" * 64, "own": "", "label": "", "prev": "", "around": "Copy", "pprev": "Public Key",
            "up": "Public Key Copy"}]
    res = store_capture(its, obs(), store=SecretFileStore(tmp_path / "s"), masker=m, run_id="r1",
                        plan_kind="oauth_client")
    assert res.captured == ["client_id"] and res.unlabelled == 1
    assert not m.contains_known("1234567890123456789") and not m.contains_known("f" * 64)
    url = "https://discord.com/developers/applications/1234567890123456789/information"
    assert m.mask_text(url) == url and not m.contains_known(url)  # the page URL is not treated as a secret
