# Ghillie Developers' Guide

This guide covers local development setup, tooling, and deployment workflows
for contributors to the Ghillie project.

## Coverage publication

Main owns CodeScene. Pull-request CI measures `ghillie` serially with
`generate-coverage`, compares the result with the ratchet baseline that `main`
wrote (`with-ratchet: 'true'`), and uploads no artefact
(`publish-artefact: 'false'`). Nothing a pull request can start talks to
CodeScene, holds `CS_ACCESS_TOKEN`, or needs full Git history. The step is
guarded to the `pull_request` event, because `generate-coverage` saves its
baseline on a push to `main` and `coverage-main.yml` must be the only workflow
writing it.

Both workflows use `.coverage-baseline.python-main-owned`; the separate cache
namespace prevents the source-scoped measurement from being compared with the
broader pre-migration baseline.

After each merge, `coverage-main.yml` regenerates the same measurement,
advances the ratchet, and uploads `coverage.xml` with
`upload-codescene-coverage` in explicit `mode: upload`. A check step learns
whether the token exists with the one command
`echo "available=${{ secrets.CS_ACCESS_TOKEN != '' }}" >> "$GITHUB_OUTPUT"`,
which binds nothing, and the upload step runs only when that output is `true`
and `github.ref == 'refs/heads/main'`. The token reaches the uploader only as
its `access-token` input, because the uploader is a composite action and a step
`env` would reach every action nested in it. The ref guard means that a
`workflow_dispatch` aimed at a branch cannot publish that branch as `main`. Its
concurrency group never cancels, so no upload or baseline write is abandoned.
The group is keyed on `github.ref` alone, so runs on `main` never overlap, a
newer trigger replaces an older pending run rather than queueing behind it, and
a branch dispatch cannot displace a pending push to `main`. GitHub does not
promise to start runs in trigger order, so this is not a guarantee of commit
order: an older run can still publish last, and its coverage and baseline then
stand until a later successful run supersedes them; that is accepted. A
dispatch on `main` saves no baseline, because the baseline is saved only on a
push, so one that replaces pending pushes leaves the ratchet baseline behind
until the next push. A manual re-run of an older run keeps its SHA and its run
id: it republishes that commit's coverage to CodeScene, but its baseline cache
key already exists, so it replaces no baseline unless the original run saved
none. Merges made by the Dependabot automerge workflow's `GITHUB_TOKEN` fire no
push, so they are published only by a manual dispatch; this is a known
exception until the shared automerge workflow dispatches the publisher itself.

The retired `installer-checksum` input, the `CODESCENE_CLI_SHA256` variable,
and the `get-codescene-sha.yml` refresher are gone. The shared uploader selects
and verifies the `cs-coverage` archive from its own manifest.

`make test-workflow-contracts` holds this shape by running
`cv005-contracts check`, the shared contract library in `leynos/shared-actions`
(`packages/cv005-contracts`), from the full commit named by
`CV005_CONTRACTS_REF` in the Makefile. The library follows local
reusable-workflow calls from every workflow a pull request can start, refuses
the CodeScene host, credential, client and uploader in that closure, and holds
the publisher, the lanes, the environment placement and the lanes' selection
parity to the rules above. A fix to a rule reaches this repository as a pin
bump. The target needs `uv`, which fetches the Python 3.13 the library runs
under; `.github/cv005.toml` holds the repository's parameters. The decision is
recorded in
[ADR-004](adrs/adr-0004-adopt-the-shared-cv005-contract-library.md).
`tests/workflow_contracts/test_cv005_wiring.py` fails if the pin is not a full
commit, the target stops running the pinned checker, the repository parameter
is wrong, `make all` drops the target or CI stops running it.

Both coverage lanes set up Python 3.14 with `actions/setup-python`, inside the
project's `requires-python` (`>=3.14`). generate-coverage chooses its
interpreter from its `python-version` input, then `UV_PYTHON`, then
`.python-version`, then the `python3` on `PATH`, which is the most recent
`setup-python` step before the call in its job; `uv sync` refuses an
interpreter outside `requires-python`.
`tests/workflow_contracts/test_coverage_python_version.py`, with its reader in
`tests/workflow_contracts/coverage_python_sources.py`, requires every
generate-coverage call in the pull-request lane and the publisher to declare at
least one of those sources, every declared source to name the same version,
that version to be inside `requires-python`, and both lanes to measure on that
one version. A `setup-python` step guarded by `if:` or allowed to fail with
`continue-on-error` declares nothing. The ratchet baseline key already carries
the interpreter (`ratchet-baseline-<os>-py<major.minor>-`), so a lane on
another Python would miss its baseline rather than compare against the wrong
one; the contract turns that silent restart into a failure. It uses
`packaging`, a development dependency, and stays a local contract: the shared
CV-005 library holds the interpreter only through an opt-in `UV_PYTHON` pin
that these lanes do not use.

## Spelling policy

Run `make spelling` to enforce en-GB-oxendict prose spelling. The generated
`typos.toml` starts from the shared estate dictionary, refreshes its untracked
local cache only when the authority is newer, and then applies the narrow
repository policy in `typos.local.toml`. Edit the local policy and regenerate
the configuration rather than changing generated entries by hand.

## Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) for dependency management
- Docker (for k3d local previews)
- Helm 3.x (for chart development and testing)
- Node.js (optional, for py-pglite Postgres tests)

## Development setup

Clone the repository and install dependencies:

```bash
git clone https://github.com/leynos/ghillie.git
cd ghillie
make build
```

Run the quality gate chain to verify the development environment:

```bash
make all
```

This runs formatting checks, linting, type checking, and tests.

## Quality gates

The project enforces these quality gates before commits:

| Target                    | Description                                      |
| ------------------------- | ------------------------------------------------ |
| `make fmt`                | Format Python and Markdown sources               |
| `make check-architecture` | Run Hecate import-direction architecture checks  |
| `make interrogate`        | Fail on any undocumented Python definition       |
| `make lint`               | Run Hecate, Interrogate, Ruff, and Skylos checks |
| `make check-fmt`          | Verify formatting without changes                |
| `make typecheck`          | Run the type checker                             |
| `make test`               | Run pytest with parallel execution               |
| `make helm-lint`          | Lint the Ghillie Helm chart                      |
| `make helm-test`          | Run Helm chart tests                             |

Run all gates before committing:

```bash
make check-fmt && make lint && make typecheck && make test && make helm-lint
```

### Docstring coverage

