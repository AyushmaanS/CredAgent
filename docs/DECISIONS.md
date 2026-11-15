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

## D-009 Model IDs — Decided (verified live 2026-11-15)
*Observed* from FastRouter's public model list (no key needed), 2026-11-15:
- Jev: `typesafe/jev-latest` (active, 64k context). Responses report the exact version; we log it per call. We use the alias for now; pin once the spike confirms the served version.
- LLM (research, planning, re-planning, page reasoning): `anthropic/claude-sonnet-5.5`.
- Stagehand's model (observe/act), via the custom LLM callback: `anthropic/claude-haiku-5.5` (cheaper and faster for per-page calls).
All configurable in `.env.local`.
*Observed live* (`docs/spikes/fastrouter.json`): all three IDs listed and active. Sonnet 5.5 returned schema-valid JSON in 6/6 structured calls, both `strict: true` and `strict: false`. Haiku 5.5 served Stagehand `observe()` correctly in both modes. The served model name alternates between `anthropic.claude-sonnet-5-5` and `claude-sonnet-5-5`, so FastRouter routes across upstream providers (*inferred*). We log the served name per call.

## D-010 Jev request format — Decided (verified live)
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
*Observed live:* 25/25 five-decision requests returned all five answers in the documented shape; 0 errors. `typesafe/jev-latest` served **`jev-1.14.0`** (FastRouter's docs still say 1.13.0). FastRouter lists only the alias, so the version cannot be pinned: we record the served version on every call, and a version change becomes a re-calibration trigger.

## D-011 Jev certainty thresholds — Provisional (calibrate in Sprint 4; first live data below)
choice/score: uncertain if `confidence < 0.6`. noul: confident yes if `p ≥ 0.8`,
confident no if `p ≤ 0.2`, otherwise uncertain. Starting points, not measured
values. They get calibrated on the fake provider and the first real runs.
*Observed live* (5 synthetic pages × 5 trials, two runs):
- **Blocker detection** was confident and correct for the sign-in wall (0.95), CAPTCHA (0.94–0.96), create form (0.06–0.07, no blocker) and credential page (0.06–0.07).
- **Implied agreement** ("By clicking Create, you agree to the Developer Terms…"): blocker p = **0.43–0.53**, uncertain every time, and on the yes/no reading 2 of 5 trials in the first run said "no human needed". Under the PRD fallback this goes to the LLM second opinion and code checks, so it would pause, but it shows **Jev cannot be relied on for terms**. Decision: the code hard check for terms (checkbox *and* implied wording) runs **before** Jev on every page, as PRD §9/§13 require. Jev's answer can never clear it.
- **Completion detection:** credential page 0.95–0.96; all other pages ≤ 0.05.
- **Element selection:** confident and correct on the create form (`c0`, 1.0). On the sign-in wall it chose `none` with ~0.5 confidence (uncertain), which is reasonable since sign-in is a DO handoff.
- **Risk assessment:** confidence was usually low (0.12–0.58) except on the create form (0.88–0.93; `reversible`). With the 0.6 threshold, risk will often be bumped one level ("assume the next higher risk level"). That is safe but may cause extra DECIDE handoffs. Calibrate wording and threshold in Sprint 4; never loosen hard stops.

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

## D-016 Measured latency (2026-11-15, this machine) — Recorded
| Call | p50 | max | n |
|---|---:|---:|---:|
| Jev five-decision request | 377–412 ms | 639 ms | 50 |
| LLM plain (Sonnet 5.5) | 1.5 s | 2.8 s | 6 |
| LLM structured JSON (Sonnet 5.5) | 2.8–3.2 s | 3.6 s | 12 |
| Stagehand `observe()` via FastRouter (Haiku 5.5) | 1.7–1.9 s | 1.9 s | 4 |
| Tavily search (basic, 5 results) | 1.3–3.9 s | 3.9 s | 6 |
| Tavily extract (2 URLs) | 0.4 s | 0.4 s | 2 |
Jev is fast enough to call on every page. Starting timeouts (Q6): Jev 20 s, LLM 60 s, Tavily 30 s, then one Jev retry per the PRD.

## D-017 Error mapping for the FastRouter-unavailable rule — Decided (verified live)
Unknown model → HTTP 4xx → `ModelCallError` (a request problem, not an outage). Unreachable host, timeout or 5xx → `ServiceUnavailable`. Only `ServiceUnavailable` on both the LLM and Jev triggers the PRD's resumable `failed: service unavailable` end. Error messages are masked and never include the key (unit-tested).

## D-018 Tavily — Decided (verified live)
`Authorization: Bearer` works on `/search` and `/extract`. Result fields: `title, url, content, score, raw_content, id`; extract returns `raw_content, title, url, images`. Results were relevant for a common app (GitHub: official docs at ranks 2–3, a tutorial at rank 1), sensible for a less common app (Raindrop.io: official developer docs ranked first), and **low-scoring and off-topic for a nonsense name** (top score 0.36). Implication for Sprint 2: research must rank official domains above tutorials and treat a low top score as "app not identified", not as a fact.

## D-019 Masking must not destroy research URLs — Decided
*Observed:* the first Tavily run masked URL paths (e.g. `community.openai.[REDACTED]`) because long path tokens with digits looked random. Fix: inside URLs, each path/query segment is judged on its own, and lowercase word-slugs are kept. Secret-looking query values and random segments are still masked (tests for both, plus base64 secrets containing `/` outside URLs). After the fix, 0 masked URLs across the Tavily results.

## D-020 TLS on this Python build — Recorded
python.org Python 3.12's stdlib `urllib` fails certificate verification here (no system CA bundle installed). All network code uses `httpx`, which bundles certifi. stdlib HTTP is used only for `127.0.0.1` (Chrome's DevTools port). No owner action needed.

