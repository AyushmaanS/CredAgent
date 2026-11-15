# CredAgent — Sprint Plan v1

Eight focused sprints for the 48-hour assignment window. The time estimates below are planning estimates, not PRD guarantees. Adjust based on the actual environment and record trade-offs in `docs/DECISIONS.md`.

Every sprint ends with a checkpoint: commit, short status note, tests, and a clear list of verified facts, assumptions, blockers, and owner actions.

## Rules for every sprint

- Work in small tasks and commit after each meaningful task.
- Run lint and relevant tests before committing.
- Run the secret scan before every commit once it exists.
- Never put provider credentials, API keys, or real secrets in chat, source, fixtures, logs, reports, screenshots, or demo output.
- Never invent provider facts. Distinguish observed, sourced, inferred, and untested information.
- Do not act in a real provider account without the owner's explicit consent for that provider.
- Follow `docs/ATTEMPT-PROTOCOL.md`; stop at every human-only or consequential step.
- Record all material technical choices and PRD open questions in `docs/DECISIONS.md`.

Owner actions are marked **👤**. Claude Code must explain them in plain, numbered steps.

---

## Sprint 0 — Local foundation and feasibility spikes (≈2 hours)

**Goal:** a working local CLI skeleton and verified feasibility for the chosen tools.

Tasks

1. Scaffold the local project, CLI entry point, test setup, `.gitignore`, `.env.example`, `README.md`, `RESULTS.md`, and the repository structure in the engineering spec.
2. Add a secret scan script and pre-commit check. Ensure `.env*` files other than `.env.example`, browser profiles, run state, and secret-store paths are ignored.
3. 👤 Explain how the owner creates the local environment file and adds FastRouter and Tavily keys without pasting them into chat or committing them.
4. Verify FastRouter connectivity for the LLM and Jev:
   - identify available model IDs;
   - test a normal LLM request;
   - test constrained structured output;
   - test Jev request/response format and latency;
   - run repeated trials for the five-decision response shape.
5. Verify Tavily search and research extraction.
6. Verify Stagehand can launch a visible local browser and retain a persistent profile across process restarts.
7. Verify whether Stagehand sends page content to its model and whether secret-bearing content can be excluded. If it cannot, document the plain-browser-code fallback for credential pages.
8. Verify local state persistence and owner-only secret-file permissions on the target machine.
9. Create `docs/DECISIONS.md` with results, selected runtime/CLI approach, models, paths, budgets to test later, and unresolved questions.

Exit: CLI prints help; local project starts; tool feasibility results are recorded; no secrets are committed.

Checkpoint 👤: owner reviews the decisions summary and confirms the local setup.

---

## Sprint 1 — Safety protocol, domain model, and fake provider (≈3 hours)

**Goal:** define the safety boundary and make the core workflow testable without real provider accounts.

Tasks

1. Write `docs/ATTEMPT-PROTOCOL.md` from PRD sections 5, 6.2, 7, 9, and 13. It must define consent, DO/DECIDE, terms, payment, verification, account access, screenshots, secrets, and cleanup.
2. 👤 Owner reviews and approves the protocol before any real-provider walkthrough.
3. Implement the logical run, plan, step, handoff, credential-reference, and verification models from the engineering spec.
4. Implement checkpoint serialization and state transitions. Test restart and recovery.
5. Build the local fake provider site with:
   - sign-in wall;
   - terms checkbox;
   - implied agreement copy;
   - create-app form;
   - shown-once secret;
   - CAPTCHA stand-in;
   - mock token endpoint.
6. Add deterministic fake-provider scenarios for success, terms handoff, sign-in/resume, CAPTCHA, blocked, and Jev failure.
7. Create obviously fake test fixtures; no real provider branding or credentials.

Exit: protocol approved; state can be saved/restored; fake provider can represent each required path.

Checkpoint 👤: owner approves the protocol and confirms the fake-site scenarios.

---

## Sprint 2 — CLI, research, and plan generation (≈3 hours)

**Goal:** `credagent get "<app>"` researches an app and produces a structured, honest plan.

Tasks

