# GitHub Application configuration for Ghillie

Ghillie accesses GitHub to ingest repository activity for status reporting.
This document explains how to create and configure a GitHub App with the
minimal permissions required for Ghillie's read-only operations.

## Quick start: required permissions at a glance

For operators who need the minimal configuration without reading the full
document, the following table summarizes the required GitHub App permissions:

| Category     | Permission    | Access level         |
| ------------ | ------------- | -------------------- |
| Repository   | Metadata      | Read-only            |
| Repository   | Contents      | Read-only            |
| Repository   | Issues        | Read-only            |
| Repository   | Pull requests | Read-only            |
| Organisation | Members       | Read-only (optional) |

**Installation scope:** Install on all repositories that Ghillie should
monitor, or use organisation-wide installation with selective repository access.

**Environment variable:** Set `GHILLIE_GITHUB_TOKEN` to the installation access
token (not the private key).

For detailed configuration steps, continue reading the sections below.

## Why use a GitHub App

GitHub Apps offer several advantages over Personal Access Tokens (PATs) for
production deployments:

- **Scoped permissions:** Apps request only the permissions they need, reducing
  the blast radius if credentials are compromised.
- **Installation-level access:** Permissions are granted per organisation or
  repository, not tied to individual user accounts.
- **Automatic token rotation:** Installation access tokens expire after one
  hour, limiting exposure from leaked credentials.
- **Audit trail:** GitHub logs all App activity separately from user actions,
  simplifying compliance and security reviews.
- **Organisational control:** Administrators can review, approve, and revoke App
  installations without affecting developer accounts.

Ghillie operates in a strictly read-only mode. It never modifies repository
content, settings, or workflows. The GitHub App configuration reflects this
constraint by requesting only the permissions necessary to observe repository
metadata, pull requests, issues, and documentation paths.

## Prerequisites

Before creating a GitHub App for Ghillie, ensure the following prerequisites
are met:

- **Organisation administrator access** to create and install GitHub Apps, or
  the ability to request installation approval from an administrator.
- **A list of repositories** that Ghillie will monitor, either as an explicit
  allowlist or as membership in a catalogue configuration.
- **Documentation path patterns** for each project (for example, `docs/**`,
  `ROADMAP.md`, `adr/**`) so Ghillie can track roadmap and design document
  changes.

## Creating the GitHub App

### Step 1: Navigate to GitHub App settings

1. Sign in to GitHub as an organisation owner or administrator.
2. Navigate to the organisation settings page:
   `https://github.com/organizations/<org-name>/settings`
3. In the left sidebar, select **Developer settings** then **GitHub Apps**.
4. Click **New GitHub App**.

### Step 2: Configure App metadata

Fill in the basic information for the App:

| Field           | Recommended value                                                           |
| --------------- | --------------------------------------------------------------------------- |
| GitHub App name | `ghillie-status-reporter` (or include the organisation name for uniqueness) |
| Description     | Read-only status reporting for engineering estate monitoring                |
| Homepage URL    | The Ghillie deployment URL or internal documentation page                   |

Under **Identifying and authorizing users**, leave the defaults unless
user-level OAuth flows are required (Ghillie does not use them).

Under **Post installation**, leave the setup URL blank unless a custom
onboarding flow is required.

### Step 3: Configure webhook (optional)

Ghillie currently uses polling rather than webhooks for ingestion. Leave the
webhook URL blank and uncheck **Active** under the Webhook section.

If real-time ingestion is planned for the future, webhooks can be configured
later without recreating the App.

### Step 4: Configure repository permissions

Request only the permissions Ghillie requires. All permissions should be
**Read-only**.

| Permission    | Access level | Rationale                                                                                                 |
| ------------- | ------------ | --------------------------------------------------------------------------------------------------------- |
| Metadata      | Read-only    | Required for basic repository information (name, default branch, visibility)                              |
| Contents      | Read-only    | Required to read documentation paths such as roadmaps and ADRs; Ghillie does not access source code blobs |
| Issues        | Read-only    | Required to ingest issue metadata (titles, labels, states, timestamps)                                    |
| Pull requests | Read-only    | Required to ingest pull request metadata (titles, labels, states, branches)                               |

Do not request any other repository permissions. In particular, do not request:

