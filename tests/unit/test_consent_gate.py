"""Sprint 6: a real provider's browser starts only after a recorded terms check and the owner's consent."""

import pytest
from click.testing import CliRunner

from credagent.consent.terms import TERMS_CHECKS, TermsCheck, lookup
from credagent.state.models import Identification, Plan, Run


def test_lookup_and_findings():
    assert lookup("Spotify Web API", "Spotify").provider == "Spotify"
    assert lookup("Acme") is None
    assert TERMS_CHECKS["spotify"].may_automate  # unclear → automated by default (D-059)
    assert not TermsCheck("X", "prohibited", "2026-11-16").may_automate


def planned_run(name, provider):
    from credagent.config.settings import load_settings
    from credagent.secrets.masking import Masker
    from credagent.state.store import RunStore

    s = load_settings()
    plan = Plan(identification=Identification(canonical_name=name, provider=provider), credential_kind="oauth_client",
                console_url="https://developer.example.com/dashboard", allowed_domains=["example.com"],
                predicted_outcome="partial", expected_blockers=["sign_in: needs an account"],
                verification_procedure="token request")
    run = Run(id=f"r-{name.split()[0].lower()}", app_input=name, app_name=name, provider=provider, plan=plan,
              phase="planned")
    RunStore(s.runs_dir, Masker()).create(run)
    return run


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setenv("FASTROUTER_API_KEY", "fr-dummy-key-for-tests")
    monkeypatch.setenv("TAVILY_API_KEY", "tv-dummy-key-for-tests")
    import credagent.cli.main as main
    from credagent.cli.main import cli as c
    opened = []
    monkeypatch.setattr(main, "_real_deps", lambda *a, **k: opened.append(1) or pytest.fail("browser opened"))
    return c


def test_an_unchecked_provider_is_not_blocked_but_still_needs_consent(cli):
    """D-091: a provider with no recorded terms check proceeds to the consent screen; the browser opens only after consent."""
    planned_run("Acme API", "Acme Inc.")
    r = CliRunner().invoke(cli, ["resume", "r-acme"])  # no answer given: no consent
    assert r.exit_code == 0, r.output
    assert "have not been checked yet" not in r.output
    assert "Terms check:    not checked" in r.output and "Unchecked providers are automated too" in r.output
    assert "No consent given" in r.output


def test_terms_for_never_returns_none_and_only_a_recorded_prohibition_blocks():
    from credagent.consent.terms import terms_for

    unknown = terms_for("Google Cloud", "Google")
    assert unknown.finding == "unchecked" and unknown.may_automate and unknown.provider == "Google Cloud"
    assert terms_for("Discord").finding == "unclear" and terms_for("Discord").may_automate
    assert not TermsCheck("X", "prohibited", "2026-11-16").may_automate


@pytest.mark.parametrize("answers", ["", "\n", "my test account\nno\n"])
def test_no_consent_no_browser(cli, answers):
    planned_run("Spotify Web API", "Spotify")
    r = CliRunner().invoke(cli, ["resume", "r-spotify"], input=answers)
    assert r.exit_code == 0, r.output
    assert "Will create:" in r.output and "Terms check:    unclear" in r.output
    assert "No consent given" in r.output
