# Minimum viable product (MVP) operator CLI specification

## Purpose

Define a single command-line interface (CLI) for the MVP operator workflow,
covering:

1. Local k3d/Helm startup with GitHub and inference providers configured,
   without background workers.
2. Configure estate manually.
3. Trigger two-week ingestion with observability controls.
4. Export collected and derived data in a structured format.
5. Trigger a large language model (LLM) report over the two-week window.

The CLI is intentionally task-oriented and should be the easiest path for a
human operator to execute the workflow end to end.

## Technology constraints

The CLI implementation must use:

- `cyclopts` for command modelling and parsing.
- `httpx` for all control-plane HTTP calls to Ghillie APIs.
- One integration backend for local runtime orchestration:
  - `cuprum` wrappers around `docker`, `k3d`, `helm`, and `kubectl`, or
  - direct Python integrations (`docker` SDK, Helm subprocess contract,
    Kubernetes Python client).

Recommended default:

- Use `cuprum` as the primary integration backend because command parity with
  existing operational runbooks is higher, and failure output is easier to
  surface unchanged.
- Provide a `python-api` backend as an optional adapter where installed.

## Command model

Command grammar:

```text
ghillie <noun> <verb> [selectors] [predicates] [options]
```

- **Nouns** describe top-level resources: `stack`, `estate`, `ingest`,
  `report`, `export`, `metrics`.
- **Verbs** describe actions within each noun: `up`, `down`, `list`, `run`,
  `watch`, `get`, `set`, `import`, `sync`.
- **Predicates/adjectives** narrow behaviour:
  `--active`, `--inactive`, `--wait`, `--no-wait`, `--background-workers`,
  `--no-background-workers`.

## Global options

All commands should support these global options:

| Option                | Type                       | Default         | Purpose                             |
| --------------------- | -------------------------- | --------------- | ----------------------------------- |
| `--api-base-url`      | `str`                      | auto-discovered | Ghillie API root URL                |
| `--auth-token`        | `str`                      | unset           | Bearer token for authenticated APIs |
| `--output`            | `table, json, yaml`        | `table`         | Output format                       |
| `--log-level`         | `debug, info, warn, error` | `info`          | CLI log verbosity                   |
| `--request-timeout-s` | `float`                    | `30`            | `httpx` timeout                     |
| `--non-interactive`   | `bool`                     | `true`          | Fail fast instead of prompting      |
| `--dry-run`           | `bool`                     | `false`         | Print intended actions only         |

Configuration precedence:

1. Explicit CLI flags.
2. Environment variables (for example, `GHILLIE_API_BASE_URL`).
3. Profile file (`~/.config/ghillie/cli.toml`).
4. Persisted runtime state (`~/.config/ghillie/state.json`) written by
   `ghillie stack up`.
5. Fallback `http://127.0.0.1:8080` only when no discovered state exists.

### API base URL persistence and discovery

To keep the easy path reliable when `stack up` auto-selects an ingress port:

- `ghillie stack up` must persist the resolved API base URL (for example
  `http://127.0.0.1:49213`) into `state.json`.
- Subsequent API commands (`estate`, `ingest`, `export`, `report`, `metrics`)
  must use that persisted value unless explicitly overridden by
  `--api-base-url` or environment configuration.
- `ghillie stack status` must print the currently effective API base URL and
  its source (flag, env, profile, or discovered state).

### Configuration file schemas and environment contract

`~/.config/ghillie/cli.toml` example:

```toml
[global]
api_base_url = "http://127.0.0.1:8080"
auth_token_env = "GHILLIE_AUTH_TOKEN"
output = "table"
log_level = "info"
request_timeout_s = 30
non_interactive = true
dry_run = false

[stack]
backend = "cuprum"
profile = "api-only"
cluster_name = "ghillie-local"
namespace = "ghillie"
ingress_port = 8080
image = "ghillie:local"
provider_github_token_env = "GHILLIE_GITHUB_TOKEN"
provider_model_backend = "mock"
provider_openai_key_env = "GHILLIE_OPENAI_API_KEY"

[defaults]
window_days = 14
poll_interval_s = 2
```

`~/.config/ghillie/state.json` example:

```json
{
  "api_base_url": "http://127.0.0.1:49213",
  "source": "stack_up",
  "cluster_name": "ghillie-local",
  "namespace": "ghillie",
  "profile": "api-only",
  "updated_at": "2026-03-02T16:50:00Z"
}
```

