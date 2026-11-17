"""Run orchestrator: create → research → plan → (browser: Sprint 3+) with a checkpoint
after every step. Code owns the lifecycle; models only propose content."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from credagent.handoff.cards import render_card
from credagent.reports.report import render_plan, write_reports
from credagent.research.agent import (
    BudgetExhausted,
    ResearchAgent,
    ResearchError,
    ResearchResult,
    ResearchUnavailable,
)
from credagent.research.schemas import Candidate
from credagent.secrets.masking import Masker
from credagent.state.models import Blocker, Evidence, Handoff, Run, StepRecord, new_run_id
from credagent.state.store import RunStore

NONE_OF_THESE = "None of these — I will re-run with a more specific name"
BROWSER_PENDING = ("Plan ready. The browser starts only after the provider's terms check and your consent "
                   "(docs/ATTEMPT-PROTOCOL.md section 2).")
UNTESTED_AT_PLAN = ["Browser execution (not available yet)", "Credential capture", "Live credential test"]


class IO(Protocol):
    def say(self, text: str) -> None: ...
    def choose(self, prompt: str, options: list[str]) -> str | None: ...


@dataclass
class Orchestrator:
    store: RunStore
    masker: Masker
    research: ResearchAgent
    io: IO

    def _cp(self, run: Run, event: str, data: dict | None = None) -> None:
        self.store.checkpoint(run, event, data)

    def _finish(self, run: Run, status: str, reason: str, *, resumable: bool | None = None) -> Run:
        run.transition(status, reason, resumable=resumable)
        self._cp(run, "run_finished", {"status": status, "reason": reason})
        self._report(run)
        return run

    def _report(self, run: Run) -> None:
        write_reports(run, self.store.runs_dir / run.id, self.masker, self.store.events(run.id))

    # ------------------------------------------------------------------ get
    def get(self, app_input: str) -> Run:
        run = Run(id=new_run_id(app_input), app_input=app_input, untested=list(UNTESTED_AT_PLAN))
        self.store.create(run)
        self.io.say(f"Run {run.id}: researching how {app_input!r} issues credentials…")
        return self._research_and_plan(run, None)

    def _research_and_plan(self, run: Run, chosen: Candidate | None) -> Run:
        run.phase = "research"
        self._cp(run, "research_started", {"chosen": chosen.model_dump() if chosen else None})
        try:
            result = self.research.research(run.app_input, chosen)
        except ResearchUnavailable as exc:
            self._log_actions(run)
            label = "FastRouter (LLM)" if exc.service == "fastrouter" else "Tavily (research search)"
            return self._finish(run, "failed", f"service unavailable: {label}. {exc}"[:400], resumable=True)
        except BudgetExhausted as exc:
            self._log_actions(run)
            return self._finish(run, "failed", f"research budget exhausted: {exc}", resumable=True)
        except ResearchError as exc:
            self._log_actions(run)
            return self._finish(run, "failed", f"research failed: {exc}"[:400], resumable=True)
        self._log_actions(run)
        run.add_step(
            StepRecord(
                action=f"research ({sum(a['action'] == 'search' for a in self.research.actions)} searches, "
                f"{sum(len(a.get('urls', [])) for a in self.research.actions if a['action'] == 'extract')} "
                f"pages read)",
                actor="agent",
                outcome="done" if result.status == "planned" else "failed",
                evidence=[Evidence(kind="observed", text=f"{len(result.sources)} sources retrieved")],
            )
        )

        if result.status == "ambiguous" and chosen is None:
            return self._ask_which_app(run, result)
        if result.status != "planned" or result.plan is None:
            return self._not_identified(run, result)

        run.plan = result.plan
        if result.plan.alternatives:
            if not self._choose_credential_type(run):
                return run
        return self._finalize_plan(run)

    def resume_choice(self, run: Run) -> Run:
        """Resume a run saved with the credential-type question unanswered: ask again (no new research)."""
        h = run.pending_handoff
        if h is not None:
            run.resolve_handoff(h.id, cancelled=True)
        if not self._choose_credential_type(run):
            return run
        return self._finalize_plan(run)

    def _finalize_plan(self, run: Run) -> Run:
        run.app_name = run.plan.identification.canonical_name
        run.provider = run.plan.identification.provider
        run.predicted_outcome = run.plan.predicted_outcome
        run.phase = "planned"
        run.status_reason = BROWSER_PENDING
        run.add_step(
            StepRecord(
                action="plan created",
                actor="agent",
                outcome="done",
                evidence=[
                    Evidence(
                        kind="inferred", text=f"{len(run.plan.steps)} steps; predicted {run.plan.predicted_outcome}"
                    )
                ],
            )
        )
        self._cp(run, "plan_ready", {"steps": len(run.plan.steps), "predicted": run.plan.predicted_outcome})
        self._report(run)
        self.io.say(render_plan(run, self.masker))
        self.io.say(f"\n{BROWSER_PENDING}\nSaved. Report: credagent report {run.id}")
        return run

    def _choose_credential_type(self, run: Run) -> bool:
        """D-035 / PRD §9: choosing between credential types is the person's decision. Returns False if
        the question is left unanswered (run saved with the DECIDE pending)."""
        rec = f"{run.plan.credential_kind} (recommended by research)"
        options = [rec] + [a[:150] for a in run.plan.alternatives]
        h = run.open_handoff(
            Handoff(
                kind="DECIDE",
                blocker_kind="other",
                reason="Research found more than one credential type for this app.",
                evidence=[Evidence(kind="inferred", text=f"recommended: {run.plan.credential_kind}")],
                completed_so_far="research done",
                person_instruction="Choose which credential to obtain.",
                where="this terminal",
                expected_resume_action="Plan the browser steps for that credential.",
                options=options,
            )
        )
        self._cp(run, "handoff_opened", {"handoff_id": h.id, "kind": "DECIDE", "about": "credential_type"})
        self.io.say(render_card(run, h, self.masker))
        answer = self.io.choose("Which credential?", options)
        if answer is None:
            self.io.say(f"No answer given. The run is saved with this question pending: {run.id}")
            return False
        run.resolve_handoff(h.id, answer=answer)
        run.add_step(StepRecord(action=f"chose credential type: {answer[:80]}", actor="person", outcome="done"))
        if answer != rec:
            run.plan.unknowns.insert(
                0,
                f"The person chose '{answer[:80]}' instead of the recommended "
                f"{run.plan.credential_kind}; the browser steps must be re-planned for it.",
            )
        self._cp(run, "handoff_resolved", {"handoff_id": h.id, "answer": answer})
        return True

    def _log_actions(self, run: Run) -> None:
        for a in getattr(self.research, "actions", []):
            self.store.checkpoint(run, "research_action", a)

    def _ask_which_app(self, run: Run, result: ResearchResult) -> Run:
        options = [f"{c.name} — {c.provider}" for c in result.candidates] + [NONE_OF_THESE]
        h = run.open_handoff(
            Handoff(
                kind="DECIDE",
                blocker_kind="other",
                reason=f"The name {run.app_input!r} matches more than one product.",
                evidence=[Evidence(kind="inferred", text=result.triage.notes[:300] if result.triage else "")],
                completed_so_far="research step 1 of 2",
                person_instruction="Choose which app you mean.",
                where="this terminal",
                expected_resume_action="Research the chosen app and write the plan.",
                options=options,
            )
        )
        self._cp(run, "handoff_opened", {"handoff_id": h.id, "kind": "DECIDE"})
        self.io.say(render_card(run, h, self.masker))
        answer = self.io.choose("Which app do you mean?", options)
        if answer is None:
            self.io.say(f"No answer given. The run is saved with this question pending: {run.id}")
            return run
        run.resolve_handoff(h.id, answer=answer)
        run.add_step(StepRecord(action=f"chose: {answer}", actor="person", outcome="done"))
        self._cp(run, "handoff_resolved", {"handoff_id": h.id, "answer": answer})
        if answer == NONE_OF_THESE:
            b = run.add_blocker(
                Blocker(
                    kind="app_not_identified",
                    description="The person said none of the candidates is the app.",
                    who_must_act="person",
                    next_steps=[
                        'Re-run with a more specific name, e.g. include the company: credagent get "<App> by <Company>"'
                    ],
                )
            )
            return self._finish(run, "blocked", b.description, resumable=False)
        chosen = result.candidates[options.index(answer)]
        return self._research_and_plan(run, chosen)

    def _not_identified(self, run: Run, result: ResearchResult) -> Run:
        notes = result.triage.notes if result.triage else "no search results"
        b = run.add_blocker(
            Blocker(
                kind="app_not_identified",
                description=f"Could not identify an app or provider called {run.app_input!r} from public sources.",
                evidence=[
                    Evidence(kind="observed", text=f"{len(result.sources)} search results; triage: {notes[:300]}")
                ],
                who_must_act="person",
                next_steps=['Check the spelling, or re-run with the company name: credagent get "<App> by <Company>"'],
            )
        )
        return self._finish(run, "blocked", b.description, resumable=False)


# ---------------------------------------------------------------- browser phase


@dataclass
class BrowserDeps:
    """Everything the browser phase needs; built by the CLI (online) or by tests/offline runs."""

    secret_store: object  # SecretFileStore
    profile_dir: object  # Path
    redirect_uri: str
    headless: bool = False
    allow_dcr: bool = False  # DCR creates a client at the provider: fake provider only until Sprint 6
    ephemeral_profile: bool = False  # delete the profile when the run ends (fake provider)


def _metadata_step(o: Orchestrator, run: Run, deps: BrowserDeps, start_url: str, http: object) -> Run | None:
    """Public OAuth metadata and the dynamic-registration shortcut (observed and recorded either way). Returns the
    finished run if dynamic registration produced a credential (no browser needed), else None."""
    from credagent.browser.values import FieldValues
    from credagent.metadata.dcr import register
    from credagent.metadata.discovery import discover

    origin = "/".join(start_url.split("/")[:3])
    meta = discover(run.plan, http, base_urls=[origin])  # type: ignore[arg-type]
    run.metadata_check = meta.summary()
    run.add_step(StepRecord(action=f"checked OAuth metadata ({len(meta.checked)} URLs)", actor="agent",
                            outcome="done", evidence=[Evidence(kind="observed", text=meta.reason)]))
    o._cp(run, "metadata_checked", {"dcr_eligible": meta.dcr_eligible, "reason": meta.reason})
    o.io.say(f"OAuth metadata: {meta.reason}")
    if meta.dcr_eligible and deps.allow_dcr and meta.registration_endpoint:
        seq = o.store.begin_action(run, "dcr_register", {"endpoint": meta.registration_endpoint})
        values = FieldValues.default(deps.redirect_uri)
        out = register(meta.registration_endpoint, http, deps.secret_store, o.masker, run.id,  # type: ignore[arg-type]
                       client_name=values.app_name, redirect_uri=deps.redirect_uri)
        o.store.end_action(run, seq, "done" if out.ok else "failed", {"observed": out.observed})
        run.add_step(StepRecord(action="dynamic client registration (no browser)", actor="agent",
                                outcome="done" if out.ok else "failed",
                                evidence=[Evidence(kind="observed", text=out.observed)]))
        if out.ok and out.credential:
            run.credential = out.credential
            return verify_and_finish(o, run, deps, http, how="obtained by dynamic registration (no browser)")
    elif meta.dcr_eligible:
        o.io.say("Dynamic registration looks available, but it is not used at real providers yet (it creates a "
                 "client without the console steps you consented to); continuing in the browser.")
    return None


async def _after_loop(o: Orchestrator, run: Run, deps: BrowserDeps, session: object, result: object) -> Run:
    """Map a browser-loop result to the run's outcome; close or keep the browser. Shared by get and resume."""
    import httpx

    keep_open = False
    if result is None or result.status == "handoff_pending":
        # Real providers: keep the window open so the person can finish and resume later.
        # Fake provider: its server stops with this process, so an open window would show a dead site.
        keep_open = not deps.ephemeral_profile
        what = "Paused at a handoff" if result is not None else "Paused (stopped, or the browser window was closed)"
        run.status_reason = (f"{what}; the browser window stays open. Continue with: "
                             f"credagent resume {run.id}" if keep_open else
                             f"{what}. The browser was closed; the fake site's state is saved. "
                             f"Continue with: credagent resume {run.id}")
        o._cp(run, "paused", {})
        o._report(run)
    elif result.status == "credential_page":
        if run.credential is None:
            run.add_blocker(Blocker(
                kind="other",
                description="The credential page was reached, but no value could be captured safely "
                            "(no recognisable label next to it).",
                who_must_act="person",
                next_steps=["Copy the credential from the provider's console into your own secret manager; "
                            "CredAgent did not capture it and never guesses which value is which."],
            ))
            o._finish(run, "blocked", run.blockers[-1].description, resumable=False)
        else:
            with httpx.Client() as http:
                verify_and_finish(o, run, deps, http, how="captured from the console by plain browser code")
    elif result.status == "blocked":
        o._finish(run, "blocked", result.reason, resumable=True)
    else:
        o._finish(run, "failed", f"{result.status}: {result.reason}", resumable=True)
    if keep_open:
        await session.detach()
    else:
        ended = await session.close()
        o._cp(run, "browser_closed", {"how": ended})
        if deps.ephemeral_profile and run.status != "running":
            import shutil

            # Fake-provider runs: nothing worth keeping once the run has ended. A paused run keeps its
            # profile so `credagent resume` can continue with the same cookies.
            shutil.rmtree(deps.profile_dir, ignore_errors=True)
    return run


