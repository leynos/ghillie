# Add estate-management APIs and command-line interface (CLI) commands

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`,
`Outcomes & Retrospective`, `Conformance basis`, and `Verification plan` must
be kept up to date as work proceeds.

Status: DRAFT

This plan implements roadmap Task 2.5.b (tracked on the branch
`2-5-2-estate-management-apis`). It must not be implemented until a human has
explicitly approved it.

## Purpose / big picture

Today an operator who wants Ghillie to watch a set of repositories has to write
Python: they construct a `CatalogueImporter`, call
`RepositoryRegistryService.sync_from_catalogue`, and call `enable_ingestion` or
`disable_ingestion` from a REPL or a script. The packaged `ghillie` CLI has the
right command names (`ghillie estate import`, `sync`, `list`, `repo list`,
`repo set`), but every one of them prints a `not_implemented` placeholder, and
the HTTP service exposes no estate endpoints at all.

After this change an operator can configure an estate end to end with no
Python. They run `ghillie estate import` to upload a catalogue file for an
estate, `ghillie estate sync` to project the catalogue's repositories into the
operational registry, `ghillie estate repo list` to see which repositories are
registered and whether ingestion is enabled, and `ghillie estate repo set` to
switch ingestion on or off for one repository. Every command calls a stable
HTTP endpoint on the Ghillie service, and the same endpoints can be driven with
`curl`. An ingestion toggle set by the operator survives later catalogue
imports and registry syncs.

Success is observable when:

1. Against a running service, the command below exits `0` and reports created
   projects, components, and repositories:

   ```bash
   ghillie --api-base-url http://127.0.0.1:8089 estate import \
     --estate-key demo --catalogue-path examples/wildside-catalogue.yaml \
     --commit-sha abc123
   ```

2. `ghillie estate sync --estate-key demo` exits `0` and reports
   `repositories_created` greater than zero.
3. `ghillie --output json estate repo list --estate-key demo` exits `0` and
   prints a JSON document whose `items` list contains `leynos/wildside` with
   `"ingestion_enabled": true`.
4. `ghillie estate repo set --owner leynos --name wildside --ingestion-disabled`
   exits `0`; a subsequent re-import with a new commit and a re-sync leaves
   `leynos/wildside` disabled.
5. Requests for an unknown estate or repository return HTTP `404` with a
   structured error body, and the CLI maps them to exit code `3` with `code`,
   `message`, and `hint` fields.
6. `make check-fmt`, `make typecheck`, `make lint`, `make test`,
   `make markdownlint`, and `make nixie` all pass.

## Constraints

- Hexagonal boundaries are enforced by Hecate (`[tool.hecate]` in
  `pyproject.toml`, run by `make check-architecture` inside `make lint`). New
  modules must be assigned to an existing group. Domain policy must be pure:
  the sync ingestion policy and the estate-key validation may import only the
  standard library and other `domain_ports` modules.
- The CLI must stay a thin HTTP client. `ghillie/cli/` must not import
  `ghillie.catalogue`, `ghillie.registry`, or SQLAlchemy. (Importing
  `ghillie.catalogue` runs a module-level Dramatiq broker guard that raises
  `RuntimeError` outside tests; see `Surprises & Discoveries`.)
- The HTTP paths are fixed by `docs/mvp-cli-specification.md` (endpoint table,
  "Estate commands" section): `GET /estates`,
  `POST /estates/{estate_key}/catalogue-import`,
  `POST /estates/{estate_key}/registry-sync`,
  `GET /estates/{estate_key}/repositories`, and
  `PATCH /repositories/{owner}/{name}/ingestion`. Do not invent verb-first
  paths.
- Existing endpoints (`/health`, `/ready`,
  `POST /reports/repositories/{owner}/{name}`) and their response bodies must
  not change.
- No new runtime or development dependencies. `msgspec`, `httpx`, `falcon`,
  `cyclopts`, `ruamel.yaml`, `hypothesis`, `syrupy`, `pytest-bdd`, and
  `py-pglite` are already declared.
- No persisted-schema change. The repository has no migration framework
  (tables are created with `create_all`), so adding a column would silently
  fail on existing databases. The toggle-preservation fix must use existing
  columns.
- Follow Red-Green-Refactor for every behavioural change, and use
  `@pytest.mark.xfail(strict=True, reason=...)` to record each red stage before
  the green step removes the marker.
- Run the quality gates sequentially, never in parallel, so the shared build
  and test caches stay effective.
- British English with Oxford spelling in all prose
  (`docs/documentation-style-guide.md`).

## Tolerances (exception triggers)

- Scope: if the change needs more than 40 files touched (tests and docs
  included) or more than 3500 net new lines, stop and escalate.
- Interface: if any existing HTTP endpoint, existing CLI verb name, or the
  `RepositoryRegistryService` public method signatures must change in a
  breaking way, stop and escalate. Adding methods or keyword-only parameters
  with defaults is allowed.
- Dependencies: if any new third-party package is needed, stop and escalate.
- Persistence: if any table, column, or constraint must change, stop and
  escalate.
- Iterations: if a gate still fails after 5 focused fix attempts, stop and
  escalate with the log path.
- Architecture: if Hecate rejects an import that the design requires and the
  only fix is a new group or a widened `allowed` list, stop and escalate.
- Ambiguity: if implementation reveals a third interpretation of the
  `--active/--inactive` or `--wait/--no-wait` options beyond those recorded in
  `Decision Log`, stop and present options.

## Risks

- Risk: registry sync currently overwrites `ingestion_enabled` from the
  catalogue on every run, so an operator's toggle is lost on the next sync.
  Severity: high. Likelihood: certain (confirmed in `ghillie/registry/sync.py`,
  `_update_silver_repository`). Mitigation: milestone EP-M1 changes the policy,
  test-first, before any endpoint exposes the toggle.
- Risk: importing `ghillie.catalogue` or `ghillie.reporting` in a process with
  no Dramatiq broker raises `RuntimeError` at import time, so the service
  started with `GHILLIE_DATABASE_URL` crashes unless
  `GHILLIE_ALLOW_STUB_BROKER=1` is set. Severity: medium. Likelihood: certain
  (reproduced with `uv run python -c "import ghillie.api.factory"`).
  Mitigation: out of scope here (Task 2.5.e owns `api-only` start-up); the
  end-to-end test sets the variable explicitly, the users' guide documents it,
  and `Outcomes & Retrospective` hands it to 2.5.e.
- Risk: the operator's catalogue file lives on their machine, not on the
  server. Severity: medium. Likelihood: certain. Mitigation: the CLI reads the
  file locally and uploads its text in a JSON body; the server never reads
  operator-supplied paths (which would also be a path-traversal hazard).
- Risk: a large upload could exhaust memory. Severity: low. Likelihood: low.
  Mitigation: a 1 MiB request-body ceiling enforced before decoding, with HTTP
  `413` and a matching CLI pre-check.
- Risk: the new endpoints are unauthenticated, as are all current endpoints;
  the CLI already sends `Authorization: Bearer <token>`, but the server ignores
  it. Severity: medium. Likelihood: certain. Mitigation: record the gap in the
  design document; server-side authentication is not part of Task 2.5.b and the
  service is deployed only to local k3d previews today.
- Risk: Skylos may report Falcon responders or Cyclopts handlers as dead code
  if they are reached only by framework dispatch. Severity: low. Likelihood:
  low (existing responders pass). Mitigation: add precise
  `[[tool.skylos.dead_code.entrypoints]]` rules with reasons if a finding
  appears.
- Risk: Hypothesis tests that touch a database are slow and may trip the
  30-second pytest timeout. Severity: low. Likelihood: medium. Mitigation: keep
  the stateful property on the pure policy; database-backed properties use a
  fresh in-memory SQLite engine per example with small `max_examples`.

## Progress

- [x] (2026-10-16) Renamed branch to `2-5-2-estate-management-apis`.
- [x] (2026-10-16) Reconnaissance of CLI, API, catalogue, registry, and docs
  with a Wyvern agent team.
- [x] (2026-10-16) Spiked Cyclopts 3.24 negative-flag naming
  (`Parameter(negative="--inactive")` and
  `Parameter(name="--ingestion-enabled", negative="--ingestion-disabled")` both
  behave as required).
- [x] (2026-10-16) Drafted this ExecPlan.
- [ ] Expert-panel design review and plan revision.
- [ ] Plan approved by a human.
- [ ] EP-M1: sync preserves operator ingestion toggles.
- [ ] EP-M2: estate application service and domain models.
- [ ] EP-M3: HTTP endpoints, error mapping, and OpenAPI.
- [ ] EP-M4: CLI commands, rendering, and error/exit-code mapping.
- [ ] EP-M5: behavioural, snapshot, and end-to-end coverage.
- [ ] EP-M6: documentation, roadmap, and final gates.

## Surprises & discoveries

- Observation: registry sync resets operator toggles.
  Evidence: `ghillie/registry/sync.py` `_update_silver_repository` includes
  `("ingestion_enabled", cat_repo.is_active)` in its field updates, and
  `tests/unit/test_registry_service_sync.py::test_sync_updates_existing_silver_repository`
  asserts the reset for an ad hoc row. Impact: EP-M1.
- Observation: importing `ghillie.api.factory` without
  `GHILLIE_ALLOW_STUB_BROKER` fails. Evidence:
  `env -u GHILLIE_ALLOW_STUB_BROKER uv run python -c "import
  ghillie.api.factory"`
  raises `RuntimeError: No Dramatiq broker configured` from
  `ghillie/catalogue/importer.py` line 689; `ghillie.reporting.actor` fails the
  same way. Impact: the runtime needs the variable whenever
  `GHILLIE_DATABASE_URL` is set; deferred to Task 2.5.e.
