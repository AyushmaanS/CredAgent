# CredAgent — Product Requirements Document

Status: v1 · Owner: Ayushmaan · Consumer: Claude Code (implementing agent)
Working name: **CredAgent** (rename freely). Deadline: submission within 48 hours of receiving the assignment.

---

## 1. One-paragraph summary

A developer gives CredAgent an app name. CredAgent researches how that app issues credentials, opens a real browser, and works through the provider's developer console to obtain **working credentials** (an OAuth client ID and secret, an API key, a test-mode key, or whatever the app requires) with as little human intervention as possible. When it needs a person (sign-in, email code, 2FA, CAPTCHA, identity checks, payment, accepting terms), it pauses with a clear handoff, saves its progress, and resumes afterwards from where it stopped. It ends with a credential stored safely outside the repo **and a live test proving it works**, or with an honest report of what it completed, what is blocking it, and what has to happen next.

## 2. Background (for implementers with no domain context)

- **Provider**: the company whose app is being integrated (Google, Slack, Notion, GitHub...).
- **Credentials**: what a developer's code needs to call the provider. Common kinds:
  - **OAuth client** (client ID + client secret): registered in the provider's developer console; lets the developer's users connect their accounts.
  - **API key / personal or internal token**: a secret string for calling the API directly.
  - **Test-mode / sandbox keys**: credentials that work against a test environment.
- **Why access blocks progress**: generating integration code is easy; getting credentials means finding the right console, creating accounts, filling unfamiliar forms, and sometimes waiting for a provider's review. Some providers gate access behind business verification, partnerships, or paid plans.
- **Composio** (who set this assignment) is a platform between AI agents and apps. It offers managed OAuth for many apps, but developers often still need their own credentials ("bring your own OAuth app"). This agent automates getting them.

## 3. The assignment (requirements, verbatim intent)

1. Given an app name, the agent gets working credentials with as little human intervention as possible.
2. The agent decides how to get there. **Browser automation must be part of the implementation.** It must work for **unfamiliar apps** too.
3. When blocked, the agent explains **what it completed, what is preventing progress, and what needs to happen next**.
4. If a person must intervene, the **handoff is clear** and the **workflow resumes afterwards**.
5. Submit: working implementation + source repo + short setup instructions; a short demo across a few apps with **different access paths**, showing **successful and blocked** outcomes; a brief explanation of approach, where human involvement was needed, and how results were verified.
6. Be clear about **what actually ran, what failed, and what remains untested**. Keep **credentials out of the repo and the demo**.
7. Evaluated on: **how far the agent gets**, **whether its results are trustworthy**, and **the judgment behind decisions**. A follow-up discussion will explore how it handles unfamiliar apps.

## 4. Target user

A developer or agent builder who needs credentials for an app to start or ship an integration. Technically capable, but does not want to learn each provider's console. Willing to sign in and do the few steps only a human can do.

## 5. Product principles

1. **Do the work, not just describe it.** The agent performs every step it safely can.
2. **Trustworthy over impressive.** A credential is "working" only after a live test passes. Every claim in the report says what was actually done and observed.
3. **The human does what only a human should do.** Sign-in, verification codes, CAPTCHA, identity checks, payment and **accepting terms** are always done by the person. The agent never accepts terms on anyone's behalf.
4. **Clear handoffs, real resume.** Every pause tells the person exactly what to do, where, and what happens next. Resume continues from the saved step, not from scratch.
5. **Secrets never leak.** Credentials never appear in the repo, logs, reports, screenshots, model inputs, or the demo.
6. **Fast judgment where the options are known; reasoning where they are not; code where it matters.** Jev answers five closed decisions per page. The LLM handles open-ended reasoning. Code enforces safety, secrets and verification.
7. **Honest outcomes.** Blocked is a valid, useful outcome when the report explains it well.

## 6. Scope

### 6.1 In scope

| # | Feature | Notes |
|---|---|---|
| F1 | **CLI**: `credagent get "<app>"`, `resume`, `status`, `runs`, `report`, `verify`, `secret` | Local tool on the owner's laptop. No hosted service |
| F2 | **Research and plan**: identify the app, find its developer console and docs, decide the credential type and steps, predict blockers and outcome, choose how to test the credential | Bounded research agent (LLM + Tavily). Works for unfamiliar apps |
| F3 | **Shortcut check**: read public OAuth metadata; if open dynamic client registration is available, register via API without the browser | Usually not available; recorded either way |
| F4 | **Browser loop** with Stagehand: look → hard checks → Jev decisions → policy → act → record → checkpoint | Headed (visible) local browser with its own persistent profile |
| F5 | **Jev decision layer** for exactly five closed decisions: element selection, action selection, blocker detection, risk assessment, completion detection | With defined fallbacks (section 8) |
| F6 | **Handoffs**: DO (person acts in the browser) and DECIDE (person answers in the terminal) with a standard handoff card | Section 9 |
| F7 | **Pause and resume**: state checkpointed after every step; resume re-checks the page before continuing; browser profile keeps sign-ins | Works after hours or days |
| F8 | **Secret capture and storage**: masked before any model call; read by plain browser code; stored outside the repo with owner-only permissions | Shown-once secrets handled |
| F9 | **Live verification** of the credential | Section 10 |
| F10 | **Run report** (markdown + JSON): outcome, masked credential, verification, steps, handoffs, blockers, next steps, untested items, cleanup notes | No secrets in reports |
| F11 | **Demo mode**: blurs secret elements on screen and masks terminal output during recording | Plus post-demo credential rotation/deletion |
| F12 | **Fake provider test site** (local) with sign-in walls, terms boxes, implied agreement, create-app forms, shown-once secrets, CAPTCHA stand-in, and a mock token endpoint | Lets the loop be tested repeatably without real providers |
| F13 | **RESULTS.md**: honest table of every real run: what ran, what failed, what remains untested | Assignment deliverable |
| F14 | **README**: setup, approach, human involvement, verification, limitations | Assignment deliverable |

