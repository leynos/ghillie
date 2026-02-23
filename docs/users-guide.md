# ghillie Users' Guide

## Estate catalogue (Phase 1.1)

Ghillie now ships a YAML 1.2 catalogue describing programmes, projects,
components, repositories, and their relationships. Catalogue files are
validated with `msgspec` and exposed as a JSON Schema for external linters.

### Authoring a catalogue

- Use lowercase, dash-separated keys for programmes, projects, and components
  (for example, `wildside-engine`). Keys must be unique across the estate.
- Components may omit `repository` when they represent planned work. When
  present, repositories require `owner`, `name`, and `default_branch`.
- Capture relationships with `depends_on`, `blocked_by`, and
  `emits_events_to`. Each entry includes the target `component` and an optional
  `kind` (`runtime`, `dev`, `test`, `ops`) plus a short rationale.
- Configure per-project noise filters (`ignore_authors`, `ignore_labels`,
  `ignore_paths`, `ignore_title_prefixes`) and status preferences under `noise`
  and `status`. Set `noise.enabled: false` to disable all filters for a
  project, or use `noise.toggles.*` to disable individual filters without
  deleting the configured values. Setting `summarise_dependency_prs: false`
  signals that dependency update pull requests should be ignored in downstream
  summaries.
- Record documentation paths at both project level (`documentation_paths`) and
  per repository (`repository.documentation_paths`) so roadmaps and ADRs are
  discoverable to ingestion and summarization jobs.
- See `examples/wildside-catalogue.yaml` for a complete multi-repository
  project with planned components and cross-project dependencies.

### Validating a catalogue

The catalogue linter enforces YAML 1.2 semantics (strings like `on` remain
strings) and referential integrity between components.

1. Generate schema and JSON artefacts from a catalogue file:

   ```bash
   python -m ghillie.catalogue.cli examples/wildside-catalogue.yaml \
     --schema-out schemas/catalogue.schema.json \
     --json-out .cache/catalogue.json
   ```

2. Validate against the JSON Schema with `pajv`:

   ```bash
   pajv -s schemas/catalogue.schema.json -d .cache/catalogue.json
   ```

3. A non-zero exit code indicates structural errors, such as missing
   components in dependency lists or duplicate keys.

### Example: Wildside

The catalogue example models Wildside as a multi-repository project:

- `leynos/wildside` (core API) depends on `wildside-engine` and df12 shared
  libraries (`ortho-config`, `pg-embedded-setup-unpriv`, `rstest-bdd`).
- `leynos/wildside-engine` underpins the core service and is blocked by
  shared configuration rollout.
- `leynos/wildside-mockup` models UI experiments and receives events from the
  core service.
- `wildside-ingestion` is marked `lifecycle: planned` to represent work with
  no repository yet.

Noise controls ignore dependency bots and generated documentation paths, so the
ingestion pipeline can focus on meaningful events.

### Importing a catalogue into the database

The catalogue importer reconciles the YAML file into relational tables for
estates, projects, components, repositories, and component edges. Imports run
inside a single transaction: invalid catalogues fail fast and do not leave
partial rows behind. Re-running the same commit is idempotent and will prune
entries removed from the source catalogue.

Project noise filters, status preferences, and documentation paths are
persisted alongside projects and repositories, so ingestion and reporting
services can consume them without parsing YAML at runtime.

> Operational note: existing deployments must add a JSON
> `documentation_paths` column to the `repositories` table before enabling
> this feature because `Base.metadata.create_all` will not alter existing
> tables in place.

Example: load the example catalogue into a SQLite database using the
asynchronous importer:

```python
import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy import select

from ghillie.catalogue import CatalogueImporter, init_catalogue_storage


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///catalogue.db")
    await init_catalogue_storage(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    importer = CatalogueImporter(session_factory, estate_key="wildside")
    await importer.import_path(Path("examples/wildside-catalogue.yaml"), commit_sha="abc123")


asyncio.run(main())
```

In deployments that already run Dramatiq workers, use the
`ghillie.catalogue.importer.import_catalogue_job` actor. It accepts the
catalogue path, database URL, estate key, optional estate name, and commit SHA
so scheduling systems can enqueue work without importing Python modules.

## Bronze raw event store (Phase 1.2)

The Bronze layer retains unmodified GitHub payloads, so Silver transforms can
be replayed deterministically. Events are written to the `raw_events` table
with:

- `source_system`, `event_type`, and optional `source_event_id`,
- optional `repo_external_id` (for example `owner/name`),
- `occurred_at` (timezone aware) and `ingested_at`,
- a JSON `payload`, stored exactly as received.

### Ingesting events

Use `RawEventWriter` to append events. An SHA-256 `dedupe_key` prevents webhook
retries or overlapping pollers from writing duplicates.

```python
import asyncio
import datetime as dt

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ghillie.bronze import RawEventEnvelope, RawEventWriter, init_bronze_storage
from ghillie.silver import RawEventTransformer, init_silver_storage


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///bronze.db")
    await init_bronze_storage(engine)
    await init_silver_storage(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    writer = RawEventWriter(session_factory)
    envelope = RawEventEnvelope(
        source_system="github",
        source_event_id="evt-1",
        event_type="github.push",
        repo_external_id="acme/api",
        occurred_at=dt.datetime.now(dt.timezone.utc),
        payload={"ref": "refs/heads/main", "after": "abc123"},
    )
    await writer.ingest(envelope)

    transformer = RawEventTransformer(session_factory)
    await transformer.process_pending()


asyncio.run(main())
```

