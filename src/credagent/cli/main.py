"""`credagent` command-line entry point.

Every PRD command exists. Anything not available yet says so plainly and exits
with code 2 — it never implies success. Output never includes secrets, except
`credagent secret --reveal`, which the owner confirms by typing the value's name.
"""

from __future__ import annotations

import json
import sys

import click

from credagent import __version__
from credagent.config.settings import ConfigError, Settings, load_settings
from credagent.handoff.cards import render_card
from credagent.reports.report import build_report, render_markdown, write_reports
from credagent.secrets.masking import Masker
from credagent.state.store import RunNotFound, RunStore, StoreError

NOT_IMPLEMENTED_EXIT = 2
CONFIG_EXIT = 1


class TerminalIO:
    def say(self, text: str) -> None:
        click.echo(text)

    def choose(self, prompt: str, options: list[str]) -> str | None:
        for i, o in enumerate(options, 1):
            click.echo(f"  {i}. {o}")
        try:
            n = click.prompt(prompt + " (number)", type=click.IntRange(1, len(options)))
        except (click.Abort, EOFError):
            return None
        return options[n - 1]

    def wait_enter(self, prompt: str) -> bool:
        try:
            click.prompt(prompt, default="", show_default=False, prompt_suffix=" ")
        except (click.Abort, EOFError):
            return False
        return True


def _settings() -> Settings:
    try:
        return load_settings()
    except ConfigError as exc:
        click.echo(f"Configuration problem: {exc}", err=True)
        sys.exit(CONFIG_EXIT)


def _masker(s: Settings) -> Masker:
    m = Masker()
    if s.fastrouter_api_key:
        m.register(s.fastrouter_api_key, "fastrouter_key")
    if s.tavily_api_key:
        m.register(s.tavily_api_key, "tavily_key")
    return m


def _store(s: Settings, m: Masker) -> RunStore:
    return RunStore(s.runs_dir, m)


def _load(store: RunStore, run_id: str | None):
    try:
        if run_id is None:
            runs = store.list_runs()
            if not runs:
                click.echo("No runs yet. Start one with: credagent get \"<app>\"")
                sys.exit(0)
            run_id = runs[0].id
        return store.load(run_id).run
    except RunNotFound:
        click.echo(f"No run with id {run_id}. List runs with: credagent runs", err=True)
        sys.exit(1)
    except StoreError as exc:
        click.echo(f"Could not read run {run_id}: {exc}", err=True)
        sys.exit(1)


def _validate_app(_ctx: click.Context, _param: click.Parameter, value: str) -> str:
    name = value.strip()
    if not name:
        raise click.BadParameter("give the app name, e.g. credagent get \"GitHub\"")
    if len(name) > 100:
        raise click.BadParameter("app name is too long (max 100 characters)")
    if any(ch in name for ch in "\n\r\t"):
        raise click.BadParameter("app name must be a single line")
    return name


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="credagent")
def cli() -> None:
    """CredAgent: get working developer credentials for an app, with a live test.

    Runs locally. Opens a visible browser, pauses for steps only you should do
    (sign-in, codes, CAPTCHA, terms, payment), saves progress after every step,
    and stores credentials outside the repo.
    """


def _fake_provider_names() -> list[str]:
    try:
        from fake_provider.app import load_scenarios
        return sorted(load_scenarios())
    except Exception:  # noqa: BLE001 - fake provider not available in this install
        return []


@cli.command()
@click.argument("app", callback=_validate_app)
@click.option("--fake-provider", "scenario", metavar="SCENARIO", default=None,
              help="Run the browser phase against the local fake provider (Fakeprov) with this scenario.")
@click.option("--offline", is_flag=True, help="With --fake-provider: no API calls (rule-based decisions, "
              "plain-code candidates).")
