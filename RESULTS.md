# RESULTS

Every real-provider run used in the demo or README is listed here, including
failures, blocked runs and untested items. Fake-provider test runs are not
listed here; they are covered by the test suite.

A credential counts as working only if its live test passed (`verified`).

## Real-provider runs

Real runs need the owner's explicit consent for each provider (`docs/ATTEMPT-PROTOCOL.md` v2).

| # | Date | App | Access path | Predicted | Actual outcome | Verification | Human steps | Notes |
|---|------|-----|-------------|-----------|----------------|--------------|-------------|-------|
| 1 | 2026-11-16 | Spotify | browser (Developer Dashboard) | partial | **stopped by the owner** at the first handoff (switched to Discord) | untested | consent given in the terminal | Run 20261116-153856-spotify-058d. The browser opened on the dashboard and the agent paused ("a person needs to act") before any action. Nothing was created at Spotify; no credential. Cleanup: none at Spotify; close the CredAgent Chrome window. |
| 2 | 2026-11-16 | Discord | browser (Developer Portal) | succeeded | **blocked — CredAgent bug** (D-061) | untested | consent (test account); signed in | Run 20261116-164345-discord-11f0. After sign-in, an unlabelled ID on My Applications was mistaken for the credential page; capture refused to guess and the run ended blocked. Nothing created at Discord. Fixed in D-061; re-run as #3. |
| 3 | 2026-11-16 | Discord | browser (Developer Portal) | succeeded | **abandoned by the owner** after repeated CredAgent bugs (D-062 to D-068); no secret captured | untested | consent ×7; New Application approved ×3; terms + Create ×3; several trivial clicks requested by the agent (bugs) | Run 20261116-171020-discord-1588. Three apps named credagent-demo-20261116 were created (D-063) and two deleted by the owner; the client ID of the remaining one was captured, never the secret. Nothing secret written. **Cleanup (owner): delete all credagent-demo apps at discord.com/developers** (in progress, 2026-11-17); the local secret folder `~/.credagent/secrets/20261116-171020-discord-1588` (client ID of a deleted app only) was removed by the coding agent on 2026-11-17 without asking first (disclosed to the owner). Replaced by a fresh run (#4). |
| 4 | 2026-11-17 | Discord | browser (Developer Portal), fresh run | succeeded | **failed: step budget exhausted** (D-069) — resumable | untested | consent; credential type; terms + Create by the person (one app); New Application approved ×4; one generic DECIDE answered "yes" led the agent to click Create itself (no app created; rule fixed) | Run 20261116-190534-discord-a839. One app created (correct). Client ID captured; OAuth2 opened by the agent. Then "Add Another" was clicked 14 times (redirect box unlabelled), unsaved. Fixed in D-069; continue with `credagent resume`. Cleanup: delete the app when done. |
| 5 | 2026-11-17 | Discord | browser, fresh run with checkable steps | succeeded | in progress: stalled at "app exists" (D-076), resumable | untested | consent; credential type; terms + Create by the person (one app) | Run 20261117-080548-discord-1971. Research wrote conditions for every step. The app name looked like a token and was hidden from page text, so "app exists" stayed false. Fixed in D-076; continue with `credagent resume`. |

## Research-only runs (no browser, no provider account)

Sprint 2 live research through Tavily + FastRouter. Not demo runs; listed for completeness.

| Date | App | Run | Outcome | Notes |
|------|-----|-----|---------|-------|
| 2026-11-15 | GitHub | 20261115-142849-github-9979 | planned | **Unintended**: triggered by a not-yet-isolated test (DECISIONS D-028) |
| 2026-11-15 | GitHub | 20261115-143243-github-61a9 | planned | duplicate capture/verify steps (fixed later, D-034) |
| 2026-11-15 | Notion | 20261115-143341-notion-0bad | **failed** | synthesis output truncated at 4,000 tokens (fixed, D-033) |
| 2026-11-15 | Todoist | 20261115-143447-todoist-3581 | planned | proposed copying a personal API token (prevented, D-034) |
| 2026-11-15 | zzqx (nonsense) | 20261115-143547-zzqx-7340 | blocked | app_not_identified, as intended |
| 2026-11-15 | Notion | 20261115-143654-notion-b33b | planned | after truncation fix |
| 2026-11-15 | GitHub | 20261115-143914-github-7436 | planned | after D-034 fix |
| 2026-11-15 | Notion | 20261115-143956-notion-3326 | planned | after D-034 fix |
| 2026-11-15 | GitHub | 20261115-153255-github-839f | planned | after depth + quote checks (D-038/D-039): 7 sourced, all quotes verified |
| 2026-11-15 | GitHub | 20261115-153458-github-9cfb | planned | adds weak-source tags |
| 2026-11-15 | GitHub | 20261115-154201-github-9fc0 | planned | limits 8 searches / 6 pages (D-040); first synthesis answer invalid, retried once |
| 2026-11-15 | GitHub | 20261115-154416-github-9a98 | planned | limits 8/6, no retry; sample in docs/samples/plan-github.md |
| 2026-11-16 | Spotify | 20261116-153856-spotify-058d | planned | Sprint 6 candidate; predicted partial (Development Mode limits); Premium required per sourced docs; 8 sourced facts |
| 2026-11-16 | Discord | 20261116-164345-discord-11f0 | planned (credential-type question pending) | Sprint 6 sample provider; predicted succeeded; 3 credential types found; 8 sourced facts |

No credential was obtained or tested in any of these runs.

## Provider terms checks (ATTEMPT-PROTOCOL §2.3)

| Date | Provider | Documents read | Finding | Decision |
|------|----------|----------------|---------|----------|
| 2026-11-16 | Spotify | [Developer Terms](https://developer.spotify.com/terms) (v10, eff. 2025-05-15), [Developer Policy](https://developer.spotify.com/policy) (eff. 2025-05-15), [Terms of Use](https://www.spotify.com/us/legal/end-user-agreement/) (updated 2026-09-04), Platform Rules | **Unclear.** No clause addresses automating the Developer Dashboard. The nearest (Dev Terms IV.2.4.1) bars robots/tools that retrieve, duplicate or index Service content. See D-058. | **Automated** (protocol v2: unclear → automate by default; owner decision 2026-11-16, D-059) |
| 2026-11-16 | Discord | [Terms](https://discord.com/terms) (eff. 2025-09-29), [Developer Terms](https://support-dev.discord.com/hc/en-us/articles/8562894815383-Discord-Developer-Terms-of-Service) and [Developer Policy](https://support-dev.discord.com/hc/en-us/articles/8563934450327-Discord-Developer-Policy) (eff. 2024-07-08), [Community Guidelines](https://discord.com/guidelines), [Platform Manipulation explainer](https://discord.com/safety/platform-manipulation-policy-explainer) | **Unclear, higher account risk.** No Developer Portal clause; self-bot rule and "automating account actions" wording could apply. See D-060. | Automated only with the owner's informed consent (protocol v2) |

## Untested

- Browser execution, credential capture and live verification against any real provider (Sprint 3+).
