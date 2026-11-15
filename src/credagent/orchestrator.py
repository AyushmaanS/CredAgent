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
BROWSER_PENDING = "Paused after planning: browser execution is not available in this version yet (Sprint 3)."
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
        run.add_step(StepRecord(
            action=f"research ({sum(a['action'] == 'search' for a in self.research.actions)} searches, "
                   f"{sum(len(a.get('urls', [])) for a in self.research.actions if a['action'] == 'extract')} "
                   f"pages read)", actor="agent",
            outcome="done" if result.status == "planned" else "failed",
            evidence=[Evidence(kind="observed", text=f"{len(result.sources)} sources retrieved")]))

        if result.status == "ambiguous" and chosen is None:
            return self._ask_which_app(run, result)
        if result.status != "planned" or result.plan is None:
            return self._not_identified(run, result)

        run.plan = result.plan
        run.app_name = result.plan.identification.canonical_name
        run.provider = result.plan.identification.provider
        run.predicted_outcome = result.plan.predicted_outcome
        run.phase = "planned"
        run.status_reason = BROWSER_PENDING
        run.add_step(StepRecord(action="plan created", actor="agent", outcome="done",
                                evidence=[Evidence(kind="inferred",
                                                   text=f"{len(run.plan.steps)} steps; predicted "
                                                        f"{run.plan.predicted_outcome}")]))
        self._cp(run, "plan_ready", {"steps": len(run.plan.steps),
                                     "predicted": run.plan.predicted_outcome})
        self._report(run)
        self.io.say(render_plan(run, self.masker))
        self.io.say(f"\n{BROWSER_PENDING}\nSaved. Report: credagent report {run.id}")
        return run

    def _log_actions(self, run: Run) -> None:
        for a in getattr(self.research, "actions", []):
            self.store.checkpoint(run, "research_action", a)

    def _ask_which_app(self, run: Run, result: ResearchResult) -> Run:
        options = [f"{c.name} — {c.provider}" for c in result.candidates] + [NONE_OF_THESE]
        h = run.open_handoff(Handoff(
            kind="DECIDE", blocker_kind="other",
            reason=f"The name {run.app_input!r} matches more than one product.",
            evidence=[Evidence(kind="inferred", text=result.triage.notes[:300] if result.triage else "")],
            completed_so_far="research step 1 of 2", person_instruction="Choose which app you mean.",
            where="this terminal", expected_resume_action="Research the chosen app and write the plan.",
            options=options))
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
            b = run.add_blocker(Blocker(
                kind="app_not_identified", description="The person said none of the candidates is the app.",
                who_must_act="person",
                next_steps=["Re-run with a more specific name, e.g. include the company: "
                            'credagent get "<App> by <Company>"']))
            return self._finish(run, "blocked", b.description, resumable=False)
        chosen = result.candidates[options.index(answer)]
        return self._research_and_plan(run, chosen)

    def _not_identified(self, run: Run, result: ResearchResult) -> Run:
        notes = result.triage.notes if result.triage else "no search results"
        b = run.add_blocker(Blocker(
            kind="app_not_identified",
            description=f"Could not identify an app or provider called {run.app_input!r} from public sources.",
            evidence=[Evidence(kind="observed", text=f"{len(result.sources)} search results; triage: {notes[:300]}")],
            who_must_act="person",
            next_steps=["Check the spelling, or re-run with the company name: "
                        'credagent get "<App> by <Company>"']))
        return self._finish(run, "blocked", b.description, resumable=False)
