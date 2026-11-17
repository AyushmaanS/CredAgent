# Web UI for Access Agent: inspection, gaps and proposal

Status: **built** (D-089). The owner approved the approach on 2026-11-17: local stdlib API, vanilla ES modules, the header says **CredAgent** (not "Access Agent"), and handoffs and consent may be given in the page. Section 9 lists what differs from this proposal and what is still not available.

## 1. What exists today (inspected 2026-11-17)

- **No frontend, no HTTP API, no WebSocket/SSE, no `package.json`.** The only interface is the click CLI (`credagent get | resume | status | runs | report | verify | secret`). There is no existing framework or component library to reuse.
- **The backend is a library plus a CLI.** `Orchestrator` (research, plan, then `execute_agent_phase` / `resume_agent_phase` for the browser) talks to the person only through an `IO` object: `say(text)`, `choose(prompt, options)` and `wait_enter(prompt)` (the last two may be awaited: `Handoffs._wait` accepts awaitables). The CLI's `TerminalIO` is one implementation. A second implementation is all a UI needs; no orchestrator change is required.
- **Run state is on disk and complete.** `~/.credagent/runs/<id>/run.json` (checkpointed after every step, atomic writes) and `events.jsonl` (append-only, `seq`, `type`, `data`, masked). Fields the UI needs, all already there: `status` (`running | succeeded | partial | blocked | waiting_on_provider | failed | cancelled`), `phase` (`created | research | planned | browser | verifying | done`), `status_reason`, `resumable`, `pending_handoff` (`kind` DO/DECIDE, `reason`, `person_instruction`, `where`, `options`, `blocker_kind`), `blockers` (with `next_steps`), `steps` (actor, action, outcome), `plan` (credential kind, console URL, guidance steps, expected blockers, verification procedure), `created`, `consent`, `credential` (kind and **masked** parts only), `verification` (`label`, `test_description`, `observed_result`, `production_limitations`, `tested_at`).
- **Secrets** live in owner-only files (`SecretFileStore`). `credagent secret --reveal` copies one value to the clipboard after the owner types its name; run state, events and reports never hold a value.
- **Consent** (ATTEMPT-PROTOCOL §2) is asked in the terminal before any real-provider browser run: terms check, "which account", "type yes", recorded in `run.consent`. Every resume asks again.
- **Fake provider (Fakeprov)** with scenarios and an offline scripted stand-in for the model already exist (`--fake-provider S --offline`): a real backend run without a real account.

## 2. Gaps (documented, not simulated)

| Needed by the brief | Backend today | Plan |
|---|---|---|
| Start a run, read progress, answer handoffs over HTTP | **Missing** | Add a small local API layer (new code only; nothing existing is modified) |
| Live updates | Events are appended to `events.jsonl` with a `seq` | Poll `GET …/events?after=<seq>` (1 s). No SSE/WebSocket needed |
| Milestone progress | Plan steps are *guidance*, not a counter (D-078) | Derive milestones from real run state and events (table in section 4) |
| "Open the browser session" | The agent's Chrome is a local window; a web page cannot raise it | Best effort `POST …/browser/focus` (macOS `osascript` activates Chrome's saved pid). If it fails, the UI says "switch to the Chrome window titled …" |
| Granted scopes | **Not recorded.** The agent requests none when creating an app; `plan.scopes` are research suggestions | Show "Permissions: none requested", never a made-up list. Gap noted |
| Resume after the server restarts | Runs persist; `resume_*_phase` re-attaches or relaunches the profile | `POST …/resume` calls the existing resume path (consent is asked again, as the protocol requires) |
| Secret retrieval | `SecretFileStore.get` | `POST …/secrets/<part>/reveal`, explicit click only, value in the response body only |

## 3. Approach

`credagent ui` (new CLI command) starts a **local web server in-process** on `127.0.0.1` and opens the browser. It runs the existing orchestrator on worker threads and serves a static frontend plus a small JSON API. **No new Python dependency** (stdlib `http.server`, as the fake provider already does) and **no Node toolchain or build step** (vanilla ES modules, one CSS file).

