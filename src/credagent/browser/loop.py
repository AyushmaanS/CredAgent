"""The browser loop (PRD F4, spec §6.4). Fixed order per page:

  observe (plain code) → hard checks (code) → Jev (five decisions) → fallbacks → policy (code)
  → act (Stagehand / plain locator, only if allowed) → record → checkpoint

Every browser action is bracketed by begin_action/end_action so a crash leaves an
"in doubt" marker instead of a silent replay. After any handoff the page is observed
again from scratch; nothing is replayed.

Sprint 3 scope: stops when a credential page is reached (capture + verification: Sprint 5).
"""

from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from credagent.browser.candidates import (
    FieldValues,
    RawCandidate,
    dom_candidates,
    from_stagehand,
    normalise,
    use_stagehand,
)
from credagent.browser.observe import Observation, observe_page
from credagent.decisions.client import DecisionLog, ServiceDown, apply_fallbacks
from credagent.decisions.jev import NONE_OPTION, PageState
from credagent.handoff.cards import render_card
from credagent.policy.engine import ProposedAction, Verdict, evaluate
from credagent.policy.hard_checks import blocking, check, host_allowed
from credagent.reasoning.replan import ReplanInfeasible, ReplanLimitReached, replan
from credagent.secrets.masking import Masker
from credagent.state.models import Blocker, Evidence, Handoff, Run, StepRecord
from credagent.state.store import RunStore

DO_INSTRUCTIONS = {
    "sign_in": "Sign in (or create the account) in the CredAgent browser window. Complete any code or 2FA prompt.",
    "verification_code": "Enter the verification code / complete the second factor in the browser window.",
    "captcha": "Complete the human check (CAPTCHA) in the browser window.",
    "payment": "This page asks for payment. Decide yourself; the agent never enters payment details. "
    "If you do not want to pay, leave the page and press Enter.",
    "terms": "Read the terms. If you agree, tick the box (if any) and submit the form yourself.",
    "cookie_consent": "Choose your cookie preference in the banner.",
    "off_allow_list": "The agent stopped at a page outside the allowed domains. If this page is expected, act on it "
    "yourself; otherwise go back to the provider's console.",
    "account_creation": "Create the account yourself in the browser window.",
    "unexpected": "Check the browser window and do what the page needs, or bring it back to the console.",
    "human_field": "Fill this field yourself in the browser window.",
}


MAX_HANDOFF_TRIES = 3


def terms_instruction(obs: Observation, gates: list) -> tuple[str, str]:
    """Exact instruction for a terms gate, naming the box and the button, and what is still missing.
    Returns (instruction, still_missing)."""
    g = next((x for x in gates if x.kind == "terms"), None)
    box = next((i for i in obs.inputs if g and i["xpath"] == g.target_xpath), None)
    form = (g.form_xpath if g else None) or (box["form"] if box else None)
    submit = next((b for b in obs.buttons if form and b["form"] == form and b["type"] in ("submit", "")), None)
    btn = f"“{submit['text']}”" if submit and submit["text"] else "the form's submit button"
    stop = " If you do not agree, press Ctrl+C: nothing is submitted and the run is saved."
    if box and not box["checked"]:
        missing = f"tick “{box['label'][:90]}” and click {btn}"
        return f"In the browser window: read the terms, tick “{box['label'][:90]}”, then click {btn}.{stop}", missing
    if box and box["checked"]:
        missing = f"click {btn}"
        return (
            f"The box “{box['label'][:90]}” is ticked, but the form is not submitted yet. "
            f"Click {btn} in the browser window.{stop}"
        ), missing
    missing = f"click {btn}"
    return (
        f"In the browser window: read the terms linked on the page. If you agree, click {btn}: clicking it "
        f"accepts the terms.{stop}"
    ), missing


class LoopIO(Protocol):
    def say(self, text: str) -> None: ...
    def choose(self, prompt: str, options: list[str]) -> str | None: ...
    def wait_enter(self, prompt: str) -> bool: ...


@dataclass(frozen=True)
class LoopBudget:
    max_observations: int = 40
    max_actions: int = 25
    max_no_progress: int = 4
    max_seconds: float = 900.0
    settle_ms: int = 700


@dataclass
class LoopResult:
    status: Literal["credential_page", "handoff_pending", "blocked", "failed", "stuck", "budget"]
    reason: str
    observations: int = 0
    actions: int = 0


