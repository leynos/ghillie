# MVP operator CLI specification

## Purpose

Define a single command-line interface (CLI) for the MVP operator workflow,
covering:

1. Local k3d/Helm startup with GitHub and inference providers configured,
   without background workers.
2. Manual estate configuration.
3. Manual two-week ingestion trigger with observability.
4. Manual structured export of collected and derived data.
5. Manual LLM report trigger over the two-week window.

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
  existing operational runbooks is higher and failure output is easier to
  surface unchanged.
- Provide a `python-api` backend as an optional adapter where installed.

## Command model

Command grammar:

```text
ghillie <verb> <noun> [selectors] [predicates] [options]
```

- **Verbs** describe actions: `up`, `down`, `list`, `run`, `watch`, `get`,
  `set`, `import`, `sync`.
- **Nouns** describe resources: `stack`, `estate`, `repo`, `ingest`, `report`,
  `export`, `metrics`.
- **Predicates/adjectives** narrow behaviour:
  `--active`, `--inactive`, `--wait`, `--no-wait`, `--background-workers`,
  `--no-background-workers`.

## Global options

All commands should support these global options:

| Option                | Type                       | Default                 | Purpose                             |
| --------------------- | -------------------------- | ----------------------- | ----------------------------------- |
| `--api-base-url`      | `str`                      | `http://127.0.0.1:8080` | Ghillie API root URL                |
| `--auth-token`        | `str`                      | unset                   | Bearer token for authenticated APIs |
| `--output`            | `table, json, yaml`        | `table`                 | Output format                       |
| `--log-level`         | `debug, info, warn, error` | `info`                  | CLI log verbosity                   |
| `--request-timeout-s` | `float`                    | `30`                    | `httpx` timeout                     |
| `--non-interactive`   | `bool`                     | `true`                  | Fail fast instead of prompting      |
| `--dry-run`           | `bool`                     | `false`                 | Print intended actions only         |

Configuration precedence:

1. Explicit CLI flags.
2. Environment variables (for example, `GHILLIE_API_BASE_URL`).
3. Profile file (`~/.config/ghillie/cli.toml`).

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

Each CLI command should call a stable HTTP endpoint via `httpx`.

| CLI command        | HTTP target                                    |
| ------------------ | ---------------------------------------------- |
| `estate import`    | `POST /estates/{estate_key}/catalogue-import`  |
| `estate sync`      | `POST /estates/{estate_key}/registry-sync`     |
| `estate repo list` | `GET /estates/{estate_key}/repositories`       |
| `estate repo set`  | `PATCH /repositories/{owner}/{name}/ingestion` |
| `ingest run`       | `POST /ingestion/runs`                         |
| `ingest status`    | `GET /ingestion/runs/{run_id}`                 |
| `report run`       | `POST /reports/runs` or scoped endpoints       |
| `report status`    | `GET /reports/runs/{run_id}`                   |
| `export *`         | `POST /exports/{kind}`                         |
| `metrics required` | `GET /metrics/repositories/required`           |
| `metrics nice`     | `GET /metrics/repositories/nice`               |

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
