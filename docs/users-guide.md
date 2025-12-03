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
  and `status`. Setting `summarise_dependency_prs: false` signals that
  dependency update pull requests should be ignored in downstream summaries.
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

from ghillie.bronze import RawEventWriter, init_bronze_storage
from ghillie.silver import RawEventTransformer, init_silver_storage


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///bronze.db")
    await init_bronze_storage(engine)
    await init_silver_storage(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    writer = RawEventWriter(session_factory)
    await writer.ingest(
        source_system="github",
        source_event_id="evt-1",
        event_type="github.push",
        repo_external_id="acme/api",
        occurred_at=dt.datetime.now(dt.timezone.utc),
        payload={"ref": "refs/heads/main", "after": "abc123"},
    )

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