`make interrogate` runs Interrogate `1.7.0` as an isolated `uv tool` on Python
3.14, because Interrogate parses source with the interpreter that runs it and
this code uses template strings. It scans `ghillie`, `scripts`, and `tests`
recursively, with Interrogate's default exclusions, so check a new file against
the verbose report. Add a new Python directory to `INTERROGATE_TARGETS` in the
`Makefile`.

The target fails when the tool exits non-zero, and also when the verbose report
holds any `MISSED` row, because the percentage is rounded to one decimal place
and would pass a lone gap. A failure prints the report, so the `MISSED` rows
name the undocumented definitions. `make lint` runs the target after the
architecture check and before Ruff and Skylos, so a missing docstring stops
linting before either of those tools starts.

## Workflow pins and Dependabot

Dependabot owns the upgrade of GitHub Actions and reusable workflows, including
calls into `leynos/shared-actions`. Contract tests that assert a caller's exact
commit SHA create a lockstep dependency: every time Dependabot opens a bump PR,
the test fails until a human edits the pinned constant to match. That defeats
the purpose of automated dependency updates and turns a routine bump into a
manual chore.

Contract tests may still verify the *shape* of a reusable-workflow caller. They
must not verify the specific SHA value.

- Do assert the workflow references the correct reusable workflow path.
- Do assert the ref is pinned to a full 40-character commit SHA, not a
  mutable branch such as `main` or `rolling`.
- Do assert the expected `on:` triggers, least-privilege `permissions:`, and
  the inputs the caller relies on.
- Do not hard-code the current SHA value as an expected string. Match it with
  a pattern instead.
- Do not fail a test purely because Dependabot bumped the pinned SHA.

```python
import re

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def test_uses_pinned_full_sha(caller_step):
    ref = caller_step["uses"].split("@")[-1]
    assert SHA_RE.match(ref), f"expected a 40-hex commit SHA, got {ref!r}"
```

If a workflow's behaviour genuinely depends on a feature only present from a
particular commit onwards, express that as a comment or a changelog note, not
as a test assertion on the SHA string.

### Tool versions

Every tool a CI job installs names an exact version, and every ruff invocation
goes through one pin. An unpinned `uv tool install ruff` is what turned `main`
red at "Check formatting" on 2026-08-13: it followed upstream into a release
that formats Python inside Markdown fences, against a tree formatted by an
older one. The Makefile ran whichever ruff was on `PATH`, so nothing in the
repository could disagree with it.

| Tool                | Where the version lives                                                                 |
| ------------------- | --------------------------------------------------------------------------------------- |
| `ruff`              | `RUFF_VERSION` in the Makefile, matched by the `ruff==` requirement in `pyproject.toml` |
| `typos`             | `TYPOS_VERSION` in the Makefile                                                         |
| `mbake`             | `MBAKE_VERSION` in `ci.yml`                                                             |
| `markdownlint-cli2` | `MARKDOWNLINT_CLI2_VERSION` in `ci.yml`                                                 |
| `pajv`              | `PAJV_VERSION` in `ci.yml`                                                              |
| `ty`                | the `dev` dependency group, resolved in `uv.lock`                                       |

`tests/test_ci_workflow_contract.py` enforces all of it. Every
`uv tool install`, `npm install -g` and `bun install -g` in `ci.yml` must name
an exact version, and the test resolves a version written as `${VERSION}` back
to the value the step's `env` gives it, so a variable holding `latest` fails
and a misspelt variable name fails rather than looking pinned. A moving tag or
a range is not a pin: `@latest`, `^0.23`, `~0.23.0`, `1.*` and `>=1.4.6` are
each rejected by name. On the Makefile side, `RUFF` must expand to
`uv tool run ruff@$(RUFF_VERSION)`, no recipe may call `ruff` from `PATH`, and
the Makefile pin must equal the `pyproject.toml` requirement. Each assertion
matches the command or recipe line itself, not a comment near it, and carries a
mutation check.

## Architecture checks

Ghillie uses Hecate as the static architecture fitness function for Python
import direction. Run it directly with:

```bash
make check-architecture
```

The same check runs before Ruff as part of `make lint`, so CI and local linting
share the same architecture gate. The CI lint step also runs Skylos dead-code
detection through this target.

The Hecate policy is stored in `[tool.hecate]` in `pyproject.toml`. When adding
or moving modules:

- update the policy if the module introduces a new package boundary;
- put specific prefixes before broad prefixes because Hecate uses first-match
  group classification;
- keep composition-root prefixes narrow and explicit;
- prefer refactoring a dependency edge over adding `ignore_imports`;
- if an ignore rule is unavoidable, include a precise reason that explains why
  the edge is intentional; and
- run `make check-architecture` before opening a pull request.

The current policy groups modules as composition roots, domain ports,
application modules, inbound adapters, and outbound adapters. The adoption
rationale is recorded in
`docs/adrs/adr-0003-adopt-hecate-for-architecture-checks.md`.

## Registry synchronization

Catalogue synchronization projects an estate's catalogue components into the
Silver `Repository` table. The policy that decides each repository's
`ingestion_enabled` flag is separate from the persistence work, so the rules
can be read and tested without a database.

`ghillie.registry.policy` holds that decision as a pure function. The module
imports only the standard library, which is why Hecate groups it under
`domain_ports`; keep it that way when changing the module. The transitions it
produces are:

| Row state               | Catalogue state   | Transition            |
| ----------------------- | ----------------- | --------------------- |
| absent                  | present, active   | `ADOPT` (enabled)     |
| absent                  | present, inactive | `ADOPT` (disabled)    |
| unlinked, this estate   | present           | `ADOPT`               |
| linked, this estate     | present, active   | `PRESERVE`            |
| linked, this estate     | present, inactive | `DISABLE_INACTIVE`    |
| linked, this estate     | absent            | `DISABLE_REMOVED`     |
| unlinked, this estate   | absent            | `PRESERVE`            |
| owned by another estate | present           | `CONFLICT` (reported) |
| owned by another estate | absent            | `CONFLICT` (silent)   |

`RepositoryRegistryService.sync_from_catalogue(estate_key, *, dry_run=False)`
runs the whole projection inside one Silver transaction:

- with `dry_run=False`, the rows it created, updated, or disabled are committed;
- with `dry_run=True`, the same work runs and the transaction is rolled back, so
  the call returns the counts it would have produced and persists nothing.

The service resolves the insert strategy once in its constructor and hands it,
with the dry-run flag, to `ghillie.registry.sync.sync_from_catalogue` as a
`SyncOptions` record. That record is the syncing function's only keyword
argument, so a further persistence choice joins it rather than widening a
signature that already names the estate it projects. Its clock defaults to
`utcnow` and is read once per run, so every row a single run touches carries
the same `last_synced_at`.