`RawEventWriter.ingest` deep-copies the payload to prevent caller mutations
leaking into storage. If an event already exists, the existing row is returned
without updating timestamps, preserving the append-only contract.

All timestamps must be timezone aware. `RawEventWriter` rejects naive
`occurred_at` values and normalizes any payload datetimes to UTC ISO-8601
strings before persisting to JSON, ensuring hashes and database writes remain
deterministic. Payloads containing unsupported types raise
`UnsupportedPayloadTypeError`.

### Reprocessing and idempotency

`RawEventTransformer` copies Bronze payloads into the Silver `event_facts`
staging table and marks the source row as processed. Re-running a transform
over the same `raw_event_id` is idempotent: if the `event_facts` payload
differs from Bronze, the transform is marked as failed, so operators can
investigate drift; otherwise, no additional rows are created. If two workers
race to insert the same event fact, the late worker re-reads the row and marks
the raw event as processed instead of failing the transform.

## Silver entity tables (Phase 1.2)

Silver now materializes repositories, commits, pull requests, issues, and
documentation changes from Bronze raw events. The transformer recognizes
`github.commit`, `github.pull_request`, `github.issue`, and `github.doc_change`
event types and applies deterministic upserts so reprocessing is safe.

- Repositories are auto-created with a default branch of `main` when no prior
  record exists. If a payload supplies `default_branch`, it updates the stored
  value to keep downstream consumers aligned with GitHub.
- Labels for pull requests and issues are stored as JSON arrays for SQLite
  compatibility while remaining Postgres friendly.
- Documentation changes deduplicate on `(repo, commit_sha, path)` and insert a
  lightweight commit stub if a documentation event arrives before the commit
  record.

### Hydrating Silver from Bronze

The same `RawEventTransformer` instance now populates both `event_facts` and
the entity tables in a single transaction.

```python
import asyncio
import datetime as dt

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ghillie.bronze import RawEventEnvelope, RawEventWriter, init_bronze_storage
from ghillie.silver import (
    Commit,
    RawEventTransformer,
    init_silver_storage,
)


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///silver.db")
    await init_bronze_storage(engine)
    await init_silver_storage(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    writer = RawEventWriter(session_factory)
    await writer.ingest(
        RawEventEnvelope(
            source_system="github",
            source_event_id="commit-1",
            event_type="github.commit",
            repo_external_id="octo/reef",
            occurred_at=dt.datetime.now(dt.timezone.utc),
            payload={
                "sha": "abc123",
                "message": "docs: refresh roadmap",
                "repo_owner": "octo",
                "repo_name": "reef",
                "default_branch": "main",
                "committed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
        )
    )

    transformer = RawEventTransformer(session_factory)
    await transformer.process_pending()

    async with session_factory() as session:
        commit = await session.get(Commit, "abc123")
        assert commit is not None


asyncio.run(main())
```

Running the example leaves `repositories`, `commits`, and `event_facts`
populated for the pilot repository without duplicating rows on replay.

## Gold report metadata (Phase 1.2)

The Gold layer now persists report metadata alongside the Silver entities but
separate from raw GitHub payloads. Reports capture:

- `scope`: `repository`, `project`, or `estate`.
- `window_start` / `window_end`: the reporting window, enforced so end is after
  start.
- `model`, `human_text`, and `machine_summary`: which generator produced the
  report and the stored Markdown plus a JSON machine summary.

Repository reports link to `repositories.id`; project reports link to
`report_projects.id` (a lightweight dimension keyed by `key` so reporting is
decoupled from the catalogue database). `report_coverage` tracks which
`event_facts` have been consumed, allowing replays without double counting
events.

### Creating a report with coverage

```python
import asyncio
import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ghillie.bronze import RawEventEnvelope, RawEventWriter, init_bronze_storage
from ghillie.gold import (
    Report,
    ReportCoverage,
    ReportProject,
    ReportScope,
    init_gold_storage,
)
from ghillie.silver import EventFact, RawEventTransformer, init_silver_storage


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///gold.db")
    await init_bronze_storage(engine)
    await init_silver_storage(engine)
    await init_gold_storage(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    writer = RawEventWriter(session_factory)
    await writer.ingest(
        RawEventEnvelope(
            source_system="github",
            source_event_id="commit-1",
            event_type="github.commit",
            repo_external_id="octo/reef",
            occurred_at=dt.datetime.now(dt.timezone.utc),
            payload={
                "sha": "abc123",
                "message": "docs: refresh roadmap",
                "repo_owner": "octo",
                "repo_name": "reef",
                "default_branch": "main",
                "committed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
        )
    )

    transformer = RawEventTransformer(session_factory)
    await transformer.process_pending()

    async with session_factory() as session:
        event_fact = await session.scalar(select(EventFact))
        project = ReportProject(key="wildside", name="Wildside")

        report = Report(
            scope=ReportScope.PROJECT,
            project_id=project.id,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.timezone.utc),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.timezone.utc),
            model="gpt-5.1-thinking",
            human_text="# Weekly status\n\n- refreshed roadmap",
            machine_summary={"status": "on_track"},
        )
        if event_fact:
            report.coverage_records.append(
                ReportCoverage(event_fact_id=event_fact.id)
            )

        session.add_all([project, report])
        await session.commit()


asyncio.run(main())
```

The example records both the report metadata and the event coverage. Because
coverage references `event_facts`, reprocessing the same raw events does not
create duplicate coverage rows.

### Coverage scope and evidence bundles

Coverage is scope-specific. Repository evidence bundles exclude events already
covered by repository-scoped reports only. Coverage from project or estate
reports does not suppress repository evidence, so repository reporting remains
complete for its own window even if higher-level reports already include the
same events. Re-running a repository report without new events returns the same
bundle.

