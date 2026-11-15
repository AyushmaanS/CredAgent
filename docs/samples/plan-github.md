# CredAgent report — GitHub

Run `20261115-153458-github-9cfb` · provider: GitHub · created 2026-11-15T15:34:58+00:00

## Outcome
- **Status:** running (phase: planned) — Paused after planning: browser execution is not available in this version yet (Sprint 3).
- **Predicted:** succeeded · **Actual:** not finished
- **Credential:** not captured
- **Verification:** `untested` — only `verified` counts as working

## What happened
- Agent actions: 2 · Person actions: 0 · System: 0
- [agent] research (3 searches, 4 pages read) → done
- [agent] plan created → done

## Plan
- Credential type: oauth_client
- Alternatives found: other: GitHub App: uses OAuth 2.0 with fine-grained permissions and short-lived tokens. It can act on behalf of a user or independently, and issues installation access tokens.; token: Personal access token, either fine-grained (github_pat_) or classic (ghp_). Used to call the REST API for personal use.; token: Built-in GITHUB_TOKEN for GitHub Actions workflows. It can only access resources in the repository that contains the workflow.
- Console: https://github.com/settings/applications/new
- Allowed domains: github.com, docs.github.com, github.blog
- Redirect URI needed: yes · Dynamic registration: not_documented

1. Sign in to github.com. This is a human handoff; complete any 2FA or device verification prompt. `handoff`
2. Click your profile picture (upper right), then Settings, then Developer settings, then OAuth apps. Or go directly to https://github.com/settings/applications/new. `navigate`
3. Click New OAuth App. If you haven't created an app before, the button says 'Register a new application'. `click`
4. Fill in Application name, Homepage URL and an optional description. Use only information you consider public. `fill`
5. Enter the Authorization callback URL (up to 10 are allowed, added with 'Add callback URL'). `fill`
6. Optionally tick Enable Device Flow if the app is headless. Leave 'Expire user access tokens' checked unless the app's code doesn't yet support refresh tokens. `click`
7. Click Register application. GitHub may ask to re-confirm the password (sudo mode); treat that as a handoff to the user. `click`
8. Capture only the newly created credential with plain browser code (never a model) and store it outside the repo. Research notes: Copy the Client ID, then generate a client secret and copy it immediately. The secret is typically shown only once. (inferred) `capture`
9. Live test: Run the web application flow against the registered callback: authorize with client_id, then POST the returned code with client_id and client_secret to the token endpoint. A returned access_token proves the secret works. Optionally call GET https://api.github.com/user with that token as a 'who am I' check. Research notes: Verify by running the web flow against your callback and exchanging the code for an access token at https://github.com/login/oauth/access_token with the client ID and secret. `verify`

## Facts
**Sourced**
- OAuth apps can be registered under a personal account or any organization where the user is an admin. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app))
  > "You can create and register an OAuth app under your personal account or under any organization you have administrative access to."
- A user or organization can own up to 100 OAuth apps. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app))
  > "A user or organization can own up to 100 OAuth apps."
- Up to 10 callback URLs can be entered, so a redirect/callback URL is required. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app))
  > "You can enter up to 10 callback URLs."
- GitHub recommends considering a GitHub App instead of an OAuth app. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app))
  > "Consider building a GitHub App instead of an OAuth app."
- The registration page for a new OAuth app is https://github.com/settings/applications/new. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps))
  > "The client ID you received from GitHub when you [registered](https://github.com/settings/applications/new)."
- The token exchange endpoint is POST https://github.com/login/oauth/access_token and requires client_id, client_secret and code. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps))
  > "POST https://github.com/login/oauth/access_token"
- GitHub recommends fine-grained personal access tokens over classic ones for API access. ([source](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github))
  > "If possible, GitHub recommends that you use a fine-grained personal access token instead of a personal access token (classic)."
