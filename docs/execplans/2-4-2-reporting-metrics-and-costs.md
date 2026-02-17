# Capture reporting metrics and costs

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`, and
`Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: DONE

## Purpose / big picture

Task 2.4.b adds operational telemetry to repository report generation so
operators can assess runtime behaviour and approximate cost over time.

After this change, each generated repository report records:

- invocation latency in milliseconds,
- prompt/completion/total token counts (where available), and
- structured lifecycle log events for start/success/failure.

A new aggregation service computes period snapshots (report count, average and
p95 latency, and token totals) across all repositories or one estate.

Success is observable when:

1. Gold-layer report rows persist latency and token fields.
2. Scheduled and on-demand report generation emits structured reporting events.
3. Operators can query period snapshots for total reports, latency profile, and
   token usage totals.
4. API report responses include persisted metrics fields.
5. Unit and pytest-bdd coverage validates metrics capture and aggregation.
6. Docs and roadmap reflect the delivered capability.
7. Quality gates pass: `make check-fmt`, `make typecheck`, `make lint`, and
   `make test`.

## Constraints

- Keep `StatusModel` protocol unchanged; adapter metrics are side-channel only.
- Follow TDD requirements in `AGENTS.md` (tests added before implementation).
- Preserve existing reporting architecture and storage contracts.
- Keep new Gold report metric columns nullable for backward compatibility.
- Maintain markdown wrapping and linting requirements in `docs/`.

## Tolerances (exception triggers)

- If period aggregation required database-specific percentile functions,
  percentile computation could move to Python for cross-database compatibility.
- If exposing metrics required protocol changes in `StatusModel`, stop and use
  adapter-side attributes instead.

## Risks

- Risk: OpenAI responses may omit `usage`.
  Mitigation: Token fields are nullable and default to `None`.

- Risk: Very short invocations could round latency to 0 ms.
  Mitigation: Latency is still stored (nullable int ms) and aggregation uses
  available values.

- Risk: Metrics for retries could reflect a failed attempt.
  Mitigation: `ReportingService` stores metrics from the last invocation used
  for the persisted report.

- Risk: API response shape change could regress clients.
  Mitigation: Unit tests cover serialized `metrics` payload fields.

## Progress

- [x] Add failing unit tests for model invocation metrics value object.
- [x] Add failing unit tests for OpenAI/Mock adapter metrics capture.
- [x] Add failing unit tests for reporting metrics capture and logger
  integration.
- [x] Add failing unit tests for reporting metrics aggregation service.
- [x] Add failing pytest-bdd scenarios for report metrics and period snapshots.
- [x] Implement status adapter metrics (`ModelInvocationMetrics`).
- [x] Persist latency/token fields on Gold `Report` rows.
- [x] Add reporting observability logger and wire into service/actors/API
  factory.
- [x] Add `ReportingMetricsService` for period and estate aggregation.
- [x] Extend on-demand report response to include metrics payload.
- [x] Update design docs, users guide, roadmap, and this ExecPlan.
- [x] Run quality gates and record outcomes.

## Surprises & discoveries

- The Qdrant project-memory MCP tools are not exposed in this environment, so
  this implementation relied on repository docs and code context only.
- `generated_at` defaults to current time, so BDD period queries must use a
  dynamic "current period" window unless explicit timestamps are inserted.

## Decision log

1. **No `StatusModel` protocol change.**
   Metrics are exposed via optional `last_invocation_metrics` attributes on
   adapters and consumed with duck-typing in `ReportingService`.

2. **Metrics stored on `Report` rows.**
   Added nullable `model_latency_ms`, `prompt_tokens`, `completion_tokens`, and
   `total_tokens` columns directly on `reports`.

3. **Latency measured in service layer.**
   `ReportingService._invoke_with_retries()` uses `time.monotonic()` and merges
   adapter token metrics with measured latency.

4. **Operational telemetry via structured logging.**
   `ReportingEventLogger` emits `reporting.report.started`,
   `reporting.report.completed`, and `reporting.report.failed` events.

5. **Aggregation computed on demand.**
   `ReportingMetricsService` computes totals and latency profile for a period,
   with p95 latency computed in Python for portability.

## Outcomes & retrospective

Task 2.4.b completion criteria are met:

- Repository reports now persist latency and token metrics.
- Reporting lifecycle logs expose operational state and run-level metrics.
- Operators can query `ReportingMetricsService` snapshots for report counts,
  average/p95 latency, and total token usage.
- On-demand report API responses now include a `metrics` object.
- Unit and BDD tests cover adapter capture, persistence, logging,
  aggregation, and API serialization.

Primary implementation files:

- `ghillie/status/metrics.py`
- `ghillie/status/openai_client.py`
- `ghillie/status/mock.py`
- `ghillie/gold/storage.py`
- `ghillie/reporting/service.py`
- `ghillie/reporting/observability.py`
- `ghillie/reporting/metrics_service.py`
- `ghillie/api/gold/resources.py`

Primary test coverage added/updated:

- `tests/unit/status/test_invocation_metrics.py`
- `tests/unit/status/test_openai_parsing.py`
- `tests/unit/status/test_mock_status_model.py`
- `tests/unit/test_reporting_metrics_capture.py`
- `tests/unit/test_reporting_observability.py`
- `tests/unit/test_reporting_metrics_service.py`
- `tests/features/reporting_metrics.feature`
- `tests/features/steps/test_reporting_metrics_steps.py`
