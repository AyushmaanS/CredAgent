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
BROWSER_PENDING = ("Paused after planning: browser runs against real providers stay disabled until the per-provider "
                   "consent flow (Sprint 6, docs/ATTEMPT-PROTOCOL.md section 2). Try the browser on the fake "
                   "provider: credagent get Fakeprov --fake-provider success")
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
        run.app_name = result.plan.identification.canonical_name
        run.provider = result.plan.identification.provider
        run.predicted_outcome = result.plan.predicted_outcome
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

    jev: object  # JevClient | RuleJev
    reasoner: object | None  # FastRouterClient for fallbacks/re-plans (None = offline)
    llm_model: str | None
    model_callback: object | None  # Stagehand model callback (None = offline: plain-code candidates)
    secret_store: object  # SecretFileStore
    profile_dir: object  # Path
    redirect_uri: str
    headless: bool = False
    allow_dcr: bool = False  # DCR creates a client at the provider: fake provider only until Sprint 6
    ephemeral_profile: bool = False  # delete the profile when the run ends (fake provider)


async def execute_browser_phase(o: Orchestrator, run: Run, deps: BrowserDeps, start_url: str, io: object) -> Run:
    import httpx

    from credagent.browser.candidates import FieldValues
    from credagent.browser.loop import BrowserLoop
    from credagent.browser.session import open_session
    from credagent.metadata.dcr import register
    from credagent.metadata.discovery import discover
    from credagent.state.models import decide_outcome

    # 1. Public metadata / DCR shortcut (observed, recorded either way)
    origin = "/".join(start_url.split("/")[:3])
    with httpx.Client() as http:
        meta = discover(run.plan, http, base_urls=[origin])
        run.metadata_check = meta.summary()
        run.add_step(
            StepRecord(
                action=f"checked OAuth metadata ({len(meta.checked)} URLs)",
                actor="agent",
                outcome="done",
                evidence=[Evidence(kind="observed", text=meta.reason)],
            )
        )
        o._cp(run, "metadata_checked", {"dcr_eligible": meta.dcr_eligible, "reason": meta.reason})
        o.io.say(f"OAuth metadata: {meta.reason}")
        if meta.dcr_eligible and deps.allow_dcr and meta.registration_endpoint:
            seq = o.store.begin_action(run, "dcr_register", {"endpoint": meta.registration_endpoint})
            values = FieldValues.default(deps.redirect_uri)
            out = register(
                meta.registration_endpoint,
                http,
                deps.secret_store,
                o.masker,
                run.id,
                client_name=values.app_name,
                redirect_uri=deps.redirect_uri,
            )
            o.store.end_action(run, seq, "done" if out.ok else "failed", {"observed": out.observed})
            run.add_step(
                StepRecord(
                    action="dynamic client registration (no browser)",
                    actor="agent",
                    outcome="done" if out.ok else "failed",
                    evidence=[Evidence(kind="observed", text=out.observed)],
                )
            )
            if out.ok and out.credential:
                run.credential = out.credential
                run.untested = ["Live credential test (Sprint 5)"]
                outcome, reason = decide_outcome(credential_captured=True, verification=None)
                return o._finish(
                    run,
                    outcome,
                    reason + " — obtained by dynamic registration; live test arrives in Sprint 5",
                    resumable=True,
                )
        elif meta.dcr_eligible:
            o.io.say(
                "Dynamic registration looks available, but creating a client at a real provider needs "
                "your per-provider consent (Sprint 6); using the browser path is also disabled until then."
            )

    # 2. Browser loop
    session = await open_session(deps.profile_dir, headless=deps.headless, model_callback=deps.model_callback)
    run.browser = session.record()
    o._cp(run, "browser_opened", {"profile": str(deps.profile_dir)})
    loop = BrowserLoop(
        o.store,
        o.masker,
        io,
        deps.jev,
        FieldValues.default(deps.redirect_uri),
        reasoner=deps.reasoner,
        llm_model=deps.llm_model,
    )
    keep_open = False
    try:
        seq = o.store.begin_action(run, "navigate", {"url": o.masker.mask_text(start_url)})
        await session.page.goto(start_url)
        o.store.end_action(run, seq, "done")
        result = await loop.run(run, session.page, session.stagehand, session.browser.context)
    except KeyboardInterrupt:
        result = None
    run.untested = ["Credential capture (Sprint 5)", "Live credential test (Sprint 5)"]
    if result is None or result.status == "handoff_pending":
        # Real providers: keep the window open so the person can finish and resume later.
        # Fake provider: its server stops with this process, so an open window would show a dead site.
        keep_open = not deps.ephemeral_profile
        run.status_reason = ("Paused at a handoff; the browser window stays open. Resume arrives in Sprint 5."
                             if keep_open else
                             "Paused at a handoff with no answer. The fake provider stops with this process, so "
                             "the browser was closed.")
        o._cp(run, "paused", {})
        o._report(run)
    elif result.status == "credential_page":
        run.status_reason = (
            "Credential page reached. Capture and the live test arrive in Sprint 5, so nothing was captured."
        )
        o._cp(run, "paused", {"reason": "credential page"})
        o._report(run)
    elif result.status == "blocked":
        o._finish(run, "blocked", result.reason, resumable=True)
    else:
        o._finish(run, "failed", f"{result.status}: {result.reason}", resumable=True)
    if keep_open:
        await session.detach()
    else:
        ended = await session.close()
        o._cp(run, "browser_closed", {"how": ended})
        if deps.ephemeral_profile:
            import shutil

            shutil.rmtree(deps.profile_dir, ignore_errors=True)  # fake-provider runs: nothing worth keeping
    return run


def fake_provider_plan(base_url: str) -> object:
    import json as _json
    from pathlib import Path

    from credagent.state.models import Plan

    raw = (Path(__file__).resolve().parents[2] / "fake_provider" / "fixtures" / "plan.json").read_text()
    return Plan.model_validate(_json.loads(raw.replace("{base}", base_url))["plan"])