- Account passwords are no longer accepted for REST API authentication; tokens are required. [code: search snippet only] ([source](https://github.blog/news-insights/company-news/token-authentication-requirements-for-api-and-git-operations))
  > "we will no longer accept account passwords when authenticating via the REST API"

**Observed**
- (none)

**Inferred**
- The client secret is likely shown only once after generation, so it must be captured immediately.
- Identified as GitHub by GitHub (confidence: high).
- Chosen credential: oauth_client. GitHub offers third-party OAuth apps, which give a client ID and secret that users authorize. This matches the goal of bringing your own OAuth app. A GitHub App is GitHub's recommended alternative if fine-grained permissions are needed.

**Unknown**
- GitHub publishes no OAuth authorization-server metadata URL or open dynamic client registration in the provided sources.

**Unknowns**
- Whether the signed-in account will hit 2FA, device verification or sudo-mode password re-confirmation, to be observed in the browser.
- Whether the target organization (if any) restricts OAuth app creation or requires SAML SSO authorization.
- The exact client secret generation UI on the app settings page; the provided sources do not describe it officially.
- Whether GitHub publishes an OAuth authorization-server metadata document or supports dynamic client registration.

## Corrections made by code to the model's plan
- 2 model-written capture/verify step(s) folded into the code-owned capture and live-test steps (only the credential being created is captured).
- 3 other credential type(s) found; choosing between credential types is the person's decision (DECIDE) before the browser starts.

## Expected blockers
- sign_in: A GitHub account is required to register an OAuth app, either under a personal account or under an organization where you are an admin. [sourced: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app]
- two_factor: Users who contribute code on GitHub.com must have 2FA enabled, so the sign-in may ask for a 2FA code or new-device verification. [sourced: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github]
- other: Each user or organization can own at most 100 OAuth apps. [sourced: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app]
- other: Organization-owned OAuth apps need org admin access. Organizations may also restrict third-party app access or require SAML SSO authorization. This is not covered in the provided sources. [inferred]

## Handoffs
- (none)

## Blockers
- (none)

## Verification
- Procedure: Run the web application flow against the registered callback: authorize with client_id, then POST the returned code with client_id and client_secret to the token endpoint. A returned access_token proves the secret works. Optionally call GET https://api.github.com/user with that token as a 'who am I' check. — endpoint https://github.com/login/oauth/access_token
- Observed: not run
- Production limitations: none recorded

## Next steps
- [owner] Review the plan above. Browser execution is not available in this version yet (Sprint 3); the run is saved and can be resumed then: credagent resume 20261115-153458-github-9cfb

## Untested
- Browser execution (not available yet)
- Credential capture
- Live credential test

## Cleanup
- Nothing was created at the provider (no browser actions were taken).

## Sources
How much the model saw: 13 search snippet(s) only (pages never opened), 1 page(s) read in full, 3 long page(s) read partially (sections most relevant to credentials). A sourced fact is kept only if its quote appears in that text.

- [Token authentication requirements for API and Git operations - The GitHub Blog](https://github.blog/news-insights/company-news/token-authentication-requirements-for-api-and-git-operations) — snippet only: 700 of 1,048 chars of the search excerpt; page not opened
- [About authentication to GitHub - GitHub Docs](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github) — snippet only: 700 of 1,252 chars of the search excerpt; page not opened
- [Authorizing OAuth apps - GitHub Docs](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps) — snippet only: 700 of 1,102 chars of the search excerpt; page not opened
- [Mastering the GitHub API: REST, GraphQL, Automation, and Collaboration](https://blog.namespacecomm.in/github-api-demystified-a-developers-handbook) — snippet only: 700 of 1,082 chars of the search excerpt; page not opened
- [Getting started with the REST API - GitHub Docs](https://docs.github.com/rest/using-the-rest-api/getting-started-with-the-rest-api) — snippet only: 700 of 1,274 chars of the search excerpt; page not opened
- [How to create GitHub OAuth App (client ID and client secret)](https://www.youtube.com/watch?v=R9lxXQcy-nM) — snippet only: 700 of 1,446 chars of the search excerpt; page not opened
- [How to Configure GitHub OAuth Authentication in DreamFactory: Complete Setup Guide](https://www.linkedin.com/pulse/how-configure-github-oauth-authentication-dreamfactory-yai7c) — snippet only: 700 of 1,335 chars of the search excerpt; page not opened
- [Generate API Key · Actions · GitHub Marketplace · GitHub](https://github.com/marketplace/actions/generate-api-key) — snippet only: 700 of 1,237 chars of the search excerpt; page not opened
- [Configure Github as the OAuth 2.0 provider - Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/684068/configure-github-as-the-oauth-2-0-provider) — snippet only: 700 of 1,122 chars of the search excerpt; page not opened
- [Creating an OAuth app - GitHub Docs](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app) — snippet only: 700 of 1,187 chars of the search excerpt; page not opened
- [GitHub REST API documentation - GitHub Docs](https://docs.github.com/en/rest) — snippet only: 700 of 1,431 chars of the search excerpt; page not opened
- [mattermost-api-reference/v4/source/introduction.yaml at master · mattermost/mattermost-api-reference · GitHub](https://github.com/mattermost/mattermost-api-reference/blob/master/v4/source/introduction.yaml) — snippet only: 700 of 1,260 chars of the search excerpt; page not opened
- [REST API endpoints for repositories - GitHub Docs](https://docs.github.com/rest/repos) — snippet only: 700 of 1,248 chars of the search excerpt; page not opened
- [https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app) — read in full (2,704 chars)
- [https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps) — read 12,000 of 29,474 chars: 7 of 28 sections, chosen for relevance to credentials
- [https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github) — read 11,687 of 16,534 chars: 13 of 18 sections, chosen for relevance to credentials
- [https://docs.github.com/rest/using-the-rest-api/getting-started-with-the-rest-api](https://docs.github.com/rest/using-the-rest-api/getting-started-with-the-rest-api) — read 11,962 of 72,367 chars: 7 of 62 sections, chosen for relevance to credentials