State schema notes:

- `api_base_url`: required absolute HTTP(S) URL used for auto-discovery.
- `source`: required source marker (`stack_up` for current MVP flow).
- `cluster_name`, `namespace`, `profile`: optional informational fields.
- `updated_at`: required ISO-8601 UTC timestamp.

Supported environment variables:

| Variable                      | Type                                           | Maps to / purpose                                      |
| ----------------------------- | ---------------------------------------------- | ------------------------------------------------------ |
| `GHILLIE_API_BASE_URL`        | `str`                                          | Global `--api-base-url`                                |
| `GHILLIE_AUTH_TOKEN`          | `str`                                          | Global `--auth-token`                                  |
| `GHILLIE_OUTPUT`              | `table, json, yaml`                            | Global `--output`                                      |
| `GHILLIE_LOG_LEVEL`           | `debug, info, warn, error`                     | Global `--log-level`                                   |
| `GHILLIE_REQUEST_TIMEOUT_S`   | `float`                                        | Global `--request-timeout-s`                           |
| `GHILLIE_NON_INTERACTIVE`     | `bool`                                         | Global `--non-interactive`                             |
| `GHILLIE_DRY_RUN`             | `bool`                                         | Global `--dry-run`                                     |
| `GHILLIE_BACKEND`             | `cuprum, python-api`                           | `stack up --backend` default                           |
| `GHILLIE_PROFILE`             | `api-only, ingestion-worker, reporting-worker` | `stack up --profile` default                           |
| `GHILLIE_CLUSTER_NAME`        | `str`                                          | `stack` command default cluster                        |
| `GHILLIE_NAMESPACE`           | `str`                                          | `stack` command default namespace                      |
| `GHILLIE_INGRESS_PORT`        | `int`                                          | `stack up --ingress-port` default                      |
| `GHILLIE_IMAGE`               | `str`                                          | `stack up --image` default                             |
| `GHILLIE_MODEL_BACKEND`       | `mock, openai`                                 | Report/runtime model backend default                   |
| `GHILLIE_GITHUB_TOKEN`        | `str`                                          | GitHub provider token (referenced by env-name options) |
| `GHILLIE_OPENAI_API_KEY`      | `str`                                          | OpenAI provider token (referenced by env-name options) |
| `GHILLIE_DEFAULT_WINDOW_DAYS` | `int`                                          | Default for `--window-days` / `--lookback-days`        |
| `GHILLIE_POLL_INTERVAL_S`     | `float`                                        | Default polling interval for `watch` commands          |

## Root command tree

```text
ghillie
  stack
    up
    down
    status
    logs
  estate
    import
    sync
    list
    repo list
    repo set
  ingest
    run
    status
    watch
  export
    events
    evidence
    reports
    bundle
  report
    run
    status
    watch
  metrics
    required
    nice
```

### Task 2.5.a scaffold status and Task 2.5.b estate delivery

The first packaged operator CLI delivery is a scaffold, not a finished control
plane. The implemented Task 2.5.a contract is:

- `uv run ghillie --help` exposes the full root noun tree shown above.
- Every documented noun and verb is registered under the packaged
  `ghillie/cli/` entry point, even where later tasks still own the real backend
  behaviour.
- Task 2.5.b replaced the estate placeholders with live control-plane calls;
  the estate section below records their request, response, and error shapes.
  The remaining nouns still return `status: not_implemented` placeholders.
- Root-global options are resolved before noun dispatch. The scaffold accepts
  `--api-base-url`, `--auth-token`, `--output`, `--log-level`,
  `--request-timeout-s`, `--non-interactive` or `--interactive`, and
  `--dry-run` or `--no-dry-run`.
- Valid placeholder invocations return deterministic structured output with
  `status: not_implemented` and the message `not implemented in Task 2.5.a`.
- Invalid CLI input still fails fast with exit code `2`.

The `stack up` backend selector and the control-plane client seam are real in
the scaffold: `cuprum` and `python-api` both resolve to distinct local runtime
adapter placeholders, and API-facing commands resolve one `httpx` client from
the shared root configuration.

## Stack commands (k3d/Helm lifecycle)

### `ghillie stack up`

Purpose: start an instance with explicit runtime profile and provider config.

