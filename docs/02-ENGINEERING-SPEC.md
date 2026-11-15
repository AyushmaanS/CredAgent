# CredAgent — Engineering Requirements Spec

Status: v1 · Derived strictly from `CredAgent-PRD.md` · Consumer: Claude Code

Anything marked **[VERIFY]** is an implementation assumption or an open question from the PRD. Confirm it before relying on it and record the outcome in `docs/DECISIONS.md`.

---

## 1. Architecture overview

CredAgent is a **local CLI application**. It runs on the owner's laptop, opens a visible browser, persists run state locally, and stores credentials outside the repository. It is not a hosted service.

```text
Terminal
  │
  ├─ credagent get "<app>"
  ├─ credagent resume <run-id>
  ├─ credagent status [<run-id>]
  ├─ credagent runs
  ├─ credagent report <run-id>
  ├─ credagent verify <run-id>
  └─ credagent secret <run-id>
          │
          ▼
     CLI / command layer
          │
          ▼
     Run orchestrator ───────────────► persistent run state + event history
          │
          ├── Research + plan (LLM via FastRouter, Tavily)
          │
          ├── Public OAuth metadata shortcut check
          │
          ├── Browser loop
          │     ├── Stagehand: observe / interact with visible browser
          │     ├── Jev: five closed decisions per page
          │     ├── LLM: open-ended reasoning and bounded replanning
          │     └── Policy engine: hard stops, action permissions
          │
          ├── Human handoff: DO / DECIDE
          │
          ├── Secret capture + external secret store
          │
          ├── Live credential verification
          │
          └── Markdown + JSON report
```

### Core execution sequence

1. Validate the app input and create a run.
2. Research the provider, developer console, credential type, setup path, likely blockers, and verification method.
3. Check public OAuth metadata for open dynamic client registration; use the API shortcut only when supported.
4. Otherwise open the headed local browser using a persistent browser profile.
5. For each page: observe, run hard checks, ask Jev its five closed decisions, apply fallbacks where needed, enforce policy, act only when permitted, record the result, and checkpoint.
6. Pause with a DO or DECIDE handoff whenever a human-only or human-judgment step is reached.
7. On resume, reopen the saved browser profile and re-check the page before continuing.
8. Capture credentials without exposing them to model inputs, logs, reports, screenshots, or demo output.
9. Run a live test. Only a passing live test earns the `verified` label.
10. Write the run report and update `RESULTS.md` for real demo runs.

## 2. Runtime and technology choices

The PRD explicitly decides the product shape and key tools below. Exact package versions and some integration details remain **[VERIFY]**.

| Concern | PRD decision | Implementation note |
|---|---|---|
| Product form | Local CLI | No hosted/public service |
| Language/runtime | [VERIFY] | Choose a supported local runtime compatible with Stagehand and the chosen CLI framework; record decision |
| Browser automation | Stagehand | Headed browser, visible to owner, persistent profile |
| Fast page decisions | Jev via FastRouter | Exactly five closed decisions per page |
| Open-ended reasoning | LLM via FastRouter | Research, planning, re-planning, page reasoning, text drafting |
| Research | Tavily | Bounded research agent for unfamiliar apps |
| Rules and orchestration | Local application code | Hard stops, policy order, state, secret handling, verification, reports |
| Persistence | Local run state | Checkpoint after every step; exact database/file format [VERIFY] |
| Secret storage | File outside repo with owner-only permissions by default | OS keychain is an open alternative; decide and record |
| Test environment | Local fake provider site | Deterministic coverage of safety and workflow cases |

Do not add a hosted backend, multi-user service, or unrelated product surface. Do not substitute a different browser automation or decision tool without recording why and how the PRD requirements remain satisfied.

## 3. Proposed repository layout

This layout is an implementation proposal derived from the PRD; adjust only with a recorded reason.