### 6.2 Out of scope

- Creating email accounts, receiving email codes, or solving CAPTCHAs (always human).
- Accepting terms of service, entering payment details, completing identity/business verification, or submitting apps for provider review (always human; the agent prepares everything before).
- Paid accounts; completing multi-day provider approvals (the agent records "waiting on provider" and can resume later).
- A hosted/public web service; multi-user operation; storing other people's credentials.
- Automated deletion of created apps (the report gives cleanup instructions; stretch only).

### 6.3 Stretch (only if time remains)

1. `credagent cleanup <run>`: guided deletion of test apps, with the person confirming each deletion.
2. Small local status page showing the live run and handoff card.
3. Export a verified credential into a chosen `.env.local` file outside the repo.

## 7. Key user flows

**Flow A: success.** `credagent get "GitHub"` → plan shown (credential type, steps, predicted outcome) → browser opens → agent navigates → pauses: "sign in" (DO) → person signs in, presses Enter → agent re-checks, continues, fills the form → pauses where a terms checkbox or implied agreement exists (DO) → person accepts and clicks → agent captures the client ID and secret (masked) → verification passes → report: **succeeded**.

**Flow B: blocked.** Same start → agent reaches a requirement it cannot satisfy and a person cannot satisfy right now (e.g., a company page, business verification, partner approval, paid plan) → report: **blocked**, with what was completed, the exact blocker and evidence, and the next steps (who must do what, and how to resume).

**Flow C: partial.** Agent obtains credentials that work in a limited mode (e.g., testing mode, unverified app, sandbox only) → report: **partial**, explaining what works now and what is needed for production (e.g., provider review).

**Flow D: resume later.** Person closes the terminal mid-handoff → later runs `credagent resume <run-id>` → browser reopens with the saved profile at the last page → agent re-checks the blocker → continues or explains why it is still blocked.

**Flow E: unfamiliar app.** Any app name → research finds the console → the plan is written from scratch → when the real page differs from the plan, the LLM rewrites the remaining plan (at most twice) → otherwise asks the person.

## 8. The decision layers (what decides what)

| Layer | Tool | Decides |
|---|---|---|
| Thinking | LLM via FastRouter | Research, planning, re-planning, open-ended page reasoning, text to type (descriptions), second opinions |
| Fast judgment | **Jev** via FastRouter | Only the five closed decisions below |
| Hands | Stagehand | Observing the page, clicking, typing, reading values |
| Rules | Code | Hard stops, policy order, secrets, verification, state, reports |

**Jev's five decisions** (one Jev request per page asks all five):

| Decision | Type | If Jev is uncertain |
|---|---|---|
| Element selection: which candidate does what this step needs? (candidates from Stagehand `observe()` plus "none of these") | Choice | **LLM** re-observes and picks |
| Action selection: proceed / step complete / wait / go back / stuck | Choice | **LLM** decides |
| Blocker detection: does a human need to act here? | Noul (yes/no probability) | **LLM second opinion**: continue only if the LLM says no human is needed, gives a reason, *and* code checks find nothing; otherwise pause |
| Risk assessment: read-only / reversible / hard to undo / irreversible | Score | Assume the next higher risk level; code hard stops always apply |
| Completion detection: has the credential been created and shown? | Noul | **Code** tries to read the credential and runs the live test |

**Jev-failure rule:** if a Jev call times out or errors, retry once; if it still fails, treat all five answers as uncertain and use the fallbacks above. If FastRouter itself is unavailable (LLM and Jev both down), save state and end as `failed: service unavailable`, resumable later.

**Rule of thumb:** Jev answers closed questions whose full answer set we wrote ourselves. Open-ended questions go to the LLM. Anything risky or final goes to code.

## 9. Handoffs

| Kind | When | Person does |
|---|---|---|
| **DO** | Sign-in or account creation, email/phone code, 2FA, CAPTCHA, identity/business verification, payment, **accepting terms (checkbox or "By clicking X you agree" wording)**, anything unexpected | Acts in the open browser window, then presses Enter |
| **DECIDE** | Choosing permissions/scopes, choosing between app types, overwriting an existing app, hard-to-undo actions | Answers in the terminal; the agent acts |

