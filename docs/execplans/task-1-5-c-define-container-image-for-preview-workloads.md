# Task 1.5.c: Define container image for preview workloads

This ExecPlan is a living document. The sections Constraints, Tolerances,
Risks, Progress, Surprises & Discoveries, Decision Log, and Outcomes &
Retrospective must be kept up to date as work proceeds.

Status: COMPLETE

This document must be maintained in accordance with
`.claude/skills/execplans/execplans.md`.

## Purpose / Big Picture

Provide a container image that deploys Ghillie into Kubernetes environments.
After this change, operators can build a Docker image locally, import it into
k3d, and deploy via the existing Helm chart. The container starts a Falcon ASGI
server exposing `/health` and `/ready` endpoints on port 8080, proving the
runtime entrypoint works and enabling Kubernetes liveness/readiness probes.

Observable outcome: Running `docker build -t ghillie:local .` produces an
image. Running the image logs a startup message and responds to HTTP requests
on port 8080 with health status.

## Constraints

- Python 3.12+ as specified in `pyproject.toml`.
- No new runtime dependencies beyond what's in `pyproject.toml` (Falcon is not
  currently listed, so it must be added).
- The Dockerfile must use multi-stage builds per the design sketch in
  `docs/local-k8s-preview-design.md`.
- The runtime must use a non-root user for security.
- Configuration must be environment-variable driven (no hardcoded values).
- All quality gates must pass: `make check-fmt`, `make lint`, `make typecheck`,
  `make test`.
- Tests must include both unit tests (pytest) and behaviour-driven development
  (BDD) tests (pytest-bdd).

## Tolerances (Exception Triggers)

- Scope: If implementation requires changes to more than 15 files, stop and
  escalate.
- Dependencies: Adding Falcon (and Granian for ASGI) is expected; any other new
  dependencies require escalation.
- Iterations: If tests still fail after 3 attempts to fix, stop and escalate.
- Ambiguity: If the Helm chart requires modifications beyond
  `livenessProbe`/`readinessProbe` configuration, escalate.

## Risks

- Risk: Granian may have platform-specific build issues in the container.
  Severity: medium. Likelihood: low. Mitigation: Use standard Python slim
  image; fall back to uvicorn if needed.

- Risk: Port 8080 conflicts with other local services during testing.
  Severity: low. Likelihood: low. Mitigation: Document port usage; tests use
  ephemeral ports.

- Risk: Non-root user may not have write access to required directories.
  Severity: medium. Likelihood: medium. Mitigation: Create writable directories
  in Dockerfile; document requirements.

## Progress

- [x] (2026-01-07) Stage A: Research and scaffolding
  - [x] Add Falcon and Granian dependencies to pyproject.toml
  - [x] Create docker/ directory structure
  - [x] Write failing unit tests for runtime module
  - [x] Write failing BDD feature for container startup
- [x] (2026-01-07) Stage B: Implement runtime module
  - [x] Create ghillie/runtime.py with Falcon app
  - [x] Implement /health endpoint
  - [x] Implement /ready endpoint
  - [x] Add main() function to start Granian server
  - [x] Verify unit tests pass (11 tests)
- [x] (2026-01-07) Stage C: Implement Dockerfile and entrypoint
  - [x] Create docker/entrypoint.sh
  - [x] Create Dockerfile with multi-stage build
  - [x] Add Makefile targets for docker-build and docker-run
  - [x] Verify image builds and runs locally
- [x] (2026-01-07) Stage D: Documentation and cleanup
  - [x] Update users-guide.md with container usage
  - [x] No deviations from local-k8s-preview-design.md
  - [x] Update roadmap.md to mark task complete
  - [x] Verify all quality gates pass (329 tests passed, lint/typecheck clean)
  - [x] Commit changes

## Surprises & Discoveries

- Observation: Docstring formatting requires specific NumPy style without
  colons on section headers. The ruff D406 rule enforces this. Evidence:
  Initial implementation had "Parameters:" which caused lint failures. Impact:
  Simplified docstrings to avoid formal NumPy sections for method-level docs.

- Observation: Type checker warning for `falcon.asgi.App` submodule access.
  Evidence: type-checker warning "possibly-missing-attribute" for
  falcon.asgi.App. Impact: Added explicit `import falcon.asgi` to test file to
  satisfy type checker.

## Decision Log

- Decision: Use Falcon for HTTP endpoints.
  Rationale: Falcon is the framework specified in the architecture design
  documents (docs/async-sqlalchemy-with-pg-and-falcon.md). It aligns with the
  existing async-first architecture. Date/Author: 2026-01-07 / Planning phase

- Decision: Use Granian as ASGI server.
  Rationale: Specified in docs/ghillie-bronze-silver-architecture-design.md as
  the ASGI application server for Ghillie. Date/Author: 2026-01-07 / Planning
  phase

- Decision: Implement health endpoint only (not full worker logic).
  Rationale: User preference to keep initial implementation minimal. Full
  worker logic deferred to future tasks. Date/Author: 2026-01-07 / User
  clarification