Key options:

| Option                                         | Type                                           | Default                   | Notes                 |
| ---------------------------------------------- | ---------------------------------------------- | ------------------------- | --------------------- |
| `--profile`                                    | `api-only, ingestion-worker, reporting-worker` | `api-only`                | Runtime role          |
| `--backend`                                    | `cuprum, python-api`                           | `cuprum`                  | Integration adapter   |
| `--cluster-name`                               | `str`                                          | `ghillie-local`           | k3d cluster name      |
| `--namespace`                                  | `str`                                          | `ghillie`                 | Kubernetes namespace  |
| `--ingress-port`                               | `int`                                          | auto                      | Loopback ingress port |
| `--image`                                      | `str`                                          | `ghillie:local`           | Workload image        |
| `--provider-github-token-env`                  | `str`                                          | `GHILLIE_GITHUB_TOKEN`    | Token env key         |
| `--provider-model-backend`                     | `mock, openai`                                 | `mock`                    | Model backend         |
| `--provider-openai-key-env`                    | `str`                                          | `GHILLIE_OPENAI_API_KEY`  | OpenAI key env key    |
| `--background-workers/--no-background-workers` | `bool`                                         | `--no-background-workers` | API profile guardrail |
| `--wait/--no-wait`                             | `bool`                                         | `--wait`                  | Wait for readiness    |

Behaviour notes:

- `--profile api-only` plus `--no-background-workers` is the default MVP mode.
- Provider settings are rendered into secrets/config maps expected by runtime.

### `ghillie stack down`

Purpose: delete local preview resources.

Options: `--cluster-name`, `--purge-images`, `--force`.

### `ghillie stack status`

Purpose: show pod status, ingress URL, profile, and provider readiness checks.

Options: `--cluster-name`, `--namespace`, `--output`.

### `ghillie stack logs`

Purpose: stream application logs.

Options: `--cluster-name`, `--namespace`, `--follow`, `--since`.

## Estate commands (manual estate configuration)

All five estate verbs call the control plane (Task 2.5.b). They honour the root
options `--api-base-url`, `--auth-token`, `--output`, `--dry-run`, and
`--request-timeout-s`. `json` and `yaml` print the server document unchanged;
`table` is human-oriented. Invalid local input exits `2`; a control-plane
failure exits `3` with the documented envelope.

### `ghillie estate import`

Purpose: import catalogue definitions into estate storage.

Options:

- `--estate-key <key>` (required; must match
  `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`)
- `--catalogue-path <path>` (required; read as UTF-8 with any BOM stripped)
- `--commit-sha <sha>` (required)
- `--estate-name <name>` (optional; defaults to the estate key)
- root `--dry-run` maps to `?dry_run=true`

Request: `POST /estates/{estate_key}/catalogue-import` with
`{"commit_sha", "estate_name"?, "catalogue_yaml"}`. The CLI rejects a body
larger than 1 MiB before sending it.

Response: 200 with `estate_key`, `commit_sha`, `state`, `dry_run`, `skipped`,
`skipped_reason`, `registry_sync_required`, and `created`/`updated`/`deleted`
counts for `projects`, `components`, `repositories`, and `edges`. A repeat of
an imported commit returns `skipped: true`; table output leads with `SKIPPED:`.

Errors: `invalid_estate_key` and `catalogue_file_unreadable` (2);
`catalogue_invalid` (422), `conflict` (409), `payload_too_large` (413), and
`storage_unavailable` (503) (3).

### `ghillie estate sync`

Purpose: project imported catalogue repositories into the registry.

Options:

- `--estate-key <key>` (required)
- root `--dry-run` maps to `?dry_run=true`

The sync is synchronous and idempotent; there is no `--wait` flag (D2).
Response: 200 with `estate_key`, `state`, `dry_run`, `repositories_created`,
`repositories_updated`, `repositories_deactivated`, `repositories_conflicted`,
`repositories_left_disabled`, and `repositories_left_disabled_count` (the first
100 slugs).

Errors: `estate_not_found` (404), `registry_sync_failed` (500).

### `ghillie estate list`

Purpose: list estates known to the control plane.

Options: none. Estates have no lifecycle state, so active and inactive flags
are rejected (D4).