- **Actions:** Ghillie does not interact with GitHub Actions workflows.
- **Administration:** Ghillie does not modify repository settings.
- **Checks:** Ghillie does not create or read check runs.
- **Deployments:** Ghillie does not track deployment status.
- **Environments:** Ghillie does not access deployment environments.
- **Secrets:** Ghillie never accesses repository secrets.
- **Webhooks:** Ghillie does not configure webhooks (even with incoming webhooks
  enabled, this permission is not required).

### Step 5: Configure organisation permissions (optional)

Organisation permissions are not required for basic Ghillie operation. To
attribute activity to organisation members in reports, request:

| Permission | Access level | Rationale                                                       |
| ---------- | ------------ | --------------------------------------------------------------- |
| Members    | Read-only    | Optional: enables author attribution by organisation membership |

Leave all other organisation permissions unselected.

### Step 6: Configure account permissions

Ghillie does not require any account-level permissions. Leave this section
empty.

### Step 7: Select where the App can be installed

Choose **Only on this account** to restrict installation to the current
organisation, or **Any account** if the App is intended to be shared across
multiple organisations.

For most deployments, **Only on this account** is appropriate.

### Step 8: Create the App

Click **Create GitHub App**. GitHub will display the new App's settings page.

### Step 9: Generate and secure the private key

1. On the App settings page, scroll to **Private keys**.
2. Click **Generate a private key**. GitHub will download a `.pem` file.
3. Store this private key securely in an approved secrets management system (for
   example, HashiCorp Vault, AWS Secrets Manager, or Azure Key Vault).
4. Never commit the private key to version control or store it in plain text.

Record the **App ID** displayed at the top of the App settings page. Both the
App ID and the private key are required to generate installation tokens.

## Installing the App on repositories

### Organisation-wide installation

1. Navigate to the App's public page:
   `https://github.com/apps/<app-name>`
2. Click **Install** or **Configure**.
3. Select the target organisation.
4. Choose **All repositories** to grant access to every repository, or **Only
   select repositories** to choose specific repositories.
5. Click **Install**.

### Per-repository installation

If **Only select repositories** was selected during installation, the
repository list can be modified at any time:

1. Navigate to the organisation settings.
2. Select **Installed GitHub Apps** in the left sidebar.
3. Click **Configure** next to the Ghillie App.
4. Add or remove repositories as needed.
5. Click **Save**.

### Verification

After installation, verify the App appears in each repository's settings:

1. Navigate to a repository Ghillie should monitor.
2. Go to **Settings** then **Integrations** (or **GitHub Apps** depending on the
   GitHub version).
3. Confirm the Ghillie App is listed with the expected permissions.

## Configuring Ghillie to use the GitHub App

Ghillie authenticates to GitHub using an installation access token. The process
for obtaining this token involves exchanging the App's credentials for a
short-lived token.

### Token exchange flow

For screen readers: The following sequence diagram shows how Ghillie obtains an
installation access token from GitHub.

```mermaid
sequenceDiagram
    participant G as Ghillie
    participant S as Secrets store
    participant GH as GitHub API

    Note over G: On startup or token expiry
    G->>S: Retrieve App private key
    S-->>G: Private key (PEM)
    G->>G: Generate JWT (App ID + private key)
    G->>GH: POST /app/installations/{id}/access_tokens
    GH-->>G: Installation access token (1hr TTL)
    Note over G: Use token for API calls
    G->>GH: GraphQL queries (Bearer token)
    GH-->>G: Repository data
```

### Environment variables

Ghillie reads the GitHub token from an environment variable:

