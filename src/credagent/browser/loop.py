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
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from credagent.browser.candidates import (
    FieldValues,
    RawCandidate,
    dom_candidates,
    field_key_for,
    from_stagehand,
    normalise,
    use_stagehand,
)
from credagent.browser.observe import Observation, observe_page
from credagent.decisions.client import DecisionLog, ServiceDown, apply_fallbacks, toward_goal
from credagent.decisions.jev import NONE_OPTION, PageState
from credagent.handoff.cards import render_card
from credagent.policy.engine import CREATE_RE, HUMAN_ONLY_FIELDS, ProposedAction, Verdict, evaluate
from credagent.policy.hard_checks import blocking, check, host_allowed
from credagent.reasoning.fastrouter import ModelCallError, ServiceUnavailable
from credagent.reasoning.replan import ReplanInfeasible, ReplanLimitReached, normalise_steps, replan
from credagent.secrets.capture import CaptureResult, capture
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
REVEAL_RE = re.compile(r"^(view|show|reveal|display)\b[^\n]{0,30}\b(secret|key|token)s?$", re.I)
NEVER_REVEAL = re.compile(r"regenerate|rotate|reset|new|create|delete|revoke", re.I)


_GOAL_WORD = re.compile(r"[a-z0-9]{3,}")
_GOAL_STOP = {"the", "and", "for", "with", "this", "that", "page", "click", "open", "your", "from", "into", "left",
              "side", "sidebar", "application", "button", "link", "field", "text"}


def rank_for_goal(cands: list, goal: str) -> list:
    """Order the page's own candidates by how well they match the current step, before the list is capped at
    20 (D-066). On Discord's app page nine fields and eleven buttons came before the sidebar's "OAuth2" link,
    so the one element the step named was never offered to Jev. Stable: equal scores keep page order."""
    words = set(_GOAL_WORD.findall(goal.lower())) - _GOAL_STOP

    def score(c) -> int:
        desc = c.description.lower()
        hit = sum(1 for w in words if w in desc)
        return -(hit * 2 + (1 if c.method == "click" and hit else 0))

    return sorted(cands, key=score)


def reveal_control(obs: Observation) -> dict | None:
    """A button or link that only shows the secret (e.g. Spotify's "View client secret")."""
    for c in list(obs.buttons) + list(obs.links):
        text = (c.get("text") or "").strip()
        if REVEAL_RE.match(text) and not NEVER_REVEAL.search(text) and not c.get("disabled"):
            return {"xpath": c["xpath"], "text": text, "href": c.get("href")}
    return None
HIDDEN_VALUE_INSTRUCTION = (
    "The secret is no longer shown (providers show it only once). To get a working one, click “Regenerate "
    "secret” in the browser yourself: the old secret stops working, so this is your decision. The agent then "
    "captures the new one by plain code without showing it. If you do not want to regenerate, press Ctrl+C: the "
    "run is saved and the credential is reported as not captured."
)


def terms_instruction(obs: Observation, gates: list) -> tuple[str, str]:
    """Exact instruction for a terms gate, naming the box and the button, and what is still missing.
    Returns (instruction, still_missing)."""
    g = next((x for x in gates if x.kind == "terms"), None)
    box = next((i for i in obs.inputs if g and i["xpath"] == g.target_xpath), None)
    form = (g.form_xpath if g else None) or (box["form"] if box else None)
    submit = next((b for b in obs.buttons if form and b["form"] == form and b["type"] in ("submit", "")), None)
    btn = f"“{submit['text']}”" if submit and submit["text"] else "the form's submit button"
    stop = " If you do not agree, press Ctrl+C: nothing is submitted and the run is saved."
    empty = [
        i["label"][:60]
        for i in obs.inputs
        if form
        and i["form"] == form
        and i["required"]
        and not i["value_len"]
        and i["type"] not in ("checkbox", "radio", "submit", "button", "hidden")
    ]
    if empty:
        fields = ", ".join(f"“{e}”" for e in empty)
        btn = f"{btn} (first fill the required field(s) the agent could not: {fields})"
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