## D-021 Run status model — Decided (Sprint 1)
Status values are the spec's: `running` plus the six PRD outcomes. A run paused at a handoff stays `running` with exactly one **pending handoff**. `status` shows it as "waiting for you". No extra status was invented.
Transitions (`state/models.py: TRANSITIONS`): `running` → any outcome. `blocked` / `waiting_on_provider` / `failed` → `running` **only via resume** (`failed` only when `resumable=True`, e.g. service unavailable). `partial` → `running` or `succeeded` (re-verification after provider review). `succeeded` and `cancelled` are final. Invalid transitions raise.

## D-022 `succeeded` is enforced by the model, not by convention — Decided
A `Run` cannot be constructed, assigned or transitioned to `succeeded` unless it has a credential reference **and** a `verified` result with **no production limitations**. Tested for every non-verified label. `decide_outcome` maps results to outcomes:
verified + no limits → succeeded · verified + limits → partial · captured but client_recognized / inconclusive / untested → partial (label stated) · invalid → failed · review pending → waiting_on_provider · blocker → blocked · error → failed.
**Interpretation recorded:** PRD §10 doesn't say what a captured-but-`invalid` credential is. We use `failed` ("provider rejected it"), not `partial`, because nothing usable was obtained.

## D-023 Credential reference holds named parts — Decided
The spec's `CredentialReference` has a single `storeRef`. An OAuth client has two values, so it becomes `parts: {"client_id": {store_ref, masked_display}, "client_secret": {...}}`. Each `store_ref` must match `file:<run>/<name>`, so a raw value cannot be stored in that field. Extra fields are forbidden on every model (`extra="forbid"`).

## D-024 Checkpoint store format — Decided (resolves spec open decision 5)
`~/.credagent/runs/<run-id>/run.json` (atomic snapshot) + `events.jsonl` (append-only, fsync per line), all `0600` in `0700` dirs.
- Write order: event first, then snapshot. On load, events newer than the snapshot are reported (`events_after_snapshot`) and the sequence stays monotonic.
- **Never-replay:** `begin_action` records the intent before any browser action, and `end_action` records the result. An action started but not finished is returned as `in_doubt_action` on load. Tested with a real process killed by `os._exit` between the two. Resume must re-check the page for it.
- A torn final event line (crash mid-write) is tolerated. A corrupt snapshot is a plain-language error, not a guess.
- **Secret guard:** every snapshot and event is checked against the Masker's registered values and refused (`SecretLeakError`) before anything touches disk.
- Run IDs: `YYYYMMDD-HHMMSS-<app-slug>-<4 hex>`, safe for paths and the secret store.

## D-025 Handoff cards — Decided
`handoff/cards.py` renders the six PRD §9 fields, numbered 1–6, plus DECIDE options. Default "do not" lines: don't close the browser window; don't paste secrets into chat. Cards pass through the Masker. Model rules: DECIDE needs ≥ 2 options and the answer must be one of them; DO has no options; one pending handoff at a time.

