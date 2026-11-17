# Design: checkable steps (code-proven progress)

Status: **approved by the owner** (2026-11-17), with the recommended answers to §13. Work starts with §11a.
Decision record: `docs/DECISIONS.md` D-073.

## 1. Why

The Discord runs (`RESULTS.md` #2–#4) needed twelve fixes (D-061 to D-072). Almost all of them come from three gaps in the
current browser loop:

| Gap | What happened on Discord | Fixes it caused |
|---|---|---|
| **A. Steps can't be checked.** A step is one English sentence. Jev decides from that sentence whether it is done. | "Open the OAuth2 page" was marked done on a **docs** page. A redirect with a stray full stop looked done. A credential-like ID on the app list was taken for the credential. | D-061, D-070, D-071 |
| **B. The plan position is a counter that code keeps correcting.** | The counter didn't move after the app was created (three apps were created). It jumped past OAuth2, redirect and Reset Secret. It landed on "Capture". Re-plans scattered live-test steps mid-plan. | D-063, D-064, D-065, D-067, D-068 |
| **C. Each decision is made in isolation.** Jev sees one sentence, page text and 20 elements. It doesn't know where things live, what is done, or what comes next. | It said "stuck" when OAuth2 was one click away. The target was not in the 20 elements. It clicked "Add Another" 14 times, bounced between pages, and never clicked Save. | D-066, D-068, D-069, D-072 |

Each fix was right, but each one patched a symptom. This design removes the causes.

## 2. Goals and non-goals

**Goals**
1. Every browser step has a **done-when** that plain code checks against the live page. A step is done only when its check passes. Each pass is recorded as proof (the check, the URL, the time).
2. The plan position is **computed** from the proofs and the page, never adjusted by hand. Resume and "the person already did it" fall out naturally.
3. Each Jev request carries what Jev lacks: **progress, where the step happens, its target, the next steps, and recent actions with their effect.**

**Non-goals and unchanged rules**
- **Jev keeps exactly its five closed decisions** (PRD §8). The LLM still does research, re-planning, fallbacks and navigation questions. Code still owns policy, secrets, verification and state.
- **No safety rule is relaxed:**
  - policy order, DO/DECIDE, terms are always the person's, one app per run (D-063), no docs detours (D-070), the repeat guard (D-069);
  - secrets are never read by models;
  - no provider facts are invented.
- **No provider-specific code.** Conditions come from research, in a closed vocabulary that code validates.

## 3. Overview

```
research (LLM) ──► plan: steps with  where · target · done_when   (closed vocabulary)
                         │
code validator ──────────┘ rejects unknown checks, off-domain URLs, unchecked agent steps

browser loop, every observation:
  observe (plain code) ─► hard checks (code) ─► EVALUATE CHECKS (code)
        │                                          │
        │            step status: done (proof) / not done (which check failed) / not here
        │                                          │
        │            position = first step not proven done
        ▼                                          ▼
  if the current step's WHERE is false ─► go there (code: known link or URL) or ask the navigator
  else ─► build Jev request (progress, failing checks, target first, next steps, recent actions)
          ─► Jev five decisions ─► fallbacks ─► POLICY (code) ─► act ─► observe ─► EVALUATE ─► proof
```

## 4. Step format

```jsonc
{
  "id": "s4",
  "kind": "fill",                                   // navigate | click | fill | handoff | capture | verify | check
  "intent": "Add the callback URL under Redirects and save the changes.",
  "where":  [{"check": "at_page", "path": "/developers/applications/{app_id}/oauth2"}],
  "target": {"role": "button", "name": "Add Redirect"},       // optional: what to act on first
  "value":  "redirect_uri",                                   // fill steps: which code-approved value
  "done_when": [
    {"check": "field_holds", "field": {"section": "Redirects"}, "value": "redirect_uri"},
    {"check": "element_absent", "role": "button", "name": "Save Changes"}
  ],
  "source_url": "https://docs.discord.com/developers/topics/oauth2"   // where research learned it (or null)
}
```

- **`intent`** is the sentence used today. It is still shown to Jev and to the person.
- **`where`** says which page the step happens on, as checks. An empty list means any page.
- **`target`** names the control the step starts with. It is ranked first when present (§7).
- **`done_when`** lists checks that **all** must hold for the step to count as done.
- **Placeholders:** only `{app_id}` and `{base}` are allowed. `{app_id}` is bound by code from the first URL that matches a pattern containing it after the app was created, or from the captured client ID when they are equal (as on Discord).

## 5. The check vocabulary (closed, evaluated by plain code)

| Check | Parameters | How code evaluates it (no model) | Notes |
|---|---|---|---|
| `at_page` | `path` (glob with placeholders), optional `host` | URL host on the allowed domains; path matches | A docs host never matches a console `where` (D-070) |
| `element_present` | `role` (button/link/field/heading/dialog/checkbox), `name`, `match`: exact or contains | Search the plain-code observation | Names are compared after whitespace normalisation |
| `element_absent` | same | Negation | e.g. the create dialog closed, "Save Changes" bar gone |
| `field_holds` | `field` (label / aria label / section heading), `value` (approved value key) | **In-page equality test**: the page compares the field's value with the approved value and returns only true/false | Only for code-approved non-secret values (app name, homepage, callback, description). Code refuses it on password, secret, code or human-only fields. No value is read out. |
| `field_empty` | `field` | `value_len == 0` | |
| `checked` | `field` | Checkbox state | Never used on terms controls (terms stay the person's) |
| `app_exists` | none | `run.created` is non-empty, **and** the page shows the run's app name or its ID in the URL | Proves the create step (D-063) |
| `credential_shown` | `parts` (e.g. client_id, client_secret) | The existing plain-code capture finds those labelled parts | Code-owned; replaces "a credential-like value is on the page" (D-061) |

New checks are added only in code, with tests. The LLM can only use the names above.

## 6. Step status and plan position

For every step, code keeps one of:
- **done**, with proof (check results, URL, time). Proofs are written to run state and events.
- **not done**, with the check that failed (e.g. `field_holds Redirects ≠ callback`).
- **not here**: the step's `where` is false on this page, so its `done_when` can't be judged.

Rules:
1. After every observation, code evaluates the current step, and also every later step whose `where` holds on this page. A later step proven done is skipped with its proof, which covers things the person did by hand or done earlier.
2. **The position is the first step that is not proven done.** Nothing else moves it. The cursor corrections from D-063/D-064/D-065/D-067/D-068 are deleted.
3. **Once proven, a step stays done.** It is re-checked only when its `where` holds again; if its check then fails (e.g. the redirect was removed), it goes back to *not done*.
4. Jev's `step_complete` answer becomes a **hint**. If code's check disagrees, the step is not done, and the next request says why.
5. **Steps without a checkable condition:**
   - **handoff** (person) steps may lack a condition. They complete when the person presses Enter and the hard checks no longer show the blocker, as today.
   - **Agent** steps without a checkable `done_when` are rejected by the validator. If research cannot express one, the step is kept as *inferred*: completion falls back to Jev's judgement, and the report says so.
6. **Resume:** proofs are loaded from run state, and the page is re-observed. The position is recomputed under rule 2, so no counter needs repairing. The in-doubt click rule (D-056) still applies.

## 7. What Jev and the navigator receive

`PageState.step_goal` becomes a structured block (still under 6,000 characters):

```
Current step (4 of 7): Add the callback URL under Redirects and save the changes.
Done when: [✗] Redirects box holds the callback   [✓] no unsaved "Save Changes" bar
Already done: open portal ✓ · app created ✓ (proof: app page /applications/<id>/information) · OAuth2 open ✓
Next: click "Reset Secret" (needs your DECIDE) · capture · live test
Recent actions: clicked "Add Redirect" → a Redirects box appeared (empty)
```

- **Target first:** if the step's `target` is on the page, it is candidate `c0`. The other candidates are ranked as now (D-066/D-072) and capped at `MAX_CANDIDATES`. That is 20 today, an unmeasured Sprint 3 default; the measurement in §11a sets the final value.
- **Location:** if the current step's `where` is false, code first tries the **known way there**. That is a link whose href matches the `where` path (remembered from any earlier page in this run, e.g. the sidebar's OAuth2 link), or the path itself when the placeholders are bound. Only if neither exists does the navigator choose (D-068).
- **Recent actions** (last 3) state their observed effect, e.g. "no change". The repeat guard (D-069) stays as a backstop.
- The navigator gets the same block.

## 8. Research and re-planning

- **Research schema:** `setup_steps` items gain `where`, `target`, `value` and `done_when`, using the §5 vocabulary.
- **Prompt:** describe each step's page and how to tell it is done, using only these checks.
- **Validator:**
  - unknown checks, unknown placeholders, and paths on hosts outside the allowed domains are rejected;
  - `field_holds` is allowed only on approved value keys;
  - capture and verify steps get code-owned conditions (`credential_shown`; the live-test result);
  - the create step must end with `app_exists`.
- **Re-plan:** uses the same schema and validator. Proven steps keep their proofs and are never rewritten.
- **Old plans** (no conditions) run in **legacy mode**, today's behaviour, with a warning in the report. `fake_provider/fixtures/plan.json` gets conditions.

## 9. What gets simpler, what stays

**Removed (replaced by proofs):**
- plan-cursor corrections on resume (D-064, D-065, D-067, D-068 correction parts);
- `_mark_created` moving the cursor (D-063/D-067);
- "a filled field means the step is done" (D-044), replaced by `field_holds`;
- the save heuristics of D-069/D-071, replaced by `done_when` with `element_absent` "Save Changes";
- the length comparison of D-071, replaced by `field_holds` equality. The DECIDE "replace the different value?" stays.

**Kept as backstops:** one app per run (D-063), the duplicate-app DECIDE on uncertain resume, docs detour (D-070), repeat guard (D-069), navigator (D-068), ranking (D-066/D-072), page memory (D-070), and policy and terms (D-069 named-button rule).

## 10. Safety review

- `field_holds` runs a fixed in-page comparison against code-approved, non-secret values. It returns a boolean and is refused on password, secret, code or human-only fields. Nothing a model wrote is executed in the page.
- Conditions are data, not code. The validator allows only the closed vocabulary. URLs in `where` must be on the allowed domains, and code navigates only to those.
- Navigation by known link or path is read-only and still passes policy (allow-list, docs rule).
- No change to who may do what: DO and DECIDE categories, hard stops, terms, consent and secret handling are untouched.

## 11. Testing plan

1. **Unit:** each check (positive, negative, wrong page). Placeholder binding. The validator, including rejection cases. Position rules 1–6, including resume and "the person did it".
2. **Fake provider:**
   - add conditions to `plan.json`;
   - run the `discord_like` scenario end to end offline (RuleJev) and once online;
   - one regression test per Discord failure (below).
3. **Regression map:**

| Failure | Test |
|---|---|
| D-061 unlabelled ID taken for the credential | `credential_shown` false → continue |
| D-063 three apps | the create step proven by `app_exists`; position never returns to it |
| D-064/D-065/D-067 position jumps | position computed from proofs; no step skipped without proof |
| D-066/D-072 target not offered | `target` is `c0` |
| D-068/D-070 stuck one click away / docs | `where` false → known link used; docs never match |
| D-069 Add Another ×14, Save never clicked | `done_when` fails until saved; recent actions show "no change" |
| D-071 stray full stop | `field_holds` false → DECIDE replace |

4. **Then one real Discord run** (owner present), recorded in `RESULTS.md` as #5.

## 11a. Measurement: how many elements Jev should see

**Why:** `MAX_CANDIDATES = 20` (`src/credagent/browser/candidates.py`) was chosen in Sprint 3 as a size limit and never measured. Twice on Discord the right element was beyond the 20 (D-066, D-072). Jev's request format allows 60, and its context is 64k tokens. So the limit should come from data.

**Method (fake provider only, no real provider contacted):**
- **Pages:** crowded pages that copy real layouts. The `discord_like` app page (9 fields and 11 buttons before the sidebar), its OAuth2 page (32 inputs, about 20 scope checkboxes), and the app list with the run's app among other apps. Plus three ordinary fake pages as a control.
- **Cases:** for each page, 2–3 steps with a known correct element (e.g. "open the OAuth2 page" → link `OAuth2`). Some steps quote the target name, some don't.
- **Variants:**
  - limit **20 / 40 / 60**;
  - ranked, with and without "target first";
  - the target placed at the *end* of the list, as a worst case.
- **Repeats:** 5 Jev calls per case and variant (about 150–250 calls in all).

**What is recorded per call:** whether Jev chose the correct element, whether it said "none" while the element was in the list, its confidence, latency, request size in characters, and the served Jev version.

**How the limit is chosen:** the smallest limit that both
- reaches at least 95 % correct when the target is in the list, and
- keeps median latency under about 3 s.

If 40 or 60 is no more accurate than 20, it stays 20. The results and the chosen value are recorded in `docs/DECISIONS.md` (with a table), and the script is kept in `scripts/` so it can be re-run.

## 12. Order of work (after approval)

0. ~~Run the §11a measurement and set `MAX_CANDIDATES` from it.~~ **Done (D-074):** the limit stays 20. Jev picks the target 100 % of the time when it is offered. The misses come from ranking and vague steps, which steps 1–5 address.
1. Check vocabulary and evaluator, plus unit tests.
2. Step format, validator, `{app_id}` binding, legacy mode.
3. Loop: evaluate checks after every observation; computed position; proofs in state; remove the cursor patches.
4. Jev and navigator request block; target first; known-link navigation.
5. Research prompt and schema; re-plan with the same validator; fake `plan.json` conditions.
6. Regression tests (§11), full suites, then the real Discord run.

## 13. Open questions for the owner

1. **Direct navigation by path:** when `where` names a path on an allowed domain (e.g. `/applications/{app_id}/oauth2`), may code open it directly, or only by clicking a link seen on the page? *Recommendation: allowed (read-only, allow-listed), with a link preferred when known.*
2. **Agent steps research cannot make checkable:** keep them as *inferred* (Jev decides, the report says so), or hand them to the person? *Recommendation: inferred, and a handoff if one fails twice.*
3. **Learned recipes:** after a verified run, save the proven steps (paths, names) as a recipe for the next run of the same provider? *Recommendation: later (stretch). Research and the live page stay the source of truth.*
4. **How many elements Jev sees:** *Owner decision (2026-11-17): measure 20 vs 40 vs 60 first (§11a), then set the limit from the results.*

## 14. What this does not solve

- **A wrong or changed portal:** if Discord changes its portal, or research writes a wrong condition, a check fails. The agent then re-plans (at most twice) or asks the person, but it does so knowing exactly which check failed.
- **Unfamiliar apps** may still need the person more often on the first run.
- **Jev can still choose badly** within a page. The difference is that a bad choice can no longer *complete* a step or move the position.
