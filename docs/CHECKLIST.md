# CredAgent — Task checklist

Derived from `docs/03-SPRINT-PLAN.md`. Sprint 0 and Sprint 1 are expanded into
individual tasks; later sprints stay at sprint-plan granularity until they start.
👤 = owner action. Status: `[x]` done and verified, `[~]` done but not yet
verified live, `[ ]` not started.

## Sprint 0 — Local foundation and feasibility spikes

- [x] S0.1 Initialise git repo; move PRD/spec/sprint plan into `docs/` (spec layout)
- [x] S0.2 Choose runtime + CLI framework; record in DECISIONS.md
- [x] S0.3 Scaffold Python package with the spec's module layout (`src/credagent/...`)
- [x] S0.4 CLI entry point with all seven commands (`get resume status runs report verify secret`); `--help` works
- [x] S0.5 Test setup (pytest) and lint (ruff)
- [x] S0.6 `.gitignore` covering `.env*` (except `.env.example`), venv, browser profiles, run state, secret store
- [x] S0.7 `.env.example` — names only
- [x] S0.8 Secret scan script (`scripts/check_secrets.py`: staged / tree / history modes) + pre-commit hook
- [x] S0.9 README.md and RESULTS.md skeletons
- [x] S0.10 👤 Owner creates `.env.local` and adds FastRouter + Tavily keys (steps in README "Local environment")
- [x] S0.11 Env check script that reports set/missing without printing values
- [x] S0.12 FastRouter: list model IDs (public endpoint; per-model structured-output support confirmed in S0.14)
- [x] S0.13 FastRouter: plain LLM request + latency
- [x] S0.14 FastRouter: constrained structured output (json_schema) + validation
- [x] S0.15 Jev: request/response format, five-decision request shape, repeated trials, latency
- [x] S0.16 Tavily: search + extract, latency, result shape
- [x] S0.17 Stagehand: headed local Chrome launches
- [x] S0.18 Stagehand: persistent profile survives process restart — FAILS with Stagehand launch/close; PASSES with CredAgent-owned Chrome (D-012)
- [x] S0.19 Stagehand: record exactly what page content reaches its model (recording callback); test `ignore_locators` exclusion of secret-bearing nodes
- [x] S0.20 Stagehand: check for outbound network connections in local mode
- [x] S0.21 Local state: atomic write + reload in a fresh process
- [x] S0.22 Secret file: owner-only permissions (0600 file / 0700 dir) outside the repo on this machine
- [x] S0.23 DECISIONS.md: results, runtime, models, paths, budgets-to-test, unresolved questions
- [x] S0.24 👤 Checkpoint: owner reviews decisions summary and confirms local setup (approved 2026-11-15)

## Sprint 1 — Safety protocol, domain model, fake provider

- [ ] S1.1 Write `docs/ATTEMPT-PROTOCOL.md` from PRD §5, §6.2, §7, §9, §13 (consent, DO/DECIDE, terms, payment, verification, account access, screenshots, secrets, cleanup)
- [ ] S1.2 👤 Owner approves ATTEMPT-PROTOCOL.md (required before any real-provider walkthrough)
- [ ] S1.3 Domain models: Run, Plan, StepRecord, Handoff, Blocker, CredentialReference, VerificationResult (pydantic, validated)
- [ ] S1.4 Run state machine: allowed status transitions; outcome mapping (only `verified` → `succeeded`)
- [ ] S1.5 Checkpoint store: atomic per-step checkpoint + append-only event log; no secret fields
- [ ] S1.6 Restart/recovery tests (kill mid-write, reload in new process, corrupted tail of event log)
- [ ] S1.7 Handoff model + card renderer (all six required fields) for DO and DECIDE
- [ ] S1.8 Re-plan counter (max 2) in the run model
- [ ] S1.9 Fake provider site: sign-in wall
- [ ] S1.10 Fake provider site: create-app form
- [ ] S1.11 Fake provider site: terms checkbox variant
- [ ] S1.12 Fake provider site: implied-agreement ("By clicking Create you agree") variant
- [ ] S1.13 Fake provider site: shown-once secret page
- [ ] S1.14 Fake provider site: CAPTCHA stand-in
- [ ] S1.15 Fake provider site: blocked path (e.g. "business verification required")
- [ ] S1.16 Fake provider site: mock token endpoint (client_credentials) for live verification
- [ ] S1.17 Deterministic scenario fixtures: success, terms (checkbox), terms (implied), sign-in + resume, shown-once secret, CAPTCHA, blocked, Jev failure
- [ ] S1.18 Tests for the fake provider (HTTP-level) and fixtures; obviously fake credentials only
- [ ] S1.19 👤 Checkpoint: owner approves protocol and confirms fake-site scenarios

## Sprint 2 — CLI, research, plan generation
- [ ] Per sprint plan; expanded when Sprint 1 checkpoint is approved

## Sprint 3 — Metadata shortcut and browser loop
- [ ] Per sprint plan

## Sprint 4 — Jev decisions, policy, handoffs
- [ ] Per sprint plan

## Sprint 5 — Resume, secret handling, verification
- [ ] Per sprint plan

## Sprint 6 — Real-provider runs and demo coverage
- [ ] Per sprint plan (each provider needs 👤 explicit consent + approved protocol)

## Sprint 7 — Hardening, README, submission
- [ ] Per sprint plan