@click.option("--headless", is_flag=True, help="With --fake-provider: hide the browser window.")
def get(app: str, scenario: str | None, offline: bool, headless: bool) -> None:
    """Start a new run to obtain credentials for APP (e.g. "GitHub").

    Real apps: research + plan, then pause (real-provider browser runs need per-provider consent,
    Sprint 6). Fakeprov: --fake-provider SCENARIO runs the browser phase locally.
    """
    if scenario is not None:
        _run_fake(app, scenario, offline, headless)
        return
    from credagent.orchestrator import Orchestrator
    from credagent.reasoning.fastrouter import FastRouterClient
    from credagent.research.agent import ResearchAgent
    from credagent.research.tavily import TavilyClient

    s = _settings()
    missing = [k for k, v in s.describe().items() if v == "missing"]
    if missing:
        click.echo(f"Missing configuration: {', '.join(missing)}. See README 'Local environment'.", err=True)
        sys.exit(CONFIG_EXIT)
    m = _masker(s)
    agent = ResearchAgent(TavilyClient(s, m), FastRouterClient(s, m), model=s.llm_model)
    store = _store(s, m)
    run = Orchestrator(store, m, agent, TerminalIO()).get(app)
    if run.status != "running":
        click.echo(f"\nRun {run.id} ended: {run.status} — {run.status_reason}")
        click.echo(f"Report: credagent report {run.id}")
        sys.exit(0 if run.status in ("succeeded", "partial") else 3)
    if run.phase == "planned" and run.pending_handoff is None:
        _real_browser(s, m, store, run, resume=False)


def _intended_actions(s: Settings, run, check) -> str:
    from credagent.browser.candidates import FieldValues

    v = FieldValues.default(s.redirect_uri)
    p = run.plan
    lines = [
        "",
        f"Before the browser opens (ATTEMPT-PROTOCOL §2), this is what will happen at {run.provider or run.app_name}:",
        f"  Credential:     {p.credential_kind.replace('_', ' ')}",
        f"  Console:        {p.console_url}   (allowed domains: {', '.join(p.allowed_domains)})",
        f"  Will create:    one app named {v.app_name!r}, description {v.description!r}",
        f"  Callback URL:   {v.redirect_uri}" if p.needs_redirect_uri != "no" else "  Callback URL:   not needed",
        "  Permissions:    none requested when creating the app; any permission or app-type choice is asked here",
        "  You do:         sign in, codes/2FA, CAPTCHA, accepting terms, anything unexpected (in the browser)",
        f"  Predicted:      {p.predicted_outcome}",
    ]
    lines += [f"  Known blocker:  {b[:150]}" for b in p.expected_blockers[:6]]
    lines += [f"  Live test:      {p.verification_procedure[:200]}",
              "  Afterwards:     delete the app in the provider's console yourself when you no longer need it "
              "(the agent never deletes).",
              f"  Terms check:    {check.finding.replace('_', ' ')} ({check.checked_on}; {check.record}). "
              + check.summary]
    if check.finding == "unclear":
        lines.append("                  Unclear wording is automated by default (your decision, protocol v2). "
                     "You remain responsible for activity on your account.")
    return "\n".join(lines)


def _ask_consent(s: Settings, run, check) -> str | None:
    """Per-provider, per-session consent in the owner's own words (ATTEMPT-PROTOCOL §2.2, §2.4)."""
    click.echo(_intended_actions(s, run, check))
    provider = check.provider
    try:
        account = click.prompt(f"\nWhich {provider} account will you sign in with? Describe it (no password, no "
                               "email), or press Enter to stop", default="", show_default=False)
        if not account.strip():
            return None
        yes = click.prompt(f'Type "yes" to run CredAgent against {provider} using {account.strip()!r}',
                           default="", show_default=False)
    except (click.Abort, EOFError):
        return None
    return account.strip()[:120] if yes.strip().lower() == "yes" else None


def _real_deps(s: Settings, m: Masker, run):
    import re

    from credagent.browser.stagehand_llm import make_generate
    from credagent.decisions.client import JevClient
    from credagent.orchestrator import BrowserDeps
    from credagent.reasoning.fastrouter import FastRouterClient
    from credagent.secrets.store import SecretFileStore

    fr = FastRouterClient(s, m)
    slug = re.sub(r"[^a-z0-9]+", "-", (run.app_name or run.app_input).lower()).strip("-")[:40] or "provider"
    return BrowserDeps(jev=JevClient(fr), reasoner=fr, llm_model=s.llm_model,
                       model_callback=make_generate(fr, s.stagehand_model), secret_store=SecretFileStore(s.secrets_dir),
                       profile_dir=s.profiles_dir / slug, redirect_uri=s.redirect_uri, headless=False,
                       allow_dcr=False, ephemeral_profile=False)