Terms are **always DO**: when terms appear inside a form, the agent fills every other field and leaves the terms control for the person, who ticks it and clicks the button. Cookie banners: the agent chooses the most limited option ("reject all" / "necessary only"); if neither exists, DO.

Every pause prints a **handoff card**: what is done so far (n of m steps), what is blocking (with the evidence observed), exactly what to do and where, what the agent will do afterwards, how to resume, and what not to do (e.g., do not close the browser window).

## 10. Trustworthy results

- **Verification labels** for credentials: `verified` (live test passed), `client_recognized` (provider accepted the client ID / client auth, but no token issued), `inconclusive`, `invalid`, `untested`. Only `verified` counts as working.
- **Run outcomes**: `succeeded` (verified credential), `partial` (credential obtained but limited or not fully verified), `blocked` (needs something that cannot be done now), `waiting_on_provider` (review pending), `failed` (error or budget exhausted), `cancelled`.
- Reports distinguish what the agent **did**, what the person **did**, and what was **observed** vs **inferred**.
- The plan's predicted outcome is compared with the actual outcome in every report.
- **RESULTS.md** lists every real run used in the demo and README, including failures.

## 11. Demo apps

**Decided later (Sprint 6).** Selection criteria: different access paths; at least one clean success, one partial, one clearly blocked, and one app the agent has not been tuned on. Candidate hypotheses (unverified, to be checked): GitHub OAuth app (likely success after sign-in), Google Cloud OAuth client (likely partial: credentials usable in testing mode, production needs verification), Slack app (likely success), Notion internal integration (API-token path), LinkedIn (possibly blocked by a company-page requirement), a test-mode API key provider (sandbox path).

## 12. Success criteria

1. **How far the agent gets** (measured per run): steps completed by the agent vs. by the person; number and kind of human interventions; time to credential; outcome.
2. **Trustworthiness**: zero credentials reported as working without a passing live test; every report lists untested items; prediction vs. reality shown.
3. **Judgment**: decisions documented (README "Key decisions"); safety rules enforced in code and tested on the fake provider site.
4. **Works on unfamiliar apps**: at least one demo run on an app not used during development; behaviour explained even if blocked.

Acceptance checks:
- [ ] End-to-end runs on the fake provider site pass for: success, terms handoff (checkbox and implied wording), sign-in handoff + resume, shown-once secret, CAPTCHA stand-in, blocked, Jev failure fallback.
- [ ] ≥4 real apps with different access paths run; at least one `succeeded` with `verified`, one `blocked`, one `partial` or `waiting_on_provider`; at least one unfamiliar app.
- [ ] Resume demonstrated after a real handoff, including after closing and reopening.
- [ ] No secret in repo history, logs, reports, screenshots or the demo (checked by a secrets scan and by reviewing the recording).
- [ ] README and RESULTS.md complete and honest; test credentials rotated or deleted after the demo.

## 13. Risks

| Risk | Mitigation |
|---|---|
| Agent clicks something harmful | Code hard stops (payment, terms, submit for review, delete, off-allow-list navigation); risk score; DECIDE for hard-to-undo |
| Secret leaks to a model, log or video | Masking before every model call; plain-code extraction; no `extract()` on secrets; demo mode blur; recording review; post-demo rotation |
| Stagehand sends credential page content to its model | Verify in Sprint 0; if it cannot be hidden, switch to plain browser code on credential pages |
| Jev misjudges a page | Thresholds, fallbacks, logging every fallback, calibration on the fake site and real runs |
| Unfamiliar console differs from the plan | Re-plan (max 2), then DECIDE/DO handoff |
| Provider terms forbid automation | Check per provider before real runs; skip and document if forbidden |
| Bot detection blocks the browser | Headed browser with a real profile; person handles CAPTCHA; report as observed |
| Over-claiming results | Verification labels; RESULTS.md with failures and untested items |
| 48-hour deadline | Sprint plan with cut order; fake site lets most work happen without real accounts |

## 14. Key decisions so far

1. Browser automation with **Stagehand**, local headed browser, persistent profile.
2. **Email accounts and verification are human steps.**
3. **Accepting terms is always DO**, never done by the agent.
4. **Jev only for the five closed decisions**; open-ended work goes to the LLM.
5. **LLM second opinion** for uncertain blocker detection; **Jev-failure rule** as in section 8.
6. **One FastRouter key** for LLM and Jev (and Stagehand's model); Tavily for research.
7. **Local CLI**, not serverless: long browser sessions, saved sign-ins and secrets need a local machine.
8. Demo apps chosen in Sprint 6.

## 15. Open questions (resolve and record in `docs/DECISIONS.md`)

1. Jev model ID and request/response format through FastRouter; latency in practice.
2. Stagehand v4 local browser with a persistent profile; whether page content can be hidden from its model calls.
3. Redirect URI to register by default (local placeholder vs. the callback the integration will actually use, e.g. Composio's).
4. Secret store: file outside the repo with owner-only permissions (default) vs. OS keychain.
5. Final demo app list and each provider's terms on automation.