Request: `GET /estates` with no query parameters. Response: 200 with `items`,
`limit`, `offset`, `has_more`, and `next_offset`; each item carries `key`,
`name`, `description`, and `last_import` (`commit_sha`, `imported_at`).

### `ghillie estate repo list`

Purpose: list repositories for one estate.

Options:

- `--estate-key <key>` (required)
- `--ingestion-enabled` / `--active` (select enabled rows)
- `--ingestion-disabled` / `--inactive` (select disabled rows)
- `--limit <n>` (1 to 500, default 50)
- `--offset <n>` (0 or more, default 0)

Omitting both filter flags lists both states (D5). Request:
`GET /estates/{estate_key}/repositories?ingestion_enabled?&limit&offset`.
Response: 200 with `estate_key`, `items`, and the pagination metadata; each
item carries `owner`, `name`, `default_branch`, `ingestion_enabled`, and
`documentation_paths`. Results are ordered by owner and name.

Errors: `estate_not_found` (404); an out-of-range `--limit` or `--offset` is
rejected locally with exit `2` before any request.

### `ghillie estate repo set`

Purpose: set per-repository ingestion state.

Options:

- `--owner <owner>` (required)
- `--name <repo>` (required)
- `--ingestion-enabled/--ingestion-disabled` (required; exactly one)

Request: `PATCH /repositories/{owner}/{name}/ingestion` with
`{"ingestion_enabled": bool}`. Each path segment is URL-quoted, so an owner or
name containing `/` cannot change the route. Response: 200 with `owner`, `name`,
`ingestion_enabled`, and `changed`.

The endpoint has no dry-run mode. When root `--dry-run` is set, the command
refuses locally with `dry_run_unsupported` and exit `2` rather than applying a
live toggle (D6, D20).

Errors: `repository_not_found` (404).

## Ingestion commands (two-week manual trigger + observability)

### `ghillie ingest run`

Purpose: start a manual ingestion run.

Options:

| Option                  | Type                 | Default         | Notes                         |
| ----------------------- | -------------------- | --------------- | ----------------------------- |
| `--scope`               | `repository, estate` | required        | Run target type               |
| `--estate-key`          | `str`                | unset           | Required for estate scope     |
| `--owner`               | `str`                | unset           | Required for repository scope |
| `--name`                | `str`                | unset           | Required for repository scope |
| `--lookback-days`       | `int`                | `14`            | MVP default                   |
| `--max-events-per-kind` | `int`                | service default | Optional override             |
| `--wait/--no-wait`      | `bool`               | `--wait`        | Wait for completion           |

Output:

- Always returns `run_id`.
- If waiting, returns terminal state and per-repository counts.

### `ghillie ingest status`

Purpose: fetch status for one run.

Options: `--run-id <id>`.

### `ghillie ingest watch`

Purpose: follow ingestion run progress.

Options: `--run-id <id>`, `--poll-interval-s <seconds>`.

## Export commands (structured export)

### `ghillie export events`

Purpose: export ingested Bronze/Silver event data.

Options:

- `--scope repository|estate`
- selectors (`--estate-key` or `--owner/--name`)
- `--window-days 14` or `--window-start`/`--window-end`
- `--format json|jsonl|csv`
- `--output-path <path>`

### `ghillie export evidence`

Purpose: export derived evidence bundles used for reporting.

Options mirror `export events`, plus `--include-previous-reports`.

### `ghillie export reports`

Purpose: export Gold report metadata, machine summaries, and coverage lineage.

Options mirror `export events`, plus `--include-coverage`.

### `ghillie export bundle`

Purpose: single artefact containing events, evidence, and reports.

Options:

- `--scope ...`
- selectors
- `--window-days 14`
- `--format json`
- `--output-path <path>`

## Reporting commands (manual LLM trigger)

### `ghillie report run`

Purpose: run on-demand LLM reporting.

Options:

| Option             | Type                 | Default     | Notes                              |
| ------------------ | -------------------- | ----------- | ---------------------------------- |
| `--scope`          | `repository, estate` | required    | Run target                         |
| selectors          | -                    | -           | `--estate-key` or `--owner/--name` |
| `--window-days`    | `int`                | `14`        | MVP override                       |
| `--as-of`          | ISO-8601 datetime    | now         | Window end override                |
| `--model-backend`  | `mock, openai`       | env default | Optional override                  |
| `--wait/--no-wait` | `bool`               | `--wait`    | Wait for completion                |