| Variable               | Description                              | Example                                    |
| ---------------------- | ---------------------------------------- | ------------------------------------------ |
| `GHILLIE_GITHUB_TOKEN` | Installation access token for GitHub API | `ghs_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |

The token value should be an installation access token, not the App's private
key directly. Token exchange logic must be implemented externally, or use a
secrets manager that handles GitHub App authentication.

### Obtaining an installation access token

To exchange App credentials for an installation token:

1. **Generate a JSON Web Token (JWT)** signed with the App's private key:
   - Set the `iss` (issuer) claim to the App ID.
   - Set the `iat` (issued at) claim to the current time.
   - Set the `exp` (expiration) claim to no more than 10 minutes in the future.
   - Sign with the RS256 algorithm using the private key.

2. **Request an installation token** by calling the GitHub API:

   ```bash
   curl -X POST \
     -H "Authorization: Bearer <JWT>" \
     -H "Accept: application/vnd.github+json" \
     https://api.github.com/app/installations/<installation-id>/access_tokens
   ```

   Replace `<JWT>` with the generated token and `<installation-id>` with the
   App's installation ID (visible in the installation URL or via the API).

3. **Extract the token** from the response:

   ```json
   {
     "token": "ghs_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
     "expires_at": "2024-01-15T12:00:00Z"
   }
   ```

4. **Set the environment variable** before starting Ghillie:

   ```bash
   export GHILLIE_GITHUB_TOKEN="ghs_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
   ```

### Token refresh considerations

Installation access tokens expire after one hour. For long-running Ghillie
deployments, the token must be refreshed before expiry. Common approaches
include:

- **External token manager:** A sidecar process or cron job that refreshes the
  token and updates the environment or secrets store.
- **Secrets manager integration:** Services like HashiCorp Vault can
  automatically rotate GitHub App tokens using their secrets engine.
- **Application-level refresh:** Future versions of Ghillie may support direct
  App authentication with automatic token refresh (see Task 1.4.b in the
  roadmap).

For pilot deployments, manually refreshing the token before each ingestion run
is acceptable. For production, automate token refresh to avoid authentication
failures.

## Security considerations

### Private key storage

- Store the App's private key in an approved secrets management system.
- Restrict access to the private key to only the services that need it.
- Rotate the private key periodically by generating a new key in GitHub App
  settings, updating the secrets store, and then deleting the old key.
- Never log or expose the private key in error messages or debug output.

### Installation token handling

- Installation tokens are short-lived (one hour) and automatically limit
  exposure from credential leaks.
- Do not cache installation tokens beyond their expiry time.
- Avoid logging full token values; log only the first few characters if needed
  for debugging.

### Audit and monitoring

- GitHub logs all App API activity in the organisation's audit log.
- Monitor rate limit headers in API responses to detect unusual usage patterns.
- Set up alerts for authentication failures, which may indicate credential
  issues or permission changes.

### Network security

- Always use HTTPS for GitHub API calls (the default endpoint
  `https://api.github.com` enforces this).
- If operating behind a corporate proxy, ensure the proxy does not intercept or
  log sensitive headers.

## Permissions not granted

Ghillie deliberately excludes several permissions to minimise its access
footprint:

| Permission      | Reason excluded                                                     |
| --------------- | ------------------------------------------------------------------- |
| Contents: Write | Ghillie is strictly read-only; it never modifies repository content |
| Actions         | Ghillie does not interact with GitHub Actions                       |
| Administration  | Ghillie does not modify repository settings or access controls      |
| Checks          | Ghillie does not create or consume check run results                |
| Deployments     | Ghillie does not track deployment pipelines                         |
| Environments    | Ghillie does not access deployment environment secrets              |
| Packages        | Ghillie does not interact with GitHub Packages                      |
| Pages           | Ghillie does not access GitHub Pages configuration                  |
| Security events | Ghillie does not consume security advisories or alerts              |
| Webhooks        | Ghillie does not configure outgoing webhooks                        |

If future Ghillie features require additional permissions, update the App
configuration and document the rationale. Always prefer the minimal permission
set that enables the required functionality.

## Troubleshooting

### Authentication failures

**Symptom:** Ghillie reports "401 Unauthorized" or "Bad credentials" errors.

**Possible causes:**

- The installation access token has expired. Refresh the token and update
  `GHILLIE_GITHUB_TOKEN`.
- The App is not installed on the target repository. Verify the installation in
  organisation settings.
- The JWT used for token exchange is malformed or expired. Ensure the `exp`
  claim is set correctly and the private key matches the App.

### Insufficient permissions

**Symptom:** Ghillie reports "403 Forbidden" or "Resource not accessible"
errors.

**Possible causes:**

- The App does not have the required permission (for example, Issues: Read).
  Update the App permissions in GitHub settings.
- The repository is not included in the App installation. Add the repository to
  the installation scope.
- Organisation policies restrict App access. Check with the organisation
  administrator.

### Rate limiting

**Symptom:** Ghillie reports "403 rate limit exceeded" or slows down
significantly.

**Possible causes:**

- Ingestion is running too frequently or across too many repositories. Adjust
  the ingestion schedule or batch size.
