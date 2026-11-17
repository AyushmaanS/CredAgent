# Scoping: LLM agent loop over Playwright, run by the orchestrator (D-078)

Status: **approved** (2026-11-17). Phase 1 done (D-079). Decision: `docs/DECISIONS.md` D-078.

## 1. Target architecture (owner)

```
User request
   │
Orchestrator ─── workflow state, phases, budgets, checkpoints, handoffs, consent, reports
   │   ▲
   ▼   │ result (done / needs person / blocked / failed)
Agent loop, per step:
   Browser observation ──► LLM reasoning ──► code gate ──► Playwright executor
   (DOM snapshot, URL,      (one structured    (hard stops,   (click · type · select ·
    visible elements,        action + reason)   policy,        navigate · scroll ·
    what changed)                               secrets)       inspect · back · wait)
        ▲                                                             │
        └──────────────────────── page changes ◄──────────────────────┘
   until the objective is reached (code confirms it) or the workflow stops
```

**One decision maker per step:** the LLM. **One executor:** Playwright, connected over CDP to the CredAgent-owned Chrome. **One place for safety:** code, applied to every proposed action before it runs. There is no Jev, no Stagehand, no fallback chain, no navigator, no re-plan call, and no step-position bookkeeping.

### What code still owns (non-negotiable, unchanged from the brief)
| Concern | Where | Notes |
|---|---|---|
| **Hard stops and policy** | `policy/hard_checks.py`, `policy/engine.py` | Run on every observation and every proposed action: terms (including buttons named in the agreement), payment, verification, CAPTCHA, deletion, review, off-allow-list, docs-detour, one app per run, repeat guard |
| **DO/DECIDE handoffs** | `handoff/cards.py` and loop | The LLM may *ask* for a handoff; code decides which kind, and some are forced (sign-in, terms, CAPTCHA) |
| **Values typed** | `browser/candidates.FieldValues` | The LLM names a value **key** (`app_name`, `redirect_uri` …). It never writes free text into fields |
| **Secrets** | `secrets/` | The snapshot hides secret elements (`[SECRET-ELEMENT]`). Capture is plain code; masking before every model call and write; leak guard |
| **Completion** | capture plus `verification/` | The LLM may say "done"; the run is done only when code has captured a secret and the live test result is in |
| **State** | `state/`, orchestrator | Run record, events, checkpoints, resume, consent, created resources |

## 2. The LLM step contract

**Input per step** (masked; about 6–10k tokens):
- **Objective:** credential kind, console URL, allowed domains, what was created, approved value keys and their purposes.
- **Plan:** research's steps as plain guidance text, not a state machine.
- **Snapshot:**
  - URL and title;
  - visible headings;
  - interactive elements as numbered refs `e1…eN`, each with role, name, state (filled / checked / disabled), section and href;
  - trimmed page text with secrets removed.
- **Recent history:** the last 8 steps, as action → observed effect (page changed / no change / error / policy denied with reason).
- **Code notes:** e.g. *"not done: no credential captured"*, *"denied: 'Create' carries the terms — ask the person"*.

**Output (strict JSON schema):**
```jsonc
{
  "action": "click | type | select | navigate | scroll | inspect | back | wait | ask_person | done | give_up",
  "ref": "e12",                 // click / type / select / inspect
  "value_key": "redirect_uri",  // type: an approved key, never free text
  "option": "Web app",          // select: one of the element's options
  "url": "https://…",           // navigate: allowed domains only
  "reason": "…",                // short; logged for debugging
  "expected": "…",              // what should change; compared with the next observation
  "person": {"kind": "DO|DECIDE", "why": "…", "options": ["…"]}   // ask_person only
}
```

**Validation by code, before the policy:**
- the `ref` exists in this snapshot;
- `value_key` is approved;
- `url` is on the allowed domains and not a docs page;
- an invalid action is rejected with a note, and the step is retried (it counts against the budget).

## 3. Inventory: what is reused, adapted, removed or new

Line counts are as of 2026-11-17.

