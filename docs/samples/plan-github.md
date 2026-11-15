# CredAgent report — GitHub

Run `20261115-154416-github-9a98` · provider: GitHub (Microsoft) · created 2026-11-15T15:44:16+00:00

## Outcome
- **Status:** running (phase: planned) — Paused after planning: browser execution is not available in this version yet (Sprint 3).
- **Predicted:** succeeded · **Actual:** not finished
- **Credential:** not captured
- **Verification:** `untested` — only `verified` counts as working

## What happened
- Agent actions: 2 · Person actions: 0 · System: 0
- [agent] research (7 searches, 6 pages read) → done
- [agent] plan created → done

## Plan
- Credential type: oauth_client
- Alternatives found: token: Personal access token, either fine-grained (recommended) or classic. It is created in Settings > Developer settings.; token: Built-in GITHUB_TOKEN inside GitHub Actions workflows. It can only access resources in the workflow's repository.
- Console: https://github.com/settings/applications/new
- Allowed domains: github.com, docs.github.com, github.blog
- Redirect URI needed: yes · Dynamic registration: not_documented

1. Sign in to github.com (account creation, email verification and 2FA if needed) and accept any terms prompts. The user does this themselves. `handoff`
2. Open Settings > Developer settings > OAuth apps (https://github.com/settings/applications/new opens the registration form directly). To register under an organization, use that organization's settings, which requires administrative access. `navigate`
3. Click 'New OAuth App' (or 'Register a new application' if no app exists yet). `click`
4. Fill in Application name, Homepage URL and an optional description, using only information that is public. `fill`
5. Enter the Authorization callback URL (up to 10 can be added via 'Add callback URL'). This must be the integration's redirect URI. `fill`
6. Tick 'Enable Device Flow' only if the app will use the device flow. Leave 'Expire user access tokens' enabled unless the app cannot handle refresh tokens yet. `click`
7. Click 'Register application'. `click`
8. Capture only the newly created credential with plain browser code (never a model) and store it outside the repo. Research notes: On the app settings page, copy the Client ID, then click 'Generate a new client secret' and copy the secret immediately. Third-party guides say the secret is shown only once. `capture`
9. Live test: Send a token-exchange request with the client ID, client secret and a deliberately invalid code. The response error type shows whether GitHub recognizes the client. No user authorization is required. A stronger check is to run the full web or device flow and then call GET https://api.github.com/user with the resulting token. Research notes: Run the verification request (see the verification section) with the captured client ID and secret. (inferred) `verify`

## Facts
**Sourced**
- OAuth apps can be registered under a personal account or an organization where the user has admin access. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app))
  > "You can create and register an OAuth app under your personal account or under any organization you have administrative access to."
- GitHub recommends considering a GitHub App over an OAuth app. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/differences-between-github-apps-and-oauth-apps))
  > "In general, GitHub Apps are preferred over OAuth apps."
- A user or organization can own up to 100 OAuth apps. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app))
  > "A user or organization can own up to 100 OAuth apps."
- Up to 10 callback URLs can be registered. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app))
  > "You can enter up to 10 callback URLs."
- The registration form link is https://github.com/settings/applications/new. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps))
  > "The client ID you received from GitHub when you [registered](https://github.com/settings/applications/new)."
- The authorization code is exchanged for a token at https://github.com/login/oauth/access_token. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps))
  > "POST https://github.com/login/oauth/access_token"
- The authorization endpoint is https://github.com/login/oauth/authorize. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps))
  > "GET https://github.com/login/oauth/authorize"
