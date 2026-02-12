# Provide an on-demand reporting entry-point

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`, and
`Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: DRAFT

## Purpose / big picture

Task 2.3.c adds an HTTP API endpoint so operators can trigger a fresh
repository report on demand — for example, to respond to a review request —
without waiting for the next scheduled run. After this change, an operator can
`POST /reports/repositories/{owner}/{name}`, and receive JSON report metadata
(200), a signal that no events exist in the window (204), or a clear error if
the repository is unknown (404). The rendered Markdown flows through the same
`ReportSink` as scheduled reports, so the file at
`{base_path}/{owner}/{name}/latest.md` is updated immediately.

This is the first database-connected endpoint in the Ghillie runtime. It
therefore also implements the modular `ghillie/api/` package structure
described in Section 8.4 of `docs/ghillie-design.md`, establishing session
middleware, error handling, and a dependency-injected application factory that
subsequent endpoints (CloudEvents ingestion, status query APIs) will reuse.

Success is observable when:

1. `POST /reports/repositories/{owner}/{name}` generates a report via
   `ReportingService.run_for_repository()` and returns JSON metadata (200).
2. The endpoint returns 204 when the repository exists but has no events.
3. The endpoint returns 404 when the repository slug is not in the Silver
   layer.
4. The rendered Markdown appears at the same filesystem path as scheduled
   reports.
5. Health endpoints (`/health`, `/ready`) continue to work unchanged.
6. The Granian entrypoint `ghillie.runtime:create_app` remains backwards
   compatible -- when `GHILLIE_DATABASE_URL` is not set, only health endpoints
   are registered.
7. All quality gates pass: `make check-fmt`, `make typecheck`, `make lint`,
   `make test`, `make markdownlint`, `make nixie`.

## Constraints

- Python 3.12, Falcon 4.x Asynchronous Server Gateway Interface (ASGI),
  SQLAlchemy 2.x async.
- Ruff linting with `max-args = 4` (PLR0913), `max-complexity = 9`, plus 70+
  other rules.
- Import conventions: `from __future__ import annotations`, `typing as typ`,
  `datetime as dt`, `collections.abc as cabc`.
- NumPy-style docstrings with Parameters/Returns/Raises sections.
- Frozen slots dataclasses for configuration and dependency injection.
- `@runtime_checkable` Protocol for ports.
- Test-driven development (TDD) required per `AGENTS.md`: write failing tests
  before implementation.
- Both unit tests (pytest) and behaviour-driven development (BDD) tests
  (pytest-bdd) required for new features.
- The existing `tests/unit/test_runtime.py` must continue to pass without
  modification.
- The Granian entrypoint string `ghillie.runtime:create_app` must continue to
  resolve to a callable that returns a Falcon ASGI app.
- No new external dependencies may be added.

## Tolerances (exception triggers)

- Scope: if implementation requires changes to more than 25 files or 2000
  lines of code (net), stop and escalate.
- Interface: if a public API signature in `ghillie/reporting/` must change,
  stop and escalate.
- Dependencies: if a new external dependency is required, stop and escalate.
- Iterations: if tests still fail after 5 attempts at fixing, stop and
  escalate.
- Ambiguity: if multiple valid interpretations exist and the choice materially
  affects the outcome, stop and present options with trade-offs.

## Risks

- Risk: Falcon `TestClient.simulate_*` methods are synchronous; using them
  inside `async def` tests may cause event loop conflicts. Severity: medium
  Likelihood: medium Mitigation: Use `falcon.testing.TestClient` only in
  synchronous tests (the existing pattern in `tests/unit/test_runtime.py`). For
  BDD steps that call `asyncio.run()` internally, this is safe. For any truly
  async integration tests, use `httpx.AsyncClient` with `ASGITransport`.

- Risk: The session middleware must not interfere with
  `ReportingService`'s own transaction management. Severity: high Likelihood:
  low Mitigation: The `ReportResource` uses the middleware session only for the
  repository slug lookup. `ReportingService` manages its own sessions via its
  injected `session_factory`. These are independent session instances.

