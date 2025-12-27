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
read-only access to the managed repositories.

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
use Python's standard logging module with consistent field schemas suitable for
parsing by log aggregators (Datadog, Loki, CloudWatch Logs Insights, etc.).

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
INFO ghillie.github.observability [ingestion.run.completed]
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