## Outcomes & Retrospective

Task 1.5.c is complete. The implementation delivers:

- Multi-stage Dockerfile with Python 3.12-slim base and non-root user
- Runtime module (ghillie/runtime.py) with Falcon ASGI app
- /health and /ready endpoints for Kubernetes probes
- Container entrypoint script with signal handling
- Makefile targets for docker-build and docker-run
- 11 new tests (9 unit, 2 BDD) for runtime module
- Documentation in users-guide.md

The original purpose was achieved: a local build produces an image that starts
the runtime entrypoint without errors. All quality gates pass (329 tests, lint,
typecheck).

Lessons learned:

- Start with simplified docstrings to avoid NumPy section formatting issues.
- Import submodules explicitly to satisfy type checkers.

## Context and Orientation

The Ghillie project is a Python 3.12+ application that ingests GitHub events
and produces status reports. The codebase follows a Medallion architecture with
Bronze (raw events), Silver (entities), and Gold (reports) layers.

Key files for this task:

- `pyproject.toml`: Package configuration and dependencies
- `docs/local-k8s-preview-design.md`: Design document with Dockerfile sketch
- `charts/ghillie/values.yaml`: Helm chart configuration (port 8080,
  command/args)
- `ghillie/__init__.py`: Package root

The Helm chart (`charts/ghillie/`) is already implemented with support for
custom commands, args, and optional liveness/readiness probes. The chart
expects the container to:

- Listen on port 8080 (configurable via `service.port`)
- Read secrets from environment variables (DATABASE_URL, VALKEY_URL, etc.)
- Support command/args overrides for different runtime modes

## Plan of Work

### Stage A: Research and scaffolding

Add runtime dependencies to pyproject.toml. Falcon provides the ASGI web
framework; Granian serves as the ASGI server. Both are async-compatible and
align with the architecture documents.

Create the docker/ directory to hold the entrypoint script, following the
design sketch convention.

Write failing tests first (test-driven development (TDD) approach per AGENTS.md
guidelines):

- Unit tests in `tests/unit/test_runtime.py` for health resources
- BDD feature in `tests/features/runtime.feature` for container startup
  behaviour

### Stage B: Implement runtime module

Create `ghillie/runtime.py` with:

1. A `HealthResource` class with `on_get` method returning JSON
   `{"status": "ok"}`
2. A `ReadyResource` class with `on_get` method returning JSON
   `{"status": "ready"}`
3. A `create_app()` function that builds the Falcon ASGI app
4. A `main()` function that starts Granian on `0.0.0.0:8080`

The module should read configuration from environment:

- `GHILLIE_HOST`: Bind address (default: 0.0.0.0)
- `GHILLIE_PORT`: Listen port (default: 8080)
- `GHILLIE_LOG_LEVEL`: Log level (default: INFO)

### Stage C: Implement Dockerfile and entrypoint

Create `docker/entrypoint.sh`:

- Set up signal handling for graceful shutdown
- Execute the command passed as arguments
- Make it executable and POSIX-compliant

Create `Dockerfile` following the design sketch:

    # Build stage
    FROM python:3.12-slim AS build
    WORKDIR /build
    RUN pip install --upgrade pip
    COPY pyproject.toml README.md /build/
    COPY ghillie /build/ghillie
    RUN pip wheel --wheel-dir /wheels .

    # Runtime stage
    FROM python:3.12-slim
    WORKDIR /app
    RUN useradd --create-home --shell /bin/bash ghillie
    COPY --from=build /wheels /wheels
    RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
    COPY docker/entrypoint.sh /usr/local/bin/ghillie-entrypoint
    RUN chmod +x /usr/local/bin/ghillie-entrypoint
    USER ghillie
    EXPOSE 8080
    ENTRYPOINT ["ghillie-entrypoint"]
    CMD ["python", "-m", "ghillie.runtime"]

Add Makefile targets:

- `docker-build`: Build the image with tag `ghillie:local`
- `docker-run`: Run the image for local testing

### Stage D: Documentation and cleanup

Update `docs/users-guide.md` with a new section for container usage, including:

- Building the image
- Running locally
- Environment variable configuration
- Health check endpoints

Update `docs/local-k8s-preview-design.md` if any design deviations occurred.

Mark Task 1.5.c as complete in `docs/roadmap.md`.

Run all quality gates and commit.

## Concrete Steps

All commands run from repository root `/data/leynos/Projects/ghillie/`.

### Stage A

1. Edit pyproject.toml to add dependencies:

       dependencies = [
           …
           "falcon>=4.0.0",
           "granian>=1.0.0",
       ]

2. Sync dependencies:

       make build

3. Create docker directory:

       mkdir -p docker

4. Create test files (content detailed in Stage B):
   - `tests/unit/test_runtime.py`
   - `tests/features/runtime.feature`
   - `tests/features/steps/test_runtime_steps.py`