```text
/
├── README.md
├── RESULTS.md
├── docs/
│   ├── CredAgent-PRD.md
│   ├── 02-ENGINEERING-SPEC.md
│   ├── 03-SPRINT-PLAN.md
│   ├── 04-CLAUDE-CODE-STARTER-PROMPT.md
│   ├── DECISIONS.md
│   └── ATTEMPT-PROTOCOL.md
├── src/
│   ├── cli/                 # command definitions and terminal presentation
│   ├── research/            # app resolution, Tavily research, plan creation
│   ├── metadata/            # public OAuth metadata discovery and DCR shortcut
│   ├── browser/             # Stagehand lifecycle, persistent profile, page observation
│   ├── decisions/           # Jev request, schema, thresholds, fallbacks
│   ├── reasoning/           # LLM prompts, structured outputs, bounded replanning
│   ├── policy/              # hard stops, action classification, allow/deny rules
│   ├── handoff/             # DO and DECIDE cards and resume coordination
│   ├── state/               # run state, step events, checkpoints, recovery
│   ├── secrets/             # masking, capture, external store, permissions
│   ├── verification/        # credential-specific live tests
│   ├── reports/             # Markdown and JSON reports
│   └── config/              # environment and local configuration
├── fake-provider/
│   ├── app/                  # local fake provider console
│   └── fixtures/             # deterministic success/blocker scenarios
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fake-provider/
│   └── fixtures/
├── scripts/
│   ├── check-secrets.*
│   └── demo-safety-check.*
├── .env.example
└── .gitignore
```

The secret store, browser profile, and runtime run-state directory must be outside the repository or explicitly ignored and permission-restricted. Their exact paths are **[VERIFY]** and must be documented. Do not put real credentials in fixtures.

## 4. Configuration and secrets

Use a local environment/configuration file that is git-ignored. `.env.example` may contain variable names and non-secret defaults only.

The PRD explicitly identifies one FastRouter key for the LLM, Jev, and Stagehand's model, plus Tavily for research. Exact variable names and Stagehand wiring are **[VERIFY]**.

| Configuration | Purpose |
|---|---|
| FastRouter API key | LLM and Jev access; Stagehand model configuration if supported |
| FastRouter base URL | Gateway endpoint, if required |
| LLM model ID | Open-ended reasoning |
| Jev model ID | Five closed decisions |
| Tavily API key | Research |
| Browser profile path | Persistent local browser profile |
| Run-state path | Local checkpoints and event history |
| Secret-store path or keychain setting | Credential storage outside repo |
| Research/action/time budgets | Bounded execution limits; values to be decided and recorded |

### Non-negotiable secret rules

- Never print API keys or provider credentials.
- Never send provider secrets to any model.
- Mask secret values before every model call.
- Read credential values using plain browser code; do not use Stagehand extraction or an LLM on secret-bearing page content.
- Store credentials outside the repository with owner-only permissions.
- Never place secrets in run state, event history, reports, screenshots, fixtures, terminal transcripts, or demo recordings.
- The `secret` command must reveal a stored secret only through an intentional local interaction and must not print it by default. Exact UX is **[VERIFY]**.
- Scan the repository and git history before submission.

## 5. Domain model and state

The implementation must preserve enough state to resume after a handoff, including after the terminal and browser are closed. The following is a logical model; storage representation is **[VERIFY]**.

### Run

```ts
type RunOutcome =
  | "running"
  | "succeeded"
  | "partial"
  | "blocked"
  | "waiting_on_provider"
  | "failed"
  | "cancelled";

type Run = {
  id: string;
  appInput: string;
  appName?: string;
  provider?: string;
  createdAt: string;
  updatedAt: string;
  status: RunOutcome;
  currentStepId?: string;
  plan: Plan;
  steps: StepRecord[];
  handoffs: Handoff[];
  blockers: Blocker[];
  credential?: CredentialReference; // reference only; never secret material
  verification?: VerificationResult;
  predictedOutcome?: string;
  actualOutcome?: string;
  untested: string[];
};
```

### Plan

A plan records the credential type, target console, ordered actions, predicted outcome, expected blockers, and a credential-specific verification procedure. The research agent proposes the plan; code validates its shape and policy compatibility.

