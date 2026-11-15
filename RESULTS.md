# RESULTS

Every real-provider run used in the demo or README is listed here, including
failures, blocked runs and untested items. Fake-provider test runs are not
listed here; they are covered by the test suite.

A credential counts as working only if its live test passed (`verified`).

## Real-provider runs

_None yet._ No real provider has been contacted. Real runs need the owner's
explicit consent for each provider and an approved `docs/ATTEMPT-PROTOCOL.md`.

| # | Date | App | Access path | Predicted | Actual outcome | Verification | Human steps | Notes |
|---|------|-----|-------------|-----------|----------------|--------------|-------------|-------|

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
| 2026-11-15 | GitHub | 20261115-153458-github-9cfb | planned | adds weak-source tags; sample in docs/samples/plan-github.md |

No credential was obtained or tested in any of these runs.

## Untested

- Browser execution, credential capture and live verification against any real provider (Sprint 3+).