def _real_browser(s: Settings, m: Masker, store: RunStore, run, *, resume: bool, in_doubt: dict | None = None):
    """Real-provider browser phase: terms check → consent → browser (new or resumed)."""
    import asyncio

    from credagent.browser.chrome import ChromeError
    from credagent.consent.terms import lookup
    from credagent.orchestrator import Orchestrator, execute_browser_phase, resume_browser_phase
    from credagent.state.models import Consent

    check = lookup(run.app_name, run.provider, run.app_input)
    name = run.app_name or run.app_input
    if check is None:
        click.echo(f"\n{name}'s terms on automated console use have not been checked yet, so the browser is not "
                   "started (ATTEMPT-PROTOCOL §2.3). The plan is saved; once the terms are checked: "
                   f"credagent resume {run.id}")
        return
    if not check.may_automate:
        click.echo(f"\n{name}'s terms prohibit automated use of the console ({check.record}), so CredAgent will "
                   "not drive it. Follow the plan by hand if you want the credential.")
        return
    if not s.fastrouter_api_key:
        click.echo("FASTROUTER_API_KEY is missing; the browser needs Jev and the LLM.", err=True)
        sys.exit(CONFIG_EXIT)
    account = _ask_consent(s, run, check)
    if account is None:
        click.echo(f"\nNo consent given, so the browser was not started. The run is saved: credagent resume {run.id}")
        return
    run.consent.append(Consent(provider=check.provider, account=m.mask_text(account),
                               scope=f"this run ({run.id}): create one app and capture its credential",
                               terms_finding=check.finding, terms_record=check.record))
    store.checkpoint(run, "consent_given", {"provider": check.provider, "terms": check.finding})
    deps = _real_deps(s, m, run)
    io = TerminalIO()
    orch = Orchestrator(store, m, None, io)  # type: ignore[arg-type]  (research is done)
    click.echo(f"\nOpening the CredAgent browser window (profile: {_tilde(deps.profile_dir)}).")
    from credagent.state.store import SecretLeakError

    try:
        if resume:
            run = asyncio.run(resume_browser_phase(orch, run, deps, io, in_doubt))
        else:
            run = asyncio.run(execute_browser_phase(orch, run, deps, run.plan.console_url, io))
    except ChromeError as exc:
        click.echo(f"Browser problem: {exc}", err=True)
        sys.exit(1)
    except SecretLeakError:
        click.echo("\nCredAgent stopped itself: it was about to write a value registered as secret into the run's "
                   "log, which it never does. Nothing was written. This is a CredAgent bug; the run is saved up "
                   f"to the last safe step and can be continued after the fix: credagent resume {run.id}", err=True)
        sys.exit(4)
    _end_message(run)


def _fake_dir(s: Settings, run_id: str):
    return s.home / "fakeprov" / run_id


def _fake_deps(s: Settings, m: Masker, run_id: str, scenario_name: str, offline: bool, headless: bool):
    from fake_provider.app import load_scenarios
    from fake_provider.faults import FaultyFastRouter, faults_for

    from credagent.decisions.client import JevClient, RuleJev, RuleLLM
    from credagent.orchestrator import BrowserDeps
    from credagent.secrets.store import SecretFileStore

    faults = faults_for(load_scenarios()[scenario_name])
    if faults.any:
        click.echo("Simulated fault for this scenario: "
                   + ("Jev and the LLM are unreachable." if faults.llm_down else "every Jev call fails."))
    if offline:
        jev, reasoner, cb = RuleJev(), None, None
        if faults.any:  # the offline LLM stand-in answers the fallbacks, as the real LLM would
            llm = FaultyFastRouter(RuleLLM(), faults)
            jev, reasoner = JevClient(llm), llm
    else:
        from credagent.browser.stagehand_llm import make_generate
        from credagent.reasoning.fastrouter import FastRouterClient
        fr = FastRouterClient(s, m)
        if faults.any:
            fr = FaultyFastRouter(fr, faults)  # type: ignore[assignment]
        jev, reasoner, cb = JevClient(fr), fr, make_generate(fr, s.stagehand_model)
    return BrowserDeps(jev=jev, reasoner=reasoner, llm_model=s.llm_model, model_callback=cb,
                       secret_store=SecretFileStore(s.secrets_dir),
                       profile_dir=s.profiles_dir / "fakeprov" / run_id, redirect_uri=s.redirect_uri,
                       headless=headless, allow_dcr=True, ephemeral_profile=True)