- Client secrets (for GitHub Apps, per community answers) do not expire automatically and are shown only once at creation. Multiple secrets can be active. ([source](https://github.com/orgs/community/discussions/187781))
  > "GitHub App client secrets do not expire automatically."

**Observed**
- (none)

**Inferred**
- GitHub's OAuth implementation supports the authorization code grant and the device authorization grant. The implicit grant is not supported.
- A bad-code token exchange distinguishes recognized from unrecognized client credentials. This is based on general knowledge and is not documented in the sources.
- Identified as GitHub by GitHub (Microsoft) (confidence: high).
- Chosen credential: oauth_client. The task is to bring your own OAuth app, and GitHub offers third-party OAuth apps that give a client ID and secret through a simple form. GitHub says a GitHub App is generally preferred, so that is a reasonable alternative if fine-grained permissions or bot behavior are needed. An OAuth app is the straightforward match for a user-delegated OAuth client.

**Unknown**
- Open dynamic client registration and an OAuth authorization-server metadata URL are not documented in the provided sources.

**Unknowns**
- Whether the signed-in account is prompted for 2FA, a device verification code or a CAPTCHA when signing in.
- Whether the target organization has OAuth app access restrictions or requires an owner to approve the app.
- Whether the app will be created under a personal account or an organization.
- The exact error responses to the verification token-exchange request, which are not shown in the sources.
- Whether GitHub publishes OAuth authorization-server metadata (an RFC 8414 URL) or dynamic client registration. The sources do not cover this.

## Corrections made by code to the model's plan
- 2 model-written capture/verify step(s) folded into the code-owned capture and live-test steps (only the credential being created is captured).
- The proposed live test only proves the client ID is recognised; a pass would be labelled client_recognized, which is not 'working' and cannot give 'succeeded'.
- 1 sourced claim(s) downgraded: the quote was missing or not found in the text the model was shown for the cited source.
- 2 other credential type(s) found; choosing between credential types is the person's decision (DECIDE) before the browser starts.

## Expected blockers
- sign_in: A GitHub account must be signed in to register an OAuth app. This is a user handoff. [inferred]
- two_factor: GitHub requires 2FA for users who contribute code, and may ask for device verification on new devices. Sign-in may therefore need a 2FA code or a device verification code. [sourced: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github]
- other: To register the app under an organization, the user needs administrative access to that organization. Organization application policies may also require an owner to approve the OAuth app later. [sourced: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app]

## Handoffs
- (none)

## Blockers
- (none)

## Verification
- Procedure: Send a token-exchange request with the client ID, client secret and a deliberately invalid code. The response error type shows whether GitHub recognizes the client. No user authorization is required. A stronger check is to run the full web or device flow and then call GET https://api.github.com/user with the resulting token. — endpoint POST https://github.com/login/oauth/access_token (a pass = client_recognized only)
- Observed: not run
- Production limitations: none recorded

## Next steps
- [owner] Review the plan above. Browser execution is not available in this version yet (Sprint 3); the run is saved and can be resumed then: credagent resume 20261115-154416-github-9a98

## Untested
- Browser execution (not available yet)
- Credential capture
- Live credential test

## Cleanup
- Nothing was created at the provider (no browser actions were taken).

## Sources
How much the model saw: 31 search snippet(s) only (pages never opened), 2 page(s) read in full, 4 long page(s) read partially (sections most relevant to credentials). A sourced fact is kept only if its quote appears in that text.

- [Differences between GitHub Apps and OAuth apps - GitHub Docs](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/differences-between-github-apps-and-oauth-apps) — snippet only: 700 of 1,248 chars of the search excerpt; page not opened
- [Does a GitHub App "Client Secret" ever expire? · community · Discussion #187781 · GitHub](https://github.com/orgs/community/discussions/187781) — snippet only: 700 of 1,500 chars of the search excerpt; page not opened
- [Deciding when to build a GitHub App - GitHub Docs](https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/deciding-when-to-build-a-github-app) — snippet only: 700 of 1,356 chars of the search excerpt; page not opened
- [PAT vs oAuth vs GitHub App · community · Discussion #109668 · GitHub](https://github.com/orgs/community/discussions/109668) — snippet only: 700 of 1,506 chars of the search excerpt; page not opened
- [GitHub App vs. GitHub OAuth: When to Use Which? | Nango Blog](https://nango.dev/blog/github-app-vs-github-oauth) — snippet only: 700 of 1,348 chars of the search excerpt; page not opened
- [Token authentication requirements for API and Git operations - The GitHub Blog](https://github.blog/news-insights/company-news/token-authentication-requirements-for-api-and-git-operations) — snippet only: 700 of 1,048 chars of the search excerpt; page not opened
- [Fine-grained Personal Access Token permissions · community · Discussion #133558 · GitHub](https://github.com/orgs/community/discussions/133558) — snippet only: 700 of 1,488 chars of the search excerpt; page not opened
- [Managing your personal access tokens - GitHub Docs](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) — snippet only: 700 of 1,340 chars of the search excerpt; page not opened
- [About authentication to GitHub - GitHub Docs](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github) — snippet only: 700 of 1,252 chars of the search excerpt; page not opened
- [Permissions required for fine-grained personal access tokens - GitHub Docs](https://docs.github.com/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens) — snippet only: 700 of 999 chars of the search excerpt; page not opened
- [Authorizing OAuth apps - GitHub Docs](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps) — snippet only: 700 of 1,102 chars of the search excerpt; page not opened
- [Support for client secret rotation · ory/hydra · Discussion #3005 · GitHub](https://github.com/ory/hydra/discussions/3005) — snippet only: 700 of 1,401 chars of the search excerpt; page not opened
- [Mastering the GitHub API: REST, GraphQL, Automation, and Collaboration](https://blog.namespacecomm.in/github-api-demystified-a-developers-handbook) — snippet only: 700 of 1,082 chars of the search excerpt; page not opened
- [Getting started with the REST API - GitHub Docs](https://docs.github.com/rest/using-the-rest-api/getting-started-with-the-rest-api) — snippet only: 700 of 1,274 chars of the search excerpt; page not opened
- [How to create GitHub OAuth App (client ID and client secret)](https://www.youtube.com/watch?v=R9lxXQcy-nM) — snippet only: 700 of 1,446 chars of the search excerpt; page not opened
- [How to Configure GitHub OAuth Authentication in DreamFactory: Complete Setup Guide](https://www.linkedin.com/pulse/how-configure-github-oauth-authentication-dreamfactory-yai7c) — snippet only: 700 of 1,335 chars of the search excerpt; page not opened
- [Generate API Key · Actions · GitHub Marketplace · GitHub](https://github.com/marketplace/actions/generate-api-key) — snippet only: 700 of 1,237 chars of the search excerpt; page not opened
- [Building a "Login with GitHub" button with a GitHub App - GitHub Enterprise Cloud Docs](https://docs.github.com/enterprise-cloud@latest/apps/creating-github-apps/writing-code-for-a-github-app/building-a-login-with-github-button-with-a-github-app) — snippet only: 700 of 1,212 chars of the search excerpt; page not opened
- [Scopes for OAuth apps - GitHub Docs](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps) — snippet only: 700 of 1,171 chars of the search excerpt; page not opened
- [Configure Github as the OAuth 2.0 provider - Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/684068/configure-github-as-the-oauth-2-0-provider) — snippet only: 700 of 1,122 chars of the search excerpt; page not opened
- [Authenticating to the REST API with an OAuth app - GitHub Docs](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authenticating-to-the-rest-api-with-an-oauth-app) — snippet only: 700 of 1,224 chars of the search excerpt; page not opened
- [Creating an OAuth app - GitHub Docs](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app) — snippet only: 700 of 1,187 chars of the search excerpt; page not opened
- [GitHub REST API documentation - GitHub Docs](https://docs.github.com/en/rest) — snippet only: 700 of 1,431 chars of the search excerpt; page not opened
- [Fine-grained personal access tokens | GitLab Docs](https://docs.gitlab.com/auth/tokens/fine_grained_access_tokens) — snippet only: 700 of 1,256 chars of the search excerpt; page not opened
- [Amazon Has Secret Workaround to Scrape GitHub for AI Training Data - Business Insider](https://www.businessinsider.com/amazon-secret-workaround-scrape-microsoft-github-ai-training-data-2024-6) — snippet only: 700 of 893 chars of the search excerpt; page not opened