## Repository discovery and registration (Phase 1.3)

The repository registry bridges catalogue-defined repositories with the Silver
layer ingestion pipeline. It enables controlled GitHub event ingestion by
synchronizing repositories from the catalogue and providing toggle controls for
enabling or disabling ingestion per repository.

### Synchronizing catalogue repositories to Silver

The `RepositoryRegistryService` projects catalogue `RepositoryRecord` entries
into the Silver `Repository` table. Repositories not present in the catalogue
have ingestion disabled by default.

```python
import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ghillie.catalogue import CatalogueImporter, init_catalogue_storage
from ghillie.registry import RepositoryRegistryService
from ghillie.silver import init_silver_storage


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///ghillie.db")
    await init_catalogue_storage(engine)
    await init_silver_storage(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Import catalogue
    importer = CatalogueImporter(session_factory, estate_key="wildside")
    await importer.import_path(Path("examples/wildside-catalogue.yaml"), commit_sha="v1")

    # Sync to Silver
    service = RepositoryRegistryService(session_factory, session_factory)
    result = await service.sync_from_catalogue("wildside")
    print(f"Created: {result.repositories_created}")
    print(f"Updated: {result.repositories_updated}")


asyncio.run(main())
```

### Enabling and disabling ingestion

Each Silver repository has an `ingestion_enabled` flag that controls whether
the ingestion worker should process events for that repository. The registry
service provides methods to toggle this flag.

```python
# Disable ingestion for a repository
await service.disable_ingestion("leynos", "wildside-engine")

# Re-enable ingestion
await service.enable_ingestion("leynos", "wildside-engine")

# List only active repositories
active_repos = await service.list_active_repositories()
for repo in active_repos:
    print(f"{repo.slug}: branch={repo.default_branch}")

# Paginate active repositories (ordered by owner/name)
page = await service.list_active_repositories(limit=100, offset=0)
```

### Ad hoc repositories

When the Silver transformer encounters events for repositories not in the
catalogue, it creates repository rows with `ingestion_enabled=False` and
`catalogue_repository_id=None`. This prevents uncontrolled event processing
while preserving historical data. To enable ingestion for ad hoc repositories,
either add them to the catalogue and re-sync, or explicitly call
`enable_ingestion()`.

### Documentation paths

The registry copies `documentation_paths` from catalogue repositories into
Silver. These paths guide the ingestion worker when detecting documentation
changes such as roadmaps and ADRs.

## Incremental GitHub ingestion (Phase 1.3.b)

Ghillie polls GitHub per managed repository and appends activity into the
Bronze `raw_events` table. Each repository has per-kind watermarks stored in
`github_ingestion_offsets`, allowing the worker to fetch only new commits, pull
requests, issues, and documentation changes since the last successful ingestion
run.

The reference implementation uses the GitHub GraphQL API for commits, pull
requests, and issues, and reuses commit history filtering for documentation
paths (for example, roadmaps and ADR directories).

### Running the ingestion worker

The GraphQL client expects a GitHub token in `GHILLIE_GITHUB_TOKEN`. For pilot
deployments, use a fine-scoped token or GitHub App installation token with
read-only access to the managed repositories. For production deployments, see
[GitHub Application configuration](github-application-configuration.md) for
guidance on creating a GitHub App with least-privilege permissions.

```python
import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ghillie.github import (
    GitHubGraphQLClient,
    GitHubGraphQLConfig,
    GitHubIngestionWorker,
)
from ghillie.registry import RepositoryRegistryService


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///ghillie.db")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    registry = RepositoryRegistryService(session_factory, session_factory)
    repos = await registry.list_active_repositories()

    client = GitHubGraphQLClient(GitHubGraphQLConfig.from_env())
    # If the catalogue database is separate from Bronze/Silver, pass it via config:
    # config = GitHubIngestionConfig(catalogue_session_factory=catalogue_sf)
    worker = GitHubIngestionWorker(session_factory, client)

    for repo in repos:
        await worker.ingest_repository(repo)

    await client.aclose()


asyncio.run(main())
```

After ingestion, run `RawEventTransformer.process_pending()` to hydrate the
Silver entity tables (`commits`, `pull_requests`, `issues`,
`documentation_changes`) from the newly-ingested raw events.

### Running tests against Postgres with py-pglite

The test fixtures now attempt to start a py-pglite Postgres instance by default
so behavioural and unit tests exercise real Postgres semantics. If py-pglite
cannot start (for example, Node.js is missing), the fixtures automatically fall
back to SQLite to keep the suite runnable. To force SQLite explicitly, set
`GHILLIE_TEST_DB=sqlite` before invoking `make test`. See
`docs/testing-sqlalchemy-with-pytest-and-py-pglite.md` for full guidance.

## GitHub ingestion observability (Phase 1.3.d)

Ghillie emits structured log events for ingestion health monitoring. All events
use femtologging with consistent field schemas suitable for parsing by log
aggregators (Datadog, Loki, CloudWatch Logs Insights, etc.). Log levels accept
`TRACE`, `DEBUG`, `INFO`, `WARN`/`WARNING`, `ERROR`, and `CRITICAL`.

### Log events

The ingestion worker emits the following structured events:

| Event Type                   | Level   | Description                                 |
| ---------------------------- | ------- | ------------------------------------------- |
| `ingestion.run.started`      | INFO    | Ingestion run begins for a repository       |
| `ingestion.run.completed`    | INFO    | Ingestion run finished successfully         |
| `ingestion.run.failed`       | ERROR   | Ingestion run failed with error             |
| `ingestion.stream.completed` | INFO    | Stream (commit/PR/issue/doc) ingested       |
| `ingestion.stream.truncated` | WARNING | Stream hit max_events limit, backlog exists |