## D-026 Fake provider ("Fakeprov") — Decided
- Python standard library only (`ThreadingHTTPServer`). No new dependency, runs in-process for tests or by hand: `python -m fake_provider.app --scenario <name>`.
- Clearly fake: a banner on every page, "Fakeprov" name, `fpcid_` / `fpcs_` / `fpat_` prefixes, `*.test` email. A test checks that no real provider name appears.
- **Audit log with actor:** consequential events (terms accepted, sign-in, CAPTCHA solved, app created / overwritten / deleted, review submitted, payment, business verification, secret regenerated, account created) are logged with the `X-Fakeprov-Actor` header. The test harness sends `person` only while simulating the human, so acceptance tests can assert that e.g. every `terms_accepted` came from the person and no `app_deleted` ever happened.
- Test hooks (`/__test__/…`) require `X-Fakeprov-Test: 1`, so a browser navigating the site cannot trigger them.
- Off-allow-list link uses `partner.elsewhere.localhost` (Chrome resolves `*.localhost` to loopback), so domain checks can be tested without the internet.
- Scenarios (`fake_provider/fixtures/scenarios.json`): the 8 PRD acceptance cases (success, terms checkbox, terms implied, sign-in + resume, shown-once secret, CAPTCHA, blocked, Jev failure) **plus** service unavailable, partial (testing mode), DECIDE app type + scopes, overwrite existing app, cookie accept-only, prompt injection, and DCR shortcut. The extras exercise PRD requirements (§8, §9, §10, F3, spec §7) that the acceptance list does not name. Each scenario states its expected outcome, handoffs and verification label, used by the Sprint 4+ acceptance tests.
- The verification path on Fakeprov is `POST /oauth/token` (client_credentials, Basic or POST auth), then `GET /api/me`. `/oauth/authorize` recognises a client ID without a secret, which provides a real `client_recognized` case.

## D-027 Real-browser tests are opt-in — Decided
`tests/integration/test_fake_provider_browser.py` launches Chrome, so it runs only with `CREDAGENT_BROWSER_TESTS=1` (headed by default; `CREDAGENT_HEADLESS=1` hides the window). It calls no model API: Stagehand gets a recording callback. *Observed* (headed and headless, 2026-11-15): cookie "Reject all" by plain click; sign-in by the simulated person; **sign-in survived a full Chrome quit and relaunch**; terms left unticked by the agent; one real `observe()` model request containing the page minus the excluded credentials panel, with neither client ID nor secret in it; secret read by plain code on first view and hidden after reload; captured credential passed the token + `/api/me` live test; audit shows terms accepted once, by the person, and no forbidden events.

## D-028 Research-only live runs are not "real-provider runs" under the protocol — Decided (interpretation)
Sprint 2 live runs only read public documentation through Tavily and send it to the LLM. There is no browser, no provider account and no console. The protocol's consent rule (section 2) covers acting in a provider's console or account, so research-only runs need no per-provider consent. Every browser run against a real provider still does.
**Incident (minor, disclosed):** once, while wiring up `get`, an existing CLI test still invoked `credagent get "GitHub"` before tests were isolated from the real `.env.local`. One unintended research-only run used the owner's FastRouter and Tavily keys (3 searches, 1 extract call, 2 LLM calls; run `20261115-142849-github-9979`). Nothing else happened, and no secret was exposed (keys are never printed; the run was masked as usual). Fix: `tests/conftest.py` now isolates every test from the real env file, keys and `~/.credagent`, so no test can reach the network through the real clients. The same fix exposed and corrected an env-file precedence bug (an explicit `env_file` argument now beats `CREDAGENT_ENV_FILE`).

## D-029 Research pipeline and budgets — Decided (resolves the research part of Q6)
Fixed pipeline, not an open-ended loop: 3 searches → triage LLM → ≤2 follow-up searches → read ≤4 pages → synthesis LLM → code validation.
Budgets (`ResearchBudget`): ≤6 searches × 5 results; ≤4 extracted pages, each truncated to 12,000 chars; 700-char snippets; ≤4 LLM calls (one retry each); 180 s total; ≤15 model-proposed steps. Exhaustion gives a resumable `failed: research budget exhausted`. *Observed:* 8–83 s per run, 2–3 LLM calls.

## D-030 Code validates every research claim — Decided
- A `sourced` fact, blocker or DCR claim must cite a URL that research actually retrieved. Otherwise code downgrades it to `inferred` (DCR claims to `unknown`) and records a correction note.
- Official domains must match the host of a retrieved source; others are dropped. The console URL must be on an allowed domain, otherwise it is not used.
- Allowed domains = validated official domains + sign-in domains under them. A sign-in domain elsewhere becomes a DO handoff when navigating.
- Pages to read can only be chosen from URLs already retrieved: triage cannot make the agent fetch an arbitrary URL. Web content is delimited as untrusted data, and a page cannot close the delimiter (tested).
- A proposed live test that only proves the client ID exists is flagged: a pass would be `client_recognized`, never `succeeded`.
- Prediction consistency: `succeeded` predicted alongside a sourced review/verification/partner/paid-plan blocker gets an "may be optimistic" note. The model's prediction is not overwritten; the browser run decides.
All corrections are listed in the plan and the report under "Corrections made by code".