### Step record

Each step records its action, actor (`agent` or `person`), timestamp, outcome, observed evidence, and checkpoint reference. Distinguish explicitly between:
- what the agent did;
- what the person did;
- what the system observed;
- what the model inferred.

Never store raw credential values in a step record.

### Handoff

```ts
type HandoffKind = "DO" | "DECIDE";

type Handoff = {
  id: string;
  kind: HandoffKind;
  reason: string;
  evidence: string[];
  completedSoFar: string;
  personInstruction: string;
  expectedResumeAction: string;
  createdAt: string;
  status: "pending" | "completed" | "cancelled";
};
```

A DO handoff requires the person to act in the open browser. A DECIDE handoff requires a terminal answer; after the answer, the agent may act if policy allows.

### Credential reference and verification

```ts
type CredentialVerification =
  | "verified"
  | "client_recognized"
  | "inconclusive"
  | "invalid"
  | "untested";

type CredentialReference = {
  kind: "oauth_client" | "api_key" | "token" | "sandbox_key" | "other";
  storeRef: string;       // pointer only
  maskedDisplay: string;  // e.g. prefix/suffix only, if safe
};

type VerificationResult = {
  label: CredentialVerification;
  testedAt?: string;
  testDescription: string;
  observedResult: string;
  productionLimitations: string[];
};
```

Only `verified` means the credential is working. `client_recognized` is not equivalent to a working credential.

## 6. System components

### 6.1 CLI

Implement the commands required by the PRD:

| Command | Required behavior |
|---|---|
| `credagent get "<app>"` | Start a new run: research, plan, execute, hand off, verify, report |
| `credagent resume <run-id>` | Restore state and browser profile; re-check current page/blocker before continuing |
| `credagent status [<run-id>]` | Show current status, step, pending handoff, and next action without secrets |
| `credagent runs` | List local runs and their outcomes |
| `credagent report <run-id>` | Display or export the Markdown/JSON report |
| `credagent verify <run-id>` | Run or re-run the appropriate credential verification without exposing the secret |
| `credagent secret <run-id>` | Owner-controlled access to the stored credential; safe default is masked/no reveal |

CLI errors must be plain-language and actionable. Do not imply a run succeeded merely because a browser form was submitted.

### 6.2 Research and plan

Input: app name.

Use a bounded research agent combining Tavily and the LLM to:
- identify the canonical app/provider;
- find the developer console and official documentation;
- determine likely credential type(s);
- identify setup steps and required permissions/scopes where relevant;
- identify likely account, verification, business, payment, legal, or review blockers;
- find public information about OAuth metadata and dynamic registration;
- propose a credential-specific verification test;
- predict likely outcome and identify uncertainties.

The plan must separate sourced facts from inference and unknowns. Never invent a provider flow. If research cannot establish a fact, label it unknown and let the browser observe the actual page.

The LLM may re-plan when the page differs from the plan, but at most twice for a run. If the path remains unclear, pause with a DECIDE or DO handoff rather than improvising indefinitely.

### 6.3 Public OAuth metadata shortcut

Before browser automation, inspect public OAuth metadata where applicable. If the provider publishes open dynamic client registration, CredAgent may register through that API without opening the browser.

Rules:
- Only use a documented/public registration endpoint and supported protocol.
- Do not infer that dynamic registration is available merely because metadata exists.
- Record whether metadata was found and whether dynamic registration is supported.
- If the shortcut is unavailable or fails, continue through the browser path when appropriate.
- Do not bypass provider restrictions or human requirements.

Exact metadata discovery coverage and protocol handling are **[VERIFY]**.

### 6.4 Browser loop with Stagehand

Use a headed, visible local browser with its own persistent profile.

The loop order is fixed:

