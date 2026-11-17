"""Runs the existing orchestrator for the local web UI (D-089). Additive: nothing in the backend is changed.

`Service` owns the settings, the run store and one `RunController` per active run. A controller runs the same
sequence the CLI runs (research and plan, then terms check, consent, the browser agent, capture, live test) on a
worker thread, asking the person through `WebIO` instead of the terminal.

Rules kept from the CLI: a real provider is automated only after a recorded terms check and the person's consent
(asked again on every resume); at most one run is active at a time; credentials are never in any value this module
returns except from `reveal`, which is called only on an explicit click.
"""

from __future__ import annotations

import asyncio
import platform
import subprocess
import threading
from typing import Any

from credagent.config.settings import Settings
from credagent.secrets.capture import load_into_masker
from credagent.secrets.masking import Masker
from credagent.secrets.store import SecretFileStore, SecretStoreError
from credagent.state.models import Consent, Run, new_run_id
from credagent.state.store import RunNotFound, RunStore, SecretLeakError, StoreError
from credagent.web.views import build_view, plain, public_event, summary
from credagent.web.webio import WebIO


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str = "error") -> None:
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


def _clean_app(value: object) -> str:
    name = str(value or "").strip()
    if not name:
        raise ApiError(400, "Enter an application name.", "empty_name")
    if len(name) > 100:
        raise ApiError(400, "The application name is too long (100 characters at most).", "name_too_long")
    if any(ch in name for ch in "\n\r\t"):
        raise ApiError(400, "The application name must be a single line.", "name_multiline")
    return name


