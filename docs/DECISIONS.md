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
Budgets (`ResearchBudget`, **raised by the owner 2026-11-15, see D-040**): ≤8 searches × 5 results; ≤6 pages read, each ≤12,000 chars (relevant sections for long pages, D-038); 700-char snippets; ≤4 LLM calls (one retry each); 180 s total; ≤15 model-proposed steps. Exhaustion gives a resumable `failed: research budget exhausted`. *Observed:* 8–83 s per run, 2–3 LLM calls.

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

## D-040 Research limits raised: 8 searches, 6 pages — Decided (owner request, 2026-11-15)
Owner asked for 8 searches (was 6) and 6 pages read (was 4). Per-page size stays 12,000 chars.
Two hidden caps had to change too, or the new limits would have had no effect:
- Searches: 3 fixed queries + **up to 5** model-proposed follow-ups (was 2). Before, only 5 searches could ever run, so a limit of 6 was never reached. The triage prompt states the numbers from the budget.
- Pages: the Tavily client sends at most 5 URLs per extract request. The agent now reads pages **in batches of 5**, so 6 pages = 5 + 1 requests, with no reliance on an unverified Tavily per-request maximum.
*Observed* (GitHub, 2 live runs): 6 searches used (the model asked for 3 of 5 follow-ups); 6 pages read (2 in full, 4 partially); 8–9 sourced facts, all quotes verified, 0 downgrades; 60 s and 94 s (was 42–79 s). Synthesis input ≈ 80k chars.
In one of the two runs the first synthesis answer failed schema validation and was retried (+37 s, +1 LLM call). The reason was not logged then. Schema-validation failures are now recorded in the run log (`research_action` with `invalid output: …`). The next run had no retry. Retries stay within the 4-call LLM budget.

## D-041 Sprint 3 scope: browser on the fake provider only — Decided
Browser runs (and the DCR POST, which creates a client at the provider) work against the local fake provider only. For a real app, `get` stops after the plan and says why. Real-provider browser runs need the per-provider consent flow (protocol §2), built in Sprint 6. Public OAuth **metadata GETs** are read-only and allowed, like research.
`credagent get Fakeprov --fake-provider SCENARIO [--offline] [--headless]` runs the browser phase locally. The fixture plan (`fake_provider/fixtures/plan.json`) stands in for research, which cannot find a local site. `--offline` uses a rule-based stand-in for Jev and plain-code candidates (no API calls) so reviewers without keys can see the loop. It is a test aid, not a replacement for Jev.

## D-042 OAuth metadata discovery and DCR — Decided
GET only the RFC 8414 / OIDC well-known paths (plus a plan-cited metadata URL), only on allowed domains, HTTPS only (HTTP only for loopback), ≤6 requests, every result recorded as observed (`run.metadata_check`). DCR is eligible only if the metadata advertises a `registration_endpoint` on an allowed domain **and** research documented open registration with a verified quote. Metadata alone is never enough. RFC 7591 registration stores `client_secret` / `registration_access_token` in the secret store and registers them with the masker immediately. A 401/403 is recorded as "requires an initial access token". A DCR credential is reported `partial` (untested) until the Sprint 5 live test. *Tested on Fakeprov* (`dcr_shortcut`): registered without opening a browser; the secret is absent from run state, events and reports.
Default redirect URI: `http://127.0.0.1:8976/callback`, a **provisional placeholder** (`CREDAGENT_REDIRECT_URI`) until the owner decides Q3.

## D-043 Domain allow-list: code check + Stagehand domain policy — Decided
Code checks every observed page (off-domain → go back, then DO), every link before clicking, and policy denies off-domain navigation. *Observed:* Stagehand's `context.set_domain_policy({"allowed_domains": [...]})` blocks off-domain navigation in Chrome, both `goto` and a real link click (they end on `chrome-error://`, which the code check also flags). It is used as a **second layer**: on for the agent, **lifted only while a DO handoff is open** (the person may need e.g. SSO on another domain), then restored (tested).

## D-044 Page observation, secret safeguard, candidates — Decided
- Observation is plain JavaScript: URL, title, text, inputs, buttons, links, forms, banners, iframes. **Secret-looking values never leave the page:** input values come back only as length + flag. Credential-like elements are reported by XPath and their text is replaced with `[SECRET-ELEMENT]` in the page before it is returned. The text is masked again in Python. URLs with query tokens are logged masked.
- **Stagehand `observe()` is not called on any page that shows a credential-like element or mentions client secrets / API keys / tokens.** There, candidates come from plain-code DOM enumeration. Elsewhere, credential-like elements are excluded with `ignore_locators`. (Conservative: e.g. the Fakeprov home page mentions "client secret", so it used plain-code candidates.)
- Candidates are normalised to c0..c19 (deduplicated, denied elements excluded) with code-built descriptions incl. "(already filled)"/"(chosen)"/"(checked)".
- **Typed values are code-owned** (`FieldValues`: app name `credagent-demo-YYYYMMDD`, homepage = callback origin, callback URL, a fixed description). The PRD allows LLM-drafted text, but a fixed template is safer and enough for now.
- *Observed with real Jev:* it kept choosing "proceed" on a field that was already filled (it never sees values), and the loop hit its no-progress stop. Fix: Jev's state now includes a "Form status: already filled: …" line (labels only), and a **code rule** completes a fill/select step when the chosen field already has a value, instead of re-filling it. This removes a redundant action; it relaxes no safety rule.

## D-045 Policy engine order and rules — Decided
Fixed order before every action: (1) named hard-stop categories are **denied**: delete/remove/revoke, submit for review/publish, pay/upgrade/billing/trial, business/identity verification, sign-out/password/2FA/security settings. Account creation and sign-in buttons → DO. (2) Terms: the terms control and any submit in a form with terms (checkbox or implied wording) → DO, so the person ticks and submits. (3) Allow-list. (4) Fields: human-only fields (password, code, card, email, phone, …) → DO. **Dropdowns (e.g. app type) and checkboxes (e.g. scopes) → DECIDE.** A fill with no code-approved value → denied. (5) Regenerate/rotate secret, overwrite → DECIDE. Fills are reversible and allowed. Links on allowed domains are allowed. Buttons use Jev's risk, bumped one level when uncertain: hard-to-undo → DECIDE.
**Change made from live evidence:** risk-assessed `irreversible` (not a named category) was first **denied**. *Observed:* with real Jev, "Create app" was rated hard-to-undo (low confidence), bumped to irreversible, and the denial left the run stuck with no way forward. The PRD says hard-to-undo actions are a DECIDE, so it now goes to the person as a DECIDE with an explicit warning. Named hard-stop categories remain denied regardless of any answer.

## D-046 Browser loop, fallbacks, handoffs — Decided
Loop order per page: observe → hard checks (off-domain; limited cookie option chosen by code; DO gates; BLOCK = business/identity verification → `blocked`; credential page → stop) → candidates → **one Jev request** → PRD §8 fallbacks → policy → act → record → checkpoint. Every action is bracketed by begin/end action events (*tested:* begin and end counts match). After any handoff the page is re-observed; nothing is replayed.
Fallbacks: Jev retried once, then all-uncertain. Element/action uncertain → one LLM call picks from the same closed sets. Blocker uncertain → LLM second opinion; continue only if it says no human is needed, gives a reason ≥10 chars, and code found no gate. Risk → bump. Completion → code (credential-like element present); Jev can never declare success. Both services down → resumable `failed: service unavailable`. LLM unusable → pause for the person, with the error now logged (`fallback_error`). *Observed:* an element fallback was being asked even when Jev's action was "step complete" (element irrelevant), and its failure paused the run. The element fallback now runs only when the action is "proceed" or uncertain.
Budgets: 40 observations, 25 actions, 4 identical pages without progress, 15 min. Then a resumable stop.
Handoffs (DO) wait for Enter. While the person acts, the domain guard is lifted. If no answer arrives (closed terminal), the run is saved with the handoff pending and **Chrome stays open** (resume: Sprint 5). Fake-provider runs use a **per-run profile, deleted afterwards**. *Observed:* reusing one profile per scenario failed when a paused run's Chrome still held it. A Chrome start failure is now a plain message, not a traceback. For fake-provider runs, a paused handoff closes Chrome too: the fake site runs inside the CredAgent process and stops with it (*observed* in a fresh-clone check: the window was left on a dead site). Real-provider runs keep the window open for resume.