1. **Look:** Stagehand observes the current page and candidate interactive elements.
2. **Hard checks:** code checks URL/domain, page state, known dangerous controls, secret-bearing content, and policy conditions.
3. **Jev decisions:** request exactly the five closed decisions for this page.
4. **Fallbacks:** apply the PRD's Jev uncertainty/failure rules.
5. **Policy:** code decides whether the proposed action is allowed.
6. **Act:** Stagehand performs only the approved action.
7. **Record:** save action, observation, actor, outcome, and evidence without secrets.
8. **Checkpoint:** persist resumable state after every step.

Stagehand observes and acts; it does not own safety policy, decide whether a credential is verified, or bypass human handoffs.

**Credential-page safeguard:** verify in Sprint 0 whether Stagehand sends page content to its model. If secret-bearing content cannot be excluded, switch to plain browser code for credential-bearing pages. Never call `extract()` on secret values.

### 6.5 Jev decision layer

Jev is used for exactly five closed decisions. One Jev request per page asks all five.

| Decision | Expected output | Uncertainty fallback |
|---|---|---|
| Element selection | Choose the candidate from Stagehand `observe()` results, or none | LLM re-observes and picks |
| Action selection | `proceed`, `step_complete`, `wait`, `go_back`, or `stuck` | LLM decides |
| Blocker detection | Yes/no probability: does a human need to act? | LLM second opinion; continue only if LLM says no human is needed, gives a reason, and code checks find nothing; otherwise pause |
| Risk assessment | `read_only`, `reversible`, `hard_to_undo`, `irreversible` | Assume the next higher risk level; code hard stops always apply |
| Completion detection | Probability that credential has been created and shown | Code reads credential safely and runs live test; Jev cannot declare success |

Jev must not make open-ended plans, write arbitrary scripts, override policy, or decide final verification.

**Jev failure rule:** retry a timed-out or failed Jev call once. If it fails again, treat all five answers as uncertain and apply the fallbacks above. If FastRouter is unavailable for both LLM and Jev, checkpoint and end as `failed: service unavailable`, resumable later.

Thresholds, request/response schema, and model ID are **[VERIFY]** in Sprint 0 and must be recorded in `DECISIONS.md`.

### 6.6 Policy engine and action safety

Code owns policy. It must run after model decisions and before every browser action.

Hard stops include:
- accepting terms of service or any equivalent agreement;
- payment or entering payment details;
- identity or business verification;
- CAPTCHA or bot checks;
- submitting an app for provider review;
- deleting an app or other destructive action;
- off-allow-list navigation;
- any unexpected action whose risk cannot be established safely.

The agent must never accept terms on the person's behalf. This includes a checkbox and implied agreement such as “By clicking Create you agree”. It may fill the other fields, then hand control to the person.

Cookie banners: choose the most limited option (`reject all` / `necessary only`). If no such option exists, create a DO handoff.

DECIDE is required for:
- choosing permissions/scopes;
- choosing between app types;
- overwriting an existing app;
- hard-to-undo actions;
- other consequential choices where the person must decide.

A policy denial must be recorded with the reason and evidence. No LLM/Jev response can override a code hard stop.

### 6.7 Handoffs

Two kinds:

| Kind | Meaning | Person's action |
|---|---|---|
| **DO** | Human-only interaction or unexpected condition | Act in the visible browser, then return to terminal and press Enter |
| **DECIDE** | Human judgment or consequential choice | Answer the question in the terminal; agent continues only if allowed |

DO conditions include account creation/sign-in, email or phone code, 2FA, CAPTCHA, identity/business verification, payment, accepting terms, and unexpected conditions.

Each handoff card must show:
1. what has been completed so far (`n of m` where known);
2. the observed blocker and evidence;
3. exactly what the person must do and where;
4. what the agent will do afterwards;
5. how to resume;
6. what not to do (for example, do not close the browser window during an active handoff).

Handoff state must survive process exit. A person may close the terminal and resume later.

### 6.8 Pause, checkpoint, and resume

Checkpoint after every step, including immediately before and after handoffs.

On `resume`:
1. load the run and its latest checkpoint;
2. restore the persistent browser profile;
3. reopen or focus the last relevant page;
4. re-observe the page and re-check the blocker;
5. compare the current state with the saved expected state;
6. continue from the saved step if safe, otherwise re-plan (within the two-replan limit) or hand off.