1. Implement `get`, `status`, `runs`, and `report` command skeletons.
2. Implement Tavily wrapper with bounded searches, timeouts, deduplication, and source capture.
3. Implement app/provider resolution and developer-console discovery.
4. Implement structured LLM research synthesis:
   - credential type;
   - console URL;
   - documented setup steps;
   - likely blockers;
   - public OAuth metadata/DCR availability;
   - verification approach;
   - predicted outcome and uncertainties.
5. Ensure every plan separates sourced facts, observations, inferences, and unknowns.
6. Add the maximum-two-replans guard to the run model.
7. Test with several app names, including an unfamiliar name and a nonsense input.
8. Record the quality and failure modes in `DECISIONS.md`.

Exit: research and plan generation work with mocked and live tool calls; uncertainty is surfaced rather than filled with guesses.

Checkpoint: owner reviews one generated plan before browser execution is enabled.

---

## Sprint 3 — Metadata shortcut and browser loop (≈4 hours)

**Goal:** execute the safe parts of a real setup path in a visible browser.

Tasks

1. Implement public OAuth metadata discovery and dynamic-registration eligibility checks.
2. Implement the API shortcut only for providers whose public metadata documents support for dynamic registration. Record unsupported/unknown outcomes too.
3. Integrate Stagehand with a headed browser and persistent profile.
4. Implement the ordered loop: observe → hard checks → Jev → fallback → policy → act → record → checkpoint.
5. Implement candidate-element normalization for Jev element selection.
6. Add domain allow-list and navigation checks.
7. Add the Stagehand secret-page safeguard; use plain browser code for secret-bearing pages if necessary.
8. Use the fake provider to verify the browser can navigate and complete safe form fields without crossing human-only gates.

Exit: browser loop works on fake provider; metadata check is honest; every action is policy-checked and checkpointed.

Checkpoint 👤: owner watches a fake-provider run and confirms the browser is visible and understandable.

---

## Sprint 4 — Jev decisions, policy, and human handoffs (≈4 hours)

**Goal:** enforce the five Jev decisions and make human intervention safe and clear.

Tasks

1. Implement one Jev request per page containing exactly:
   - element selection;
   - action selection;
   - blocker detection;
   - risk assessment;
   - completion detection.
2. Implement all uncertainty fallbacks and one retry on Jev error/timeout.
3. Implement FastRouter-unavailable behavior: checkpoint and end as resumable `failed: service unavailable`.
4. Implement policy hard stops for terms, payment, identity/business verification, CAPTCHA, provider review submission, deletion, and off-allow-list navigation.
5. Implement DO and DECIDE handoff cards with all required fields.
6. Implement cookie-banner behavior: choose the most limited option or DO handoff.
7. Test terms checkbox and implied agreement detection.
8. Test that LLM/Jev outputs cannot override hard stops.

Exit: every required handoff and Jev fallback passes fake-provider tests.

Checkpoint 👤: owner reviews sample DO and DECIDE cards.

---

## Sprint 5 — Resume, secret handling, and verification (≈4 hours)

**Goal:** safely continue after interruptions and prove credentials work.

Tasks

1. Implement `resume <run-id>`:
   - restore state and browser profile;
   - re-open/focus the saved page;
   - re-observe and re-check blocker;
   - continue only when the current state is safe;
   - avoid blindly replaying clicks or submissions.
2. Test resume after terminal close/reopen and after browser close/reopen.
3. Implement credential-field detection and plain-code secret capture, including shown-once values.
4. Implement masking before all model calls, event writes, logs, reports, and terminal output.
5. Implement external secret storage with owner-only permissions; decide file versus OS keychain and record the rationale.
6. Implement `secret <run-id>` with safe default behavior and intentional owner-controlled reveal.
7. Implement credential-specific live verification and all five verification labels.
8. Enforce outcome mapping: only `verified` can produce `succeeded`.
9. Add automated secret-leak tests across run state, logs, reports, and screenshots where testable.

Exit: resume works after restart; shown-once secrets are captured without model exposure; fake credential live test passes; unverified credentials cannot be called successful.

Checkpoint 👤: owner approves secret-storage behavior and sees a safe verification report.

---

## Sprint 6 — Real-provider runs and demo coverage (≈5 hours)

**Goal:** demonstrate different access paths, honest outcomes, and unfamiliar-app handling.