- Risk: The `GHILLIE_STATUS_MODEL_BACKEND` env var may not be set in test
  environments, causing `create_status_model()` to raise. Severity: low
  Likelihood: medium Mitigation: Unit tests for the resource inject a mock
  `ReportingService` directly, bypassing the factory. BDD tests set the env var
  to `mock` or inject `MockStatusModel` directly.

## Progress

- [x] Write ExecPlan document
- [x] Write failing unit tests for session middleware
- [x] Write failing unit tests for error handling
- [x] Write failing unit tests for `ReportResource`
- [x] Write failing unit tests for modular `create_app()`
- [x] Write BDD feature and step definitions
- [x] Implement `ghillie/api/middleware.py`
- [x] Implement `ghillie/api/errors.py`
- [x] Implement `ghillie/api/health/resources.py`
- [x] Implement `ghillie/api/gold/resources.py`
- [x] Implement `ghillie/api/factory.py`
- [x] Implement `ghillie/api/app.py` and `ghillie/api/__init__.py`
- [x] Update `ghillie/runtime.py` to delegate to `ghillie.api`
- [x] Update `specs/openapi.yml` with new endpoint
- [x] Update `docs/users-guide.md` with on-demand reporting section
- [x] Update `docs/ghillie-design.md` Section 8.4
- [x] Mark Task 2.3.c done in `docs/roadmap.md`
- [x] All quality gates passed

## Surprises and discoveries

- Granian 1.7.6 does not compile on Python 3.14 due to PyO3 FFI
  incompatibilities. The `pyproject.toml` version constraint was relaxed from
  `<2.0.0` to allow granian 2.7.1 which supports Python 3.14.
- BDD integration tests needed recent-timestamp events (relative to
  `utcnow()`) because `run_for_repository` computes a 7-day window from the
  current time. Using fixed 2024 dates caused 204 responses.

## Decision log

1. **Modular API structure now, not deferred.** The design document
   (Section 8.4) calls for the `ghillie/api/` modular structure when
   database-connected endpoints are added. Task 2.3.c is the first such
   endpoint. Implementing the structure now avoids a second restructuring when
   CloudEvents ingestion (Task 4.1.a) or status query endpoints arrive. The
   existing `ghillie/runtime.py` delegates `create_app()` to
   `ghillie.api.app.create_app()` for backwards compatibility with the Granian
   entrypoint.

2. **Endpoint path: `POST /reports/repositories/{owner}/{name}`.** Operators
   identify repositories by GitHub slug (`owner/name`) rather than internal
   UUID. This matches the filesystem sink path convention
   (`{base_path}/{owner}/{name}/latest.md`), the catalogue notation, and is
   more discoverable for operators. The `POST` method is appropriate because
   the request triggers a side effect (report generation and persistence).

3. **Response codes: 200 / 204 / 404.** 200 with JSON report metadata when a
   report is generated. 204 when the repository exists but has no events in the
   current window. 404 when the owner/name pair is not found in the Silver
   layer.

4. **`ReportResource` does not use the middleware session for report
   generation.** The middleware attaches a request-scoped `AsyncSession` to
   `req.context.session` for the repository slug lookup. The `ReportingService`
   manages its own sessions via its injected `session_factory`. This separation
   avoids entangling the service's transaction lifecycle with the middleware's
   commit/rollback logic.

5. **`AppDependencies` dataclass groups constructor arguments.** The
   `create_app()` function accepts an optional `AppDependencies` frozen
   dataclass. When `None` or when `session_factory` is not provided, only
   health endpoints are registered. This keeps constructor arg counts under
   `max-args = 4`.

6. **`GHILLIE_DATABASE_URL` environment variable.** New env var for the
   runtime to know its database. When not set, the runtime operates in
   health-only mode (backwards compatible with existing container deployments
   that only need health probes).