### `ghillie report status`

Purpose: query status for asynchronous report run.

Options: `--run-id <id>`.

### `ghillie report watch`

Purpose: poll until report run completion.

Options: `--run-id <id>`, `--poll-interval-s <seconds>`.

## Metrics commands

### `ghillie metrics required`

Purpose: return required MVP metrics per repository for selected window.

Options:

- `--scope repository, estate`
- selectors
- `--window-days 14`
- `--group-by repo`

### `ghillie metrics nice`

Purpose: return nice-to-have metrics where data is available.

Options:

- same as `metrics required`
- `--include-comments`
- `--include-commit-counts`
- `--include-sloc-breakdown`

## Endpoint mapping contract

Each API-backed CLI command should call a stable HTTP endpoint via `httpx`.
Non-API commands (for example, `stack up`, `stack down`, and `stack logs`) are
local orchestration commands and are excluded from this `httpx` contract.

Naming convention policy:

- Keep OpenAPI path style as plural resource nouns plus optional resource ID:
  `/estates/{estate_key}/repositories`, `/ingestion/runs/{run_id}`.
- New endpoints should not introduce verb-first resources in paths.
- Existing OpenAPI paths keep their current names for MVP to avoid breaking
  consumers; aliases may be added where needed.

Lifecycle policy for this MVP:

- Existing endpoints retained:
  - `GET /health`
  - `GET /ready`
  - `POST /reports/repositories/{owner}/{name}` (current on-demand repository
    report trigger)
- Deprecated endpoints in this MVP: none.
- Renamed endpoints in this MVP: none.

| CLI command           | HTTP target(s)                                 | Lifecycle in MVP | OpenAPI mapping note                                                     |
| --------------------- | ---------------------------------------------- | ---------------- | ------------------------------------------------------------------------ |
| `stack up`            | no HTTP call                                   | existing (local) | Local orchestration (`k3d`, `helm`, `kubectl`); excluded from OpenAPI.   |
| `stack down`          | no HTTP call                                   | existing (local) | Local orchestration teardown; excluded from OpenAPI.                     |
| `stack logs`          | no HTTP call                                   | existing (local) | Local log streaming via Kubernetes tooling; excluded from OpenAPI.       |
| `stack status`        | `GET /ready`, `GET /health`                    | existing         | Reuses existing readiness and liveness paths.                            |
| `estate list`         | `GET /estates`                                 | new              | Adds estate collection endpoint using plural-resource path style.        |
| `estate import`       | `POST /estates/{estate_key}/catalogue-import`  | new              | Plural-resource path; optional `dry_run` query parameter.                |
| `estate sync`         | `POST /estates/{estate_key}/registry-sync`     | new              | Plural-resource path; optional `dry_run` query parameter.                |
| `estate repo list`    | `GET /estates/{estate_key}/repositories`       | new              | Follows plural-resource path style.                                      |
| `estate repo set`     | `PATCH /repositories/{owner}/{name}/ingestion` | new              | Follows plural-resource path style.                                      |
| `ingest run`          | `POST /ingestion/runs`                         | new              | Adds run resource; aligns with run-status paths.                         |
| `ingest status`       | `GET /ingestion/runs/{run_id}`                 | new              | Adds run resource; aligns with run-trigger paths.                        |
| `ingest watch`        | `GET /ingestion/runs/{run_id}`                 | new              | Polling wrapper over run status endpoint; WebSocket is optional future.  |
| `report run` (repo)   | `POST /reports/repositories/{owner}/{name}`    | existing         | Existing endpoint kept as primary repository trigger.                    |
| `report run` (estate) | `POST /reports/runs`                           | new              | Adds estate/asynchronous run trigger without renaming existing endpoint. |
| `report status`       | `GET /reports/runs/{run_id}`                   | new              | Adds run-state retrieval endpoint for asynchronous reporting.            |
| `report watch`        | `GET /reports/runs/{run_id}`                   | new              | Polling wrapper over run status endpoint; WebSocket is optional future.  |
| `export *`            | `POST /exports/{kind}`                         | new              | New export resource family under plural noun.                            |
| `metrics required`    | `GET /metrics/repositories/required`           | new              | New metrics resource, noun-first naming retained.                        |
| `metrics nice`        | `GET /metrics/repositories/nice`               | new              | New metrics resource, noun-first naming retained.                        |