class RunController:
    """One run's worker thread and its open question for the person."""

    def __init__(self, svc: Service, run_id: str) -> None:
        self.svc, self.run_id = svc, run_id
        self.io = WebIO()
        self.thread: threading.Thread | None = None
        self.stage = "starting"
        self.error: dict[str, str] | None = None
        self.consent_info: dict[str, Any] | None = None
        self.consented = False
        self.masker = svc.new_masker()
        self.store = RunStore(svc.settings.runs_dir, self.masker)

    def start(self, target, *args) -> None:  # noqa: ANN001
        self.thread = threading.Thread(target=self._guard, args=(target, *args), daemon=True,
                                       name=f"run-{self.run_id}")
        self.thread.start()

    def alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def live(self) -> dict[str, Any]:
        snap = self.io.snapshot()
        return {"alive": self.alive(), "stage": self.stage, "error": self.error,
                "pending": snap[0] if snap else None, "options": snap[1] if snap else [],
                "consent": self.consent_info if snap and snap[0] == "consent" else None,
                "consented": self.consented}

    def _guard(self, target, *args) -> None:  # noqa: ANN001
        try:
            target(*args)
        except Exception as exc:  # noqa: BLE001 - a crash is shown to the person, never swallowed silently
            self.error = {"kind": "internal", "message": self.masker.mask_text(f"{type(exc).__name__}: {exc}")[:300]}
        finally:
            self.stage = "finished" if self.error is None else "stopped"

    # ----------------------------------------------------------------- bodies
    def real_new(self) -> None:
        from credagent.orchestrator import Orchestrator
        from credagent.reasoning.fastrouter import FastRouterClient
        from credagent.research.agent import ResearchAgent
        from credagent.research.tavily import TavilyClient

        s, m = self.svc.settings, self.masker
        run = self.store.load(self.run_id).run
        self.stage = "researching"
        agent = ResearchAgent(TavilyClient(s, m), FastRouterClient(s, m), model=s.llm_model)
        run = Orchestrator(self.store, m, agent, self.io)._research_and_plan(run, None)  # same call the CLI resume uses
        if run.status == "running" and run.phase == "planned" and run.pending_handoff is None:
            self.browser_stage(run, resume=False, doubt=None)

    def real_resume(self) -> None:
        from credagent.orchestrator import Orchestrator
        from credagent.reasoning.fastrouter import FastRouterClient
        from credagent.research.agent import ResearchAgent
        from credagent.research.tavily import TavilyClient

        s, m = self.svc.settings, self.masker
        loaded = self.store.load(self.run_id)
        run, doubt = loaded.run, loaded.in_doubt_action
        load_into_masker(run.credential, SecretFileStore(s.secrets_dir), m)
        if run.phase == "research" and run.plan.steps and run.pending_handoff is not None:
            if run.status != "running":
                run.transition("running", "resumed", resume=True)
            self.stage = "researching"
            run = Orchestrator(self.store, m, None, self.io).resume_choice(run)  # type: ignore[arg-type]
            if run.phase == "planned":
                self.browser_stage(run, resume=False, doubt=None)
            return
        if run.phase in ("created", "research"):
            if run.status != "running":
                run.transition("running", "resumed", resume=True)
            self.stage = "researching"
            agent = ResearchAgent(TavilyClient(s, m), FastRouterClient(s, m), model=s.llm_model)
            Orchestrator(self.store, m, agent, self.io)._research_and_plan(run, None)
            return
        if run.status != "running":
            run.transition("running", "resumed", resume=True)
        self.store.checkpoint(run, "resumed", {"in_doubt": bool(doubt), "pending_handoff": bool(run.pending_handoff),
                                               "via": "web"})
        self.browser_stage(run, resume=run.phase != "planned", doubt=doubt)

    def browser_stage(self, run: Run, *, resume: bool, doubt: dict | None) -> None:
        """Terms check, the person's consent, then the browser agent (the CLI's `_real_browser`)."""
        from credagent.browser.chrome import ChromeError
        from credagent.cli.main import _real_deps, _step_llm
        from credagent.consent.terms import terms_for
        from credagent.orchestrator import Orchestrator, execute_agent_phase, resume_agent_phase

        s, m = self.svc.settings, self.masker
        check = terms_for(run.app_name, run.provider, run.app_input)
        name = run.app_name or run.app_input
        if not check.may_automate:
            self.error = {"kind": "terms_prohibited", "message": f"{name}'s terms prohibit automated use of the "
                          f"console ({check.record}), so CredAgent will not drive it."}
            return
        if not s.fastrouter_api_key:
            self.error = {"kind": "config",
                          "message": "FASTROUTER_API_KEY is missing; the browser agent needs the LLM."}
            return
        if not run.plan.console_url:  # research found none: ask for it instead of a plan that cannot start (D-092)
            from credagent.research.console import accept_console_url

            self.stage = "awaiting_console"
            given = self.io.wait_console()
            plan, _why = accept_console_url(run.plan, given) if given else (None, "")
            if plan is None:
                self.stage = "stopped"
                return
            run.plan = plan
            self.store.checkpoint(run, "console_url_given", {"host": plan.console_url.split("/")[2], "via": "web"})
        self.consent_info = self.svc.consent_summary(run, check)
        self.stage = "awaiting_consent"
        account = self.io.wait_consent()
        if not account:
            self.stage = "stopped"
            return
        run.consent.append(Consent(provider=check.provider, account=m.mask_text(account)[:120],
                                   scope=f"this run ({run.id}): create one app and capture its credential",
                                   terms_finding=check.finding, terms_record=check.record))
        self.store.checkpoint(run, "consent_given", {"provider": check.provider, "terms": check.finding, "via": "web"})
        self.consented = True
        self.consent_info = None
        self.stage = "browser"
        deps, llm = _real_deps(s, m, run), _step_llm(s, m)
        orch = Orchestrator(self.store, m, None, self.io)  # type: ignore[arg-type]
        try:
            if resume:
                asyncio.run(resume_agent_phase(orch, run, deps, self.io, llm, doubt))
            else:
                asyncio.run(execute_agent_phase(orch, run, deps, run.plan.console_url, self.io, llm))
        except ChromeError as exc:
            self.error = {"kind": "browser", "message": f"Browser problem: {exc}"}
        except KeyboardInterrupt:
            self.error = {"kind": "stopped", "message": "Stopped. The run is saved."}
        except RuntimeError as exc:
            if "closed" not in str(exc).lower():
                raise
            self.error = {"kind": "browser_closed", "message": "The agent's browser window was closed, so the agent "
                          "stopped. The run is saved up to the last step."}
        except SecretLeakError:
            self.error = {"kind": "leak_guard", "message": "CredAgent stopped itself: it was about to write a value "
                          "registered as secret into the run's log. Nothing was written. This is a CredAgent bug; "
                          "the run is saved up to the last safe step."}

    def fake_new(self, fp, scenario_name: str, offline: bool, headless: bool) -> None:  # noqa: ANN001
        from credagent.browser.chrome import ChromeError
        from credagent.cli.main import _fake_deps, _fake_llm
        from credagent.orchestrator import Orchestrator, execute_agent_phase

        s, m = self.svc.settings, self.masker
        try:
            run = self.store.load(self.run_id).run
            self.stage = "browser"
            orch = Orchestrator(self.store, m, None, self.io)  # type: ignore[arg-type]
            try:
                asyncio.run(execute_agent_phase(orch, run, _fake_deps(s, run.id, headless), fp.base_url + "/", self.io,
                                                _fake_llm(s, m, scenario_name, offline)))
            except ChromeError as exc:
                self.error = {"kind": "browser", "message": f"Browser problem: {exc}"}
        finally:
            fp.stop()

    def fake_resume(self, headless: bool) -> None:
        import json

        from fake_provider.app import FakeProvider
        from fake_provider.app.server import saved_scenario

        from credagent.browser.chrome import ChromeError
        from credagent.cli.main import _fake_deps, _fake_dir, _fake_llm
        from credagent.orchestrator import Orchestrator, resume_agent_phase

        s, m = self.svc.settings, self.masker
        loaded = self.store.load(self.run_id)
        run, doubt = loaded.run, loaded.in_doubt_action
        fdir = _fake_dir(s, run.id)
        launch = json.loads((fdir / "launch.json").read_text(encoding="utf-8"))
        if run.status != "running":
            run.transition("running", "resumed", resume=True)
        self.store.checkpoint(run, "resumed", {"in_doubt": bool(doubt), "via": "web"})
        from urllib.parse import urlparse
        port = urlparse(run.plan.console_url or "").port or 0
        sf = fdir / "state.json"
        fp = FakeProvider(saved_scenario(sf), port=port, state_file=sf)
        fp.start()
        try:
            self.stage = "browser"
            orch = Orchestrator(self.store, m, None, self.io)  # type: ignore[arg-type]
            try:
                asyncio.run(resume_agent_phase(orch, run, _fake_deps(s, run.id, headless or launch["headless"]),
                                               self.io, _fake_llm(s, m, launch["scenario"], launch["offline"]), doubt))
            except ChromeError as exc:
                self.error = {"kind": "browser", "message": f"Browser problem: {exc}"}
        finally:
            fp.stop()