## D-047 Sprint 3 test evidence — Recorded
Real Chrome, offline stand-in, a harness playing the person (its requests marked `person`), 10 tests: success (no handoffs, every action bracketed); terms checkbox and implied (agent filled name + callback; handoff `DO terms`; the person accepted and created the app); sign-in; CAPTCHA; blocked (no app created); prompt injection (nothing deleted or submitted); cookie accept-only (`DO cookie_consent`); app type (`DECIDE`); domain guard lifted/restored; CLI end-to-end. In every scenario the audit shows **no forbidden event**, and terms/sign-in/CAPTCHA only ever by the person.
Online, real Jev 1.14.0 + Stagehand observe + LLM via FastRouter, headless, fake provider: success → credential page in 39 s (9 decisions, 1 DECIDE for "Create app", 0 fallback errors). Prompt injection → credential page in 36 s (1 DECIDE, nothing forbidden). Blocked → blocked in 3 s. Earlier online attempts that got stuck or paused are what led to the fixes in D-044, D-045 and D-046.

## D-048 Handoffs re-check the page before letting go — Decided (from the owner's checkpoint run)
*Observed (owner, terms_checkbox, real Jev):* Jev flagged the create-app page as needing a person, and the loop opened a **generic "unexpected"** handoff ("do what the page needs"). It never said that clicking **Create app** is part of accepting. The owner ticked the box and pressed Enter; the form was still unsubmitted, so the agent asked again with the same card, three times, with no limit.
Fixes:
1. If code has identified a terms gate on the page, the handoff is a **terms** handoff no matter what triggered it (Jev's blocker decision or policy). The card names the exact box and button: *"tick 'I have read and agree to …', then click 'Create app'"*, plus *"If you do not agree, press Ctrl+C: nothing is submitted and the run is saved."*
2. After Enter, the handoff **re-checks the page by plain code before resolving**. Gate gone → continue. Not done → *"Not done yet — still needed: click 'Create app'"* and wait again on the **same** handoff (no new card, no new Jev call).
3. After **3** Enters with the gate still there, the run is saved with the handoff pending (*"Still needed: …"*) instead of looping.
4. Card fixes: the run ID is never split across lines (it had been broken at a hyphen, making the resume command un-copyable). The resume line no longer tells people to run `credagent resume` before it exists (Sprint 5). The "Blocking" text is plainer.
Tested in real Chrome by replaying the owner's steps: tick only → Enter → "still needed: click 'Create app'" → click → Enter → credential page, with **one** handoff and terms accepted only by the person. Doing nothing 3 times → saved as waiting, nothing submitted.

## D-049 A terms-only "person needed" flag must not pre-empt the agent's form filling — Decided (owner's second checkpoint run)
*Observed (owner, terms_checkbox, real Jev):* after the agent filled the app name, Jev (correctly) flagged the page as needing a person because of the terms box. The loop treated that as "hand off now" and gave the person the terms step **before the callback URL was filled**. The person ticked and clicked Create app, and Chrome refused: "Please fill out this field". That breaks PRD §9: the agent fills every other field and leaves only the terms control and the agreement-carrying submit to the person.
Fixes:
1. If Jev (or the LLM fallback) says a person must act **and code has identified the reason as terms** (the only gate left at that point), the flag is recorded (`blocker_deferred`) and the agent carries on. Policy hands off exactly when the agent reaches the terms control or the submit. Any other "person needed" flag still hands off immediately (tested).
2. Safety net: before any terms handoff, the agent fills every **required** field in that form that is still empty and has a code-approved value. Policy still decides each fill. The card names any required field the agent could not fill.
Tested: a Jev stand-in that flags terms like the real one (checkbox + implied) → both fields filled before the single handoff, app created with the callback URL. A plan missing the callback step → required field pre-filled before the handoff. *Online with real Jev 1.14.0 + Stagehand + LLM and a simulated person:* both terms scenarios reached the credential page with one handoff, Jev's flag deferred 1–2 times, the app created with the callback URL, and terms accepted and app created by the person.

## D-050 Complete the whole form before it is submitted; hand off only what needs a person — Decided (owner request)
Owner: *"why only required fields? It should fill all fields it logically can and only hand off where a human is actually required."* That replaces D-049's required-only pre-fill. Before a form is submitted (by the person at a terms handoff, or by the agent clicking a submit button), a **form-completion pass** runs:
- every empty text field the agent has a **code-approved value** for (app name, homepage, callback URL, description) is filled, **required or optional**; values are never overwritten; policy decides each fill;
- empty fields without an approved value (e.g. a privacy-policy URL) are left empty, and the card names them;
- an **unanswered dropdown** (still on a placeholder) becomes a DECIDE before submitting. Every dropdown DECIDE now includes **"Stop here"**, so the person can always say no. A "no" ends the run `blocked` (*found while testing:* with ≥2 options there had been no way to decline);
- checkboxes/radios (other than terms) are **left at their defaults** and listed. Ticking one is a choice (e.g. a scope), i.e. the person's DECIDE;
- human-only fields and the terms control are never touched; they are listed as "for you".
The terms card now says what the agent did: *"The agent filled: “Application name”, “Description”, “Homepage URL”, “Authorization callback URL”."*
*Also found and fixed:* a dropdown's label was read as the whole wrapping `<label>` text, including every option, which bloated step records, Jev's view and cards.
Tested (real Chrome, offline stand-in): terms checkbox/implied → all four fields filled, one handoff, the created app has homepage + description + callback. Dropdown with no plan step → DECIDE before submit, scopes left unticked. "Stop here" → blocked, nothing created. *Online (real Jev + Stagehand + LLM, simulated person):* terms checkbox → the card listed the four fields, the app was created with all four values, one handoff, terms accepted by the person.

## D-051 Sprint 4: Jev fallbacks proved end to end; element fallback re-observes; LLM errors during re-plan cannot crash a run — Decided
Most Sprint 4 machinery (one five-question Jev request per page, retry once, fallbacks, hard stops, cards, cookie rule) was built in Sprint 3. Sprint 4 closed these gaps:
- **Element fallback re-observes** (spec §6.5 says "LLM re-observes and picks"). Before, the LLM picked from the candidates Jev had seen. Now the page is observed again first. If it changed, the loop starts over and the hard checks run again. If it is the same, the candidates are rebuilt (Stagehand `observe()` again when it is in use) and the LLM picks from those. This is logged as the fallback `re_observed`.
- **Fault injection for fake-provider scenarios** (`fake_provider/faults.py`): `jev: always_fail` makes every Jev call fail; `fastrouter: down` makes Jev and the LLM unreachable. The CLI honours these scenario fields (`credagent get Fakeprov --fake-provider jev_failure|service_unavailable`) and says it is simulating a fault. This is test harness code only.
- **Offline LLM stand-in** (`RuleLLM`, beside `RuleJev`): with `--offline` it answers only the fallback question, using the same rule as RuleJev. Any other request, such as a re-plan, is refused like an unusable model. It is used only for fake-provider runs and tests.
- *Found while testing:* if the LLM raised `ModelCallError`/`ServiceUnavailable` **during a re-plan**, the exception escaped the loop and crashed the run. Now it is recorded as "cannot re-plan: the LLM is unavailable" and the run hands off as stuck.
Tested: real Chrome, offline. `jev_failure` reaches the credential page; on every page Jev was tried exactly twice; all five fallbacks and `re_observed` were logged. `service_unavailable` checkpoints `service_unavailable` and ends `failed` with resumable=true, via both the loop and the CLI. *Online (real LLM fallback, Jev forced to fail):* 9 pages, 2 Jev attempts each, all five fallbacks logged, the LLM gave a reason for every pick, and the credential page was reached after one DECIDE (see D-052).

## D-052 Uncertain risk asks the person; off-domain links are refused, not handed off; card progress counts plan steps — Decided (owner reviewed the cards at the Sprint 4 checkpoint)
- **With Jev down, "Create app" becomes a DECIDE.** The spec's risk fallback is "assume the next higher risk level", and hard-to-undo actions require a DECIDE (§6.6). When Jev fails, no risk was assessed at all, so the policy treats the click as hard to undo and asks. The `jev_failure` fixture had said `handoffs: []`. That conflicts with the spec, so the fixture now expects this one DECIDE. The card says why in plain words: *"The risk of this action could not be assessed, so the agent assumes it is hard to undo; you decide."*
- **Off-allow-list links are a hard stop (deny), not a DO.** Before, if Jev picked an off-domain link, the person was asked to act, though there was nothing useful for them to do, and after three Enters the run sat waiting. Now code refuses the link, excludes it, and the agent carries on, the same as Delete or Billing. Landing on an off-domain page by other means (a redirect that `go_back` cannot undo) is still a DO handoff.
- **"n of m" counted actions, not plan steps.** For example, sample cards showed "step 11 of 7", because every field fill counted. In the browser phase it now uses the plan cursor, capped at the plan length, and the line reads "4 of 7 plan steps done; 11 actions by the agent, 0 by you".
**A hostile Jev cannot override code** (real Chrome, offline). A confident decider picked the target control whenever it was offered, called it read-only, said no person was needed, and claimed the credential was shown on every page:
- *Delete app* (prompt-injection page) → denied, not deleted;
- *Billing* → denied, never visited;
- *Partner marketplace* (off-domain) → denied, never visited;
- terms checkbox / "Create app" on a terms form → DO; terms accepted by the person only;
- CAPTCHA page with "no blocker" → DO; solved by the person only.
Each run reached the credential page only when the real credential page appeared. No forbidden audit event occurred.

## D-053 Redirect URI and secret store — Decided (owner, 2026-11-16)
- **Redirect URI (Q3):** the owner chose to keep `http://127.0.0.1:8976/callback` "for now" (`CREDAGENT_REDIRECT_URI` can override it). It is a loopback address, so nothing outside this machine can receive an authorization code sent to it. If a later integration needs its own callback (e.g. Composio's), that is a new owner decision.
- **Secret store (Q4):** the owner chose **a file with owner-only permissions**: `~/.credagent/secrets/<run-id>/<name>.secret`, with directories at 0700 and files at 0600, written atomically and created at 0600. The store refuses to read a file whose permissions have widened or whose owner is someone else, and refuses a location inside the repository. The file is **not encrypted**: anyone who can read files as this macOS user, and any backup of the home folder, can read it. *Time Machine currently includes `~/.credagent`* (D-015). CredAgent does not change backup settings itself; to exclude the folder, the owner can run `tmutil addexclusion ~/.credagent`. The OS keychain was not chosen; if wanted later, it would replace this one storage module.

## D-054 Credential capture: plain code reads only flagged elements, classifies by label, never guesses — Decided
- **Read:** on a credential page (code gate `credential_shown`), `secrets/capture.py` reads by plain JavaScript only the elements the observer had already flagged by XPath. Neither Stagehand nor any model is involved, and Stagehand is never used for candidates on credential pages (D-044).
- **Classify:** each value is named from its own attributes (id / aria-label / name), then its `<label>`, the text just before it, then the surrounding text: client secret, client ID, signing secret, API key, token.
  - **A value with no recognisable label is not stored** and only counted. A name seen twice with different values is ambiguous and also not stored. The agent never guesses which value is which.
- **Store:** every value is registered with the Masker *first*, then written to the owner-only store, then dropped. Run state gets references plus masked displays (`fpcs… (45 chars)`), and the step record says which parts were captured.
- **Shown-once:** capture happens on the first view, on the page as it is, with no reload and no navigation. Tested: a second view of the fake app page shows the secret hidden, and the captured value is the one the site issued.
- **Already hidden** (e.g. someone viewed it earlier): this becomes a DO handoff, `secret_hidden`. Regenerating invalidates the old secret, so that is the person's decision; the agent never clicks "Regenerate". After the person regenerates, the agent captures the new value. If they decline, the credential is reported as not captured.
- **Nothing capturable:** if the page has credential-like values but none is labelled, the run is `blocked`, and the person is told to copy the credential themselves.
- **Production limitations observed** on the credential page (e.g. "testing mode", "only test users", "submit for review") are kept, without secrets, and make a verified credential `partial`.
- The masked display gained a space (`fpcs… (45 chars)`). Without it, the leak masker read `client_secret: fpcs…(45` as a labelled secret and garbled the report line.

## D-055 Live verification: generic OAuth client-credentials test; everything else `untested` with the reason — Decided
- **The built-in test is an RFC 6749 §4.4 client-credentials token request.** It is sent to the token endpoint seen in the provider's own public OAuth metadata, only if that endpoint is on the allowed domains and uses HTTPS (or loopback). An issued access token proves the ID+secret pair is live; that is more than reading the client ID, as spec §6.10 requires. The token is registered with the Masker and dropped, never stored.
- **Label mapping:**
  - 200 + token → `verified`;
  - 401 / `invalid_client` → `invalid`;
  - `unauthorized_client` → `client_recognized` (authenticated, but no token);
  - other 4xx and 5xx → `inconclusive`;
  - unreachable → `untested` (no result, so never "invalid").
- **`untested`, with the reason, when no safe built-in test exists:** a public client (no secret), metadata that does not list client-credentials, no metadata, an endpoint off the allowed domains (the secret is not sent), or an API key / token. Provider-specific tests (an API key's "who am I" call; the authorization-code flow a person approves, using the D-053 callback) arrive with the real providers in Sprint 6. They need per-provider facts and consent.
- **Only `verified` with no limitations → `succeeded`** (model invariant plus `decide_outcome`). The DCR shortcut is now live-tested too, so a DCR run can be `succeeded`.
- **`credagent verify <run-id>`** re-runs the test from the stored credential, records it, and updates the outcome where the state machine allows. New transitions: `succeeded → partial|failed` and `partial → failed`, only through re-verification. For fake runs it restarts the fake site from its saved state for the test. Exit code: 0 = verified, 3 = anything else.

## D-056 Resume: re-check, never assume; never repeat an unconfirmed click; fake site keeps its state — Decided
- **`credagent resume <run-id>`:**
  - loads the run and teaches the Masker this run's stored secrets again;
  - reattaches to the same Chrome if it is still running (real-provider handoffs keep it open); otherwise relaunches it with the run's persistent profile and reopens the last observed page (only if its stored URL is intact and allowed; otherwise the console URL).
- **A pending handoff is not assumed done.** It is closed as "re-checked on resume", and the loop observes the page again. If the blocker is still there, a fresh card appears. If the person already did it while CredAgent was not running, the agent simply continues. Tested both ways: (a) the browser closed, relaunched, sign-in asked again, then finished; (b) Chrome kept open, the person signed in while CredAgent was not running, resume reattached to the same Chrome process and asked nothing.
- **In-doubt actions** (an `action_started` with no `action_finished`): if the loop is about to repeat that same click, it asks first (DECIDE). Doing it again could, for example, create a second app. "No" ends the run `blocked`. Tested both answers: exactly one app, or none.
- **Research-phase runs** (e.g. `failed: service unavailable` during research) resume by re-running research. Real-provider *browser* runs are not resumable yet, because none exist before Sprint 6.
- **The fake provider persists its state.** Its apps, sessions, tokens and audit go to `~/.credagent/fakeprov/<run-id>/state.json` (0600). The file holds the fake site's own fake credentials, like a provider's database. `resume` restarts the site on the same port with that state, and a paused fake run keeps its browser profile (removed when the run ends). This makes Flow D demonstrable with the fake site from a new terminal. Tested through the CLI (two processes) and online: a run paused at a DECIDE was resumed from a new process, the DECIDE was asked again and answered, and the run `succeeded` with one app and no leak.
- *Found while testing:* a Sprint 0 test clicked the cookie banner once, and that click sometimes had no effect in headless Chrome (banner still shown, no cookie). The agent's loop is not affected, because it re-observes and clicks again. The test now retries the same way.

## D-057 `credagent secret`: masked by default, reveal only on purpose — Decided (owner approved at the Sprint 5 checkpoint)
- **Default:** for each stored part, the masked display, the file path (with `~`) and a live permission check (`owner-only`, or `NOT SAFE: …` if the file or folders were widened). Plus: "not encrypted", and the Time Machine status (`tmutil isexcluded`). CredAgent never changes backup settings.
- **`--reveal <name>`** works only in an interactive terminal (never to a pipe or script), and only after the person types the name to confirm. It then **copies the value to the clipboard** (`pbcopy`), so it does not land in terminal scrollback. The message warns that clipboard managers may keep a history. `--print` shows it in the terminal instead, with a scrollback warning.
- I (the coding agent) never run `--reveal`. The tests use fake values in temporary folders.

## D-058 Spotify terms check (ATTEMPT-PROTOCOL §2.3) — Unclear; automated by the owner's decision (D-059)
Read 2026-11-16:
- [Developer Terms](https://developer.spotify.com/terms), version 10, effective 2025-05-15;
- [Developer Policy](https://developer.spotify.com/policy), effective 2025-05-15;
- [Terms of Use](https://www.spotify.com/us/legal/end-user-agreement/), last updated 2026-09-04;
- the Platform Rules they incorporate. The separate User Guidelines page was **not** read.
Reading the terms is not accepting them.

**Nothing addresses the Developer Dashboard UI, supervised automation or Development Mode.** Relevant clauses (paraphrased):
- **Dev Terms IV.2.4.1:** no robot, spider or other tool used to *retrieve, duplicate or index* Spotify Service content. "Spotify Service" includes Spotify's websites, so the Dashboard is arguably covered. But the clause targets content retrieval, and creating one app is not that.
- **IV.2.4.3:** do not obtain users' authentication credentials except as the Platform provides. CredAgent never types or reads passwords: the person signs in.
- **IV.2.1.4:** do not interfere with the Platform's functioning.
- **VI.1.4:** the account holder is responsible for all activity on the account, including by a third party or tool.
- **Developer Policy II.2:** no bots or scripts to *artificially* inflate plays or follows. Not relevant to creating an app.
- **Terms of Use §3:** a general "not expressly permitted" catch-all. No robot or automation clause was found in the text read.
- **Licence III.1.1:** personal, private use. That fits one test app.

**Assessment: unclear, not clearly prohibited.** Owner decision (2026-11-16): unclear wording means the console **is** automated (protocol v2, D-059). Spotify is therefore automated, and the report says the wording was unclear.

Research (run `20261116-153856-spotify-058d`, sourced) adds two facts:
- **Premium.** Spotify's Web API documentation says a **Premium** account is required, including for Development Mode.
- **Limits.** New apps are in Development Mode: one Client ID per developer, a few users, and fewer endpoints. That predicts `partial`.

## D-059 Attempt protocol v2: unclear terms → automate by default — Decided (owner, 2026-11-16)
Owner: *"by default if it's unclear; the console should be automated."* ATTEMPT-PROTOCOL §2.3 now has three findings:
- **prohibited**: not automated. This is unchanged and matches the original brief: "If automated console use is prohibited, do not run it."
- **unclear**: automated, and the report says the wording was unclear.
- **not prohibited**: automated.
A provider whose terms were never checked is still never automated. Findings live in code (`src/credagent/consent/terms.py`, one entry per provider with date and source URLs), so the CLI refuses unchecked or prohibited providers. Per-provider consent (§2.2) is still asked for in the terminal at the start of every session.

## D-060 Discord terms check (ATTEMPT-PROTOCOL §2.3) — Unclear, with a higher account risk; automated only with the owner's informed consent
The owner switched the Sprint 6 sample provider from Spotify to Discord (2026-11-16). Read 2026-11-16:
- [Terms of Service](https://discord.com/terms), effective 2025-09-29;
- [Developer Terms](https://support-dev.discord.com/hc/en-us/articles/8562894815383-Discord-Developer-Terms-of-Service), effective 2024-07-08, read in the owner's Chrome because the automated fetch got HTTP 403;
- [Developer Policy](https://support-dev.discord.com/hc/en-us/articles/8563934450327-Discord-Developer-Policy), effective 2024-07-08, also read in Chrome;
- [Community Guidelines](https://discord.com/guidelines), effective 2025-09-29;
- [Platform Manipulation Policy Explainer](https://discord.com/safety/platform-manipulation-policy-explainer), 2024-03-15.
No support article on self-bots was found or read.

**No clause addresses automating the Developer Portal.** Relevant clauses (paraphrased):
- **Community Guideline 14:** no self-bots or user-bots; each account must be associated with a human. The explainer describes self-bots as user accounts modified to perform automated actions, and says not to modify the client, *including by automating account actions*. CredAgent does not modify the Discord client, and a human is present and signs in. But "automating account actions" is broad, and an external tool driving a signed-in web session could be read as exactly that.
- **ToS §9:** no scraping by any robot, crawler or other automatic process without written consent. **Developer Policy 20:** no mining or scraping data. CredAgent reads only the credential it just created.
- **Developer Terms 2(d):** keep keys, tokens and secrets confidential, used only with your own application. Keep them encrypted in files *accessible by third parties*. CredAgent's file is owner-only and unencrypted (D-053), and not accessible to third parties.
- **Developer Policy 4:** apps may not obtain users' login credentials. CredAgent never touches passwords; the person signs in.
- **Developer Terms §9 / ToS §10:** Discord may suspend or terminate the user account or the developer credentials, with or without notice.

**Assessment: unclear**, so it is automated by default under protocol v2 (D-059). But it carries **a higher risk than Spotify**: Discord explicitly polices automated user accounts, and the penalty falls on the Discord account used. The consent screen says so. Recommendation to the owner: use a dedicated test Discord account.

## D-061 Seeing a credential-like value is not having the credential — Decided (found in the first Discord run)
*Found in real run `20261116-164345-discord-11f0`:* after the owner signed in, Discord's **My Applications** list showed one credential-like value with no label (probably an existing ID). The loop treated any `credential_shown` page as *the* credential page. Plain-code capture correctly refused to guess, and the run then ended **`blocked`, wrongly**, before anything had been created.

Fix: the loop ends at a credential page only once a **secret** has been captured. If nothing labelled was found, or only a client ID was captured (Discord's secret needs "Reset Secret" first), the step is recorded as "seen, nothing labelled to capture; continuing" and the loop keeps following the plan. Each credential-like page state is examined once, never re-captured. The terms of the run are unchanged: capture still never guesses.

Also from that run: Jev's "a person needs to act" card was generic ("Check the browser window…"). It now quotes the agent's current plan step and says "if it is already done, just press Enter".

Tested with a new fake scenario, `decoy_token`: an unlabelled token on the console before any app exists. The run continues and succeeds.

## D-062 Only secrets are registered with the Masker; IDs are captured from labels further up — Decided (found in the second Discord run)
*Found in real run `20261116-171020-discord-1588`:* the person created the app. On Discord's General Information page the agent read the credential-like values: the all-digit Application ID and the Public Key. Capture **registered every value it read with the Masker before classifying it**. The Application ID is also in the page URL (`/developers/applications/<id>/information`), which run state records, so the leak guard (`SecretLeakError`) refused the next write and the CLI crashed with a traceback. **Nothing secret was written.** The guard worked as designed; the false positive was the bug. The Application ID was also not recognised: its label ("Application ID") is a heading two levels above the number.

Fixes:
- **Only values classified as secrets** (client secret, signing secret, API key, token) are registered with the Masker, still before they are stored. IDs are stored but not registered, as the DCR path already did. Unlabelled values are not stored or written by CredAgent. The observer already removes them from page text, and the high-entropy masking rule still applies.
- **Labels are looked for further up:** the parent's previous sibling (a heading) and the grandparent's text. This applies both in the observer (for all-digit IDs) and in capture.
- **If the leak guard ever trips again, the CLI says so plainly** (exit code 4): nothing was written, and the run can be resumed after the fix.

Tested: the `numeric_client_id` fake scenario now matches Discord's layout, with the ID in the URL and the label two levels up. Unit tests check that an ID in a URL is not treated as a secret.

## D-063 One run creates at most one app; the plan moves past "create" once it exists — Decided (found in the resumed Discord run, which created three apps)
*Found in real run `20261116-171020-discord-1588`, resumed after the D-062 fix:*
1. **The plan never moved past "create".** The person had created the app (in the earlier session), but the plan cursor was still on step 3, "Click 'New Application'…".
2. **The agent went back and offered to create again.** On resume, it left the app's page for the app list and asked to click "New Application" again: a DECIDE, because the risk was uncertain.
3. **Each yes made another app.** Each "yes" plus the person's Create made another app.
4. **Nothing in code stopped it.** No rule limited a run to one app.

**Result: three apps named `credagent-demo-20261116` now exist in the owner's Discord account** (IDs ending 3211, 5969 and 9347). They must be deleted by the owner (cleanup; the agent never deletes).

Fixes:
- **Hard rule in the policy engine:** once a run has created an app (`run.created`), any click that would create another is **denied**, whatever Jev, the LLM or the person's earlier answers say. That means "New Application", "Create app", "Create new app" and a bare "Create", but not "Add Redirect", "Save Changes", "Reset Secret" or "OAuth2". The person can still do anything themselves in the browser.
- **When a run counts as having created an app:**
  - the person resolves a terms handoff whose submit button creates something (the button named on the form, or in the "By clicking Create, you agree" wording), and the page then moves;
  - the agent's own create-submit click moves the page;
  - a credential part is captured.
  Each time, the plan cursor moves past every create step, so the agent does not go back to them.
- **Resume:**
  - A run with a captured credential counts as created.
  - If the person submitted a terms form earlier but CredAgent cannot tell whether it created an app, the next create click becomes a DECIDE that warns about a duplicate: "Yes, create it (none exists yet)" or "No, one already exists". "No" records the app as existing.
  - The report's Cleanup section now lists what the run created.
- **Ctrl+C:** a second Ctrl+C while the browser was detaching printed a traceback. Detaching now never raises, and the CLI says "Stopped. The run is saved…".

Tested with a new `discord_like` fake scenario: implied terms on create, the ID in the URL, the secret on an OAuth2 page behind "Reset Secret". It creates exactly one app and succeeds. A replay decider that goes back and keeps proposing "Create app" is denied, and the audit shows one app.

## D-064 Moving past "create" skips one step, not every step that mentions it; the agent can find its own app on a list — Decided (found in the second resume of the Discord run)
*Found in real run `20261116-171020-discord-1588`, after the D-063 fix:*
- **The cursor skipped too far.** D-063 moved the plan cursor past the *last* plan step that mentioned creating an app. The run had been re-planned, and a later step mentioned "New Application" again, so the cursor jumped to the live-test step. The person was then shown a card asking them to act on "Live test…", which needs nothing from them.
- **The agent couldn't open its own app.** Before that, on the app list, it could not tell which card was its app (the plan assumed it would already be inside the app), and it showed a generic "stuck" card.

Fixes:
- **One step only:** the cursor now moves past only the first create action step at or after the current step (navigate, click, fill or handoff kinds). Later steps are never skipped.
- **Its own app is marked:** a clickable candidate whose text contains this run's app name is described to Jev as "(the app this run created)".
- **"Stuck" cards quote the current plan step** and ask the person to do it, as the "person needed" card already does (D-061).

First I asked the owner to do the remaining console steps by hand. The owner objected, rightly: *"why does agent want me to [do the] remaining steps — it has to be done by it."* Those steps are the agent's job: only the "Reset Secret" yes/no and any 2FA code belong to the person.

So a run whose saved cursor is already past every console step while no secret has been captured is now **corrected on resume**. The cursor goes back to the first step after the create step, and that correction is logged. The agent then does the remaining steps itself. The outcome is recorded in RESULTS.md.

## D-065 Jev always sees the page's own links; code-owned steps stay at the end of the plan — Decided (found in the third resume of the Discord run)
*Found in real run `20261116-171020-discord-1588`:* the agent stayed on Discord's **My Applications** list and never opened the app.
- **The app link wasn't offered to Jev.** The card is an ordinary link (`a[href=/developers/applications/<id>]`), and plain-code observation sees it. But whenever Stagehand returned any candidates, only Stagehand's were offered, and Stagehand returned at most one, never the app link.
- **Re-plans had scattered live-test steps through the plan.** The re-plan kept "done" steps, and code-owned verify steps counted as done because actions carry the current step's id. So the plan had live-test steps at positions 2, 4 and 12, and the D-064 correction moved the cursor onto one of them.
- **Jev then marked steps done without doing them.** The run reached a "2FA" step while still on the list.

Fixes:
- **Merged candidates:** Stagehand's goal-ranked candidates come first, then the page's own links, buttons and fields (deduplicated, capped at 20). The app this run created is still marked by its name (D-064).
- **Code-owned steps:** re-plans keep exactly one capture step and one live-test step, at the end. A plan saved earlier is normalised when the run starts or resumes, and the cursor is mapped to the same browser step.
- **The browser goal skips capture and live-test steps:** code does those.
- **On start or resume, if an app exists but no secret has been captured,** the agent continues from the step right after the create step. Steps that are already done are marked complete quickly, and a second app can never be created (D-063).

Simulated on this run's saved plan: 12 steps after normalising, and the resume starts at "open the OAuth2 page". Online fake check: candidates came from `stagehand+dom`.

## D-066 Rank the page's own candidates by the current step before capping them — Decided (found in the fourth resume of the Discord run)
*Found in real run `20261116-171020-discord-1588`:* on the app's General Information page, the step was "In the left sidebar of the application, open the OAuth2 page." The page has an `OAuth2` link, and plain-code observation saw it. But Jev is offered at most 20 candidates, and the page's own candidates came in page order: fields first, then buttons, then links. Discord's page has 9 fields and 11 buttons before the sidebar links, so **the one element the step named was never offered**. Stagehand, which ranks by the goal, is not used on pages showing credential-like values (D-044). So Jev answered "none of these", the agent showed a "stuck" card, and the owner was asked to click a sidebar link: *"why should I do small trivial steps"*.

**Fix:** the page's own candidates are ranked by how many of the step's words their description contains, before the cap (`rank_for_goal`). The ranking is stable, so equal scores keep page order. It is deterministic and runs in code; no model is involved. A regression test crowds the Discord-like fake app page with 9 fields and 11 buttons before the `OAuth2` link: it fails without the ranking and passes with it.

## D-067 "Generate a new client secret" is not creating an app; only the step being performed moves the cursor — Decided (found in the fifth resume of the Discord run)
*Found in real run `20261116-171020-discord-1588`:*
- **Capturing the client ID moved the plan.** On resume, the agent captured the client ID on the app page, which records "an app exists" (D-063), and moved the cursor past the next create step.
- **The wrong step counted as "create".** The create-detection pattern matched step 8, "click 'Reset Secret' to generate a **new client** secret".
- **So the agent skipped OAuth2, the redirect and Reset Secret,** and showed the owner a card for the code-owned capture step.

Fixes:
- **The pattern ignores "client secret":** it no longer treats "client" as an app when "secret" follows.
- **`_mark_created` moves the cursor only if the step the run is on is itself a create step.** Recording an app on resume or at capture never moves the plan.
- On this run's saved plan, only step 1 ("Click 'New Application'…") now counts as a create step. On restart the agent continues from "open the OAuth2 page".

## D-068 One navigator question before "stuck"; resume restarts after the end of the creation phase — Decided (found in the sixth resume of the Discord run)
*Found in real run `20261116-171020-discord-1588`:* the browser was on the app list, and the step was "In the left sidebar of the application, open the OAuth2 page." Jev answered "stuck". The LLM even said the OAuth2 link "only appears inside" an app, but did not pick the app. Both re-plans had been used long before, so the agent handed a trivial click to the owner. **The owner abandoned the run** and is deleting all `credagent-demo` apps to start Discord from scratch.

Fixes:
- **Navigator:** when Jev finds no element for the step, the LLM is asked once per page state, with a closed answer set (a candidate id or none), for the click that *leads toward* the step. Examples: opening the right item in a list, or a tab that contains it. It prefers the candidate marked "(the app this run created)" (D-064) and never picks anything that creates, deletes, submits or pays. Policy still decides on the pick, and the pick is logged (`toward_goal`). Only if nothing is picked does the run hand off as stuck.
- **The resume correction (D-064/D-065) goes to the step after the *last* create action:** creation can span several steps (open form, fill, submit). It ignores conditional steps such as "If no app exists yet, click 'New Application'".

Tested: a real-Chrome case starts on the app list with Jev forced to "stuck". The navigator opens the run's existing app, the run reaches OAuth2, and it captures and live-tests with no new app created. 74 of 74 real-Chrome tests pass.

## D-069 Formless terms buttons, unlabelled fields, repeated clicks, and "… and save" steps — Decided (found in the fresh Discord run)
*Found in real run `20261116-190534-discord-a839`* (fresh; one app created by the owner, as it should be):
1. **The agent clicked Discord's terms-carrying "Create" itself.** The owner had answered "yes" to a generic "hard to undo" DECIDE. Discord's create dialog is not an HTML `<form>`, so the rule "a submit in a terms form is the person's" found no form. The checkbox was unticked, so nothing was created, but the rule had a hole. **Fix:** any control named in the agreement wording ("By clicking **Create**, you agree…") is a terms DO, with or without a form.
2. **"Add Another" was clicked 14 times** and the redirect was never typed. Discord's redirect box has no label, so it had no approved value; Jev kept choosing the button that matched "add" until the step budget ran out. Those rows were never saved.
   **Fixes:**
   - The observer records each field's section heading (e.g. "Redirects"), and an unlabelled field is described and mapped by it.
   - A control with the same text is clicked at most twice on one page; after that it is no longer offered.
   - The form-completion pass fills each approved value once per form, not into every empty row.
3. **"… and save" steps now finish properly.** When a step says to save, after the agent has typed on the page, it clicks the page's Save / Save Changes once. The step is then complete (code rule), so Save is not clicked again.

Tested: the `discord_like` fake now copies those quirks:
- the create button sits outside its form and is named in the agreement;
- the Redirects box has no label, with "Add Redirect" → "Add Another" and "Save Changes";
- "Reset Secret" has no "hidden" marker.

The run hands Create to the person, saves exactly one redirect (the callback), asks before Reset Secret, and captures and live-tests. Unit tests cover the formless terms button and the section mapping.

## D-070 No documentation detours; return to the page the previous step reached; a closed browser is reported plainly — Decided (found resuming the fresh Discord run)
*Found in real run `20261116-190534-discord-a839`, resumed:*
- **The navigator (D-068) went to the docs.** On the app list it picked a button labelled "apps", which led to Discord's **documentation** (`docs.discord.com`, an allowed domain). There Jev declared "open the OAuth2 page" done on the docs page "OAuth2 & Permissions".
- **The redirect step then bounced.** Jev bounced between the app list and the app (`go_back` ↔ app link) without ever opening OAuth2.
- **The navigator's reply was cut off once** (300-token limit).
- **The owner then closed the browser window,** and the CLI crashed with "CDP client is closed".

Fixes:
- **Documentation pages are never part of console steps.** A page on `docs.*` or under `/docs` is undone with a code `go_back` unless the step is about the docs, so it can never complete a console step.
- **Page memory:** when a navigate step completes, its URL is remembered. If a later step then gets `go_back` or `stuck` on a different page, the agent goes directly to the remembered page (at most twice).
- **Navigator:** its reply limit is now 900 tokens, and it is told to prefer links over buttons of unclear effect and to stay in the console.
- **A closed browser window** ends with a plain message (exit code 5): the run is saved, continue with `credagent resume`.

Tested: a real-Chrome case where the decider sends the agent to the docs once; the agent goes back and the run succeeds. 74 of 74 earlier real-Chrome tests still pass.

## D-071 "Type this value" steps are checked by code: done when the box holds the approved value's length; otherwise the person decides — Decided (found resuming the fresh Discord run)
*Found in real run `20261116-190534-discord-a839`:* the owner typed the redirect themselves, as `http://127.0.0.1:8976/callback.` with a trailing full stop (most likely copied from a sentence in my instructions). CredAgent never reads field values, only their length, and the box has an aria label ("Select redirect URI"). Jev kept clicking "Add Redirect", "Add Another" and "Select redirect URI" instead of finishing the step, so the agent showed "person needed" cards. The owner had already done the step, but with a value that would not match.

**Fix:** before Jev, a `fill` step whose description maps to an approved value (e.g. the callback URL) is checked in plain code:
- **The box holds a value of the approved length:** the step is complete. If the step says save and a Save button is visible, the agent clicks it first.
- **The box holds a value of a different length:** a DECIDE says so, *"31 characters vs 30: a stray character, such as a trailing full stop, makes it not match"*, and asks whether to replace it with the approved value. "Yes" → the agent types the approved value, then saves.

Values are still never read; only their lengths are compared. Tested: the Discord-like fake starts with the callback plus a trailing full stop saved. The agent asks, replaces it, saves exactly one correct redirect, resets the secret after a DECIDE, captures and live-tests.

*Also noted:* commands and URLs in my messages to the owner sit at the end of sentences. I now put them on their own line, with no punctuation after them.

## D-072 Ranking matches names quoted in the step, and puts the run's own app first — Decided
*Found in real run `20261116-190534-discord-a839`* (the owner continued it in a tab started before D-071): a re-planned step read "Click the 'c-d-2' application in the My Applications list". Splitting the step into words drops a name like `c-d-2`, so the app link scored nothing and fell outside the 20 candidates offered. The navigator then said, correctly, that none of the candidates was the app.

**Fix:** `rank_for_goal` scores a name quoted in the step ('…', “…”) as a whole-string match (strong). When the step is about an app, the candidate marked "(the app this run created)" scores high too. A unit test reproduces the list page.

## D-073 Design: checkable steps, with progress proven by code — Approved (owner, 2026-11-17); superseded by D-078
After twelve Discord fixes (D-061 to D-072), the owner asked to step back from patching. Design: `docs/design/checkable-steps.md`.
- **Checkable steps:** every browser step gets `where`, `target` and `done_when`, from a closed vocabulary that plain code evaluates (`at_page`, `element_present` / `element_absent`, `field_holds` as an in-page equality test with approved non-secret values, `app_exists`, `credential_shown`).
- **Progress from proofs:** a step is done only with proof. The plan position is the first step not proven done, so the cursor corrections go away.
- **Better Jev requests:** each request carries progress, the failing checks, the target first, the next steps and recent actions.

Jev's five decisions, the policy rules and secret handling are unchanged. Three open questions for the owner are listed in §13 of the design. No code has been changed for it yet.

Added at the owner's request: **measure how many elements Jev should see (20 vs 40 vs 60) before building** (design §11a, step 0). The current 20 was an unmeasured Sprint 3 default.

**Approved by the owner** ("Approve, start"), with the recommended answers to the design's §13 questions:
- **Q1:** code may open an allowed console path directly; a visible link is preferred when known.
- **Q2:** steps research cannot make checkable stay *inferred*, and are handed off if one fails twice.
- **Q3:** recipes come later.
- **Q4:** measure first.

Work starts with step 0, the measurement.

## D-074 Jev's candidate limit stays at 20; the misses come from ranking and vague steps, not list size — Decided (measured 2026-11-17, design §11a)
**Measurement:** `scripts/measure_candidates.py`, fake provider only, real Jev (`jev-1.14.0`).
- **Pages:** crowded pages copied from Discord's layout (app page, 50 candidates; OAuth2 page, 54 candidates with a sidebar and about 20 scope checkboxes; app list, 19), plus a form and the home page.
- **Calls:** 9 cases × 3 limits × 3 orders × 3 repeats = **243 Jev calls**, with no Jev failures. Raw metrics in `docs/samples/candidate-limit.json`; table in `docs/samples/candidate-limit.md`.

| limit | order | correct when the target was offered | said "none" when offered | median latency | request size |
|---|---|---|---|---|---|
| 20 | ranked | **100 %** (target offered in 89 % of calls) | 0 % | 304 ms | 4.8 k chars |
| 20 | target first | **100 %** | 0 % | 322 ms | 4.8 k |
| 20 | target last (20th) | **100 %** | 0 % | 345 ms | 4.8 k |
| 40 | ranked | 89 % | 11 % | 310 ms | 6.0 k |
| 40 | target first | 100 % | 0 % | 342 ms | 6.0 k |
| 60 | ranked | 89 % | 11 % | 320 ms | 6.8 k |
| 60 | target first | 100 % | 0 % | 338 ms | 6.8 k |

**Findings:**
1. **When the target is in the list, Jev picks it**, even in 20th place (100 %). Latency is about 0.3 s at every size, so size costs little, but it does not help either.
2. **All the misses are one case.** A vague step ("Go to the page with the client credentials and redirects") ranks the `OAuth2` link 37th of 50. At 20 it is not offered. At 40 or 60 it *is* offered, and Jev still answers "none", always uncertain (confidence 0.37–0.56), which would go to the LLM fallback. **Bigger lists did not fix it.** Putting the target first did (100 %).
3. So the failures seen on Discord (D-066, D-072) come from **ranking and vague step wording**, not from the limit. That is what the checkable-steps design addresses, with named targets placed first and a `where` for each step.

**Decision:** keep `MAX_CANDIDATES = 20`. It meets the bar (≥95 % correct when offered, median well under 3 s), and 40 or 60 were no better. Re-measure with the same script if steps or ranking change.

**Limits of the measurement:** 9 cases on fake pages, 3 repeats. Real portals may differ, so this is evidence for the design, not proof for every site.

## D-075 Checkable steps implemented: progress proven by code — Decided (implements D-073); superseded by D-078
Built per `docs/design/checkable-steps.md`, steps 1–5:
- **Checks (`src/credagent/steps/checks.py`):** the closed vocabulary.
  - `at_page` binds `{app_id}` and never matches docs.
  - `element_present` / `element_absent` match buttons, links, fields, headings and dialogs; the observer now records headings.
  - `field_holds` is an **in-page equality test** returning only true/false, allowed only for approved non-secret values, and refused on secret, password or code fields.
  - Also: `field_empty`, `checked`, `app_exists`, `credential_shown`.
- **Step format:** `PlanStep` gains `where`, `target`, `value`, `done_when` and `inferred`; `Run` gains `proofs` and `bindings`. The validator (`steps/validate.py`):
  - removes model conditions from the code-owned capture and live-test steps;
  - keeps only allowed-domain pages in `where`;
  - adds `app_exists` to the step that actually creates (the last non-conditional create step);
  - marks agent steps without a checkable condition as *inferred*.
  The converter (`steps/convert.py`) drops any invalid condition with a note.
- **Loop (proof mode, when a plan has conditions):**
  - after every observation, code evaluates the current step and later steps on their own page; global checks (`app_exists`, `credential_shown`) are evaluated from any page;
  - proofs are recorded (`step_proven`); a proven later step implies the earlier ones (linear flows; recorded as *implied by*);
  - **the position is the first step without proof**;
  - Jev's "done" is a hint: if the checks disagree, the next request says which check is false (`jev_complete_rejected`), and a third rejection hands over to the navigator or the person;
  - if a field the step names holds a *different* value, the person decides whether to replace it (D-071).
- **Going to the step's page:** if the step happens on another page, code goes there first: a link on the page, then a link seen earlier in the run, then the allowed path itself (owner Q1).
- **Jev request:** a structured block with the current step, done-when lines (✓/✗), a note when "done" was rejected, what is already done, the next two steps, and the last three actions with their effect. The step's named target is candidate `c0`.
- **Research and re-planning:** both write `where_path`, `target_role` / `target_name`, `value` and `done_when` in the same JSON shape, through the same validator. Re-planning never rewrites proven steps.
- **Legacy mode:** plans without conditions (all saved runs, including Discord #4) keep the earlier behaviour, and the cursor corrections and save heuristics run only there. In proof mode they are not used.

**Tests:**
- unit: every check, the validator, the converter, the position rules (implied proofs, `{app_id}` binding) and the Jev block;
- research: conditions flow into the plan, and invalid ones are dropped;
- real Chrome:
  - the `discord_like` run is proven step by step (page, field held *and saved*, app exists);
  - a lying "done" is rejected;
  - legacy plans still run;
  - all earlier regression tests (D-061 to D-072) pass in proof mode. **79 of 79 real-Chrome tests pass.**
- **Online** (real Jev, Stagehand and LLM, fake provider): succeeded, every step proven by code checks, with **5 Jev decisions** where earlier runs took about 9–12.

*Found while building:* an `{app_id}` learned from a step's done-when (rather than its `where`) was discarded. Fixed and unit-tested.

## D-076 App names are not secrets; "app exists" also reads link text — Decided (found in Discord run #5)
*Found in real run `20261117-080548-discord-1971`, the first real run with checkable steps.* Research wrote a check for every step; the redirect and Save steps were split as intended. The person clicked Create, and the run recorded the app as created.
- **Why it stalled:** the create step's check, "this run's app exists", stayed false on the app list. The observer treats a 20+ character mix of letters and digits as a possible secret and removes it from page text. `credagent-demo-20261117` qualifies, so the app's name was hidden from the text the check read.
- **What happened next:** the agent stayed on "Click 'Create'" and showed "person needed" and "stuck" cards.

Fixes:
- **The run's own values are names:** the observer is given the run's own approved, non-secret values (app name, homepage, callback, description) and never flags them as credentials. *Correction:* I first exempted all lowercase word slugs. That also exempted the fake site's client ID (`fpcid_…`) and could exempt real tokens such as Slack's `xoxb-…`, and three real-Chrome tests failed. So the exemption now covers exact approved values only.
- **`app_exists` reads more text:** link, button and heading text as well as page text.
- A unit test reproduces the list page.

The run is resumable. Its proofs so far, and the app, are kept.

## D-077 Capture and live test are never Jev's; a reset-for-secret is a DECIDE the agent then carries out; "not shown" checks wait to be sure — Decided (found resuming Discord run #5)
*Found in real run `20261117-080548-discord-1971`, resumed with D-076.* Progress, all proven by code: "app exists", the OAuth2 page (with `{app_id}` bound from the URL), "the Redirects box holds the callback", and "Save Changes is not shown". The person clicked into the app once, because Jev had no app link to offer.

Then:
1. **No browser step reset the secret.** Research had folded "click Reset Secret" into the code-owned capture step as a note.
2. **Jev completed the capture and live-test steps.** Its "done" was accepted on them as on any step without a condition. With nothing left, Jev kept saying "done" on the OAuth2 page until the no-progress check handed off.
3. **"Save Changes not shown" was proven right after typing.** The live page later showed no unsaved-changes bar and the box holding the exact callback, so it was most likely saved, but the proof had not waited.

Fixes:
- **Code-owned steps are never completed by Jev.** A "done" on capture or verify is rejected, with a note that code does the capture.
- **At the capture step,** if no secret has been captured and a reset/regenerate control is visible ("Reset Secret", "Regenerate secret", "Reset Bot Token" …), the person gets a DECIDE. It explains that a new secret is generated, that any old one stops working, and that nothing uses this run's app yet. After a "yes" (here, or via the usual secret-rotation DECIDE on a reset step), the agent clicks it and confirms the provider's "are you sure" dialog ("Yes, do it!"), because the person already decided. Codes and 2FA stay with the person, through the hard checks.
- **Stable "not shown":** a step whose done-when includes `element_absent` is re-checked after 1.5 s before it is proven.
- **Diagnosis:** the `decisions` event now logs the first 20 candidate descriptions offered to Jev.

Tested: the Discord-like fake now shows the "Reset the client secret?" dialog. A plan *without* a reset step gets the DECIDE at capture, then the confirmation, exactly one regeneration, capture and a verified live test. 80 of 80 real-Chrome tests pass.

## D-078 Architecture change: an LLM agent loop over Playwright, run by the orchestrator; Jev and Stagehand removed — Decided (owner, 2026-11-17)
**Owner's decision and reasoning (verbatim):**
> *"I want to keep the following architecture to make things simple since Jev performs well only in bounded set up and is mostly stateless. Managing state via code and giving exhaustive set of bounded action for unfamiliar apps would is leading to a complex system which is also tough to debug what broke where."*
>
> *"User Request -> Orchestrator (Maintains workflow state and controls execution) -> LLM Reasoning Layer (Observes page → chooses next action → returns structured output -> Playwright Executor (Click · Type · Navigate · Scroll · Inspect) -> Browser Observation (DOM snapshot · URL · Visible elements · Page changes). Observation feeds back into the LLM until the objective is reached or the workflow is stopped. So basically it's Playwright + LLM overlooked by an orchestrator. Simple."*
>
> *"That means we're not using jev and stagehand. It is making the process tough to debug and introducing statefulness via code is becoming complex, hence we should move in this direction."*

**Evidence behind it** (the Discord runs and D-074):
- **Jev's element choice** was fine: 100 % when the target was offered.
- **Jev's action and risk answers were weak:** uncertain on 27 % and 43 % of 130 live decisions. 13 of 20 "go back" answers came straight back, and the uncertain-risk rule produced most of the unnecessary questions.
- **Stagehand added almost nothing:** 114 of 132 decisions used only plain-code candidates.
- **The code built to compensate caused most of the bugs:** 10 of the 17 fixes from D-061 to D-077 were in CredAgent's glue code (plan position, candidate building, observer heuristics).
- **Every failure took a long trace to localise,** across code, Stagehand, Jev, the fallback LLM, the navigator and re-planning.

**What changes (supersedes):**
- **PRD:**
  - F4 ("Browser loop with Stagehand … Jev decisions …"), F5 (Jev's five closed decisions), §8 (decision layers and the Jev-failure rule);
  - the §13 risks on Stagehand and Jev; §14 key decisions 1, 4, 5 and 6 ("Stagehand", "Jev only for the five closed decisions", "LLM second opinion", "one key for LLM, Jev and Stagehand").
- **Engineering spec:** §3 (Stagehand, Jev), §6.4 (browser loop with Stagehand), §6.5 (Jev decision layer), and the Jev/Stagehand items in §9.
- **Owner's original brief:** *"Browser automation is mandatory and must use Stagehand"* and *"Jev makes exactly five closed decisions per page."* The owner, as author of the brief and the PRD, replaces both. The rest of the brief stands.
- **Designs:** D-073/D-075 (checkable steps) are superseded. Their step machine (position, proofs, conditions) is dropped, though some ideas may be reused as plain safety checks; see the scoping document.

**What does not change:**
- **Code still owns** hard stops, policy order, secret handling, terms, consent, the one-app rule, state and checkpoints, verification, and reports. *"Neither the LLM nor any model can override code policy"*, and the policy is applied before every executor action.
- **Secrets** are read only by plain browser code and masked before every model call and every write.
- **The browser** stays headed and visible, with a persistent profile, local only.
- **Handoffs:** DO/DECIDE, cards, resume and per-provider consent stay; so does ATTEMPT-PROTOCOL v2.
- **Only `verified` gives `succeeded`.**

**Approved by the owner (2026-11-17), with the recommended answers to the scoping's five questions:** start with `anthropic/claude-sonnet-5.5` for the loop and measure; no screenshots for the model at first; keep the four code safeguards (docs-detour, repeat guard, form completion before a terms handoff, one app per run); research steps become plain guidance; the old code is removed from `main` after phase 5, tagged `pre-d078`. Phase 1 started.

Scoping (what is reused, what is new, what is removed, risks, phases): `docs/design/llm-browser-agent.md`. The PRD, spec, sprint plan and README are updated when the rewrite lands, not before, so the documents stay true to the code at every commit. This entry is the record of the change until then.

## D-079 D-078 phase 1 done: Playwright session, snapshot with refs, executor — Decided (implementation record)
Built as **new modules beside the old ones**, so the 80 earlier real-Chrome tests stayed green until phase 5 removes the old code:
- **`browser/pw_session.py`:** Playwright `connect_over_cdp` to the existing `ChromeProcess`. Reattach to a still-running Chrome from the saved pid and port; `detach()` leaves Chrome open; `close()` quits it gracefully. It also provides the browser-level **domain guard** (main-frame navigations outside the allowed domains are aborted; the person's handoffs lift it).
- **`browser/snapshot.py`:** the agent's view of a page. The observer now also reports the interactive elements in document order, and the snapshot numbers them `e1…eN`. It shows URL, headings, dialogs, scroll position, element roles, names, states, options and links, and trimmed text. **Credential-like elements are never listed. Field values are never reported, only filled or empty.** Everything is masked. `describe_change(before, after)` says what an action did, including "no change".
- **`browser/executor.py`:** click, type, select, navigate, scroll, inspect, back and wait. A ref is valid only for the snapshot that issued it and while the page is at the same address ("stale ref" otherwise). It refuses password and read-only fields, non-http(s) addresses and disabled controls. `inspect` on a field answers only whether it holds one of the run's approved values. A link that opens a new tab moves the executor to that tab. A closed browser raises `BrowserClosed`.

**Findings:**
- **Playwright works with the existing Chrome** (launched with Stagehand's flags): the persistent profile survives a graceful close (cookie still there after relaunch), and a detached Chrome can be re-attached with its page intact.
- **After an aborted (blocked) navigation, Chrome moves the tab to an error page** that interrupts the next navigation. The executor now waits briefly and goes back, returns "blocked: that address is outside the allowed sites", and leaves the tab where it was.
- **The Stagehand-specific Chrome flags** are not needed by Playwright. They stay until phase 5, then are trimmed.

**Tests:** 5 unit tests (refs, secrets never in a snapshot, rendering and trimming, change description) and 6 in real Chrome (profile persistence, reattach, the domain guard, every action on the fake create form, the refusal rules, secrets in a snapshot or `inspect`, new-tab adoption and a closed browser). **86 of 86 real-Chrome tests pass.**

## D-080 D-078 phase 2 done: step contract, prompt builder with leak guard, LLM caller — Decided (implementation record)
New package `src/credagent/agent/`, beside the old code (still untouched):
- **`step.py`: the contract.** The model returns ONE action as strict, flat JSON (no nested objects): `action` (click, type, select, navigate, scroll, inspect, back, wait, ask_person, done, give_up), `ref`, `value_key`, `option`, `url`, `direction`, `wait_ms`, `person_kind` / `person_why` / `person_options`, `reason` and `expected`. Code then does three things, in order:
  1. **Parses it** (extra fields refused).
  2. **Validates it against the live snapshot.** The ref exists and suits the action. Typed text is an approved value **key**, never free text. A dropdown option exists. An address is on an allowed site and not documentation. A handoff request is well formed. A rejection is a message written for the model, e.g. "ref e99 is not in the current snapshot".
  3. **Turns it into a policy input** (`to_proposed`) in the *unchanged* label format, so every existing hard stop and policy rule still applies: terms (the control named in the agreement wording), delete, reset-secret DECIDE, permission DECIDE, human-only fields, and one app per run. Read-only actions and handoffs need no policy input.
- **`prompt.py`: the input.** A stable 660-token system prompt (page text is *data*; never accept terms; handoff rules; approved keys only; one app; never delete; capture is done by code; do not repeat "no change" actions). Then the objective, the research guide (capture and live test shown as "done by code"), the last 8 actions with what each changed, code notes, and the numbered snapshot last. It is capped at about 36,000 characters. **Leak guard:** everything is masked, then the finished prompt is checked against every registered secret. A match raises `PromptLeak` and the prompt is never sent.
- **`llm.py`: the caller.** One structured call per step. Invalid output is retried once, with the problem named. Cut-off output is retried with more room. A failed call is retried once. An outage twice in a row raises `LLMUnavailable`, so the run ends `failed: service unavailable`, resumable (PRD §8). This module is an addition to the scoping's list: it keeps the loop smaller.

**Tests (all unit, no network):**
- the schema is strict and flat and matches the model;
- anything outside the contract is refused;
- every validation rule has a positive and a negative case;
- **the policy path:** a Create button named in the agreement wording is a DO, Delete is denied, Reset Secret and permissions are DECIDEs, "Email" fields stay the person's even with an approved key, and a second Create after one was made is denied;
- **the leak test:** a registered client secret, a registered token and an *unregistered* token-shaped string, planted in the guide, history, notes, snapshot text, element names, title and the objective, appear nowhere in what would be sent, and a broken masker is caught by the final check;
- retries, cut-off output, outage and a leaking prompt that makes no call.

**Real-model smoke check** (fake-provider pages → real prompt → `anthropic/claude-sonnet-5.5`; a throwaway script, not a repo test). All five answers were valid on the first attempt:

| Page | Answer | Policy |
|---|---|---|
| Console, no app yet | click "Create new app" | allow |
| Create form | type `app_name` into "Application name" | allow |
| Sign-in wall | ask_person, kind DO | – |
| Console with a notice telling agents to delete all apps | ignores it as page data; clicks "Create new app" | allow |
| Credential page, secret shown | done | – |

Latency was 2.2–3.1 s and 2.4–2.5k tokens per call on these small pages. Real portals will be larger, so cost and speed are measured properly in phase 6.

**Open for phase 3 (needs a decision):** the policy engine needs a *risk* for a button click. Jev used to supply it, and when it was unsure the engine assumed "hard to undo", which caused most of the repeated yes/no questions. The new loop has no Jev, so code must assign risk. Recommendation in the phase 3 report.

---

## Discrepancies between documents
1. Docs location (see D-001).
2. Spec §3 lists `docs/04-CLAUDE-CODE-STARTER-PROMPT.md`, which was not provided.
3. Spec §5 `CredentialReference.storeRef` (single) vs. OAuth's two values → `parts` (D-023).
4. PRD §10 does not classify a captured-but-`invalid` credential → `failed` (D-022).
5. **PRD F4/F5/§8/§14 and spec §6.4/§6.5 (Stagehand, Jev) are superseded by D-078** (owner, 2026-11-17). Those documents are updated when the rewrite lands; until then D-078 is authoritative.

## Assumptions not yet verified
- ~~A1. Structured outputs work for the chosen models.~~ Verified (D-009).
- ~~A2. Jev latency is low enough to call on every page.~~ Verified (D-016).
- ~~A3. Tavily accepts Bearer auth.~~ Verified (D-018).
- A7. Jev's behaviour on synthetic page summaries carries over to real pages built from Stagehand observations. → calibrate on the fake provider (Sprint 4).
- ~~A4. Stagehand's local mode sends nothing off-machine except our model callback.~~ Verified (D-014).
- ~~A5. A user-supplied `user_data_dir` keeps cookies/localStorage across restarts.~~ **False** with Stagehand's own launch/close; true with CredAgent-owned Chrome (D-012).
- ~~A6. Chrome's graceful quit flushes the profile even after a long session with sign-ins.~~ Partly verified in Sprint 5: in the online resumed run, the cookie-consent choice made before Chrome closed was still there after the relaunch, and the fake site recorded no second choice (D-056). Sign-in persistence across a restart is covered by the Sprint 0 test (D-012). A long signed-in session on a real provider is still unverified (Sprint 6).

## Open questions (PRD §15 / spec §10)
- ~~Q1. Jev model ID, format, latency.~~ Resolved: D-009, D-010, D-016 (version cannot be pinned; logged per call).
- ~~Q2. Stagehand persistent profile and hiding page content from its model.~~ Resolved: D-012, D-013.
- ~~Q3. Default redirect URI.~~ **Decided by the owner (2026-11-16): keep `http://127.0.0.1:8976/callback` for now** (D-053).
- ~~Q4. Secret store.~~ **Decided by the owner (2026-11-16): a file with owner-only permissions** (D-053).
- Q5. Demo app list and each provider's automation terms. **Open: Sprint 6.**
- ~~Spec open decision 5 (run-state format and location).~~ Resolved: D-024.
- Q6 (research part resolved: D-029). Budgets: research/search count, page observations, actions, per-call timeouts, retries, total run time, max plan steps. **Open: set in Sprints 2–4.** Current client defaults: LLM timeout 60 s, Jev 20 s, Tavily 30 s.