def fake_provider_plan(base_url: str) -> object:
    import json as _json
    from pathlib import Path

    from credagent.state.models import Plan

    raw = (Path(__file__).resolve().parents[2] / "fake_provider" / "fixtures" / "plan.json").read_text()
    return Plan.model_validate(_json.loads(raw.replace("{base}", base_url))["plan"])


def verify_and_finish(o: Orchestrator, run: Run, deps: BrowserDeps, http: object, *, how: str) -> Run:
    """Live test (code only) → outcome. Only `verified` can make the run `succeeded` (PRD §10)."""
    from credagent.state.models import decide_outcome
    from credagent.verification.verify import verify_run

    run.phase = "verifying"
    seq = o.store.begin_action(run, "verify_credential", {})
    v = verify_run(run, deps.secret_store, o.masker, http)  # type: ignore[arg-type]
    o.store.end_action(run, seq, "done", {"label": v.label})
    run.verification = v
    run.untested = [] if v.label != "untested" else [f"Live credential test: {v.observed_result}"]
    run.add_step(StepRecord(action=f"live test: {v.test_description}"[:200], actor="agent",
                            outcome="done" if v.label == "verified" else "failed",
                            evidence=[Evidence(kind="observed", text=o.masker.mask_text(v.observed_result)[:300])]))
    o._cp(run, "verified", {"label": v.label, "limitations": v.production_limitations})
    outcome, reason = decide_outcome(credential_captured=True, verification=v)
    run.phase = "done"
    return o._finish(run, outcome, f"{reason} — {how}", resumable=outcome != "succeeded")


