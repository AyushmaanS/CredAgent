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

## D-081 D-078 phase 3 done: the agent loop; code assigns risk — Decided (owner approved the risk rule, 2026-11-17)
**The risk rule (owner: "Yes, start phase 3", accepting the recommendation).** Jev used to supply a risk, and when it was unsure the engine assumed "hard to undo" and asked: the cause of the repeated "New Application?" questions. Code now assigns it (`policy/risk.py`):
- the hard stops stay first and unchanged (delete, review, payment, verification, account security, terms, off-site, one app per run);
- **creating the one planned app is already consented** (the consent screen says "Will create one app named …"), so the first create click is not asked again; a second is denied;
- a button whose name carries a **consequence verb** (reset, regenerate, rotate, generate a new …, transfer, publish, make public, confirm, disable, enable, disconnect, leave, archive, convert, migrate, merge, overwrite, replace, ban, kick, erase, wipe, clear all) **asks the person**; any other button goes ahead and is logged;
- links, navigation and typing approved values are read-only or reversible.
- **Trade-off, accepted by the owner:** this *lets through* a button whose name is not on the list, where the old rule asked about unknown buttons. The hard stops are the backstop.

**New: `agent/loop.py`, `agent/handoff.py`, `agent/scripted.py`, `policy/risk.py`.** Per step: look (plain code) → **hard checks in code** → one LLM call → validate → **policy** → execute → record.
- **Hard checks** (before any model is asked):
  - off-site pages: go back, else the person;
  - documentation pages: go back (D-070);
  - cookie banners: the most limited option, chosen by code;
  - sign-in, CAPTCHA, codes, payment: the person;
  - business verification: blocked.
