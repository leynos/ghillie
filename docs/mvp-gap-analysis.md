# MVP gap analysis for manual two-week reporting workflow

## Scope and assessment criteria

This document assesses whether Ghillie currently provides an easy execution
path and API surface for the requested MVP behaviour:

1. Start an instance on k3d/Helm without background tasks, with GitHub and
   inference provider configured.
2. Manually configure an estate of repositories.
3. Manually trigger ingestion for two weeks of data with observability.
4. Manually export structured collected data and derived evidence.
5. Manually trigger an LLM-generated report over that two-week evidence.

For this assessment, an easy execution path means a documented CLI command or
HTTP API endpoint, rather than bespoke Python scripts.

Assessment date: 2026-03-01.

## Executive summary

| MVP behaviour                                                         | Current status                                                                                                                                                                                                                             | Verdict |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------- |
| 1. k3d/Helm startup with no background tasks and providers configured | Local k3d + Helm deployment is available. Runtime deployment defaults to API-only behaviour (no ingestion/report workers). Provider configuration is possible via generic env/secret injection, but not via a purpose-built operator flow. | Partial |
| 2. Manual estate configuration                                        | Catalogue schema/import and registry sync services exist, with programmatic examples. No dedicated runtime API for catalogue import/sync/toggle operations.                                                                                | Partial |
| 3. Manual two-week ingestion trigger with observability               | Ingestion worker, structured logs, and lag service exist. No first-class API/CLI to trigger and track one-off backfills (including a two-week run).                                                                                        | Gap     |
| 4. Structured export of collected data and derived evidence           | Data exists in Bronze/Silver/Gold and in-memory evidence structures exist, but there is no built-in structured export API/CLI. Markdown report sink is available but not a structured export.                                              | Gap     |
| 5. Manual LLM report trigger over two-week evidence                   | Per-repository on-demand report API exists; background Dramatiq actors exist for repository and estate runs. No API-level window override or estate trigger endpoint.                                                                      | Partial |

Overall: Ghillie has most core primitives, but does not yet provide an
end-to-end operator-facing MVP workflow through a cohesive API/CLI path.

## Detailed gap analysis

### 1) Start instance without background tasks, with GitHub and inference configured

Current capabilities:

- Local k3d/Helm deployment exists via `make local-k8s-up` and
  `scripts/local_k8s.py`.
- Runtime app starts as health-only or domain-enabled API depending on
  `GHILLIE_DATABASE_URL`.
- The chart supports generic env/secret injection (`env.normal`, `envFrom`
  secret), and command/args overrides.
- The default deployment profile runs API only; ingestion/reporting workers are
  not automatically deployed in local-k8s flow.

Gaps:

- No explicit runtime profile abstraction (for example, `api`, `ingestion`,
  `reporting-worker`) with ready-made values files and commands.
- Local-k8s automation provisions only `DATABASE_URL` and `VALKEY_URL` secrets;
  GitHub and inference settings are not part of an opinionated bootstrap flow.
- No single documented path that validates provider configuration readiness.

Impact:

- Hosting works, but setup of GitHub and inference backends remains manual and
  error-prone.

### 2) Manually configure an estate of repositories

Current capabilities:

- Estate catalogue schema/validation exists.
- Import and registry synchronisation services exist.
- Ingestion enable/disable controls exist in registry service.

Gaps:

- No operator API endpoints for:
  - catalogue import,
  - registry sync from catalogue,
  - listing/toggling repositories.
- No dedicated CLI workflow in this repo that provides these operations as
  first-class commands.

Impact:

- Estate configuration is possible, but mostly through embedded Python usage
  rather than an easy operational interface.

### 3) Manually trigger two weeks of ingestion with observability

Current capabilities:

- `GitHubIngestionWorker` supports incremental polling with watermarks.
- Ingestion observability emits structured lifecycle events.
- `IngestionHealthService` computes lag and stalled repositories.

Gaps:

- No API/CLI to trigger an explicit backfill run for a chosen scope
  (repo/estate) and lookback window (for example, 14 days).
- Default initial lookback is seven days in code; no documented operator API
  contract for one-off two-week runs.
- No persistent job model/endpoint to query ingestion run state, progress, and
  completion outcomes.

Impact:

- Observability primitives exist, but controlled manual backfill operations are
  not operationally easy.

### 4) Manually export structured collected data and derived evidence

Current capabilities:

- Raw, refined, and report data are stored in Bronze/Silver/Gold schemas.
- Evidence bundle models and builders exist in code.
- Markdown filesystem sink exists for rendered report text.