Each event includes `repo_slug` and `estate_id` for filtering. Completion
events include duration and event counts. Failure events categorize errors for
alert routing.

Example log output:

```text
ghillie.github.observability [INFO] [ingestion.run.completed]
  repo_slug=octo/reef estate_id=wildside duration_seconds=45.200
  commits_ingested=12 pull_requests_ingested=3 issues_ingested=5
  doc_changes_ingested=2 total_events=22
```

### Error categories

Failed ingestion runs are classified into categories for alerting:

| Category                | Description                   | Typical Action          |
| ----------------------- | ----------------------------- | ----------------------- |
| `transient`             | GitHub 5xx errors             | Retry automatically     |
| `client_error`          | GitHub 4xx errors             | Check token/permissions |
| `schema_drift`          | Unexpected API response shape | Investigate API changes |
| `configuration`         | Missing or invalid config     | Fix environment/config  |
| `database_connectivity` | DB connection issues          | Check infrastructure    |
| `data_integrity`        | Constraint violations         | Investigate data issues |
| `database_error`        | Other DB errors               | Check database health   |
| `unknown`               | Unclassified errors           | Investigate logs        |

### Querying ingestion lag

Use `IngestionHealthService` to query per-repository lag and identify stalled
ingestion:

```python
import asyncio
import datetime as dt

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ghillie.github import (
    IngestionHealthConfig,
    IngestionHealthService,
)


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///ghillie.db")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Default threshold is 1 hour
    service = IngestionHealthService(session_factory)

    # Or configure a custom threshold
    config = IngestionHealthConfig(stalled_threshold=dt.timedelta(minutes=30))
    service = IngestionHealthService(session_factory, config=config)

    # Query a single repository
    metrics = await service.get_lag_for_repository("octo/reef")
    if metrics:
        print(f"Lag: {metrics.time_since_last_ingestion_seconds}s")
        print(f"Has backlog: {metrics.has_pending_cursors}")
        print(f"Stalled: {metrics.is_stalled}")

    # Find all stalled repositories
    stalled = await service.get_stalled_repositories()
    for repo in stalled:
        print(f"STALLED: {repo.repo_slug}")


asyncio.run(main())
```

### Lag metrics

The `IngestionLagMetrics` dataclass provides:

- `repo_slug`: Repository identifier (owner/name)
- `time_since_last_ingestion_seconds`: Seconds since newest watermark (None if
  never ingested)
- `oldest_watermark_age_seconds`: Age of oldest stream watermark
- `has_pending_cursors`: True if any stream has a pagination cursor (backlog)
- `is_stalled`: True if lag exceeds threshold or never ingested

### Alerting recommendations

Configure alerts based on structured log queries:

1. **Transient failures (repeated):** Alert if `ingestion.run.failed` with
   `error_category=transient` occurs 3+ times in 15 minutes for the same
   repository.

2. **Configuration errors:** Alert immediately on any `ingestion.run.failed`
   with `error_category=configuration`.

3. **Schema drift:** Alert on `error_category=schema_drift` for prompt
   investigation of GitHub API changes.

4. **Stalled ingestion:** Query
   `IngestionHealthService.get_stalled_repositories()` periodically and alert
   when the list is non-empty.

5. **Backlog accumulation:** Alert when `ingestion.stream.truncated` events
   occur repeatedly for the same repository (indicates sustained high activity
   or processing issues).

## Container image (Phase 1.5.c)

Ghillie provides a container image for Kubernetes deployments. The image runs a
Falcon Asynchronous Server Gateway Interface (ASGI) application served by
Granian, with health endpoints for Kubernetes probes.

### Building the image

Build the image locally using the provided Makefile target:

```bash
make docker-build
```

This produces an image tagged `ghillie:local` using a multi-stage build. The
build stage creates a wheel from the source, and the runtime stage installs it
into a minimal Python 3.12 slim image with a non-root user.

Alternatively, build directly with Docker:

```bash
docker build -t ghillie:local .
```

### Running the container

Run the container locally to verify the build:

```bash
docker run --rm -p 8080:8080 ghillie:local
```

The container starts the Granian server and logs a startup message. Verify the
health endpoints:

```bash
curl http://localhost:8080/health
# Returns: {"status": "ok"}

curl http://localhost:8080/ready
# Returns: {"status": "ready"}
```

### Environment variables

The runtime reads configuration from environment variables:

| Variable            | Default   | Description                   |
| ------------------- | --------- | ----------------------------- |
| `GHILLIE_HOST`      | `0.0.0.0` | Bind address for the server   |
| `GHILLIE_PORT`      | `8080`    | Listening port for HTTP       |
| `GHILLIE_LOG_LEVEL` | `INFO`    | Log level (DEBUG, INFO, etc.) |

Additional environment variables for database and cache connectivity should be
injected via Kubernetes Secrets when deploying with the Helm chart.

### Health endpoints

The runtime exposes two health endpoints for Kubernetes probes:

- `/health`: Liveness probe endpoint. Returns `{"status": "ok"}` when the
  process is alive.
- `/ready`: Readiness probe endpoint. Returns `{"status": "ready"}` when the
  service is ready to accept traffic.

Both endpoints return HTTP 200 with JSON content type.

### OpenAPI specification

The runtime health endpoints are documented in the OpenAPI specification:

- [`specs/openapi.yml`](../specs/openapi.yml)

