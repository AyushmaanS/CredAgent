# Decisions, assumptions, and open questions

Every material implementation decision and every unverified assumption is
recorded here. The PRD (`docs/CredAgent-PRD.md`) is authoritative; where the
spec or sprint plan differ, the PRD wins and the discrepancy is listed below.

Status values: **Decided** (made, with evidence), **Provisional** (made, to be
re-checked at the stated point), **Open** (not decided).
Evidence labels: *observed* (we ran it here), *sourced* (vendor docs, cited),
*inferred* (our reasoning), *unverified*.

---

## D-001 Repository layout: docs moved into `docs/` — Decided
The three documents were delivered at the repo root; the spec's layout (§3) and
the sprint plan reference `docs/`. Moved them to `docs/` unchanged.
The spec lists `docs/04-CLAUDE-CODE-STARTER-PROMPT.md`; that file was not
provided and is not needed (the starter prompt came via chat). Not created.

## D-002 Runtime: Python 3.12 + Stagehand v4 Python SDK — Decided
- *Observed:* this machine has Python 3.12.10 and Google Chrome; Node.js, npm and Homebrew are not installed.
- *Sourced:* Stagehand v4 supports TypeScript (Node ≥ 22.18), Python ≥ 3.11 and Go; it drives Chrome over CDP with no Playwright dependency ([installation](https://docs.stagehand.dev/v4/first-steps/installation.md)). Node is "recommended", but the Python SDK is official and has local browsers, persistent `user_data_dir`, `observe/act/extract`, `ignore_locators`, and a bring-your-own-LLM callback ([models](https://docs.stagehand.dev/v4/configuration/models.md), [user data](https://docs.stagehand.dev/v4/best-practices/user-data.md)).
- *Observed:* `stagehand==4.4.0` from PyPI is a pure-Python wheel (deps: browserbase, httpx, pydantic, websockets, opentelemetry-api). It ships a bundled Chrome extension that it loads into the launched browser.
- Why: works on the owner's machine with no admin install; the PRD prescribes no language. TypeScript would need the owner to install Node (admin password).
- Risk: the Python SDK may lag the TS SDK. Mitigation: the Sprint 0 spike exercises each Stagehand feature we depend on.
- The spec's TypeScript types (§5) are a logical model; they become pydantic models in Sprint 1.

## D-003 CLI framework: click; tests: pytest; lint: ruff — Decided
Small, stable, well-known. Commands not yet implemented exit with code 2 and say
"not implemented yet … Nothing was run", so no command can imply success.

## D-004 Package layout: `src/credagent/<module>/`, `fake_provider/` — Decided
Spec §3's `src/cli/`, `src/research/`… become subpackages of `src/credagent/`
(Python packaging needs one importable root). `fake-provider/` becomes
`fake_provider/` so it can be imported by tests.

## D-005 Runtime data location: `~/.credagent/` — Decided
`runs/`, `profiles/`, `secrets/` under `~/.credagent` (override: `CREDAGENT_HOME`).
Code refuses a `CREDAGENT_HOME` inside the repo. Directories 0700, files 0600.
`.gitignore` also covers the usual in-repo names as a second guard.

## D-006 Local env file: `.env.local` at the repo root — Decided
Git-ignored, blocked by the secret scan's forbidden-path rule, `chmod 600`
recommended (`scripts/check_env.py` warns if wider). Values are never printed;
`Settings.__repr__` hides keys. `.env.example` holds names only; defaults live in code.

## D-007 Secret scanning: own script + pre-commit hook — Decided
`gitleaks` is not installed and installing it needs Homebrew or a binary
download. `scripts/check_secrets.py` scans staged files / working tree / full
history for: forbidden paths (.env files, keys, runtime dirs), the **exact
values** of the keys in `.env.local`, credential-shaped patterns (shared with the
runtime masker), and quoted high-entropy literals. It prints `path:line: rule`
only, never the match. Hook: `.githooks/pre-commit` (enabled via
`git config core.hooksPath .githooks`). Running gitleaks as well before
submission is recommended (Sprint 7) if the owner installs it.

## D-008 Masking at the HTTP boundary — Decided
`FastRouterClient` masks every outgoing request body (LLM and Jev) through
`Masker` before sending, and registers our own API keys as known secrets.
Tavily responses are masked on receipt. The masker over-masks by design:
registered exact values, known key prefixes, labelled `secret: …` values, and
long high-entropy tokens.

## D-009 Model IDs — Provisional (until the live spike runs)
*Observed* from FastRouter's public model list (no key needed), 2026-11-15:
- Jev: `typesafe/jev-latest` (active, 64k context). Responses report the exact version; we log it per call. We use the alias for now; pin once the spike confirms the served version.
- LLM (research, planning, re-planning, page reasoning): `anthropic/claude-sonnet-5.5`.
- Stagehand's model (observe/act), via the custom LLM callback: `anthropic/claude-haiku-5.5` (cheaper and faster for per-page calls).
All configurable in `.env.local`. Structured-output support per model is confirmed by the live spike, not assumed.

## D-010 Jev request format — Provisional
*Sourced* ([FastRouter Jev docs](https://docs.fastrouter.ai/explore-features/openai-decisions-and-typesafe-systemone/typesafe-systemone-jev.md)):
`POST {FASTROUTER_BASE_URL}/systemone` with `{model, state, questions}`; question
types `noul` (yes/no probability), `choice` (option map, max 255), `score`
(ordered levels, 2–10). The PRD's five decisions map one-to-one:

| PRD decision | Jev type | Answer set (written in code) |
|---|---|---|
| Element selection | choice | `c0..cN` (Stagehand `observe()` candidates) + `none` |
| Action selection | choice | proceed / step_complete / wait / go_back / stuck |
| Blocker detection | noul | p(human must act now) |
| Risk assessment | score | read_only / reversible / hard_to_undo / irreversible |
| Completion detection | noul | p(credential created and shown) |

All five go in **one request per page** (`src/credagent/decisions/jev.py`).
Missing or malformed answers, unknown choices, and out-of-range values all
parse as *uncertain*, so they follow the PRD §8 fallbacks rather than being guessed.

## D-011 Jev certainty thresholds — Provisional (calibrate in Sprint 4)
choice/score: uncertain if `confidence < 0.6`. noul: confident yes if `p ≥ 0.8`,
confident no if `p ≤ 0.2`, otherwise uncertain. Starting points, not measured
values. They get calibrated on the fake provider and the first real runs.

## D-012 Chrome lifecycle: CredAgent owns the Chrome process; Stagehand attaches via `connect()` — Decided
- *Observed* (`docs/spikes/stagehand.json`, reproduced twice): with `stagehand.local_browser.launch(user_data_dir=…)` + `browser.close()`, a persistent cookie and a localStorage value set before close were **gone** after relaunching the same profile in a new process. The profile directory was kept and in use.
- *Observed in source* (stagehand 4.4.0 `browser.py`): `close()` sends CDP `Browser.close`, then immediately `killpg(SIGTERM)` on Chrome's process group. Likely cause: storage helpers killed before flushing (*inferred*).
- *Observed:* with `credagent.browser.chrome.ChromeProcess` (we launch Chrome with Stagehand's default flags in a new session, attach with `local_browser.connect(cdp_url=…)`, detach with `browser.disconnect()`, and quit with CDP `Browser.close` + wait for exit), cookie and localStorage **survived** relaunch in a new process.
- *Observed:* Chrome stays open after the CredAgent Python process exits; a new process re-attached on the saved CDP port and saw the state. This directly supports PRD Flow D (terminal closed mid-handoff).
- Consequences: run state will store `{chrome pid, CDP port, profile dir}`. Resume tries to re-attach to a live Chrome first, otherwise relaunches the profile. `STAGEHAND_FLAGS` mirrors Stagehand's private default flags and must be re-checked on every Stagehand upgrade.
- Risk: the CDP port on 127.0.0.1 is reachable by other local processes while Chrome runs (same as Stagehand's own launch). Accepted for a single-user local tool; noted for README limitations.
- Stagehand's own `launch()` path is now used only by the spike's comparison test.

## D-013 What Stagehand sends its model — Decided (verified offline)
- *Observed* (recording callback, fake values only): `observe()` sends a system prompt plus the page's **accessibility tree as text**, including visible text (`<code>` contents) and the values of text inputs, readonly included. `type=password` values appear as bullets. 3 of 4 fake secrets on the page reached the model request.
- *Observed:* `ignore_locators=[page.locator("#cred-panel")]` removed every value inside that panel from the request. `locator=page.locator("nav")` scoping removed all of them.
- *Observed:* `act(Action)` with a selector from `observe()` made **0** model calls (deterministic). Reading a value with `page.evaluate(...)` made 0 model calls.
- *Observed:* Stagehand's request is structured: `response_format: json_schema` with an `elements[{elementId, description, method, arguments}]` schema.
- Decision (layered, PRD §13 "Stagehand sends credential page content to its model"):
  1. Stagehand gets **only** our callback (`browser/stagehand_llm.py`), never a model name or provider key. Every Stagehand model request goes through `FastRouterClient`, which masks the full body.
  2. Image content is **refused** by the callback (screenshots cannot be masked).
  3. On any page that code or Jev flags as credential-bearing, CredAgent does not call `observe()`/`extract()` on it unscoped: it either passes `ignore_locators` for the secret containers or uses plain browser code only.
  4. Secret values are read only with `page.evaluate` (plain code), registered with the Masker immediately, then stored. `extract()` is never used on secrets.
- Gap found and fixed: random hex strings (e.g. 40-char client secrets) are below the 4.0-bit entropy threshold and were not pattern-masked. Hex runs of 32+ characters are now always masked (test added). Pattern masking is still a backstop, not a guarantee, for *unregistered* secrets; the guarantee comes from point 3.

## D-014 Stagehand network behaviour in local mode — Decided (verified offline)
- *Observed:* with Chrome routed through a local deny-all proxy, `observe()`/`act()` all worked. The only off-machine hosts Chrome attempted were its own services (`accounts.google.com`, `clients2.google.com`, `www.google.com`, `www.gstatic.com`); no Browserbase or Stagehand host. The Python process had no off-machine sockets.
- *Observed in source:* telemetry (OpenTelemetry traces) is only enabled if a `telemetry` config is passed; we never pass one. Browserbase API URLs in the package are used only for Browserbase-hosted browsers.
- Note: Stagehand's `context.set_domain_policy(...)` exists and may give a browser-level domain allow-list. Evaluate in Sprint 3 as a second layer behind the code check.

## D-015 Local state and secret file permissions on this machine — Decided (verified)
*Observed* (`docs/spikes/storage.json`, macOS 26.6, APFS, umask 022): secret file `0600`, run and store dirs `0700`, `~/.credagent` `0700`, all owned by the current user. Readable from a new process. A widened `0644` file is refused by `SecretFileStore`. Checkpoint written atomically (`0600`) and reloaded from a new process. A torn final JSONL line is tolerated (unit test).
*Bug found and fixed during this spike:* `Path.mkdir(parents=True, mode=0o700)` left the intermediate `~/.credagent/runs` at `0755` (mode applies only to the last component). All directory creation now goes through `state.atomic.mkdir_private`, which makes every created component `0700`. Unit test added; the spike now checks the `runs/` and `profiles/` roots too.
**Finding for Q4:** `tmutil isexcluded ~/.credagent` → `[Included]`. Stored secrets would be copied into Time Machine backups. Excluding the folder changes a backup setting, so CredAgent will not do it automatically. This is an input to the file-vs-keychain decision (Sprint 5); the owner may choose to exclude it.

---

## Discrepancies between documents
1. Docs location (see D-001).
2. Spec §3 lists `docs/04-CLAUDE-CODE-STARTER-PROMPT.md`, which was not provided.

## Assumptions not yet verified
- A1. FastRouter chat completions accept `response_format: json_schema, strict: true` for the chosen Claude models (docs say "compatible models"). → live spike.
- A2. Jev latency is low enough to call on every page. → live spike.
- A3. Tavily accepts `Authorization: Bearer` on `/search` and `/extract`. → live spike.
- ~~A4. Stagehand's local mode sends nothing off-machine except our model callback.~~ Verified (D-014).
- ~~A5. A user-supplied `user_data_dir` keeps cookies/localStorage across restarts.~~ **False** with Stagehand's own launch/close; true with CredAgent-owned Chrome (D-012).
- A6. Chrome's graceful quit flushes the profile even after a long session with sign-ins (verified only for a cookie and localStorage set seconds before quitting). → re-check during the Sprint 5 resume tests.

## Open questions (PRD §15 / spec §10)
- Q1. Jev model ID, format, latency (→ D-009/D-010 provisional; live spike pending).
- ~~Q2. Stagehand persistent profile and hiding page content from its model.~~ Resolved: D-012, D-013.
- Q3. Default redirect URI: local placeholder vs. the integration's real callback (e.g. Composio's). **Open: owner decision, needed before Sprint 6.**
- Q4. Secret store: owner-only file (default, implemented) vs. OS keychain. **Open: evaluate in Sprint 5.** Input: Time Machine currently backs up `~/.credagent` (D-015).
- Q5. Demo app list and each provider's automation terms. **Open: Sprint 6.**
- Q6. Budgets: research/search count, page observations, actions, per-call timeouts, retries, total run time, max plan steps. **Open: set in Sprints 2–4.** Current client defaults: LLM timeout 60 s, Jev 20 s, Tavily 30 s.