7. **ReportingService factory in `ghillie/api/factory.py`.** A
   `build_reporting_service(session_factory)` function mirrors the Dramatiq
   actor's `_build_service()` pattern but accepts a pre-existing
   `session_factory` rather than a database URL string, avoiding engine/session
   factory duplication.

8. **Test approach.** Unit tests for the resource use
   `falcon.testing.TestClient` with a mock `ReportingService` injected into the
   resource, avoiding database setup. BDD tests use the existing
   `session_factory` fixture (py-pglite/SQLite) and `MockStatusModel` for full
   integration through the HTTP layer.

## Outcomes and retrospective

Implementation complete. The modular `ghillie/api/` package provides the first
database-connected HTTP endpoint. All existing tests continue to pass,
confirming backwards compatibility of the `ghillie.runtime:create_app` Granian
entrypoint. The `ReportResource` successfully reuses the existing
`ReportingService` pipeline for on-demand generation.

## Context and orientation

### Existing structures

The Ghillie codebase follows a Medallion architecture (Bronze/Silver/Gold) with
hexagonal ports-and-adapters patterns.

**Reporting service** (`ghillie/reporting/service.py`): `ReportingService`
orchestrates the full workflow -- computing the next reporting window, building
an evidence bundle from Silver layer data, invoking the large language model
(LLM) status model, and persisting the report to the Gold layer. The key method
is `run_for_repository(repository_id, as_of=None) -> Report | None`. When a
`ReportSink` is injected, the service also renders and writes Markdown via the
sink.

**ReportingServiceDependencies** (`ghillie/reporting/service.py`): Frozen
dataclass grouping `session_factory`, `evidence_service`, and `status_model`.

**ReportingConfig** (`ghillie/reporting/config.py`): Frozen dataclass with
`window_days` and `report_sink_path`, loadable from environment variables via
`from_env()`.

**Report model** (`ghillie/gold/storage.py`): SQLAlchemy model with `id` (UUID
string), `scope`, `repository_id`, `window_start`, `window_end`,
`generated_at`, `model`, `human_text`, `machine_summary` (JSON dict).

**Repository model** (`ghillie/silver/storage.py`): SQLAlchemy model with `id`,
`github_owner`, `github_name`, `slug` property, and a unique constraint on
`(github_owner, github_name)`.

**Runtime** (`ghillie/runtime.py`): Current monolithic app factory with
`create_app()` returning `falcon.asgi.App` with `/health` and `/ready` routes.
The Granian entrypoint is `ghillie.runtime:create_app`. No database-connected
endpoints exist yet.

**Actor pattern** (`ghillie/reporting/actor.py`):
`_build_service(database_url)` constructs a `ReportingService` from environment
variables and a database URL, creating the session factory, evidence service,
status model, and optional filesystem sink.

**ReportSink** (`ghillie/reporting/sink.py`): `@runtime_checkable` Protocol
with `write_report(markdown, *, metadata)`. `FilesystemReportSink`
(`ghillie/reporting/filesystem_sink.py`) implements it, writing to
`{base_path}/{owner}/{name}/latest.md` and dated archive files.

**Test fixtures** (`tests/conftest.py`): `session_factory` fixture provides an
`async_sessionmaker[AsyncSession]` backed by py-pglite Postgres (with SQLite
fallback). All storage layers are initialized.

**BDD pattern** (`tests/features/steps/test_reporting_workflow_steps.py`):
TypedDict context class, `@scenario` wrappers, `asyncio.run()` in step
functions, `session_factory` fixture from conftest.

### Key patterns to follow

1. Configuration: `@dc.dataclass(frozen=True, slots=True)` with `from_env()`.
2. Protocols: `@typ.runtime_checkable` Protocol classes.
3. Constructor injection: optional parameters with `None` defaults.
4. Import conventions: `from __future__ import annotations`, `typing as typ`,
   `datetime as dt`, `collections.abc as cabc`.
5. Docstrings: NumPy-style.
6. `__all__` exports: explicit in package `__init__.py`.
7. Test-first: write failing tests before implementation.
8. BDD + unit: both pytest-bdd scenarios and unit tests for new features.