### `--wait/--no-wait` run-state contract

Applies to `stack up`, `ingest run`, and `report run`. Estate sync is
synchronous and has no wait contract (D2).

Non-terminal states:

- `queued`
- `running`

Terminal states:

- `succeeded`
- `partial` (some scope units failed, others succeeded)
- `failed`
- `cancelled`
- `timed_out` (run-level timeout determined by service)

`--no-wait` behaviour:

- Return immediately after run creation/trigger confirmation.
- Output includes `run_id`, initial `state`, and status endpoint hint.
- Exit code `0` if trigger request succeeded.

`--wait` behaviour:

- Poll until one terminal state is observed, or until CLI wait deadline is hit.
- Always return `run_id`, final observed `state`, and summary counts.
- For `partial`, `failed`, or `timed_out`, include `partial_results` for any
  completed units plus `failed_units` and error summaries.
- If terminal state is:
  - `succeeded`: exit code `0`.
  - `partial`: exit code `3`.
  - `failed`: exit code `3`.
  - `cancelled`: exit code `3`.
  - `timed_out`: exit code `3`.
- If CLI wait deadline is exceeded before terminal state is reached, return
  `last_observed_state`, any `partial_results`, and exit code `5`.

## Error handling and exit codes

Exit code contract:

- `0`: success.
- `2`: invalid CLI input.
- `3`: API or transport failure.
- `4`: integration backend failure (`k3d`, `helm`, `kubectl`, `docker`).
- `5`: timed out waiting for terminal run state.

Output contract:

- `--output table` for operator readability.
- `--output json` for automation.
- `--output yaml` for YAML-oriented operator workflows.

Machine-readable modes print one error envelope (D7). `status` appears only
when the service answered, and `issues` only when it supplied per-field
problems:

```json
{
  "error": {
    "code": "catalogue_invalid",
    "message": "The catalogue is invalid.",
    "hint": "Fix the listed catalogue issues and import the catalogue again.",
    "status": 422,
    "issues": [{"code": "invalid_projects", "message": "expected an array"}]
  }
}
```

| Code                        | Exit | Meaning                                       |
| --------------------------- | ---- | --------------------------------------------- |
| `invalid_estate_key`        | 2    | Key fails the creation pattern.               |
| `catalogue_file_unreadable` | 2    | File cannot be read as UTF-8.                 |
| `request_too_large`         | 2    | Serialized body exceeds 1 MiB.                |
| `dry_run_unsupported`       | 2    | Dry run requested for a live-only verb.       |
| `estate_not_found`          | 3    | Estate key is unknown.                        |
| `repository_not_found`      | 3    | Repository slug is unknown.                   |
| `catalogue_invalid`         | 3    | Catalogue failed schema validation (422).     |
| `conflict`                  | 3    | Stored commit conflicts with this import.     |
| `invalid_input`             | 3    | A request field is malformed (400).           |
| `payload_too_large`         | 3    | The service rejected the request size (413).  |
| `unauthorized`              | 3    | The service requires or rejected a token.     |
| `not_found`                 | 3    | No such route, or estate routes are disabled. |
| `storage_unavailable`       | 3    | The catalogue store is unavailable (503).     |
| `registry_sync_failed`      | 3    | The sync failed inside the service (500).     |
| `internal_error`            | 3    | An unexpected service failure (500).          |
| `transport`                 | 3    | The service could not be reached.             |
| `timeout`                   | 3    | The request exceeded the timeout.             |
| `invalid_response`          | 3    | A successful response was not a JSON object.  |
| `http_<status>`             | 3    | Any other non-2xx response.                   |

## Security constraints

- Never print provider secrets.
- Support token retrieval via environment variable names rather than literal
  token values in command arguments where possible.
- Redact bearer tokens and connection strings in debug logs.

## MVP acceptance checklist

The CLI spec is complete when all of the following are executable through the
CLI without writing ad hoc scripts:

1. `stack up` starts API-only profile with provider config and no background
   workers.
2. Estate can be imported and synced via `estate import` and `estate sync`.
3. A 14-day ingestion run can be started and monitored via `ingest run/watch`.
4. Structured exports can be produced via `export bundle`.
5. Estate or repository report can be triggered for a 14-day window via
   `report run`.