IMPLIED_BUTTON = re.compile(r"by (clicking|selecting|tapping|pressing) [“\"'‘]?([A-Za-z][\w &-]{0,30}?)[”\"'’]?[,.]?\s+"
                            r"you (agree|accept|consent)", re.I)


def terms_submit_text(obs: Observation, gates: list) -> str | None:
    """The button that submits the terms form: the form's submit button, or the one named in the agreement
    wording ("By clicking Create, you agree…")."""
    form = terms_form(obs, gates)
    submit = next((b for b in obs.buttons if form and b["form"] == form and b["type"] in ("submit", "")), None)
    if submit and submit["text"]:
        return submit["text"]
    g = next((x for x in gates if x.kind == "terms"), None)
    for text in (g.evidence if g else []):
        m = IMPLIED_BUTTON.search(text)
        if m:
            return m.group(2).strip()
    return None


def terms_form(obs: Observation, gates: list) -> str | None:
    g = next((x for x in gates if x.kind == "terms"), None)
    box = next((i for i in obs.inputs if g and i["xpath"] == g.target_xpath), None)
    return (g.form_xpath if g else None) or (box["form"] if box else None)


def form_summary_text(summary: dict[str, list[str]]) -> str:
    parts = []
    if summary["filled"]:
        parts.append("The agent filled: " + ", ".join(summary["filled"]) + ".")
    if summary["left_empty"]:
        parts.append(
            "Left empty (no approved value; fill them yourself if needed): " + ", ".join(summary["left_empty"]) + "."
        )
    if summary["defaults"]:
        parts.append("Options left at their defaults: " + ", ".join(summary["defaults"]) + ".")
    return (" " + " ".join(parts)) if parts else ""


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
    secret_store: Any | None = None  # SecretFileStore: capture on the credential page (None = do not capture)
    in_doubt: dict | None = None  # resume: last action started before the interruption with no recorded end
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
        # Capture and the live test are done by code, never browser goals: aim at the next browser step.
        while run.plan_cursor < len(steps) and steps[run.plan_cursor].kind in ("capture", "verify") and any(
                x.kind not in ("capture", "verify") for x in steps[run.plan_cursor:]):
            run.plan_cursor += 1
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
        if kind == "DO" and blocker_kind == "terms" and page is not None:
            obs, gates, status, summary = await self._complete_form(run, page, obs, gates, terms_form(obs, gates))
            if status != "ok":
                if status == "declined":
                    self._stop = "person declined a choice in the form"
                return None
            if instruction is None:
                instruction, _ = terms_instruction(obs, gates)
                instruction += form_summary_text(summary)
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
                    w0 = time.monotonic()
                    done = self.io.wait_enter("Press Enter when you are done (Ctrl+C to stop; the run is saved)")
                    if inspect.isawaitable(done):
                        done = await done
                    self._waited = getattr(self, "_waited", 0.0) + time.monotonic() - w0
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
            submit = terms_submit_text(obs, gates) if blocker_kind == "terms" else None
            if submit and CREATE_RE.search(f"button '{submit}'") and page is not None:
                try:
                    moved = (await page.url()) != obs.url
                except Exception:  # noqa: BLE001 - unknown: assume the form was submitted (the safe side)
                    moved = True
                if moved:
                    self._mark_created(run, f"an app (created when the person clicked “{submit}”)")
            return "done"
        w0 = time.monotonic()
        answer = self.io.choose("Your decision", h.options)
        if inspect.isawaitable(answer):
            answer = await answer
        self._waited = getattr(self, "_waited", 0.0) + time.monotonic() - w0
        if answer is None:
            return None
        run.resolve_handoff(h.id, answer=answer)
        self._step(run, f"person decided: {answer}", "person", "done")
        self._cp(run, "handoff_resolved", {"handoff_id": h.id, "answer": answer})
        return answer

    async def _complete_form(
        self, run: Run, page: Any, obs: Observation, gates: list, form: str | None
    ) -> tuple[Observation, list, str, dict[str, list[str]]]:
        """Before a form is submitted (by the person at a terms handoff, or by the agent), complete everything
        the agent may legitimately fill (D-050). Policy decides every fill. Never overwrites a value.

        Returns (obs, gates, status, summary); status is "ok", "pending" (a DECIDE was left unanswered)
        or "declined"; summary lists what was filled, left empty, left at defaults, or left for the person."""
        summary: dict[str, list[str]] = {"filled": [], "left_empty": [], "defaults": [], "for_you": []}
        if not form:
            return obs, gates, "ok", summary
        terms_xpaths = {g.target_xpath for g in gates if g.kind == "terms" and g.target_xpath}
        used_keys: set[str | None] = set()
        changed = False
        for i in list(obs.inputs):
            if i["form"] != form or i["type"] in ("hidden", "submit", "button", "image", "reset"):
                continue
            if i["readonly"] or i["value_secretlike"] or i["xpath"] in obs.secret_xpaths:
                continue
            label = i["label"] or i["name"] or i["type"]
            if i["xpath"] in terms_xpaths:
                summary["for_you"].append(f"“{label[:70]}”")
                continue
            if HUMAN_ONLY_FIELDS.search(label):
                summary["for_you"].append(f"“{label[:70]}”")
                continue
            if i["type"] in ("checkbox", "radio"):
                summary["defaults"].append(f"“{label[:60]}” ({'ticked' if i['checked'] else 'unticked'})")
                continue
            if i["value_len"]:
                if i["tag"] != "select":
                    summary["filled"].append(f"“{label[:60]}”")
                    used_keys.add(field_key_for(label))
                continue
            if i["tag"] == "select":
                cand = RawCandidate(i["xpath"], "select", f"dropdown '{label}'")
                act = ProposedAction(method="select", xpath=i["xpath"], description=cand.description)
                verdict = evaluate(act, obs, gates, self._allowed, risk="reversible", risk_uncertain=False)
                if verdict.decision == "DECIDE":
                    choice = await self._decide(run, cand, verdict, obs)
                    if choice is None:
                        return obs, gates, "pending", summary
                    if choice == "__declined__":
                        return obs, gates, "declined", summary
                    seq = self.store.begin_action(run, "select", {"target": cand.description, "why": "complete form"})
                    await page.locator("xpath=" + i["xpath"]).select_option(choice)
                    self.store.end_action(run, seq, "done")
                    self._step(run, f"select {cand.description} = {choice} (your choice)", "agent", "done")
                    summary["filled"].append(f"“{label[:60]}” (your choice)")
                    changed = True
                continue
            key = field_key_for(label)
            value = self.values.get(key)
            if key and key in used_keys:  # D-069: one value once per form (not the callback into every empty row)
                continue
            if not value:
                summary["left_empty"].append(f"“{label[:60]}”" + (" (required)" if i["required"] else ""))
                continue
            used_keys.add(key)
            act = ProposedAction(
                method="fill", xpath=i["xpath"], description=f"text field '{label}'", field_key=key, value=value
            )
            verdict = evaluate(act, obs, gates, self._allowed, risk="reversible", risk_uncertain=False)
            if verdict.decision != "allow":
                summary["for_you"].append(f"“{label[:60]}”")
                continue
            seq = self.store.begin_action(
                run, "fill", {"target": act.description, "field": key, "why": "complete form"}
            )
            await page.locator("xpath=" + i["xpath"]).fill(value)
            self.store.end_action(run, seq, "done")
            self._step(
                run,
                f"fill {act.description} = {value} (completing the form before it is submitted)",
                "agent",
                "done",
                [f"policy: {verdict.reason}"],
            )
            summary["filled"].append(f"“{label[:60]}”")
            changed = True
        self._cp(run, "form_completed", summary)
        if changed:
            await page.wait_for_timeout(self.budget.settle_ms)
            obs = await observe_page(page, self.masker)
            gates = check(obs, self._allowed)
        return obs, gates, "ok", summary

    async def _save_if_step_says_so(self, run: Run, page: Any, obs: Observation, gates: list, goal: str,
                                    saved_on: set[str]) -> bool:
        """D-069: a step that says "… and save" is not complete while the page's Save button is unclicked. After the
        agent typed into a field on this page, click the visible Save / Save Changes button once (policy decides)."""
        if not re.search(r"\bsave\b", goal, re.I) or obs.url in saved_on:
            return False
        typed = any(s.action.startswith("fill ") and s.actor == "agent" for s in run.steps[-6:])
        btn = next((b for b in obs.buttons if not b["disabled"]
                    and re.fullmatch(r"save( changes)?", (b["text"] or "").strip(), re.I)), None)
        if not (typed and btn):
            return False
        saved_on.add(obs.url)
        desc = f"button '{btn['text']}'"
        verdict = evaluate(ProposedAction(method="click", xpath=btn["xpath"], description=desc), obs, gates,
                           self._allowed, risk="reversible", risk_uncertain=False, already_created=bool(run.created))
        self._cp(run, "policy", {"candidate": desc, "verdict": verdict.decision, "reason": verdict.reason,
                                 "category": verdict.category})
        if verdict.decision != "allow":
            return False
        seq = self.store.begin_action(run, "click", {"target": desc, "why": "the step says save"})
        await page.locator("xpath=" + btn["xpath"]).click()
        await page.wait_for_timeout(self.budget.settle_ms)
        self.store.end_action(run, seq, "done")
        self._step(run, f"click {desc} (the step says to save)", "agent", "done")
        # The step said "enter … and save": filled and saved, so it is complete (no second Save, D-069).
        self._step(run, f"step complete: {goal[:120]} (code: filled and saved)", "agent", "done")
        run.plan_cursor += 1
        self._cp(run, "plan_step_complete", {"cursor": run.plan_cursor, "by": "code: filled and saved"})
        return True

    def _mark_created(self, run: Run, what: str) -> None:
        """Record that this run created an app at the provider (D-063): never create a second one, and move
        the plan past its create step(s) so the agent does not go back to them."""
        first = not run.created
        if first:
            run.created.append(what[:200])
        # Move past the create step only if that is the step the run is on; nothing else moves the cursor.
        # Later steps may mention creating too ("generate a new client secret"), and must not be skipped (D-064,
        # D-067). A capture elsewhere (e.g. on resume) records the app but leaves the plan where it is.
        cur = run.plan.steps[run.plan_cursor] if run.plan_cursor < len(run.plan.steps) else None
        if cur is not None and cur.kind in ("click", "handoff", "navigate", "fill") and CREATE_RE.search(
                cur.description):
            run.plan_cursor += 1
        if first:
            self._step(run, f"recorded: this run created {what[:160]}; it will not create another", "system",
                       "done")
            self._cp(run, "resource_created", {"what": what[:200], "cursor": run.plan_cursor})

    async def _reveal(self, run: Run, page: Any, obs: Observation, gates: list, ctl: dict) -> bool:
        """Click a read-only "View/Show secret" control so the credential being created becomes readable
        by plain code. Policy still decides; a regenerate/reset control never matches (see reveal_control)."""
        desc = f"{'link' if ctl.get('href') else 'button'} '{ctl['text'][:60]}'"
        action = ProposedAction(method="click", xpath=ctl["xpath"], description=desc, href=ctl.get("href"))
        verdict = evaluate(action, obs, gates, self._allowed, risk="read_only", risk_uncertain=False)
        self._cp(run, "policy", {"candidate": desc, "verdict": verdict.decision, "reason": verdict.reason,
                                 "category": verdict.category})
        if verdict.decision != "allow":
            return False
        seq = self.store.begin_action(run, "click", {"target": desc, "why": "show the new credential"})
        await page.locator("xpath=" + ctl["xpath"]).click()
        await page.wait_for_timeout(self.budget.settle_ms)
        self.store.end_action(run, seq, "done")
        self._step(run, f"clicked {desc} to show the new credential (read-only; nothing is changed)", "agent",
                   "done")
        return True

    async def _capture(self, run: Run, page: Any, obs: Observation) -> CaptureResult:
        """Plain-code capture of the credential on this page (spec §6.9). Values go straight to the
        owner-only store; run state gets references and masked displays only."""
        seq = self.store.begin_action(run, "capture_credential", {"elements": len(obs.secret_xpaths)})
        res = await capture(page, obs, store=self.secret_store, masker=self.masker, run_id=run.id,
                            plan_kind=run.plan.credential_kind)
        self.store.end_action(run, seq, "done", {"observed": res.observed()})
        if res.credential is not None:
            self._mark_created(run, "an app (its credential page was reached)")
            if run.credential is not None and not res.has_secret:
                res.credential.parts = {**run.credential.parts, **res.credential.parts}
            run.credential = res.credential
            run.observed_limitations = res.limitations
            shown = ", ".join(f"{k} {p.masked_display}" for k, p in res.credential.parts.items())
            self._step(run, f"captured the credential by plain browser code ({', '.join(res.captured)}); "
                       "stored outside the repo", "agent", "done", [res.observed(), shown] + res.limitations[:2])
        else:
            self._step(run, "credential-like value(s) seen, but nothing labelled to capture; continuing the plan",
                       "system", "skipped", [res.observed()])
        self._cp(run, "credential_captured" if res.credential else "credential_not_captured",
                 {"parts": res.captured, "unlabelled": res.unlabelled, "ambiguous": res.ambiguous,
                  "secret_hidden": res.secret_hidden, "limitations": res.limitations})
        return res

    async def _still_needed(self, page: Any | None, before: Observation, blocker_kind: str) -> str | None:
        """Re-check the page after the person pressed Enter. None = the handoff's condition is resolved."""
        if page is None:
            return None
        try:
            now = await observe_page(page, self.masker)
        except Exception:  # noqa: BLE001 - if the page cannot be read, let the main loop re-observe
            return None
        if blocker_kind == "secret_hidden":
            if len(now.secret_xpaths) > len(before.secret_xpaths) or now.url != before.url:
                return None
            return "the secret is still hidden (click “Regenerate secret” in the browser if you want a new one)"
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
        # Stagehand's few, goal-ranked candidates first, then the page's own links/buttons/fields, so a plain
        # link Stagehand did not return (e.g. an app card on a list page) is still offered (D-065).
        dom = rank_for_goal(dom_candidates(obs), goal)
        if raw:
            have = {r.xpath for r in raw}
            raw = raw + [d for d in dom if d.xpath not in have]
            source = "stagehand+dom"
        else:
            raw, source = dom, "dom"
        # Help the decider find the app this run created on a list page (D-064): mark it by its name.
        if self.values.app_name:
            from dataclasses import replace as _replace

            raw = [_replace(r, description=r.description + " (the app this run created)")
                   if r.method == "click" and self.values.app_name in r.description else r for r in raw]
        cands, mapping = normalise(raw, exclude=denied)
        return cands, mapping, source

    # --------------------------------------------------------------- main
    async def run(self, run: Run, page: Any, sh: Any | None = None, context: Any | None = None) -> LoopResult:
        self._stop: str | None = None
        result = await self._run(run, page, sh, context)
        if self._stop:  # a person's "no" ends the run honestly as blocked, not as a pending handoff
            run.add_blocker(
                Blocker(
                    kind="other",
                    description=self._stop,
                    who_must_act="person",
                    next_steps=["Re-run when you are ready to make that choice."],
                )
            )
            return LoopResult("blocked", self._stop, result.observations, result.actions)
        return result

    async def _run(self, run: Run, page: Any, sh: Any | None, context: Any | None) -> LoopResult:
        t0 = time.monotonic()
        n_obs = n_act = 0
        no_progress = 0
        last_fp = ""
        denied: set[str] = set()
        revealed = False
        seen_cred: set[tuple] = set()
        toward_tried: set[str] = set()
        clicks: dict[tuple[str, str], int] = {}
        saved_on: set[str] = set()
        self._waited = 0.0  # seconds spent waiting for the person: not counted against the time budget
        allowed = run.plan.allowed_domains
        run.phase = "browser"
        self.context = context
        self._allowed = allowed
        self._page = page
        self._gates: list = []
        if not run.created and run.credential is not None:
            # Resumed after an interruption: an app was already created earlier in this run (D-063).
            self._mark_created(run, "an app (created earlier in this run, before the interruption)")
        steps2, cursor2 = normalise_steps(run.plan.steps, run.plan_cursor)
        if [x.id for x in steps2] != [x.id for x in run.plan.steps]:
            # Older re-plans could leave live-test steps in the middle (D-065): put code-owned steps last.
            self._cp(run, "plan_normalised",
                     {"steps": len(steps2), "cursor_from": run.plan_cursor, "cursor_to": cursor2})
            run.plan = run.plan.model_copy(update={"steps": steps2})
            run.plan_cursor = cursor2
        cur = run.plan.steps[run.plan_cursor] if run.plan_cursor < len(run.plan.steps) else None
        has_secret = bool(run.credential and set(run.credential.parts) & {"client_secret", "api_key", "token",
                                                                          "signing_secret"})
        if run.created and not has_secret and cur is not None:
            # Starting (or resuming) with an app that exists but no secret captured: continue from the first step
            # after the create step. Steps that are already done are marked complete quickly; a second app can
            # never be created (D-063). This repairs a saved cursor that skipped console steps (D-064/D-065).
            # The end of the creation phase: the last create action before the code-owned steps, ignoring
            # conditional steps such as "If no app exists yet, click 'New Application'" (D-064, D-068).
            first = max((i for i, st in enumerate(run.plan.steps)
                         if st.kind in ("click", "handoff", "navigate", "fill") and CREATE_RE.search(st.description)
                         and not st.description.lstrip().lower().startswith("if ")), default=None)
            if first is not None and first + 1 < run.plan_cursor:
                self._cp(run, "plan_cursor_corrected", {"from": run.plan_cursor, "to": first + 1})
                self._step(run, f"plan position corrected: back to step {first + 2} (the console steps after "
                           "creating the app are not done yet)", "system", "done")
                run.plan_cursor = first + 1
        self._maybe_created = not run.created and any(
            h.blocker_kind == "terms" and h.status == "completed" for h in run.handoffs)
        await self._domain_guard(run, on=True)
        self._cp(run, "browser_loop_started", {"allowed_domains": allowed, "domain_guard": context is not None})

        while True:
            if (
                n_obs >= self.budget.max_observations
                or n_act >= self.budget.max_actions
                or time.monotonic() - t0 - self._waited > self.budget.max_seconds
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
            cred_key = (obs.url, tuple(sorted(obs.secret_xpaths)))
            if any(g.kind == "credential_shown" for g in gates) and cred_key not in seen_cred:
                self._cp(run, "credential_page_reached", {})
                if self.secret_store is None:
                    self._step(run, "credential page reached (no secret store: nothing captured)", "system", "done",
                               [g.evidence[0] for g in gates if g.kind == "credential_shown"])
                    return LoopResult("credential_page", "credential page reached", n_obs, n_act)
                seen_cred.add(cred_key)  # look at each credential-like page state once, never re-capture it
                res = await self._capture(run, page, obs)
                if res.has_secret:
                    return LoopResult("credential_page", "credential captured", n_obs, n_act)
                if not revealed:
                    ctl = reveal_control(obs)
                    if ctl is not None and await self._reveal(run, page, obs, gates, ctl):
                        revealed = True
                        n_act += 1
                        continue  # re-observe; the next pass captures what the page now shows
                if res.secret_hidden:
                    if await self._handoff(
                        run, "DO", "secret_hidden",
                        "The secret is no longer shown on this page (providers show it only once).",
                        [res.observed()], obs, instruction=HIDDEN_VALUE_INSTRUCTION,
                        after="Re-check the page and capture the new secret by plain code, without showing it.",
                    ) is None:
                        return LoopResult("handoff_pending", "secret hidden", n_obs, n_act)
                    continue
                # No secret yet (e.g. an unlabelled ID on a list page, or a client ID whose secret needs another
                # step such as "Reset Secret"): keep following the plan. Seeing a credential-like value is not
                # the same as having the credential (D-061).

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
            acting = d["action_selection"].uncertain or d["action_selection"].value == "proceed"
            if d["element_selection"].uncertain and acting and self.reasoner is not None:
                # Spec §6.5: the element-selection fallback is "LLM re-observes and picks". Look again first;
                # if the page changed, start over (hard checks run again) instead of picking from stale elements.
                await page.wait_for_timeout(self.budget.settle_ms)
                obs2 = await observe_page(page, self.masker)
                n_obs += 1
                if obs2.fingerprint() != fp:
                    self._cp(run, "re_observed", {"page_changed": True})
                    continue
                cands, mapping, source = await self._candidates(sh, page, goal, obs2, denied)
                obs = obs2
                state = state.model_copy(update={"candidates": cands})
                log.fallbacks.append("re_observed")
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

            terms = [g for g in gates if g.kind == "terms"]
            if d["blocker_detection"].value is True and terms:
                # PRD §9: the agent fills every other field first; the person's part is the terms control and
                # the agreement-carrying submit, which policy hands off when the agent reaches them (D-049).
                self._cp(run, "blocker_deferred", {"reason": "terms only: filling the other fields first"})
            elif d["blocker_detection"].value is True:
                why = "Jev/LLM judged that a person needs to act on this page" + (
                    f" ({log.llm_reason[:120]})" if log.llm_reason else ""
                )
                step = run.plan.steps[run.plan_cursor] if run.plan_cursor < len(run.plan.steps) else None
                instruction = (
                    f"The agent's current step is: “{step.description[:220]}” It looks like this needs you. Do "
                    "the part only a person may do (e.g. sign in, a code, a CAPTCHA) in the browser window. If it "
                    "is already done, just press Enter."
                    if step else None
                )
                if await self._handoff(run, "DO", "unexpected", why, [f"title: {obs.title}"], obs,
                                       instruction=instruction) is None:
                    return LoopResult("handoff_pending", why, n_obs, n_act)
                continue
            if act == "step_complete" and await self._save_if_step_says_so(run, page, obs, gates, goal, saved_on):
                n_act += 1
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
                pick = None
                if self.reasoner is not None and fp not in toward_tried:
                    # D-068: the step's own element is not here (e.g. "open OAuth2" on the app list). Ask once per
                    # page state for the click that leads toward it before giving up.
                    toward_tried.add(fp)
                    pick, why_nav = toward_goal(state, self.reasoner, self.llm_model)
                    self._cp(run, "toward_goal", {"element": pick, "reason": why_nav[:200]})
                if pick is None:
                    if await self._stuck(run, obs, "Jev found no suitable element for the current step") is None:
                        return LoopResult("stuck", "no suitable element", n_obs, n_act)
                    continue
                el, act = pick, "proceed"

            # 5. policy (code) — the model's choice is an input, never a permission
            cand = mapping[el]
            if cand.method in ("fill", "select") and cand.filled and await self._save_if_step_says_so(
                    run, page, obs, gates, goal, saved_on):
                n_act += 1
                continue
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
                already_created=bool(run.created),
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

            # D-063: the person submitted a terms form earlier in this run, but CredAgent cannot tell whether
            # it created an app (e.g. the run was interrupted). Ask before anything that could make a duplicate.
            if getattr(self, "_maybe_created", False) and cand.method == "click" \
                    and CREATE_RE.search(cand.description):
                self._maybe_created = False
                answer = await self._handoff(
                    run, "DECIDE", "unexpected",
                    f"{cand.description} would create an app, but you submitted a form with terms earlier in this "
                    "run, which may already have created one. Creating another makes a duplicate.",
                    [cand.description], obs,
                    instruction="Look at the provider's app list in the browser. If the app already exists, choose "
                    "“No”: the agent will not create another, and you can open the existing app yourself.",
                    options=["Yes, create it (none exists yet)", "No, one already exists"],
                    after="Create it once (if yes) and continue.",
                )
                if answer is None:
                    return LoopResult("handoff_pending", "possible duplicate app: waiting for you", n_obs, n_act)
                if answer.startswith("No"):
                    self._mark_created(run, "an app (created earlier in this run; confirmed by the person)")
                    denied.add(cand.xpath)
                    self._step(run, f"not repeated (person: an app already exists): {cand.description}", "system",
                               "denied")
                    continue

            # Resume (spec §6.8): an action that was started before an interruption but never confirmed is
            # never repeated without asking. Clicking it again could, e.g., create a second app.
            doubt = self.in_doubt
            if doubt and cand.method == "click" and doubt.get("action") == "click" \
                    and doubt.get("target") == cand.description:
                self.in_doubt = None
                answer = await self._handoff(
                    run, "DECIDE", "unexpected",
                    "Before the interruption the agent started this click, and CredAgent cannot tell whether it "
                    f"happened: {cand.description}. Doing it again could repeat it (e.g. create a second app).",
                    [cand.description], obs,
                    instruction="Look at the browser window. If the action already happened, stop here and check "
                    "the console yourself. Otherwise let the agent do it once.",
                    options=["Yes, do it (it did not happen)", "No, stop here"],
                    after="Do it once (if yes) and continue.",
                )
                if answer is None:
                    return LoopResult("handoff_pending", "in-doubt action waiting for you", n_obs, n_act)
                if answer.startswith("No"):
                    self._stop = f"person chose not to repeat an in-doubt action: {cand.description}"
                    return LoopResult("blocked", self._stop, n_obs, n_act)

            # Before the agent itself submits a form, complete everything it may fill (D-050).
            form_of_btn = next(
                (
                    b["form"]
                    for b in obs.buttons
                    if b["xpath"] == cand.xpath and b["type"] in ("submit", "") and b["form"]
                ),
                None,
            )
            if cand.method == "click" and form_of_btn:
                obs, gates, status, _summary = await self._complete_form(run, page, obs, gates, form_of_btn)
                if status == "pending":
                    return LoopResult("handoff_pending", "a choice in the form is waiting for you", n_obs, n_act)
                if status == "declined":
                    self._stop = "person declined a choice in the form"
                    return LoopResult("blocked", self._stop, n_obs, n_act)
            # D-069: clicking the same control again and again on one page is not progress (Discord: "Add Another"
            # ×14). After two clicks of a control with the same text on this page, it is no longer offered.
            if cand.method == "click":
                norm = lambda t: re.sub(r"\s+", " ", (t or "").lower()).strip()  # noqa: E731
                text = norm(next((b.get("text") for b in obs.buttons + obs.links if b["xpath"] == cand.xpath), ""))
                ctl = (obs.url.split("#")[0], text or norm(cand.description))
                clicks[ctl] = clicks.get(ctl, 0) + 1
                if clicks[ctl] > 2:
                    denied.add(cand.xpath)
                    self._step(run, f"not repeated a third time on this page: {cand.description}", "system", "denied")
                    if text:  # the same control text elsewhere on this page is not offered again either
                        denied.update(b["xpath"] for b in obs.buttons + obs.links if norm(b.get("text")) == text)
                    continue
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
            btn_text = next((b.get("text") or "" for b in obs.buttons if b["xpath"] == cand.xpath), "")
            if cand.method == "click" and re.fullmatch(r"save( changes)?", btn_text.strip(), re.I) and re.search(
                    r"\bsave\b", goal, re.I):
                saved_on.add(obs.url)
                self._step(run, f"click {cand.description}", "agent", "done")
                self._step(run, f"step complete: {goal[:120]} (code: saved)", "agent", "done")
                run.plan_cursor += 1
                self._cp(run, "plan_step_complete", {"cursor": run.plan_cursor, "by": "code: saved"})
                continue
            if cand.method == "click" and form_of_btn and CREATE_RE.search(cand.description):
                try:
                    moved = (await page.url()) != obs.url
                except Exception:  # noqa: BLE001
                    moved = True
                if moved:
                    self._mark_created(run, f"an app (created by the agent clicking {cand.description})")
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
            opts = opts + ["Stop here"] if opts else ["Stop here", "Skip"]  # the person can always say no
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
            except (ModelCallError, ServiceUnavailable) as exc:  # the LLM failing must not crash the run
                self._step(run, f"cannot re-plan: the LLM is unavailable ({type(exc).__name__})", "system", "failed")
        step = run.plan.steps[run.plan_cursor] if run.plan_cursor < len(run.plan.steps) else None
        instruction = (
            f"The agent's current step is: “{step.description[:220]}” It could not find what to click for it. "
            "Do that step yourself in the browser window (or bring the page to where it can continue), then "
            "press Enter."
            if step else None
        )
        return await self._handoff(run, "DO", "unexpected", f"The agent is stuck: {why}.", [f"title: {obs.title}"], obs,
                                   instruction=instruction)


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
    "secret_hidden",
    "other",
}