Adoption of an unowned row is atomic. The sync claims it with a conditional
update and reports a conflict if another estate claimed it first, so concurrent
syncs cannot silently replace each other's claim. A race to insert the same
repository is arbitrated by the owner/name uniqueness constraint.

Either way the call returns a `SyncResult`. `repositories_created`,
`repositories_updated`, and `repositories_deactivated` count the changes.
`repositories_conflicted` lists this estate's catalogue slugs that another
estate owns; sync leaves those rows untouched. `repositories_left_disabled`
previews the active catalogue repositories whose linked Silver row was disabled
in the view the sync loaded and that the sync left disabled, and
`repositories_left_disabled_count` carries the total across the estate. The
pair observes that view plus the sync's own writes rather than re-reading
committed state, so a toggle another writer commits after the load is not seen
and is not overwritten. Two paths reload a single row from committed state to
judge ownership: a lost adoption claim and a lost owner/name insert race. A row
reloaded that way is reported from the reloaded state, so a toggle committed
before the reload can be seen, and a row it makes enabled is not reported as
left disabled. They say that ingestion is off, not why: a row can have been
disabled by an operator or by an earlier removal. `repositories_deactivated`
counts only removed rows that this sync turned from enabled to disabled, so a
removed row an operator had already disabled is not counted again.

