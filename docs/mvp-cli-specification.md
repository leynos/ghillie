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

### `ghillie estate import`

Purpose: import catalogue definitions into estate storage.

Options:

- `--estate-key <key>` (required)
- `--catalogue-path <path>` (required)
- `--commit-sha <sha>` (required)
- `--estate-name <name>` (optional)

### `ghillie estate sync`

Purpose: sync imported catalogue repositories into operational registry.

Options:

- `--estate-key <key>` (required)
- `--wait/--no-wait`

### `ghillie estate list`

Purpose: list estates known to the control plane.

Options:

- `--active/--inactive`

### `ghillie estate repo list`

Purpose: list repositories for an estate.

Options:

- `--estate-key <key>`
- `--active/--inactive`
- `--limit <n>`
- `--offset <n>`

### `ghillie estate repo set`

Purpose: set per-repository ingestion state.

Options:

- `--owner <owner>` (required)
- `--name <repo>` (required)
- `--ingestion-enabled/--ingestion-disabled` (required)

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
| `estate import`       | `POST /estates/{estate_key}/catalogue-import`  | new              | Follows plural-resource path style.                                      |
| `estate sync`         | `POST /estates/{estate_key}/registry-sync`     | new              | Follows plural-resource path style.                                      |
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

Applies to `stack up`, `estate sync`, `ingest run`, and `report run`.

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
- Errors should include structured fields: `code`, `message`, and `hint`.

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