- Observation: the runtime also requires `GHILLIE_STATUS_MODEL_BACKEND` when
  `GHILLIE_DATABASE_URL` is set, because `build_reporting_service` calls
  `create_status_model()`. Impact: the end-to-end test sets
  `GHILLIE_STATUS_MODEL_BACKEND=mock`.
- Observation: the catalogue YAML has no `active` field; the importer never
  writes `RepositoryRecord.is_active`, so it is `True` unless changed directly
  in the database. Impact: the sync policy must still honour `False` (an
  existing test requires it) but the transition from inactive to active is not
  reachable through operator workflows.
- Observation: there are two unrelated `RepositoryNotFoundError` classes:
  `ghillie.api.errors.RepositoryNotFoundError(owner, name)` (mapped to `404`)
  and `ghillie.registry.errors.RepositoryNotFoundError(slug)` (unmapped).
  Impact: EP-M3 registers a handler for the registry one.
- Observation: `ghillie/cli/output.py` `render_output` only renders flat
  mappings; the `table` mode prints `key: value` lines. Impact: EP-M4 adds a
  collection renderer.
- Observation: `/tmp` contains a stray `bisect.py`, so any Python run with
  `/tmp` as the working directory fails to import the standard library. Impact:
  run scratch Python with `-I` and never from `/tmp`.

## Decision log

- Decision D1: catalogue import uploads the catalogue text in a JSON body.
  The request is `POST /estates/{estate_key}/catalogue-import` with
  `Content-Type: application/json` and body
  `{"commit_sha": str, "estate_name": str | null, "catalogue_yaml": str}`. The
  server parses the YAML with the existing loader logic and calls
  `CatalogueImporter.import_catalogue`. Rationale: the operator's file is local
  to the CLI; a server-side path would only work when CLI and service share a
  filesystem and would let callers make the server read arbitrary files. JSON
  keeps one envelope style for every endpoint and lets `commit_sha` and
  `estate_name` travel alongside the document. Alternatives rejected: raw
  `application/yaml` body with query parameters (two encodings to document),
  server-side path (unsafe, non-portable). Date/Author: 2026-10-16, planning
  agent.
- Decision D2: registry sync and catalogue import are synchronous
  request/response operations. `estate sync` drops its `--wait/--no-wait`
  option, and `docs/mvp-cli-specification.md` removes `estate sync` from the
  run-state contract list. Rationale: both operations are single database
  transactions that finish in well under the 30-second request timeout for
  MVP-sized estates; inventing a run resource with no status endpoint would be
  dishonest, and a persisted run table would need a schema change. Task 2.5.c
  introduces run resources for ingestion, where they are needed. Date/Author:
  2026-10-16, planning agent.
- Decision D3: sync may enable ingestion only when it adopts a repository;
  after that only the operator can re-enable it. Precisely: a new Silver row,
  or an existing row with `catalogue_repository_id IS NULL` (an ad hoc row
  being adopted), takes `ingestion_enabled = catalogue.is_active`. A row that
  is already linked keeps its current `ingestion_enabled`, except that a
  catalogue-inactive repository is forced to `False`. A linked row whose
  repository disappears from the catalogue is forced to `False` (unchanged
  behaviour). Rationale: preserves operator intent without a schema change and
  fails closed — sync can never silently restart ingestion an operator stopped.
  A repository removed from and later re-added to the catalogue therefore stays
  disabled until an operator enables it; this is documented in the users'
  guide. Alternatives rejected: an override column (needs a migration
  framework), unlinking removed rows (breaks
  `ghillie/evidence/project_service.py`, which joins on
  `catalogue_repository_id`). Date/Author: 2026-10-16, planning agent.
- Decision D4: `estate list` drops `--active/--inactive`. Estates have no
  lifecycle state (`ghillie/catalogue/storage.py` `Estate` has no active flag),
  so the filter has no meaning. `GET /estates` returns every estate with its
  key, name, description, and latest import (`commit_sha`, `imported_at`).
  Date/Author: 2026-10-16, planning agent.