Gaps:

- No export API/CLI for structured bundles (for example, JSON/JSONL/CSV) of:
  - collected event data,
  - derived evidence bundles,
  - report + coverage lineage.
- No stable export schema contract for downstream analytics/report pipelines.

Impact:

- Operators must write custom extraction scripts directly against internals or
  database tables.

### 5) Manually trigger LLM report from the two-week evidence

Current capabilities:

- `POST /reports/repositories/{owner}/{name}` generates on-demand repository
  reports.
- Dramatiq actors support repository and estate reporting jobs.

Gaps:

- No API endpoint for on-demand estate-wide report triggering.
- No API-level override for reporting window/as-of in on-demand report calls,
  making explicit two-week reruns awkward.
- No run-state API for asynchronous report jobs.

Impact:

- Single-repository manual trigger is good; estate-wide and window-controlled
  operator workflows are not yet first-class.

## Metrics coverage analysis

### Needed metrics

| Metric                                                                   | Data availability in current model                                            | Current delivery path          | Gap                                   |
| ------------------------------------------------------------------------ | ----------------------------------------------------------------------------- | ------------------------------ | ------------------------------------- |
| Number of PRs merged or closed by repo                                   | Available from `pull_requests` (`state`, `merged_at`, `closed_at`, `repo_id`) | No dedicated API/report export | Add metrics query API/export contract |
| Average open-to-merge time per repo                                      | Available from `pull_requests.created_at` and `merged_at`                     | No dedicated API/report export | Add metrics query API/export contract |
| Number of resolved and outstanding issues by repo                        | Available from `issues.state` and `closed_at`                                 | No dedicated API/report export | Add metrics query API/export contract |
| Duration each resolved issue stayed open / open age of unresolved issues | Available from `issues.created_at` and `closed_at`                            | No dedicated API/report export | Add metrics query API/export contract |

### Nice-to-have metrics

| Metric                                             | Data availability in current model                                            | Current delivery path | Gap                                                      |
| -------------------------------------------------- | ----------------------------------------------------------------------------- | --------------------- | -------------------------------------------------------- |
| PR comments by repo and commenter                  | Not ingested/stored as first-class data                                       | None                  | Extend ingestion + schema + metrics API                  |
| Commit count per PR                                | Not ingested/stored as first-class data                                       | None                  | Extend ingestion + schema + metrics API                  |
| SLoC per merged PR, disaggregated by code category | Not ingested/stored (no per-PR file stats/additions/deletions classification) | None                  | Extend ingestion + schema + classification + metrics API |

## Cross-cutting API and operability gaps

- Runtime API surface is narrow (`/health`, `/ready`, and one on-demand
  repository report endpoint).
- Ingestion and estate-management operations are service-level capabilities, not
  operator-facing APIs.
- OpenAPI contract lags implementation details (for example, on-demand endpoint
  behaviour includes validation failure handling and metrics payload nuances).
- No single “MVP runbook” command sequence that performs estate config,
  backfill, export, and report trigger with observable run state.

## Closure priority

1. Operator control API/CLI for estate management and ingestion/report trigger
   operations, including run-state tracking.
2. Structured export API/CLI with stable schemas for events, evidence, and
   report lineage.
3. Required metrics API over existing Silver data.
4. Ingestion/schema upgrades for nice-to-have metrics.
5. k3d/Helm profile hardening and OpenAPI/documentation parity updates.

## Evidence references

- [scripts/local_k8s.py](../scripts/local_k8s.py)
- [charts/ghillie/values.yaml](../charts/ghillie/values.yaml)
- [ghillie/runtime.py](../ghillie/runtime.py)
- [ghillie/api/app.py](../ghillie/api/app.py)
- [specs/openapi.yml](../specs/openapi.yml)
- [ghillie/github/ingestion.py](../ghillie/github/ingestion.py)
- [ghillie/github/observability.py](../ghillie/github/observability.py)
- [ghillie/github/lag.py](../ghillie/github/lag.py)
- [ghillie/registry/service.py](../ghillie/registry/service.py)
- [ghillie/silver/storage.py](../ghillie/silver/storage.py)
- [ghillie/github/client.py](../ghillie/github/client.py)
- [ghillie/evidence/service.py](../ghillie/evidence/service.py)
- [ghillie/reporting/service.py](../ghillie/reporting/service.py)
- [docs/users-guide.md](./users-guide.md)
