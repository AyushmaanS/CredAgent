# CredAgent report — GitHub

Run `20261115-143914-github-7436` · provider: GitHub · created 2026-11-15T14:39:14+00:00

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
- Alternatives found: other: GitHub App: GitHub recommends it over OAuth apps. It uses fine-grained permissions and short-lived tokens, and it can act on behalf of a user or independently of one. Registration steps are not covered in the sources provided.; token: Fine-grained personal access token. It is limited to one resource owner, can be limited to selected repositories, and carries specific permissions. Organization owners can require approval. It has documented feature gaps and a limit of 50 per user.; token: Personal access token (classic). It is less secure and uses broad scopes. Some features and endpoints work only with classic tokens.
- Console: https://github.com/settings/applications/new
- Allowed domains: github.com, docs.github.com
- Redirect URI needed: yes · Dynamic registration: not_documented

1. Sign in to GitHub. This may involve a password, 2FA, or other verification that the user must complete themselves. (inferred) `handoff`
2. Open the OAuth app registration page (https://github.com/settings/applications/new), or reach it via profile picture > Settings > Developer settings > OAuth apps > New OAuth App. The button reads 'Register a new application' if no app exists yet. `navigate`
3. Enter the application name and the full homepage URL. Use only information you consider public. Optionally add an application description. `fill`
4. Enter the Authorization callback URL (up to 10 are allowed, via 'Add callback URL'). `fill`
5. Optionally tick 'Enable Device Flow' if the app will use the device flow. Leave 'Expire user access tokens' at its default (enabled), or untick it if the app can't yet handle refresh tokens. `click`
6. Click 'Register application'. `click`
7. Capture only the newly created credential with plain browser code (never a model) and store it outside the repo. Research notes: Copy the Client ID from the app settings page. Generate a client secret and copy it immediately, because it is shown only once (per a third-party source). `capture`
8. Live test: Complete the web application flow: exchange the authorization code at the token endpoint with client_id and client_secret (Accept: application/json), then call the authenticated 'who am I' endpoint with the returned token. This needs a user to authorize the app once. Research notes: Verify the credential by running the web flow: redirect to https://github.com/login/oauth/authorize, exchange the code at https://github.com/login/oauth/access_token with the client secret, then call GET https://api.github.com/user with the token. `verify`

## Facts
**Sourced**
- OAuth apps can be created and registered under a personal account or any organization you have administrative access to. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app))
- Path to registration: Settings > Developer settings > OAuth apps > New OAuth App. Required fields are the application name, homepage URL, and authorization callback URL (up to 10 allowed). ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app))
- The registration page is linked at https://github.com/settings/applications/new. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps))
- GitHub recommends considering a GitHub App instead of an OAuth app. OAuth apps can only act on behalf of a user. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app))
- The authorize endpoint is https://github.com/login/oauth/authorize and the token endpoint is https://github.com/login/oauth/access_token. The authorization code expires after 10 minutes. PKCE (S256) is supported and the implicit grant is not. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps))
- Expiring tokens: the access token lasts 8 hours and the refresh token expires after 6 months without use. The 'Expire user access tokens' option is enabled by default. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps))
- GET https://api.github.com/user with 'Authorization: Bearer <token>' is used to access the API and revalidate the user's identity. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps))
- The device flow must be enabled in the app's settings before it can be used. ([source](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps))
- Personal access tokens come in fine-grained and classic types. GitHub recommends fine-grained, and creating one requires a verified email address. ([source](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens))
- The client secret is displayed only once at generation, according to a third-party guide (not official docs). ([source](https://www.linkedin.com/pulse/how-configure-github-oauth-authentication-dreamfactory-yai7c))

**Observed**
- (none)

**Inferred**
- Registering an OAuth app likely requires no provider review, payment, or business verification, since the docs describe only self-service form steps.
- Identified as GitHub by GitHub (confidence: high).
- Chosen credential: oauth_client. GitHub offers third-party OAuth apps with a self-service client ID and secret, which matches the 'bring your own OAuth app' goal. The docs recommend GitHub Apps for some use cases, but the OAuth app is the straightforward OAuth client. A GitHub App or personal access token is an alternative for automation or personal use.

**Unknown**
- No OAuth authorization-server metadata URL (RFC 8414) or open dynamic client registration is documented in the provided sources.

**Unknowns**
- Whether GitHub prompts for 2FA, sudo-mode re-authentication, or additional verification during sign-in or secret generation.
- Exact UI labels for generating the client secret, since the provided pages are truncated before that step.
- Whether an OAuth authorization-server metadata endpoint or dynamic client registration exists. Neither is documented in the sources.
- Organization-level restrictions, such as OAuth app access policies, that might limit use of the app by organization members.
- Which scopes the specific integration needs. The scopes page was not among the provided sources.

## Corrections made by code to the model's plan
- 2 model-written capture/verify step(s) folded into the code-owned capture and live-test steps (only the credential being created is captured).
- 3 other credential type(s) found; choosing between credential types is the person's decision (DECIDE) before the browser starts.

## Expected blockers
- sign_in: A GitHub account is required to register an OAuth app under Settings > Developer settings. [sourced: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app]
- two_factor: The account may prompt for 2FA or sudo-mode re-authentication at sign-in or when creating secrets. The sources do not state this. [inferred]
- account_creation: If the user has no GitHub account, one must be created first. Personal access tokens additionally require a verified email address. [sourced: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens]
- other: To register the app under an organization, the user needs administrative access to that organization. Each user or organization can own up to 100 OAuth apps. [sourced: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app]
- terms: Standard GitHub terms may need to be accepted. The sources do not describe any specific terms gate for OAuth app registration. [inferred]

## Handoffs
- (none)

## Blockers
- (none)

## Verification
- Procedure: Complete the web application flow: exchange the authorization code at the token endpoint with client_id and client_secret (Accept: application/json), then call the authenticated 'who am I' endpoint with the returned token. This needs a user to authorize the app once. — endpoint GET https://api.github.com/user (Authorization: Bearer <token>), after POST https://github.com/login/oauth/access_token
- Observed: not run
- Production limitations: none recorded

## Next steps
- [owner] Review the plan above. Browser execution is not available in this version yet (Sprint 3); the run is saved and can be resumed then: credagent resume 20261115-143914-github-7436

## Untested
- Browser execution (not available yet)
- Credential capture
- Live credential test

## Cleanup
- Nothing was created at the provider (no browser actions were taken).

## Sources
- [GitHub API Requires Authentication: The Five Causes of the 401, in the Order to Check Them](https://www.runxbuild.com/blog/github-api-requires-authentication) (search)
- [Authorizing OAuth apps - GitHub Docs](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps) (search)
- [Mastering the GitHub API: REST, GraphQL, Automation, and Collaboration](https://blog.namespacecomm.in/github-api-demystified-a-developers-handbook) (search)
- [Getting started with the REST API - GitHub Docs](https://docs.github.com/rest/using-the-rest-api/getting-started-with-the-rest-api) (search)
- [How to create GitHub OAuth App (client ID and client secret)](https://www.youtube.com/watch?v=R9lxXQcy-nM) (search)
- [How to Configure GitHub OAuth Authentication in DreamFactory: Complete Setup Guide](https://www.linkedin.com/pulse/how-configure-github-oauth-authentication-dreamfactory-yai7c) (search)
- [Generate API Key · Actions · GitHub Marketplace · GitHub](https://github.com/marketplace/actions/generate-api-key) (search)
- [Configure Github as the OAuth 2.0 provider - Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/684068/configure-github-as-the-oauth-2-0-provider) (search)
- [Managing your personal access tokens - GitHub Docs](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) (search)
- [Creating an OAuth app - GitHub Docs](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app) (search)
- [GitHub REST API documentation - GitHub Docs](https://docs.github.com/en/rest) (search)
- [mattermost-api-reference/v4/source/introduction.yaml at master · mattermost/mattermost-api-reference · GitHub](https://github.com/mattermost/mattermost-api-reference/blob/master/v4/source/introduction.yaml) (search)
- [REST API endpoints for repositories - GitHub Docs](https://docs.github.com/rest/repos) (search)
- [https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app) (extract)
- [https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps) (extract)
- [https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) (extract)
- [https://docs.github.com/en/rest](https://docs.github.com/en/rest) (extract)