FAKE_PROVIDER_NAME = "Fakeprov (local)"


def safe_resume_url(run: Run) -> str | None:
    """Where to reopen the browser: the last observed page if its stored (masked) URL is intact and on the
    allowed domains, otherwise the plan's console URL. Never a URL whose parts were masked."""
    from credagent.policy.hard_checks import host_allowed

    last = run.browser.last_url if run.browser else None
    if last and "[" not in last and host_allowed(last, run.plan.allowed_domains):
        return last
    return run.plan.console_url or None


# ---------------------------------------------------------------- the agent loop (D-078)


async def execute_agent_phase(o: Orchestrator, run: Run, deps: BrowserDeps, start_url: str, io: object,
                              llm: object, *, session: object | None = None) -> Run:
    """Metadata / DCR shortcut, then the LLM agent loop over Playwright, then capture → live test → outcome.
    `session`: an already open PwSession (tests); otherwise one is opened on the run's profile."""
    import httpx

    from credagent.agent.loop import AgentLoop
    from credagent.browser.executor import BrowserClosed
    from credagent.browser.pw_session import open_pw_session
    from credagent.browser.values import FieldValues

    with httpx.Client() as http:
        done = _metadata_step(o, run, deps, start_url, http)
        if done is not None:
            return done
    if session is None:
        session = await open_pw_session(deps.profile_dir, headless=deps.headless)  # type: ignore[arg-type]
    run.browser = session.record()  # type: ignore[attr-defined]
    o._cp(run, "browser_opened", {"profile": str(deps.profile_dir)})
    loop = AgentLoop(o.store, o.masker, io, llm, FieldValues.default(deps.redirect_uri),  # type: ignore[arg-type]
                     secret_store=deps.secret_store)
    try:
        seq = o.store.begin_action(run, "navigate", {"url": o.masker.mask_text(start_url)})
        await session.page.goto(start_url)  # type: ignore[attr-defined]
        o.store.end_action(run, seq, "done")
        result = await loop.run(run, session)
    except (KeyboardInterrupt, BrowserClosed):
        result = None
    return await _after_loop(o, run, deps, session, result)