def _end_message(run) -> None:
    click.echo(f"\nRun {run.id}: {run.status} — {run.status_reason}")
    if run.verification:
        click.echo(f"Live test: {run.verification.label} — {run.verification.observed_result}")
    if run.credential:
        click.echo(f"Credential (masked): credagent secret {run.id}")
    click.echo(f"Report: credagent report {run.id}")


def _run_fake(app: str, scenario_name: str, offline: bool, headless: bool) -> None:
    import asyncio

    from fake_provider.app import FakeProvider, scenario

    from credagent.browser.chrome import ChromeError
    from credagent.orchestrator import FAKE_PROVIDER_NAME, Orchestrator, execute_browser_phase, fake_provider_plan
    from credagent.state.atomic import atomic_write_json
    from credagent.state.models import Run, new_run_id

    names = _fake_provider_names()
    if scenario_name not in names:
        click.echo(f"Unknown scenario {scenario_name!r}. Choose one of: {', '.join(names)}", err=True)
        sys.exit(CONFIG_EXIT)
    s = _settings()
    m = _masker(s)
    if not offline and not s.fastrouter_api_key:
        click.echo("FASTROUTER_API_KEY is missing. Add it (README 'Local environment') or use --offline.", err=True)
        sys.exit(CONFIG_EXIT)
    store = _store(s, m)
    io = TerminalIO()
    run_id = new_run_id(f"fakeprov-{scenario_name}")
    fdir = _fake_dir(s, run_id)
    # The fake site's state is saved (owner-only) so `credagent resume` / `verify` work from a new terminal.
    with FakeProvider(scenario(scenario_name), state_file=fdir / "state.json") as fp:
        atomic_write_json(fdir / "launch.json", {"scenario": scenario_name, "offline": offline, "headless": headless})
        click.echo(f"Fakeprov ({scenario_name}) at {fp.base_url} (test sign-in: fake_provider/app/server.py)")
        run = Run(id=run_id, app_input=app, app_name="Fakeprov", provider=FAKE_PROVIDER_NAME,
                  plan=fake_provider_plan(fp.base_url))
        run.predicted_outcome = run.plan.predicted_outcome
        run.phase = "planned"
        store.create(run)
        deps = _fake_deps(s, m, run.id, scenario_name, offline, headless)
        orch = Orchestrator(store, m, None, io)  # type: ignore[arg-type]  (no research for Fakeprov)
        try:
            run = asyncio.run(execute_browser_phase(orch, run, deps, fp.base_url + "/", io))
        except ChromeError as exc:
            click.echo(f"Browser problem: {exc}", err=True)
            sys.exit(1)
    _end_message(run)


def _start_saved_fake(s: Settings, run):
    """Restart the fake site for RUN on its original port with its saved state."""
    from urllib.parse import urlparse

    from fake_provider.app import FakeProvider
    from fake_provider.app.server import saved_scenario

    sf = _fake_dir(s, run.id) / "state.json"
    if not sf.exists():
        click.echo("The fake site's saved state for this run is missing, so it cannot be restarted.", err=True)
        sys.exit(1)
    port = urlparse(run.plan.console_url or "").port or 0
    try:
        return FakeProvider(saved_scenario(sf), port=port, state_file=sf)
    except OSError:
        click.echo(f"Port {port} is in use, so the fake site for this run cannot be restarted. Close whatever "
                   "is using it and try again.", err=True)
        sys.exit(1)