@dataclass
class BrowserLoop:
    store: RunStore
    masker: Masker
    io: LoopIO
    jev: Any  # JevClient | RuleJev
    values: FieldValues
    reasoner: Any | None = None  # LLM for fallbacks + re-planning (None = offline)
    llm_model: str | None = None
    budget: LoopBudget = field(default_factory=LoopBudget)
    context: Any | None = None  # browser context for the domain guard (set by run())

    # ------------------------------------------------------------- helpers
    def _cp(self, run: Run, event: str, data: dict | None = None) -> None:
        self.store.checkpoint(run, event, self.masker.mask(data or {}))

    def _step(
        self,
        run: Run,
        action: str,
        actor: str,
        outcome: str,
        ev: list[str] | None = None,
        inferred: list[str] | None = None,
    ) -> None:
        evidence = [Evidence(kind="observed", text=self.masker.mask_text(e)[:300]) for e in ev or []]
        evidence += [Evidence(kind="inferred", text=self.masker.mask_text(e)[:300]) for e in inferred or []]
        plan_id = run.plan.steps[run.plan_cursor].id if run.plan_cursor < len(run.plan.steps) else None
        run.add_step(
            StepRecord(
                plan_step_id=plan_id,
                action=self.masker.mask_text(action)[:200],
                actor=actor,
                outcome=outcome,
                evidence=evidence,
                checkpoint_seq=run.checkpoint_seq + 1,
            )
        )

    def _goal(self, run: Run) -> str:
        steps = run.plan.steps
        if run.plan_cursor >= len(steps) or steps[run.plan_cursor].kind in ("capture", "verify"):
            return "Reach the page that shows the newly created credential"
        s = steps[run.plan_cursor]
        return s.description + (f" (expected page: {s.expected_page})" if s.expected_page else "")

    def _progress(self, run: Run) -> str:
        return f"step {min(run.plan_cursor + 1, len(run.plan.steps))} of {len(run.plan.steps)}"

    async def _handoff(
        self,
        run: Run,
        kind: Literal["DO", "DECIDE"],
        blocker_kind: str,
        reason: str,
        evidence: list[str],
        obs: Observation,
        *,
        instruction: str | None = None,
        options: list[str] | None = None,
        after: str = "Re-check the page, then continue the plan.",
        page: Any | None = None,
        gates: list | None = None,
    ) -> str | None:
        page = page if page is not None else getattr(self, "_page", None)
        gates = gates if gates is not None else getattr(self, "_gates", [])
        if kind == "DO" and blocker_kind == "terms" and instruction is None:
            instruction, _ = terms_instruction(obs, gates)
        h = run.open_handoff(
            Handoff(
                kind=kind,
                blocker_kind=blocker_kind
                if blocker_kind in _BLOCKER_KINDS
                else ("other" if kind == "DECIDE" else "unexpected"),
                reason=self.masker.mask_text(reason),
                evidence=[
                    Evidence(kind="observed", text=self.masker.mask_text(e)[:300], url=obs.url_masked)
                    for e in evidence[:4]
                ],
                completed_so_far=self._progress(run),
                person_instruction=instruction or DO_INSTRUCTIONS.get(blocker_kind, DO_INSTRUCTIONS["unexpected"]),
                where="the CredAgent Chrome window" if kind == "DO" else "this terminal",
                expected_resume_action=after,
                options=options or [],
            )
        )
        self._cp(run, "handoff_opened", {"handoff_id": h.id, "kind": kind, "blocker": blocker_kind})
        self.io.say(render_card(run, h, self.masker))
        if kind == "DO":
            # The person may need other domains (e.g. single sign-on): lift the browser-level domain
            # guard only while they act, then restore it. The code allow-list check still applies to the agent.
            await self._domain_guard(run, on=False)
            try:
                for attempt in range(1, MAX_HANDOFF_TRIES + 1):
                    done = self.io.wait_enter("Press Enter when you are done (Ctrl+C to stop; the run is saved)")
                    if inspect.isawaitable(done):
                        done = await done
                    if not done:
                        return None
                    still = await self._still_needed(page, obs, blocker_kind)
                    if still is None:
                        break
                    self._cp(run, "handoff_not_done_yet", {"handoff_id": h.id, "attempt": attempt, "still": still})
                    if attempt == MAX_HANDOFF_TRIES:
                        self.io.say(f"Still needed: {still}. The run is saved with this step waiting for you.")
                        return None
                    self.io.say(f"Not done yet — still needed: {still}. Do that in the browser, then press Enter.")
            finally:
                await self._domain_guard(run, on=True)
            run.resolve_handoff(h.id)
            self._step(run, f"person: {h.person_instruction[:120]}", "person", "done")
            self._cp(run, "handoff_resolved", {"handoff_id": h.id})
            return "done"
        answer = self.io.choose("Your decision", h.options)
        if inspect.isawaitable(answer):
            answer = await answer
        if answer is None:
            return None
        run.resolve_handoff(h.id, answer=answer)
        self._step(run, f"person decided: {answer}", "person", "done")
        self._cp(run, "handoff_resolved", {"handoff_id": h.id, "answer": answer})
        return answer

    async def _still_needed(self, page: Any | None, before: Observation, blocker_kind: str) -> str | None:
        """Re-check the page after the person pressed Enter. None = the handoff's condition is resolved."""
        if page is None:
            return None
        try:
            now = await observe_page(page, self.masker)
        except Exception:  # noqa: BLE001 - if the page cannot be read, let the main loop re-observe
            return None
        allowed = self._allowed
        gates_now = check(now, allowed)
        if blocker_kind == "terms":
            if not any(g.kind == "terms" for g in gates_now) or now.url != before.url:
                return None
            return terms_instruction(now, gates_now)[1]
        if blocker_kind in {g.kind for g in gates_now if g.action in ("DO", "BLOCK")}:
            return "the page still shows the same step (" + blocker_kind.replace("_", " ") + ")"
        unchanged = now.fingerprint() == before.fingerprint()
        if blocker_kind in ("unexpected", "human_field", "off_allow_list") and unchanged:
            return "nothing has changed on the page yet"
        return None

    async def _domain_guard(self, run: Run, *, on: bool) -> None:
        """Second layer behind the code allow-list: Stagehand's browser-level domain policy (D-043)."""
        if self.context is None:
            return
        try:
            await self.context.set_domain_policy({"allowed_domains": run.plan.allowed_domains} if on else None)
        except Exception as exc:  # noqa: BLE001 - recorded; the code allow-list still protects the agent
            self._cp(run, "domain_guard_error", {"on": on, "error": type(exc).__name__})

    async def _act(self, page: Any, cand: RawCandidate, value: str | None) -> None:
        loc = page.locator("xpath=" + cand.xpath)
        if cand.method == "fill":
            await loc.fill(value or "")
        elif cand.method == "select":
            await loc.select_option(value or "")
        else:  # click / check
            await loc.click()
        await page.wait_for_timeout(self.budget.settle_ms)

    async def _candidates(
        self, sh: Any | None, page: Any, goal: str, obs: Observation, denied: set[str]
    ) -> tuple[list, dict[str, RawCandidate], str]:
        raw: list[RawCandidate] = []
        source = "dom"
        if sh is not None and use_stagehand(obs):
            try:
                res = await sh.observe(goal, ignore_locators=[page.locator("xpath=" + x) for x in obs.secret_xpaths])
                raw = from_stagehand(list(res.data), obs)
                source = "stagehand"
            except Exception:  # noqa: BLE001 - observe failure falls back to plain code
                raw = []
        if not raw:
            raw, source = dom_candidates(obs), "dom"
        cands, mapping = normalise(raw, exclude=denied)
        return cands, mapping, source

    # --------------------------------------------------------------- main
    async def run(self, run: Run, page: Any, sh: Any | None = None, context: Any | None = None) -> LoopResult:
        t0 = time.monotonic()
        n_obs = n_act = 0
        no_progress = 0
        last_fp = ""
        denied: set[str] = set()
        allowed = run.plan.allowed_domains
        run.phase = "browser"
        self.context = context
        self._allowed = allowed
        self._page = page
        self._gates: list = []
        await self._domain_guard(run, on=True)
        self._cp(run, "browser_loop_started", {"allowed_domains": allowed, "domain_guard": context is not None})

        while True:
            if (
                n_obs >= self.budget.max_observations
                or n_act >= self.budget.max_actions
                or time.monotonic() - t0 > self.budget.max_seconds
            ):
                self._cp(run, "loop_budget_exhausted", {"observations": n_obs, "actions": n_act})
                return LoopResult("budget", "browser-loop budget exhausted", n_obs, n_act)

            # 1. look (plain code)
            obs = await observe_page(page, self.masker)
            n_obs += 1
            if run.browser:
                run.browser.last_url = obs.url_masked
            gates = check(obs, allowed)
            self._gates = gates
            self._cp(run, "page_observed", {**obs.summary(), "gates": [f"{g.kind}:{g.action}" for g in gates]})

            # 2. hard checks
            if any(g.kind == "off_allow_list" for g in gates):
                self._step(run, "left the allowed domains; going back", "system", "denied", [obs.url_masked])
                await page.go_back()
                await page.wait_for_timeout(self.budget.settle_ms)
                obs2 = await observe_page(page, self.masker)
                if not host_allowed(obs2.url, allowed):
                    g = next(g for g in gates if g.kind == "off_allow_list")
                    if await self._handoff(run, "DO", "off_allow_list", g.reason, g.evidence, obs) is None:
                        return LoopResult("handoff_pending", g.reason, n_obs, n_act)
                continue
            auto = [g for g in gates if g.action == "AUTO"]
            if auto:
                g = auto[0]
                seq = self.store.begin_action(run, "cookie_limited_option", {"evidence": g.evidence})
                await page.locator("xpath=" + g.target_xpath).click()
                await page.wait_for_timeout(self.budget.settle_ms)
                self.store.end_action(run, seq, "done")
                self._step(run, f"chose the most limited cookie option ({g.evidence[-1]})", "agent", "done", g.evidence)
                n_act += 1
                continue
            stop = blocking(gates)
            if stop:
                g = stop[0]
                if g.action == "BLOCK":
                    run.add_blocker(
                        Blocker(
                            kind=g.kind,
                            description=g.reason,
                            evidence=[Evidence(kind="observed", text=e, url=obs.url_masked) for e in g.evidence],
                            who_must_act="owner",
                            next_steps=[
                                "Complete the provider's verification outside CredAgent "
                                f"(the agent never does this), then run: credagent resume {run.id}"
                            ],
                        )
                    )
                    self._step(run, "stopped: " + g.reason, "system", "denied", g.evidence)
                    self._cp(run, "blocked", {"kind": g.kind})
                    return LoopResult("blocked", g.reason, n_obs, n_act)
                if await self._handoff(run, "DO", g.kind, g.reason, g.evidence, obs) is None:
                    return LoopResult("handoff_pending", g.reason, n_obs, n_act)
                continue
            if any(g.kind == "credential_shown" for g in gates):
                self._step(
                    run,
                    "credential page reached (capture is implemented in Sprint 5)",
                    "system",
                    "done",
                    [g.evidence[0] for g in gates if g.kind == "credential_shown"],
                )
                self._cp(run, "credential_page_reached", {})
                return LoopResult("credential_page", "credential page reached", n_obs, n_act)

            fp = obs.fingerprint()
            no_progress = no_progress + 1 if fp == last_fp else 0
            last_fp = fp
            if no_progress >= self.budget.max_no_progress:
                if await self._stuck(run, obs, "no progress on this page") is None:
                    return LoopResult("stuck", "no progress", n_obs, n_act)
                no_progress = 0
                continue

            # 3. candidates + Jev (one request, five decisions)
            goal = self._goal(run)
            cands, mapping, source = await self._candidates(sh, page, goal, obs, denied)
            filled = [i["label"][:60] for i in obs.inputs if i["value_len"] and i["type"] not in ("checkbox", "radio")]
            status = ("Form status: already filled: " + "; ".join(filled) + "\n") if filled else ""
            state = PageState(
                step_goal=goal,
                url=obs.url_masked,
                title=obs.title,
                visible_text=(status + obs.text)[:6000],
                candidates=cands,
            )
            log = DecisionLog()
            d = self.jev.decide(state, log)
            # 4. fallbacks
            try:
                d = apply_fallbacks(
                    d,
                    state,
                    log,
                    self.reasoner,
                    code_gates_found=bool(stop),
                    credential_on_page=any(g.kind == "credential_shown" for g in gates),
                    model=self.llm_model,
                )
            except ServiceDown as exc:
                self._cp(run, "service_unavailable", {"detail": str(exc)})
                return LoopResult("failed", "service unavailable: FastRouter (Jev and LLM)", n_obs, n_act)
            el, act = d["element_selection"].value, d["action_selection"].value
            self._cp(
                run,
                "decisions",
                {
                    "goal": goal,
                    "candidates": len(cands),
                    "source": source,
                    "element": el,
                    "action": act,
                    "blocker": d["blocker_detection"].value,
                    "risk": d["risk_assessment"].value,
                    "risk_uncertain": d["risk_assessment"].uncertain,
                    **log.as_dict(),
                },
            )

            if d["blocker_detection"].value is True:
                terms = [g for g in gates if g.kind == "terms"]
                if terms:  # code knows exactly what the person must do here
                    why, kind_, ev_ = terms[0].reason, "terms", terms[0].evidence
                else:
                    why = "Jev/LLM judged that a person needs to act on this page" + (
                        f" ({log.llm_reason[:120]})" if log.llm_reason else ""
                    )
                    kind_, ev_ = "unexpected", [f"title: {obs.title}"]
                if await self._handoff(run, "DO", kind_, why, ev_, obs, page=page, gates=gates) is None:
                    return LoopResult("handoff_pending", why, n_obs, n_act)
                continue
            if act == "step_complete":
                self._step(run, f"step complete: {goal[:120]}", "agent", "done", inferred=["decided by Jev"])
                run.plan_cursor += 1
                self._cp(run, "plan_step_complete", {"cursor": run.plan_cursor})
                continue
            if act == "wait":
                await page.wait_for_timeout(1500)
                continue
            if act == "go_back":
                seq = self.store.begin_action(run, "go_back", {})
                await page.go_back()
                await page.wait_for_timeout(self.budget.settle_ms)
                self.store.end_action(run, seq, "done")
                self._step(run, "went back", "agent", "done")
                n_act += 1
                continue
            if act == "stuck" or el in (None, NONE_OPTION) or el not in mapping:
                if await self._stuck(run, obs, "Jev found no suitable element for the current step") is None:
                    return LoopResult("stuck", "no suitable element", n_obs, n_act)
                continue

            # 5. policy (code) — the model's choice is an input, never a permission
            cand = mapping[el]
            if cand.method in ("fill", "select") and cand.filled:
                # Code rule (D-044): re-filling a field that already holds a value is a no-op, so the step is done.
                self._step(
                    run,
                    f"step complete: {cand.description} (code: field already has a value)",
                    "agent",
                    "done",
                    [cand.description],
                )
                run.plan_cursor += 1
                self._cp(run, "plan_step_complete", {"cursor": run.plan_cursor, "by": "code: field already filled"})
                continue
            value = self.values.get(cand.field_key) if cand.method == "fill" else None
            proposed = ProposedAction(
                method=cand.method,
                xpath=cand.xpath,
                description=cand.description,
                href=cand.href,
                field_key=cand.field_key,
                value=value,
            )
            verdict = evaluate(
                proposed,
                obs,
                gates,
                allowed,
                risk=d["risk_assessment"].value,
                risk_uncertain=d["risk_assessment"].uncertain,
            )
            self._cp(
                run,
                "policy",
                {
                    "candidate": cand.description,
                    "verdict": verdict.decision,
                    "reason": verdict.reason,
                    "category": verdict.category,
                },
            )
            if verdict.decision == "deny":
                denied.add(cand.xpath)
                self._step(run, f"denied: {cand.description}", "system", "denied", [verdict.reason])
                continue
            if verdict.decision == "DO":
                gate_ev = [e for g in gates if g.kind == verdict.category for e in g.evidence] or [cand.description]
                if (
                    await self._handoff(
                        run,
                        "DO",
                        verdict.category,
                        verdict.reason,
                        gate_ev,
                        obs,
                        after="Re-check the page (the agent never repeats your action), then continue.",
                    )
                    is None
                ):
                    return LoopResult("handoff_pending", verdict.reason, n_obs, n_act)
                continue
            if verdict.decision == "DECIDE":
                value = await self._decide(run, cand, verdict, obs)
                if value is None:
                    return LoopResult("handoff_pending", verdict.reason, n_obs, n_act)
                if value == "__skip__":
                    denied.add(cand.xpath)
                    self._step(run, f"left unticked (person's choice): {cand.description}", "system", "skipped")
                    continue
                if value == "__declined__":
                    run.add_blocker(
                        Blocker(
                            kind="other",
                            description=f"The person declined: {cand.description}",
                            who_must_act="person",
                            next_steps=[f"Re-run when ready: credagent resume {run.id}"],
                        )
                    )
                    return LoopResult("blocked", f"person declined: {cand.description}", n_obs, n_act)

            # 6. act  7. record  8. checkpoint
            seq = self.store.begin_action(run, cand.method, {"target": cand.description, "field": cand.field_key})
            try:
                await self._act(page, cand, value)
            except Exception as exc:  # noqa: BLE001 - recorded, loop continues from a fresh observation
                self.store.end_action(run, seq, "failed", {"error": type(exc).__name__})
                denied.add(cand.xpath)
                self._step(run, f"{cand.method} failed: {cand.description}", "agent", "failed", [type(exc).__name__])
                continue
            self.store.end_action(run, seq, "done")
            n_act += 1
            shown = f"{cand.method} {cand.description}" + (f" = {value}" if value and cand.field_key else "")
            self._step(
                run,
                shown,
                "agent",
                "done",
                [f"policy: {verdict.reason}"],
                inferred=[f"element chosen by {'LLM fallback' if log.fallbacks else 'Jev'}"],
            )
            self._cp(run, "action_recorded", {"candidates_source": source})

    async def _decide(self, run: Run, cand: RawCandidate, verdict: Verdict, obs: Observation) -> str | None:
        if cand.method == "select":
            inp = next((i for i in obs.inputs if i["xpath"] == cand.xpath), None)
            opts = [o for o in (inp["options"] if inp else []) if o and not o.lower().startswith("choose")]
            if len(opts) < 2:
                opts = opts + ["Stop here"] if opts else ["Stop here", "Skip"]
            ans = await self._handoff(
                run,
                "DECIDE",
                "other",
                f"Choose a value for {cand.description}.",
                [cand.description],
                obs,
                instruction="Pick the option the integration needs.",
                options=opts,
                after="Select your choice and continue.",
            )
            return None if ans is None else ("__declined__" if ans in ("Stop here", "Skip") else ans)
        if cand.method == "check":
            ans = await self._handoff(
                run,
                "DECIDE",
                verdict.category,
                verdict.reason,
                [cand.description],
                obs,
                instruction=f"Should the agent tick: {cand.description}?",
                options=["Yes, tick it", "No, leave it unticked"],
                after="Tick it (if yes) and continue with the rest of the form.",
            )
            return None if ans is None else ("__skip__" if ans.startswith("No") else "")
        ans = await self._handoff(
            run,
            "DECIDE",
            verdict.category,
            verdict.reason,
            [cand.description],
            obs,
            instruction=f"Should the agent do this: {cand.description}?",
            options=["Yes, do it", "No, stop here"],
            after="Do it (if yes) and continue.",
        )
        if ans is None:
            return None
        return "__declined__" if ans.startswith("No") else (self.values.get(cand.field_key) or "")

    async def _stuck(self, run: Run, obs: Observation, why: str) -> str | None:
        if self.reasoner is not None:
            try:
                replan(run, self.reasoner, obs.text, model=self.llm_model)
                self._step(run, f"re-planned ({run.replans_used} of 2): {why}", "agent", "done")
                self._cp(run, "replanned", {"replans_used": run.replans_used})
                return "replanned"
            except (ReplanLimitReached, ReplanInfeasible) as exc:
                self._step(run, f"cannot re-plan: {exc}", "system", "failed")
        return await self._handoff(run, "DO", "unexpected", f"The agent is stuck: {why}.", [f"title: {obs.title}"], obs)


_BLOCKER_KINDS = {
    "sign_in",
    "account_creation",
    "verification_code",
    "two_factor",
    "captcha",
    "identity_verification",
    "business_verification",
    "payment",
    "terms",
    "cookie_consent",
    "provider_review",
    "paid_plan",
    "partner_approval",
    "policy_denied",
    "off_allow_list",
    "unexpected",
    "service_unavailable",
    "budget_exhausted",
    "replan_limit",
    "app_not_identified",
    "other",
}
