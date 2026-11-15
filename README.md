# CredAgent

A local CLI agent: give it an app name and it researches how that app issues
credentials, opens a visible browser, works through the provider's developer
console, pauses for steps only a person should do, and ends with a credential
stored outside the repo **plus a live test proving it works**, or an honest
report of what blocked it.

> Status: **Sprint 0 (foundation and feasibility).** The CLI commands exist but
> are not implemented yet; they say so and exit with code 2. See
> `docs/CHECKLIST.md` for progress and `docs/DECISIONS.md` for decisions.

Requirements: `docs/CredAgent-PRD.md` (authoritative), `docs/02-ENGINEERING-SPEC.md`,
`docs/03-SPRINT-PLAN.md`.

## Setup

Requires macOS or Linux, Python 3.11+, and Google Chrome.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
git config core.hooksPath .githooks   # enables the pre-commit secret scan + lint
.venv/bin/credagent --help
```

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

Feasibility spikes (Sprint 0) are in `scripts/spikes/`; curated results are in
`docs/spikes/` and summarised in `docs/DECISIONS.md`.

## Approach, human involvement, verification, limitations

To be written as the implementation lands (Sprint 7). See `RESULTS.md` for
real-provider runs.