Tasks

1. Select at least four real apps with different access paths. The final list is a decision, not a PRD assumption.
2. Before each provider run:
   - inspect its terms and automation restrictions;
   - explain the intended actions and risks;
   - obtain explicit owner consent;
   - follow the approved attempt protocol.
3. Run the workflow and capture what the agent did, what the person did, and what was observed.
4. Ensure the demo set includes:
   - at least one `succeeded` run with `verified`;
   - at least one `blocked` run;
   - at least one `partial` or `waiting_on_provider` run;
   - at least one app unfamiliar to development.
5. Demonstrate a real handoff and resume, including closing and reopening.
6. Update `RESULTS.md` with every real run, including failures and untested items.
7. Rotate or delete test credentials after the demo where applicable; document any provider cleanup the owner must perform.

Exit: the required real-app outcome mix and resume demonstration are complete, or gaps are explicitly documented with reasons.

Checkpoint 👤: owner reviews every real-run entry and approves the demo credential cleanup.

---

## Sprint 7 — Hardening, README, and submission (≈3 hours)

**Goal:** deliver a reproducible implementation and honest evidence.

Tasks

1. Run the complete unit, integration, and fake-provider test suites.
2. Run secret scans over the working tree and git history.
3. Inspect reports, logs, screenshots, and demo recording for secret leakage.
4. Confirm terms, payment, review submission, deletion, and off-domain navigation cannot be triggered by model output alone.
5. Complete `README.md`: setup, architecture, Jev's five decisions, Stagehand loop, handoffs, resume, secret handling, verification, human involvement, key decisions, and limitations.
6. Complete `RESULTS.md`: all real runs, predicted versus actual outcomes, verification labels, failures, blockers, and untested items.
7. Rehearse the demo across the selected apps and fake-provider scenarios.
8. Confirm test credentials have been rotated/deleted where applicable.

Exit: PRD acceptance checks are met or every unmet check is explicitly reported; source repo and setup instructions are ready.

Checkpoint 👤: owner reviews the final README, RESULTS.md, demo, and cleanup status.

---

## Time summary

| Sprint | Estimate |
|---|---:|
| 0 Foundation and feasibility | 2:00 |
| 1 Protocol, state, fake provider | 3:00 |
| 2 Research and planning | 3:00 |
| 3 Metadata and browser loop | 4:00 |
| 4 Jev, policy, handoffs | 4:00 |
| 5 Resume, secrets, verification | 4:00 |
| 6 Real-provider runs | 5:00 |
| 7 Hardening and submission | 3:00 |
| **Total** | **28:00** |

This is a planning estimate for implementation work, not a guarantee that the assignment can be completed in 28 hours. The 48-hour deadline includes debugging, tool access, provider friction, and owner actions. Keep the PRD's trust and safety requirements ahead of cosmetic polish.

## Cut order if time is short

Apply in this order, while preserving the PRD's core evaluation requirements:

1. Reduce CLI presentation polish; keep the required commands and behavior.
2. Reduce the number of optional research sources while retaining bounded research and source/uncertainty distinctions.
3. Keep only the minimum fake-provider UI needed to exercise every required scenario.
4. Simplify report formatting while retaining every required report field.
5. Reduce demo app count only if the acceptance requirement of at least four real apps can still be met; otherwise report the unmet criterion honestly.

**Do not cut:** browser automation, the five Jev decisions and their fallbacks, code-enforced hard stops, DO/DECIDE handoffs, checkpoint/resume, secret isolation, live verification, fake-provider safety tests, or honest RESULTS.md reporting. These are central to the PRD and evaluation.

## Risk-driven adjustments

- If Stagehand exposes secret-bearing page content to its model, switch to plain browser code for credential pages before proceeding.
- If Jev's structured response or latency is unreliable, simplify the integration and strengthen the specified fallbacks; do not silently replace Jev's five-decision role.
- If provider terms prohibit automated console use, do not automate that provider's console. Record the restriction and choose another demo path.
- If a provider requires business verification, payment, or review, stop at the handoff and report the blocker.
- If a provider's credential cannot be safely live-tested, do not label it `verified`.
- If FastRouter is unavailable, checkpoint and end the run as resumable service failure.