### Files to reference

- `ghillie/runtime.py` -- current app factory to evolve
- `ghillie/reporting/service.py` -- `ReportingService` to reuse
- `ghillie/reporting/actor.py` -- `_build_service()` pattern to adapt
- `ghillie/reporting/config.py` -- `ReportingConfig.from_env()`
- `ghillie/reporting/errors.py` -- `ReportingError` base class
- `ghillie/silver/storage.py` -- `Repository` model for slug lookup
- `ghillie/gold/storage.py` -- `Report` model for response serialization
- `ghillie/reporting/sink.py` -- `ReportSink` protocol
- `ghillie/reporting/filesystem_sink.py` -- `FilesystemReportSink`
- `ghillie/status/factory.py` -- `create_status_model()`
- `ghillie/evidence/service.py` -- `EvidenceBundleService`
- `tests/unit/test_runtime.py` -- existing health endpoint test pattern
- `tests/features/steps/test_reporting_workflow_steps.py` -- BDD step pattern
- `tests/conftest.py` -- `session_factory` fixture
- `docs/async-sqlalchemy-with-pg-and-falcon.md` -- session middleware guide
- `docs/testing-async-falcon-endpoints.md` -- testing guide

## Plan of work

### Stage A: Write failing tests (TDD, no implementation code)

Write all test files before any implementation. Tests will initially fail
because the modules they import do not yet exist.

**A1. Unit tests for session middleware** (`tests/unit/test_api_middleware.py`).

Test the `SQLAlchemySessionManager` in isolation using `AsyncMock` for the
session factory and session:

- `test_process_request_attaches_session_to_context` -- after
  `process_request`, `req.context.session` is set.
- `test_process_response_commits_on_success` -- when `req_succeeded` is True
  and status is 2xx, `session.commit()` is called.
- `test_process_response_rolls_back_on_error_status` -- when status is 4xx/5xx,
  `session.rollback()` is called.
- `test_process_response_closes_session_always` -- `session.close()` is called
  regardless of outcome.

**A2. Unit tests for error handlers** (`tests/unit/test_api_errors.py`).

- `test_repository_not_found_returns_404` -- a `RepositoryNotFoundError`
  is translated to HTTP 404 with JSON body.
- `test_value_error_returns_400` -- a `ValueError` returns HTTP 400.

**A3. Unit tests for `ReportResource`**
(`tests/unit/test_api_report_resource.py`).

Test using `falcon.testing.TestClient` with a mock `ReportingService` injected
into the resource (no database):

- `test_post_generates_report_and_returns_200` -- successful generation returns
  200 with JSON metadata.
- `test_post_returns_204_when_no_events` -- when `run_for_repository` returns
  None, returns 204.
- `test_post_returns_404_for_unknown_repository` -- when the slug does not
  match any Silver record, returns 404.
- `test_response_includes_report_fields` -- 200 JSON body includes
  `report_id`, `repository`, `window_start`, `window_end`, `generated_at`,
  `status`, `model`.
- `test_post_returns_json_content_type` -- Content-Type is
  `application/json`.

**A4. Unit tests for modular `create_app()`** (`tests/unit/test_api_app.py`).

- `test_create_app_returns_falcon_app` -- returns a `falcon.asgi.App`.
- `test_app_has_health_and_ready_routes` -- `/health` and `/ready` respond
  with 200.
- `test_app_has_report_route_with_deps` -- with `AppDependencies`, the report
  route is registered.
- `test_create_app_without_deps_omits_report_route` -- without deps, POST to
  report path returns 404.

**A5. BDD feature** (`tests/features/on_demand_report.feature` and
`tests/features/steps/test_on_demand_report_steps.py`).

Three scenarios:

1. "Generate a report for a repository with events" -- given a repository
   with ingested events and the API running, POST returns 200 with report
   metadata and a Gold report exists in the database.
