# CredAgent

A local CLI agent: give it an app name and it researches how that app issues
credentials, opens a visible browser, works through the provider's developer
console, pauses for steps only a person should do, and ends with a credential
stored outside the repo **plus a live test proving it works**, or an honest
report of what blocked it.

> **Work in progress — Sprint 6** (`docs/03-SPRINT-PLAN.md`). The browser layer was rebuilt on 2026-11-17 as an LLM agent loop over Playwright (D-078, below). Progress: `docs/CHECKLIST.md`.
> Every decision and assumption: `docs/DECISIONS.md`. Every live run, including failures: `RESULTS.md`.

Requirements documents: `docs/CredAgent-PRD.md` (authoritative), `docs/02-ENGINEERING-SPEC.md`,
`docs/03-SPRINT-PLAN.md`. Safety rules for real-provider runs: `docs/ATTEMPT-PROTOCOL.md`.

## What works today

| Works | Not built yet |
|---|---|
| `credagent get "<app>"`: researches the app (Tavily + LLM) and writes a checked plan; for a provider whose terms were checked, asks for your consent and then runs the browser agent | More real providers, API keys and the authorization-code flow (Sprint 6, in progress) |
| Browser agent on the fake provider: an LLM chooses each step over Playwright, code policy gates every action, DO/DECIDE handoffs ([sample cards](docs/samples/handoff-cards.md)) (D-078) | |
| Unusable model answers and "service unavailable" proved on the fake provider (`--fake-provider llm_failure` / `service_unavailable`) | |
| OAuth metadata check + dynamic client registration shortcut (fake provider) | Provider-specific live tests (API keys, authorization-code flow) arrive with the real providers (Sprint 6) |
| Credential capture by plain browser code (shown-once secrets too), stored in owner-only files outside the repo | |
| Live test (OAuth client-credentials token request); only `verified` → `succeeded` ([sample report](docs/samples/secret-and-report.md)) | |
| `credagent resume` (re-checks the page, never repeats an unconfirmed click), `verify`, `secret` (masked; reveal on purpose) | |
| `credagent status`, `runs`, `report`; crash-safe state; secrets masked before any model call | |