| Module | Lines | Fate | Notes |
|---|---|---|---|
| `cli/main.py` | 664 | **Adapt (small)** | Same commands; fake/real deps builders no longer build Jev or Stagehand |
| `orchestrator.py` | 449 | **Adapt** | Browser phase calls the new agent loop. Metadata/DCR, verify-and-finish and resume flow stay |
| `research/agent.py`, `schemas.py`, `sections.py`, `tavily.py` | 938 | **Keep, simplify** | Plan stays (credential kind, console, domains, blockers, verification, steps as guidance). The step condition fields (D-075) are dropped |
| `reasoning/fastrouter.py` | 141 | **Keep** | LLM client; `systemone` (Jev) is unused and removed |
| `reasoning/replan.py` | 109 | **Remove** | The agent re-decides every step; no separate re-plan call |
| `decisions/jev.py`, `decisions/client.py` | 492 | **Remove** | Jev, the fallbacks, RuleJev, RuleLLM and the navigator. An offline **scripted LLM** replaces RuleJev for tests (new) |
| `browser/chrome.py` | 180 | **Keep** | CredAgent-owned headed Chrome, persistent profile, graceful close, reattach |
| `browser/session.py` | 69 | **Rewrite** | Playwright `connect_over_cdp` to our Chrome (no Stagehand) |
| `browser/stagehand_llm.py` | 69 | **Remove** | Stagehand's model callback |
| `browser/observe.py` | 159 | **Adapt** | Same plain-code snapshot (secrets hidden, slug/approved-value rules), plus element refs and a compact text rendering for the LLM |
| `browser/candidates.py` | 182 | **Shrink** | Keep `FieldValues` and field mapping; drop candidate building, normalising and ranking (the LLM sees all refs) |
| `browser/loop.py` | 1,570 | **Rewrite, about 300–400 lines** | New agent loop. Kept *as ideas*: handoff flow and re-check, form completion before a terms handoff (D-050), reveal and reset-for-secret DECIDEs (D-077), capture at the credential page, budgets. Dropped: Jev calls, fallbacks, candidates, proofs, position, cursor corrections, save heuristics |
| `steps/checks.py`, `validate.py`, `convert.py` | 417 | **Remove (mostly)** | The step machine goes. `is_docs_host` and the create-step detection move to policy if still needed |
| `policy/engine.py`, `hard_checks.py` | 476 | **Keep, adapt input** | `ProposedAction` is built from the LLM action and ref. All rules stay. Risk comes from code rules plus the LLM's reason. Unknown, consequential buttons stay a DECIDE |
| `secrets/masking.py`, `store.py`, `capture.py` | 454 | **Keep** | Unchanged |
| `verification/verify.py` | 150 | **Keep** | Unchanged |
| `metadata/discovery.py`, `dcr.py` | 213 | **Keep** | Unchanged |
| `consent/terms.py` | 76 | **Keep** | Unchanged |
| `state/models.py`, `store.py`, `atomic.py` | 655 | **Keep, prune** | Drop `proofs`, `bindings`, `plan_cursor` and the step condition fields; old runs stay readable |
| `reports/report.py`, `handoff/cards.py` | 275 | **Keep, small** | The report gains the per-step action log (action, reason, effect, policy verdict) |
| `fake_provider/` (site, scenarios, faults) | ~900 | **Keep** | All scenarios stay. `jev_failure` becomes `llm_failure` (bad JSON / timeouts); `service_unavailable` stays |
| `scripts/measure_candidates.py` | | **Retire** | It measured Jev |

**New code:**

| New | Estimate | What it does |
|---|---|---|
| `browser/executor.py` | ~150 lines | Playwright actions by ref (click, fill, select, navigate, scroll, inspect, back, wait), with timeouts and result capture. `inspect` returns non-secret text of one element (masked) |
| `agent/step.py` (contract) | ~120 lines | JSON schema, pydantic model, validation against the snapshot (refs, keys, URLs) |
| `agent/prompt.py` | ~120 lines | Builds the masked step input: objective, plan guidance, snapshot, history, code notes |
| `agent/loop.py` | ~350 lines | Observe → hard checks → LLM → validate → policy → execute → record → checkpoint, with no-change and repeat detection, budgets, handoffs, capture and the done check |
| `agent/scripted.py` | ~100 lines | Deterministic offline stand-in for tests (follows the fake plan) |
| Dependency | | `playwright` (Python). It connects over CDP to the existing Chrome, so **no browser download is needed** |

**Net size:** about 2,900 lines removed or replaced, about 850 new.

## 4. Tests