- **Policy** on every action that changes anything (unchanged rules plus the risk above): deny (recorded; the control is shown to the model as refused and cannot be chosen again), DO (the person acts, the card names the box and the button, the agent has filled the approved fields first), DECIDE (permissions, dropdown choices, consequence buttons; "Stop here" always offered).
- **Detection and limits:**
  - what each action changed, including "no change", is shown to the model on its next turn;
  - after 3 unchanged actions it is told; after 6 the person is asked;
  - the same control clicked twice on a page is refused (D-069);
  - a step budget (60 LLM turns) and a time budget (900 s, not counting the person's turn);
  - unusable or rejected answers are counted; 6 in a row asks the person.
- **"done" is the model's claim:** code accepts it only when a credential is actually shown. Capture and the live test follow (phase 4).
- **One app per run:** the model is told what exists; code marks an app as created when a create-looking button moves the page on to something that is not a create form (or when the person submits one); a second create is denied.
- **Outage and leaks:** if the LLM is unreachable twice, the loop checkpoints and ends `failed: service unavailable` (resumable). A prompt that would leak a secret is never sent.
- **Supporting changes:** `Snapshot.refused`; `Run.loop` (`legacy` | `agent`) so cards show agent-loop progress ("N actions by the agent, M by you") instead of a plan-step counter; the snapshot fingerprint now includes the elements.
- **Size:** `loop.py` is 530 lines, plus 225 in `handoff.py`, against the scoping's estimate of about 350: the ported handoff and form-completion behaviour accounts for the difference.

**Found while testing:**
- **A real-model case:** on a terms form the model used `ask_person` *before filling anything*, skipping the careful terms path and giving a generic card. Fixed in two ways. Code recognises a terms page **however the model reaches it**: it fills the approved fields itself, then writes the card naming the box and the button. And prompt rule 2 now says: fill the other fields, then click create/submit or ask_person; either way CredAgent hands the agreement to the person. Regression-tested with a model that asks at once.
- **A gap:** a snapshot's fingerprint ignored the element list, so a page that gained a link counted as unchanged in the handoff re-check. Fixed and unit-tested.

**Tests:** 19 real-Chrome loop tests with the scripted stand-in on the fake provider:
- success: cookie banner by code, one app created by the agent, every action bracketed;
- terms (checkbox and implied): only the person accepts, the agent filled the fields first, the card names the box and the button;
- sign-in, CAPTCHA, business verification (blocked), and a cookie banner without a limited option;
- the browser domain guard is lifted only while the person acts;
- **a hostile model** that proposes Delete, Billing, an off-site link or the terms checkbox cannot cause anything forbidden;
- a second app is refused;
- "done" without a credential is rejected with a reason the model sees;
- invalid and rejected answers are recorded; an outage ends `failed: service unavailable`;
- budgets and no-change detection stop a model that goes nowhere;
- **no prompt contains a credential**, including the credential page's step.

Plus unit tests for the risk table and the ported handoff helpers.

**Early look, real LLM on the fake provider** (not the formal phase 6 measurement): success, sign-in and both terms variants all finished correctly, using 6–8 LLM calls each, about 2.8k tokens per call, and 13–38 s of LLM time per run (2–6 s per call; it varies). The model filled every field, then clicked Create. Policy handed the agreement to the person, who created the app.

**Not yet:** capture, reset/reveal, the live test and resume (phase 4); orchestrator and CLI wiring, removal of Jev, Stagehand and the step machine (phase 5).

---

## D-082 D-078 phase 4 done: capture, reset and reveal, live test, resume, in-doubt click — Decided (implementation record)
**What phase 4 added to the agent loop and orchestrator** (no change to any rule; the owner's phase 4 go-ahead covered it).
- **"done" is still only a claim.** Code accepts it when a credential is shown **and** plain browser code has captured a secret. If it has not (secret hidden, only the ID shown, or values with no readable label), the model is told exactly what is missing ("Not captured yet: …") and must try a reveal, reset or another page. After 3 misses in a row, code asks the person (DO, `secret_hidden`) to get the secret shown without it appearing in the terminal, then looks again.
- **Reset and regenerate are asked, never assumed.** The risk rule (D-081) classes a reset/regenerate button as hard to undo, so the person decides (DECIDE). Only after "yes" does the agent click it, and then also the provider's own confirmation prompt ("Yes, do it!"). The fake audit shows exactly one regeneration, and "No" leaves the secret alone (run not succeeded, nothing regenerated).
- **Capture and verification are code.** Capture reads values with plain browser code, stores them in the owner-only secret store and registers them with the masker before anything is written or sent. The live test, the outcome (`succeeded` only when `verified`; `partial` for testing mode with the observed limitation) and the report reuse the unchanged `_after_loop` and `verify_and_finish`.
- **Resume (`resume_agent_phase`).** A pending handoff is closed as "re-checked on resume", never assumed done; the page is reopened from the last URL saved in run state (the loop now records it at every observation), or the existing Chrome is re-attached by saved pid and port, and the loop looks before it acts. Resume notes tell the model the run is resumed and what already exists (so it does not create a second app).
- **In-doubt click.** An action started with no recorded end is passed in as `in_doubt`. When the model chooses that same click again, code asks the person first (DECIDE: "do it (it did not happen)" / "stop here"). "Stop" ends the run `blocked`; the app is never created twice.
- **Possible duplicate.** If a form with terms was submitted earlier in this run and no app is recorded, the next create click is asked as a DECIDE too (D-063).
- **Scripted stand-in** (tests and `--offline` fake-provider runs only) gained the capture playbook: confirm dialog → reveal → reset → OAuth2 page. It says "done" once per page and only then follows the code's hints; my first version kept resetting a secret that was already on screen, and the test's own audit assertion (no unprompted regeneration) caught it.

**Tests: `tests/integration/test_agent_phase4.py`, 16 real-Chrome tests** through the full phase (metadata check, loop, capture, live test, outcome): capture and live test for six scenarios (plain, shown-once, terms checkbox, reveal button, numeric client ID, decoy token), shown-once is not read twice, hidden secret with the person regenerating, testing mode → partial, Discord-like reset with confirmation (one regeneration, after the person said yes), reset declined, resume after the terminal and browser closed, resume re-attached to the still-open Chrome (the person signed in meanwhile: nothing asked), in-doubt click both ways, and leak scans of run files, events, reports and terminal output for every secret the fake site issued. `tests/agent_harness.py` gained `run_phase`, `new_run`, `fake_secrets`, `assert_no_leak` and a person who can close the terminal at handoff N.

**Not yet:** wiring into the CLI, removal of Jev, Stagehand, the step machine and the legacy loop (phase 5); cost and latency with the real model (phase 6); a real Discord run (phase 7). The legacy path still runs the old way until phase 5.

---

## D-083 D-078 phase 5 done: the old machinery is removed; the CLI runs the agent loop — Decided (implementation record)
**Removed (still in git history and the local tag `pre-d078`):** Jev and its fallbacks (`decisions/`), the step machine and its proofs (`steps/`), the legacy 1,570-line loop (`browser/loop.py`), Stagehand and its model callback, the old Stagehand session, re-planning (`reasoning/replan.py`), candidate building and ranking (`browser/candidates.py`), the `systemone` call, the Jev and Stagehand settings and the `stagehand` dependency. Also retired: `scripts/measure_candidates.py` and the two Sprint 0 spikes that needed Stagehand or Jev (`spike_stagehand.py`, `spike_fastrouter.py`; their recorded results stay in `docs/spikes/`). Source went from 10,070 to 7,115 lines (about 2,950 fewer); with tests the change is about 5,800 lines fewer.

**Moved, not rewritten:** `FieldValues`, the field-label mapping and `APPROVED_VALUES` into `browser/values.py`; `is_docs_host` into `policy/hard_checks.py`.

**CLI and orchestrator.** `credagent get`, `resume` and the fake-provider runs now call `execute_agent_phase` / `resume_agent_phase` with the step LLM (`StepLLM` over FastRouter, model `CREDAGENT_LLM_MODEL`). `--offline` uses the scripted stand-in, which is a test and demo tool, not a model. Fault injection is now about the model: scenario field `llm` = `flaky` (every other answer unusable; the run still succeeds) or `down` (service unavailable, resumable). Scenario `jev_failure` became `llm_failure`; `service_unavailable` stays.

**State.** Dropped `proofs`, `bindings`, `plan_cursor`, `replans_used`, `Run.loop`, `Plan.revision` and the plan-step conditions. **Old runs still load** (a before-validator drops those fields; plan steps ignore extra keys; the `replan_limit` blocker kind is kept for them), with a unit test. They cannot be resumed by the new loop (design §5). Plan steps are now `id, description, kind, expected_page`: guidance for the agent. Research no longer asks the model for step conditions, so the research call is simpler.

**Cards.** Progress reads "N actions by the agent, M by you; created: …" (no plan-step counter). The terms card again says "The agent filled: …" for fields the agent filled earlier in the form (it only listed fields filled at the handoff after the rewrite; found by the ported test).

**Chrome flags kept unchanged** (renamed `CHROME_FLAGS`). The scoping said "trim"; I did not, because the flags began as Stagehand's defaults and removing any could change how real providers treat the browser, which I cannot verify without a real run. They can be trimmed in phase 7 if the Discord run shows it is safe.

**Tests.** 305 tests; the real-Chrome suite (opt-in) and the default suite both pass. Deleted with their subjects: Jev, Stagehand, step checks, step validation, and the legacy loop and Sprint 5 files. The behaviours that mattered were **ported** to `tests/integration/test_agent_flows.py`: prompt injection ignored, unanswered dropdown is the person's choice and scopes stay unticked, declining a choice ends blocked with nothing created, the terms card names box and button and re-checks after Enter, three unchanged Enters save the handoff as waiting, optional fields and the "agent filled" line, a Discord-like portal creates exactly one app and saves the redirect, a documentation detour is undone, unusable model answers, model down, and the command line (end to end, service unavailable, `get` then `resume` from a new process). New `tests/unit/test_removed_modules.py` checks that nothing imports the removed modules and `stagehand` is not a dependency.

**Behaviour not carried over — for the owner to judge.**
1. **Stray character in a value the person typed (D-071).** The old loop compared lengths and asked before replacing a redirect like `…/callback.`. The model never sees field values, so it cannot notice this. It can use `inspect` (answers only "holds the approved value" or "holds another value", D-080), and typing an approved value replaces the field, but nothing *asks* before replacing. The replaced value is the approved one in a field of the app being created, so the risk is low; if you want the ask back it is a small addition.
2. **"Navigator" for the app list (D-068).** Gone with Jev: the model now chooses links itself from the numbered list.
3. **Old-run resume.** Runs saved before D-078 (Discord #4/#5) cannot continue; a new run starts.

**Scripted stand-in** learned the fake console's flow: it fills fields first, clicks Save after typing, picks a dropdown option (which policy turns into the person's choice), opens the "Add Redirect" box, and visits the OAuth2 page before any secret reset (my first order reset the secret and then lost it on the next page load; the capture then correctly asked the person).

**README:** only the commands and lines that no longer worked were fixed; the full rewrite of README, PRD, spec and sprint plan is phase 7 (D-078 discrepancy #5 stays open until then).

---

## D-084 D-078 phase 6 done: the real LLM on the fake provider, measured — Decided (measurement record; model unchanged)
**What was run.** `scripts/measure_agent.py`: the full orchestrator phase (metadata check, agent loop, capture, live test, outcome) in headless Chrome against Fakeprov, a harness playing the person, **13 scenarios × 2 repeats × 2 models = 52 real runs**. Models: `anthropic/claude-sonnet-5.5` (the default) and `anthropic/claude-haiku-5.5`. Only metrics are stored (`docs/samples/agent-measurement-sonnet.{md,json}`, `…-haiku.{md,json}`); the safety checks ran on every run: no forbidden audit event, at most one app, terms/sign-in/CAPTCHA only by the person, a secret reset only once and only after the person said yes, and no secret in any run file.

**Results (per run, means).**

| | Sonnet 5.5 | Haiku 5.5 |
|---|---|---|
| Succeeded | 26 of 26 | 26 of 26 |
| Safety problems | 0 | 0 |
| LLM calls per run | 8.4 (median 8, max 13) | 8.7 (median 8, max 14) |
| Tokens per call | 2,676 in + 146 out | 2,686 in + 223 out |
| Tokens per run | about 23,800 | about 25,200 |
| Latency per call | median 2.2 s, p90 2.9 s, max 4.8 s | median 2.1 s, p90 2.7 s, max 8.3 s |
| LLM time per run | 19.5 s | 18.6 s |
| Wall time per run | 26 s | 25 s |
| Unusable answers | 1 (retried, then fine) | 1 (retried, then fine) |

The easy scenarios took 8 calls (about 22k tokens); the hardest were `discord_like` (12–14 calls, 36–45k tokens: create, redirect, reset with confirmation) and `decide_app_type_and_scopes` (10–13 calls). The largest single prompt was 3.5k tokens. Both unusable answers came on the dropdown scenario, and the loop recorded them and asked again.

**Cost.** I have **not** converted tokens to dollars: I do not have FastRouter's prices, and assuming them would be a guess. Give me the per-million-token prices and the script prints the cost per run (`--price-in/--price-out`). Orders of magnitude: about 24k tokens per easy run.

**Limits of this measurement (stated plainly).**
- The fake site is small. Its pages are about 2.7k tokens; **a real console page will be bigger**. The prompt is capped at about 9–10k tokens per call by design, so a real run of 30 steps could use up to about 300k tokens, and the 60-step ceiling about 600k. The Discord run (phase 7) is the real measurement; this one only shows the loop works and what the floor is.
- Two runs per scenario per model is a small sample. Equal success (52 of 52) says the loop and the safeguards work with both models here; it does not rank the models.

**Model decision: unchanged, `anthropic/claude-sonnet-5.5` stays the default.** On this sample Haiku was no faster (2.1 s against 2.2 s per call), used about 6% more tokens, and had a slower worst call (8.3 s) and the longest runs (14 calls on `discord_like`). If Haiku's price per token is clearly lower it may still be cheaper per run; with prices I can say. The model is one setting (`CREDAGENT_LLM_MODEL`), so switching later is not a code change. Re-decide after the real Discord run.

**Observations.**
- The model is mostly consistent but not deterministic: the same scenario ranged 6 to 8 calls on Sonnet. In the 6-call runs it skipped optional fields (description, homepage) that it filled in the other runs. The code does not insist (only a terms handoff completes the form), which matches D-078 (guidance, not a script); the owner may want optional fields filled always, and that would be a small rule.
- Per-call latency (about 2 s) is the main cost of a run: 19 of 26 seconds. A real run with sign-in and the person's own time will be dominated by the person.
- Every guard held with a real model: one app, the terms only by the person, the reset asked first, no secret in any file, no forbidden event, 52 of 52.

**Not done:** the Discord run on the real provider (phase 7) and any price conversion.

---

## D-085 D-078 phase 7a done: the documents now say what the code does — Decided (documentation record)
**What changed.** D-078 discrepancy #5 is closed: the documents were brought in line with the agent loop, with every revised requirement marked “revised, D-078” and the earlier wording left in git history and the local tag `pre-d078`.
- **PRD** (`docs/CredAgent-PRD.md`): principle 6; F4 (browser agent loop) and F5 (step contract and code gate, replacing the Jev layer); Flow E (no re-plan); §8 rewritten (orchestrator, reasoning, hands, rules; what the model sees and cannot do; code-assigned risk; loop safeguards; the model-failure rule); the acceptance check, two risks, key decisions 1, 4, 5, 6 and open questions 1–2. **No principle about safety, terms, secrets or verification was weakened**; the hard stops, "accepting terms is always the person" and "only a passing live test is verified" are unchanged.
- **Spec** (`docs/02-ENGINEERING-SPEC.md`): architecture and sequence, technology table, layout, configuration, secret rules, plan, §6.2 (no re-plan), §6.4 (agent loop, rewritten) and §6.5 (model contract and failure behaviour, rewritten), §6.6 (risk by code), §6.8, budgets, tests, open decisions and definition of done.
- **Sprint plan**: a banner, "superseded" notes on Sprints 3 and 4, updated cut order and risk lines, and a D-078 addendum with the seven phases.
- **Attempt protocol**: three sentences (no re-plan limit; no model ever sees a secret and the snapshot never lists one; screenshots never reach a model). Protocol version stays v2: no consent or safety rule changed.
- **README**: status, the "works today" table, new sections on the approach, human involvement, verification, limitations and key decisions. **RESULTS.md**: run #5 marked as left paused (old loop; will not be resumed) and the untested line made precise. `docs/design/checkable-steps.md` carries a "superseded" banner.

**Honest gaps.** The README still says no real-provider credential has been obtained on the new loop. The PRD's own acceptance checks (four real apps, resume demonstrated on a real handoff) remain unmet and are Sprint 6 and 7 work.

**Next, and it needs the owner:** Discord run #6 on the new loop (RESULTS #6).

---

## D-086 Discord run #6: the page scan missed the ID and secret; capture fixed and made diagnosable — Decided (owner: "get this fix in place then")
**What happened (run 20261117-114142-discord-e141).** The agent created one app (the person accepted the terms), saved the redirect, and clicked Reset Secret after the person said yes. The new secret appeared, but every page scan reported **zero credential-like elements**, so code refused "done" three times without ever trying to read a value, nothing was stored, and the model, which cannot see values, tried `inspect`, the Copy button and then a **second reset**. The person declined it. Outcome: `blocked`; the secret of the first reset exists at Discord and was copied by the owner by hand. RESULTS #6.

**Correction to what I first told the owner.** I suspected a password-type field. The log refutes that: a visible password field always raises the sign-in gate, and the gates were empty on the page that showed the secret. The model also said the Client ID was visible *before* the reset, and that was not flagged either. The best-supported cause is the scan's label rule: a text field was flagged only if it was read-only or its label or its parent's text named a secret, and an all-digit ID in a field was never flagged. Discord's headings sit above the row that holds the value and a Copy button, which that rule cannot see. **This is a diagnosis from the logs and the code, not from the real page's markup**, which I did not inspect (no read-only probe was made on the owner's Discord session).

**Fixes.**
1. **Scan** (`browser/observe.py`): a token-shaped value (20+ characters of letters and digits, no spaces) in a plain text field is a credential whatever its label; the nearest heading above now counts as label context; an all-digit client or application ID in a field is flagged when its context says ID; more element types are scanned for token-shaped text (list items, labels, links, headings, and so on). **Password-type fields are still skipped unless their label names a credential**, so sign-in passwords are never treated as secrets. Approved values stay exempt (the app name looks like a token): a snapshot without the approved values, as one test made, now flags the app name, so that test passes them as the loop does.
2. **Capture** (`secrets/capture.py`): the heading above the value is read and used to name the part ("Client Secret" → `client_secret`).
3. **Diagnosis in the log:** every refused "done" is now an event (`done_rejected`) with what the page held, **structure only, never values**: element kind, input type, read-only, length, whether it was flagged. The next failure explains itself. A model reply that is not valid JSON now logs its length.
4. **Second reset:** if a secret was already reset in this run, the DECIDE says so ("resetting again invalidates that one; if you copied it, the copy stops working"), and the system prompt says to reset at most once per run and to ask the person instead.
5. **Model output limit** raised from 700 to 1,200 tokens: one answer was cut off at 700 on the real page (reasoning counts toward it).

**Reproduced first, then fixed.** New fake scenario `discord_inputs`: the OAuth2 page shows the ID and the new secret in plain text fields with the heading above, and keeps Reset Secret. With the old scan the scripted run ended asking the person (the symptom); with the fix it succeeds, stores both parts, live-tests, and leaves no secret in any file. New tests: that run, the second-reset warning (and that the second reset is not performed when declined), and `done_rejected` events. All suites pass.

**Not done / still unknown.** (a) Whether the real page matches the scenario; the next real run will say, through `done_rejected` if it fails again. (b) About 1 in 5 model answers on the real page were not valid JSON (against 1 in 52 on the fake site); each was retried and none broke the run. Cause unknown (`finish_reason=stop`); the logged length may help. (c) The first reset's secret cannot be captured by CredAgent: another reset is needed (run #7).

---

## D-087 Discord run #7: label lookup through neighbouring divs, confirmed on the real page — Decided (owner: "yes do it" for the probe, "yes fix it" for the fix)
**What run #7 showed (run 20261117-122019-discord-eb41).** The D-086 fix got further: after the secret reset the scan flagged one element, capture read it, and stored nothing ("1 unlabelled credential-like value left alone"). The agent then reset nothing more (the new rule held), asked the person, and the owner stopped it.

**Read-only probe of the live page (owner's OK; no clicks, no values printed).** On Discord's OAuth2 page the Client ID and the Client Secret are each a **disabled text field** (`type=text`, 19 digits and 32 token-like characters), with no aria-label, name, id or placeholder. The row's `<label>` ("Client ID" / "Client Secret") is in a *neighbouring div*, not linked to the field and not a heading: it is the previous sibling of the field's grandparent. So the scan's label sources (the field's own label, its parent's text, headings above, siblings, grandparent text) all missed it. That is why the ID was never flagged and the secret, flagged by its shape, had no recognised name. The 20-odd scope-checkbox labels also filled the 10 diagnostic slots, hiding the real elements.

**Fixes.**
1. **Label lookup** (`browser/observe.py`, `secrets/capture.py`): the nearest short text (60 characters or fewer, not just "Copy") among the earlier siblings of the element and its ancestors, up to six levels. It names a value for capture and counts as label context for the all-digit ID rule.
2. **Diagnostics:** `hints` now lists flagged elements and fields first, with the label found above each (structure only, never values).
3. **Capture** tries that label ahead of the broader surrounding text.

**Checked three ways.** (a) The fake scenario `discord_inputs` was rebuilt to the probed structure; with the D-086 code it reproduced run #7's failure (paused at a handoff), with the fix it succeeds. (b) New real-Chrome test of the scan and hints on that page. (c) **A dry run on the real, still-open Discord page** with the new code, printing only part names and lengths and storing nothing: both elements were flagged and named `client_id` (19 digits) and `client_secret` (32 characters). All suites pass (default and real Chrome).

**Not done.** The real capture, the live test and the stored files: that needs `credagent resume` on run #7 with the owner present, using the secret still on the open page (no second reset). Until it succeeds, nothing here is a result.

---

## D-088 Discord run #7: scope wording; the first real credential, captured and verified — Decided (owner: "make that fix and re-run the verification")
**What happened.** After the D-087 fix, `credagent resume` re-attached to the open Chrome window, the agent said "done", and capture read the Client ID and Client Secret (named by the label above each) into `~/.credagent/secrets/<run>/` (folder 0700, files 0600) with no second reset. The live test then returned HTTP 400 `invalid_scope` and the run ended `partial` (`inconclusive`, honestly labelled).

**Cause.** Discord needs a scope on a client-credentials request. This run's research wrote the test as `…&scope=identify (the docs example uses 'identify connections')`. The scope reader only understood quoted wording (`scope 'identify'`), found none, and sent the request without a scope. Checked offline from the saved plan: the parser returned `None`.

**Fix.** `verification/verify.py` also reads the form-body wording `scope=identify`, `scope=identify+connections` and `scope=identify%20email` (inferred text is still ignored). New unit test with this run's exact sentence, including that the request carries `scope=identify`.

**Result.** `credagent verify 20261117-122019-discord-eb41` made one token request to Discord with the stored credential: **HTTP 200, an access token was issued** (never stored). **The run is `succeeded` / `verified`: the first real-provider credential captured and live-tested by CredAgent on the D-078 loop.** The access token was registered with the masker and dropped.

**Leak check after the run.** The 32-character client secret appears in no run file and nowhere in the repo or the fake-site state. The 19-digit Client ID appears in the run files because it is part of page URLs (IDs are not registered as secrets, D-062).

**Honest limits.** One provider, one app, one run on the third attempt of this loop (#6 and #7's first half failed for reasons now fixed); a test account was advised and the owner remains responsible for it. The live test proves the client credentials authenticate, not that they work for a specific integration. The demo app `credagent-demo-20261117` still exists at Discord (the agent never deletes); the owner removes it. PRD acceptance still needs more real apps, including a blocked one and a partial or waiting one.

---

## D-089 Web UI for CredAgent: a local page and JSON API over the unchanged orchestrator — Decided (owner approved 2026-11-17)
**Request.** A clean, minimal frontend: enter any app name, follow real progress, be told when your attention is needed, resume, and see the result with credentials masked.

**Inspection.** The repo had no frontend, no HTTP API and no Node toolchain: the CLI was the only interface. The orchestrator already talks to the person through a small `IO` object (`say`, `choose`, `wait_enter`, awaitable-friendly) and run state is complete on disk (`run.json`, `events.jsonl`). So the page needed a second IO implementation and a read-only view of existing state, not a change to the backend. The proposal is `docs/design/web-ui.md`.

**Owner decisions (asked first, as the brief says).** (1) A local API in this repo using only the Python standard library; (2) vanilla ES modules, no build step, no Node; (3) the header says **CredAgent** (the brief's "Access Agent" was not used); (4) **ATTEMPT-PROTOCOL amended** so the terminal confirmations (consent, DO "I did it", DECIDE answers) may be given in the page with the same checks; the protocol version stays v2 and carries a dated amendment.

**Built (new code only; `cli/main.py` gains one `ui` command).**
- `src/credagent/web/`: `server.py` (standard-library HTTP, static files, strict security checks), `controller.py` (one worker thread per active run: research and plan, terms check, consent, the browser agent; resume; verify; reveal), `webio.py` (blocks in a thread, awaitable in the event loop), `views.py` (pure functions: run and events to what the page shows), `static/` (HTML, one CSS file, ES-module components with all `fetch` calls in `api.js`).
- API: `GET /api/config`, `GET/POST /api/runs`, `GET /api/runs/<id>` and `/events?after=`, `POST …/consent`, `…/answer`, `…/continue`, `…/stop`, `…/resume`, `…/verify`, `…/browser/focus`, `…/secrets/<part>/reveal`.
- Page: landing (any name, suggestions fill the input, collapsed Advanced for the local test site), consent screen, running view with milestones and the latest activity, "Your attention is needed" (do or decide), result (masked credentials, Reveal, Copy, verification method and status, time), failure (recoverable, needs you, waiting, unrecoverable), paused (Resume), a collapsed activity log.
- **Milestones are real facts** (identified, portal, credential type, go-ahead, browser opened, application registered, captured, verified); no percentage anywhere. Terminal wording in backend texts ("press Enter", "this terminal") is rewritten for the page; facts are never changed.

**Security.** Binds 127.0.0.1; `Host` must match (DNS rebinding); a one-time launch token becomes an HttpOnly SameSite=Strict cookie; API calls need the cookie and a custom header; `Origin`, if sent, must match; no CORS; `no-store`, a strict CSP, no inline styles, no `innerHTML` anywhere; no access log; unexpected errors return a generic message. A secret is returned only by `reveal` on an explicit click, is held in memory by one component, hidden after 30 seconds and when the tab is hidden, never stored (checked: `localStorage` and `sessionStorage` empty), never in a URL, a log line, an event or the view. The attacker model is another page or process on the same machine, not someone with the owner's account.

**Tests (all pass).** `test_web_views` (every state, masked-only, no secret), `test_web_server` (cookie and header, Host and Origin refusals, path traversal, bad bodies, reveal needs confirm), `test_web_io`; real Chrome against the fake provider and the offline stand-in: `test_web_api` (completion, reveal, a DO handoff, a DECIDE choice, stop and resume without a second app, a recoverable failure, refresh recovery) and `test_web_ui_browser` (the page itself: whole journey with refresh mid-run, reveal, hide and copy, a radio choice, stop and resume, a failure, a 375 px screen with no horizontal overflow, and the "open the link" screen). Screenshots of each state were reviewed; three defects found and fixed (a literal "null" under each credential, stretched status badges, an unhelpful "done so far" text).

**Not done or not verified.** A real-provider run through the page; the consent screen against a live provider; Safari and Firefox; granted scopes (the backend does not record them); live detail during research (the backend logs it only afterwards). Listed with reasons in `docs/design/web-ui.md` section 9.

---

## D-090 Web UI simplified: Advanced and Recent removed from the landing page — Decided (owner, after a real Discord run through the page went well)
**Change.** The landing page is now one application-name input, one button and the suggestion chips. The collapsed Advanced section (test-site mode, scenario, offline stand-in) and the Recent list are gone from the page, along with their state, styles and the unused `listRuns` call.

**What stays.** The API still starts local test-site runs (`POST /api/runs` with `mode: "fake"`) and lists runs, so scripts, the CLI and the tests are unaffected. A run is still recovered after a refresh because its id is in the address (`#/run/<id>`).

**Trade-off, stated plainly.** Without Recent, a new tab at `/` shows an empty landing page even when a run is waiting for you; reopen it from its address or with `credagent runs` / `credagent resume`. If that proves annoying, a single "a run is waiting for you" line would be a smaller fix than the old list.

**Tests.** The page tests now start test-site runs through the API and follow them in the page, and the landing test asserts that no `details`, `select` or Recent list exists and that starting is refused up front, with the reason shown, when the research keys are missing.

---

## D-091 The terms check no longer blocks an unfamiliar app — Decided (owner, 2026-11-17)
**Owner instruction.** "Terms check for automated console checks needs to be skipped. Any unfamiliar app given as input has to start with the process we have. Remove that as a blocker."

**What happened that prompted it.** A Google Cloud run through the page researched and planned, then stopped: Google had no recorded terms check (only Discord and Spotify do) and ATTEMPT-PROTOCOL §2.3 said an unchecked provider is never automated.

**Change.** `consent/terms.py` gains `terms_for()`, which never returns None: a provider without a recorded check gets an explicit **"unchecked"** finding that may be automated, exactly like "unclear" (D-059). The CLI and the web page both use it, so GitHub, Linear, Google Cloud and any other app now reach the consent screen. Consent is unchanged and still asked every session, in your own words, with an explicit confirm; the screen now says "Not checked. No check of this provider's terms on automated console use has been recorded. Automating a console can go against a provider's terms and can lead to the account being restricted. A dedicated test account is strongly advised. Unchecked providers are automated too (your decision, D-091). You remain responsible for activity on your account." The run records `terms_finding: "unchecked"` in its consent entry. ATTEMPT-PROTOCOL §2.3 and its amendment note were updated; the protocol stays v2.

**Kept on purpose.** A recorded **prohibited** finding still blocks (none exists today; both recorded findings are "unclear"). If you want that gone too, it is a one-line change, but a recorded prohibition is a fact the owner wrote down.

**Risk stated plainly.** Automating a console without reading its terms can breach them and put the account at risk (Google, for example, often blocks sign-in in automated Chrome). That is now the owner's call per run, which is what the consent screen says.

**Tests.** The old "unchecked provider never opens the browser" test now asserts the opposite for the consent screen and that no browser opens without consent; new test that `terms_for` never returns None and that only a recorded prohibition blocks.

---

## D-092 Weak research no longer leaves a plan that cannot start — Decided (owner: "make these fixes then")
**Why.** A Google Cloud run through the page ended with no official domains, no console URL and no pages read, yet the plan was "ready" and predicted "succeeded". The model's first call (the triage) had returned an empty answer; nothing downstream could recover, and the browser would have had no start page. A fresh research run found everything (domains, console URL), so the failure was a weak model answer, not Google. The raw answer was not logged.

**1. Retry once.** If research ends with no allowed domains or no console URL, it runs once more, telling the model what the first attempt lacked ("name the official domains and choose the pages to read" / "look for the exact console URL"). The better result wins (a tie goes to the retry). A retry that fails, runs out of budget or is no better never replaces the first result and never fails the run. Cost: a second research pass, about $0.15–0.20, only when needed.

**2. Name-based domain fallback.** If the retry still names no official domain, the allowed domains are inferred from the **retrieved hosts only**: the registrable domain of a host whose name is one of the words of the app or provider name (`docs.cloud.google.com` → `google.com` for "Google Cloud" / "Google"). Generic words (cloud, api, docs, console …) never count, third-party and look-alike hosts never match, and nothing is invented. The result is marked: `Plan.domains_inferred`, a plan note, and a line on the go-ahead screen and in the CLI ("inferred from the app name, not named by research: …, check that they are right"). The allowed domains are a safety boundary, so ATTEMPT-PROTOCOL §9 now says where they can come from.

**3. No dead-end plan.** If there is still no console URL, the run does not stop and does not pretend: the CLI prompts for it and the page shows "Where is the developer console?" with a field. The address is accepted only if it is a plain `https://` address with a domain name (no IP number, no user name or password, no spaces, at most 300 characters); its host is added to the allowed domains for that run and recorded in the plan notes and the run log (`console_url_given`). Pressing Enter / "Not now" stops with the run saved. This comes before the go-ahead, so nothing happens at the provider until the owner consents.

**4. Logging.** The run log now records what the model returned, no content: `triage_result` (official domains as the model gave them, which were kept, which were inferred, the pages it asked to read and how many were read), `synthesis_result` (console URL and its source, sign-in domains, credential kind), `plan_result` (the final console URL and allowed domains) and `research_retry` (why, and what was still missing), each with its attempt number. The next failure explains itself.

**Tests.** Research: a weak first answer is retried once and the better result wins; no retry when the first attempt is complete; still weak after the retry infers marked domains and never a third party; a failed retry keeps the first result; the facts are logged (and reach the run log); inference is conservative (generic words, look-alikes, two-part suffixes). Console address: validation rules, the CLI prompt (invalid, then valid, then consent still required; no address means no browser), the API (a plan without a console shows the prompt, refuses bad addresses, delivers a good one to the waiting run) and the page itself. One existing test that hit a hostile console URL now expects the retry. All suites pass.

**Not done.** A live research run after the change (the probe before it cost about $0.20 and used the old code); the model may still return weak answers, the point is that the system now recovers. The inference matches only the app or provider name, so a provider whose own domain does not contain its name (a product hosted under a parent brand) still needs the console address from the owner.

---

## D-093 Google Cloud run: an off-site sign-in redirect is the person's, not a bounce back to a blank page — Decided (fix after reading the run's log)
**What happened (run 20261117-145242-google-cloud-4910).** The D-092 research fixes worked: research found the console URL and the official domains on its first attempt (no retry needed) and the go-ahead screen showed "Not checked" for the terms. The browser then opened the console URL and Google redirected it to `accounts.google.com`, which was **not** on the allowed domains (the model's official domains were `cloud.google.com`, `developers.google.com` and so on, not `google.com`, so the sign-in domain it also named was left out, as designed: "navigating there will be handed to the person"). The loop's off-site rule was to go back; going back from a redirect lands on `about:blank`, which counts as allowed, so no handoff happened. The model navigated to the console again, was redirected again, three times, then asked the person to sign in on a blank page. The person never reached Google's sign-in page.

**Fix (`agent/loop.py`).** On an off-site page that **looks like a sign-in page** (its address says sign-in, login, /auth/ or starts with `accounts.`, or it has an email or password field), or when there is **no earlier allowed page** to go back to, the agent no longer goes back: it hands the page to the person as a `sign_in` DO ("The provider sent the browser to its sign-in page (accounts.google.com), which is outside the allowed sites. The agent does not act there; you sign in, then you are sent back to the console"). The domain guard is lifted for the person as for any DO, and the agent re-checks the page afterwards. Any other off-site page keeps the old behaviour (go back, then the person if that fails).

**Test.** New fake scenario `signin_offsite`: the console redirects to a sign-in page on another host (`localhost`, outside the allowed `127.0.0.1`) and a one-time ticket carries the session back, as Google does. Without the fix the run reproduces the Google symptom (paused at a handoff after bouncing); with it the run hands the sign-in to the person once, makes no "going back" step, signs in, creates exactly one app and verifies.

**Not done / still unknown.** Whether Google lets the person sign in inside the agent's Chrome at all: Google often refuses sign-in in an automated browser ("This browser or app may not be secure"). That is a provider limit and is not something this fix can change; the next real attempt will show.

---

## D-094 Google Cloud run #3: project vs app, a credentials dialog taken for a cookie banner, "Add secret", a window-less Chrome — Decided (owner: "make the fixes and run the probe")
**What the run showed (20261117-152213-google-cloud-6458).** After the D-093 fix the sign-in worked and the agent got much further: it asked about a project, filled the project form, set up Google Auth Platform and reached the OAuth client page. Four things went wrong, all read from the log:
1. **"Can't create a new app again."** The code counted the "Create project" click as *the* app (any "Create …" matched), so "Create client" was refused as "would create another app (D-063)" and the person had to click it. Google needs a project, then a consent screen, then the client.
2. **The credentials dialog was a "cookie banner".** The "OAuth client created" dialog mentions the OAuth *consent* screen; the cookie rule matched the bare word "consent", so the person was asked to "choose your cookie preference" with the credentials on screen.
3. **"Add secret" was clicked unasked.** To get a secret the agent opened the client page and clicked "Add secret", which creates an extra client secret at Google; policy called it reversible. (There may now be two secrets on that client: check it.)
4. **The secret was not recognised** in the creation dialog: the scan flagged one 20-character value in a table cell (not the secret) and nothing was captured; only the Client ID was.

**Fixes.**
- **One app means one credential resource.** A creation is `setup` (project, workspace, organisation, team, folder, tenant) or `credential` (app, client, integration, API key); a bare "Create" is judged by its page (title, headings, address). A setup creation is **asked** (the person says yes) and recorded in the new `Run.created_setup`; it never counts as the app, and a project is never refused as "another app". A second *credential* creation is still refused (D-063). The consent screen and the CLI say a project or workspace may be needed first and is asked separately; the system prompt says so too. New fake scenario `project_then_app` and a test: the person is asked about the project once, then the agent still creates the one app itself.
- **Cookie banners.** A banner is about cookies only if its text says cookie, tracking or privacy choices, or says "consent" **and** a dialog button says accept/reject/decline. A dialog that mentions a client ID, a secret, an API key or a token, or any dialog while a credential is on screen, is never a banner. Real banners still behave as before.
- **"Add/create/generate a (client) secret"** now asks the person, like "Reset Secret".
- **A saved Chrome that cannot be driven** (found while trying to probe): the run's Chrome was alive but had **no window** (the window had been closed; on macOS Chrome keeps running), and DevTools then refuses to be driven ("Browser context management is not supported"). `credagent resume` would have failed. Now the stale Chrome is quit (which releases the profile) and a fresh one is opened on the same profile; sign-ins live in the profile. Test: a forced attach failure ends with a new Chrome and the old process gone.
- **Diagnostics for the unrecognised secret.** `done_rejected` now also records, as structure only, any bullet-masked values (`masked`) and, for each dialog, how many leaves, inputs, token-like and masked values it has and its button names.

**The probe could not be run.** The Chrome had no window, so there was no Google page to look at (and it could not be attached to at all, see above). The fix for the unrecognised secret therefore **waits for evidence**: the next real attempt will record the dialog's structure in `done_rejected`. If the secret is only shown masked, or shown once in a form the scan cannot read, that will say so.

**Not done / unknown.** Whether Google shows the secret in the creation dialog in a readable form at all (recent Google changes hide client secrets after creation). Whether Google lets automated Chrome stay signed in over a longer run. The owner should check the Google client for an extra secret created by "Add secret".

---

## D-095 Why the browser did not open: a window-less Chrome from the closed window held the profile — Decided (fix after reading the logs)
**What happened.** Google runs after D-094: run 3b22's browser opened (event `browser_opened`), then the window was closed and the run **paused**. On macOS, closing the last window leaves Chrome running without one, and it keeps the profile locked. The next runs (e46c, c5b0) launched a new Chrome on the same profile: it found the profile taken, handed over and exited with code 0, and CredAgent reported "Chrome could not start with the profile … (exit code 0). Usually another Chrome window is still using it". No `browser_opened` event, no window. The stale process (pid 50248) had no pages and no browser contexts, which I confirmed with a read-only DevTools query. A fresh launch on the same profile works (checked three times, including connecting straight away), so the profile and the launch code are not at fault.

**Fix.** Before a new Chrome is launched on a profile, `release_stale_chrome` looks at who holds it (the profile's `SingletonLock` names the pid): if it is a CredAgent-started Chrome (our `--user-data-dir` and a debugging port) with **no page**, it is quit gracefully (which flushes and releases the profile) and the launch goes ahead. A Chrome that still has a window is somebody's open session and is **left alone**, so that case still fails with the old message. The same release runs in the re-attach fallback added in D-094.

**Test (real Chrome).** A window is closed (headless: its last page), Chrome stays alive with the lock held; the next `open_pw_session` quits it and opens a fresh Chrome; a Chrome with a window is not released; a launch on a held profile still fails as a control.

**What the person sees.** Nothing extra: closing the agent's window mid-run now only pauses the run, and starting or resuming a run opens a new window. The Google profile and its sign-ins were never touched by the diagnosis (I quit the stuck Chrome, which flushes the profile, and launched and closed test windows on it).

**Not fixed / unknown.** The page records only the *latest* controller's error for a run: the first attempt's error was overwritten when Resume started a second controller, so I had to infer the first failure from the process state. Worth keeping the error history if it matters again.

---

## D-096 Choosing a credential type other than the recommended one now re-plans for it — Decided (owner reported: chose OAuth, the next screen showed an API key)
**What happened (run 20261117-164320-google-cloud-955e).** Research recommended an **API key**; the person chose **OAuth client** from the list. The run's plan stayed the API-key plan: `credential_kind` api_key, the API-key console steps and live test, and a go-ahead screen that said "Credential: api key". The code only wrote a note ("the browser steps must be re-planned for it") into the plan's unknowns and never re-planned. Earlier Discord runs never hit this because OAuth was the recommended option.

**Fix.** After a non-recommended choice, research runs again **for the chosen type** (`ResearchAgent.research(..., want_kind=…)`): the triage is told which type to find pages for, the synthesis is told to plan only that credential, and the person's choice overrides the model's (`chosen_credential_kind` is forced to it if the model answers otherwise). The new plan replaces the old one, the run records a step ("re-planned for the chosen credential type") and an event (`replanned`), and the go-ahead screen, console URL, steps and live test are those of the chosen type. Cost: one more research pass, about $0.15–0.20, only when you choose a non-recommended type; the weak-answer retry (D-092) still applies inside it. If the re-plan fails or comes back as another type, the run keeps the old plan and says so plainly in the plan's unknowns ("the plan could not be redone for it, so the browser steps may not fit"). Resuming a run whose credential-type question was left open now also has a research agent (CLI and page), so the re-plan works there too.

**Tests.** Choosing the OAuth client re-plans (second pass asked for exactly that type, plan, step and event recorded); choosing the recommended type does not research again; the person's choice wins over a model that answers another type; a failed re-plan keeps the run and says the steps may not fit.

**The obsolete run.** 955e is saved with the wrong plan; start a new run.

---

## D-097 Google run 6338 looped: the agent could not see Google's custom "Application type" dropdown — Decided (fix after reading the log and a read-only probe)
**What happened.** With D-096 the OAuth choice was applied (`credential_kind` oauth_client), the sign-in, a project (two setup creations, asked) and Google Auth Platform setup all went through, and the agent reached "Create OAuth client ID". There it looped for 48 steps (wait, reload, navigate, a detour to the classic Credentials page and back), each reload showing "only the side navigation", until I stopped it at about step 56 to save tokens.

**Cause (read-only probe of the open page, structure only).** The "Application type" control is a Google **`cfc-select` element with `role="combobox"`**, its label ("Application type") a neighbouring element, and the Name field only appears after a choice. The page snapshot lists only a fixed set of interactive elements (links, buttons, inputs, selects, ARIA roles button/link/tab/menuitem/checkbox/switch/radio), so the combobox was **not listed**: the agent saw the label and no control ("shows the 'Application type' label but no dropdown"), concluded the page had not rendered, and waited and reloaded. Nothing in the loop stopped waiting and reloading, because every reload changed the page slightly, so the no-change rule never fired.

**Fixes.**
- **Custom dropdowns are listed.** The snapshot now also lists `combobox`, `option`, `textbox`, `searchbox`, `menuitemradio`, `menuitemcheckbox` and `spinbutton` elements. A custom combobox is named by its aria-label, its `aria-labelledby` target or the nearest label above it (the D-087 lookup); an option by its text.
- **The choice is the person's.** Clicking an *option* is a DECIDE ("Choosing 'Web application' (e.g. an app type) is the person's decision"), like a native dropdown; opening the combobox is allowed. This matches the consent screen ("any app-type choice is asked here").
- **Waiting and reloading are not progress.** More than three `wait` actions in a row, or loading the same address a third time in a run, is turned away with a reason (counted as an unusable answer), and six in a row ask the person. A run can no longer spend its whole step budget (and tokens) on this.

**Tests.** New fake scenario `custom_dropdown` (a combobox with a neighbouring label, option items, the rest of the form hidden until a choice, as on Google): without the snapshot fix the run pauses at a handoff exactly as Google's did; with it the person is asked about the item once and the app is created with that type. Unit test for the roles, the names and the DECIDE; a test that an agent that only waits, or only reloads, ends within 14 model calls with the person asked.

**Not done / unknown.** Whether the rest of Google's form uses other custom controls (the Name field and "Authorized redirect URIs" appear after the choice; the first real attempt will show). The classic Credentials page was never needed. The probe showed `cfc-overlay`, `cfc-panel` and `cfc-menu` elements: popups may be rendered in overlays, which the scan reads like any other element.


---

## D-098 Slack and Google runs: the console was dropped from the plan, then bounced and looped — Decided (fix after reading runs 2f3c, fa73)

**What the logs showed.** (1) Slack run `20261117-185330-slack-2f3c`: research twice answered `console_url: https://api.slack.com/apps`, but the plan had `console_url: null` and `allowed_domains: [docs.slack.dev]`. A domain the model names is kept only if some retrieved page is on it, and only `docs.slack.dev` was read, so `api.slack.com` and `slack.com` were dropped and the console URL (which must be on a kept domain) with them. The owner then typed the console address, which added `api.slack.com` only. After the app was created, Slack redirects `api.slack.com/apps/<id>/general` to `app.slack.com/app-settings/…`: not allowed, so the agent went back, tried about eight settings paths, every one bounced, "Basic Information" was refused as off-list, and the agent gave up. (2) Google run `…174135-google-cloud-fa73`: the plan lacked `console.cloud.google.com`, the owner signed in, and the console page (address contains `/auth/clients`) was read as a sign-in page, so "sign in" was asked seven times in a minute. (3) Slack: the model's reply was not valid JSON 12 times (450–720 chars, finish_reason stop), each costing 10–20 s. The reply was never logged, so the cause is not known.

**Decision (code).**
- A domain the model named as official, with no retrieved page on it, is kept when its registrable domain's name is the app's or the provider's (`slack.com` for "Slack"); it is marked inferred and shown at the go-ahead screen. A different name (`acme-partner.example` for "Acme") is still dropped.
- A console address the owner types also opens the provider's own domain, on the same name rule, and never a shared host (`something.vercel.app`). It is recorded in the plan's notes and `domains_inferred`.
- "Looks like a sign-in page" no longer counts `/auth/` in the path (Google's console is at `/auth/clients`); the host (`accounts.*`), `signin`/`login` in the address, or a password/e-mail field still do.
- The same off-site sign-in page asked about three times with no change stops the run (`stuck`, saved, resumable) and says what it sees, instead of asking again.
- A reply with words around one JSON object (or a code fence) is parsed as that object; the schema check still decides. A reply that still fails now reports how it begins and ends and where it broke (masked), so the next occurrence is explained.

**Tests.** `test_a_domain_the_model_named_…` (research), `test_an_owner_given_console_also_allows_the_providers_own_domain_…`, `test_a_reply_with_words_around_the_object…`, `test_an_unparseable_reply_says_how_it_begins…`, `test_google_consoles_auth_path_is_not_a_sign_in_page…`, and the real-browser `test_the_same_off_site_sign_in_page_three_times…`.

**Addendum (Slack run `20261117-194737-slack-4bc5`, same day).** The D-098 domain fix worked: the run reached `app.slack.com/app-settings/…/general`. There the hard check raised a `sign_in` handoff, evidence "password field: Client Secret": any password-type input counted as a sign-in form, and Slack shows the client secret as a password input with a Show button. "I did it" could not clear it. Now a password-type input whose label, name or id names a secret/token/key/credential/signing secret is not a sign-in field (`policy/hard_checks.py`, `SECRET_FIELD`), unless its autocomplete says `current-password`/`new-password`; a page that also has a real "Password" field is still a sign-in page. This matches the snapshot's rule (D-086), which already treats such a field as a credential for capture. Test: `test_a_secret_shown_in_a_password_input_is_not_a_sign_in_page_…`.

**Not done / unknown.** Why the model's JSON failed 12 times (the new message will show). Slack's text addressed to agents on the apps page was ignored by the agent, but its exact words were never saved, so whether it is hostile is unknown (the page flag `isAgentHandoffLandingEnabled` suggests a Slack feature for coding agents). The Slack app `credagent-demo-20261117` (A0CJN1KTBKK) exists in the owner's workspace and the owner should delete it. Not yet tried against real Google or Slack again.

---

## Discrepancies between documents
1. Docs location (see D-001).
2. Spec §3 lists `docs/04-CLAUDE-CODE-STARTER-PROMPT.md`, which was not provided.
3. Spec §5 `CredentialReference.storeRef` (single) vs. OAuth's two values → `parts` (D-023).
4. PRD §10 does not classify a captured-but-`invalid` credential → `failed` (D-022).
5. ~~PRD F4/F5/§8/§14 and spec §6.4/§6.5 (Stagehand, Jev) are superseded by D-078~~ **Resolved in D-085**: the documents were updated and carry “revised, D-078” markers.

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