One real credential (Discord, run #7) has been captured and live-tested on the new agent loop; nothing else has.

## Quick start

Tested on **macOS 26 (Apple Silicon), Python 3.12, Google Chrome**. Python 3.11+ is required.
Linux is untested; the browser code currently expects Chrome at the macOS install path.

```bash
git clone https://github.com/AyushmaanS/CredAgent.git
cd CredAgent
python3 --version                      # must be 3.11 or newer
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
git config core.hooksPath .githooks    # pre-commit secret scan + lint (for contributors)
```

**No API keys needed** for these:

```bash
.venv/bin/credagent --help
.venv/bin/python -m pytest                                    # full test suite, no network
.venv/bin/python -m fake_provider.app --scenario terms_checkbox   # fake console at http://127.0.0.1:8765
.venv/bin/credagent get Fakeprov --fake-provider success --offline  # watch the agent drive the fake console
.venv/bin/credagent get Fakeprov --fake-provider signin_resume --offline  # press Ctrl+C at the card, then:
.venv/bin/credagent resume <run-id>                             # continues where it stopped
.venv/bin/credagent secret <run-id>                             # where the credential is stored (masked)
.venv/bin/credagent verify <run-id>                             # re-run the live test
.venv/bin/credagent get Fakeprov --fake-provider llm_failure --offline  # every other model answer is unusable; the run still succeeds
.venv/bin/python scripts/sample_cards.py                       # regenerate docs/samples/handoff-cards.md
```

**With your own API keys** (see "Local environment" below):

```bash
.venv/bin/credagent get "GitHub"       # research + plan (~1–2 min); real-provider browser runs: Sprint 6
.venv/bin/credagent get Fakeprov --fake-provider terms_checkbox   # agent + the real LLM; you accept the terms
.venv/bin/credagent runs
.venv/bin/credagent report <run-id>
```

You need a **FastRouter** key (the LLM) and a **Tavily** key (web research). A research run
costs roughly $0.15–0.20 at list prices (about 9–10 Tavily credits plus two LLM calls; Tavily's
free tier is 1,000 credits a month). Estimates, not measured billing; see `docs/DECISIONS.md`.

## Local environment

API keys live only in `.env.local` at the repo root. It is git-ignored, the
secret scan blocks it from commits, and no CredAgent command prints its values.
**Never paste keys into chat, issues, or commits.**

1. In Terminal, from the repo folder:
   ```bash
   cp .env.example .env.local && chmod 600 .env.local
   ```
2. Open it in a plain-text editor, e.g. `nano .env.local` (or `open -e .env.local`).
3. Put your FastRouter key after `FASTROUTER_API_KEY=` and your Tavily key after
   `TAVILY_API_KEY=`: no quotes, no spaces. Leave the other lines empty to use defaults.
4. Save and close (in nano: `Ctrl+O`, `Enter`, `Ctrl+X`).
5. Check the file without showing the keys:
   ```bash
   .venv/bin/python scripts/check_env.py
   ```
   It should print `set` for both keys.

Runtime data (run state, browser profiles, secret store) lives in
`~/.credagent/` (owner-only permissions), outside the repo.

**Where credentials go:** each captured value is a separate file,
`~/.credagent/secrets/<run-id>/<name>.secret` (folders 0700, files 0600). The files are
**not encrypted**: anyone who can read files as your macOS user can read them, and so can
backups of your home folder. Time Machine includes `~/.credagent` unless you exclude it
yourself (`tmutil addexclusion ~/.credagent`). Run state, logs and reports hold only
references and masked forms such as `fpcs… (45 chars)`. `credagent secret <run-id>` shows
where each value is and whether its permissions are still owner-only. To use a value,
`credagent secret <run-id> --reveal <name>` (you type the name to confirm) copies it to the
clipboard; add `--print` to show it in the terminal instead.

Fake-provider runs also save the fake site's own state (`~/.credagent/fakeprov/<run-id>/`,
owner-only) so `resume` and `verify` work from a new terminal.

## Development

```bash
.venv/bin/python -m pytest                        # tests
.venv/bin/ruff check src tests scripts            # lint
.venv/bin/python scripts/check_secrets.py --tree  # secret scan (also --staged, --history)
```

Real-browser tests open Chrome, so they are opt-in:

```bash
CREDAGENT_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/integration   # add CREDAGENT_HEADLESS=1 to hide the window
```

## Web page

```bash
.venv/bin/credagent ui          # prints a link and opens it; Ctrl+C to stop
```

A small local page (127.0.0.1 only) for the same runs the CLI makes: enter an application name, follow the
milestones, answer "Your attention is needed" handoffs with buttons instead of the terminal, resume a saved run, and
see the result with the credentials masked until you press Reveal or Copy. It runs the same orchestrator; the CLI
keeps working and shares the same saved runs. Details and limits: `docs/design/web-ui.md`.

- Open the exact link `credagent ui` prints (it signs this browser in once). The page cannot be used from another
  computer or another website.
- A real provider still needs a recorded terms check and your consent in the page, every session. Today only Discord
  and Spotify have a recorded terms check; for any other app the page researches and plans, then says the terms have
  not been checked yet and stops.
- The page has one input and one button. A run on the local test site (Fakeprov) with the offline stand-in, which needs no keys or account, is started through the API (`POST /api/runs` with `{"app": "x", "mode": "fake", "scenario": "success"}`) or the CLI, and can then be followed in the page.
- Reopening `/` in a new tab does not list earlier runs. Reopen a run by its address (`/#/run/<id>`), or with `credagent runs` and `credagent resume <id>`.

## Fake provider (Fakeprov)

A local, clearly fake developer console used to test every path without real accounts:

```bash
.venv/bin/python -m fake_provider.app --scenario terms_checkbox   # then open http://127.0.0.1:8765
```

Scenarios are listed in `fake_provider/fixtures/scenarios.json` (success, terms checkbox / implied,
sign-in + resume, shown-once secret, CAPTCHA, blocked, LLM failure, service unavailable, partial,
DECIDE choices, overwrite, cookie accept-only, prompt injection, DCR). The test login is in
`fake_provider/app/server.py` (fake values for this local site only).