Never blindly replay a click or form submission after resume. The current page must be re-checked first. If the provider state changed or the original action may already have happened, ask the person or safely reconcile before acting.

### 6.9 Secret capture and storage

Secret capture is a security boundary.

- Detect credential fields and shown-once secret displays.
- Read secret values using plain browser code, not model-based extraction.
- Mask the value before any model call or event/log write.
- Store the raw value outside the repo with owner-only permissions.
- Store only a reference and safe masked display in run state.
- Support shown-once secrets: capture immediately and safely, without copying them into chat or terminal output.
- If secure capture cannot be guaranteed, stop and ask the person to handle it; report the credential as not captured.
- Never expose secrets in reports, screenshots, recordings, model inputs, or demo output.

Default secret storage is a file outside the repo with owner-only permissions. OS keychain is an open question in the PRD; evaluate and record the choice. Secret-store encryption and platform-specific permission behavior are **[VERIFY]**.

### 6.10 Live credential verification

A credential counts as working only if a live test passes.

Labels:

| Label | Meaning |
|---|---|
| `verified` | Credential-specific live test passed |
| `client_recognized` | Provider accepted the client ID/client authentication, but no token was issued |
| `inconclusive` | Test ran but did not establish validity |
| `invalid` | Provider rejected the credential or test conclusively failed |
| `untested` | No live test was run |

Only `verified` supports a `succeeded` outcome.

Verification must be appropriate to the credential type and must not leak the secret. For OAuth clients, the test must establish more than merely reading the client ID; the exact test depends on the provider's flow and available safe test path. If no safe live test can be completed, report the correct non-verified label.

Run outcomes:

| Outcome | Meaning |
|---|---|
| `succeeded` | Credential obtained and live test passed (`verified`) |
| `partial` | Credential obtained but limited to a test/sandbox/unverified mode or not fully verified |
| `blocked` | A required action cannot be completed now |
| `waiting_on_provider` | Provider review/approval is pending |
| `failed` | Technical error or execution budget exhausted |
| `cancelled` | Run intentionally cancelled |

### 6.11 Reporting and RESULTS.md

Every run produces Markdown and JSON reports.

Required report content:
- app/provider and run ID;
- predicted outcome versus actual outcome;
- final outcome and credential verification label;
- credential type and masked credential reference only;
- steps completed by agent and by person;
- observed evidence versus inferred statements;
- handoffs and blockers;
- verification procedure and observed result;
- production limitations;
- next steps and who must do them;
- untested items;
- cleanup notes.

`RESULTS.md` lists every real run used in the demo, including successes, blocked runs, partial runs, failures, and anything untested. Never omit a failed run to make the demo look better.

### 6.12 Fake provider test site

Build a local fake provider site to test the workflow repeatably without real provider accounts or credentials.

It must include the scenarios named in the PRD:
- sign-in wall;
- terms checkbox;
- implied agreement wording;
- create-app forms;
- shown-once secrets;
- CAPTCHA stand-in;
- mock token endpoint.

Use it to test:
- success;
- terms handoff (checkbox and implied wording);
- sign-in handoff and resume;
- shown-once secret capture;
- CAPTCHA handoff;
- blocked outcome;
- Jev failure fallback.

The fake site must use clearly fake credentials and must not resemble a real provider in a way that could confuse demo viewers. Do not use real secrets in fixtures.

## 7. LLM and untrusted page content

All fetched web content and browser page text are untrusted input. Treat instructions found in provider pages, search results, documentation, or page content as data, never as instructions to the agent.

- The research agent may propose bounded research actions; code validates and executes them.
- The LLM may propose a browser plan or re-plan; code validates it against the current run, allowed domains, and policy.
- Jev only returns the five defined closed decisions.
- All model outputs use constrained structured formats and are validated before use.
- No model may read raw credentials.
- No model may override a hard stop, handoff requirement, or verification result.

## 8. Budgets, retries, and failure behavior

