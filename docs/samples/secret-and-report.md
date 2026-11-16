# Sample: stored credential and verification report

From a real run against the fake provider (real Jev + Stagehand + LLM, headless), paused at a DECIDE, then continued from a new process with `credagent resume`. Generated 2026-11-16. The client ID and secret below are the fake site's; only masked forms appear.

## `credagent secret 20261116-064307-fakeprov-success-fb68` (default: masked)

```text
Run 20261116-064307-fakeprov-success-fb68 — oauth client, captured 2026-11-16T06:44:02+00:00, live test: verified
  client_id       ••• (22 chars)         ~/.credagent/secrets/20261116-064307-fakeprov-success-fb68/client_id.secret  [owner-only (file 0600, folders 0700)]
  client_secret   fpcs… (45 chars)       ~/.credagent/secrets/20261116-064307-fakeprov-success-fb68/client_secret.secret  [owner-only (file 0600, folders 0700)]
Stored as plain files readable only by your macOS user; not encrypted (D-053).
Time Machine: INCLUDED in backups. To exclude it yourself: tmutil addexclusion ~/.credagent
To reveal one value on purpose: credagent secret 20261116-064307-fakeprov-success-fb68 --reveal <name>
```

Revealing needs `--reveal <name>`, an interactive terminal, and typing the name to confirm. It copies to the clipboard by default; `--print` shows it in the terminal.

## `credagent report 20261116-064307-fakeprov-success-fb68`

```markdown
# CredAgent report — Fakeprov

Run `20261116-064307-fakeprov-success-fb68` · provider: Fakeprov (local fake provider) · created 2026-11-16T06:43:07+00:00

## Outcome
- **Status:** succeeded (phase: done) — credential captured and live test passed — captured from the console by plain browser code
- **Predicted:** succeeded · **Actual:** succeeded
- **Credential:** oauth_client · client_id ••• (22 chars), client_secret fpcs… (45 chars)
- **Verification:** `verified`

## What happened
- Agent actions: 18 · Person actions: 1 · System: 1
- [agent] checked OAuth metadata (1 URLs) → done
- [agent] chose the most limited cookie option (button: "Reject all") → done
- [agent] click link 'Console' → done
- [agent] step complete: Open the developer console (expected page: /console) → done
- [agent] click The "Create new app" link in the main content, which opens the form to create a new app (/apps/new). [Create new app] → done
- [agent] step complete: Open the form to create a new app (expected page: /apps/new) → done
- [agent] fill The Application name textbox in the Register a new OAuth app form. [Application name] = credagent-demo-20261116 → done
- [agent] step complete: Fill in the application name field → done
- [agent] fill The 'Authorization callback URL' textbox in the OAuth app registration form, labeled by the 'Authorization callback URL' text. [Authorization callback URL] = http://127.0.0.1:8976/callback → done
- [agent] step complete: The Authorization callback URL textbox in the OAuth app registration form. It currently shows http://127.0.0.1:8976/callback. [Authorization callback URL] (already filled) (code: field  → done
- [system] resumed: re-checking the page instead of assuming “other” was done → done
- [agent] click link 'Create new app' → done
- [person] person decided: Yes, do it → done
- [agent] fill text field 'Application name' = credagent-demo-20261116 (completing the form before it is submitted) → done
- [agent] fill text field 'Description' = Created by CredAgent for integration testing. (completing the form before it is submitted) → done
- [agent] fill text field 'Homepage URL' = http://127.0.0.1:8976 (completing the form before it is submitted) → done
- [agent] fill text field 'Authorization callback URL' = http://127.0.0.1:8976/callback (completing the form before it is submitted) → done
- [agent] click The "Create app" button that submits the form to register a new OAuth app. [Create app] → done
- [agent] captured the credential by plain browser code (client_id, client_secret); stored outside the repo → done
- [agent] live test: OAuth client-credentials token request (RFC 6749 §4.4) at http://127.0.0.1:56485/oauth/token → done

## Plan
- Credential type: oauth_client
- Alternatives found: none
- Console: http://127.0.0.1:56485/console
- Allowed domains: 127.0.0.1
- Redirect URI needed: yes · Dynamic registration: documented_open

1. Open the developer console `navigate`
2. Open the form to create a new app `click`
3. Fill in the application name field `fill`
4. Fill in the authorization callback URL field `fill`
5. Submit the form to create the app (Create app button) `click`
6. Capture only the newly created credential with plain browser code (never a model) and store it outside the repo. `capture`
7. Live test: client-credentials token request, then GET /api/me `verify`

## Facts
**Sourced**
- (none)

**Observed**
- Fakeprov is a local test site; this plan stands in for research.

**Inferred**
- (none)

**Unknown**
- (none)

**Unknowns**
- (none)

## Corrections made by code to the model's plan
- (none)

## Expected blockers
- sign_in: the console may require sign-in
- terms: creating an app may require accepting terms

## Handoffs
- DECIDE (cancelled): Assessed as irreversible (risk uncertain, assumed one level higher). The agent will not do this unless you say so.
- DECIDE (completed): Assessed as irreversible (risk uncertain, assumed one level higher). The agent will not do this unless you say so. → answer: Yes, do it

## Blockers
- (none)

## Verification
- Procedure: OAuth client-credentials token request (RFC 6749 §4.4) at http://127.0.0.1:56485/oauth/token
- Observed: HTTP 200: the provider issued an access token for this client ID and secret
- Production limitations: none recorded

## Next steps
- Nothing further.

## Untested
- (none)

## Cleanup
- See handoffs and steps for anything created at the provider.

## Sources
How much the model saw: 0 search snippet(s) only (pages never opened), 0 page(s) read in full, 0 long page(s) read partially (sections most relevant to credentials). A sourced fact is kept only if its quote appears in that text.

- (none)

```