Feasibility spikes (Sprint 0) are in `scripts/spikes/`; curated results are in
`docs/spikes/` and summarised in `docs/DECISIONS.md`.

## Repository layout

```text
src/credagent/      CLI, orchestrator, research, reasoning (FastRouter), agent (LLM step loop),
                    browser (Chrome + Playwright), web (local page + JSON API), state, secrets, reports, config
fake_provider/      Fakeprov fake developer console + scenario fixtures
tests/              unit, integration (incl. opt-in real-browser test), fake_provider
scripts/            secret scan, env check, Sprint 0 spikes (storage, Tavily)
docs/               PRD, spec, sprint plan, protocol, decisions, checklist, spike results, samples
```

## Approach

**The agent loop (D-078).** The orchestrator keeps workflow state and runs a loop over a visible Chrome that CredAgent starts itself (persistent profile):

```text
Orchestrator → look (numbered text snapshot) → hard checks in code → LLM chooses ONE action
             → code validates it → policy + risk → Playwright executes → record + checkpoint → repeat
```

- **The model proposes, code decides.** The model returns one structured action per step (click, type, select, navigate, scroll, inspect, back, wait, ask the person, done, give up), naming an element by its number in the current snapshot. Code rejects invalid answers, applies the hard stops and the policy, and assigns risk. No model can override a hard stop.
- **What the model cannot see or do.** It sees text, never screenshots. Credential-like values are never listed and no field value is shown (only filled or empty). It types only **approved values by key** (app name, homepage, callback URL, description), so it cannot be talked into typing something else. Page text is treated as data, never as instructions.
- **Code owns the rest:** hard stops (payment, review submission, deleting, off-site navigation, business verification), the one-app-per-run rule, capture of the credential by plain browser code, the live test, run state, and reports.
- **Why not Stagehand and Jev?** The first version used both. Real runs on Discord showed that a stateless decision tool plus a step machine in code was hard to debug, so the owner replaced it with this simpler loop (reasoning and results in `docs/DECISIONS.md` D-078 to D-084).

**Measured on the fake provider (D-084, 52 real LLM runs):** about 8 LLM calls per run, about 24k tokens per run, 2.2 s median per call, every run succeeded and no safety check failed. This is not a real-provider result, and real console pages are larger.

## Human involvement

The person does what only a person should: signing in, email codes, 2FA, CAPTCHA, identity or payment steps, and **accepting terms (always the person, including "By clicking Create you agree")**. The agent fills every other field first. Choices (an app type, a permission, resetting a secret that invalidates the old one) are asked in the terminal. Real providers need per-provider consent each session (`docs/ATTEMPT-PROTOCOL.md`). After a handoff the run resumes from its saved state, never blindly replaying a click.

## Verification

A credential is **working only if its live test passes** (`verified`). Only `verified` can end a run as `succeeded`; a pass with a limitation (for example an app in testing mode) is `partial`; everything else is reported as what it is, with the untested items listed.

## Limitations

- **One real provider so far.** Discord run #7 on the new loop ended `succeeded` with a verified credential (after fixes on the real page, D-086 to D-088); earlier runs (Spotify stopped; Discord #2–#6) did not, and all are in `RESULTS.md`. Other providers, API keys and the authorization-code flow are untested.
- Tested on macOS with Google Chrome only.
- The agent's behaviour on real consoles beyond the fake provider is unmeasured; the model is not deterministic, so runs vary (for example in which optional fields it fills).
- It never deletes the apps it creates; clean them up in the provider's console.
- Where the model's value for a field cannot be seen, a stray character typed earlier by a person is not noticed unless the model inspects the field (D-083).

## Key decisions

All of them, with evidence, are in `docs/DECISIONS.md`. The ones that shape the product: local CLI with owner-only secret files outside the repo (D-053), accepting terms is always the person (D-048 to D-050), unclear terms on a provider are automated by default with consent each session (D-059), one app per run (D-063), and the agent loop over Playwright (D-078).