2. "Return 204 when no events in the reporting window" -- given a
   repository without events, POST returns 204.
3. "Return 404 for an unknown repository" -- POST for `unknown/repo`
   returns 404.

Step definitions follow the pattern in
`tests/features/steps/test_reporting_workflow_steps.py`: TypedDict context,
`asyncio.run()` in steps, `session_factory` fixture.

### Stage B: Implement the `ghillie/api/` package

**B1. `ghillie/api/middleware.py`**: `SQLAlchemySessionManager` with
`process_request` (attaches session to `req.context.session`) and
`process_response` (commit on success, rollback on error, always close).
Follows the pattern from `docs/async-sqlalchemy-with-pg-and-falcon.md`.

**B2. `ghillie/api/errors.py`**: `RepositoryNotFoundError` exception (stores
`owner` and `name`). Async error handler functions for Falcon's
`add_error_handler()`: `handle_repository_not_found` (404),
`handle_value_error` (400).

**B3. `ghillie/api/health/__init__.py` and `ghillie/api/health/resources.py`**:
Move `HealthResource` and `ReadyResource` from `ghillie/runtime.py`. Re-export
from `ghillie/runtime.py` for backwards compatibility.

**B4. `ghillie/api/gold/__init__.py` and `ghillie/api/gold/resources.py`**:
`ReportResource` accepting `reporting_service` directly. The `on_post` method:

1. Opens a session from `req.context.session` and queries `Repository` by
   `github_owner == owner AND github_name == name`.
2. If not found, raises `RepositoryNotFoundError(owner, name)`.
3. Calls `await self._reporting_service.run_for_repository(repository.id)`.
4. If None (no events), sets `resp.status = falcon.HTTP_204`.
5. If Report, serializes to JSON: `report_id`, `repository` (slug),
   `window_start`, `window_end`, `generated_at`, `status` (from
   `machine_summary`), `model`.

**B5. `ghillie/api/factory.py`**: `build_reporting_service(session_factory)`
creates `EvidenceBundleService`, calls `create_status_model()`, reads
`ReportingConfig.from_env()`, optionally creates `FilesystemReportSink`,
assembles `ReportingServiceDependencies`, returns `ReportingService`.

**B6. `ghillie/api/app.py`**: `AppDependencies` frozen dataclass with optional
`session_factory` and `reporting_service`. `create_app(dependencies)` always
registers `/health` and `/ready`. When deps have session_factory and
reporting_service, adds `SQLAlchemySessionManager` middleware and
`/reports/repositories/{owner}/{name}` route. Registers error handlers.

**B7. `ghillie/api/__init__.py`**: Package init exporting `create_app`.

### Stage C: Update runtime.py

**C1.** Replace inline `HealthResource`, `ReadyResource`, and `create_app()` in
`ghillie/runtime.py` with imports from `ghillie.api`. The module-level
`create_app()` reads `GHILLIE_DATABASE_URL` from the environment. When set, it
constructs `AppDependencies` with a session factory and reporting service. When
not set, it delegates to `ghillie.api.app.create_app()` without deps
(health-only mode). `HealthResource` and `ReadyResource` remain importable from
`ghillie.runtime` for backwards compatibility.

### Stage D: Documentation and specification updates

**D1. `specs/openapi.yml`**: Add `POST /reports/repositories/{owner}/{name}`
with path parameters, response schemas (`ReportMetadata`, `ErrorResponse`), and
tags.

**D2. `docs/users-guide.md`**: Add "On-demand report generation (Phase 2.3.c)"
section with curl example, response format, required env vars, error responses.

**D3. `docs/ghillie-design.md`**: Update Section 8.4 noting the modular API
structure is now partially implemented.

**D4. `docs/roadmap.md`**: Mark Task 2.3.c as done with implementation note.

### Stage E: Quality gates

