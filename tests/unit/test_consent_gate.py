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


def test_accept_console_url_takes_only_a_plain_https_address_and_allows_its_host():
    from credagent.research.console import accept_console_url

    plan = Plan(allowed_domains=["acme.example"], console_url=None)
    ok, why = accept_console_url(plan, " https://console.acme.example/apps?x=1 ")
    assert why == "" and ok.console_url == "https://console.acme.example/apps?x=1" and ok.allowed_domains == ["acme.example"]
    other, _ = accept_console_url(plan, "https://console.other.example/start")
    assert other.allowed_domains == ["acme.example", "console.other.example"]
    assert any("given by the owner" in n for n in other.validation_notes) and plan.console_url is None  # not mutated
    for bad in ("", "ftp://x.example/", "https://", "https://1.2.3.4/", "https://a b.example", "http://x.example/",
                "https://u:p@x.example/", "https://localhost/", "x" * 400):
        assert accept_console_url(plan, bad)[0] is None, bad


def test_a_plan_without_a_console_address_asks_for_it_in_the_cli_before_consent(cli):
    from credagent.config.settings import load_settings
    from credagent.secrets.masking import Masker
    from credagent.state.store import RunStore

    run = planned_run("Acme API", "Acme Inc.")
    run.plan = run.plan.model_copy(update={"console_url": None, "domains_inferred": ["example.com"]})
    s = load_settings()
    RunStore(s.runs_dir, Masker()).checkpoint(run, "plan_edited")
    r = CliRunner().invoke(cli, ["resume", "r-acme"], input="not an address\nhttps://console.acme.example/apps\n\n")
    assert r.exit_code == 0, r.output
    assert "could not find this provider's developer console" in r.output and "does not look like a single web address" in r.output
    assert "inferred from the app name" in r.output  # the consent screen marks inferred domains
    assert "No consent given" in r.output  # and the browser still waits for consent
    saved = RunStore(s.runs_dir, Masker()).load("r-acme").run
    assert saved.plan.console_url == "https://console.acme.example/apps"
    assert "console.acme.example" in saved.plan.allowed_domains


def test_no_console_address_given_means_no_browser(cli):
    run = planned_run("Acme API", "Acme Inc.")
    run.plan = run.plan.model_copy(update={"console_url": None})
    from credagent.config.settings import load_settings
    from credagent.secrets.masking import Masker
    from credagent.state.store import RunStore

    RunStore(load_settings().runs_dir, Masker()).checkpoint(run, "plan_edited")
    r = CliRunner().invoke(cli, ["resume", "r-acme"], input="\n")
    assert r.exit_code == 0 and "No address given, so the browser was not started" in r.output


def test_an_owner_given_console_also_allows_the_providers_own_domain_but_never_a_shared_host_d098():
    from credagent.research.console import accept_console_url
    from credagent.state.models import Identification

    slack = Plan(allowed_domains=["docs.slack.dev"], identification=Identification(canonical_name="Slack", provider="Slack"))
    ok, _ = accept_console_url(slack, "https://api.slack.com/apps")
    # Slack sends the signed-in console to app.slack.com: that must stay on the list (the hang in run …2f3c)
    assert ok.allowed_domains == ["docs.slack.dev", "api.slack.com", "slack.com"] and ok.domains_inferred == ["slack.com"]
    from credagent.policy.hard_checks import host_allowed
    assert host_allowed("https://app.slack.com/app-settings/T1/A1/general", ok.allowed_domains)
    shared = Plan(allowed_domains=[], identification=Identification(canonical_name="Slack", provider="Slack"))
    other, _ = accept_console_url(shared, "https://slack-clone.vercel.app/console")
    assert other.allowed_domains == ["slack-clone.vercel.app"]  # its name is not the provider's: no sibling opened
