# CredAgent

A local CLI agent: give it an app name and it researches how that app issues
credentials, opens a visible browser, works through the provider's developer
console, pauses for steps only a person should do, and ends with a credential
stored outside the repo **plus a live test proving it works**, or an honest
report of what blocked it.

> **Work in progress — Sprint 4 of 7** (`docs/03-SPRINT-PLAN.md`). Progress: `docs/CHECKLIST.md`.
> Every decision and assumption: `docs/DECISIONS.md`. Every live run, including failures: `RESULTS.md`.

Requirements documents: `docs/CredAgent-PRD.md` (authoritative), `docs/02-ENGINEERING-SPEC.md`,
`docs/03-SPRINT-PLAN.md`. Safety rules for real-provider runs: `docs/ATTEMPT-PROTOCOL.md`.

## What works today

| Works | Not built yet |
|---|---|
| `credagent get "<app>"`: researches the app (Tavily + LLM) and writes a checked plan, then pauses | Browser runs against **real** providers (need per-provider consent, Sprint 6) |
| Browser loop on the fake provider: Stagehand + Jev's five decisions + code policy, DO/DECIDE handoffs ([sample cards](docs/samples/handoff-cards.md)) | |
| Jev failure fallbacks and "service unavailable" proved on the fake provider (`--fake-provider jev_failure` / `service_unavailable`) | |
| OAuth metadata check + dynamic client registration shortcut (fake provider) | `resume`, credential capture, `verify`, `secret` (Sprint 5) — these commands exit with code 2 and say so |
| `credagent status`, `runs`, `report`; crash-safe state; secrets masked before any model call | |

No credential has been obtained or live-tested against a real provider yet.

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
.venv/bin/credagent get Fakeprov --fake-provider jev_failure --offline  # Jev fails on purpose; fallbacks take over
.venv/bin/python scripts/sample_cards.py                       # regenerate docs/samples/handoff-cards.md
```

**With your own API keys** (see "Local environment" below):

```bash
.venv/bin/credagent get "GitHub"       # research + plan (~1–2 min); real-provider browser runs: Sprint 6
.venv/bin/credagent get Fakeprov --fake-provider terms_checkbox   # agent + real Jev/Stagehand; you accept the terms
.venv/bin/credagent runs
.venv/bin/credagent report <run-id>
```

You need a **FastRouter** key (LLM + Jev) and a **Tavily** key (web research). A research run
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

## Fake provider (Fakeprov)

A local, clearly fake developer console used to test every path without real accounts:

```bash
.venv/bin/python -m fake_provider.app --scenario terms_checkbox   # then open http://127.0.0.1:8765
```

Scenarios are listed in `fake_provider/fixtures/scenarios.json` (success, terms checkbox / implied,
sign-in + resume, shown-once secret, CAPTCHA, blocked, Jev failure, service unavailable, partial,
DECIDE choices, overwrite, cookie accept-only, prompt injection, DCR). The test login is in
`fake_provider/app/server.py` (fake values for this local site only).

Feasibility spikes (Sprint 0) are in `scripts/spikes/`; curated results are in
`docs/spikes/` and summarised in `docs/DECISIONS.md`.

## Repository layout

```text
src/credagent/      CLI, orchestrator, research, reasoning (FastRouter), decisions (Jev),
                    browser (Chrome + Stagehand), state, secrets, reports, config
fake_provider/      Fakeprov fake developer console + scenario fixtures
tests/              unit, integration (incl. opt-in real-browser test), fake_provider
scripts/            secret scan, env check, Sprint 0 feasibility spikes
docs/               PRD, spec, sprint plan, protocol, decisions, checklist, spike results, samples
```

## Approach, human involvement, verification, limitations

To be written as the implementation lands (Sprint 7). See `RESULTS.md` for
real-provider runs.