Run all quality gates and fix any issues:

    set -o pipefail; make check-fmt 2>&1 | tee /tmp/ghillie-check-fmt.log
    set -o pipefail; make typecheck 2>&1 | tee /tmp/ghillie-typecheck.log
    set -o pipefail; make lint 2>&1 | tee /tmp/ghillie-lint.log
    set -o pipefail; make test 2>&1 | tee /tmp/ghillie-test.log
    set -o pipefail; make markdownlint 2>&1 | tee /tmp/ghillie-mdlint.log
    set -o pipefail; make nixie 2>&1 | tee /tmp/ghillie-nixie.log

## Concrete steps

1. Create `tests/unit/test_api_middleware.py` with 4 tests (Stage A1).
2. Create `tests/unit/test_api_errors.py` with 2 tests (Stage A2).
3. Create `tests/unit/test_api_report_resource.py` with 5 tests (Stage A3).
4. Create `tests/unit/test_api_app.py` with 4 tests (Stage A4).
5. Create `tests/features/on_demand_report.feature` and
   `tests/features/steps/test_on_demand_report_steps.py` (Stage A5).
6. Create `ghillie/api/__init__.py`, `ghillie/api/health/__init__.py`,
   `ghillie/api/gold/__init__.py` (package inits).
7. Create `ghillie/api/middleware.py` (Stage B1).
8. Create `ghillie/api/errors.py` (Stage B2).
9. Create `ghillie/api/health/resources.py` (Stage B3).
10. Create `ghillie/api/gold/resources.py` (Stage B4).
11. Create `ghillie/api/factory.py` (Stage B5).
12. Create `ghillie/api/app.py` (Stage B6).
13. Modify `ghillie/runtime.py` (Stage C1).
14. Update `specs/openapi.yml` (Stage D1).
15. Update `docs/users-guide.md` (Stage D2).
16. Update `docs/ghillie-design.md` (Stage D3).
17. Update `docs/roadmap.md` (Stage D4).
18. Run quality gates (Stage E).

## Validation and acceptance

The change is accepted when:

1. `POST /reports/repositories/{owner}/{name}` generates a report using
   `ReportingService.run_for_repository()` and returns JSON metadata (200).
2. The endpoint returns 204 when no events exist in the reporting window.
3. The endpoint returns 404 when the repository is not found.
4. Rendered Markdown goes through the same `ReportSink` as scheduled reports.
5. Health endpoints continue to work unchanged.
6. `ghillie.runtime:create_app` remains backwards compatible.
7. OpenAPI specification documents the new endpoint.
8. Users' guide documents the new feature.
9. Design document records the modular API implementation.
10. Roadmap marks Task 2.3.c as complete.
11. All quality gates pass.

Expected test output:

    $ pytest tests/unit/test_api_middleware.py -v
    ~4 passed

    $ pytest tests/unit/test_api_errors.py -v
    ~2 passed

    $ pytest tests/unit/test_api_report_resource.py -v
    ~5 passed

    $ pytest tests/unit/test_api_app.py -v
    ~4 passed

    $ pytest tests/features -k on_demand_report
    ~3 passed

## Idempotence and recovery

All steps are safe to rerun:

- File creation is additive (new modules).
- `ghillie/runtime.py` modification preserves backward compatibility.
- Tests can be run incrementally.
- Quality gates are read-only validations.

If tests fail:

1. Check that `session_factory` fixture provides database access for BDD
   tests.
2. Ensure `GHILLIE_STATUS_MODEL_BACKEND=mock` is set or `MockStatusModel` is
   injected directly.
3. Verify `Repository` unique constraint (`github_owner`, `github_name`) is
   available for slug-based lookups.
4. Check that `falcon.testing.TestClient` is used only in synchronous test
   functions (not inside `async def` tests).

## Artifacts and notes

### 200 response body

    {
      "report_id": "550e8400-e29b-41d4-a716-446655440000",
      "repository": "acme/widget",
      "window_start": "2024-07-07T00:00:00+00:00",
      "window_end": "2024-07-14T00:00:00+00:00",
      "generated_at": "2024-07-14T12:00:00+00:00",
      "status": "on_track",
      "model": "mock-v1"
    }