- Another service is consuming rate limit quota under the same App installation.
  Consider separate Apps for different services.

**Resolution:**

- Check the `X-RateLimit-Remaining` and `X-RateLimit-Reset` headers in API
  responses.
- Implement exponential backoff when rate limits are approached.
- For high-volume estates, consider using conditional requests or reducing
  polling frequency.

### Repository not appearing in ingestion

**Symptom:** A repository is in the catalogue but Ghillie does not ingest its
activity.

**Possible causes:**

- The repository is not included in the App installation. Add it via
  organisation settings.
- The repository has `ingestion_enabled: false` in the registry. Enable
  ingestion via `RepositoryRegistryService.enable_ingestion()`.
- The catalogue has not been re-imported after adding the repository. Run the
  catalogue importer.

## Migrating from Personal Access Tokens

For deployments currently using a Personal Access Token with Ghillie, follow
these steps to migrate to a GitHub App:

1. **Create the GitHub App** following the steps in this document.
2. **Install the App** on all repositories currently accessed by Ghillie.
3. **Set up token exchange** to generate installation access tokens.
4. **Update `GHILLIE_GITHUB_TOKEN`** to use the installation token instead of
   the PAT.
5. **Verify ingestion** by running Ghillie and checking that events are captured
   correctly.
6. **Revoke the PAT** once the App is confirmed to be working correctly.

For screen readers: The following flowchart illustrates the migration process
from Personal Access Tokens to GitHub App authentication.

```mermaid
flowchart TD
    A[Start migration] --> B[Create GitHub App with read-only permissions]
    B --> C[Install App on all required repositories]
    C --> D[Store private key securely in secrets manager]
    D --> E[Implement JWT generation and token exchange]
    E --> F[Obtain installation access token]
    F --> G[Set GHILLIE_GITHUB_TOKEN to installation token]
    G --> H[Run Ghillie and verify repository ingestion]
    H --> I{Ingestion successful for all target repositories?}
    I -->|Yes| J[Revoke existing Personal Access Token]
    I -->|No| K[Check App permissions, installation scope, and token validity]
    K --> E
    J --> L[Migration complete]
```

The migration is transparent to Ghillie's internals because both PATs and
installation tokens use the same `Authorization: Bearer <token>` header format.

## Design decisions

This section documents the rationale behind key configuration choices.

### Read-only access model

Ghillie is designed as an observational system. It aggregates repository
activity to generate status reports but never modifies repositories. This
read-only constraint:

- Reduces security risk from compromised credentials.
- Simplifies permission audits and compliance reviews.
- Aligns with the principle of least privilege.

### Contents: Read for documentation only

The Contents: Read permission is required to access documentation paths such as
roadmaps and Architecture Decision Records (ADRs). Ghillie does not read source
code blobs; it only queries commit history filtered by configured documentation
paths.

If stricter controls are required by the organisation, consider the following
options:

- Limit the App installation to repositories that contain documentation.
- Use repository-level path restrictions where GitHub supports them.

### Polling over webhooks

Ghillie currently uses periodic polling rather than webhooks for ingestion.
This design:

- Simplifies deployment (no public endpoint required).
- Avoids missed events during service downtime.
- Allows controlled backfill of historical data.

Future versions may add webhook support for lower-latency ingestion. The
webhook permission is not requested until that feature is implemented.

### GitHub Apps over fine-grained PATs

While fine-grained PATs offer similar permission scoping to GitHub Apps, they
have limitations for production use:

- **User binding:** PATs are tied to individual user accounts and may become
  invalid when users leave the organisation.
- **Manual rotation:** PATs require manual regeneration; Apps support automatic
  token refresh.
- **Audit separation:** PAT activity appears in the user's audit trail; App
  activity is logged separately for clearer accountability.

For pilot or development environments, fine-grained PATs remain acceptable. For
production deployments, GitHub Apps are strongly recommended.

## Related documentation

- [GitHub App documentation](https://docs.github.com/en/apps) – Official GitHub
  documentation for creating and managing Apps.
- [Installation access tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app)
  – GitHub documentation for token exchange.
- [Ghillie users' guide](users-guide.md) – General guidance for configuring and
  operating Ghillie.
- [Ghillie roadmap](roadmap.md) – Task 1.4.b covers secure credential storage
  and rotation.