5. Run tests (expect failures):

       UV_CACHE_DIR=.uv-cache UV_TOOL_DIR=.uv-tools uv run pytest tests/unit/test_runtime.py -v 2>&1 | tee /tmp/test-runtime.log

### Stage B

1. Create `ghillie/runtime.py` with the runtime module.

2. Run unit tests (expect pass):

       UV_CACHE_DIR=.uv-cache UV_TOOL_DIR=.uv-tools uv run pytest tests/unit/test_runtime.py -v 2>&1 | tee /tmp/test-runtime.log

3. Run full test suite:

       make test 2>&1 | tee /tmp/test-full.log

### Stage C

1. Create `docker/entrypoint.sh`.

2. Create `Dockerfile`.

3. Build the image:

       docker build -t ghillie:local . 2>&1 | tee /tmp/docker-build.log

   Expected: Build succeeds with "Successfully tagged ghillie:local"

4. Run the image:

       docker run --rm -p 8080:8080 ghillie:local &
       sleep 2
       curl -s http://localhost:8080/health
       docker stop $(docker ps -q --filter ancestor=ghillie:local)

   Expected: `{"status": "ok"}`

5. Add Makefile targets and verify:

       make docker-build

### Stage D

1. Update documentation files.

2. Run all quality gates:

       make check-fmt 2>&1 | tee /tmp/check-fmt.log
       make lint 2>&1 | tee /tmp/lint.log
       make typecheck 2>&1 | tee /tmp/typecheck.log
       make test 2>&1 | tee /tmp/test.log

   Expected: All pass with exit code 0.

3. Commit changes:

       git add -A
       git commit -m "Add container image and runtime entrypoint for preview workloads

       - Add Dockerfile with multi-stage build (Python 3.12-slim)
       - Add ghillie/runtime.py with Falcon ASGI app
       - Implement /health and /ready endpoints for Kubernetes probes
       - Add docker/entrypoint.sh for container startup
       - Add Makefile targets: docker-build, docker-run
       - Add unit tests and BDD tests for runtime module

       Task 1.5.c completion criteria: A local build produces an image that
       starts the runtime entrypoint without errors when deployed.

       Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"

## Validation and Acceptance

Quality criteria:

- Tests: `make test` passes; new tests in `test_runtime.py` and BDD runtime
  feature pass
- Lint/typecheck: `make check-fmt`, `make lint`, `make typecheck` all pass
- Container: `docker build -t ghillie:local .` succeeds
- Runtime: Container responds to `curl http://localhost:8080/health` with
  `{"status": "ok"}`

Quality method:

1. Run `make all` to verify build, format, lint, typecheck, and tests.
2. Run `docker build -t ghillie:local .` to verify image builds.
3. Run `docker run --rm -p 8080:8080 ghillie:local` and verify health endpoint.

Acceptance behaviour:

- Running `docker build -t ghillie:local .` produces an image tagged
  `ghillie:local` without errors.
- Running the image starts a server that logs a startup message.
- `GET /health` returns HTTP 200 with `{"status": "ok"}`.
- `GET /ready` returns HTTP 200 with `{"status": "ready"}`.
- The container runs as non-root user `ghillie`.

## Idempotence and Recovery

All stages are idempotent:

- Stage A: Re-running `make build` is safe; pip resolves dependencies
  idempotently.
- Stage B: File writes are idempotent; tests can be re-run.
- Stage C: Docker build uses caching; rebuild is safe.
- Stage D: Documentation updates are idempotent; commits can be amended if
  needed.

Recovery:

- If docker build fails, check logs in `/tmp/docker-build.log`.
- If tests fail, check logs in `/tmp/test-*.log`.
- To reset: `docker rmi ghillie:local` and rebuild.

## Artifacts and Notes

Expected file structure after completion:

    ghillie/
      runtime.py              # New: Falcon ASGI app with health endpoints
    docker/
      entrypoint.sh           # New: Container entrypoint script
    Dockerfile                # New: Multi-stage build
    tests/
      unit/
        test_runtime.py       # New: Unit tests for runtime module
      features/
        runtime.feature       # New: BDD feature for container behaviour
        steps/
          test_runtime_steps.py  # New: BDD step definitions

## Interfaces and Dependencies

New dependencies in pyproject.toml:

- `falcon>=4.0.0`: ASGI web framework
- `granian>=1.0.0`: ASGI server

New module `ghillie/runtime.py`:

    # Type stubs for the runtime module
    import falcon.asgi

    class HealthResource:
        async def on_get(
            self,
            req: falcon.asgi.Request,
            resp: falcon.asgi.Response,
        ) -> None: …

    class ReadyResource:
        async def on_get(
            self,
            req: falcon.asgi.Request,
            resp: falcon.asgi.Response,
        ) -> None: …

    def create_app() -> falcon.asgi.App: …

    def main() -> None: …

Environment variables:

- `GHILLIE_HOST`: Bind address (default: `0.0.0.0`)
- `GHILLIE_PORT`: Listen port (default: `8080`)
- `GHILLIE_LOG_LEVEL`: Log level (default: `INFO`)