async def resume_agent_phase(o: Orchestrator, run: Run, deps: BrowserDeps, io: object, llm: object,
                             in_doubt: dict | None, *, session: object | None = None) -> Run:
    """Continue a paused run (spec §6.8): restore the profile (or re-attach to the open Chrome), reopen the page and
    let the agent look before it acts. A pending handoff is not assumed done: it is closed as "re-checked on resume",
    and the same blocker produces a fresh card if it is still there. An action that was started but never confirmed
    is never repeated without asking."""
    from credagent.agent.loop import AgentLoop
    from credagent.browser.executor import BrowserClosed
    from credagent.browser.pw_session import open_pw_session
    from credagent.browser.values import FieldValues

    h = run.pending_handoff
    if h is not None:
        run.resolve_handoff(h.id, cancelled=True)
        run.add_step(StepRecord(action=f"resumed: re-checking the page instead of assuming “{h.blocker_kind}” "
                                "was done", actor="system", outcome="done"))
    if session is None:
        session = await open_pw_session(deps.profile_dir, headless=deps.headless,  # type: ignore[arg-type]
                                        existing=run.browser)
    reattached = bool(getattr(session, "reattached", False))
    run.browser = session.record()  # type: ignore[attr-defined]
    o._cp(run, "browser_opened", {"profile": str(deps.profile_dir), "reattached": reattached})
    url = safe_resume_url(run)
    if url and not reattached:
        seq = o.store.begin_action(run, "navigate", {"url": o.masker.mask_text(url)})
        await session.page.goto(url)  # type: ignore[attr-defined]
        o.store.end_action(run, seq, "done")
    loop = AgentLoop(o.store, o.masker, io, llm, FieldValues.default(deps.redirect_uri),  # type: ignore[arg-type]
                     secret_store=deps.secret_store)
    try:
        result = await loop.run(run, session, in_doubt=in_doubt, resumed=True)
    except (KeyboardInterrupt, BrowserClosed):
        result = None
    return await _after_loop(o, run, deps, session, result)