### Kubernetes deployment

For Kubernetes deployment, use the Ghillie Helm chart in `charts/ghillie/`.
Configure liveness and readiness probes in the chart values:

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 15

readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 5
```

For local k3d previews, import the image into the cluster:

```bash
k3d image import ghillie:local -c <cluster-name>
```

## Local k3d preview environment (Phase 1.5.d)

Ghillie provides a local preview environment using k3d (k3s-in-Docker). This
enables developers to validate the full Kubernetes deployment locally before
pushing to CI/CD, mirroring the ephemeral preview architecture on a developer
workstation.

### Prerequisites

The local preview requires the following tools installed and available on
`PATH`:

- `docker` - Container runtime
- `k3d` - Lightweight Kubernetes distribution wrapper
- `kubectl` - Kubernetes CLI
- `helm` - Kubernetes package manager

The script verifies these tools are available before proceeding.

### Creating the preview environment

Create a local k3d preview environment with:

```bash
make local-k8s-up
```

This command:

1. Creates a k3d cluster with loopback-only ingress on an ephemeral port
2. Installs the CloudNativePG (CNPG) operator and creates a Postgres instance
3. Installs the Valkey operator and creates a Valkey instance
4. Builds the Ghillie Docker image and imports it into the cluster
5. Creates application secrets with database and cache connection strings
6. Deploys the Ghillie Helm chart using local values

On completion, the script prints a preview URL:

```text
Preview environment ready!
  URL: http://127.0.0.1:49213/
```

Verify the deployment by accessing the health endpoint:

```bash
curl http://127.0.0.1:49213/health
# Returns: {"status": "ok"}
```

### Managing the preview environment

Check the status of running pods:

```bash
make local-k8s-status
```

Tail logs from the Ghillie deployment:

```bash
make local-k8s-logs
```

Tear down the preview environment:

```bash
make local-k8s-down
```

### Configuration options

The local preview script accepts environment variables for customization:

| Variable                | Default         | Description                               |
| ----------------------- | --------------- | ----------------------------------------- |
| `GHILLIE_K3D_CLUSTER`   | `ghillie-local` | Name of the k3d cluster                   |
| `GHILLIE_K3D_NAMESPACE` | `ghillie`       | Kubernetes namespace for deployment       |
| `GHILLIE_K3D_PORT`      | (auto)          | Ingress port (picks free port if not set) |

Example with custom cluster name:

```bash
GHILLIE_K3D_CLUSTER=my-preview make local-k8s-up
```

### Skipping image build

To skip building the Docker image (useful when iterating on configuration), use
the `--skip-build` flag directly:

```bash
uv run scripts/local_k8s.py up --skip-build
```

### Architecture

The local preview environment installs the following components:

- **k3d cluster**: Single-node k3s cluster running in Docker with traefik
  disabled and a custom ingress port mapping.
- **CloudNativePG**: Postgres operator providing a single-instance Postgres
  cluster (`pg-ghillie`) with credentials in a Kubernetes secret.
- **Valkey**: Redis-compatible in-memory cache via the hyperspike Valkey
  operator, providing a standalone Valkey instance.
- **Ghillie deployment**: The Ghillie Helm chart deployed with local values,
  using the locally built container image.

Connection strings for the database and cache are automatically extracted from
operator-managed secrets and injected into the application secret.

## Status model configuration (Phase 2.2.c)

Ghillie supports configurable large language model (LLM) backends for status
report generation. The same reporting job can run against different model
backends without code changes, controlled entirely via environment variables.

### Backend selection

Set `GHILLIE_STATUS_MODEL_BACKEND` to choose the status model implementation:

| Value    | Description                                         |
| -------- | --------------------------------------------------- |
| `mock`   | Deterministic heuristic-based model for testing     |
| `openai` | OpenAI-compatible API (GPT models, local endpoints) |

### Mock backend configuration

The mock backend requires no additional configuration:

```bash
export GHILLIE_STATUS_MODEL_BACKEND=mock
```

This is useful for:

- Local development without API costs
- Testing infrastructure and pipelines
- Deterministic output for regression testing

### OpenAI backend configuration

The OpenAI backend requires an API key and supports optional customization:

| Variable                       | Required | Default                                      | Description                    |
| ------------------------------ | -------- | -------------------------------------------- | ------------------------------ |
| `GHILLIE_STATUS_MODEL_BACKEND` | Yes      | -                                            | Must be `openai`               |
| `GHILLIE_OPENAI_API_KEY`       | Yes      | -                                            | API key for authentication     |
| `GHILLIE_OPENAI_ENDPOINT`      | No       | `https://api.openai.com/v1/chat/completions` | Chat completions endpoint URL  |
| `GHILLIE_OPENAI_MODEL`         | No       | `gpt-5.1-thinking`                           | Model identifier               |
| `GHILLIE_OPENAI_TEMPERATURE`   | No       | `0.3`                                        | Sampling temperature (0.0-2.0) |
| `GHILLIE_OPENAI_MAX_TOKENS`    | No       | `2048`                                       | Maximum tokens in response     |

Example configuration for production:

```bash
export GHILLIE_STATUS_MODEL_BACKEND=openai
export GHILLIE_OPENAI_API_KEY="sk-..."
export GHILLIE_OPENAI_MODEL=gpt-4-turbo
export GHILLIE_OPENAI_TEMPERATURE=0.3
export GHILLIE_OPENAI_MAX_TOKENS=2048
```

Example configuration for local testing with VidaiMock:

```bash
export GHILLIE_STATUS_MODEL_BACKEND=openai
export GHILLIE_OPENAI_API_KEY="test-key"
export GHILLIE_OPENAI_ENDPOINT="http://localhost:8080/v1/chat/completions"
```

### Programmatic usage

For programmatic configuration, use `create_status_model()`:

```python
from ghillie.status import create_status_model

# Uses GHILLIE_STATUS_MODEL_BACKEND to select implementation
model = create_status_model()
result = await model.summarize_repository(evidence_bundle)
```

Or construct models directly for testing:

```python
from ghillie.status import MockStatusModel, OpenAIStatusModel, OpenAIStatusModelConfig

# Mock model for testing
mock_model = MockStatusModel()

# OpenAI model with explicit configuration
config = OpenAIStatusModelConfig(
    api_key="sk-...",
    temperature=0.5,
    max_tokens=4096,
)
openai_model = OpenAIStatusModel(config)
```

## Scheduled reporting workflow (Phase 2.3.a)

Ghillie provides a scheduled reporting workflow that orchestrates evidence
bundle construction, status model invocation, and report persistence. The
workflow can be invoked programmatically or via Dramatiq actors for background
execution.

### Generating a repository report

Use `ReportingService` to generate reports for repositories:

```python
import asyncio
import datetime as dt

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ghillie.bronze import init_bronze_storage
from ghillie.evidence import EvidenceBundleService
from ghillie.gold import init_gold_storage
from ghillie.reporting import (
    ReportingConfig,
    ReportingService,
    ReportingServiceDependencies,
)
from ghillie.silver import init_silver_storage
from ghillie.status import create_status_model


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///ghillie.db")
    await init_bronze_storage(engine)
    await init_silver_storage(engine)
    await init_gold_storage(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Create the reporting service with dependencies
    dependencies = ReportingServiceDependencies(
        session_factory=session_factory,
        evidence_service=EvidenceBundleService(session_factory),
        status_model=create_status_model(),  # Uses GHILLIE_STATUS_MODEL_BACKEND
    )
    service = ReportingService(dependencies, config=ReportingConfig())

    # Generate a report for a specific repository
    repository_id = "..."  # Silver repository ID
    report = await service.run_for_repository(repository_id)

    if report:
        print(f"Report generated: {report.id}")
        print(f"Window: {report.window_start} to {report.window_end}")
        print(f"Summary: {report.human_text}")
    else:
        print("No events in reporting window")


asyncio.run(main())
```

### Window computation

The service automatically computes the reporting window:

- If a previous report exists for the repository, the new window starts where
  the previous report ended (continuous coverage).
- If no previous report exists, the window starts `window_days` before the
  current time (default: 7 days).

```python
# Compute the next window without generating a report
window = await service.compute_next_window(repository_id)
print(f"Next window: {window.start} to {window.end}")
```

### Configuration

Configure the reporting workflow via `ReportingConfig`:

| Parameter     | Default | Description                               |
| ------------- | ------- | ----------------------------------------- |
| `window_days` | 7       | Default window size when no prior reports |

Configuration can be loaded from environment variables:

```bash
export GHILLIE_REPORTING_WINDOW_DAYS=14
```

```python
from ghillie.reporting import ReportingConfig

config = ReportingConfig.from_env()  # Reads GHILLIE_REPORTING_WINDOW_DAYS
```

### Background execution with Dramatiq

For scheduled/background execution, use the Dramatiq actors:

```python
from ghillie.reporting import generate_report_job, generate_reports_for_estate_job

# Generate a single repository report
generate_report_job.send(
    database_url="postgresql+asyncpg://...",
    repository_id="...",
)

# Generate reports for all active repositories in an estate
generate_reports_for_estate_job.send(
    database_url="postgresql+asyncpg://...",
    estate_id="wildside",
)
```

The estate job iterates over all repositories with `ingestion_enabled=True` and
generates reports for each. Repositories without events in their window are
skipped.

### Scheduling with cron

Example cron configuration for weekly reports:

```bash
# Generate reports for all estates every Monday at 6am UTC
0 6 * * 1 python -c "
from ghillie.reporting import generate_reports_for_estate_job
generate_reports_for_estate_job.send(
    'postgresql+asyncpg://...', 'wildside'
)
"
```

For Kubernetes deployments, use a CronJob resource with the Dramatiq worker
container.

## Report Markdown and storage (Phase 2.3.b)

Ghillie can render repository status reports as Markdown documents and write
them to the filesystem at predictable paths, making reports navigable by
operators and version-controllable.

### Enabling filesystem report storage

Set the `GHILLIE_REPORT_SINK_PATH` environment variable to a directory path.
When configured, each report generation run writes two files per repository:

- `{base_path}/{owner}/{name}/latest.md` — always overwritten with the most
  recent report.
- `{base_path}/{owner}/{name}/{date}-{report_id}.md` — a dated archive that
  accumulates over time.

```bash
export GHILLIE_REPORT_SINK_PATH=/var/lib/ghillie/reports
```

When the variable is unset, report generation works as before without writing
any Markdown files.

### Markdown format

The rendered Markdown document follows this structure:

```markdown
# acme/widget — Status report (2024-07-07 to 2024-07-14)

**Status:** On Track

## Summary

The repository saw steady feature work and documentation improvements.

## Highlights

- Implemented new authentication flow
- Added comprehensive API documentation

## Risks

- CI pipeline flakiness increasing

## Next steps

- Address CI stability
- Begin database migration planning

---

*Generated at 2024-07-14 12:00 UTC by gpt-5.1-thinking
 | Window: 2024-07-07 to 2024-07-14 | Report ID: abc-123*
```