@cli.command()
@click.argument("run_id")
@click.option("--headless", is_flag=True, help="Fake-provider runs: hide the browser window.")
def resume(run_id: str, headless: bool) -> None:
    """Resume RUN_ID from its last checkpoint (re-checks the page before acting)."""
    import asyncio

    from credagent.browser.chrome import ChromeError
    from credagent.orchestrator import FAKE_PROVIDER_NAME, Orchestrator, resume_browser_phase
    from credagent.secrets.capture import load_into_masker
    from credagent.secrets.store import SecretFileStore

    s = _settings()
    m = _masker(s)
    store = _store(s, m)
    try:
        loaded = store.load(run_id)
    except RunNotFound:
        click.echo(f"No run with id {run_id}. List runs with: credagent runs", err=True)
        sys.exit(1)
    run = loaded.run
    if run.status == "succeeded":
        click.echo(f"Run {run.id} already succeeded. To re-run the live test: credagent verify {run.id}")
        return
    if run.status != "running" and (not run.resumable or run.status == "cancelled"):
        click.echo(f"Run {run.id} ended as {run.status} and cannot be resumed: {run.status_reason}", err=True)
        sys.exit(1)
    load_into_masker(run.credential, SecretFileStore(s.secrets_dir), m)
    doubt = loaded.in_doubt_action
    if doubt:
        click.echo(f"Note: the last action before the interruption ({doubt.get('action')}: "
                   f"{m.mask_text(str(doubt.get('target') or ''))[:80]}) has no recorded result. The agent "
                   "re-checks the page and asks before repeating it.")
    if run.provider != FAKE_PROVIDER_NAME:
        if run.phase == "research" and run.plan.steps and run.pending_handoff is not None:
            # Research finished; only the credential-type question was left unanswered. Ask it again.
            if run.status != "running":
                run.transition("running", "resumed", resume=True)
            run = Orchestrator(store, m, None, TerminalIO()).resume_choice(run)  # type: ignore[arg-type]
            if run.phase == "planned":
                _real_browser(s, m, store, run, resume=False)
            return
        if run.phase in ("created", "research"):
            from credagent.reasoning.fastrouter import FastRouterClient
            from credagent.research.agent import ResearchAgent
            from credagent.research.tavily import TavilyClient

            if run.status != "running":
                run.transition("running", "resumed", resume=True)
            agent = ResearchAgent(TavilyClient(s, m), FastRouterClient(s, m), model=s.llm_model)
            run = Orchestrator(store, m, agent, TerminalIO())._research_and_plan(run, None)
            _end_message(run)
            return
        if run.status != "running":
            run.transition("running", "resumed", resume=True)
        store.checkpoint(run, "resumed", {"in_doubt": bool(doubt), "pending_handoff": bool(run.pending_handoff)})
        # A planned run starts its browser phase; a browser run continues where it stopped. Either way the
        # owner consents again for this session (ATTEMPT-PROTOCOL §2.2).
        _real_browser(s, m, store, run, resume=run.phase != "planned", in_doubt=doubt)
        return
    import json as _json

    launch = _json.loads((_fake_dir(s, run.id) / "launch.json").read_text(encoding="utf-8"))
    if run.status != "running":
        run.transition("running", "resumed", resume=True)
    store.checkpoint(run, "resumed", {"in_doubt": bool(doubt), "pending_handoff": bool(run.pending_handoff)})
    io = TerminalIO()
    with _start_saved_fake(s, run) as fp:
        click.echo(f"Fakeprov restarted at {fp.base_url} with this run's saved state.")
        deps = _fake_deps(s, m, run.id, launch["scenario"], launch["offline"], headless or launch["headless"])
        orch = Orchestrator(store, m, None, io)  # type: ignore[arg-type]
        try:
            run = asyncio.run(resume_browser_phase(orch, run, deps, io, doubt))
        except ChromeError as exc:
            click.echo(f"Browser problem: {exc}", err=True)
            sys.exit(1)
    _end_message(run)


@cli.command()
@click.argument("run_id", required=False)
def status(run_id: str | None) -> None:
    """Show status, current step, pending handoff and next action (no secrets)."""
    s = _settings()
    m = _masker(s)
    store = _store(s, m)
    run = _load(store, run_id)
    r = build_report(run)
    waiting = " — waiting for you" if run.pending_handoff else ""
    lines = [f"Run {run.id}  ({run.app_name or run.app_input})",
             f"  Status: {run.status}{waiting}   Phase: {run.phase}",
             f"  Reason: {run.status_reason or '-'}",
             f"  Predicted: {run.plan.predicted_outcome}   Verification: {r['verification']['label']}",
             f"  Steps: {len(run.steps)} ({r['steps']['by_actor']['agent']} by agent, "
             f"{r['steps']['by_actor']['person']} by you)"]
    if run.steps:
        last = run.steps[-1]
        lines.append(f"  Last step: [{last.actor}] {last.action} → {last.outcome}")
    lines.append("  Next:")
    lines += [f"    - {x}" for x in r["next_steps"]]
    click.echo(m.mask_text("\n".join(lines)))
    if run.pending_handoff:
        click.echo(render_card(run, run.pending_handoff, m))