```
src/credagent/web/
  server.py       routing, security checks, static files, JSON in/out
  controller.py   one RunController per active run: worker thread, consent, pending answers
  webio.py        IO implementation: blocks/awaits until the UI answers (works in the research thread and in the async loop)
  views.py        run.json + events -> view model (pure functions, unit-tested; never contains a secret)
  static/
    index.html  app.css
    js/ main.js  api.js  state.js
        components/ header.js landing.js consent.js progress.js timeline.js attention.js result.js
                    secret-field.js activity-log.js failure.js
```

`api.js` is the only file that calls `fetch`. Components receive a view model and callbacks, and own no network code.

### API (all new; JSON; `Cache-Control: no-store`)

| Method and path | Purpose |
|---|---|
| `GET /api/config` | which modes exist (real, fake-provider scenarios), whether keys are configured (booleans only) |
| `POST /api/runs` `{app, mode?, scenario?}` | start a run (research runs in a worker thread); returns `{run_id}` |
| `GET /api/runs` / `GET /api/runs/<id>` | recent runs / one run's view model (also how a refresh recovers state) |
| `GET /api/runs/<id>/events?after=<seq>` | masked events since `seq` (the activity log) |
| `POST /api/runs/<id>/consent` `{account, confirm}` | the same consent as the terminal's, recorded in `run.consent` |
| `POST /api/runs/<id>/answer` `{handoff_id, option}` | answer a DECIDE (including the credential-type question) |
| `POST /api/runs/<id>/continue` `{handoff_id}` | "I did it" for a DO handoff (the agent re-checks the page, as with Enter) |
| `POST /api/runs/<id>/pause` · `POST /api/runs/<id>/resume` | like Ctrl+C (state is saved) and the existing resume path |
| `POST /api/runs/<id>/browser/focus` | best-effort: bring the agent's Chrome window forward |
| `POST /api/runs/<id>/secrets/<part>/reveal` | one value, on an explicit click |
| `POST /api/runs/<id>/verify` | re-run the live test (existing `verify_run`) |

### Security of the local server

The server can reveal secrets and drive a signed-in browser, so it is locked down: bind `127.0.0.1` only; a random one-time launch token in the printed URL, exchanged on first load for an `HttpOnly; SameSite=Strict` session cookie (so a refresh or a second tab works and no token stays in the address bar); every API call needs that cookie and a custom `X-CredAgent` header; `Host` and `Origin` must match; no CORS headers; no secret in any URL, log line, event or error message; the reveal response is `no-store` and the UI keeps the value in memory only, auto-hides it after 30 seconds and on tab blur, and never writes it to storage, console or analytics. The existing masker and leak guard stay in the path.

## 4. Milestones (derived from real state, never a percentage)

| Milestone shown | Done when (real backend fact) |
|---|---|
| Application identified | `plan.identification.canonical_name` set (research done) |
| Developer portal located | `plan.console_url` set |
| Credential type chosen | no DECIDE pending for the credential type and `plan.credential_kind` set |
| Your go-ahead | `run.consent` has an entry for this session |
| Browser opened | event `browser_opened` |
| Application registered | `run.created` not empty (or event `resource_created`) |
| Credentials captured | `run.credential` has parts |
| Credentials verified | `run.verification.label == "verified"` |