Sections with no content (empty highlights, risks, or next steps) are omitted
entirely. The renderer reads from the structured `machine_summary` field on the
Gold layer report, so the Markdown content always matches the database.

### Report sink configuration

| Variable                   | Default | Description                                                                        |
| -------------------------- | ------- | ---------------------------------------------------------------------------------- |
| `GHILLIE_REPORT_SINK_PATH` | (unset) | Filesystem directory for Markdown report output. When unset, no files are written. |

### Rendering and sink usage

To render a report as Markdown without writing to disk:

```python
from ghillie.reporting import render_report_markdown

md = render_report_markdown(report, owner="acme", name="widget")
```

To use the filesystem sink directly:

```python
from pathlib import Path

from ghillie.reporting import (
    FilesystemReportSink,
    ReportMetadata,
    render_report_markdown,
)

sink = FilesystemReportSink(Path("/var/lib/ghillie/reports"))
metadata = ReportMetadata(
    owner="acme",
    name="widget",
    report_id="abc-123",
    window_end="2024-07-14",
)
markdown = render_report_markdown(report, owner="acme", name="widget")
await sink.write_report(markdown, metadata=metadata)
```

The `ReportSink` protocol supports future storage backends (for example, S3 or
a dedicated Git repository) without changes to the reporting service.

### Integration with the reporting service (scheduled)

When a `FilesystemReportSink` is provided, the `ReportingService` automatically
renders and writes Markdown after each report is persisted to the Gold layer.
The Dramatiq actors (`generate_report_job`, `generate_reports_for_estate_job`)
create the sink automatically when `GHILLIE_REPORT_SINK_PATH` is set.

```python
from pathlib import Path

from ghillie.reporting import (
    FilesystemReportSink,
    ReportingConfig,
    ReportingService,
    ReportingServiceDependencies,
)

config = ReportingConfig.from_env()
sink = FilesystemReportSink(Path("/var/lib/ghillie/reports"))

dependencies = ReportingServiceDependencies(
    session_factory=session_factory,
    evidence_service=evidence_service,
    status_model=status_model,
)
service = ReportingService(dependencies, config=config, report_sink=sink)

# Reports are now rendered and stored as Markdown automatically
report = await service.run_for_repository(repository_id)
```

## On-demand report generation (Phase 2.3.c)

In addition to scheduled reporting, Ghillie provides an HTTP API endpoint for
generating reports on demand. This enables operators to trigger a fresh report
for a specific repository — for example, to respond to a review request or
verify the state of a project before a release.

### Endpoint

```text
POST /reports/repositories/{owner}/{name}
```

The endpoint identifies repositories by their GitHub owner/name slug, matching
the filesystem sink path convention and catalogue notation.

### Response codes

| Status | Meaning                                                   |
| ------ | --------------------------------------------------------- |
| 200    | Report generated. JSON body contains the report metadata. |
| 204    | Repository exists but no events in the current window.    |
| 404    | No repository matching the given owner/name exists.       |
| 422    | Generated report failed correctness checks after retries. |

### Example

Generate a report for `acme/widgets`:

```bash
curl -X POST http://localhost:8080/reports/repositories/acme/widgets
```

On success, the response body contains report metadata:

```json
{
  "report_id": "abc-123",
  "repository": "acme/widgets",
  "window_start": "2024-07-07T00:00:00+00:00",
  "window_end": "2024-07-14T00:00:00+00:00",
  "generated_at": "2024-07-14T12:00:00+00:00",
  "status": "on_track",
  "model": "mock-v1",
  "metrics": {
    "model_latency_ms": 87,
    "prompt_tokens": 1250,
    "completion_tokens": 350,
    "total_tokens": 1600
  }
}
```

When no events exist in the reporting window, the endpoint returns HTTP 204
with no body.

### Enabling the endpoint

The on-demand report endpoint requires a database connection. Set the
`GHILLIE_DATABASE_URL` environment variable to enable domain endpoints:

```bash
export GHILLIE_DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/ghillie"
```

When `GHILLIE_DATABASE_URL` is not set, the runtime starts in health-only mode
(backwards compatible with existing deployments). The endpoint also respects
`GHILLIE_REPORT_SINK_PATH` — when set, generated reports are written to the
filesystem as Markdown, just like scheduled reports.

### On-demand reporting environment variables

| Variable                        | Required | Description                          |
| ------------------------------- | -------- | ------------------------------------ |
| `GHILLIE_DATABASE_URL`          | Yes      | Database connection URL              |
| `GHILLIE_REPORT_SINK_PATH`      | No       | Directory for Markdown report output |
| `GHILLIE_REPORTING_WINDOW_DAYS` | No       | Default window size (default: 7)     |
| `GHILLIE_STATUS_MODEL_BACKEND`  | Yes      | Status model backend (e.g. `mock`)   |

### On-demand reporting OpenAPI specification

The endpoint is documented in the OpenAPI specification at
[`specs/openapi.yml`](../specs/openapi.yml).

## Report correctness validation (Phase 2.4.a)

Generated repository reports are validated before persistence. If the status
model produces output that fails basic correctness checks, Ghillie retries
generation a bounded number of times. If all retries fail, the run is marked
for human review rather than silently storing invalid data.

### Validation checks

The following heuristics are applied to each generated report:

- **Non-empty summary**: The model must produce a non-empty, non-whitespace
  summary string.
- **Truncation detection**: Summaries ending with a trailing ellipsis (`...`
  or `\u2026`) are rejected as likely truncated.
- **Highlight plausibility**: The number of highlights must be proportional to
  the number of events in the evidence bundle. A highlight count exceeding five
  times the event count is rejected as implausible.

