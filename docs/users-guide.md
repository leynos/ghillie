# ghillie Users' Guide

## Operator CLI scaffold (Task 2.5.a)

Ghillie now ships a packaged operator CLI entry point:

```bash
uv run ghillie --help
```

The scaffolded root nouns are `stack`, `estate`, `ingest`, `export`, `report`,
and `metrics`. The CLI grammar is noun-first:

```text
ghillie <noun> <verb> [selectors] [predicates] [options]
```

Shared root configuration is resolved before noun dispatch with this precedence:

1. Explicit root CLI flags such as `--api-base-url`.
2. Environment variables such as `GHILLIE_API_BASE_URL`.
3. `~/.config/ghillie/cli.toml`.
4. `~/.config/ghillie/state.json`.
5. Fallback `http://127.0.0.1:8080`.

Task 2.5.a delivers the command contract, shared config resolution, control
plane client wiring, and local runtime adapter selection for `cuprum` and
`python-api`. The estate verbs are live (see "Estate management through the CLI
and API"); the other nouns still return deterministic placeholder payloads
until their roadmap tasks attach the real ingestion, export, metrics, and
reporting backends.

Two useful checks:

```bash
uv run ghillie stack up --help
```

This shows the documented stack scaffold options, including `--backend` and
`--wait` or `--no-wait`.

```bash
uv run ghillie --api-base-url http://127.0.0.1:9999 report run --help
```

This proves the shared root options are accepted before the noun command.

## Estate management through the CLI and API (Task 2.5.b)

The estate verbs are live. Every verb is a thin HTTP call to the control plane:
local validation rejects bad input before any request is sent, and any
control-plane failure exits `3` with a stable code, a message, and an operator
hint. Shared root options come before the noun. Pass the bearer token in
`GHILLIE_AUTH_TOKEN` rather than `--auth-token`: a value in argv is visible to
every local process and is kept in shell history.

```bash
GHILLIE_AUTH_TOKEN="$GHILLIE_API_TOKEN" \
  ghillie --api-base-url http://127.0.0.1:8080 \
        --output json \
        estate list
```

| Root option           | Purpose                                             |
| --------------------- | --------------------------------------------------- |
| `--api-base-url`      | Service base URL.                                   |
| `--auth-token`        | Bearer token; needed when the service enables auth. |
| `--output`            | `table`, `json`, or `yaml`.                         |
| `--dry-run`           | Preview import and sync; `repo set` refuses it.     |
| `--request-timeout-s` | Per-request timeout in seconds.                     |

`json` and `yaml` print the server document unchanged, so scripts can rely on
the full response. `table` is for humans and may change between releases.

The five endpoints behind the verbs are:

| Method and path                                | Purpose                          |
| ---------------------------------------------- | -------------------------------- |
| `POST /estates/{estate_key}/catalogue-import`  | Import a catalogue document.     |
| `POST /estates/{estate_key}/registry-sync`     | Project repositories to Silver.  |
| `GET /estates`                                 | List estates.                    |
| `GET /estates/{estate_key}/repositories`       | List repositories for an estate. |
| `PATCH /repositories/{owner}/{name}/ingestion` | Set the ingestion toggle.        |

### Import a catalogue

`ghillie estate import` reads a UTF-8 catalogue locally (a byte-order mark is
stripped), checks the estate key against `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`
and the serialized request against the 1 MiB limit, then uploads the document:

```bash
ghillie estate import \
  --estate-key wildside \
  --catalogue-path examples/wildside-catalogue.yaml \
  --commit-sha "$(git rev-parse HEAD)" \
  --estate-name "Wildside"
```

The CLI applies the creation pattern to every import, while the service applies
it only when creating a new estate. An estate created earlier through Python
may therefore have a key that the CLI rejects, such as `Wildside Estate`.
Re-import into such an estate with the HTTP API directly;
`ghillie estate import` exits `2` with `invalid_estate_key` before sending a
request.

That workaround needs a routable key. A key containing `/` cannot be routed, so
`POST /estates/{estate_key}/catalogue-import` returns `404` with `not_found`
and the estate cannot be re-imported through either interface.

The response reports the commit, the resulting state, and created, updated, and
deleted counts for projects, components, repositories, and edges:

```json
{
  "estate_key": "wildside",
  "commit_sha": "1f0c2a9",
  "state": "succeeded",
  "dry_run": false,
  "skipped": false,
  "skipped_reason": null,
  "registry_sync_required": true,
  "projects": {"created": 1, "updated": 0, "deleted": 0},
  "components": {"created": 4, "updated": 0, "deleted": 0},
  "repositories": {"created": 2, "updated": 0, "deleted": 0},
  "edges": {"created": 3, "updated": 0, "deleted": 0}
}
```

Re-importing a commit that is already stored does no work. The response says so
with `"skipped": true` and a reason such as `commit_already_imported`, and
table output leads with a `SKIPPED:` line.

A dry run previews the import and rolls the transaction back:

```bash
ghillie --dry-run estate import \
  --estate-key wildside \
  --catalogue-path examples/wildside-catalogue.yaml \
  --commit-sha "preview"
```

The response carries the counts the import would have produced, and the estate
list is unchanged afterwards.

### Sync the registry

`ghillie estate sync` projects the estate's catalogue repositories into the
Silver registry:

```bash
ghillie --output json estate sync --estate-key wildside
```

```json
{
  "estate_key": "wildside",
  "state": "succeeded",
  "dry_run": false,
  "repositories_created": 2,
  "repositories_updated": 0,
  "repositories_deactivated": 0,
  "repositories_conflicted": [],
  "repositories_left_disabled": [],
  "repositories_left_disabled_count": 0
}
```

The sync is synchronous and idempotent; there is no wait flag. A dry run
returns the same shape with `"dry_run": true` and changes nothing.

### List estates and repositories

```bash
ghillie estate list
ghillie --output json estate repo list --estate-key wildside --active
ghillie estate repo list --estate-key wildside --inactive --limit 50 --offset 0
```

Estates have no lifecycle state, so `estate list` accepts no active or inactive
flag. Repository listing is paginated (`limit` 1 to 500, default 50; `offset`
at least 0) and ordered by owner and name. `--active` and `--inactive` select
one ingestion state; omitting both lists both.

### Enable or disable ingestion

```bash
ghillie estate repo set --owner leynos --name wildside --ingestion-disabled
ghillie estate repo set --owner leynos --name wildside --ingestion-enabled
```

The toggle is required; the CLI rejects a call that names neither state with
exit `2`. The response says what changed:

```json
{
  "owner": "leynos",
  "name": "wildside",
  "ingestion_enabled": false,
  "changed": true
}
```

The ingestion endpoint has no dry-run mode, so `estate repo set` under
`--dry-run` refuses locally with `dry_run_unsupported` and exit `2` rather than
quietly applying the toggle.

### Toggle rules across syncs

A toggle survives later catalogue imports and syncs:

- Sync creates rows, adopts unlinked rows, and disables rows that leave the
  catalogue, but it never re-enables a linked row of the estate.
- A repository removed from the catalogue and later re-added stays disabled
  until an operator enables it. The sync result names it in
  `repositories_left_disabled` (the first 100 slugs) with a matching
  `repositories_left_disabled_count`.
- If another estate already owns a repository named by this estate's
  catalogue, sync leaves that row untouched and reports the slug in
  `repositories_conflicted`. Remove the overlap from one catalogue; sync will
  not move a row between estates.
- A toggle applied to an ad hoc row lasts only until a catalogue entry adopts
  the row, at which point the catalogue's active flag takes over.

To re-enable every repository that is currently disabled, collect the whole set
first and only then apply the toggles. Enabling a repository removes it from the
`--inactive` filter, so paging and mutating in the same pass would shrink the
collection and skip rows:

```bash
# 1. Collect every disabled repository across all pages.
disabled=$(mktemp)
trap 'rm -f "$disabled"' EXIT
offset=0
while :; do
  # A failed page or an unparseable one must abort: continuing would truncate
  # the captured set and quietly leave repositories disabled.
  if ! page=$(ghillie --output json estate repo list --estate-key wildside \
    --inactive --limit 500 --offset "$offset"); then
    echo "listing failed; aborting so the set is not truncated" >&2
    exit 1
  fi
  if ! jq -r '.items[] | "\(.owner)/\(.name)"' <<<"$page" >>"$disabled"; then
    echo "could not parse the listing; aborting" >&2
    exit 1
  fi
  jq -e '.has_more' <<<"$page" >/dev/null || break
  offset=$(jq -r '.next_offset' <<<"$page")
done

# 2. Apply the toggles to the captured set.
while IFS=/ read -r owner name; do
  ghillie estate repo set --owner "$owner" --name "$name" --ingestion-enabled
done <"$disabled"
```

The temporary file has an unpredictable name and is removed on exit, so a
second operator on the same host cannot read or truncate it.

This recipe targets every repository that is disabled now. If the intent is
instead to re-enable the set the last sync left disabled, read
`repositories_left_disabled` from that sync's result. That list is a preview of
the first 100 slugs and `repositories_left_disabled_count` is the exact total;
the response does not retain the remaining identities, so a set larger than the
preview cannot be recovered from it alone.

To act on the whole set as it stands now, intersect two current sources: page
the `--inactive` listing and keep only the slugs this estate's catalogue marks
active. The inactive listing alone is not the answer, because it also contains
ad hoc rows and repositories that left the catalogue, which the sync's preview
excludes. The intersection matches the historical set only while neither the
catalogue nor the toggles have changed since that sync ran.

### Error codes

Failures exit `2` for invalid local input and `3` for control-plane failures.
Machine-readable modes print an envelope such as:

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
| `catalogue_invalid`         | 3    | Catalogue failed schema validation.           |
| `conflict`                  | 3    | The stored commit conflicts with this import. |
| `invalid_input`             | 3    | A request field is malformed.                 |
| `payload_too_large`         | 3    | The service rejected the request size.        |
| `unauthorized`              | 3    | The service requires or rejected a token.     |
| `not_found`                 | 3    | No such route, or estate routes are off.      |
| `storage_unavailable`       | 3    | The catalogue store is unavailable.           |
| `registry_sync_failed`      | 3    | The sync failed inside the service.           |
| `internal_error`            | 3    | An unexpected service failure.                |
| `transport`                 | 3    | The service could not be reached.             |
| `timeout`                   | 3    | The request exceeded the timeout.             |
| `invalid_response`          | 3    | A successful response was not a JSON object.  |
| `http_<status>`             | 3    | Any other non-2xx response.                   |

### Starting the service for these verbs

The estate endpoints need a database. `GHILLIE_DATABASE_URL` selects it; when
it is unset the runtime starts in health-only mode and the estate routes answer
`404`. The opt-in bootstrap creates the schema on startup:

```bash
export GHILLIE_DATABASE_URL="sqlite+aiosqlite:///ghillie.db"
export GHILLIE_DB_BOOTSTRAP=create-all
export GHILLIE_API_TOKEN="$(cat ~/.config/ghillie/api-token)"
export GHILLIE_ALLOW_STUB_BROKER=1
uv run python -m ghillie.runtime
```

`GHILLIE_API_TOKEN` enables bearer authentication for every endpoint except the
health probes; clients must then send `--auth-token` or set
`GHILLIE_AUTH_TOKEN`. `GHILLIE_ALLOW_STUB_BROKER=1` permits the stub event
broker used by local runs. In production the schema is migrated rather than
created, so leave `GHILLIE_DB_BOOTSTRAP` unset.

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

Storage-generated primary keys in the catalogue, Silver, and Gold relational
models remain canonical `String(36)` UUID text, but newly inserted rows now use
UUIDv7 values. Existing UUIDv4 rows remain valid because column types and API
field shapes are unchanged.

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

Operators use the CLI and API described in "Estate management through the CLI
and API"; the Python calls below are the programmatic alternative for scripts
that embed Ghillie.

### Programmatic alternative: synchronizing catalogue repositories to Silver

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

### Programmatic alternative: enabling and disabling ingestion

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

For an active linked repository, sync preserves the operator's ingestion flag.
Sync creates rows, adopts unlinked rows, and disables rows whose catalogue
entry becomes inactive or leaves the catalogue; it never re-enables a linked
row of the estate. A repository that is removed from the catalogue and later
re-added therefore stays disabled until an operator enables it again. The sync
result names those repositories:

```python
result = await service.sync_from_catalogue("wildside")
print(result.repositories_left_disabled_count)
print(result.repositories_left_disabled)  # first 100 slugs
```

`repositories_left_disabled_count` is the number of active catalogue
repositories whose linked Silver row was disabled in the view the sync loaded
and that the sync left disabled, including rows an operator disabled. It is an
observation of that view plus the sync's own writes, not a fresh read of
committed state: a toggle another writer commits after the load is not seen, so
under concurrent edits the count can differ from a query issued afterwards. Two
paths reload a single row from committed state to judge ownership: an adoption
claim that loses to a concurrent sync of the same estate, and an owner/name
insert race that loses to a concurrent sync. A row reloaded that way is
reported from the reloaded state, so a toggle committed before the reload can
be seen, and a row it makes enabled is not reported as left disabled. The sync
does not overwrite such a toggle, because preserving a disabled row leaves
`ingestion_enabled` untouched. A row the sync itself turns off because it left
the catalogue is counted in `repositories_deactivated` instead, not in the
left-disabled set; a row it turns off because its catalogue entry became
inactive is an ordinary update and is counted in `repositories_updated`. A
repository another estate owns is reported in `repositories_conflicted`.
`repositories_left_disabled` is a bounded preview of the left-disabled set: it
holds at most 100 slugs, in sorted order, so a large estate cannot produce an
unbounded result body.

If another estate already owns a repository that this estate's catalogue names,
sync leaves that row untouched and reports the slug in
`result.repositories_conflicted`. Remove the repository from this estate's
catalogue to clear the report. Sync never moves a row between estates, so the
row stays with the owning estate; removing the slug from the owning estate's
catalogue only disables that estate's own row and leaves this estate's report
in place.

A toggle applied to an ad hoc row lasts only until the row is adopted by a
catalogue entry, at which point the catalogue's active flag takes over.

To preview a sync without changing anything, pass `dry_run=True`. The result
reports the counts the sync would have produced, and the transaction is rolled
back:

```python
preview = await service.sync_from_catalogue("wildside", dry_run=True)
```

Each sync also writes one line per outcome-changing fact, so an operator can
follow an estate without reading the result object. A run that finishes logs
`SYNC_COMPLETED` with the estate key, whether it was a dry run, the duration
and the counts; a run that fails logs `SYNC_FAILED` with the sanitized reason
and re-raises. Each slug another estate owns logs `SYNC_CONFLICTED`, and each
repository whose ingestion flag the sync changed logs `INGESTION_TRANSITION`
with the transition and the new state. A `dry_run=true` line, whether it is the
completion or a slug event, describes work that was rolled back. The per-slug
lines appear only once the run's transaction has finished, so a run that fails
logs `SYNC_FAILED` alone and none of the changes it had started to make. The
completion event carries counts, never repository lists, and the developers'
guide lists the fields each event carries.

Behaviour changes that need action when upgrading, including re-applying a
disable that an earlier release reverted, are recorded in the
[migration guide](migration-guide.md).

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

## Estate management HTTP API (Task 2.5.b)

The runtime exposes a Falcon ASGI API for estate management. Its five
operations are defined in [`specs/openapi.yml`](../specs/openapi.yml) and
driven by `ghillie.estate.ports.EstateManagement`. The catalogue document
format is described in the
[Estate catalogue (Phase 1.1)](#estate-catalogue-phase-11) section; the sync
rules and their transition table are in
[Repository discovery and registration (Phase 1.3)](#repository-discovery-and-registration-phase-13).
This section covers only the HTTP surface.

### Authentication

Estate routes require `Authorization: Bearer <token>` when `GHILLIE_API_TOKEN`
is set. When the variable is unset, every route stays open, so local
development needs no credentials. `/health` and `/ready` never require the
header, because orchestrators cannot be expected to hold the token. A missing
or wrong token returns 401 `unauthorized` with a `WWW-Authenticate: Bearer`
challenge.

When `GHILLIE_API_TOKEN` is unset, start-up logs a warning that estate API
authentication is disabled, so an unauthenticated deployment is visible in the
logs. A value that is set but blank after trimming is a configuration error:
start-up logs an error and exits rather than silently disabling authentication.
A configured token shorter than 16 characters also logs a warning that a longer
random value is preferred.

### Schema bootstrap

The runtime does not touch the schema by default. When `GHILLIE_DATABASE_URL`
is set, set `GHILLIE_DB_BOOTSTRAP=create-all` to create any missing tables
during ASGI start-up, before the server accepts requests. The bootstrap uses
`create_all`, which checks for an existing table before issuing `CREATE TABLE`,
so it creates only missing tables; it does not migrate existing ones. The one
exception is the `reports` table: if it exists without the report telemetry
columns (`model_latency_ms`, `prompt_tokens`, `completion_tokens`,
`total_tokens`), bootstrap adds them with `ALTER TABLE ... ADD COLUMN`, which
needs ALTER privileges on that table. Any other non-blank value is an operator
error that stops start-up rather than starting with a half-configured schema. A
blank value is treated as unset.

Use the flag for a single replica, or for a compose deployment that has no
out-of-band migration step. Managed deployments run migrations out of band and
leave the flag unset. The existence check and `CREATE TABLE` are not atomic, so
replicas that start together can both see a missing table and race on the DDL;
PostgreSQL may fail the loser with a duplicate-table error, that replica fails
its start-up, and the orchestrator restarts it once the table exists. Prefer
one bootstrap replica or managed migrations when the platform cannot tolerate
that restart.

### Operations

| Operation         | Method and path                                | Purpose                                                                 |
| ----------------- | ---------------------------------------------- | ----------------------------------------------------------------------- |
| List estates      | `GET /estates`                                 | Return a page of estates and each one's most recent import.             |
| Import catalogue  | `POST /estates/{estate_key}/catalogue-import`  | Import one catalogue document, creating the estate when the key is new. |
| Sync registry     | `POST /estates/{estate_key}/registry-sync`     | Project the estate's imported catalogue into the repository registry.   |
| List repositories | `GET /estates/{estate_key}/repositories`       | Return a page of the estate's registered repositories.                  |
| Set ingestion     | `PATCH /repositories/{owner}/{name}/ingestion` | Enable or disable ingestion for one registered repository.              |

### Requests and responses

- `GET /estates` returns `items`, `limit`, `offset`, `has_more`, and
  `next_offset`. Each item carries `key`, `name`, `description`, and
  `last_import`, which holds `commit_sha` and `imported_at` or is `null`.
- `POST /estates/{estate_key}/catalogue-import` takes a JSON body and returns
  the import summary described below.
- `POST /estates/{estate_key}/registry-sync` takes no body and accepts the
  `dry_run` query flag. It returns `estate_key`, `state`, `dry_run`, the
  created, updated, and deactivated repository counts, the slugs in
  `repositories_conflicted`, and the `repositories_left_disabled` preview with
  its `repositories_left_disabled_count`.
- `GET /estates/{estate_key}/repositories` accepts `ingestion_enabled` (strict
  `true` or `false`) as a filter as well as the pagination parameters. Items
  carry `owner`, `name`, `default_branch`, `ingestion_enabled`, and
  `documentation_paths`.
- `PATCH /repositories/{owner}/{name}/ingestion` takes a JSON or
  `application/merge-patch+json` body of `{"ingestion_enabled": true}` or
  `{"ingestion_enabled": false}`. It returns `owner`, `name`,
  `ingestion_enabled`, and `changed`, which says whether the call altered the
  stored value.

### Importing a catalogue over HTTP

The import body is a JSON object, never a raw YAML document:

- `commit_sha` (required): the commit the document was read from, 1 to 64
  characters.
- `catalogue_yaml` (required): the catalogue document as YAML text.
- `estate_name` (optional): display name, 1 to 255 characters. When omitted, an
  existing name is kept and a new estate is named after its key.

Only `application/json` is accepted; another media type returns 415
`unsupported_media_type`. The `dry_run` query flag defaults to `false`. When
`true`, the document is validated and its counts reported without writing
anything.

The response reports `state`, `dry_run`, `skipped`, `skipped_reason`, and
`registry_sync_required` alongside `created`, `updated`, and `deleted` counts
for `projects`, `components`, `repositories`, and `edges`. A commit that was
already imported is skipped with reason `commit_already_imported`, and
`registry_sync_required` is `false` for a skipped or dry-run import.

### Pagination

`GET /estates` and `GET /estates/{estate_key}/repositories` share the same
pagination contract:

| Parameter | Range           | Default |
| --------- | --------------- | ------- |
| `limit`   | 1 to 500        | 50      |
| `offset`  | 0 to 2147483647 | 0       |

A value outside its range, a non-integer, or a repeated parameter returns 400
`invalid_input`; out-of-range pagination names the offending parameter in
`field`. Every page echoes `limit` and `offset` and adds `has_more` and
`next_offset`. `next_offset` is the offset of the following page, or `null`
when the page is the last one.

### Worked examples

The examples use `GHILLIE_API_TOKEN`, the variable the runtime reads, and
assume it holds a configured token. Import a catalogue as a dry run first; the
`dry_run=true` query flag validates the document and reports counts without
writing anything.

Start from this example catalogue. A project owns its components, and a
component names a repository when it has code to track:

```yaml
version: 1
projects:
  - key: alpha
    name: Alpha
    components:
      - key: alpha-api
        name: Alpha API
        type: service
        lifecycle: active
        repository:
          owner: org
          name: alpha
          default_branch: main
```

The request body carries that document as a string, so build it with a JSON
encoder rather than hand-escaping the newlines:

```bash
jq -n --rawfile catalogue estate.yaml \
  --arg commit_sha 0123456789abcdef0123456789abcdef01234567 \
  '{commit_sha: $commit_sha, catalogue_yaml: $catalogue}' > import.json

curl --fail-with-body \
  -X POST "http://localhost:8080/estates/demo/catalogue-import?dry_run=true" \
  -H "Authorization: Bearer ${GHILLIE_API_TOKEN}" \
  -H "Content-Type: application/json" \
  --data @import.json
```

To apply the import, omit the flag or pass `dry_run=false`. The body always
carries `commit_sha` and `catalogue_yaml`; `estate_name` is optional.

List an estate's repositories with pagination:

```bash
curl --fail-with-body \
  "http://localhost:8080/estates/demo/repositories?limit=25&offset=50" \
  -H "Authorization: Bearer ${GHILLIE_API_TOKEN}"
```

`limit` and `offset` select the page, and the response echoes both together with
`has_more` and `next_offset`. Add `ingestion_enabled=true` or
`ingestion_enabled=false` to filter by ingestion state.

### Request size limit

Catalogue import and the ingestion toggle read a body through a single limit of
1,048,576 bytes (1 MiB). A declared `Content-Length` over that limit is
rejected before the body is buffered, and a chunked body that exceeds it is
rejected after reading one byte past the limit. Either case returns 413
`payload_too_large`, and the envelope carries `max_bytes`.

### Error envelope

Every failure uses one JSON envelope:

- `code`: stable machine-readable identifier.
- `description`: human-readable explanation.
- `title`: short error title.
- `field`: optional name of the input field that failed validation.
- `issues`: optional array of `code` and `message` objects, one per validation
  problem; catalogue rejections use `code` `catalogue_schema`.
- `max_bytes`: optional largest accepted body size, present on 413.

The documented statuses are:

| Status | Code                     | Declared by                 | Meaning                                                                |
| ------ | ------------------------ | --------------------------- | ---------------------------------------------------------------------- |
| 400    | `invalid_input`          | all five operations         | Malformed body or query parameter, or pagination outside its range.    |
| 401    | `unauthorized`           | all five operations         | Missing or wrong bearer token when authentication is enabled.          |
| 404    | `estate_not_found`       | sync and repository listing | No estate has the supplied key.                                        |
| 404    | `repository_not_found`   | ingestion toggle            | No registered repository has that owner and name.                      |
| 409    | `conflict`               | import and sync             | The write conflicts with an existing record.                           |
| 413    | `payload_too_large`      | import and ingestion toggle | The request body exceeds the accepted size.                            |
| 415    | `unsupported_media_type` | import and ingestion toggle | The request media type is not accepted.                                |
| 422    | `catalogue_invalid`      | import                      | The uploaded document failed catalogue validation.                     |
| 500    | `internal_error`         | all five operations         | An unexpected server failure.                                          |
| 500    | `registry_sync_failed`   | sync                        | The sync failed for a reason that is neither a conflict nor an outage. |
| 503    | `storage_unavailable`    | all five operations         | The database cannot be reached.                                        |

### Request outcome events

Every estate API request writes one structured outcome event to the application
log, whatever the response:

```plaintext
estate.http.outcome operation=import_catalogue outcome=rejected status_class=4xx
```

`operation` names the service method that served the request, or would have:
`list_estates`, `import_catalogue`, `sync_registry`, `list_repositories`, or
`set_ingestion`. `outcome` is `succeeded` for a 2xx, `rejected` for a 4xx, and
`failed` for anything else. `status_class` is the response's hundred band, such
as `2xx` or `5xx`. Nothing else is recorded in the line: estate keys, owners,
repository names, commits, and error text never appear, so the events can be
counted per operation without their cardinality growing with the estate.
Requests rejected before routing, including a 401 for a missing bearer token,
are recorded against the endpoint the path names.

A success logs at INFO, a rejection at WARNING, and a failure at ERROR. An
operator can count failures per operation from the log, and an alert can watch
for `estate.http.outcome` lines with `outcome=failed`.

Two limits apply to that alert. It needs `GHILLIE_LOG_LEVEL` to admit ERROR
records: the default `INFO` does, but `CRITICAL` filters out every failure
event, so the alert would never fire. And the handler writes through a bounded
queue whose overflow policy can drop a record, so the events give rates and
trends rather than an exact request count.

## Incremental GitHub ingestion (Phase 1.3.b)

Ghillie polls GitHub per managed repository and appends activity into the Bronze
`raw_events` table. Each repository has per-kind watermarks stored in
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
`GHILLIE_TEST_DB=sqlite` before invoking `make test`. To run against an
existing Postgres instead, set `GHILLIE_TEST_DB` to a
`postgresql+asyncpg://user:password@host:port/database` URL; the fixtures reset
that database's `public` schema per test, so point it at a disposable one. Run
that backend serially, because `make test` uses `pytest -n auto` and parallel
workers would each reset the same schema:

```bash
GHILLIE_TEST_DB=postgresql+asyncpg://user:password@host:port/database \
    uv run pytest -q tests/
```

See `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md` for full guidance.

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
into a minimal Python 3.14 slim image with a non-root user.

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

| Variable               | Default   | Description                                     |
| ---------------------- | --------- | ----------------------------------------------- |
| `GHILLIE_HOST`         | `0.0.0.0` | Bind address for the server                     |
| `GHILLIE_PORT`         | `8080`    | Listening port for HTTP                         |
| `GHILLIE_LOG_LEVEL`    | `INFO`    | Log level for the server and its worker         |
| `GHILLIE_API_TOKEN`    | unset     | Bearer token; unset disables authentication     |
| `GHILLIE_DB_BOOTSTRAP` | unset     | `create-all` creates missing tables at start-up |

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

The on-demand report endpoint requires a database connection and a status model
backend. Set the `GHILLIE_DATABASE_URL` environment variable to enable the
estate routes:

```bash
export GHILLIE_DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/ghillie"
```

When `GHILLIE_DATABASE_URL` is not set, the runtime starts in health-only mode
(backwards compatible with existing deployments) and only `/health` and
`/ready` are available. The report route is registered only when
`GHILLIE_STATUS_MODEL_BACKEND` is also set. The endpoint also respects
`GHILLIE_REPORT_SINK_PATH` — when set, generated reports are written to the
filesystem as Markdown, just like scheduled reports.

### Runtime environment variables

| Variable                        | Required          | Applies to        | Description                                                                                       |
| ------------------------------- | ----------------- | ----------------- | ------------------------------------------------------------------------------------------------- |
| `GHILLIE_DATABASE_URL`          | For estate routes | Estate and report | Database connection URL. Unset leaves only `/health` and `/ready`; set enables the estate routes. |
| `GHILLIE_STATUS_MODEL_BACKEND`  | For report routes | Report            | Status model backend (for example `mock`). Adds the report route when set with the database URL.  |
| `GHILLIE_API_TOKEN`             | No                | All except probes | Bearer token guarding every route except `/health` and `/ready`; unset leaves the API open.       |
| `GHILLIE_DB_BOOTSTRAP`          | No                | Start-up          | `create-all` creates missing tables at start-up; any other non-blank value stops start-up.        |
| `GHILLIE_REPORT_SINK_PATH`      | No                | Report            | Directory for Markdown report output.                                                             |
| `GHILLIE_REPORTING_WINDOW_DAYS` | No                | Report            | Default window size (default: 7).                                                                 |

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

- **Project metadata**: key, name, description, programme, and
  documentation paths from the catalogue.
- **Component evidence**: one entry per component listing its key,
  name, type (service, UI, library, etc.), lifecycle stage (`planned`, `active`,
  `deprecated`), optional repository slug, and optional repository report
  summary.
- **Component dependency edges**: directed relationships between
  components within the same project (`depends_on`, `blocked_by`,
  `emits_events_to`), with kind (`runtime`, `dev`, `test`, `ops`) and optional
  rationale.
- **Previous project reports**: up to two most recent project-scope Gold
  reports for contextual continuity.

### Components with repositories

When a component has a mapped repository and the repository has at least one
Gold-layer report, the component evidence includes a
`ComponentRepositorySummary` with:

- repository slug (e.g. `leynos/wildside`)
- the latest report's status (`on_track`, `at_risk`, `blocked`, `unknown`)
- narrative summary, highlights, risks, and next steps
- reporting window timestamps

### Planned and non-code components

Components without repositories (lifecycle `planned`) are included in the
bundle, with `repository_slug` and `repository_summary` set to `None`. Their
lifecycle stage and any catalogue notes are preserved, allowing downstream
summarization to distinguish between active and planned work.

### Cross-project dependencies

Dependency edges whose target component belongs to a different project are
excluded from the bundle. Only intra-project edges appear in the `dependencies`
field. Cross-project edges remain in the catalogue for future estate-level
aggregation.

### Building a project evidence bundle

```python
import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ghillie.evidence import ProjectEvidenceBundleService


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

The service accepts two session factories: one for catalogue storage, and one
for Silver/Gold storage. In typical deployments, both point to the same
database engine, but separate session factories allow future database
separation without code changes.