Rows that are not reached stay "pending". The current one is "in progress", or "blocked" (amber) while a handoff is pending, or "failed" (red). The activity line under it is the newest meaningful event (the agent's recorded action with its reason, or the handoff). The full technical log is collapsed.

## 5. States

| UI state | Backend condition |
|---|---|
| Idle | no active run selected |
| Running | `status == running` and no `pending_handoff` and the run has a live controller |
| Needs attention | `pending_handoff` (DO: do it in the browser, then "I did it"; DECIDE: choose) or consent not yet given |
| Paused | `status == running`, no live controller (server restarted or paused): "Resume" |
| Completed | `succeeded` (verified), or `partial` (credential captured, verification limited): the result card says exactly which |
| Failed | `failed` (recoverable when `resumable`), `blocked` (the person must resolve something), unrecoverable (`not resumable`) with `status_reason`, completed work and `next_steps` |

## 6. Visual design

Light neutral background, one centered column at most 720 px, system font stack, one accent colour, 1 px borders, 8 px radius, restrained shadows, no sidebars. Header: key-shaped logo, "Access Agent", a quiet info icon. Landing: headline "Get access to any app.", one sentence, a single input (any text), "Get credentials", suggestions (GitHub, Linear, Google Cloud) that only fill the input. Status icons: green check, subtle spinner, grey dot, amber, red; every status also has text for accessibility. Responsive down to 360 px.

## 7. Tests

Unit tests for `views.py` (every status/phase/handoff combination, and that no secret or unmasked value can appear), the controller and `WebIO` with the scripted model, and API tests for the security checks (wrong token, wrong Host/Origin, reveal without a click). A real-browser end-to-end test drives the UI against the fake provider (offline, headless): start, consent, a DO handoff and resume, completion, masked-then-revealed secret, refresh mid-run, and a failure scenario. Real Discord is not used by tests.

## 8. Decisions for the owner

1. **Integration approach:** local API in this repo (stdlib, no new dependency), as above.
2. **Frontend stack:** vanilla ES modules, no build step, no Node.
3. **Name:** the UI says "Access Agent" (per the brief); the CLI and repo stay CredAgent.
4. **Protocol wording:** ATTEMPT-PROTOCOL §5–§6 say the person presses Enter or answers "in the terminal". Allow the same confirmations in the local web UI (same checks: terms finding, typed account description, explicit confirm; every resume asks again), and record it in DECISIONS.

## 9. As built: differences and limits

- **Session:** an HttpOnly cookie instead of a token held by the page (see section 3).
- **Name in the header:** CredAgent, as the owner chose.
- **Polling, not SSE:** the page polls the run's view every second (4 s when the tab is hidden, 5 s when finished); the activity log polls its own `events?after=` only while open.
- **Research has no live detail.** The backend writes its research actions to the log only when research ends, so during research the page shows "Researching how … issues credentials" and the milestones, not each search.
- **Pause is at handoffs.** "Save and stop" works when the agent is waiting for you (the CLI's Ctrl+C at a prompt). A run that is mid-step cannot be interrupted from the page, as in the CLI; closing the app leaves it saved and resumable.
- **Resume asks for your go-ahead again** for a real provider, as the protocol requires, and re-attaches to the still-open agent window when there is one.
- **One active run at a time** (HTTP 409 otherwise): the agent's browser profile is per provider.
- **Open the browser window** is best effort (macOS, by the saved Chrome pid). If the system refuses, the page says to switch to the Chrome window by hand.
- **Granted scopes** are not recorded by the backend, so the result card does not show a permissions row. This is a missing capability, not an omission.
- **Re-test** (`verify`) is offered for real providers only.
- **Terms checks:** only Discord and Spotify have a recorded terms check (`consent/terms.py`). Since D-091 any other app is automated too: the consent screen says no check was recorded and the owner stays responsible. (Before D-091 the page stopped there, as the CLI did.)
- **Masked display** is the backend's (first four characters and a length for a secret), shown as is.
- **Not covered by tests:** a real-provider run through the page (consent screen included: it is checked visually and by the API tests with a stubbed view, not against a live provider), Safari and Firefox.
- **A plan with no console address asks for it** (D-092): the page shows "Where is the developer console?" with a field, validates the address (https, a domain name, no credentials in it), and only then moves on to the go-ahead screen.
- **Advanced and Recent were removed (owner, 2026-11-17, after a real Discord run through the page).** The landing page is one input and one button. Local test-site runs are started through the API, which still supports them. A new tab at `/` no longer lists earlier runs; a run is reopened by its address (`#/run/<id>`) or from the CLI. `GET /api/runs` stays for scripts.