## D-031 Unidentifiable or ambiguous app names — Decided
Not identified → `blocked` (`app_not_identified`, not resumable), next step: re-run with the company name. No plan is invented, and synthesis is never called (*observed* for `zzqx`: 1 LLM call, 8 s).
Ambiguous between products → DECIDE handoff listing up to 4 candidates plus "None of these". The chosen candidate is researched again; "None of these" → `blocked`. Without an answer, the run is saved with the DECIDE pending.

## D-032 Pause after planning — Decided (Sprint 2 only)
Until the browser loop exists, `get` stops after the plan: `status=running`, `phase=planned`, with the reason stated. It is resumable once browser execution lands (Sprint 3). This is not reported as an outcome.

## D-033 Truncated structured output — Decided
*Observed:* the first Notion synthesis failed twice with "not valid JSON". Cause: output cut off at `max_tokens=4000`, and the retry repeated the identical request. Fix: the FastRouter client reports `finish_reason` and raises `OutputTruncated`. Synthesis starts at 8,000 tokens; on truncation the retry doubles the limit (≤16,000) and asks for a shorter answer. *Observed after fix:* Notion planned on the first attempt (twice).

## D-034 Capture and verification steps are code-owned — Decided
*Observed:* the model wrote its own capture/verify steps, duplicating code's. One (Todoist) proposed also copying the account's **personal API token**, a credential other than the one being created (protocol hard stop 8). Now model capture/verify steps are never kept as steps: their text is folded into the single code-owned capture and live-test steps as research notes. The capture step says "capture only the newly created credential". Policy enforcement of this rule in the browser is Sprint 4.

## D-035 Choosing between credential types is a DECIDE — Decided (implementation in Sprint 3)
*Observed:* research often finds several credential types (GitHub: OAuth app / GitHub App / PATs; Notion: public OAuth connection / internal connection token / PAT). The model picks one ("integration ⇒ OAuth client"), but PRD §9 makes app-type choices the person's decision. The plan now lists the alternatives. **Before the browser starts (Sprint 3), CredAgent will ask a DECIDE with the model's recommendation first** whenever alternatives exist.

## D-036 Masking of labelled values refined — Decided
*Observed:* `token: Fine-grained personal access token` was masked as a secret, garbling the plan. A labelled value is now masked only if it mixes letters and digits, or is ≥ 20 characters without spaces. Exact registered secrets and prefixed key patterns are unaffected (tests both ways).

## D-037 Live research quality, 2026-11-15 — Recorded
| App | Result | Time | Quality notes |
|---|---|---:|---|
| GitHub | planned, oauth_client, predicted succeeded | 42–58 s | Console URL exactly right (`github.com/settings/applications/new`); 10 sourced facts. Alternatives (GitHub App, PATs) surfaced. Live test needs the authorization-code flow (a person approves). |
| Notion (1st) | **failed**: synthesis truncated (D-033) | 66 s | Fixed; kept in RESULTS.md. |
| Notion | planned, oauth_client (public connection), predicted succeeded + "optimistic" note | 44–83 s | Sourced provider-review step. Console `notion.so/developers` **rejected** because `notion.so` was not among retrieved hosts (conservative; see limitation 1). Proposed test was client_recognized only, and flagged. |
| Todoist (not used in development before) | planned, oauth_client, predicted succeeded | 60 s | Console URL correct. Sourced blockers. Proposed copying a personal API token (now prevented, D-034). |
| zzqx (nonsense) | blocked: app_not_identified | 8 s | No plan invented; Tavily returned only off-topic results. |
Known limitations / failure modes:
1. Official domains come only from retrieved hosts, so a provider's second domain (e.g. `notion.so` vs `notion.com`) can be missed. The browser run will then hand navigation there to the person. Sprint 3 can add redirect observation as *observed* evidence.
2. Predictions tend to be optimistic. Code flags this but does not override it.
3. OAuth-client live tests usually need the authorization-code flow (a person approves, a redirect URI receives the code). This makes **Q3 (default redirect URI) a decision needed by Sprint 5**.
4. Ranking mixes tutorials with official docs. Triage prefers official docs, and code only cites retrieved URLs, but a tutorial can still be the cited source for a step.