### Retry behaviour

When validation fails, the service retries model invocation up to
`validation_max_attempts` times (default: 2). If the model eventually produces
a valid result, the report is persisted normally. If all attempts fail, the
service persists a `ReportReview` marker in the Gold layer and raises a
validation error.

### Human review markers

Operators can query `ReportReview` rows to identify failed generation runs.
Each review marker records:

- the repository and reporting window,
- the number of generation attempts,
- the specific validation issues encountered,
- a lifecycle state (`pending` or `resolved`).

Review markers are uniquely constrained per
`(repository_id, window_start, window_end)` to prevent duplicates from repeated
retries in the same window.

### API behaviour for validation failures

When the on-demand endpoint encounters a validation failure, it returns HTTP
422 Unprocessable Entity with a JSON body:

```json
{
  "title": "Report validation failed",
  "description": "Generated report failed correctness checks after retries.",
  "review_id": "abc-123",
  "issues": [
    {
      "code": "empty_summary",
      "message": "Summary is empty or contains only whitespace."
    }
  ]
}
```

The `review_id` field references the persisted `ReportReview` row so operators
can locate the review marker directly.

### Validation configuration

| Variable                          | Default | Description                       |
| --------------------------------- | ------- | --------------------------------- |
| `GHILLIE_VALIDATION_MAX_ATTEMPTS` | `2`     | Maximum model invocation attempts |

## Reporting metrics and costs (Phase 2.4.b)

Repository report generation now captures per-run operational metrics and
exposes aggregate period snapshots for operators.

### Per-report metrics captured

Each generated repository `Report` now stores nullable metrics fields:

- `model_latency_ms`
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`

Latency is measured by the reporting service (`time.monotonic`) and token usage
comes from the selected status model adapter when available.

### Structured reporting events

Reporting runs emit structured lifecycle events:

- `reporting.report.started`
- `reporting.report.completed`
- `reporting.report.failed`

Completion events include model identifier, latency, and token counts.

### Querying aggregate metrics for a period

Use `ReportingMetricsService` to compute totals and latency profile for a time
window:

```python
import asyncio
import datetime as dt

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ghillie.reporting.metrics_service import ReportingMetricsService


async def main() -> None:
    engine = create_async_engine("postgresql+asyncpg://user:pass@host:5432/ghillie")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    service = ReportingMetricsService(session_factory)

    snapshot = await service.get_metrics_for_period(
        period_start=dt.datetime(2026, 2, 1, tzinfo=dt.UTC),
        period_end=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
    )
    print(snapshot.total_reports)
    print(snapshot.avg_latency_ms)
    print(snapshot.total_tokens)


asyncio.run(main())
```

For estate-scoped queries, call `get_metrics_for_estate(estate_id, start, end)`.

### Estimating reporting cost

`ReportingMetricsService` returns token totals. Convert those totals to
currency using pricing configured for the active model (for example, prompt and
completion token rates from the provider contract).

## Project evidence bundles (Phase 3.1.a)

Project evidence bundles aggregate catalogue metadata, component lifecycle
stages, repository report summaries, and component dependency graphs into a
single immutable structure for project-level status reporting.

### What a project evidence bundle contains

A `ProjectEvidenceBundle` includes:

- **Project metadata** -- key, name, description, programme, and
  documentation paths from the catalogue.
- **Component evidence** -- one entry per component listing its key, name,
  type (service, UI, library, etc.), lifecycle stage (planned, active,
  deprecated), optional repository slug, and optional repository report summary.
- **Component dependency edges** -- directed relationships between
  components within the same project (depends\_on, blocked\_by,
  emits\_events\_to), with kind (runtime, dev, test, ops) and optional
  rationale.
- **Previous project reports** -- up to two most recent project-scope Gold
  reports for contextual continuity.

### Components with repositories

When a component has a mapped repository and the repository has at least one
Gold-layer report, the component evidence includes a
`ComponentRepositorySummary` with:

- repository slug (e.g. `leynos/wildside`),
- the latest report's status (on\_track, at\_risk, blocked, unknown),
- narrative summary, highlights, risks, and next steps, and
- reporting window timestamps.

### Planned and non-code components

Components without repositories (lifecycle `planned`) are included in the
bundle with `repository_slug` and `repository_summary` set to `None`. Their
lifecycle stage and any catalogue notes are preserved, allowing downstream
summarisation to distinguish between active and planned work.

### Cross-project dependencies

Dependency edges whose target component belongs to a different project are
excluded from the bundle. Only intra-project edges appear in the `dependencies`
field. Cross-project edges remain in the catalogue for future estate-level
aggregation.

### Building a project evidence bundle

```python
import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ghillie.evidence.project_service import ProjectEvidenceBundleService


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///ghillie.db")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    service = ProjectEvidenceBundleService(
        catalogue_session_factory=session_factory,
        gold_session_factory=session_factory,
    )

    bundle = await service.build_bundle(
        project_key="wildside",
        estate_id="example-estate-id",
    )

    print(f"Project: {bundle.project.name}")
    print(f"Components: {bundle.component_count}")
    print(f"Active: {len(bundle.active_components)}")
    print(f"Planned: {len(bundle.planned_components)}")
    print(f"Dependencies: {len(bundle.dependencies)}")
    print(f"Blocked: {len(bundle.blocked_dependencies)}")
    print(f"With reports: {len(bundle.components_with_reports)}")


asyncio.run(main())
```

The service accepts two session factories: one for catalogue storage and one
for silver/gold storage. In typical deployments both point to the same database
engine, but separate session factories allow future database separation without
code changes.