- Decision D5: `estate repo list --active/--inactive` filters on
  `ingestion_enabled`; with neither flag every repository in the estate is
  listed. The CLI parameter is `active: bool | None = None` with
  `Parameter(negative="--inactive")`; the HTTP query parameter is the optional
  boolean `ingestion_enabled=true|false`. Pagination uses `limit` (1–500,
  default 50) and `offset` (≥ 0, default 0). The response carries `has_more`,
  computed by fetching `limit + 1` rows, rather than a total count.
  Date/Author: 2026-10-16, planning agent.
- Decision D6: `estate repo set` uses
  `Parameter(name="--ingestion-enabled", negative="--ingestion-disabled")` so
  the flags match the specification exactly. The HTTP body is
  `{"ingestion_enabled": bool}`, accepted as `application/json` or
  `application/merge-patch+json`; the operation is idempotent and the response
  reports whether the state `changed`. Date/Author: 2026-10-16, planning agent.
- Decision D7: new error responses extend the existing envelope additively:
  `{"title", "description", "code"[, "field"][, "issues"]}`, where `code` is a
  stable snake-case identifier (`estate_not_found`, `repository_not_found`,
  `invalid_input`, `catalogue_invalid`, `payload_too_large`,
  `registry_sync_failed`). Existing handlers are left unchanged. The CLI maps
  any non-2xx response to exit `3`, taking `code` from the body (falling back to
  `http_<status>`), `message` from `description`, and a per-code `hint` from a
  CLI-side table. Rationale: matches the specification's
  `code`/`message`/`hint` requirement without altering existing responses.
  Date/Author: 2026-10-16, planning agent.
- Decision D8: request bodies are decoded with `msgspec` structs
  (`forbid_unknown_fields=True`) defined in `ghillie/api/estate/schemas.py`.
  This is the first request-body validation in the API layer; it becomes the
  convention recorded in `docs/developers-guide.md`. Date/Author: 2026-10-16,
  planning agent.
- Decision D9: estate operations sit behind one driving port,
  `ghillie.estate.ports.EstateManagement` (a `typing.Protocol`), implemented by
  `ghillie.estate.service.EstateManagementService`, which composes the existing
  `CatalogueImporter` and `RepositoryRegistryService`. Falcon resources depend
  only on the port, so resource unit tests use an in-memory fake. Date/Author:
  2026-10-16, planning agent.
- Decision D10: Vidai Mock is not used. No inference service is involved in
  estate management, so there is nothing for it to simulate; the
  `GHILLIE_STATUS_MODEL_BACKEND=mock` setting in the end-to-end test only
  satisfies runtime start-up. Date/Author: 2026-10-16, planning agent.
- Decision D11: no new ADR. The decisions are local to the estate-management
  surface and reversible; they are recorded in `docs/ghillie-design.md` as a
  new subsection "8.5 Estate-management control plane (Task 2.5.b)". Escalate
  if review deems D3 substantive enough for ADR-005. Date/Author: 2026-10-16,
  planning agent.

## Outcomes & retrospective

Not started. On completion, record what shipped against the six success
criteria, the gate results, and the hand-off of the broker import hazard to
Task 2.5.e.

## Context and orientation

Ghillie is a Python 3.14 service. Its source lives in `ghillie/`; tests in
`tests/`; documentation in `docs/`. Run everything through `make` targets
(`Makefile`) and `uv`.

An *estate* is a named collection of projects, components, and repositories
described by a YAML *catalogue* file (example:
`examples/wildside-catalogue.yaml`; schema: `schemas/catalogue.schema.json`).
Each estate has a unique `key` (up to 64 characters) stored in the `estates`
table (`ghillie/catalogue/storage.py`, class `Estate`).

*Catalogue import* reconciles a catalogue into the catalogue tables.
`ghillie/catalogue/importer.py` class
`CatalogueImporter(session_factory, *, estate_key, estate_name)` exposes
`import_path(path, *, commit_sha)` and
`import_catalogue(catalogue, *, commit_sha)`, both returning
`CatalogueImportResult` (created/updated/deleted counters, `estate_key`,
`commit_sha`, `skipped`). A repeated `commit_sha` for the same estate returns
`skipped=True`. Validation failures raise
`ghillie.catalogue.validation.CatalogueValidationError`, which carries
`issues: list[str]`. `ghillie/catalogue/loader.py` `load_catalogue(path)`
parses YAML 1.2 with `ruamel.yaml` and converts it with `msgspec`.