## D-038 How much of each source the model sees — Decided (owner request, 2026-11-15)
*Observed* on the GitHub plan: "search" sources were only Tavily's excerpt (≈1,100–1,450 chars), cut to the first 700 chars; the page was never opened. "Extract" pages were cut to their first 12,000 chars: two of four GitHub pages were 41–43% visible. The model's unknown claimed the key "Creating an OAuth app" page was truncated. **That claim was false:** the page is complete at 2,704 chars and simply doesn't cover secret generation.
Changes:
1. **Depth is recorded and shown** for every source: `snippet` (excerpt only, page not opened), `full`, or `sections` (n of m sections, chars seen of total). Shown in the plan view, the report's Sources section and the run log (`research_action.coverage`).
2. **The model is told each source's coverage** in its header (`coverage=excerpt` / `full page` / `sections …`) and must not claim truncation or absence unless it saw the page in full.
3. **Long pages are reduced to relevant sections**, not the first 12,000 chars (`research/sections.py`). The page is split at markdown headings, sections are scored for credential-related terms plus the app name, the opening section is always kept, the rest are emitted in page order with `[… section omitted …]` markers. Deterministic.
4. **Tavily `extract_depth` stays `basic`:** *observed:* `advanced` returned byte-identical text for the GitHub docs pages at twice the credit cost. Extraction now requests `format=markdown` so headings survive for section splitting.

## D-039 "Sourced" now means quote-verified — Decided
Every sourced fact, sourced blocker and documented-DCR claim must include a short verbatim `quote`. Code checks the quote against the exact text the model was shown **for the cited URL**. Matching ignores whitespace, case, quote marks, dashes, `**` and markdown link syntax, and needs ≥15 chars. Missing, too short, not found, or found only in a *different* source → downgraded to inferred (DCR → unknown), with a correction note counting the downgrades. The console URL must literally appear in its cited source's text, otherwise an "inferred" fact says so (the URL is still used if it is on an allowed domain).
Sourced facts are also tagged by code when weaker: `[code: third-party source]` (cited host not an official domain) and/or `[code: search snippet only]` (page never opened).
*Observed* (GitHub, 2 runs after the change): 7 and 8 sourced facts, all quotes verified, 0 downgrades. The console URL `github.com/settings/applications/new` is now labelled inferred, because no retrieved GitHub page prints it. The model's false "page truncated" unknown no longer appears.
Limit: a quote proves the source *says* the words, not that the model's paraphrase in `statement` is faithful. The report shows the quote next to each statement so a reader can compare.

---

## Discrepancies between documents
1. Docs location (see D-001).
2. Spec §3 lists `docs/04-CLAUDE-CODE-STARTER-PROMPT.md`, which was not provided.
3. Spec §5 `CredentialReference.storeRef` (single) vs. OAuth's two values → `parts` (D-023).
4. PRD §10 does not classify a captured-but-`invalid` credential → `failed` (D-022).

## Assumptions not yet verified
- ~~A1. Structured outputs work for the chosen models.~~ Verified (D-009).
- ~~A2. Jev latency is low enough to call on every page.~~ Verified (D-016).
- ~~A3. Tavily accepts Bearer auth.~~ Verified (D-018).
- A7. Jev's behaviour on synthetic page summaries carries over to real pages built from Stagehand observations. → calibrate on the fake provider (Sprint 4).
- ~~A4. Stagehand's local mode sends nothing off-machine except our model callback.~~ Verified (D-014).
- ~~A5. A user-supplied `user_data_dir` keeps cookies/localStorage across restarts.~~ **False** with Stagehand's own launch/close; true with CredAgent-owned Chrome (D-012).
- A6. Chrome's graceful quit flushes the profile even after a long session with sign-ins (verified only for a cookie and localStorage set seconds before quitting). → re-check during the Sprint 5 resume tests.

## Open questions (PRD §15 / spec §10)
- ~~Q1. Jev model ID, format, latency.~~ Resolved: D-009, D-010, D-016 (version cannot be pinned; logged per call).
- ~~Q2. Stagehand persistent profile and hiding page content from its model.~~ Resolved: D-012, D-013.
- Q3. Default redirect URI: local placeholder vs. the integration's real callback (e.g. Composio's). **Open: owner decision, now needed before Sprint 5** (OAuth live tests need it, D-037).
- Q4. Secret store: owner-only file (default, implemented) vs. OS keychain. **Open: evaluate in Sprint 5.** Input: Time Machine currently backs up `~/.credagent` (D-015).
- Q5. Demo app list and each provider's automation terms. **Open: Sprint 6.**
- ~~Spec open decision 5 (run-state format and location).~~ Resolved: D-024.
- Q6 (research part resolved: D-029). Budgets: research/search count, page observations, actions, per-call timeouts, retries, total run time, max plan steps. **Open: set in Sprints 2–4.** Current client defaults: LLM timeout 60 s, Jev 20 s, Tavily 30 s.