@cli.command()
def runs() -> None:
    """List local runs and their outcomes."""
    s = _settings()
    m = _masker(s)
    all_runs = _store(s, m).list_runs()
    if not all_runs:
        click.echo("No runs yet. Start one with: credagent get \"<app>\"")
        return
    click.echo(f"{'RUN ID':<40} {'APP':<22} {'STATUS':<20} {'PHASE':<10} UPDATED")
    for r in all_runs:
        st = r.status + (" (waiting)" if r.pending_handoff else "")
        click.echo(m.mask_text(f"{r.id:<40} {(r.app_name or r.app_input)[:22]:<22} {st:<20} "
                               f"{r.phase:<10} {r.updated_at}"))


@cli.command()
@click.argument("run_id")
@click.option("--format", "fmt", type=click.Choice(["md", "json"]), default="md",
              show_default=True, help="Report format.")
def report(run_id: str, fmt: str) -> None:
    """Show the Markdown or JSON report for RUN_ID (also saved in the run folder)."""
    s = _settings()
    m = _masker(s)
    store = _store(s, m)
    run = _load(store, run_id)
    jpath, mpath = write_reports(run, store.runs_dir / run.id, m, store.events(run.id))
    rep = m.mask(build_report(run, store.events(run.id)))
    click.echo(json.dumps(rep, indent=2, ensure_ascii=False) if fmt == "json"
               else m.mask_text(render_markdown(rep)))
    click.echo(f"\n(saved: {mpath} and {jpath.name})", err=True)


@cli.command()
@click.argument("run_id")
def verify(run_id: str) -> None:
    """Run (or re-run) the live credential test for RUN_ID without showing the secret."""
    import httpx

    from credagent.orchestrator import FAKE_PROVIDER_NAME
    from credagent.secrets.capture import load_into_masker
    from credagent.secrets.store import SecretFileStore
    from credagent.state.models import Evidence, InvariantError, StepRecord, decide_outcome
    from credagent.verification.verify import verify_run

    s = _settings()
    m = _masker(s)
    store = _store(s, m)
    run = _load(store, run_id)
    if run.credential is None:
        click.echo(f"Run {run.id} has no captured credential, so there is nothing to test.", err=True)
        sys.exit(1)
    sstore = SecretFileStore(s.secrets_dir)
    load_into_masker(run.credential, sstore, m)
    fake = _start_saved_fake(s, run).start() if run.provider == FAKE_PROVIDER_NAME else None
    try:
        with httpx.Client() as http:
            seq = store.begin_action(run, "verify_credential", {"via": "credagent verify"})
            v = verify_run(run, sstore, m, http)
            store.end_action(run, seq, "done", {"label": v.label})
    finally:
        if fake is not None:
            fake.stop()
    run.verification = v
    run.untested = [] if v.label != "untested" else [f"Live credential test: {v.observed_result}"]
    outcome, reason = decide_outcome(credential_captured=True, verification=v)
    note = ""
    if run.status == "running":
        run.add_step(StepRecord(action=f"live test (credagent verify): {v.test_description}"[:200], actor="agent",
                                outcome="done" if v.label == "verified" else "failed",
                                evidence=[Evidence(kind="observed", text=m.mask_text(v.observed_result)[:300])]))
    if outcome != run.status:
        try:
            run.transition(outcome, f"{reason} — re-tested with credagent verify", resumable=outcome != "succeeded")
        except InvariantError:
            note = f" (the run stays {run.status}: {run.status} cannot change to {outcome})"
    store.checkpoint(run, "verified", {"label": v.label, "via": "credagent verify"})
    write_reports(run, store.runs_dir / run.id, m, store.events(run.id))
    click.echo(m.mask_text(f"Live test: {v.label} — {v.observed_result}"))
    click.echo(m.mask_text(f"Test: {v.test_description}"))
    for lim in v.production_limitations:
        click.echo(m.mask_text(f"Limitation: {lim}"))
    click.echo(f"Run {run.id}: {run.status}{note}")
    sys.exit(0 if v.label == "verified" else 3)


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _tilde(path) -> str:
    from pathlib import Path

    home = str(Path.home())
    p = str(path)
    return "~" + p[len(home):] if p.startswith(home) else p