The *registry* is the Silver-layer `repositories` table
(`ghillie/silver/storage.py`, class `Repository`), which ingestion and
reporting consult. Each row has `github_owner`, `github_name`, `default_branch`,
`estate_id` (the estate's UUID, not its key), `catalogue_repository_id`,
`ingestion_enabled`, and `documentation_paths`. *Registry sync*
(`ghillie/registry/sync.py`, reached through `ghillie/registry/service.py`
`RepositoryRegistryService.sync_from_catalogue (estate_key) -> SyncResult`)
projects catalogue repositories into this table. The service also provides
`list_active_repositories`, `list_all_repositories` (both keyed by estate UUID,
with `limit`/`offset`), `enable_ingestion(owner, name) -> bool`, and
`disable_ingestion(owner, name) -> bool` (raising
`ghillie.registry.errors.RepositoryNotFoundError`). The lower-level
`ghillie/registry/listing.py` `RepositoryListOptions` already supports an
`ingestion_enabled: bool | None` filter.

The *HTTP API* is a Falcon ASGI app built by `ghillie/api/app.py`
`create_app(dependencies: AppDependencies | None)`. `AppDependencies` currently
holds `session_factory` and `reporting_service`; domain routes are registered
only when both are present. Errors are domain exceptions mapped by handlers in
`ghillie/api/errors.py` to `{"title", "description"[, "field"]}` bodies.
`ghillie/api/factory.py` builds services; `ghillie/runtime.py` is the Granian
entry point (`python -m ghillie.runtime`, configured by `GHILLIE_HOST`,
`GHILLIE_PORT`, `GHILLIE_DATABASE_URL`). The OpenAPI document is
`specs/openapi.yml` (maintained by hand).

The *CLI* is a Cyclopts app in `ghillie/cli/` (console script `ghillie`).
`ghillie/cli/app.py` `main(argv) -> int` pre-parses root options
(`--api-base-url`, `--auth-token`, `--output`, `--request-timeout-s`, and
others) into `ResolvedCliConfig` (`ghillie/cli/config.py`) and stores it in a
context variable (`ghillie/cli/context.py` `get_current_context()`). A command
returns a `str` (printed, exit `0`) or an `int` (exit code).
`ghillie/cli/control_plane.py`
`ControlPlaneClient(config, *, http_client=None)` wraps `httpx.Client` with
base URL, timeout, and bearer token. `ghillie/cli/output.py`
`render_output(payload, *, output)` renders a flat mapping as `json`, `yaml`, or
`table`. The estate verbs live in `ghillie/cli/commands/estate.py` and
currently call `_api_placeholder`.

*Hecate* enforces import rules between module groups (`composition_root`,
`domain_ports`, `application`, `inbound_adapter`, `outbound_adapter`,
`package_facade`) with first-match prefix semantics. *Skylos* blocks dead code
in `ghillie/`.

Tests: `tests/conftest.py` provides `session_factory` (py-pglite PostgreSQL,
falling back to SQLite when `GHILLIE_TEST_DB=sqlite`). `tests/unit/conftest.py`
provides `registry_service`, `create_repo`, `fetch_repo`, and
`wildside_catalogue_path`. Behaviour-driven development (BDD) features live in
`tests/features/*.feature` with steps in `tests/features/steps/`. API unit
tests use `falcon.testing.TestClient` (see
`tests/unit/test_api_report_resource.py`); CLI unit tests inject
`httpx.MockTransport` through `ControlPlaneClient(http_client=...)` (see
`tests/unit/cli/test_control_plane_client.py`). There is no end-to-end test
directory yet.

Documents and skills to keep open while implementing:

- `AGENTS.md` and the `.rules/python-*.md` guides (style, typing, errors).
- `docs/mvp-cli-specification.md` (the CLI and endpoint contract).
- `docs/ghillie-design.md` §3.0 (CLI boundary) and §8.4 (HTTP API layer).
- `docs/ghillie-bronze-silver-architecture-design.md` §9.1 and §9.2
  (catalogue importer and registry sync).
- `docs/async-sqlalchemy-with-pg-and-falcon.md` (session handling, error
  mapping).
- `docs/testing-async-falcon-endpoints.md` (endpoint test patterns).
- `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md` (database fixtures).
- `docs/developers-guide.md` sections "Architecture checks (Hecate)" and
  "Dead-code detection (Skylos)".
- Skills: `execplans`, `hexagonal-architecture`, `python-router` (then
  `python-types-and-apis`, `python-data-shapes`, `python-errors-and-logging`,
  `python-testing`, `hypothesis`), `skylos`, `en-gb-oxendict-style`.

## Conformance basis

Upstream artefacts at the plan's base commit `2ffdb4d`:

- `docs/roadmap.md` Task 2.5.b (identifiers below are assigned by this plan):
  - `RM-2.5.b-IMPORT`: catalogue import per estate.
  - `RM-2.5.b-SYNC`: registry sync from catalogue.
  - `RM-2.5.b-LIST`: repository listing.
  - `RM-2.5.b-TOGGLE`: ingestion enable/disable toggles.
  - `RM-2.5.b-DONE`: an operator configures estate repositories end to end via
    CLI and HTTP APIs with no direct Python scripting.
- `docs/mvp-cli-specification.md` "Estate commands" and the endpoint mapping
  table (`SPEC-EST-CMDS`, `SPEC-EST-PATHS`), "Error handling and exit codes"
  (`SPEC-EXIT`), "Security constraints" (`SPEC-SEC`).
- `docs/ghillie-design.md` §3.0 (`TDD-CLI-THIN`: the CLI is a thin HTTP
  client) and §8.4 (`TDD-API-LAYER`: resources map domain exceptions to HTTP
  through registered handlers).
- `docs/ghillie-bronze-silver-architecture-design.md` §9.2 (`TDD-REG-SYNC`:
  catalogue repositories default to ingestion enabled; removed repositories are
  disabled).
- ADR-003 (Hecate architecture checks).
- No Terms of Reference document exists for this project.

Trace links:

```plaintext
RM-2.5.b-TOGGLE -> TDD-REG-SYNC (amended by D3) -> EP-M1
                -> tests/unit/test_registry_sync_policy.py
                -> tests/unit/test_registry_service_sync.py::test_sync_preserves_operator_disable
RM-2.5.b-IMPORT -> SPEC-EST-PATHS -> EP-M2, EP-M3, EP-M4
                -> tests/unit/test_api_estate_resources.py::TestCatalogueImport*
                -> tests/features/estate_management.feature "Operator imports a catalogue for a new estate"
RM-2.5.b-SYNC   -> SPEC-EST-PATHS (amended by D2) -> EP-M2, EP-M3, EP-M4
                -> tests/features/estate_management.feature "Operator syncs the registry and lists repositories"
RM-2.5.b-LIST   -> SPEC-EST-CMDS (D4, D5) -> EP-M2, EP-M3, EP-M4
                -> tests/unit/test_estate_service.py::test_list_repositories_pages_cover_all_rows
RM-2.5.b-TOGGLE -> SPEC-EST-CMDS (D6) -> EP-M3, EP-M4
                -> tests/features/estate_management.feature "Operator disables ingestion and it survives a re-sync"
SPEC-EXIT       -> D7 -> EP-M4 -> tests/unit/cli/test_estate_commands.py::test_http_errors_exit_3
RM-2.5.b-DONE   -> EP-M5 -> tests/e2e/test_estate_management_e2e.py
TDD-CLI-THIN    -> Constraint (no catalogue imports in CLI) -> EP-M4 -> make check-architecture
```

The amendments D2, D3, and D4 change upstream documents
(`docs/mvp-cli-specification.md` and
`docs/ghillie-bronze-silver-architecture-design.md` §9.2); EP-M6 updates them.
Approval of this plan constitutes acceptance of those amendments.

## Verification plan

The change introduces four non-trivial obligations.

Axioms relied upon (not verified here): Falcon routes requests to responders by
URI template and decodes path parameters; SQLAlchemy
`ORDER BY … LIMIT … OFFSET` is deterministic for a total order (owner, name are
unique together, enforced by `uq_repositories_owner_name`); `msgspec` rejects
unknown fields when `forbid_unknown_fields=True`; Cyclopts maps
`Parameter(negative=...)` as observed in the spike recorded in `Progress`;
`httpx.MockTransport` faithfully presents responses to `httpx.Client`.

Obligation O1, toggle monotonicity under sync. For a repository already linked
to the estate's catalogue, a sync never changes `ingestion_enabled` from
`False` to `True`; if the repository is present and active in the catalogue,
sync leaves `ingestion_enabled` unchanged; if it is absent or inactive, sync
sets it to `False`. For a new or unlinked row, sync sets it to
`catalogue.is_active`.

- Method: stateful property test plus named database examples.
- Rationale: the bug is order-dependent (toggle, then import, then sync), so a
  generated operation sequence is the proportionate adversary; database
  examples prove the ORM application of the pure decision.
- Domain: Hypothesis `RuleBasedStateMachine` over a universe of 4 repository
  slugs, with rules `import_catalogue(subset, inactive_subset)`, `sync()`,
  `operator_toggle(slug, enabled)`, and `create_ad_hoc(slug)`; at most 30 steps.
- Artefact: `tests/unit/test_registry_sync_policy.py` drives the pure planner
  `ghillie.registry.policy.decide_ingestion` through a model; named examples in
  `tests/unit/test_registry_service_sync.py`.
- Evidence: run `uv run pytest -v` on both artefact files; before EP-M1 the new
  `test_sync_preserves_operator_disable` fails (asserts `False`, gets `True`).
- Non-vacuity: use `hypothesis.event()` to record each transition class
  (adopt, preserve, force-disable-removed, force-disable-inactive) and assert
  in a final `@invariant` run summary that every class occurred at least once
  over the run via `note`; the seeded mutation "restore
  `ingestion_enabled = cat_repo.is_active` for linked rows" must make the
  property fail with a counterexample of the form toggle-off, sync.

Obligation O2, pagination completeness. For any estate with `N` registered
repositories and any `limit` in 1..10, walking pages from `offset=0` while
`has_more` is true yields every repository exactly once, in `(owner, name)`
order, and the final page has `has_more == False`.

- Method: property test against a real SQLite engine.
- Rationale: the `limit + 1` look-ahead is repository-owned logic layered on
  SQL; an off-by-one is a classic defect only visible across ranges of `N` and
  `limit`.
- Domain: `N` in 0..25 (including 0 and multiples of `limit`), `limit` in
  1..10, an optional `ingestion_enabled` filter; `max_examples=40`; a fresh
  in-memory engine per example.
- Artefact:
  `tests/unit/test_estate_service.py::test_list_repositories_pages_cover_all_rows`.
- Evidence: the test passes; it is written before
  `EstateManagementService.list_repositories` exists and fails with
  `AttributeError` first.
- Non-vacuity: `hypothesis.target(N)` and assertions that examples with
  `N == 0`, `N % limit == 0`, and `N % limit != 0` all occur (checked via
  `event()` statistics in `-s --hypothesis-show-statistics` output recorded in
  `Artefacts and notes`); the seeded mutation "fetch `limit` instead of
  `limit + 1`" must fail.

Obligation O3, estate-key validation. `validate_estate_key(key)` accepts
exactly the strings matching `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`, and every
accepted key survives the CLI's path quoting and Falcon's path decoding
unchanged.

- Method: parameterized boundary examples plus a property test.
- Domain: Hypothesis `from_regex` for valid keys, `text()` for arbitrary
  strings; boundary rows for length 0, 1, 64, 65, leading `-`, `/`, `%2F`,
  whitespace, and non-ASCII.
- Artefact: `tests/unit/test_estate_models.py`; the round trip runs through
  `falcon.testing.TestClient` against a fake port in
  `tests/unit/test_api_estate_resources.py::test_estate_key_round_trips`.
- Non-vacuity: both accepted and rejected classes must be generated (assert
  via `event()`); the mutation "drop the length bound" must be rejected by the
  65-character boundary row.

Obligation O4, error-contract totality. Every documented failure of every new
endpoint produces its documented status and `code`, and the CLI maps every
non-2xx status to exit `3` with non-empty `code`, `message`, and `hint`.

- Method: parameterized tests (finite partition).
- Domain: the table in `Interfaces and dependencies` ("Error contract"), one
  row per endpoint and failure; plus transport failure (`httpx.ConnectError`)
  and a non-JSON error body.
- Artefact: `tests/unit/test_api_estate_errors.py`,
  `tests/unit/cli/test_estate_commands.py::test_http_errors_exit_3`.
- Non-vacuity: each row asserts the exact status and code; the mutation "map
  `EstateNotFoundError` to 500" must fail its row.

Residual gaps: concurrency between simultaneous syncs and toggles is not
verified (both run in single transactions; last writer wins, which is
acceptable for MVP and documented). OpenAPI conformance is checked by a
structural test only (paths, methods, operation IDs, schema names); full schema
validation is Task 2.6.c.

## Plan of work

Stage A (no code): this plan, the expert review, and approval.

Stage B onwards proceeds milestone by milestone. Each milestone starts with a
red test committed with a strict `xfail` marker, then the green change removes
the marker, then refactoring. Commit after each green step and after each
refactor, gating every commit.

### EP-M1: sync preserves operator ingestion toggles

Modify existing behaviour test-first. In
`tests/unit/test_registry_service_sync.py` add
`test_sync_preserves_operator_disable` (import, sync, disable
`leynos/wildside`, import a second commit, sync, assert still disabled) and
`test_sync_does_not_reenable_removed_then_readded_repository`. Keep
`test_sync_updates_existing_silver_repository` (ad hoc adoption still enables)
and `test_sync_disables_ingestion_for_inactive_catalogue_repository` unchanged;
they must still pass. Add `tests/unit/test_registry_sync_policy.py` with the O1
state machine.

Create `ghillie/registry/policy.py` containing pure code only: a frozen
dataclass `SilverIngestionState(is_linked: bool, ingestion_enabled: bool)`, an
enum `IngestionTransition` (`ADOPT`, `PRESERVE`, `DISABLE_INACTIVE`,
`DISABLE_REMOVED`), and
`decide_ingestion(current: SilverIngestionState | None,
*, in_catalogue: bool, catalogue_active: bool) -> tuple[bool,
IngestionTransition]`.
In `ghillie/registry/sync.py`, remove `ingestion_enabled` from
`_update_silver_repository`'s field table and apply `decide_ingestion` in
`_sync_one_repository`, `_create_silver_repository`, and
`_deactivate_removed_repositories`. Update the module docstring.

Hecate: `ghillie.registry.policy` falls under the generic `ghillie.registry`
application prefix, which is acceptable; the purity constraint is enforced by
review and by the module importing only `dataclasses` and `enum`.

### EP-M2: estate application service and domain models

Create the package `ghillie/estate/`:

- `ghillie/estate/models.py` (add prefix `ghillie.estate.models` to the
  `domain_ports` group): frozen, slotted dataclasses `EstateSummary`,
  `CatalogueImportSummary`, `RegistrySyncSummary`, `RepositorySummary`,
  `RepositoryPage`, `IngestionToggleOutcome`, `RepositoryQuery`; the constants
  `MAX_ESTATE_KEY_LENGTH = 64`, `MAX_PAGE_LIMIT = 500`,
  `DEFAULT_PAGE_LIMIT = 50`, `MAX_CATALOGUE_BYTES = 1_048_576`; and the pure
  function `validate_estate_key(key: str) -> str`.
- `ghillie/estate/errors.py` (falls under a new `ghillie.estate` application
  prefix placed after the leaf entries): `EstateError` base,
  `EstateNotFoundError(estate_key)`, `InvalidEstateKeyError(key)`,
  `InvalidPaginationError(field, reason)`.
- `ghillie/estate/ports.py` (add `ghillie.estate.ports` to `domain_ports`):
  `class EstateManagement(typ.Protocol)` with the async methods listed in
  `Interfaces and dependencies`.
- `ghillie/estate/service.py` (application): `EstateManagementService`.
  `import_catalogue` parses YAML text (via a new `ghillie/catalogue/loader.py`
  `parse_catalogue_text(text: str) -> Catalogue`, which `load_catalogue` then
  delegates to), constructs a `CatalogueImporter` for the estate, and maps the
  result. `sync_registry` resolves the estate first (raising
  `EstateNotFoundError`) and maps `SyncResult`. `list_estates` queries `Estate`
  with the latest `CatalogueImportRecord`. `list_repositories` resolves the key
  to the estate UUID and calls `ghillie.registry.listing.list_repositories` with
  `limit + 1`. `set_ingestion` calls `enable_ingestion` or `disable_ingestion`
  and re-reads the row.
- Register `ghillie.estate` in `[tool.hecate]` and confirm with
  `make check-architecture`.

Tests first: `tests/unit/test_estate_models.py` (O3),
`tests/unit/test_loader_parse_text.py` (empty text, invalid YAML, duplicate
keys, schema failure, happy path), and `tests/unit/test_estate_service.py`
(each method's happy and unhappy paths against `session_factory`, plus O2).

### EP-M3: HTTP endpoints, error mapping, and OpenAPI

Create `ghillie/api/estate/__init__.py`, `ghillie/api/estate/schemas.py`
(msgspec request structs and response serializers), and
`ghillie/api/estate/resources.py` with five resources:
`EstateCollectionResource.on_get`, `CatalogueImportResource.on_post`,
`RegistrySyncResource.on_post`, `EstateRepositoryCollectionResource.on_get`, and
`RepositoryIngestionResource.on_patch`. The import resource reads at most
`MAX_CATALOGUE_BYTES + 1` bytes from `req.stream` and raises
`PayloadTooLargeError` before decoding when exceeded.

In `ghillie/api/errors.py` add handlers for `EstateNotFoundError` (404),
`InvalidEstateKeyError` and `InvalidPaginationError` and a new
`RequestBodyError` (400, `invalid_input`), `CatalogueValidationError` (422,
`catalogue_invalid`, with `issues`), `PayloadTooLargeError` (413),
`ghillie.registry.errors.RepositoryNotFoundError` (404,
`repository_not_found`), and `RegistrySyncError` (500, `registry_sync_failed`,
description without internal detail; log the cause).

In `ghillie/api/app.py` add `estate_service: EstateManagement | None = None` to
`AppDependencies`; register the session middleware when `session_factory` and
at least one domain service are present; register reporting routes when
`reporting_service` is present and estate routes when `estate_service` is
present. Update `_has_domain_deps` accordingly and keep the docstrings exact. In
`ghillie/api/factory.py` add
`build_estate_service(session_factory) -> EstateManagementService`; in
`ghillie/runtime.py` wire it into `AppDependencies`.

Update `specs/openapi.yml` with the five operations (operation IDs
`listEstates`, `importCatalogue`, `syncRegistry`, `listEstateRepositories`,
`setRepositoryIngestion`), request and response schemas, and an `ErrorResponse`
extended with optional `code` and `issues`.

Tests first: `tests/unit/test_api_estate_resources.py` (Falcon `TestClient`
with a fake `EstateManagement`; every happy path, status code, body shape, and
O3 round trip), `tests/unit/test_api_estate_errors.py` (O4 server half),
`tests/unit/test_api_app.py` additions (estate routes present only when the
estate service is supplied; reporting routes unaffected), and
`tests/unit/test_openapi_estate_paths.py` (structural check).

### EP-M4: CLI commands, rendering, and error mapping

In `ghillie/cli/control_plane.py` add `ControlPlaneError` (base, with `code`,
`message`, `hint`, `status`), `ControlPlaneHTTPError`, and
`ControlPlaneTransportError`, plus a method
`request_json(method: str, path: str, *, params=None, json_body=None) ->
dict[str, object]`
that raises them. Path segments are quoted with
`urllib.parse.quote(segment, safe="")`.

In `ghillie/cli/output.py` add
`render_collection(items, *, columns, output, meta=None) -> str` (aligned
plain-text table for `table`; full document for `json` and `yaml`) and
`render_error(error, *, output) -> str`.

Rewrite `ghillie/cli/commands/estate.py`: delete `_api_placeholder`; each verb
builds the request, calls `request_json` inside `ControlPlaneClient`, renders
the result, and returns the string; on `ControlPlaneError` it writes
`render_error` to standard error and returns `3`. `estate import` reads the
file with `Path.read_text(encoding="utf-8")`, returns `2` with code
`catalogue_file_unreadable` if unreadable, and `2` with
`catalogue_file_too_large` if the encoded text exceeds the limit (the CLI
duplicates the 1 MiB constant rather than importing `ghillie.estate`, keeping
the CLI dependency-free; a unit test asserts the two values are equal). Remove
`wait` from `sync` (D2) and `active`/`inactive` from `estate list` (D4); change
`repo list` to `active: bool | None` (D5) and `repo set` flags (D6). Keep
`ingest.py`'s placeholder untouched.

Tests first: `tests/unit/cli/test_estate_commands.py` (each verb's request
method, path, query, and body via `httpx.MockTransport`; success output; O4
client half), `tests/unit/cli/test_output.py` additions, and
`tests/unit/cli/test_estate_output_snapshots.py` (syrupy snapshots of each
verb's output in `table`, `json`, and `yaml`). Update
`tests/unit/cli/test_app.py` only if the verb sets change (they do not).

### EP-M5: behavioural, snapshot, and end-to-end coverage

Add `tests/features/estate_management.feature` and
`tests/features/steps/test_estate_management_steps.py`. The steps run the real
CLI (`ghillie.cli.main`) against the real Falcon app and real database
in-process, through a test helper `tests/helpers/falcon_transport.py` class
`FalconTestTransport(httpx.BaseTransport)` that forwards each request to
`falcon.testing.TestClient.simulate_request`.

```gherkin
Feature: Estate management through the operator CLI and HTTP API

  Background:
    Given a Ghillie service backed by an empty database

  Scenario: Operator imports a catalogue for a new estate
    When the operator imports "examples/wildside-catalogue.yaml" into estate "demo" at commit "c1"
    Then the command exits with code 0
    And the output reports at least 1 repository created
    And the estate "demo" is listed by "estate list"

  Scenario: Re-importing the same commit is skipped
    Given the operator has imported "examples/wildside-catalogue.yaml" into estate "demo" at commit "c1"
    When the operator imports "examples/wildside-catalogue.yaml" into estate "demo" at commit "c1" with JSON output
    Then the command exits with code 0
    And the JSON output field "skipped" is true

  Scenario: Operator syncs the registry and lists repositories
    Given the operator has imported "examples/wildside-catalogue.yaml" into estate "demo" at commit "c1"
    When the operator runs "estate sync --estate-key demo"
    Then the command exits with code 0
    And "estate repo list --estate-key demo --active" lists "leynos/wildside"

  Scenario: Operator disables ingestion and it survives a re-sync
    Given estate "demo" has been imported at commit "c1" and synced
    When the operator runs "estate repo set --owner leynos --name wildside --ingestion-disabled"
    And the operator imports estate "demo" at commit "c2" and syncs it
    Then "estate repo list --estate-key demo --inactive" lists "leynos/wildside"

  Scenario: Syncing an unknown estate fails with a structured error
    When the operator runs "--output json estate sync --estate-key missing"
    Then the command exits with code 3
    And the error code is "estate_not_found"
    And the error hint mentions "estate list"

  Scenario: Importing an invalid catalogue is rejected
    Given a catalogue file containing "projects: 42"
    When the operator imports that file into estate "demo" at commit "bad"
    Then the command exits with code 3
    And the error code is "catalogue_invalid"

  Scenario: Toggling an unknown repository fails
    When the operator runs "estate repo set --owner nobody --name nothing --ingestion-enabled"
    Then the command exits with code 3
    And the error code is "repository_not_found"

  Scenario: Invalid pagination is rejected before any request
    When the operator runs "estate repo list --estate-key demo --limit 0"
    Then the command exits with code 2
```

Add `tests/e2e/__init__.py`, `tests/e2e/conftest.py`, and
`tests/e2e/test_estate_management_e2e.py`. The fixture creates a SQLite file
database under pytest's `tmp_path`, initializes all storage, picks a free port,
and starts `python -m ghillie.runtime` as a subprocess with
`GHILLIE_HOST=127.0.0.1`, `GHILLIE_PORT`, `GHILLIE_DATABASE_URL`,
`GHILLIE_ALLOW_STUB_BROKER=1`, and `GHILLIE_STATUS_MODEL_BACKEND=mock`; it polls
`/ready` for up to 20 seconds and terminates the process on teardown. The test
runs the `ghillie` console script as subprocesses through the full journey
(import, list estates, sync, list, disable, re-import c2, re-sync, list
inactive) and also issues one raw `httpx` request per endpoint to check the
wire contract independently of the CLI. Register an `e2e` marker in
`pyproject.toml` and give the module `pytest.mark.timeout(120)`.

### EP-M6: documentation, roadmap, and final gates

- `docs/users-guide.md`: replace the "Operator CLI scaffold" placeholder
  wording; add an "Estate management through the CLI and API" section with each
  command, endpoint, request and response example, error codes, the
  toggle-preservation rule (including the re-added repository case), and the
  `GHILLIE_ALLOW_STUB_BROKER` and `GHILLIE_STATUS_MODEL_BACKEND` start-up
  requirements; retitle the Python-snippet sections as programmatic
  alternatives.
- `docs/mvp-cli-specification.md`: apply D2, D4, D5, D6; add request and
  response shapes and the error-code table; replace the 2.5.a placeholder note
  for estate verbs.
- `docs/ghillie-design.md`: add §8.5 "Estate-management control plane
  (Task 2.5.b)" recording D1–D9 and the authentication gap; update §3.0 to say
  estate verbs are live.
- `docs/ghillie-bronze-silver-architecture-design.md` §9.2: record D3.
- `docs/developers-guide.md`: request-body decoding with msgspec (D8), the
  error-envelope `code` convention (D7), the `FalconTestTransport` helper, and
  how to run the `e2e` tests.
- `docs/mvp-gap-analysis.md`: mark the estate-configuration gap closed.
- `docs/roadmap.md`: mark Task 2.5.b done with an "Implemented" note.
- Run `make fmt`, then every gate.

## Milestones and plateaus

- EP-M1. Outcome: syncs preserve operator toggles; no API change.
  Requirements: `RM-2.5.b-TOGGLE` (durability), `TDD-REG-SYNC` amended.
  Acceptance: O1 property and the two new named tests pass. Conformance: no
  interface or schema change; Hecate passes. Recovery: revert the policy
  commit; the old tests are intact. Remaining gaps: no endpoints yet.
  Compatibility decision: none.
- EP-M2. Outcome: `EstateManagementService` usable from Python with full
  tests. Requirements: `RM-2.5.b-IMPORT`, `-SYNC`, `-LIST`, `-TOGGLE` at the
  application layer. Acceptance: `tests/unit/test_estate_service.py`,
  `test_estate_models.py`, and `test_loader_parse_text.py` pass; O2 and O3
  discharged. Conformance: new Hecate prefixes approved by the plan; no new
  dependency. Recovery: the package is additive; delete it to roll back.
  Remaining gaps: no HTTP or CLI exposure. Compatibility decision: none.
- EP-M3. Outcome: the five endpoints work with documented errors and are in
  `specs/openapi.yml`. Requirements: `SPEC-EST-PATHS`, `TDD-API-LAYER`.
  Acceptance: API unit and error tests pass; O4 server half discharged; `curl`
  against a locally started service returns the documented shapes. Conformance:
  existing endpoints byte-for-byte unchanged (existing tests untouched and
  passing). Recovery: routes are registered only when `estate_service` is
  supplied. Remaining gaps: CLI still placeholder. Compatibility decision: none.
- EP-M4. Outcome: all estate verbs call the API. Requirements:
  `SPEC-EST-CMDS` (amended), `SPEC-EXIT`, `TDD-CLI-THIN`. Acceptance: CLI unit
  and snapshot tests pass; O4 client half discharged. Conformance: CLI imports
  nothing from `ghillie.catalogue`, `ghillie.registry`, or `ghillie.estate`
  (checked with `rg` in the milestone and by Hecate ordering). Recovery: revert
  the CLI commit. Remaining gaps: no in-process or process-level journey test.
  Compatibility decision: none — the CLI options change is pre-1.0 and the
  verbs were placeholders.
- EP-M5. Outcome: the operator journey is proven in-process (BDD) and across
  real processes (e2e). Requirements: `RM-2.5.b-DONE`. Acceptance: the eight
  scenarios and the e2e test pass under `make test`. Recovery: tests only.
  Compatibility decision: none.
- EP-M6. Outcome: documentation and roadmap match behaviour; all gates pass.
  Requirements: AGENTS.md documentation rules. Acceptance: gates and
  `make markdownlint`, `make nixie` pass. Compatibility decision: none.

## Concrete steps

Run every command from the repository root. Never run gates in parallel. Log
each gate with `tee`, for example:

```bash
set -o pipefail
BRANCH=$(git branch --show-current)
make check-fmt 2>&1 | tee "/tmp/check-fmt-ghillie-${BRANCH}.out"
make typecheck 2>&1 | tee "/tmp/typecheck-ghillie-${BRANCH}.out"
make lint 2>&1 | tee "/tmp/lint-ghillie-${BRANCH}.out"
make test 2>&1 | tee "/tmp/test-ghillie-${BRANCH}.out"
make markdownlint 2>&1 | tee "/tmp/markdownlint-ghillie-${BRANCH}.out"
make nixie 2>&1 | tee "/tmp/nixie-ghillie-${BRANCH}.out"
```

Focused red and green loops, for example in EP-M1:

```bash
uv run pytest tests/unit/test_registry_service_sync.py -v -k preserves 2>&1 | tail -5
```

Expected red output before the fix (with the strict `xfail` marker removed to
see the reason):

```plaintext
FAILED tests/unit/test_registry_service_sync.py::test_sync_preserves_operator_disable - assert True is False
```

Manual check after EP-M3 (from the repository root, in two terminals):

```bash
export GHILLIE_DATABASE_URL="sqlite+aiosqlite:///$PWD/.scratch-estate.db"
export GHILLIE_ALLOW_STUB_BROKER=1 GHILLIE_STATUS_MODEL_BACKEND=mock
uv run python -m tests.helpers.init_db "$GHILLIE_DATABASE_URL"
GHILLIE_HOST=127.0.0.1 GHILLIE_PORT=8089 uv run python -m ghillie.runtime
curl -s http://127.0.0.1:8089/estates
```

Expected:

```plaintext
{"items": []}
```

`tests/helpers/init_db.py` is a small test helper added in EP-M3 that runs the
four `init_*_storage` functions against the given URL; the end-to-end fixture
in EP-M5 reuses it.

## Validation and acceptance

Quality criteria:

- Tests: `make test` passes, including all new unit, property, snapshot, BDD,
  and e2e tests; the red stage of every new behavioural test was observed and
  recorded in `Artefacts and notes`.
- Verification: O1–O4 discharged with the non-vacuity evidence described in
  `Verification plan`.
- Lint and typecheck: `make check-fmt`, `make typecheck`, `make lint`
  (Hecate, Ruff, Skylos) pass with no new suppressions beyond reasoned `noqa`
  comments of the kind already used for `PLR0913` on wide CLI commands.
- Documentation: `make markdownlint` and `make nixie` pass.
- Security: no secret or bearer token appears in CLI output or logs (asserted
  by a unit test that sets `--auth-token` and inspects output and captured
  logs).

The end-to-end acceptance transcript, captured in `Artefacts and notes`, must
show the journey from success criteria 1–4.

## Idempotence and recovery

All steps are re-runnable. Imports with a repeated `commit_sha` are skipped by
design; syncs are idempotent; toggles report `changed: false` when repeated.
The e2e fixture uses `tmp_path`, so no state leaks between runs. If the e2e
server fails to start, its captured standard error is attached to the test
failure. Each milestone is one or more commits; roll back with `git revert`.

## Artefacts and notes

Record here, as work proceeds: red-stage failure lines, Hypothesis statistics
for O1–O3, the seeded-mutation results, and the e2e transcript.

## Interfaces and dependencies

No new dependencies. New and changed interfaces:

```python
# ghillie/estate/ports.py
class EstateManagement(typ.Protocol):
    async def list_estates(self) -> tuple[EstateSummary, ...]: ...
    async def import_catalogue(
        self, estate_key: str, *, catalogue_yaml: str, commit_sha: str,
        estate_name: str | None,
    ) -> CatalogueImportSummary: ...
    async def sync_registry(self, estate_key: str) -> RegistrySyncSummary: ...
    async def list_repositories(
        self, estate_key: str, query: RepositoryQuery
    ) -> RepositoryPage: ...
    async def set_ingestion(
        self, owner: str, name: str, *, enabled: bool
    ) -> IngestionToggleOutcome: ...

# ghillie/registry/policy.py
def decide_ingestion(
    current: SilverIngestionState | None, *, in_catalogue: bool,
    catalogue_active: bool,
) -> tuple[bool, IngestionTransition]: ...

# ghillie/catalogue/loader.py
def parse_catalogue_text(text: str) -> Catalogue: ...

# ghillie/cli/control_plane.py
class ControlPlaneClient:
    def request_json(
        self, method: str, path: str, *,
        params: cabc.Mapping[str, str] | None = None,
        json_body: cabc.Mapping[str, object] | None = None,
    ) -> dict[str, object]: ...
```

Endpoint contract:

| Method and path                                | Request                                            | Success                                                                                                                                                                |
| ---------------------------------------------- | -------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /estates`                                 | none                                               | `200 {"items": [{"key", "name", "description", "last_import": {"commit_sha", "imported_at"} \| null}]}`                                                                |
| `POST /estates/{estate_key}/catalogue-import`  | `{"commit_sha", "estate_name"?, "catalogue_yaml"}` | `200 {"estate_key", "commit_sha", "skipped", "projects": {...}, "components": {...}, "repositories": {...}, "edges": {...}}` with `created`/`updated`/`deleted` counts |
| `POST /estates/{estate_key}/registry-sync`     | none                                               | `200 {"estate_key", "repositories_created", "repositories_updated", "repositories_deactivated"}`                                                                       |
| `GET /estates/{estate_key}/repositories`       | query `ingestion_enabled?`, `limit?`, `offset?`    | `200 {"estate_key", "items": [{"owner", "name", "default_branch", "ingestion_enabled", "documentation_paths"}], "limit", "offset", "has_more"}`                        |
| `PATCH /repositories/{owner}/{name}/ingestion` | `{"ingestion_enabled": bool}`                      | `200 {"owner", "name", "ingestion_enabled", "changed"}`                                                                                                                |

Error contract:

| Endpoint              | Failure                                 | Status | `code`                 |
| --------------------- | --------------------------------------- | ------ | ---------------------- |
| any estate path       | key fails `validate_estate_key`         | 400    | `invalid_input`        |
| import                | body not JSON, unknown or missing field | 400    | `invalid_input`        |
| import                | body over 1 MiB                         | 413    | `payload_too_large`    |
| import                | YAML or schema invalid                  | 422    | `catalogue_invalid`    |
| sync, repository list | estate unknown                          | 404    | `estate_not_found`     |
| sync                  | database failure                        | 500    | `registry_sync_failed` |
| repository list       | bad `limit`, `offset`, or boolean       | 400    | `invalid_input`        |
| ingestion toggle      | repository unknown                      | 404    | `repository_not_found` |
| ingestion toggle      | body invalid                            | 400    | `invalid_input`        |

CLI hints (table in `ghillie/cli/commands/estate.py`): `estate_not_found` → "Run
`ghillie estate list` to see known estates."; `repository_not_found` → "Run
`ghillie estate repo list --estate-key <key>` to see registered repositories.";
`catalogue_invalid` → "Validate the file with
`python -m ghillie.catalogue.cli <path>` before importing."; transport errors →
"Check `--api-base-url` and that the service is running."; any other code →
"See the service logs for details."

## Revision note

- 2026-10-16: initial draft from Wyvern reconnaissance; awaiting expert-panel
  review.