### 404 response body

    {
      "title": "Repository not found",
      "description": "No repository matching 'unknown/repo' exists."
    }

### Modular API directory structure

    ghillie/api/
      __init__.py          # Package root, exports create_app
      app.py               # Application factory with AppDependencies
      middleware.py         # SQLAlchemySessionManager
      errors.py            # RepositoryNotFoundError + Falcon error handlers
      factory.py           # build_reporting_service(session_factory)
      health/
        __init__.py
        resources.py       # HealthResource, ReadyResource
      gold/
        __init__.py
        resources.py       # ReportResource

## Interfaces and dependencies

### New public API

- `ghillie.api.create_app` -- application factory
- `ghillie.api.app.AppDependencies` -- frozen dataclass for app dependencies
- `ghillie.api.middleware.SQLAlchemySessionManager` -- request-scoped session
- `ghillie.api.gold.resources.ReportResource` -- on-demand report endpoint
- `ghillie.api.errors.RepositoryNotFoundError` -- domain exception
- `ghillie.api.health.resources.HealthResource` -- health probe (moved)
- `ghillie.api.health.resources.ReadyResource` -- readiness probe (moved)
- `ghillie.api.factory.build_reporting_service` -- service factory

### Modified public API

- `ghillie.runtime.create_app` -- now delegates to `ghillie.api.app.create_app`
- `ghillie.runtime.main` -- reads `GHILLIE_DATABASE_URL`, constructs deps

### Environment variables

- `GHILLIE_DATABASE_URL` -- new; SQLAlchemy URL for the runtime database.
  When not set, health-only mode.
- `GHILLIE_STATUS_MODEL_BACKEND` -- existing; required when database URL set.
- `GHILLIE_REPORT_SINK_PATH` -- existing; optional filesystem path.

### External dependencies

None new. Uses existing `falcon`, `sqlalchemy`, and stdlib only.

### Downstream consumers

- Task 4.1.a (CloudEvents ingestion) will add
  `ghillie/api/bronze/resources.py`.
- Task 5.1.a (report retrieval) will add read-only Gold endpoints.

## Critical files

| File                                                  | Action | Purpose                              |
| ----------------------------------------------------- | ------ | ------------------------------------ |
| `ghillie/api/__init__.py`                             | Create | Package with `create_app` export     |
| `ghillie/api/app.py`                                  | Create | App factory with `AppDependencies`   |
| `ghillie/api/middleware.py`                           | Create | Session manager middleware           |
| `ghillie/api/errors.py`                               | Create | Domain exceptions and error handlers |
| `ghillie/api/factory.py`                              | Create | `build_reporting_service()`          |
| `ghillie/api/health/__init__.py`                      | Create | Health subpackage                    |
| `ghillie/api/health/resources.py`                     | Create | Health/ready resources               |
| `ghillie/api/gold/__init__.py`                        | Create | Gold subpackage                      |
| `ghillie/api/gold/resources.py`                       | Create | `ReportResource`                     |
| `ghillie/runtime.py`                                  | Modify | Delegate to `ghillie.api`            |
| `tests/unit/test_api_middleware.py`                   | Create | Middleware unit tests                |
| `tests/unit/test_api_errors.py`                       | Create | Error handler tests                  |
| `tests/unit/test_api_report_resource.py`              | Create | Resource unit tests                  |
| `tests/unit/test_api_app.py`                          | Create | App factory tests                    |
| `tests/features/on_demand_report.feature`             | Create | BDD scenarios                        |
| `tests/features/steps/test_on_demand_report_steps.py` | Create | BDD steps                            |
| `specs/openapi.yml`                                   | Modify | Add report endpoint spec             |
| `docs/users-guide.md`                                 | Modify | Document on-demand reporting         |
| `docs/ghillie-design.md`                              | Modify | Update Section 8.4                   |
| `docs/roadmap.md`                                     | Modify | Mark Task 2.3.c done                 |