def _backup_note(path) -> str:
    import subprocess

    try:
        out = subprocess.run(["/usr/bin/tmutil", "isexcluded", str(path)], capture_output=True, text=True,  # noqa: S603
                             timeout=5)
    except (OSError, subprocess.SubprocessError):
        return "Backup status unknown (tmutil not available)."
    if "[Excluded]" in out.stdout:
        return "Time Machine: excluded from backups."
    if "[Included]" in out.stdout:
        return (f"Time Machine: INCLUDED in backups. To exclude it yourself: tmutil addexclusion {_tilde(path)}")
    return "Backup status unknown."


@cli.command()
@click.argument("run_id")
@click.option("--reveal", "reveal_name", metavar="NAME", default=None,
              help="Intentionally reveal one stored value (e.g. client_secret). Asks you to confirm.")
@click.option("--print", "print_it", is_flag=True,
              help="With --reveal: print the value in the terminal instead of copying it to the clipboard.")
def secret(run_id: str, reveal_name: str | None, print_it: bool) -> None:
    """Show where RUN_ID's credential is stored (masked by default)."""
    from credagent.secrets.store import SecretFileStore, SecretStoreError

    s = _settings()
    m = _masker(s)
    run = _load(_store(s, m), run_id)
    cred = run.credential
    if cred is None:
        click.echo(f"Run {run.id} has no stored credential.")
        sys.exit(1)
    sstore = SecretFileStore(s.secrets_dir)
    label = run.verification.label if run.verification else "untested"
    click.echo(f"Run {run.id} — {cred.kind.replace('_', ' ')}, captured {cred.captured_at}, live test: {label}")
    for name, part in cred.parts.items():
        rid, pname = part.store_ref[len("file:"):].split("/")
        try:
            sstore.check(rid, pname)
            perm = "owner-only (file 0600, folders 0700)"
        except (SecretStoreError, OSError) as exc:
            perm = f"NOT SAFE: {exc}"
        click.echo(f"  {name:<15} {part.masked_display:<22} {_tilde(sstore.root / rid / (pname + '.secret'))}  "
                   f"[{perm}]")
    click.echo("Stored as plain files readable only by your macOS user; not encrypted (D-053).")
    click.echo(_backup_note(s.home))
    if reveal_name is None:
        click.echo(f"To reveal one value on purpose: credagent secret {run.id} --reveal <name>")
        return
    part = cred.parts.get(reveal_name)
    if part is None:
        click.echo(f"No stored value named {reveal_name!r}. Names: {', '.join(cred.parts)}", err=True)
        sys.exit(1)
    if not _interactive():
        click.echo("Revealing a secret needs an interactive terminal (it is never revealed to a pipe or a script).",
                   err=True)
        sys.exit(1)
    typed = click.prompt(f"Type {reveal_name} to reveal it", default="", show_default=False)
    if typed.strip() != reveal_name:
        click.echo("Not confirmed; nothing revealed.")
        sys.exit(1)
    value = sstore.get(part.store_ref)
    if print_it:
        click.echo(value)
        click.echo("(It is now in this terminal's scrollback. Clear it when you are done.)", err=True)
        return
    import subprocess

    try:
        subprocess.run(["/usr/bin/pbcopy"], input=value.encode("utf-8"), check=True, timeout=5)  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        click.echo("Could not copy to the clipboard. Use --print to show it in the terminal instead.", err=True)
        sys.exit(1)
    finally:
        value = ""
    click.echo(f"Copied {reveal_name} to the clipboard. Paste it where you need it, then copy something else "
               "to replace it (clipboard managers may keep a history).")


if __name__ == "__main__":
    cli()
