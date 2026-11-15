"""`credagent` command-line entry point.

Every PRD command exists. Commands not yet implemented say so plainly and exit
with code 2 — they never imply success. Output never includes secrets.
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


def _not_yet(command: str, sprint: int) -> None:
    click.echo(
        f"`credagent {command}` is not implemented yet (planned for Sprint {sprint}). "
        "Nothing was run.",
        err=True,
    )
    sys.exit(NOT_IMPLEMENTED_EXIT)


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
    run = Orchestrator(_store(s, m), m, agent, TerminalIO()).get(app)
    if run.status != "running":
        click.echo(f"\nRun {run.id} ended: {run.status} — {run.status_reason}")
        click.echo(f"Report: credagent report {run.id}")
        sys.exit(0 if run.status in ("succeeded", "partial") else 3)


def _run_fake(app: str, scenario_name: str, offline: bool, headless: bool) -> None:
    import asyncio

    from fake_provider.app import FakeProvider, scenario

    from credagent.browser.chrome import ChromeError
    from credagent.decisions.client import JevClient, RuleJev
    from credagent.orchestrator import BrowserDeps, Orchestrator, execute_browser_phase, fake_provider_plan
    from credagent.secrets.store import SecretFileStore
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
    with FakeProvider(scenario(scenario_name)) as fp:
        click.echo(f"Fakeprov ({scenario_name}) at {fp.base_url} (test sign-in: fake_provider/app/server.py)")
        run = Run(id=new_run_id(f"fakeprov-{scenario_name}"), app_input=app, app_name="Fakeprov",
                  provider="Fakeprov (local)", plan=fake_provider_plan(fp.base_url))
        run.predicted_outcome = run.plan.predicted_outcome
        run.phase = "planned"
        store.create(run)
        if offline:
            jev, reasoner, cb = RuleJev(), None, None
        else:
            from credagent.browser.stagehand_llm import make_generate
            from credagent.reasoning.fastrouter import FastRouterClient
            fr = FastRouterClient(s, m)
            jev, reasoner, cb = JevClient(fr), fr, make_generate(fr, s.stagehand_model)
        deps = BrowserDeps(jev=jev, reasoner=reasoner, llm_model=s.llm_model, model_callback=cb,
                           secret_store=SecretFileStore(s.secrets_dir),
                           profile_dir=s.profiles_dir / "fakeprov" / run.id, redirect_uri=s.redirect_uri,
                           headless=headless, allow_dcr=True, ephemeral_profile=True)
        orch = Orchestrator(store, m, None, io)  # type: ignore[arg-type]  (no research for Fakeprov)
        try:
            run = asyncio.run(execute_browser_phase(orch, run, deps, fp.base_url + "/", io))
        except ChromeError as exc:
            click.echo(f"Browser problem: {exc}", err=True)
            sys.exit(1)
    click.echo(f"\nRun {run.id}: {run.status} — {run.status_reason}")
    click.echo(f"Report: credagent report {run.id}")


@cli.command()
@click.argument("run_id")
def resume(run_id: str) -> None:
    """Resume RUN_ID from its last checkpoint (re-checks the page before acting)."""
    _not_yet("resume", 5)


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
    _not_yet("verify", 5)


@cli.command()
@click.argument("run_id")
@click.option("--reveal", is_flag=True,
              help="Intentionally reveal the stored secret (asks for confirmation).")
def secret(run_id: str, reveal: bool) -> None:
    """Show where RUN_ID's credential is stored (masked by default)."""
    _not_yet("secret", 5)


if __name__ == "__main__":
    cli()