class Service:
    """Everything the HTTP layer needs. All user-visible failures are `ApiError`."""

    def __init__(self, settings: Settings, *, headless: bool = False) -> None:
        self.settings = settings
        self.headless = headless
        self.lock = threading.Lock()
        self.controllers: dict[str, RunController] = {}
        self.read_store = RunStore(settings.runs_dir, Masker())

    def new_masker(self) -> Masker:
        from credagent.cli.main import _masker
        return _masker(self.settings)

    # ------------------------------------------------------------------ reads
    def config(self) -> dict[str, Any]:
        try:
            from fake_provider.app import load_scenarios
            scenarios = sorted(load_scenarios())
        except Exception:  # noqa: BLE001 - the fake provider is optional
            scenarios = []
        s = self.settings
        return {"product": "CredAgent", "scenarios": scenarios,
                "keys": {"llm": bool(s.fastrouter_api_key), "research": bool(s.tavily_api_key)},
                "can_focus_browser": platform.system() == "Darwin"}

    def list_runs(self) -> list[dict[str, Any]]:
        return [summary(r) for r in self.read_store.list_runs()[:12]]

    def _load(self, run_id: str):  # noqa: ANN202
        try:
            return self.read_store.load(run_id)
        except RunNotFound:
            raise ApiError(404, "No such run.", "no_run") from None
        except StoreError as exc:
            raise ApiError(500, f"That run could not be read: {exc}", "unreadable") from None

    def view(self, run_id: str) -> dict[str, Any]:
        loaded = self._load(run_id)
        ctl = self.controllers.get(run_id)
        return build_view(loaded.run, self.read_store.events(run_id), ctl.live() if ctl else None)

    def events(self, run_id: str, after: int) -> list[dict[str, Any]]:
        self._load(run_id)
        return [public_event(e) for e in self.read_store.events(run_id) if e["seq"] > after][:300]

    # ------------------------------------------------------------------ starts
    def _busy(self) -> RunController | None:
        return next((c for c in self.controllers.values() if c.alive()), None)

    def start_run(self, body: dict[str, Any]) -> dict[str, str]:
        from credagent.orchestrator import FAKE_PROVIDER_NAME, UNTESTED_AT_PLAN, fake_provider_plan

        app = _clean_app(body.get("app"))
        mode = str(body.get("mode") or "real")
        s = self.settings
        with self.lock:
            if self._busy():
                raise ApiError(409, "Another run is still active. Finish or stop it first.", "busy")
            if mode == "fake":
                from fake_provider.app import FakeProvider, load_scenarios, scenario

                from credagent.cli.main import _fake_dir
                from credagent.state.atomic import atomic_write_json

                name = str(body.get("scenario") or "")
                offline = bool(body.get("offline", True))
                if name not in load_scenarios():
                    raise ApiError(400, "Unknown test scenario.", "bad_scenario")
                if not offline and not s.fastrouter_api_key:
                    raise ApiError(400, "The LLM key is missing; use the offline stand-in or add the key.",
                                   "no_llm_key")
                run_id = new_run_id(f"fakeprov-{name}")
                fdir = _fake_dir(s, run_id)
                fp = FakeProvider(scenario(name), state_file=fdir / "state.json")
                fp.start()
                atomic_write_json(fdir / "launch.json", {"scenario": name, "offline": offline,
                                                         "headless": self.headless})
                run = Run(id=run_id, app_input=app, app_name="Fakeprov", provider=FAKE_PROVIDER_NAME,
                          plan=fake_provider_plan(fp.base_url))
                run.predicted_outcome, run.phase = run.plan.predicted_outcome, "planned"
                ctl = RunController(self, run_id)
                ctl.store.create(run)
                self.controllers[run_id] = ctl
                ctl.start(ctl.fake_new, fp, name, offline, self.headless)
                return {"run_id": run_id}
            if not (s.fastrouter_api_key and s.tavily_api_key):
                raise ApiError(400, "FASTROUTER_API_KEY and TAVILY_API_KEY are needed to research a real app "
                               "(see the README, Local environment).", "no_keys")
            run_id = new_run_id(app)
            ctl = RunController(self, run_id)
            ctl.store.create(Run(id=run_id, app_input=app, untested=list(UNTESTED_AT_PLAN)))
            self.controllers[run_id] = ctl
            ctl.start(ctl.real_new)
            return {"run_id": run_id}

    def resume(self, run_id: str) -> dict[str, str]:
        from credagent.orchestrator import FAKE_PROVIDER_NAME

        loaded = self._load(run_id)
        run = loaded.run
        with self.lock:
            if self._busy():
                raise ApiError(409, "A run is already active. Finish or stop it first.", "busy")
            if run.status == "succeeded":
                raise ApiError(409, "This run already succeeded.", "done")
            if run.status != "running" and (not run.resumable or run.status == "cancelled"):
                raise ApiError(409, f"This run ended as {run.status} and cannot be resumed.", "not_resumable")
            if run.status == "running" and run.phase == "done":
                raise ApiError(409, "Nothing to resume.", "done")
            ctl = RunController(self, run_id)
            self.controllers[run_id] = ctl
            if run.provider == FAKE_PROVIDER_NAME:
                ctl.start(ctl.fake_resume, self.headless)
            else:
                if not (self.settings.fastrouter_api_key and self.settings.tavily_api_key):
                    raise ApiError(400, "The API keys are missing (see the README, Local environment).", "no_keys")
                ctl.start(ctl.real_resume)
        return {"run_id": run_id}

    # ----------------------------------------------------------------- answers
    def _ctl(self, run_id: str) -> RunController:
        ctl = self.controllers.get(run_id)
        if ctl is None or not ctl.alive():
            raise ApiError(409, "This run is not active. Resume it first.", "not_active")
        return ctl

    def consent_summary(self, run: Run, check) -> dict[str, Any]:  # noqa: ANN001
        """What ATTEMPT-PROTOCOL §2.5 says the person must be shown before a real-provider run."""
        from credagent.browser.values import FieldValues

        v, p = FieldValues.default(self.settings.redirect_uri), run.plan
        return {
            "provider": check.provider, "app": run.app_name or run.app_input,
            "credential": p.credential_kind.replace("_", " "), "console": p.console_url,
            "domains": list(p.allowed_domains), "domains_inferred": list(p.domains_inferred),
            "will_create": f"One app named “{v.app_name}”, description “{v.description}”",
            "callback": v.redirect_uri if p.needs_redirect_uri != "no" else None,
            "permissions": "None requested when creating the app; any permission or app-type choice is asked here.",
            "you_do": "Sign in, enter codes or 2FA, solve a CAPTCHA, accept the terms, anything unexpected (in the "
                      "agent's browser window).",
            "predicted": p.predicted_outcome,
            "blockers": [plain(b)[:200] for b in p.expected_blockers[:6]],
            "live_test": plain(p.verification_procedure)[:300],
            "afterwards": "Delete the app in the provider's console yourself when you no longer need it "
                          "(the agent never deletes).",
            "terms": {"finding": check.finding, "checked_on": check.checked_on, "record": check.record,
                      "summary": plain(check.summary),
                      "unclear_note": {
                          "unclear": "Unclear wording is automated by default (your decision, protocol v2). You "
                                     "remain responsible for activity on your account.",
                          "unchecked": "Unchecked providers are automated too (your decision, D-091). You remain "
                                       "responsible for activity on your account."}.get(check.finding)},
        }

    def give_console(self, run_id: str, url: object) -> None:
        from credagent.research.console import accept_console_url

        ctl = self._ctl(run_id)
        plan, why = accept_console_url(self._load(run_id).run.plan, url)
        if plan is None:
            raise ApiError(400, why, "bad_console_url")
        if not ctl.io.answer("console", str(url).strip()):
            raise ApiError(409, "Nothing is waiting for a console address.", "no_console_pending")

    def give_consent(self, run_id: str, account: object, confirm: object) -> None:
        ctl = self._ctl(run_id)
        text = " ".join(str(account or "").split())[:120]
        if confirm is not True:
            raise ApiError(400, "Confirm to give your go-ahead.", "no_confirm")
        if not text:
            raise ApiError(400, "Describe the account you will sign in with (no password, no email).", "no_account")
        if not ctl.io.answer("consent", text):
            raise ApiError(409, "Nothing is waiting for your go-ahead.", "no_consent_pending")

    def _pending_handoff(self, run_id: str, handoff_id: object):  # noqa: ANN202
        ctl = self._ctl(run_id)
        h = self._load(run_id).run.pending_handoff
        if h is None or h.id != handoff_id:
            raise ApiError(409, "That question is no longer open.", "stale")
        return ctl, h

    def answer(self, run_id: str, handoff_id: object, index: object) -> None:
        ctl, h = self._pending_handoff(run_id, handoff_id)
        snap = ctl.io.snapshot()
        if snap is None or snap[0] != "choose":
            raise ApiError(409, "Nothing is waiting for a choice.", "no_choice_pending")
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(snap[1]):
            raise ApiError(400, "Choose one of the offered options.", "bad_option")
        ctl.io.answer("choose", snap[1][index])

    def done(self, run_id: str, handoff_id: object) -> None:
        ctl, _ = self._pending_handoff(run_id, handoff_id)
        if not ctl.io.answer("enter", True):
            raise ApiError(409, "Nothing is waiting for you.", "no_do_pending")

    def stop(self, run_id: str) -> None:
        """Save and stop at the open question (the CLI's Ctrl+C at a prompt). The run can be resumed."""
        ctl = self._ctl(run_id)
        if not ctl.io.stop():
            raise ApiError(409, "The agent is mid-step; it can be stopped when it next needs you.", "mid_step")

    # ----------------------------------------------------------------- helpers
    def focus_browser(self, run_id: str) -> dict[str, Any]:
        """Best effort: bring the agent's Chrome window forward (macOS). A web page cannot do this itself."""
        run = self._load(run_id).run
        pid = run.browser.chrome_pid if run.browser else None
        if not pid or platform.system() != "Darwin":
            return {"ok": False, "how": "unsupported"}
        script = ('tell application "System Events" to set frontmost of (first process whose unix id is '
                  f'{int(pid)}) to true')
        try:
            r = subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, timeout=5)  # noqa: S603
            return {"ok": r.returncode == 0, "how": "osascript"}
        except (OSError, subprocess.SubprocessError):
            return {"ok": False, "how": "failed"}

    def reveal(self, run_id: str, part_name: str) -> str:
        """One stored value, on an explicit click. Never logged, never put in an event or a URL."""
        run = self._load(run_id).run
        part = run.credential.parts.get(part_name) if run.credential else None
        if part is None:
            raise ApiError(404, "No such stored value.", "no_part")
        try:
            return SecretFileStore(self.settings.secrets_dir).get(part.store_ref)
        except (SecretStoreError, OSError):
            raise ApiError(500, "The stored value could not be read safely.", "unreadable_secret") from None

    def verify(self, run_id: str) -> dict[str, Any]:
        """Re-run the live test with the stored credential (the CLI's `credagent verify`), real providers only."""
        import httpx

        from credagent.orchestrator import FAKE_PROVIDER_NAME
        from credagent.reports.report import write_reports
        from credagent.state.models import Evidence, InvariantError, StepRecord, decide_outcome
        from credagent.verification.verify import verify_run

        if self._busy():
            raise ApiError(409, "A run is still active.", "busy")
        m = self.new_masker()
        store = RunStore(self.settings.runs_dir, m)
        run = self._load(run_id).run
        if run.credential is None:
            raise ApiError(409, "There is no captured credential to test.", "no_credential")
        if run.provider == FAKE_PROVIDER_NAME:
            raise ApiError(409, "Re-testing is not available for the local test site.", "fake")
        sstore = SecretFileStore(self.settings.secrets_dir)
        load_into_masker(run.credential, sstore, m)
        with httpx.Client() as http:
            seq = store.begin_action(run, "verify_credential", {"via": "web"})
            v = verify_run(run, sstore, m, http)
            store.end_action(run, seq, "done", {"label": v.label})
        run.verification = v
        run.untested = [] if v.label != "untested" else [f"Live credential test: {v.observed_result}"]
        outcome, reason = decide_outcome(credential_captured=True, verification=v)
        if run.status == "running":
            run.add_step(StepRecord(action=f"live test (web): {v.test_description}"[:200], actor="agent",
                                    outcome="done" if v.label == "verified" else "failed",
                                    evidence=[Evidence(kind="observed", text=m.mask_text(v.observed_result)[:300])]))
        if outcome != run.status:
            try:
                run.transition(outcome, f"{reason} — re-tested from the web UI", resumable=outcome != "succeeded")
            except InvariantError:
                pass
        store.checkpoint(run, "verified", {"label": v.label, "via": "web"})
        write_reports(run, store.runs_dir / run.id, m, store.events(run.id))
        return {"label": v.label}