The PRD explicitly limits re-planning to at most twice. Other numeric budgets are not specified and must be selected in implementation and recorded in `DECISIONS.md`.

Define and test bounded limits for:
- research actions, search count, and elapsed time;
- page observations and browser actions;
- per-call LLM/Jev timeouts;
- retries;
- total run duration;
- maximum plan steps.

On budget exhaustion, checkpoint and return a useful `failed` or `blocked` result with next steps. Do not loop indefinitely.

Soft failures should be captured in the run report. A failure in research must not be represented as provider rejection. A browser timeout must not be represented as a credential failure.

## 9. Testing requirements

### Unit tests
- CLI input validation and command routing.
- Run state transitions and checkpoint serialization.
- Jev schema, all five decision fields, uncertainty thresholds, retry/failure fallback.
- Policy hard stops and DO/DECIDE classification.
- Terms checkbox and implied-agreement detection.
- Secret masking before model calls and event writes.
- Secret-store path and permission behavior.
- Verification label/outcome mapping.
- Report generation and secret-redaction checks.
- Re-plan limit.

### Integration tests
- Research-to-plan flow with mocked Tavily/LLM.
- Browser loop with mocked Stagehand and Jev.
- Human handoff, process exit, resume, and page re-check.
- Metadata shortcut supported / unsupported / malformed / failed.
- Credential capture and verification without raw secret entering logs or model inputs.
- FastRouter unavailable behavior.

### Fake-provider acceptance tests
All cases in PRD acceptance check 1 must pass:
1. success;
2. terms handoff by checkbox;
3. terms handoff by implied agreement;
4. sign-in handoff and resume;
5. shown-once secret;
6. CAPTCHA stand-in;
7. blocked;
8. Jev failure fallback.

### Security checks
- Scan working tree and git history for secrets.
- Inspect logs, reports, screenshots, fixtures, and demo output for leakage.
- Verify `.env` and runtime directories are ignored.
- Verify secret-store permissions.
- Confirm no terms, payment, review submission, deletion, or off-domain action can be triggered by model output alone.

## 10. Open decisions to resolve

Record each decision and evidence in `docs/DECISIONS.md`.

1. Jev model ID and request/response format through FastRouter; measure latency and reliability.
2. Stagehand version and local headed-browser setup with a persistent profile.
3. Whether Stagehand sends page content to its model and whether secret-bearing content can be hidden; if not, use plain browser code on credential pages.
4. Runtime/language and CLI framework.
5. Exact run-state storage format and location.
6. Secret store: owner-only file outside repo versus OS keychain.
7. Default redirect URI: local placeholder versus the callback the integration will actually use (for example, Composio's).
8. Research, action, page, retry, and time budgets.
9. Provider-specific terms and whether automation is permitted for each real demo.
10. Final demo app list, chosen to show different access paths and the required outcome mix.

## 11. Definition of done

- [ ] CLI supports all required commands.
- [ ] Research and planning work for an unfamiliar app, with bounded actions and honest uncertainty.
- [ ] Public OAuth metadata/DCR shortcut is checked and recorded where applicable.
- [ ] Headed Stagehand browser uses a persistent profile.
- [ ] Jev makes exactly the five defined decisions, with all specified fallbacks.
- [ ] Code enforces hard stops and DO/DECIDE handoffs.
- [ ] Every step is checkpointed; resume re-checks the page and does not blindly replay actions.
- [ ] Secrets are masked before model calls and stored outside the repo with owner-only permissions.
- [ ] Only a passing live test is labelled `verified`.
- [ ] Fake-provider acceptance scenarios pass.
- [ ] At least four real apps with different access paths are run, including one verified success, one blocked, one partial or waiting-on-provider, and one unfamiliar app.
- [ ] Resume is demonstrated after a real handoff, including closing and reopening.
- [ ] `README.md` and `RESULTS.md` are complete and honest.
- [ ] No secrets exist in repo history, logs, reports, screenshots, or demo.
- [ ] Test credentials are rotated or deleted after the demo.