The rules and their rationale are recorded in
[ADR-005](adr-005-registry-sync-preserves-operator-ingestion-toggles.md), the
upgrade actions in the [migration guide](migration-guide.md), and the
surrounding catalogue and Silver design is in
[the Bronze/Silver architecture design](ghillie-bronze-silver-architecture-design.md#92-repository-discovery-and-registration-phase-13a).

### Persistence and upsert strategies

`ghillie.registry.storage` owns the Silver persistence SQL for registry sync;
`ghillie.registry.sync` holds the decisions and the orchestration, and calls
into storage for the statements themselves.

The insert is an `UpsertStrategy`, a protocol whose `build(session, row)`
method returns a SQLAlchemy `Insert` or `None`. Returning `None` declines the
upsert, and the caller then inserts plainly so the uniqueness constraint
decides the outcome. `DialectUpsertStrategy` is the default; it resolves the
session's dialect and delegates to the named strategy for it.
`PostgresUpsertStrategy` and `SqliteUpsertStrategy` both emit
`ON CONFLICT DO NOTHING`, and `PlainInsertStrategy` is the named fallback for a
dialect without an upsert construct.

To choose a strategy explicitly, pass `upsert_strategy=` to
`RepositoryRegistryService(...)`. The service resolves its default once in the
constructor and passes the chosen strategy to the sync inside `SyncOptions`, as
described above.

Storage also reports outcomes and guarded changes:

- `InsertOutcome` is `INSERTED`, `CONFLICT`, or `DECLINED`; sync uses it to
  distinguish its own insert from a competing writer's row and from a declined
  upsert.
- `claim_unowned_repository` and `deactivate_if_still_enabled` return a
  `bool` meaning "this sync made the change", so a claim or disable that lost a
  race is not counted.

## Estate management boundary

`ghillie.estate` is the application boundary for catalogue import, registry
sync, repository listing, and ingestion toggles. Adapters depend on
`ghillie.estate.ports.EstateManagement`, a `typing.Protocol`; the shipped
implementation is `ghillie.estate.service.EstateManagementService`. The port
contract is that implementations own their units of work and translate
persistence and catalogue failures into `ghillie.estate.errors`, so the HTTP
and CLI layers never import a catalogue, registry, or SQLAlchemy exception.
`ghillie/estate/persistence.py` is the storage boundary: it issues the
catalogue and registry calls and classifies their failures into the estate
error vocabulary.

### Service responsibilities

- **Untrusted YAML off the event loop.** `import_catalogue` validates the key,
  then runs the injected catalogue parser through `asyncio.to_thread`, so
  parsing a client-supplied document cannot block the loop. The production
  parser is `ghillie.catalogue.loader.parse_catalogue_text`. A
  `CatalogueValidationError` becomes a `CatalogueRejectedError` holding one
  `Issue(code="catalogue_schema")` per validation message.
- **Per-estate serialization.** Import and sync each run under an
  `asyncio.Lock` obtained from `_lock_for`. Each `EstateManagementService`
  instance keeps its own lock table, so the lock serializes import and sync
  only between calls that reach the same instance: two instances in one process
  do not share it, and neither do worker processes or replicas. Serializing
  imports therefore relies on the application building one service instance in
  one worker in one replica, which is the MVP deployment. The locks live in a
  `weakref.WeakValueDictionary`, so a coroutine inside `async with` holds the
  only strong reference and an idle estate retains no lock. Two concurrent
  requests for one estate through that instance cannot interleave their
  catalogue writes, while different estates proceed independently.
- **Failure translation.** SQLAlchemy and registry failure classification lives
  in `ghillie/estate/persistence.py`, the only estate module that imports
  `sqlalchemy.exc`. `ghillie/estate/translation.py` holds only the pure
  catalogue-validation translation: a `CatalogueValidationError` becomes a
  `CatalogueRejectedError` with one `catalogue_schema` `Issue` per message.
  Neither module logs, so the service keeps ownership of the D21 record that
  accompanies the outcome. An `IntegrityError` raised by an import or by a
  registry projection becomes `EstateConflictError`. Any other SQLAlchemy
  failure from a catalogue read or write becomes `StorageUnavailableError`, and
  a non-integrity SQLAlchemy failure raised by the registry projection becomes
  `RegistrySyncFailedError`. An ingestion toggle maps only
  `RepositoryNotFoundError` and a storage outage, so an `IntegrityError` there
  becomes `StorageUnavailableError` like any other SQLAlchemy failure. A
  registry projection failure is classified through
  `RegistrySyncError.__cause__`: an `IntegrityError` cause is a conflict, and
  `OperationalError` or `InterfaceError` causes are storage outages. The
  registry's `ESTATE_NOT_FOUND_REASON` becomes `EstateNotFoundError`; anything
  else becomes `RegistrySyncFailedError`. The adapter raises these errors
  directly, so the service contains no `SQLAlchemyError` handling.
- **Right database for Silver.** `list_repositories` lists through the
  registry's own session factory rather than the catalogue factory, because the
  two stores can be deployed separately.

### Request value types

`ghillie.estate.models` holds the frozen, slotted dataclasses that the port and
its adapters pass. Hecate classifies it, with `ghillie.estate.errors` and
`ghillie.estate.ports`, as `domain_ports`, so it imports only the standard
library and estate-owned modules.

- `CatalogueImportRequest` groups `catalogue_yaml`, `commit_sha`,
  `estate_name`, and `dry_run`. The grouping keeps the port signature small and
  lets an adapter pass one value through without re-listing each field;
  `estate_name=None` keeps an existing name and names a new estate after its
  key.
- `PageRequest` carries `limit` and `offset`; `RepositoryQuery` adds the
  optional `ingestion_enabled` filter. `Page[T]` and `RepositoryPage` return
  the items with `limit`, `offset`, `has_more`, and `next_offset`.
- The pagination bounds are module constants: `DEFAULT_PAGE_LIMIT` 50,
  `MAX_PAGE_LIMIT` 500, and `MAX_PAGE_OFFSET` `2**31 - 1`. `MAX_PAGE_OFFSET` is
  a domain-level ceiling in `ghillie/estate/models.py`;
  `ghillie/catalogue/queries.py` enforces the same storage range before the
  value is bound, because SQLite raises `OverflowError` beyond its signed
  64-bit bind range and PostgreSQL rejects an out-of-range `OFFSET` as a
  storage error.
- `MAX_REQUEST_BODY_BYTES` is an HTTP transport limit of 1 MiB, defined in
  `ghillie/api/estate/resources.py`; that adapter enforces it.
- `validate_new_estate_key` applies `NEW_ESTATE_KEY_PATTERN` only when the
  import creates an estate; `validate_estate_key_reference` accepts any key of
  one to `MAX_ESTATE_KEY_LENGTH` (64) characters, so keys created earlier
  through Python stay reachable (D16).

### Error vocabulary

`ghillie.estate.errors` is the whole vocabulary an adapter may handle: `Issue`,
the `EstateError` base class, `EstateNotFoundError`, `InvalidEstateKeyError`,
`InvalidPaginationError`, `CatalogueRejectedError`, `RepositoryNotFoundError`,
`EstateConflictError`, `StorageUnavailableError`, and
`RegistrySyncFailedError`. Each error carries the minimum data needed to render
the contract: `estate_key` for a missing or invalid key, `field` and `reason`
for pagination, `owner` and `name` for a repository, and `issues` for a
rejected catalogue. `ghillie.api.errors` maps these types to a status and code;
adapters must see only these types, never a catalogue, registry, or SQLAlchemy
exception in their place.

### HTTP adapter and composition

The inbound adapter is `ghillie/api/estate/resources.py`. It defines
`EstateCollectionResource`, `CatalogueImportResource`, `RegistrySyncResource`,
`EstateRepositoryCollectionResource`, and `RepositoryIngestionResource`, each
holding an `EstateManagement` port. The resources depend on no catalogue,
registry, or SQLAlchemy module: every failure they can see is an estate error,
mapped centrally by `ghillie.api.errors`. Request and response bodies are
msgspec structs in `ghillie/api/estate/schemas.py`; request structs forbid
unknown fields, so a malformed body becomes one `DecodeError` and a 400.

`ghillie/api/factory.py` composes the service. `build_estate_service`
constructs one `RepositoryRegistryService(session_factory, session_factory)`
and passes it to `EstateManagementService(session_factory, registry=registry)`,
so that wiring shares one session factory between the catalogue and Silver
stores.

The adapter's dependency direction is inward. The package docstring in
`ghillie/api/estate/__init__.py` states that the resources depend only on
`ghillie.estate.ports`, `ghillie.estate.models`, and `ghillie.estate.errors`;
`resources.py` imports the `EstateManagement` port under `TYPE_CHECKING` and
the request and result value types from `ghillie.estate.models`, while
`schemas.py` imports only the standard library and msgspec. The resources also
use `InvalidInputError` and `PayloadTooLargeError` from `ghillie.api.errors`,
which is the adapter's own central error mapping, not a domain module. No
module under `ghillie/api/estate/` imports catalogue, registry, or SQLAlchemy
code.

### Authentication and start-up middleware

`BearerTokenMiddleware` in `ghillie/api/auth.py` enforces the optional token
that `ghillie.runtime._read_api_token` supplies through
`AppDependencies.api_token`. When a token is configured it requires
`Authorization: Bearer <token>` on every route except `GET /health` and
`GET /ready`, compares the supplied credential with `hmac.compare_digest`, and
raises `falcon.HTTPUnauthorized` on failure; the app's Falcon HTTP error
handler renders that as 401 `unauthorized` with a `WWW-Authenticate: Bearer`
challenge. With no token it logs a warning and returns without checking.
`AppDependencies.api_token` is declared with `repr=False`, so the secret cannot
appear in a dataclass repr.

`StorageBootstrapMiddleware` in `ghillie/storage_bootstrap.py` implements only
the ASGI lifespan hook `process_startup`, which calls
`init_all_storage(engine)` before the server accepts requests. It does no
request or response work. `ghillie.runtime.create_app` supplies
`bootstrap_engine` only when `GHILLIE_DATABASE_URL` is set and
`GHILLIE_DB_BOOTSTRAP=create-all`, and `ghillie.api.app._build_middleware`
appends the middleware to the Falcon stack.

Running the DDL from the lifespan hook is deliberate. The lifespan start-up is
the one point every ASGI driver, including Granian, awaits before it accepts
its first request, so the tables exist before any request can read them. An
explicit `init_all_storage` hook called from `create_app` would still have to
be awaited by that same driver at that same moment, so it would add a wiring
step without changing the ordering guarantee. The composition root keeps the
decision of whether the DDL runs at all: the engine is supplied only for the
`GHILLIE_DB_BOOTSTRAP=create-all` opt-in, so a managed deployment never
bootstraps its schema here (D13).

Both are composed in `ghillie/api/app.py`. `_build_middleware` appends the
bearer check first so an unauthenticated request never opens a database
session, then the SQLAlchemy session manager, and finally the bootstrap
middleware because it implements only the lifespan hooks. Resources do not
construct either middleware; `ghillie.runtime` and `ghillie.api.app` are the
composition root for the middleware, and `ghillie.api.factory` is the
composition root for the estate and reporting services.

### Worker logging configuration

Granian calls the application factory in a worker process, so the logging
configuration that `main` performs in the parent process never reaches the
worker. `ghillie.runtime.create_app` therefore applies `GHILLIE_LOG_LEVEL`
through `configure_logging` before it delegates to `ghillie.api.app.create_app`
to build the app. Without that call the worker's application logs, including
the D21 mutation records, are discarded. `configure_logging` defaults to
`force=False`, so it leaves an existing handler in place and in-process callers
such as the unit tests are unaffected.

The decision is recorded under
[worker logging configuration](ghillie-design.md#worker-logging-configuration)
in the design document's decision records.

### Hecate group placement

Hecate enforces the declared import direction through `[tool.hecate]` in
`pyproject.toml`. The estate boundary spans four groups:

- `ghillie.estate.errors`, `ghillie.estate.models`, and `ghillie.estate.ports`
  are `domain_ports`; that group may import only `domain_ports`.
- The remaining `ghillie.estate` modules — the service, translation,
  observability, and collaborators code — fall under the generic
  `ghillie.estate` prefix in the `application` group, which may import
  `application`, `domain_ports`, and `outbound_adapter` modules.
- `ghillie.estate.persistence` and `ghillie.catalogue.queries` are
  `outbound_adapter` modules, the group allowed to import `application`,
  `domain_ports`, and other `outbound_adapter` modules.
- `ghillie.storage_bootstrap` is a `composition_root`, the group allowed to
  import every other layer.

Declaration order matters because Hecate uses first-match semantics. The leaf
`ghillie.estate.errors`, `ghillie.estate.models`, `ghillie.estate.ports`, and
`ghillie.estate.persistence` entries must precede the generic `ghillie.estate`
prefix, or the application group would claim the domain ports and the
persistence adapter. The composition-root group, which also holds
`ghillie.api.app` and `ghillie.api.factory`, is declared before the
inbound-adapter group so those modules are classified as composition roots
rather than by the generic `ghillie.api` prefix. There is no generic
`ghillie.catalogue` prefix, so the `ghillie.catalogue.queries` entry alone
decides its group.

The design rationale, including the component layout and the bootstrap and
authentication decisions, is recorded in
[HTTP API layer architecture](ghillie-design.md#84-http-api-layer-architecture).

### Mutation records (D21)

Import, sync, and ingestion-toggle attempts each emit one structured record,
whether they succeed or fail. Rendering is owned by `MutationRecorder` in
`ghillie/estate/observability.py`, which follows the shape that
`ghillie/registry/observability.py` established: the module is the only place
that renders these lines. The service decides which outcome applies and calls
the recorder; it measures no duration itself.

`ghillie/estate/collaborators.py` groups the three seams the service does not
own: the importer factory, the catalogue parser, and the recorder. The service
takes an `EstateCollaborators` value, defaulting to the production
implementations, so a test can substitute one seam without the others. The
recorder holds its clock, defaulting to `time.perf_counter`, so a test can pin
the rendered `duration_ms` exactly.

- Import records carry `operation=estate.import`, the estate key, the commit
  SHA (`-` when absent), the dry-run flag, the per-family created, updated, and
  deleted counts, the duration in milliseconds, and the outcome.
- Sync records carry `operation=estate.registry-sync`, the estate key, `-` for
  the absent commit, the dry-run flag, the created, updated, deactivated,
  conflicted, and left-disabled counts, the duration, and the outcome.
- Toggle records carry `operation=estate.set-ingestion`, the owner and name,
  the requested flag, the previous state and whether the call changed it, the
  duration, and the outcome.

The outcome vocabulary is `succeeded`, `skipped`, `failed`, and `cancelled`:

- `succeeded` is the normal terminal record.
- `skipped` is an import whose commit was already imported.
- `failed` records the error class and message, so an operator can tell a
  client error from a storage outage. A toggle failure that has no translation
  is re-raised unchanged after its record is written.
- `cancelled` is recorded because `asyncio.CancelledError` derives from
  `BaseException` and cannot be seen by an `except Exception` clause; the error
  still propagates so the caller's task unwinds.

Estate keys, repository identities, and failure messages are rendered with
`%r`, so a newline in client-supplied text cannot forge a second record. Read
operations emit no mutation record. The sync's own per-slug events
(`SYNC_COMPLETED`, `SYNC_CONFLICTED`, and so on) are separate and described in
[Registry sync events](#registry-sync-events); the transition table is in
[Registry synchronization](#registry-synchronization).

### HTTP outcome events (D27)

Every request to one of the five estate endpoints records one metric-style
event, whether it succeeds, is rejected, or fails:

```plaintext
estate.http.outcome operation=list_estates outcome=succeeded status_class=2xx
```

`ghillie/api/estate/observability.py` owns the vocabulary and rendering, and
`EstateOutcomeMiddleware` in the same module emits the line. The middleware is
registered first in the application's stack so its response hook runs last,
after the session middleware has settled the final status; Falcon calls that
hook even when an earlier request hook raised. A request rejected before
routing, such as an unauthenticated one, is therefore counted against the
endpoint its path names, matched through the same route shapes. The event
carries only three bounded labels: the operation (the `EstateManagement` method
name), the outcome (`succeeded`, `rejected`, or `failed`), and the status class
(`2xx`, `4xx`, or `5xx`). No estate key, repository name, commit SHA, or error
string is ever a label. A success logs at INFO, a rejection at WARNING, and a
failure at ERROR.

The one-event-per-request rule is a property of the middleware, not of the log
sink. femtologging writes each record through a bounded queue with an overflow
policy, so a queue that is full can drop a record, and the log can then hold
fewer events than the server handled. Read the events as the stream to rate and
trend, not as an exact request count; reconcile against a source that cannot
drop when the count must be exact.

When a new estate route is added, add it to `_ROUTE_OPERATIONS` in
`ghillie/api/estate/observability.py`; the path patterns used before routing
are derived from the same table.

## Dead-code detection

`make lint` runs Skylos `4.33.2` as an isolated `uv tool` with Python 3.14
against `ghillie/`. Skylos parses source using its own runtime's Python AST, so
pinning Python 3.14 prevents phantom dead-code findings from newer syntax that
an older tool runtime cannot parse. The blocking scan is local and
non-interactive: it neither uploads source nor collects provenance. Tests are
intentionally excluded from its liveness graph, and grep verification is
disabled, so test-only references cannot mask dead production code.

Treat each finding as dead code until its runtime caller is verified. Remove
genuine dead code. For a framework callback or protocol implementation that
static analysis cannot see, add a precise entry-point rule with the fully
qualified name and a reason in `[tool.skylos.dead_code]` in `pyproject.toml`.
Use `make skylos-allow` only when an entry-point rule cannot express the
boundary:

```bash
make skylos-allow SYMBOL=registered_handler REASON="Loaded by plugin registry"
```

The target rejects missing or whitespace-only `SYMBOL` or `REASON` values with
exit status 2 and records the reason in Skylos's documented allow list. Use
`SYMBOL`, rather than `NAME`, because WSL may inject `NAME` with the hostname.
`flock` serializes these read-modify-write updates through the ignored
repository-local `.skylos-whitelist.lock` file; set `SKYLOS_WHITELIST_LOCK` to
an alternate path only for isolated tests. Do not add broad or unexplained
exceptions; retain the verified caller rationale in the reviewing change and
remove an allow-list entry when its dynamic boundary no longer exists.

The registry sync dispatches its persistence helpers through the
`UpsertStrategy` protocol and the named dialect selector, which Skylos cannot
follow. It also records its events through `_SilverSyncContext.events`, a
dataclass field, so `SyncEventBuffer.record_conflict` and
`SyncEventBuffer.record_transition` are reached through an attribute chain that
Skylos does not traverse; `SyncEventBuffer.publish` is called by name on the
returned buffer and needs no rule. `pyproject.toml` therefore declares
`[[tool.skylos.dead_code.entrypoints]]` rules for the registry strategy
methods, the two buffer recorders, `dialect_upsert_strategy`, and
`_insert_values`, and `tests/unit/test_skylos_lint_contract.py` pins the same
names so the contract cannot drift unnoticed.

The Skylos Makefile contract is parsed with pinned Makeutil in
`tests/unit/test_skylos_lint_contract.py`; `make test` requires that parser.
Only the Makeutil-dependent parser contract tests skip in isolated runs where
Makeutil has not been provisioned, such as mutmut; the copied Makefile,
workflow, and ignore-file contracts still run. Ordinary `make test` retains its
hard Makeutil prerequisite, and CI and coverage install the pinned binary.
Before running the full suite locally, install the same pinned toolchain and
revision used in CI:

```bash
rustup toolchain install nightly-2026-05-28 --profile minimal
RUSTFLAGS="-Zpolonius=next" cargo +nightly-2026-05-28 install \
  --git https://github.com/leynos/makeutil \
  --rev 29fc5a1634ffbaa18a773eed9dff1b2838a45d9c \
  --locked --force makeutil
make test
```

## Code style and type handling

Prefer code and type signatures that the checker can prove without help. Use
`typ.cast(...)` only at boundaries where a third-party API or framework returns
values that are correct at runtime but too loose for static analysis.

Typical cases in this repository include framework constructor parameters and
validated values pulled from generic dictionaries. Keep the cast narrow and
close to the boundary instead of spreading `Any` through the rest of the code.

```python
import typing as typ

if typ.TYPE_CHECKING:
    from falcon._typing import AsyncMiddleware as FalconAsyncMiddleware

middleware: list[FalconAsyncMiddleware] = []
middleware.append(typ.cast("FalconAsyncMiddleware", build_middleware()))

raw_timeout = config_data["timeout_seconds"]
timeout_seconds = float(
    typ.cast("str | bytes | bytearray | typ.SupportsFloat", raw_timeout)
)
```

Use `typ.cast(...)` to document intent, not to silence the checker blindly. If
the value can be validated or narrowed with normal control flow, prefer that
over a cast. When a cast is necessary, add it at the smallest possible scope
and keep the surrounding code explicit about why the cast is safe.

Use `if typ.TYPE_CHECKING:` when the type checker needs a private or
heavyweight framework symbol that should never be imported at runtime. The
Falcon middleware alias is the concrete pattern in this repository: guard the
`falcon._typing.AsyncMiddleware` import, then reference it only in annotations
or stringified `typ.cast(...)` targets. Do not dereference guarded imports in
runtime expressions.

See the canonical `FalconAsyncMiddleware` example above for the exact
`middleware` and `build_middleware()` pattern.

### Logging integration

Application code should obtain loggers through `ghillie.logging`, which wraps
the underlying `femtologging` logger and preserves the repository's
percent-formatting, level normalization, and `exc_info` handling rules. Call
sites should go through that wrapper instead of importing `femtologging`
directly.

To obtain a named logger, use the helpers in `ghillie.logging`. Keep named
logger acquisition behind that wrapper so the module remains the single
translation layer for the femtologging integration boundary.

Tests that need to inspect emitted logs should use the
`capture_femto_logs(name)` context manager from
`tests.helpers.femtologging_capture`. It captures the records emitted by the
named logger without routing through `logging.getLogger`, which would bypass
the femtologging integration entirely.

### Registry sync events

`ghillie.registry.observability` owns the lines a registry sync emits, and it
is the only module that renders them. Each line starts with a bracketed event
name, then `key=value` fields on the same record, so a log query can select one
event type without parsing prose.

| Event                  | Level | Emitted                                                 |
| ---------------------- | ----- | ------------------------------------------------------- |
| `SYNC_COMPLETED`       | INFO  | once per run that returns, with the counts and duration |
| `SYNC_FAILED`          | ERROR | once per run that raises `RegistrySyncError`            |
| `SYNC_CONFLICTED`      | INFO  | per slug another estate owns                            |
| `INGESTION_TRANSITION` | INFO  | per repository whose ingestion flag the run changed     |

The completion and failure events are emitted at the public edge, so a failure
in loading the catalogue and a failure while writing Silver both produce
exactly one event, and neither path logs twice. `SYNC_FAILED` carries the
`RegistrySyncError` reason, which is already sanitized; do not extend it with
SQL, driver text, or exception detail.

Every line carries `estate_key` and `dry_run`. The terminal events carry counts
and duration rather than repository lists, so they stay one line whatever the
estate's size. The per-slug events scale with the conflicts and changes the run
actually made, not with the estate: a sync of a thousand unchanged repositories
emits one completion line, while a run that changes a hundred flags emits a
hundred transition lines. That volume is the point — it names each change — but
it is worth knowing when sizing log retention.

The per-slug events are recorded in a `SyncEventBuffer` while the run's
transaction is still open and published by
`_sync_catalogue_repositories_or_raise` only once it settles. A committed run
publishes with `dry_run=false`; a dry run publishes after its rollback with
`dry_run=true`, because its lines describe projected work the database does not
hold. A run that fails publishes nothing but `SYNC_FAILED`: the work it
recorded was rolled back, and the failure event is the whole record. Never log
a change at the point the row is written; it could be undone before the
transaction ends.

Metrics and tracing are not part of this module: the repository has no metrics
or tracing infrastructure, and issue #219 tracks that remainder.

## Estate control-plane adapters

Task 2.5.b exposes estate configuration through one application service and two
adapters. Keep new estate work inside that shape.

- **Port first.** Add a method to
  `ghillie.estate.ports.EstateManagement` (D9) and implement it in
  `ghillie.estate.service.EstateManagementService`. The HTTP resources in
  `ghillie/api/estate/resources.py` call the port and import neither
  `ghillie.catalogue` nor `ghillie.registry` directly. The CLI verbs in
  `ghillie/cli/commands/estate.py` are a separate adapter: they call the HTTP
  API, never the Python port, and may import neither the port nor those
  packages. Hecate enforces the boundaries, and O6 requires that importing
  `ghillie.cli.app` loads nothing under those packages or `sqlalchemy`.
- **One error vocabulary.** Raise the exceptions in
  `ghillie.estate.errors`; the API maps them to statuses and D7 codes, and the
  CLI maps the same codes to operator hints. Do not introduce a second error
  type per adapter.
- **msgspec at the wire.** Request and response bodies are msgspec `Struct`s in
  `ghillie/api/estate/schemas.py` (D8). Decode with
  `msgspec.json.decode(..., type=Struct)` and let `msgspec.ValidationError`
  become the documented `invalid_input` response. Add new fields to the structs
  rather than hand-building dictionaries.
- **One envelope.** Every failure uses `{"title", "description", "code"}` plus
  the optional `field`, `issues`, and `max_bytes` members (D7). The CLI's
  `ControlPlaneError` reads the same members, so a new server code reaches the
  operator without a client change.
- **Keep port package initializers docstring-only.**
  `ghillie/estate/__init__.py` re-exports nothing. Importing the service from
  it would pull `ghillie.catalogue` — and its Dramatiq broker guard — into
  every consumer of the pure models, breaking O6 for the CLI and forcing broker
  configuration on tests that only need the dataclasses. Import concrete
  modules explicitly.
- **Duplicated CLI constants are deliberate.** The CLI re-declares
  `MAX_REQUEST_BODY_BYTES` and `NEW_ESTATE_KEY_PATTERN` because O6 forbids
  importing the server-side modules. The unit tests assert equality with the
  originals, so a change on one side fails the suite until both are updated.

### Behavioural and end-to-end coverage

The estate feature file (`tests/features/estate_management.feature`) drives the
real CLI against an in-process ASGI app. The `estate_state` fixture builds the
SQLite engine, the application service, and the Falcon app, then patches
`ghillie.cli.control_plane.httpx.Client` to send through
`tests/helpers/runner_transport.RunnerTransport`. That transport runs the async
client on an `asyncio.Runner`, which bridges the synchronous CLI to the ASGI
app without a socket.

`tests/e2e/test_estate_management_e2e.py` starts the packaged runtime as a
subprocess on a free port, runs the installed console script against it over
real HTTP, and then repeats the key calls with raw `httpx` to prove the wire
contract. End-to-end tests carry the `e2e` marker and are part of `make test`;
opt out with `-m "not e2e"` when a database-backed subprocess is not wanted.

## Helm chart for local and GitOps (Git-driven operations) previews

The `charts/ghillie` Helm chart deploys Ghillie to Kubernetes clusters for both
local k3d development and GitOps ephemeral preview environments. The chart
follows the design specified in `docs/local-k8s-preview-design.md`.

### Chart structure

```text
charts/ghillie/
  Chart.yaml              # Chart metadata (version 0.1.0)
  values.yaml             # Default values with full interface
  values.schema.json      # JSON Schema for values validation
  templates/
    _helpers.tpl          # Helper functions (fullname, labels, secretName)
    deployment.yaml       # Application deployment
    service.yaml          # ClusterIP service
    ingress.yaml          # Ingress with hostless support for k3d
    serviceaccount.yaml   # Optional service account
    externalsecret.yaml   # Optional External Secrets Operator support
    configmap.yaml        # Non-sensitive environment visibility
    NOTES.txt             # Post-install instructions
```

### Installing for local k3d development

Local k3d uses hostless ingress (empty `host: ""`), relying on Traefik as the
default ingress controller in k3s. The local workflow expects a pre-created
Kubernetes Secret containing `DATABASE_URL` and `VALKEY_URL`.

```bash
# Create the application secret (example values)
kubectl create secret generic ghillie \
  --from-literal=DATABASE_URL='postgresql://user:pass@host:5432/db' \
  --from-literal=VALKEY_URL='redis://valkey:6379'

# Install with local values
helm install ghillie charts/ghillie \
  --set image.repository=ghillie \
  --set image.tag=local \
  --set secrets.existingSecretName=ghillie
```

Or use a values file:

```yaml
# values-local.yaml
image:
  repository: ghillie
  tag: local
  pullPolicy: IfNotPresent

ingress:
  enabled: true
  hosts:
    - host: ""
      paths:
        - path: /
          pathType: Prefix

secrets:
  existingSecretName: ghillie
  externalSecret:
    enabled: false
```

```bash
helm install ghillie charts/ghillie -f values-local.yaml
```

**Expected outcome:**

- Deployment creates a single pod running `ghillie:local`
- Service exposes port 8080 as ClusterIP
- Ingress routes all traffic (hostless) to the service
- Pod loads `DATABASE_URL` and `VALKEY_URL` from the `ghillie` secret
- Pod logs show the runtime entrypoint starting cleanly

Verify the installation:

```bash
kubectl get pods -l app.kubernetes.io/name=ghillie
kubectl logs -l app.kubernetes.io/name=ghillie -f
```

### Installing for GitOps ephemeral previews

GitOps environments use explicit hostnames and External Secrets Operator to
hydrate secrets from Vault or another backend. The chart creates an
ExternalSecret resource when `secrets.externalSecret.enabled` is true.

```yaml
# values-gitops.yaml
image:
  repository: ghcr.io/leynos/ghillie
  tag: sha-abc123

ingress:
  enabled: true
  hosts:
    - host: pr-123.preview.example.com
      paths:
        - path: /
          pathType: Prefix

secrets:
  externalSecret:
    enabled: true
    secretStoreRef: platform-vault
    refreshInterval: 1h
    data:
      - secretKey: DATABASE_URL
        remoteRef:
          key: ghillie/database
          property: url
      - secretKey: VALKEY_URL
        remoteRef:
          key: ghillie/valkey
          property: url
```

Deploy via FluxCD HelmRelease or directly:

```bash
helm install ghillie charts/ghillie -f values-gitops.yaml
```

**Expected outcome:**

- Deployment uses the immutable image tag (`sha-abc123`)
- ExternalSecret is created, referencing `platform-vault` ClusterSecretStore
- External Secrets Operator hydrates a Secret named after the release
- Ingress routes `pr-123.preview.example.com` to the service
- Pod starts with secrets injected from Vault

### Values interface

The chart supports the following configuration:

| Value                                    | Description                         | Default                      |
| ---------------------------------------- | ----------------------------------- | ---------------------------- |
| `image.repository`                       | Container image repository          | `ghillie`                    |
| `image.tag`                              | Container image tag                 | `local`                      |
| `image.pullPolicy`                       | Image pull policy                   | `IfNotPresent`               |
| `command`                                | Container command override          | `[]`                         |
| `args`                                   | Container arguments override        | `[]`                         |
| `replicaCount`                           | Number of replicas                  | `1`                          |
| `service.port`                           | Service port                        | `8080`                       |
| `service.type`                           | Service type                        | `ClusterIP`                  |
| `ingress.enabled`                        | Enable ingress                      | `true`                       |
| `ingress.className`                      | Ingress class name                  | `""`                         |
| `ingress.annotations`                    | Ingress annotations                 | `{}`                         |
| `ingress.hosts`                          | Ingress hosts configuration         | hostless default             |
| `ingress.tls`                            | TLS configuration                   | `[]`                         |
| `env.normal`                             | Non-sensitive environment variables | `{GHILLIE_ENV: development}` |
| `secrets.existingSecretName`             | Pre-created secret name             | `""`                         |
| `secrets.externalSecret.enabled`         | Enable ExternalSecret creation      | `false`                      |
| `secrets.externalSecret.secretStoreRef`  | ClusterSecretStore name             | `""`                         |
| `secrets.externalSecret.refreshInterval` | Secret refresh interval             | `1h`                         |
| `secrets.externalSecret.data`            | Secret data mappings                | `[]`                         |
| `resources`                              | Resource limits/requests            | `{}`                         |
| `securityContext`                        | Container security context          | `{}`                         |
| `podSecurityContext`                     | Pod security context                | `{}`                         |
| `serviceAccount.create`                  | Create service account              | `true`                       |
| `serviceAccount.name`                    | Service account name override       | `""`                         |
| `serviceAccount.annotations`             | Service account annotations         | `{}`                         |

### Command and args overrides

The chart supports entrypoint overrides for running different Ghillie modes:

```yaml
# Run as ingestion worker
command: ["python", "-m", "ghillie.worker"]
args: ["--mode", "ingestion"]

# Run as transform worker
command: ["python", "-m", "ghillie.worker"]
args: ["--mode", "transform"]
```

### Linting and testing the chart

Validate the chart structure:

```bash
make helm-lint
# Or directly:
helm lint charts/ghillie
```

**Expected output:**

```text
==> Linting charts/ghillie
[INFO] Chart.yaml: icon is recommended

1 chart(s) linted, 0 chart(s) failed
```

Run the chart test suite:

```bash
make helm-test
# Or directly:
uv run pytest tests/helm -v
```

**Expected output:**

```text
tests/helm/test_template_render.py::TestDeploymentRendering::test_deployment_uses_correct_image PASSED
tests/helm/test_template_render.py::TestDeploymentRendering::test_deployment_uses_default_image PASSED
...
tests/helm/features/steps/test_helm_steps.py::test_chart_default_rendering PASSED
tests/helm/features/steps/test_helm_steps.py::test_chart_local_config PASSED
tests/helm/features/steps/test_helm_steps.py::test_chart_gitops_config PASSED
tests/helm/features/steps/test_helm_steps.py::test_chart_lint PASSED

24 passed in 6.92s
```

### Template rendering

Preview rendered manifests without installing:

```bash
# Default values
helm template test-release charts/ghillie

# With local values
helm template test-release charts/ghillie \
  -f tests/helm/fixtures/values_local.yaml

# With GitOps values
helm template test-release charts/ghillie \
  -f tests/helm/fixtures/values_gitops.yaml
```

**Expected: valid Kubernetes YAML with no template errors.**

### Dry-run installation

Validate against a cluster without deploying:

```bash
helm template test-release charts/ghillie | kubectl apply --dry-run=client -f -
```

**Expected output:**

```text
serviceaccount/test-release-ghillie created (dry run)
configmap/test-release-ghillie-config created (dry run)
service/test-release-ghillie created (dry run)
deployment.apps/test-release-ghillie created (dry run)
ingress.networking.k8s.io/test-release-ghillie created (dry run)
```

### Troubleshooting

**Chart lint fails with schema errors:**

The `values.schema.json` enforces value constraints. When using `--set`, ensure
complete structures are provided. For complex values, use a values file instead.

**Helm tests skip:**

Tests skip automatically if `helm` is not installed. Install Helm 3.x to run
the full test suite.

**Ingress not routing traffic:**

For local k3d, ensure Traefik is running as the default ingress controller. The
hostless ingress relies on Traefik's default routing behaviour.

```bash
kubectl get pods -n kube-system -l app.kubernetes.io/name=traefik
```

**ExternalSecret not creating Secret:**

Verify the External Secrets Operator is installed and the ClusterSecretStore
exists:

```bash
kubectl get clustersecretstores
kubectl get externalsecrets
kubectl describe externalsecret <release-name>-ghillie
```

## Running tests

### Unit and behavioural tests

```bash
make test
```

Tests run in parallel using pytest-xdist. The test suite uses py-pglite for
Postgres semantics when available, falling back to SQLite otherwise.

### Database backend selection

Force SQLite for faster local iteration:

```bash
GHILLIE_TEST_DB=sqlite make test
```

Point the suite at an existing Postgres when py-pglite cannot start, for
example to run the overlapping-transaction tests in
`tests/unit/test_registry_service_sync_concurrency.py`:

```bash
GHILLIE_TEST_DB=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ghillie_test \
    uv run pytest -q tests/
```

The fixture drops and recreates the `public` schema before each test, so use a
disposable database and never a shared one. Run serially, as above: `make test`
uses `pytest -n auto`, and parallel workers would each reset the same schema
while other workers were using it. The fixture raises rather than run under
`pytest-xdist`.

### End-to-end tests only

```bash
uv run pytest tests/e2e -v
```

`tests/e2e` starts the packaged runtime as a real subprocess: it runs
`python -m ghillie.runtime` against a fresh SQLite database with
`GHILLIE_DB_BOOTSTRAP=create-all` and a configured bearer token, then drives
the estate routes over HTTP. Each test gets its own server, database, and port,
so the suite runs under `pytest-xdist` with the rest of `make test`. Deselect
it with `-m "not e2e"`.

### Helm chart tests only

```bash
make helm-test
```

### Estate end-to-end tests only

```bash
uv run pytest -v tests/e2e
```

These tests start the runtime as a subprocess, so they need a free loopback
port and a writable temporary directory. Run them without `-n auto` when
diagnosing a failure, because the subprocess output is attached to the test
report.

### Opting out of end-to-end tests

```bash
uv run pytest -m "not e2e"
```

## Documentation

- Update `docs/users-guide.md` for user-facing feature documentation
- Update `docs/developers-guide.md` for development workflow changes
- Follow the style guide in `docs/documentation-style-guide.md`
- Run `make fmt` to format Markdown after changes