- **Kept as is:** unit tests for masking, the secret store, state and atomic writes, settings, check_secrets, models, run store, capture and verification, consent, research, sections and the FastRouter client.
- **Kept, adapted to the new action input:** policy and hard-check tests (`test_policy_and_checks.py`) and cards.
- **Removed:** `test_jev.py`, `test_stagehand_llm.py`, `test_step_checks.py`, `test_steps_validate.py`, and the Jev parts of `test_policy_and_checks.py`.
- **Real Chrome (fake provider):** the harness switches from RuleJev to the scripted LLM. **Every scenario and safety assertion is kept**: terms only by the person, one app, no forbidden audit events, no leaks, shown-once secret, hidden secret, reset with confirmation, resume and reattach, in-doubt click, docs detour, stray full stop, the decoy token and the hostile-model tests (now a hostile LLM).
- **New:**
  - the step contract (schema, invalid ref, key or URL);
  - the executor (each action);
  - the loop (no-change detection, budget, `done` without a captured credential is rejected);
  - online smoke runs on the fake provider with the real LLM.

## 5. Risks and how the design handles them

| Risk | Handling |
|---|---|
| **The LLM clicks something dangerous, or obeys page text** (prompt injection) | Unchanged code gate: hard stops and policy on every action; page text is data in the prompt; tests with a hostile LLM |
| **It invents an element** | Refs are validated against this snapshot; anything else is rejected |
| **It loops** | The history shows "no change"; code detects repeats and no progress, then tells the LLM; after N repeats the person is asked; budgets stop the run |
| **It says "done" too early** | Code completion: a secret captured by plain code plus the live test; otherwise *"not done: …"* goes back in the next step |
| **Secrets reach the LLM** | Same snapshot rules (secret elements hidden; masking before every call; leak guard); `inspect` is masked and refused on secret elements |
| **Cost and latency** | One LLM call per step. To measure on the fake provider and on Discord before choosing the model: tokens per step, steps per run, seconds per step |
| **Debugging** | One decision point per step. The report logs input summary → action → reason → expected → policy verdict → effect |
| **Old runs** | Runs saved under the old loop are not resumable by the new one. They stay readable in reports, and a fresh run is started (RESULTS.md notes this) |

## 6. Phases (after approval)

| # | Phase | Exit check |
|---|---|---|
| 1 | ✅ Playwright session over CDP, executor, snapshot with refs | Executor tests pass on the fake site; profile and reattach unchanged (D-079) |
| 2 | Step contract, prompt builder, validation | Contract unit tests; prompt contains no secret (leak test) |
| 3 | Agent loop with policy, hard checks, handoffs and budgets | Fake scenarios with the scripted LLM: success, terms, sign-in, CAPTCHA, blocked, cookie |
| 4 | Capture, reset/reveal DECIDEs, verification, resume and reattach | Shown-once, hidden secret, reset with confirmation, resume, in-doubt click |
| 5 | Remove Jev, Stagehand, steps and re-plan; prune state; update CLI | All suites green; no import of the removed modules |
| 6 | Online fake runs with the real LLM; measure cost and latency | Recorded in DECISIONS |
| 7 | Update PRD, spec, sprint plan and README; then the real Discord run | Owner review; RESULTS #6 |

Rough effort: phases 1–5 about 1.5–2 working days; phase 6 half a day; phase 7 depends on Discord.

## 7. Questions for the owner

1. **Model for the agent loop:** `anthropic/claude-sonnet-5.5` (the current research LLM), or decide after the phase 6 measurement? *Recommendation: start with Sonnet 5.5 and measure.*
2. **Screenshots for the LLM:** keep them off (current rule: images are never sent to a model), or allow them on pages without secrets? *Recommendation: keep off at first. The DOM snapshot is enough for consoles, and screenshots carry secret risk.*
3. **Which code safeguards stay** beyond the brief's hard stops: the docs-detour rule, the repeat guard, form completion before a terms handoff, and the one-app rule? *Recommendation: keep all four. They are simple policy rules, not state machines.*
4. **Research plan detail:** drop the step conditions (D-075) and keep steps as plain guidance? *Recommendation: yes.*
5. **Remove the old code**, or keep it on a branch? *Recommendation: remove it from `main` after phase 5. It stays in git history (tag `pre-d078`).*
