# Add estate-management APIs and command-line interface (CLI) commands

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`,
`Outcomes & Retrospective`, `Conformance basis`, and `Verification plan` must
be kept up to date as work proceeds.

Status: APPROVED (2026-11-03)

This plan implements roadmap Task 2.5.b (tracked on the branch
`2-5-2-estate-management-apis`). It was approved by a human on 2026-11-03 and
implementation began the same day. It has been revised once after an
expert-panel design review; see `Decision log` and the revision note at the end.

## Purpose / big picture

Today an operator who wants Ghillie to watch a set of repositories has to write
Python: they construct a `CatalogueImporter`, call
`RepositoryRegistryService.sync_from_catalogue`, and call `enable_ingestion` or
`disable_ingestion` from a REPL or a script. The packaged `ghillie` CLI has the
right command names (`ghillie estate import`, `sync`, `list`, `repo list`,
`repo set`), but every one of them prints a `not_implemented` placeholder, the
HTTP service exposes no estate endpoints, and nothing outside the test suite
creates the database schema.

After this change an operator can configure an estate end to end with no
Python. They start the service with environment variables only (including an
opt-in schema bootstrap), run `ghillie estate import` to upload a catalogue
file for an estate, `ghillie estate sync` to project the catalogue's
repositories into the operational registry, `ghillie estate repo list` to see
which repositories are registered and whether ingestion is enabled, and
`ghillie estate repo set` to switch ingestion on or off for one repository.
Every command calls a stable HTTP endpoint, and the same endpoints can be
driven with `curl`. An ingestion toggle set by the operator survives later
catalogue imports and registry syncs.

Success is observable when:

1. A service started with `GHILLIE_DATABASE_URL` pointing at an empty
   database, `GHILLIE_DB_BOOTSTRAP=create-all`, `GHILLIE_ALLOW_STUB_BROKER=1`,
   and no other configuration answers `GET /estates` with `200` and an empty
   `items` list.
2. Against that service, the command below exits `0` and reports created
   projects, components, and repositories:

   ```bash
   ghillie --api-base-url http://127.0.0.1:8089 estate import \
     --estate-key demo --catalogue-path examples/wildside-catalogue.yaml \
     --commit-sha abc123
   ```

3. `ghillie estate sync --estate-key demo` exits `0` and reports
   `repositories_created` greater than zero.
4. `ghillie --output json estate repo list --estate-key demo` exits `0` and
   prints a JSON document whose `items` list contains `leynos/wildside` with
   `"ingestion_enabled": true`.
5. `ghillie estate repo set --owner leynos --name wildside --ingestion-disabled`
   exits `0`; a subsequent re-import with a new commit and a re-sync leaves
   `leynos/wildside` disabled and lists it in the sync response's
   `repositories_left_disabled`.
6. Requests for an unknown estate or repository return HTTP `404` with a
   structured error body carrying a stable `code`, and the CLI maps them to
   exit code `3` with `code`, `message`, and `hint` fields.
7. `make check-fmt`, `make typecheck`, `make lint`, `make test`,
   `make markdownlint`, and `make nixie` all pass after each milestone.

## Constraints

- Hexagonal boundaries are enforced by Hecate (`[tool.hecate]` in
  `pyproject.toml`, run by `make check-architecture` inside `make lint`). New
  modules must be assigned to a group explicitly, with narrower prefixes listed
  before generic ones (first-match semantics). Pure policy and port modules
  (`ghillie.registry.policy`, `ghillie.estate.models`, `ghillie.estate.errors`,
  `ghillie.estate.ports`) must be in `domain_ports`, so Hecate enforces their
  purity.
- The driving port owns its error vocabulary. Falcon resources import only
  `ghillie.estate.{ports,models,errors}`; they never import catalogue or
  registry exceptions. `EstateManagementService` translates
  `CatalogueValidationError`, `ghillie.registry.errors.RepositoryNotFoundError`,
  `RegistrySyncError`, and SQLAlchemy errors into `ghillie.estate.errors`.
- The CLI stays a thin HTTP client. After `import ghillie.cli.app`, no module
  under `ghillie.catalogue`, `ghillie.registry`, `ghillie.estate`, or
  `sqlalchemy` may be loaded. Hecate cannot express this (the `inbound_adapter`
  group may import `application`), so a subprocess test enforces it.
- `ghillie/estate/__init__.py` contains only a docstring: a re-exporting
  package initializer would drag the service, the catalogue package, and its
  import-time Dramatiq broker guard into every `ghillie.estate.models` import.
- HTTP paths are those in `docs/mvp-cli-specification.md` (endpoint table):
  `GET /estates`, `POST /estates/{estate_key}/catalogue-import`,
  `POST /estates/{estate_key}/registry-sync`,
  `GET /estates/{estate_key}/repositories`, and
  `PATCH /repositories/{owner}/{name}/ingestion`.
- Existing endpoints keep their paths, statuses, and existing body fields.
  Error bodies may gain the additive `code` field (D7); nothing is removed or
  renamed.
- No new runtime or development dependencies.
- No persisted-schema change: no table, column, index, or constraint is added
  or altered. The repository has no migration framework.
- Red-Green-Refactor for every behavioural change. Red stages use
  `@pytest.mark.xfail(strict=True, raises=AssertionError, reason=...)` (or
  `raises=NotImplementedError` against committed stubs); the green step removes
  the marker. Red test modules must collect cleanly: import new symbols inside
  test bodies or commit signature stubs first.
- Gates run sequentially, never in parallel; long output is captured with
  `tee` under `/tmp`.
- British English with Oxford `-ize` spelling (`make spelling` enforces it).

## Tolerances (exception triggers)

The work is delivered as three stacked pull requests (D19). Tolerances apply
per pull request.

- Scope: more than 35 files touched or more than 2500 net new lines in one
  pull request: stop and escalate.
- Interface: any change that removes or renames an existing HTTP path,
  existing response field, existing CLI verb, or an existing public method of
  `RepositoryRegistryService` or `CatalogueImporter`: stop and escalate. Adding
  keyword-only parameters with defaults is allowed.
- Dependencies: any new third-party package: stop and escalate.
- Persistence: any table, column, index, or constraint change: stop and
  escalate.
- Iterations: a gate still failing after 5 focused fix attempts: stop and
  escalate with the log path.
- Architecture: if Hecate rejects an import the design requires and the only
  fix is a new group or a widened `allowed` list: stop and escalate.
- Runtime: if Granian does not deliver ASGI lifespan events to Falcon's
  `process_startup` (D13), stop and present the fallback options.
- Ambiguity: a third interpretation of any option or policy recorded in
  `Decision log`: stop and present options.

## Risks

- Risk: registry sync overwrites `ingestion_enabled` on every run.
  Severity: high. Likelihood: certain (`ghillie/registry/sync.py`
  `_update_silver_repository`). Mitigation: EP-M1, test-first, in its own pull
  request, before any endpoint exposes toggles.
- Risk: a repository listed in two estates' catalogues, or re-imported under a
  second estate key after a typo, makes sync insert a duplicate Silver row and
  fail with a uniqueness violation for the whole estate. Severity: high.
  Likelihood: medium. Mitigation: EP-M1 loads Silver rows by slug, skips rows
  owned by another estate, and reports them in `repositories_conflicted`.
  Moving a repository between estates, and deleting an estate, remain out of
  scope and are documented as known gaps.
- Risk: importing `ghillie.api.app`, `ghillie.runtime`, `ghillie.catalogue`,
  or `ghillie.reporting` in a process with no Dramatiq broker raises
  `RuntimeError` at import time, so the service crashes in every mode unless
  `GHILLIE_ALLOW_STUB_BROKER=1` is set. Severity: medium. Likelihood: certain.
  Mitigation: out of scope (Task 2.5.e owns worker-free start-up, D15); the
  users' guide documents the variable; the end-to-end test strips `PYTEST_*`
  variables from the child environment and sets the variable explicitly, so the
  hazard is exercised rather than masked.
- Risk: the Helm chart injects `DATABASE_URL` with a `postgresql://` URL,
  whereas the runtime reads `GHILLIE_DATABASE_URL` and needs an asyncpg URL, so
  a chart deployment starts in health-only mode. Severity: medium. Likelihood:
  certain. Mitigation: handed to Task 2.5.e; the runtime logs its mode and
  registered route families at start-up, and the CLI reports a route-level
  `404` as `endpoint_unavailable` with a health-only-mode hint.
- Risk: a crafted catalogue uses YAML anchors and aliases to expand into a
  huge object graph, and synchronous parsing blocks the event loop. Severity:
  high (unauthenticated by default). Likelihood: low. Mitigation: reject
  documents containing anchors or aliases before composition, cap the body at 1
  MiB, and parse in `asyncio.to_thread`.
- Risk: mutating endpoints are unauthenticated by default and the chart's
  ingress uses a catch-all host. Severity: medium. Likelihood: medium.
  Mitigation: opt-in bearer-token check (D14) when `GHILLIE_API_TOKEN` is set;
  the CLI already sends the header.
- Risk: the 30-second CLI timeout expires while the server completes a large
  import, so the operator sees a failure for a committed change. Severity:
  medium. Likelihood: low. Mitigation: `request_timeout` error code with a hint
  that re-running is safe (imports of a repeated `commit_sha` are skipped; sync
  is idempotent). If sync p95 approaches the timeout, D2's asynchronous path is
  triggered.
- Risk: PostgreSQL rejects over-long `commit_sha` (64) and `estate_name`
  (255) values that SQLite silently accepts. Severity: medium. Likelihood:
  medium. Mitigation: request-struct length constraints returning `400`, and
  error-contract rows run against the py-pglite fixture.
- Risk: Skylos flags new symbols with no production caller at a plateau, or
  msgspec response-struct fields read only by the encoder. Severity: low.
  Likelihood: medium. Mitigation: wire `build_estate_service` into
  `ghillie/api/factory.py` in EP-M2; add reasoned
  `[[tool.skylos.dead_code.entrypoints]]` rules where a finding is a verified
  false positive.
- Risk: database-backed Hypothesis runs breach the 30-second pytest timeout or
  mix event loops. Severity: low. Likelihood: medium. Mitigation: one in-memory
  SQLite engine per state-machine run inside a dedicated `asyncio.Runner`,
  bounded settings, and an explicit module timeout.

## Progress

- [x] (2026-10-16) Renamed branch to `2-5-2-estate-management-apis`.
- [x] (2026-10-16) Reconnaissance of CLI, API, catalogue, registry, and docs
  with a Wyvern agent team.
- [x] (2026-10-16) Spiked Cyclopts 3.24 flag naming:
      `Parameter(name=[…], negative=[…])` yields `--ingestion-enabled/--active`
      and
      `--ingestion-disabled/--inactive` aliases on one `bool | None` parameter,
      and a required `bool` reports `MissingArgumentError` when omitted.
- [x] (2026-10-16) Drafted this ExecPlan.
- [x] (2026-10-16) Expert-panel design review (structure, contracts, failure
  modes, alternatives, verification); verdict "proceed with conditions"; plan
  revised to address every finding (see revision note).
- [x] (2026-10-16) Opened draft pull request leynos/ghillie#200 for plan
  review.
- [x] (2026-11-03) Plan approved by a human; implementation commenced.
- [x] PR-A, EP-M1: sync preserves operator toggles and reports conflicts.
  - [x] (2026-11-03) Red artefacts written: `ghillie/registry/policy.py`
        stub, `SyncResult` fields, `dry_run` stubs, the exhaustive policy
        table, the named examples, and the O1 state machine.
  - [x] (2026-11-03) Red observed after the environment build completed:
        `test_sync_preserves_operator_disable` failed with `assert True is
        False`, `test_sync_keeps_readded_repository_disabled` failed the same
        way, `test_sync_reports_cross_estate_conflict` raised
        `RegistrySyncError`, `test_sync_dry_run_leaves_registry_unchanged`
        raised `NotImplementedError`, and the O1 state machine failed with
        `sqlite3.IntegrityError: UNIQUE constraint failed:
        repositories.github_owner, repositories.github_name` because the old
        loader could not see another estate's row.
  - [x] (2026-11-03) Green: `ghillie.registry.policy` implemented; `sync.py`
        loads estate, unowned, and catalogue-named rows, consults the policy,
        and implements `dry_run` by rolling back an explicit transaction.
  - [x] (2026-11-03) Focused suites green: 42 tests across the policy table,
        named examples, and O1; 60 registry unit tests overall. O1 produced
        all five transitions (adopt, preserve, disable_inactive,
        disable_removed, conflict) in the witness seed.
  - [x] (2026-11-03) CodeRabbit review addressed: a dry run now flushes
        before rolling back so constraints are evaluated, the state machine's
        `toggle` rule takes `enabled` keyword-only, and the policy and ADR
        wording were corrected.
  - [x] (2026-11-03) Full gate suite green sequentially: `check-fmt`,
        `check-architecture`, `typecheck`, `lint` (Hecate and Skylos),
        `test` (1222 passed, 11 skipped), `markdownlint`, `nixie`, and
        `spelling`.
  - [x] (2026-11-05) Hosted CodeScene review of the published PR-A head
        flagged `EstateSyncMachine._apply_transition` (complex method, bumpy
        road) and `import_subset` (complex conditional) in the O1 state
        machine. The transition replay now dispatches to `_replay_conflict`,
        `_replay_unlinked`, and `_replay_removed`, and the import replay moved
        into `_replay_import`; behaviour is unchanged and `cs delta
        origin/main` reports no findings.
  - [x] (2026-11-05) Hosted ExecPlan assessment asked for the O1
        seeded-mutation evidence and for coverage of the remaining dry-run and
        preview guarantees. The mutation was run on a disposable worktree at
        `2a56711`: `decide_for_catalogue_repository` returned
        `catalogue_active` for `PRESERVE`, and both
        `test_sync_preserves_operator_disable` (`assert True is False`) and
        `test_sync_transitions_are_modelled` (`AssertionError:
        leynos/wildside-mockup`) failed; the file was then restored. Three
        tests were added: a dry run over existing rows proves metadata updates
        and removal deactivations roll back, a flush-time `IntegrityError`
        surfaces as `RegistrySyncError`, and 101 disabled repositories yield a
        100-entry preview with an exact count of 101.
  - [x] (2026-11-05) The follow-up assessment at `3f7a959` found no remaining
        implementation defect and confirmed all three gaps closed. It raised
        one conformance exception: the PR-A diff is 2657 net new lines, 157
        above the 2500-line scope tolerance. The exception is recorded as D24
        with its rationale; the added tests are EP-M1 verification obligations
        and cannot move to PR-B without breaking the D19 plateau boundary.
  - [x] (2026-11-06) The EP-A-R6 assessment asked to reconcile the O1
        seeded-mutation record. Running the specified field-update mutation
        showed both O1 tests still pass: the policy block reasserts the final
        flag, though the scalar loop can still mark the row changed. The plan
        now records that result and names the policy mutation that did fail.
        EP-A-R7 asked to drop the broader "behaviourally equivalent" claim; the
        text now says only that the final ingestion flag is preserved and notes
        the changed-row side effect.
- [x] (2026-11-06) Reached the hosted pre-merge checks. The PR title now names
      roadmap task 2.5.b. Two test gaps were closed: the cross-estate conflict
      test gives the foreign row distinct metadata and compares a full field
      snapshot before and after sync, and the dry run asserts the exact
      six-repository projection instead of a lower bound.
      `docs/developers-guide.md` gained a "Registry synchronization" section
      covering the policy transitions, their `domain_ports` placement, the
      `dry_run` rollback contract, and the `SyncResult` fields. The remaining
      three pre-merge findings are recorded as D27 with evidence for why each
      is outside the approved scope.
- [x] (2026-11-06) The second hosted review round corrected D27's claim about
      `uq_repositories_owner_name` and asked for concurrent-adoption coverage.
      Adoption of an unowned row is now claimed with a conditional update that
      matches only rows where `estate_id` is null (D28), so a sync that loses
      the race reports a conflict instead of replacing the winner's claim. New
      tests cover the
      primitive under a stale view, the losing sync path, and the insert race's
      preserved `IntegrityError` cause; the Silver snapshot helper now includes
      `is_active`, `created_at`, and `updated_at`.
- [x] (2026-11-06) The hosted CodeScene review of `4866f8e` failed the advisory
      rule gate on `test_concurrent_insert_surfaces_as_a_conflict_cause`
      (excess function arguments). The test now inserts its foreign row
      directly instead of taking the `create_repo` fixture, and the local
      `cs check` reports a code health score of `10.00` for the module.
- [x] (2026-11-06) The third hosted review round accepted the two repaired
      dispositions and asked for the exceptional-state limits to stay explicit.
      The Surprises entry now names both: an ownership-only claim commits
      without advancing `repositories_updated` or `last_synced_at`, and the
      removal path judges ownership from the loaded view, so a row another
      estate claimed after the load can still be disabled. The Verification
      section also says what the D28 tests are — deterministic stale-view and
      missed-read regressions — rather than implying overlapping-transaction
      coverage.
- [x] (2026-11-06) The follow-up review corrected that round's account of the
      two limits. The ownership-only limit is not inherited: at the PR base the
      claim was unconditional and `_update_silver_repository` applied
      `estate_id` itself, so the change counted; D28's conditional claim
      introduced the gap. Only the removal-path limit predates D28. The entry
      now says so, and says that no normal production path creating the state
      was identified rather than that none exists. The Verification section no
      longer says every D28 test drives a sync:
      `test_claim_unowned_repository_is_atomic_under_a_stale_view` calls the
      claim primitive directly.
- [x] PR-B, EP-M2: estate port, service, and catalogue queries.
  - [x] (2026-11-03) Red observed: `test_estate_service.py` hit
        `NotImplementedError` from the service stub, and the new importer
        dry-run and rename tests exercised the missing behaviour.
  - [x] (2026-11-03) Green: `parse_catalogue_text` rejects anchors and aliases
        in `asyncio.to_thread`; `ghillie.catalogue.queries` reads estates with
        their latest import; the importer accepts `dry_run` and keeps an
        existing description on rename (D18); `EstateManagementService`
        validates keys and pages, serializes import and sync per estate,
        translates every underlying failure (D17), logs each mutation (D21),
        and implements dry runs (D20).
  - [x] (2026-11-03) Focused suites green: 84 tests on SQLite and 53 tests on
        py-pglite across the models, parser, queries, service, pagination, and
        importer modules. The O2 walk covers 780 count, filter, and limit
        combinations.
  - [x] (2026-11-03) Hecate groups extended for the new ports, application
        service, and catalogue query adapter; `build_estate_service` provides
        the production caller.
  - [x] (2026-11-03) Full gate suite green sequentially: `check-fmt`,
        `test` (1298 passed, 11 skipped), `markdownlint`, and `nixie` on the
        candidate. The first `lint`/`typecheck` run failed: Skylos reported
        six service helpers as dead and `MAX_REQUEST_BODY_BYTES` as unused, and
        `ty` rejected the importer's transaction annotation and a possibly
        `None` page offset.
  - [x] (2026-11-03) Repairs: the importer now annotates
        `AsyncSessionTransaction` (the type `session.begin()` returns), the
        pagination test narrows `next_offset` before arithmetic,
        `MAX_REQUEST_BODY_BYTES` was removed until EP-M3 adds it with its
        consumer, and a reasoned `type = "function"` Skylos entrypoint rule
        records that the six helpers have verified runtime callers in
        `EstateManagementService`. `make lint` and `make typecheck` then
        passed on the repaired candidate.
- [x] PR-B, EP-M3: HTTP endpoints, error contract, bootstrap, and auth.
  - [x] (2026-11-03) Red artefacts written: `tests/unit/test_api_auth.py`,
        `test_api_estate_errors.py`, `test_api_estate_resources.py`,
        `test_openapi_estate_paths.py`, `test_runtime_wiring.py`, and
        `test_storage_bootstrap.py`, plus updates to `test_api_app.py`,
        `test_api_errors.py`, and `test_api_report_resource.py`.
  - [x] (2026-11-03) Green: `ghillie/api/estate/schemas.py` and
        `resources.py` implement the five endpoints with msgspec decoding, a
        one-megabyte body limit, media-type checks, and single-valued query
        parameters; `ghillie/api/auth.py` adds the optional bearer middleware
        (D14); `ghillie/storage_bootstrap.py` creates missing tables at ASGI
        start-up behind `GHILLIE_DB_BOOTSTRAP` (D13); `ghillie/api/errors.py`
        renders every failure through the D7 envelope with stable codes and
        Falcon's own headers preserved; `ghillie/api/app.py` registers route
        families independently and `ghillie/runtime.py` reads the new
        environment variables; `specs/openapi.yml` documents the endpoints,
        security scheme, parameters, and reusable error responses.
  - [x] (2026-11-03) Focused suites green: 129 tests across the nine API,
        runtime, and OpenAPI modules.
  - [x] (2026-11-03) First full gate run found four `ty` diagnostics and one
        stale Skylos contract test. Repairs: the middleware protocol keeps
        Falcon's keyword-compatible parameter names, the error handler narrows
        `HTTPError.headers` to `dict[str, str]`, the chunked-body test casts
        the Falcon app at the `httpx.ASGITransport` boundary, and
        `_RUNTIME_ENTRY_POINTS` gained the EP-M2 function rule.
  - [x] (2026-11-03) Second full gate run went seven of eight green;
        `make lint` then reported five `SKY-U006` unused-parameter findings on
        the Falcon-mandated middleware arguments. A narrow `type =
        "parameter"` entrypoint rule with its rationale records why the bearer
        check cannot consume them, and the contract test asserts that rule.
  - [x] (2026-11-03) Third full gate run went seven of eight green again; the
        exhaustive O2 walk timed out during py-pglite fixture start-up on a
        heavily loaded host. The module now carries the explicit 120-second
        timeout the plan reserves for database-heavy runs; its test body takes
        about four seconds, so the longer budget covers start-up only.
  - [x] (2026-11-03) Fourth full gate run green sequentially: `check-fmt`,
        `check-architecture`, `typecheck`, `lint` (Hecate, Ruff, and Skylos),
        `test` (1391 passed, 11 skipped), `markdownlint`, `nixie`, and
        `spelling`.
  - [x] (2026-11-04) CodeRabbit review of this milestone returned nine
        findings (six minor, three trivial). Repairs: the bootstrap docstring
        now states that concurrent `CREATE TABLE` can fail a replica;
        `GHILLIE_API_TOKEN` is stripped before use; the bearer check compares
        bytes so a Latin-1 credential is a 401 rather than a `TypeError`; a
        catch-all `Exception` handler renders the D7 envelope and logs the
        detail; the BOM literal is an escape sequence; per-estate locks live
        in a `WeakValueDictionary` with a regression test; the empty estate
        port double is shared from `tests/unit/estate_test_helpers.py`; every
        new-test assert carries a failure message; and the four
        `nullable: true` OpenAPI fields are JSON Schema null unions, asserted
        by a new test.
  - [x] (2026-11-04) Final gate suite after the review repairs, run
        sequentially on the candidate: `check-fmt`, `check-architecture`,
        `typecheck`, `test` (1396 passed, 11 skipped), `markdownlint`,
        `nixie`, and `spelling` were green. `lint` found one `ANN401` in the
        new OpenAPI walker; retyping its argument as `object` fixed it, and
        `make lint` and the OpenAPI module then passed on the final
        candidate.
  - [x] (2026-11-04) Second CodeRabbit review (against the real base
        `2-5-2-estate-management-apis`) returned fourteen findings (twelve
        unique; one was reported twice). Repairs: `MAX_PAGE_OFFSET` bounds
        `offset` so an oversized value is a 400 instead of a SQLite
        `OverflowError` 500 or a PostgreSQL storage 503, and the OpenAPI
        `Offset` parameter documents the same maximum; the bearer middleware
        is built whenever estate routes are exposed (or a token is
        configured) so the disabled-authentication warning logs without
        dropping protection from a reports-only app; `handle_falcon_http_error`
        passes `HTTPError.headers` to `set_headers` so list-form headers
        survive; `get_estate_by_key` scopes its ranking window to the
        requested estate; the unreachable 409 and 422 responses are removed
        from `setRepositoryIngestion`; the `-ise` docstrings use en-GB
        Oxford `-ize` spelling; and the remaining bare test asserts carry
        failure messages. Regression tests were added for the offset bound,
        middleware construction, and scoped subquery. The full gate suite was
        green on the repair commit (`6bb5d44`): `check-fmt`,
        `check-architecture`, `typecheck`, `lint`, `test` (1401 passed, 11
        skipped), `markdownlint`, `nixie`, and `spelling`.
  - [x] (2026-11-04) Third CodeRabbit review returned five findings (one
        minor, four trivial). Repairs: `CatalogueImportRequest.estate_name`
        is a JSON Schema null union, matching the server's accepted null; the
        public port, service, and `get_estate_by_key` docstrings carry NumPy
        parameter, return, and raise sections; `_sync_error` matches on the
        wrapped cause and compares `RegistrySyncError.reason` to the new
        `ESTATE_NOT_FOUND_REASON` constant exported by
        `ghillie.registry.errors`; the remaining bare property-test assert
        carries a message; and the two oversized test modules were split at
        their endpoint and service seams, with the shared fake port and
        database builders moved into `tests/unit/estate_test_helpers.py`. The
        full gate suite was green on `946ad03`: `check-fmt`,
        `check-architecture`, `typecheck`, `lint`, `test` (1401 passed, 11
        skipped), `markdownlint`, `nixie`, and `spelling`.
  - [x] (2026-11-05) Fourth CodeRabbit review returned fifteen findings (three
        major, three minor, nine trivial). Triage and repairs:
        - The reported partial-read upload bug is a false positive for Falcon
          4.3: `BoundedStream.read(size)` already loops over ASGI events until
          it fills the requested size or reaches the end of the body. A new
          regression test pins multi-chunk assembly and the existing streamed
          oversize test still rejects at the limit.
        - `parse_catalogue_text` now rejects collections nested deeper than 64
          levels during the preparse event scan, before the recursive
          constructor can exhaust the interpreter stack.
        - `EstateManagementService.list_repositories` delegates to a new
          `RepositoryRegistryService.list_repositories`, so the Silver query
          uses the registry's own session factory instead of the catalogue
          factory.
        - `list_estates` selects its page before ranking latest imports, and
          `_latest_import_subquery` accepts `estate_ids` so the window covers
          only that page.
        - `generateReport` documents its 401 response.
        - The test helper treats only `None` as "use the fixture", so an
          explicitly empty upload reaches validation.
        - NumPy `Attributes` sections were added to the public estate data
          classes, estate exceptions, and `EstateRow`; the three newly exported
          API handlers gained parameter and return sections.
        - Remaining trivial repairs: a `TypedDict` for the error-body helper,
          `collections.abc.AsyncIterator`, removal of a redundant `__future__`
          import, and `AsyncSessionTransaction` moved under `TYPE_CHECKING`.
        Focused red-then-green runs are recorded above; fast gates
        (`check-fmt`, `typecheck`, `lint`) were green before the repair commit.
  - [x] (2026-11-05) Fifth CodeRabbit review returned seventeen findings (two
        major, four minor, eleven trivial). Triage and repairs:
        - A configured but blank `GHILLIE_API_TOKEN` now stops start-up instead
          of silently disabling authentication. `_read_api_token` strips the
          value (secrets read from files often carry a newline) and raises
          `SystemExit` when the stripped value is empty; a regression test
          covers it.
        - `ghillie.estate.ports` imports its model types at runtime, so
          `typing.get_type_hints` resolves annotations for adapters and
          documentation tools under PEP 649; a regression test resolves the
          `list_estates` return type.
        - `handle_registry_sync_failed` logs the exception before rendering the
          envelope, so a handled 500 still leaves an operator-visible record;
          a `capture_femto_logs` test asserts the line.
        - The generated-report 422 example and `ErrorResponse` schema now carry
          the optional `review_id`, asserted by the OpenAPI walker.
        - `estate service` private helpers gained single-line docstrings; every
          API error handler gained full NumPy sections.
        - The registry, service, and estate-service test fixtures moved to
          `tests/unit/conftest.py`, removing three duplicate local fixtures; the
          pagination matrix now walks an empty registry for every filter and
          limit; the lock-leak test probes lock lifetime through weak
          references instead of reading the protected `_locks` map; the dry-run
          importer test asserts neither an estate nor an import record
          persists; the bootstrap idempotence test inserts a row between runs
          and asserts it survives; and `estate_test_helpers` documents its
          exported builders.
        - Skipped with reasons: the claimed future-dated plan entry is correct
          (the cited commit `8d26df3` is dated 2026-11-05), and no
          `types-PyYAML` stub package is needed (`pyright` reports no
          missing-stub diagnostic for the test file, and Pyright is not a
          gate). The suggestion to rewrite the loader's explicit `isinstance`
          event scan as structural pattern matching is stylistic; the current
          form is clear, and the `getattr(event, "anchor", None)` guard
          deliberately covers event types that declare the attribute
          differently.
  - [x] (2026-11-05) Full gates on the fifth-review repair commit `bb2d39d`
        were green sequentially: `check-fmt`, `check-architecture`,
        `typecheck`, `lint`, `test` (1410 passed, 11 skipped), `markdownlint`,
        `nixie`, and `spelling`. The milestone CodeRabbit CLI review against
        base `2-5-2-estate-management-apis` returned two trivial findings:
        - The five exported estate resource classes gained NumPy `Parameters`
          and `Raises` sections on their public `on_get`, `on_post`, and
          `on_patch` handlers, naming the API and port errors each path can
          raise.
        - Skipped with reason: making an unset `GHILLIE_API_TOKEN` a fail-fast
          configuration error unless `GHILLIE_API_AUTH=disabled` is set would
          contradict decision D14, which deliberately keeps an unset token as
          "unauthenticated with a start-up warning". The reviewer labels it a
          posture suggestion rather than a defect; changing it needs a new
          decision and is outside this plan's approved scope.
        The follow-up review of the docstring commit returned one minor
        finding: `tests/unit/test_api_auth.py` used `-ise` spellings in
        assertion messages. They now use the repository's en-GB Oxford `-ize`
        form; the `unauthorized` code literal was already correct.
        A third pass returned one trivial test-strength finding: the
        Falcon-description test repeated the `/nope` case and only asserted
        truthiness. It now drives the 415 media-type path, where the resource
        sets its own description, and asserts that the accepted media type
        reaches the envelope.
        A fourth pass returned two minor findings, both accepted:
        - `GET /estates` now normalizes `last_import.imported_at` to an aware
          UTC timestamp at the wire boundary. SQLite drops `tzinfo` on
          round-trip, so a self-hosted deployment previously emitted an ISO
          string with no offset, violating the OpenAPI `format: date-time`
          contract. A red-then-green test covers the naive case.
        - The `ghillie/api/auth.py` module docstring claimed an unset *or
          empty* token leaves every route open. The launcher now refuses a
          set-but-blank token, so the docstring and the corresponding test
          docstring state the middleware-level behaviour separately from the
          launcher's fail-fast.
        A fifth pass returned one trivial finding: `ghillie/catalogue/queries.py`
        annotated `estate_ids` as `typ.Sequence`. It now imports
        `collections.abc` under `TYPE_CHECKING` and uses `cabc.Sequence`, per
        the repository rule that ABCs come from their defining module.
        A sixth pass returned two findings, both accepted:
        - `handle_storage_unavailable` now logs the chained exception before
          rendering the 503, matching the other server-fault handlers; a
          `capture_femto_logs` test asserts the line.
        - `_log_mutation` renders the client-supplied `estate_key` and
          `commit_sha` with `%r`. A newline can no longer split the record or
          forge a second line; a red-then-green test feeds a hostile
          `commit_sha` and asserts the record stays single-line with a visible
          escape.
        A seventh pass returned two findings, both accepted:
        - `import_catalogue` applied `validate_new_estate_key` before the
          lookup, so an estate created earlier through Python under a legacy
          key (for example `"Wildside Estate"`) could never be re-imported.
          That contradicted D16: the strict pattern belongs only to creation.
          The method now validates the key as a reference up front and applies
          the creation pattern inside the per-estate lock only when no row
          exists. A red-then-green test seeds a legacy-key estate and imports
          into it.
        - `set_ingestion` interpolated the client-supplied `owner` and `name`
          with `%s`. They now use `%r`, matching `_log_mutation`, and a test
          feeds a newline-bearing name and asserts the record stays on one
          line. `make test` also produced five `vidaimock` fixture-teardown
          timeout errors under twelve-worker load in code untouched by this
          branch; the next gate run confirmed they were flaky: `test`
          reported 1415 passed and 11 skipped with no vidaimock errors.
        An eighth pass returned two findings:
        - `AppDependencies.api_token` appeared in the dataclass-generated
          `__repr__`, so a token could leak through a log line or traceback.
          The field is now excluded from `repr`, with a red-then-green test
          asserting the token never renders.
        - Skipped with the earlier reason: rewriting the loader's explicit
          `isinstance` event scan as structural pattern matching is stylistic;
          the current form is clear, and the `getattr(event, "anchor", None)`
          guard deliberately covers event types that declare the attribute
          differently.
        A ninth pass returned one minor finding: `load_catalogue` caught only
        `OSError`, so a file with invalid UTF-8 raised an uncaught
        `UnicodeDecodeError` instead of the validation report the catalogue
        CLI prints for other read and parse failures. The read-time handler
        now covers `UnicodeError` too, with a red-then-green test writing
        undecodable bytes to a temporary file.
        A tenth pass returned two low-severity findings on the same lines,
        proposing conflicting remedies for one gap: an over-length catalogue
        value (project or component name, repository owner/name/default
        branch) passed validation and failed at flush with `DataError`, which
        the service reported as a 503 storage fault rather than a 422
        rejection. The validator remedy was chosen over mapping `DataError` to
        422, because `DataError` also covers faults unrelated to length, and
        the validator runs before a session opens, so a dry run now fails
        exactly as a real import does. `_validate_stored_length` records an
        issue for any value beyond `String(255)`, without echoing the
        over-length value; red-then-green unit tests cover each field at 255
        (accepted) and 256 (rejected), and a service test asserts the HTTP
        boundary maps it to `CatalogueRejectedError`. The reviewer's separate
        observation that the `except (OperationalError, InterfaceError)` branch
        duplicates the following `SQLAlchemyError` branch is correct — both
        exceptions are subclasses — and was applied as its own behaviour-
        preserving refactor commit, after the functional change, per the
        repository's atomic-refactor rule.
  - [x] (2026-11-05) Final EP-M3 gate run at `1dde1aa` was green across all
        eight gates: `check-fmt`, `check-architecture`, `typecheck`, `lint`,
        `test` (1424 passed, 11 skipped, 94 warnings, exit 0),
        `markdownlint`, `nixie`, and `spelling`. The milestone CodeRabbit CLI
        review against base `2-5-2-estate-management-apis` reviewed 45 files
        and returned no findings; the two previously skipped stylistic and
        D14-posture suggestions were not re-raised. EP-M3 is complete and
        PR-B is ready for publication.
  - [x] (2026-11-05) Hosted CodeScene review of the PR-B head flagged eleven
        findings: `EstateManagementService.import_catalogue` (large method,
        excessive parameters, complex conditionals), `_log_mutation` (excessive
        parameters), `_reject_unsafe_structure` (bumpy road), six duplicated
        error handlers in `ghillie/api/errors.py`, `_build_middleware`
        conditionals, and duplicated assertion blocks in the API, catalogue,
        and pagination test modules. Repairs, all behaviour-preserving:
        - `CatalogueImportRequest` (D22) replaces the five-argument port
          method; `_run_import`, `_import_summary`, `_import_details`,
          `_parse_catalogue`, and `_MutationLog` split the service method.
        - `_reject_unsafe_structure` delegates to `_reject_anchor` and
          `_track_depth`.
        - A declarative `_ESTATE_ERROR_SPECS` table plus a shared `_Envelope`
          and `_set_error` collapse the six estate handlers, the catalogue
          rejection handler, and the report-validation handler into one
          `handle_estate_error`; every remaining handler renders through the
          same envelope builder.
        - `_needs_auth` and `_has_bootstrap` name the middleware conditions.
        - The duplicated tests merge into parametrized cases, and the 780-case
          pagination walk extracts `_walk_every_limit`, `_walk_every_filter`,
          and `_import_seed`.
        Focused suites were green; the eight-gate run at `6903e14`, recorded below,
        covers this entry (its first attempt at `507f684` failed `check-fmt`
        on `mdtablefix` and was reformatted before the green run).
  - [x] (2026-11-05) The hosted ExecPlan assessment for PR-B found no core
        mutation or authentication defect and listed three evidence gaps,
        all now closed:
        - D21: `import_catalogue`, `sync_registry`, and `set_ingestion` wrap
          their work and log exactly one terminal record on success, skip, or
          failure, with the error class and message on failure; import records
          now include edge counts. Red run first: the five new tests failed
          against the previous service (missing edge counts and missing
          failure records) and pass after the change. The success, skipped,
          failed, and pre-lock rejection paths each assert a single record.
        - O4: two database-backed HTTP cases now run the real service over
          `session_factory`. An over-long `estate_name` is a 400
          `invalid_input`, and a second import replays the losing insert of a
          concurrent import so the unique estate key raises a real
          `IntegrityError` and the response is a 409 `conflict`; both assert
          that no SQL or driver text reaches the body.
        - O5: `test_body_limit_boundary` builds exact-byte JSON bodies at
          1 MiB − 1, 1 MiB, and 1 MiB + 1 using multibyte padding and escaped
          newlines, so character count and byte count differ; the first two are
          accepted and the third is a 413 `payload_too_large`.
        - The PR-B scope-tolerance exception is recorded as D23.
        Focused suites (101 tests) were green; the full eight-gate run at
        `6903e14` then passed: `check-fmt`, `check-architecture` (`hecate:
        architecture check passed`), `typecheck` (`All checks passed!`), `lint`
        (Hecate, Ruff, Skylos), `test` (1440 passed, 11 skipped, 94 warnings,
        exit 0), `markdownlint` (58 files, 0 issues), `nixie` (all diagrams
        validated), and `spelling` (93.70% coverage). Logs are under
        `/tmp/*-ghillie-2-5-2-estate-management-apis-b.out`; the hosted
        re-observation follows.
  - [x] (2026-11-05) The PR-B re-assessment at `6903e14` confirmed the O4,
        O5, and D23 closures and left one narrow D21 omission: `set_ingestion`
        logged a terminal record only for `RegistryRepositoryNotFoundError`
        and `SQLAlchemyError`, so any other exception escaped without one. A
        direct service caller has no HTTP catch-all to log it, so the attempt
        vanished from the operator's view. Red run first: the new test
        (`test_set_ingestion_logs_one_terminal_record_for_an_unexpected_error`)
        failed because no record was written; it now passes. The fix logs one
        `estate.set-ingestion` record naming the error class and re-raises the
        exception unchanged, preserving the two existing translations. The
        full eight-gate run at `ec3a80d` passed: `check-fmt`,
        `check-architecture`, `typecheck`, `lint`, `test` (1441 passed, 11
        skipped, 0 failed), `markdownlint`, `nixie`, and `spelling`. Logs are
        under `/tmp/*-ghillie-2-5-2-estate-management-apis-b.out`.
  - [x] (2026-11-05) The PR-C gate run at `0655461` failed `make test` with a
        native segmentation fault in `msgspec._core`, crashing xdist worker
        `gw3` while the O4 conflict test raced two imports. The test now
        replays the loser's insert deterministically: one import commits the
        estate, then a patched `_ensure_estate` inserts the duplicate and
        flushes, so the database's unique key produces the `IntegrityError`
        the service translates. The focused module passes (16 tests). The
        crash itself is recorded under Surprises as unexplained; the
        two-thread `msgspec.convert` race did not reproduce in 200 fresh
        processes. The PR-B re-gate at `95c7886` then passed all eight gates:
        `check-fmt`, `check-architecture`, `typecheck`, `lint`, `test` (1442
        passed, 11 skipped, 0 failed), `markdownlint`, `nixie`, and `spelling`.
        Logs are under `/tmp/gate-B-95c7886-*.out`. PR-C's rebase follows this
        entry.
- [ ] PR-C, EP-M4: CLI commands, rendering, and error mapping.
- [ ] PR-C, EP-M5: behavioural, snapshot, and end-to-end coverage.
- [ ] PR-C, EP-M6: documentation, roadmap, and final gates.

## Surprises & discoveries

- Observation: registry sync resets operator toggles. Evidence:
  `ghillie/registry/sync.py` `_update_silver_repository` includes
  `("ingestion_enabled", cat_repo.is_active)` in its field updates. Impact:
  EP-M1.
- Observation: the deployed process cannot import its own application without
  a broker. Evidence:
  `env -u GHILLIE_ALLOW_STUB_BROKER uv run python -c
  "import ghillie.api.factory"`
  raises `RuntimeError: No Dramatiq broker configured` from
  `ghillie/catalogue/importer.py`; the panel reproduced the same failure for
  `import ghillie.api.app` through `ghillie/reporting/__init__.py` importing
  the reporting actor. Impact: health-only mode is affected too; deferred to
  Task 2.5.e (D15).
- Observation: no production code path creates the Silver, Gold, or Bronze
  tables; `init_*_storage` is called only by tests and by the catalogue
  Dramatiq job. Impact: D13.
- Observation: the runtime requires `GHILLIE_STATUS_MODEL_BACKEND` whenever
  `GHILLIE_DATABASE_URL` is set, because `build_reporting_service` calls
  `create_status_model()`. Impact: D13 decouples estate routes from reporting
  configuration.
- Observation: the catalogue YAML has no `active` field; the importer never
  writes `RepositoryRecord.is_active`, so `False` is reachable only by direct
  database writes, yet an existing test requires sync to honour it.
- Observation: re-importing without `--estate-name` renames the estate to its
  key and clears its description (`ghillie/catalogue/importer.py`
  `CatalogueImporter.__init__` and `_ensure_estate`). Impact: D18.
- Observation: Falcon decodes `%2F` before routing, so an estate key
  containing `/` misses the route and receives Falcon's default `404`; it never
  reaches validation. Impact: D16 and the error contract.
- Observation: `ghillie/registry/ingestion.py` `set_ingestion_enabled`
  already reports whether the state changed, and the docstrings of
  `enable_ingestion` and `disable_ingestion` in `ghillie/registry/service.py`
  misdescribed the return value. Impact: corrected in EP-M1.
- Observation: the old sync loaded only this estate's and unowned rows, so a
  catalogue slug already owned by another estate became an INSERT and failed
  the global unique `(github_owner, github_name)` constraint. Evidence: the O1
  machine's witness seed raised `sqlite3.IntegrityError`. Impact: EP-M1 adds a
  second, slug-scoped query so conflicts are visible rather than fatal.
- Observation: Hypothesis passes only the machine instance to a `@precondition`
  callable, never the rule's arguments. Impact: O1 keeps coarse preconditions
  and guards the chosen index inside each rule body; a guard that rejects the
  index is a no-op step.
- Observation: pull-request CI runs pytest through the shared
  `generate-coverage` action (`.github/workflows/ci.yml`), not `make test`.
  Impact: EP-M5 confirms the `e2e` tests run there.
- Observation: `/tmp` contains a stray `bisect.py`, so Python run with `/tmp`
  as its working directory cannot import the standard library. Impact: run
  scratch Python with `-I` from the repository root.
- Observation: `ty` matches Falcon middleware protocol members by parameter
  name, so an underscore-prefixed unused argument fails conformance, while the
  keyword-compatible name triggers Skylos's `SKY-U006`. Impact: the protocol
  keeps Falcon's names and the five arguments the bearer check cannot consume
  are declared as documented Skylos parameter entry points.
- Observation: Falcon's ASGI `App` annotates the scope as `dict[str, Any]`,
  while `httpx.ASGITransport` requires a `MutableMapping`. Impact: the
  chunked-body test casts at that boundary instead of weakening either type.
- Observation: `session_factory` starts a fresh py-pglite Postgres for every
  test, so fixture set-up alone costs about 26 seconds; under heavy host load
  pytest-timeout's 30-second default can expire during set-up before the test
  body runs. Impact: `test_estate_pagination` carries the plan's explicit
  120-second module timeout.
- Observation: Falcon routes an exception with no registered handler to its
  default 500, which bypasses the D7 envelope and emits only a `title`.
  Registering a domain handler set is therefore not "every failure type"; the
  catch-all `Exception` handler is required, and `falcon.HTTPError` handlers
  still win by method-resolution order. Impact: EP-M3.
- Observation: OpenAPI 3.1 aligns the Schema Object with JSON Schema
  2020-12, which has no `nullable` keyword, so `nullable: true` is silently
  ignored by validators; `type: [T, "null"]` is the portable form. Impact: the
  four optional response fields in `specs/openapi.yml`.
- Observation: the local CodeRabbit CLI reviews committed history, not the
  working tree, so review repairs must be committed before a re-assessment can
  cover them. Impact: the review loop for EP-M3.
- Observation: the O4 conflict proof raced two imports through
  `asyncio.to_thread(parse_catalogue_text, ...)`, and one full-suite run
  crashed an xdist worker with a native segmentation fault inside
  `msgspec._core` at `ghillie/catalogue/loader.py`'s `msgspec.convert` call.
  Evidence: the scrutineer's gate-5 log for PR-C head `0655461` (1 failed, 1529
  passed, 11 skipped); the same test alone passed ten times, and 200 fresh
  processes racing two threads through the first `msgspec.convert` of
  `Catalogue` did not reproduce it. Impact: the proof now replays the losing
  insert deterministically instead of racing, so O4 no longer depends on thread
  scheduling or on a concurrent parse. The crash remains unexplained and is
  recorded here rather than attributed to a cause the evidence does not
  support; if it recurs, capture a core dump before changing production code.

- Observation: the Silver schema permits an unowned row (`estate_id` null) that
  still carries a `catalogue_repository_id`. Because the policy treats a null
  `estate_id` as adoptable, and therefore as owned for its purposes, such a row
  falls through to the removal and update paths like an owned one. No normal
  production path that creates that state was identified: adoption applies only
  to unlinked rows, and creation always sets `estate_id`. Two narrow limits
  follow. EP-M1 records both rather than adding special cases, and they do not
  share an origin.
  - An ownership-only claim does not register as an update. D28 introduced this
    limit. `_claim_unowned_repository` mirrors the new `estate_id` onto the
    loaded row, so `_update_silver_repository` afterwards finds every field
    already equal. The claim commits, but `repositories_updated` does not
    increment and `last_synced_at` does not advance for that row. At the PR
    base the claim was unconditional and `_update_silver_repository` applied
    `estate_id` itself, so the same change was counted.
  - The removal path judges ownership from the loaded view. This limit predates
    D28 and is unchanged by it. If the slug is absent from this estate's
    catalogue and is enabled, the removal path disables it — including when
    another estate claimed the row after this sync loaded its view. Closing
    that would need the same conditional ownership check in the removal path
    that D28 added to the claim.

## Decision log

All decisions dated 2026-10-16 by the planning agent, revised after the
expert-panel review.

- D1, catalogue upload. `POST /estates/{estate_key}/catalogue-import` takes
  `application/json` body
  `{"commit_sha": str (1–64), "estate_name": str
  (1–255) | null, "catalogue_yaml": str}`.
  The 1 MiB limit applies to the HTTP request body (checked from
  `Content-Length` and while reading); the `413` body carries `max_bytes`. The
  CLI serializes the body once and checks those exact bytes, so the client
  check is advisory and no constant is shared. The server rejects documents
  containing YAML anchors or aliases, and parses in `asyncio.to_thread`. The
  response carries `skipped`, `skipped_reason` (`"commit_already_imported"` or
  `null`), `registry_sync_required` (`true` unless skipped or dry run), and
  `state: "succeeded"`. Rationale: the file is local to the operator;
  server-side paths are non-portable and a path-traversal hazard. Rejected: raw
  YAML body, server path, server-side git fetch (overlaps
  `GitCatalogueWatcher`, adds credential and request-forgery risk). The upload
  is the manual path; `GitCatalogueWatcher` remains the automated one.
- D2, synchronous operations. Import and sync complete within the request.
  `estate sync` drops `--wait/--no-wait`, and the specification removes
  `estate sync` from the run-state contract. Responses include
  `state: "succeeded"` so that a later asynchronous mode (`202` with a
  `run_id`) is an additive change. Rationale: both are single transactions well
  inside the timeout for MVP estates; a run resource without a status endpoint
  would be dishonest. Trigger for revisiting: sync p95 approaching the request
  timeout.
- D3, toggle ownership (recorded as ADR-005). Sync decides ingestion with two
  pure functions in `ghillie.registry.policy`. For a repository present in the
  catalogue: a new row, or an unlinked row (`catalogue_repository_id IS NULL`)
  being adopted, takes `catalogue.is_active` (`ADOPT`); a linked row of this
  estate keeps its state (`PRESERVE`) unless the catalogue marks it inactive
  (`DISABLE_INACTIVE`); a row owned by another estate is left untouched and
  reported (`CONFLICT`). For a linked row of this estate absent from the
  catalogue: `DISABLE_REMOVED`. Sync assigns `ingestion_enabled` only when the
  decided value differs, which narrows the lost-update window with concurrent
  toggles. Fail-closed applies to linked rows: sync never re-enables one. A
  repository removed and later re-added therefore stays disabled until an
  operator enables it, and the sync response lists such repositories in
  `repositories_left_disabled` (first 100 slugs plus a count). A toggle on an
  unlinked ad hoc row lasts only until adoption; this is documented. Rejected:
  an override column (needs migrations); unlinking removed rows (breaks
  `ghillie/evidence/project_service.py`, which joins on
  `catalogue_repository_id`); moving rows between estates (no safe ownership
  rule without estate deletion).
- D4, estate listing. `estate list` drops `--active/--inactive` (estates have
  no lifecycle state). `GET /estates` uses the same paginated envelope as
  repository listing and returns key, name, description, and latest import
  (`commit_sha`, `imported_at`). The query lives in a catalogue-owned module,
  `ghillie/catalogue/queries.py` (outbound adapter).
- D5, repository listing. `repo list` takes one `bool | None` parameter named
  `--ingestion-enabled/--ingestion-disabled`, with `--active/--inactive` as
  documented aliases (the specification's spelling); neither flag lists all.
  The query parameter `ingestion_enabled` accepts exactly `true` or `false`.
  Pagination: `limit` 1–500 (default 50), `offset` ≥ 0 (default 0); the
  response carries `has_more` (from a `limit + 1` look-ahead) and `next_offset`
  (`null` on the last page). Items reuse
  `ghillie.registry.models.RepositoryInfo` fields. The CLI validates `limit` and
  `offset` locally with `cyclopts.validators.Number` and exits `2` without a
  request.
- D6, toggles. `repo set` uses
  `Parameter(name="--ingestion-enabled", negative="--ingestion-disabled")`
  (required). `PATCH` accepts `application/json` or
  `application/merge-patch+json` with `{"ingestion_enabled": bool}`; `null`,
  strings, missing, or unknown fields return `400`; other media types return
  `415`. The response is `{"owner", "name", "ingestion_enabled", "changed"}`;
  repeating a toggle returns `changed: false`.
- D7, error contract. Every error body is
  `{"title", "description", "code"[, "field"][, "issues"][, "max_bytes"]}`.
  `code` is added to the three existing handlers (`repository_not_found`,
  `invalid_input`, `report_validation_failed`) and to a `falcon.HTTPError`
  handler (`not_found`, `method_not_allowed`, `unsupported_media_type`,
  `unauthorized`, `payload_too_large`). `issues` is always a list of
  `{"code", "message"}`; catalogue validation strings become
  `{"code": "catalogue_schema", "message": ...}`. RFC 9457 (problem details) is
  deferred to Task 2.6.c, which can negotiate it with `detail` mirroring
  `description`. The CLI writes errors to standard error as
  `{"error": {"code", "message", "hint", "status", "issues"?}}` in `json` and
  `yaml` modes and as readable lines in `table` mode, and exits `3`. JSON and
  YAML success output is the server document unchanged and is a contract; table
  output is not.
- D8, msgspec at the HTTP boundary. Request bodies decode into
  `msgspec.Struct` types with `forbid_unknown_fields=True` and `Meta` length
  constraints; responses encode from structs. The CLI decodes responses
  leniently. Compatibility rule: adding a response field is non-breaking;
  adding a request field needs the server upgraded first.
- D9, driving port. `ghillie.estate.ports.EstateManagement` is a
  `typing.Protocol` implemented by
  `ghillie.estate.service.EstateManagementService`, which composes
  `CatalogueImporter`, `RepositoryRegistryService`, and
  `ghillie.catalogue.queries`. The panel's alternative (methods directly on
  `RepositoryRegistryService`, concrete services in resources) was weighed: it
  saves about six files but couples the HTTP layer to catalogue and registry
  exceptions and leaves no single place for estate-key resolution, translation,
  locking, and logging. The port is kept because the task requires domain logic
  to be separated from adapters. The service stays a thin coordinator.
- D10, Vidai Mock is not used: no inference service is involved. The
  end-to-end test does not configure a status model at all (D13).
- D11, ADR-005 records D3 ("Registry sync preserves operator ingestion
  toggles"), because it changes operator-visible semantics and amends the
  registry design. Other decisions are recorded in `docs/ghillie-design.md`
  §8.5.
- D12, path naming. `catalogue-import` and `registry-sync` are kept as
  specified action sub-resources of an estate. Pluralizing them would imply
  persisted, addressable records that do not exist.
- D13, start-up decoupling and schema bootstrap. `ghillie/runtime.py` builds
  the estate service whenever `GHILLIE_DATABASE_URL` is set, and the reporting
  service only when `GHILLIE_STATUS_MODEL_BACKEND` is also set (an invalid
  value still fails fast); it logs the mode and registered route families. A new
  `ghillie/storage_bootstrap.py` provides `init_all_storage(engine)`; when
  `GHILLIE_DB_BOOTSTRAP=create-all` the app runs it from a Falcon
  `process_startup` lifespan hook. The default is off. It uses `create_all`,
  which only creates missing tables and is documented as single-replica and
  pre-migration. Rationale: the completion criterion forbids Python scripting,
  and the end-to-end test must exercise the operator path, not a test helper.
- D14, optional authentication. When `GHILLIE_API_TOKEN` is set, a middleware
  requires `Authorization: Bearer <token>` on every route except `/health` and
  `/ready`, compared with `hmac.compare_digest`; failures return `401`
  `unauthorized`. Unset means unauthenticated, as today, and a start-up warning
  is logged. The token is never logged.
- D15, deferred to Task 2.5.e: the import-time broker guard, the Helm
  environment-variable and driver mismatch, and worker-free start-up. The
  hand-off is written into `Outcomes & retrospective` and the roadmap's 2.5.e
  entry.
- D16, estate keys. Creating an estate (import) requires
  `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`; other endpoints accept any 1–64
  character key so that keys created earlier through Python stay reachable. The
  CLI pre-validates the import key with the same pattern and exits `2`; a test
  asserts the two patterns are equal. Keys containing `/` cannot be routed and
  surface as `not_found`.
- D17, concurrency and storage failures. The service serializes import and
  sync per estate with an in-process `asyncio.Lock` (single replica in MVP).
  `IntegrityError` maps to `409` `conflict`; connection-level
  `OperationalError` and `InterfaceError` map to `503` `storage_unavailable`.
  Descriptions never include SQL or driver detail; the cause is logged.
- D18, estate identity on re-import. When `estate_name` is `null`, the service
  passes the stored name, and `_ensure_estate` no longer clears the description
  on rename (catalogues carry no estate description).
- D19, delivery as three stacked pull requests: PR-A (EP-M1 and ADR-005),
  PR-B (EP-M2 and EP-M3), PR-C (EP-M4 to EP-M6). Each is a coherent plateau
  that passes every gate. The roadmap is marked done in PR-C.
- D20, dry runs. The root `--dry-run` option, already parsed into
  `ResolvedCliConfig.dry_run`, maps to `?dry_run=true` on import and sync. The
  service runs the operation in its transaction and rolls back, returning the
  counts it would have produced. `CatalogueImporter.import_catalogue` and
  `RepositoryRegistryService.sync_from_catalogue` gain keyword-only
  `dry_run: bool = False`. Rationale: the pre-mortem's most likely incident is
  importing the wrong file into a live estate.
- D21, observability. Each mutation attempt logs exactly one terminal
  structured line through `ghillie.logging`: operation, estate key, commit, dry
  run, counts, duration, and outcome. Import records include edge counts. A
  failed attempt records the error class and message instead of the counts, so
  a rejected document, a conflict, and a storage outage are distinguishable
  without a second log line. Toggles also log the old and new state.
- D22, catalogue-import request value. The port method is
  `import_catalogue(estate_key, request: CatalogueImportRequest)` rather than a
  five-argument signature. Rationale: the four request fields travel together
  from the HTTP resource through the service to the importer, so grouping them
  removes a data clump and keeps the driven port inside the repository's
  parameter limits without a suppression. The frozen, slotted dataclass lives in
  `ghillie.estate.models`, so the port stays free of transport types. The API
  layer constructs it from the decoded body and the `dry_run` query flag; the
  service passes it through unchanged. Behaviour is identical to the positional
  form.
- D23, PR-B scope-tolerance exception. PR-B exceeds the per-PR tolerance in
  `Tolerances (exception triggers)`: GitHub's comparison against `2a56711`
  reports 45 changed files and 7,718 net added lines, against limits of 35
  files and 2,500 lines. The overage is an exception, not an unnoticed drift.
  Rationale: EP-M2 and EP-M3 are one coherent plateau — the service, its
  models, and its error vocabulary are not independently testable from the five
  HTTP routes, the auth middleware, and the bootstrap wiring that expose them,
  and D19 fixes that pairing in PR-B. Splitting them would leave an unexercised
  port in one PR and an untested adapter in the next. The escalation outcome is
  the standing instruction to continue the approved plan to completion; no
  scope was added beyond EP-M2 and EP-M3, and no interface, dependency, or
  persisted-schema tolerance is exceeded. Recorded here so a later reviewer
  sees the deviation and its basis rather than discovering it from the
  comparison.
- D24, PR-A scope-tolerance exception. The hosted ExecPlan assessment measured
  PR-A against `main` at `2ffdb4d` as 13 files, 2748 additions, and 91
  deletions: 2657 net new lines, 157 above the 2500-line tolerance. The overage
  is the three tests the same assessment requested at `3f7a959` (an
  existing-row dry-run rollback, a flush-time `IntegrityError` translation, and
  a 100-entry disabled preview from 101 repositories). Those tests are part of
  EP-M1's own verification obligations, so deferring them to PR-B would break
  the D19 plateau boundary; the alternative was shipping EP-M1 with the dry-run
  and preview guarantees unproved. Recorded as an accepted exception under the
  standing instruction to continue delivery. No interface, dependency, or
  persistence tolerance is exceeded, and the file-count tolerance (35) is not
  approached.
- D27, pre-merge-check reconciliation. The hosted pre-merge checks raised six
  findings against PR-A. Three are actioned in this round: the title names
  roadmap task 2.5.b; `test_sync_reports_cross_estate_conflict` gives the
  foreign row a distinct branch, catalogue link, documentation paths, and sync
  time, then proves a full field snapshot is unchanged; and the dry run asserts
  the exact six-repository creation count. Three are dispositions:
  1. A "2.0.0 migration document" has no basis here: `pyproject.toml` declares
     version 1.0.0, and no release or migration process exists. The users' guide
     already signposts toggle ownership, conflict reporting, the result fields,
     and `dry_run`.
  2. Ownership of an existing row is not arbitrated by
     `uq_repositories_owner_name`: that constraint guards concurrent *inserts*
     of the same owner/name, and D17 maps the resulting `IntegrityError` to
     409. It cannot arbitrate two estates adopting the same unowned row,
     because changing `estate_id` leaves the owner/name pair unique. The
     second review round made that distinction explicit, so the adoption claim
     is now a conditional `UPDATE ... WHERE estate_id IS NULL` (D28) and the
     losing sync reports a conflict. The earlier wording overstated the
     constraint's reach and is corrected here.
  3. The repository has no metrics or tracing stack, and the plan forbids new
     runtime dependencies and persisted-schema changes. D21 specifies exactly
     one structured line per mutation at the estate-service boundary; adding a
     second line in the registry module would contradict that. Metrics and
     tracing are a cross-cutting platform decision, not an EP-M1 deliverable.
- D28, atomic adoption of an unowned Silver row. `_claim_unowned_repository`
  issues a conditional update of `estate_id` that matches only rows where
  `estate_id` is null, and treats a zero row count as a conflict. This closes
  the race the owner/name constraint cannot see: two estates syncing
  concurrently can both read the same unowned row, and without the conditional
  update the later writer silently replaces the earlier claim. The claim runs
  inside the sync transaction, so a dry run rolls it back. Concurrent inserts
  of the same slug remain arbitrated by `uq_repositories_owner_name` and
  surface as `IntegrityError`, which D17 maps to 409. D25 and D26 are
  introduced by branch C and follow this entry once the stack is
  applied.

## Outcomes & retrospective

Not complete. On completion record, per pull request, what shipped against the
success criteria, the gate results, and the hand-off of D15 to Task 2.5.e.

### PR-A, EP-M1 (complete)

Outcome: `ghillie.registry.policy` decides ingestion from four inputs
(ownership, linkage, current flag, catalogue activity) through
`decide_for_catalogue_repository` and `decide_for_removed_repository`.
`sync.py` consults it, loads estate, unowned, and catalogue-named rows, reports
other-estate rows in `repositories_conflicted` instead of failing, and supports
`dry_run`. `SyncResult` gained `repositories_conflicted`,
`repositories_left_disabled`, and `repositories_left_disabled_count`.

Evidence: the red run failed exactly as predicted (see Progress), and the
focused suites are green (42 tests for policy plus named examples plus O1; 60
registry unit tests). The O1 witness seed produced every `IngestionTransition`,
so the non-vacuity assertion holds.

Retrospective: the state machine found a real defect that the named examples
alone could not express — the cross-estate UNIQUE violation — because it
exercised interleavings in which one estate claims a slug first. A CodeRabbit
review then found that a dry run could report counts for a sync whose unique
constraint would fail on commit; flushing before the rollback closes that gap
and keeps the dry-run contract honest.

### PR-B, EP-M2 (complete)

Outcome: `ghillie.estate` provides the `EstateManagement` protocol and its
`EstateManagementService`, which composes `CatalogueImporter`,
`RepositoryRegistryService`, and `ghillie.catalogue.queries`. The service
validates keys and pages, serializes import and sync per estate, translates
every underlying failure into the estate error vocabulary, logs each mutation,
and implements dry runs. `parse_catalogue_text` rejects anchors and aliases off
the event loop, and the importer keeps an estate's description on rename.

Evidence: red and green runs are recorded in Progress; the focused suites pass
on SQLite (84 tests) and py-pglite (53 tests), and the O2 walk covers 780
count, filter, and limit combinations. The full gate suite passed, then the
dead-code and type repairs described in Progress were re-gated with `make lint`
and `make typecheck`.

Retrospective: Skylos's liveness graph misses module-private helpers called
from async methods, so the six false positives needed an entrypoint rule with
the caller rationale; the rule stays narrow rather than disabling the gate.

### PR-B, EP-M3 (complete)

Outcome: `ghillie/api/estate/` exposes the five documented endpoints over
msgspec request and response structs. `ghillie/api/errors.py` renders the D7
envelope — `title`, `description`, and a stable `code`, plus optional fields
such as `field`, `issues`, or `max_bytes` — for every failure, with the HTTP
status carried separately on the response, including the catch-all handler
Falcon would otherwise answer with a bare 500. `BearerTokenMiddleware` enforces
an optional token while the probes stay open, `AppDependencies` lets each route
family appear independently, and `StorageBootstrapMiddleware` creates the
schema only when `GHILLIE_DB_BOOTSTRAP` opts in. Catalogue parsing runs off the
event loop, rejects anchors, aliases, and excessive nesting before composition,
and now also rejects values that cannot fit their storage columns.

Evidence: the ten review cycles recorded in Progress each ended in a green
eight-gate run; the final run at `1dde1aa` reported 1424 passed, 11 skipped,
and 94 warnings with exit 0, and the milestone CodeRabbit CLI review returned
no findings across 45 files. The O4 and O5 server halves are covered by
`tests/unit/test_api_estate_resources.py`, `test_api_estate_errors.py`,
`test_api_auth.py`, and the py-pglite endpoint suite.

Retrospective: ten independent review passes were needed because each pass
looked at a different facet — wire-format contracts, log safety, validation
ordering, secret redaction, and input decoding. Two lessons carried forward:
validate untrusted input against the storage contract rather than mapping the
database's error afterwards, and treat a seeded legacy key as a first-class
case whenever a new key format is introduced.

## Context and orientation

Ghillie is a Python 3.14 service. Source lives in `ghillie/`, tests in
`tests/`, documentation in `docs/`. Use `make` targets and `uv`.

An *estate* is a named collection of projects, components, and repositories
described by a YAML *catalogue* (example: `examples/wildside-catalogue.yaml`;
schema: `schemas/catalogue.schema.json`). Estates live in the `estates` table
(`ghillie/catalogue/storage.py`, class `Estate`: `id` UUID string, unique `key`
up to 64 characters, `name`, `description`). `CatalogueImportRecord`
(`catalogue_imports`) records each processed `(estate_id, commit_sha)`.
Catalogue repositories (`RepositoryRecord`, table `catalogue_repositories`) are
unique by owner and name across all estates.

*Catalogue import* is `ghillie/catalogue/importer.py` class
`CatalogueImporter(session_factory, *, estate_key, estate_name)`, with
`import_path` and `import_catalogue(catalogue, *, commit_sha)` returning
`CatalogueImportResult`. A repeated `commit_sha` returns `skipped=True`.
Validation failures raise
`ghillie.catalogue.validation.CatalogueValidationError` (`issues: list[str]`).
`ghillie/catalogue/loader.py` `load_catalogue(path)` parses YAML 1.2 with
`ruamel.yaml` and converts with `msgspec`. Importing anything under
`ghillie.catalogue` runs the package initializer, which imports the importer
and its module-level broker guard.

The *registry* is the Silver `repositories` table (`ghillie/silver/storage.py`,
class `Repository`: `github_owner`, `github_name` unique together,
`default_branch`, `estate_id` (the estate UUID, no foreign key),
`catalogue_repository_id` (no foreign key), `ingestion_enabled`,
`documentation_paths`). Ingestion (`ghillie/github/ingestion.py`) and reporting
(`ghillie/reporting/actor.py`) honour `ingestion_enabled`.
`ghillie/registry/service.py`
`RepositoryRegistryService(catalogue_session_factory, silver_session_factory)`
provides `sync_from_catalogue(estate_key) -> SyncResult`, listing by estate
UUID, and `enable_ingestion` / `disable_ingestion(owner, name) -> bool` (raising
`ghillie.registry.errors.RepositoryNotFoundError`). Sync is implemented in
`ghillie/registry/sync.py`; listing in `ghillie/registry/listing.py`
(`RepositoryListOptions` supports `ingestion_enabled: bool | None`, `limit`,
`offset`, ordered by owner then name).

The *HTTP API* is a Falcon ASGI app from `ghillie/api/app.py`
`create_app(dependencies: AppDependencies | None)`. Errors are domain
exceptions mapped by handlers in `ghillie/api/errors.py`.
`ghillie/api/middleware.py` `SQLAlchemySessionManager` provides
`req.context.session`, used by `ghillie/api/gold/resources.py` `ReportResource`.
`ghillie/api/factory.py` builds services. `ghillie/runtime.py` is the Granian
entry point (`python -m ghillie.runtime`; `GHILLIE_HOST`, `GHILLIE_PORT`,
`GHILLIE_DATABASE_URL`). `specs/openapi.yml` is maintained by hand.

The *CLI* is a Cyclopts app in `ghillie/cli/` (console script `ghillie`, module
entry `python -m ghillie.cli`). `ghillie/cli/app.py` `main(argv) -> int`
pre-parses root options into `ResolvedCliConfig` (`ghillie/cli/config.py`,
including `output`, `request_timeout_s`, `dry_run`) and exposes it through
`ghillie/cli/context.py` `get_current_context()`. A command returns a `str`
(printed, exit `0`) or an `int` (exit code). `ghillie/cli/control_plane.py`
`ControlPlaneClient(config, *, http_client=None)` builds an `httpx.Client` with
base URL, timeout, and bearer token. `ghillie/cli/output.py`
`render_output(payload, *, output)` renders flat mappings. Estate verbs live in
`ghillie/cli/commands/estate.py` and call `_api_placeholder`.

*Hecate* enforces import rules between groups (`composition_root`,
`domain_ports`, `application`, `inbound_adapter`, `outbound_adapter`,
`package_facade`). *Skylos* blocks dead code in `ghillie/` (tests do not count
as callers).

Test infrastructure: `tests/conftest.py` `session_factory` (py-pglite
PostgreSQL, SQLite when `GHILLIE_TEST_DB=sqlite`); `tests/unit/conftest.py`
(`registry_service`, `create_repo`, `fetch_repo`, `wildside_catalogue_path`);
BDD features in `tests/features/*.feature` with steps in
`tests/features/steps/` (pattern: `test_on_demand_report_steps.py`); API unit
tests with `falcon.testing.TestClient`
(`tests/unit/test_api_report_resource.py`); CLI unit tests with
`httpx.MockTransport` (`tests/unit/cli/`). `make test` runs
`uv run pytest -v -n auto`; the default per-test timeout is 30 seconds.

Documents and skills to keep open:

- `AGENTS.md` and `.rules/python-*.md`.
- `docs/mvp-cli-specification.md` (CLI and endpoint contract).
- `docs/ghillie-design.md` §3.0 (CLI boundary) and §8.4 (HTTP API layer).
- `docs/ghillie-bronze-silver-architecture-design.md` §9.1 and §9.2.
- `docs/async-sqlalchemy-with-pg-and-falcon.md`,
  `docs/testing-async-falcon-endpoints.md`,
  `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`.
- `docs/developers-guide.md` "Architecture checks (Hecate)" and "Dead-code
  detection (Skylos)"; `docs/adr-003-adopt-hecate-for-architecture-checks.md`
  and `docs/adr-004-adopt-the-shared-cv005-contract-library.md` (ADR format).
- Skills: `execplans`, `hexagonal-architecture`, `python-router` (then
  `python-types-and-apis`, `python-data-shapes`, `python-errors-and-logging`,
  `python-testing`, `hypothesis`), `skylos`, `en-gb-oxendict-style`,
  `pr-creation`.

## Conformance basis

Upstream artefacts at base commit `2ffdb4d`:

- `docs/roadmap.md` Task 2.5.b. Identifiers assigned by this plan:
  `RM-2.5.b-IMPORT` (catalogue import per estate), `RM-2.5.b-SYNC` (registry
  sync), `RM-2.5.b-LIST` (repository listing), `RM-2.5.b-TOGGLE` (ingestion
  toggles), `RM-2.5.b-DONE` (end to end via CLI and HTTP with no Python).
- `docs/mvp-cli-specification.md`: "Estate commands" (`SPEC-EST-CMDS`), the
  endpoint table (`SPEC-EST-PATHS`), the `--wait/--no-wait` contract
  (`SPEC-WAIT`), "Error handling and exit codes" (`SPEC-EXIT`), "Security
  constraints" (`SPEC-SEC`).
- `docs/ghillie-design.md` §3.0 (`TDD-CLI-THIN`) and §8.4 (`TDD-API-LAYER`).
- `docs/ghillie-bronze-silver-architecture-design.md` §9.2 (`TDD-REG-SYNC`).
- ADR-003 (Hecate). No Terms of Reference document exists.

Trace links:

```plaintext
RM-2.5.b-TOGGLE -> TDD-REG-SYNC (amended by D3, ADR-005) -> EP-M1
                -> tests/unit/test_registry_sync_policy.py
                -> tests/unit/test_registry_sync_state_machine.py
                -> tests/unit/test_registry_service_sync.py::test_sync_preserves_operator_disable
RM-2.5.b-IMPORT -> SPEC-EST-PATHS (D1, D16, D18, D20) -> EP-M2, EP-M3, EP-M4
                -> tests/unit/test_api_estate_resources.py
                -> tests/features/estate_management.feature "Operator imports a catalogue for a new estate"
RM-2.5.b-SYNC   -> SPEC-EST-PATHS, SPEC-WAIT (amended by D2) -> EP-M1, EP-M2, EP-M3, EP-M4
                -> tests/features/estate_management.feature "Operator syncs the registry and lists repositories"
RM-2.5.b-LIST   -> SPEC-EST-CMDS (D4, D5) -> EP-M2, EP-M3, EP-M4
                -> tests/unit/test_estate_pagination.py
RM-2.5.b-TOGGLE -> SPEC-EST-CMDS (D6) -> EP-M3, EP-M4
                -> tests/features/estate_management.feature "Operator disables ingestion and it survives a re-sync"
SPEC-EXIT       -> D7 -> EP-M3, EP-M4 -> tests/unit/test_api_estate_errors.py, tests/unit/cli/test_estate_commands.py
SPEC-SEC        -> D14 -> EP-M3, EP-M4 -> tests/unit/test_api_auth.py, tests/unit/cli/test_estate_token_redaction.py
TDD-CLI-THIN    -> Constraint -> EP-M4 -> tests/unit/cli/test_cli_import_closure.py
RM-2.5.b-DONE   -> D13 -> EP-M5 -> tests/e2e/test_estate_management_e2e.py
```

D2, D3, D4, D5, and D16 amend `docs/mvp-cli-specification.md` and
`docs/ghillie-bronze-silver-architecture-design.md` §9.2; EP-M1 and EP-M6
update them. Approving this plan accepts those amendments.

## Verification plan

Axioms (not verified here): Falcon routes by URI template after
percent-decoding the path; SQL `ORDER BY owner, name LIMIT ... OFFSET ...` is
deterministic because owner and name are unique together; msgspec enforces
`forbid_unknown_fields` and `Meta` constraints; Cyclopts maps `name` and
`negative` lists as observed in the spike; Granian's `ASGI` interface delivers
lifespan events (exercised by the end-to-end test, which fails if the bootstrap
does not run); `httpx.MockTransport` and `httpx.ASGITransport` faithfully
present requests and responses; `ruamel.yaml`'s event parser reports anchors
and aliases.

Obligation O1, toggle ownership under sync (D3).

- Statement: for every combination of current row state (absent; linked or
  unlinked; owned by this estate or another; enabled or disabled) and catalogue
  state (present active, present inactive, absent), the policy returns the
  transition and value in D3; and across any sequence of real imports, syncs,
  toggles, inactive markings, and ad hoc row creations, a linked row of the
  estate is never changed from disabled to enabled by sync, and a present,
  active, linked row keeps the operator's last toggle.
- Method: an exhaustive parameterized table for the pure functions (the input
  space is finite, about 20 cases, so the table is a complete check), plus a
  Hypothesis `RuleBasedStateMachine` driving the real
  `CatalogueImporter.import_catalogue`, `sync_from_catalogue`, and
  `enable/disable_ingestion` against a model.
- Rationale: the defect is order-dependent and lives in the ORM application in
  `sync.py`, not in the pure decision, so the generated adversary must run the
  real code.
- Domain: four repository slugs from the wildside example; rules
  `import_subset(subset)` (fresh `commit_sha` from a counter on each call),
  `sync()`, `toggle(slug, enabled)`, `mark_inactive(slug)` (direct
  `RepositoryRecord.is_active = False`, because YAML cannot express it),
  `create_ad_hoc(slug)` with a precondition that the slug is absent from
  Silver, and `import_into_other_estate(slug)` for `CONFLICT`. One in-memory
  `sqlite+aiosqlite://` engine with `StaticPool` per run, created inside an
  `asyncio.Runner` owned by the machine and closed in `teardown()`. Settings:
  `max_examples=15`, `stateful_step_count=15`, `deadline=None`; module timeout
  120 seconds.
- Artefacts: `tests/unit/test_registry_sync_policy.py` (table),
  `tests/unit/test_registry_sync_state_machine.py` (machine),
  `tests/unit/test_registry_service_sync.py` (named examples, one witness per
  transition, including `test_sync_preserves_operator_disable`,
  `test_sync_keeps_readded_repository_disabled`, and
  `test_sync_reports_cross_estate_conflict`).
- Evidence: before the fix, `test_sync_preserves_operator_disable` fails with
  `assert True is False` and the machine finds a counterexample of the form
  sync, toggle off, import, sync.
- Non-vacuity: the machine test calls
  `hypothesis.stateful.run_state_machine_as_test` inside one test function
  while the model records each observed transition in a `collections.Counter`;
  the same test then asserts the counter covers every `IngestionTransition`
  member. This avoids `event()` statistics (not assertable) and cross-worker
  counters (broken by `-n auto`). Seeded mutation: changing
  `decide_for_catalogue_repository` to return `catalogue_active` for `PRESERVE`
  makes both the named test and the machine fail. Re-adding
  `("ingestion_enabled", cat_repo.is_active)` to the field updates in `sync.py`
  preserves the final ingestion flag, because the policy block reasserts
  `decision.ingestion_enabled` afterwards, but the scalar loop can still mark
  the row changed before the policy restores the flag, so it can increment
  `repositories_updated` and advance `last_synced_at`. It was run and both
  tests still passed, so it is not usable as non-vacuity evidence for the
  final-flag invariant.

Obligation O2, pagination completeness (D4, D5).

- Statement: for `N` registered repositories, any `limit` in 1..10, and each
  filter value (`None`, `True`, `False`), walking pages from `offset=0` while
  `has_more` is true visits every matching repository exactly once, in the
  order of a single unpaged query; the last page has `has_more == False` and
  `next_offset is None`; an offset past the end returns no items.
- Method: exhaustive enumeration (finite domain of 26 × 10 × 3 = 780 cases).
- Domain: one engine seeded one repository at a time (alternating enabled and
  disabled); after each insert, every `limit` and filter is walked. Covers
  `N == 0`, `N % limit == 0`, and `N % limit != 0` by construction.
- Artefact: `tests/unit/test_estate_pagination.py` (runs against
  `session_factory`, so PostgreSQL collation is exercised under py-pglite).
- Evidence: written before `EstateManagementService.list_repositories`
  exists, failing on a `NotImplementedError` stub.
- Non-vacuity: the expected order comes from the database, not Python
  `sorted()`; seeded mutation "fetch `limit` rows instead of `limit + 1`" must
  fail at the first `N == limit` case.

Obligation O3, estate-key validation (D16).

- Statement: `validate_new_estate_key` accepts exactly the strings matching
  the pattern; `validate_estate_key_reference` accepts exactly the strings of
  length 1–64; the CLI pattern equals the server pattern.
- Method: parameterized boundaries plus a Hypothesis property.
- Domain: boundary rows (empty, 1, 64, 65 characters, leading `-` or `.`,
  space, non-ASCII, `..`); Hypothesis `from_regex(pattern, fullmatch=True)` for
  accepted keys and `text()` for arbitrary strings, asserting
  `accepted == bool(pattern.fullmatch(s))`.
- Artefact: `tests/unit/test_estate_models.py`; the CLI equality check lives
  in `tests/unit/cli/test_estate_commands.py`.
- Non-vacuity: the property is split so each outcome class is generated by
  construction: one test draws keys from `from_regex` and asserts acceptance;
  the other draws `text()` filtered to non-matching strings (a filter that
  rejects few inputs, so no health-check suppression is needed) and asserts
  rejection. The mutation "drop the length bound" must fail the 65-character
  row. The route-miss behaviour of `/` is pinned by
  `tests/unit/test_api_estate_errors.py::test_estate_key_with_encoded_slash_is_not_found`,
  which sends `%2F` inside the estate-key segment and expects `404` with code
  `not_found`; the port double raises `StorageUnavailableError`, so routing
  would have produced `503` and the `404` proves the route was never matched.

Obligation O4, error-contract totality (D7, D17).

- Statement: every row of the error contract in `Interfaces and dependencies`
  yields its status and `code`; every non-2xx response, transport failure,
  timeout, and non-JSON error body yields CLI exit `3` with non-empty `code`,
  `message`, and `hint`.
- Method: parameterized tests over the finite contract table.
- Artefacts: `tests/unit/test_api_estate_errors.py` (resource rows with a fake
  port; length-overflow and conflict rows against the real service on
  `session_factory`, so PostgreSQL behaviour is exercised),
  `tests/unit/cli/test_estate_commands.py::test_errors_exit_3`.
- Non-vacuity: each row asserts the exact status and code; mutation "map
  `EstateNotFoundError` to 500" must fail its row.

Obligation O5, size-limit agreement (D1).

- Statement: the CLI rejects exactly the bodies the server would reject.
- Method: parameterized boundary test at limit − 1, limit, and limit + 1
  bytes of serialized body, using a catalogue padded with multibyte characters
  and JSON-escaped newlines.
- Artefact: `tests/unit/test_api_estate_resources.py::test_body_limit_boundary`
  and `tests/unit/cli/test_estate_commands.py::test_import_body_limit_boundary`.
- Non-vacuity: the multibyte padding makes text length and byte length differ,
  so a check on characters instead of bytes fails.

Obligation O6, CLI import closure (`TDD-CLI-THIN`).

- Statement: importing `ghillie.cli.app` loads no module from the forbidden
  packages.
- Method: subprocess test with a clean environment, printing
  `sorted(sys.modules)`.
- Artefact: `tests/unit/cli/test_cli_import_closure.py`.
- Non-vacuity: the test also asserts that `ghillie.cli.commands.estate` is in
  the loaded set, proving the estate commands were imported.

Concurrency of adoption (D28): three tests in
`tests/unit/test_registry_service_sync.py` cover the adoption boundary.
`test_claim_unowned_repository_is_atomic_under_a_stale_view` calls
`_claim_unowned_repository` directly, first with the winner's session and then
with a row loaded before that claim committed, and asserts the second call
claims nothing. `test_sync_reports_conflict_when_adoption_loses_a_race` drives
one sync whose claim matches no row and asserts the reported conflict.
`test_concurrent_insert_surfaces_as_a_conflict_cause` drives one sync whose
loaded view misses a row it then re-inserts, and asserts that the lost insert
preserves the `IntegrityError` cause for the 409 mapping. None of the three
exercises two overlapping transactions, so they are deterministic stale-view
and missed-read regressions rather than a concurrency proof; what they
establish is that a lost claim is reported instead of silently overwriting the
winner.

Residual gaps: the per-estate lock is in-process, so concurrent requests across
replicas are not serialized (single replica in MVP); adoption of an unowned row
and insertion of a new row are still arbitrated atomically at the persistence
boundary (D28). OpenAPI conformance is structural only (paths, methods,
operation IDs, schema names and required properties) until Task 2.6.c.

## Plan of work

Stage A is this plan, the review, and approval. Each later milestone begins
with red tests (strict `xfail` with `raises=`), then the green change removes
the markers, then refactoring. Commit after each green step and each refactor,
gating every commit.

### EP-M1 (PR-A): sync preserves operator toggles and reports conflicts

Tests first. Add the named examples to
`tests/unit/test_registry_service_sync.py`; keep the two existing behaviour
tests (`test_sync_updates_existing_silver_repository` for ad hoc adoption and
`test_sync_disables_ingestion_for_inactive_catalogue_repository`) unchanged. Add
`tests/unit/test_registry_sync_policy.py` and
`tests/unit/test_registry_sync_state_machine.py` (O1).

Create `ghillie/registry/policy.py`, importing only `dataclasses` and `enum`,
and add `ghillie.registry.policy` to the `domain_ports` prefixes. The
`domain_ports` group is declared before `application`, so this prefix wins over
the generic `ghillie.registry` entry, exactly as `ghillie.registry.models` does
today; confirm with `make check-architecture`.

```python
class IngestionTransition(enum.StrEnum):
    ADOPT = "adopt"
    PRESERVE = "preserve"
    DISABLE_INACTIVE = "disable_inactive"
    DISABLE_REMOVED = "disable_removed"
    CONFLICT = "conflict"

@dataclasses.dataclass(frozen=True, slots=True)
class SilverIngestionState:
    is_linked: bool
    is_owned_by_estate: bool  # estate_id equals this estate, or is NULL
    ingestion_enabled: bool

@dataclasses.dataclass(frozen=True, slots=True)
class IngestionDecision:
    ingestion_enabled: bool
    transition: IngestionTransition

def decide_for_catalogue_repository(
    current: SilverIngestionState | None, *, catalogue_active: bool
) -> IngestionDecision: ...

def decide_for_removed_repository(current: SilverIngestionState) -> IngestionDecision: ...
```

In `ghillie/registry/sync.py`: load Silver rows for this estate, unowned rows,
and rows whose slug appears in the catalogue (so rows owned by other estates
are seen); remove `ingestion_enabled` from the field-update table; apply the
decisions, assigning `ingestion_enabled` only when it differs; drive
`repositories_created`, `repositories_updated`, `repositories_deactivated`, and
the new `SyncResult` fields `repositories_conflicted: list[str]` and
`repositories_left_disabled: list[str]` (capped at 100, with
`repositories_left_disabled_count: int`) from the transitions. Add keyword-only
`dry_run: bool = False` to `sync_from_catalogue` (roll back instead of
committing). Update module and service docstrings, including the incorrect
`enable_ingestion` and `disable_ingestion` return-value docs.

Write `docs/adr-005-registry-sync-preserves-operator-ingestion-toggles.md`
(format of ADR-004) and amend
`docs/ghillie-bronze-silver-architecture-design.md` §9.2 and the users' guide's
"Enabling and disabling ingestion" section.

### EP-M2 (PR-B): estate port, service, and catalogue query

Create:

- `ghillie/estate/__init__.py`: docstring only.
- `ghillie/estate/models.py` (`domain_ports`): frozen, slotted dataclasses
  `EstateSummary`, `CatalogueImportSummary`, `RegistrySyncSummary`,
  `RepositoryQuery`, `RepositoryPage` (items are
  `ghillie.registry.models.RepositoryInfo`), `IngestionToggleOutcome`,
  `Page[T]`; constants `MAX_ESTATE_KEY_LENGTH = 64`, `MAX_PAGE_LIMIT = 500`,
  `DEFAULT_PAGE_LIMIT = 50`, `MAX_REQUEST_BODY_BYTES = 1_048_576`,
  `NEW_ESTATE_KEY_PATTERN`; pure `validate_new_estate_key` and
  `validate_estate_key_reference`.
- `ghillie/estate/errors.py` (`domain_ports`): `EstateError`,
  `EstateNotFoundError`, `InvalidEstateKeyError`, `InvalidPaginationError`,
  `CatalogueRejectedError(issues: tuple[Issue, ...])`,
  `RepositoryNotFoundError(owner, name)`, `EstateConflictError`,
  `StorageUnavailableError`, `RegistrySyncFailedError`.
- `ghillie/estate/ports.py` (`domain_ports`): the `EstateManagement`
  Protocol (see `Interfaces and dependencies`).
- `ghillie/catalogue/queries.py` (`outbound_adapter`):
  `list_estates(session_factory, *, limit, offset) -> list[EstateRow]` (estate
  plus latest import) and
  `get_estate_by_key(session_factory, key) -> EstateRow | None`.
- `ghillie/estate/service.py` (`application`, prefix `ghillie.estate` placed
  after the three `domain_ports` leaf prefixes):
  `EstateManagementService
  (session_factory, *, registry: RepositoryRegistryService)`.
  It parses text through a new `ghillie/catalogue/loader.py`
  `parse_catalogue_text(text)` (rejecting anchors and aliases, run in
  `asyncio.to_thread`; `load_catalogue` delegates to it), constructs a
  `CatalogueImporter` per call, passes the stored estate name when none is
  given (D18), holds a per-estate lock (D17), translates errors, logs each
  mutation (D21), and implements `dry_run` (D20).

Modify `ghillie/catalogue/importer.py`: keyword-only `dry_run` on
`import_catalogue` and `import_path`; `_ensure_estate` keeps the description.
Add `build_estate_service(session_factory)` to `ghillie/api/factory.py` so the
service has a production caller at this plateau.

Tests first: `tests/unit/test_estate_models.py` (O3),
`tests/unit/test_catalogue_parse_text.py` (empty, invalid YAML, duplicate keys,
anchors, aliases, alias bomb under 1 MiB, byte-order mark, schema failure,
happy path), `tests/unit/test_catalogue_queries.py`,
`tests/unit/test_estate_service.py` (each method's happy and unhappy paths,
translation of every underlying error, rename preservation, dry run leaves no
rows, lock serializes two concurrent imports),
`tests/unit/test_estate_pagination.py` (O2), and additions to
`tests/unit/test_catalogue_importer.py` (dry run, description kept).

### EP-M3 (PR-B): HTTP endpoints, error contract, bootstrap, and auth

Create `ghillie/api/estate/__init__.py` (docstring only),
`ghillie/api/estate/schemas.py` (request and response structs, D8), and
`ghillie/api/estate/resources.py` with `EstateCollectionResource.on_get`,
`CatalogueImportResource.on_post`, `RegistrySyncResource.on_post`,
`EstateRepositoryCollectionResource.on_get`, and
`RepositoryIngestionResource.on_patch`. The import resource reads at most
`MAX_REQUEST_BODY_BYTES + 1` bytes from `req.stream` (rejecting early on
`Content-Length`). Create `ghillie/api/auth.py` (D14) and
`ghillie/storage_bootstrap.py` (`composition_root` group, D13).

In `ghillie/api/errors.py` add `code` to the existing handlers and add handlers
for every `ghillie.estate.errors` type and `falcon.HTTPError` (D7). In
`ghillie/api/app.py` add `estate_service: EstateManagement | None = None`,
`api_token: str | None = None`, and
`bootstrap_engine: AsyncEngine | None = None` to `AppDependencies`; register
reporting routes and the session middleware only when both `session_factory` and
`reporting_service` are present (unchanged predicate), estate routes whenever
`estate_service` is present (no middleware needed: the service owns its units
of work), the auth middleware when `api_token` is set, and the lifespan
bootstrap when `bootstrap_engine` is set. In `ghillie/runtime.py` implement
D13's wiring and start-up log line, and read `GHILLIE_API_TOKEN` and
`GHILLIE_DB_BOOTSTRAP` (unknown values fail fast).

Update `specs/openapi.yml`: five operations (`listEstates`, `importCatalogue`,
`syncRegistry`, `listEstateRepositories`, `setRepositoryIngestion`), schemas,
`ErrorResponse` with optional `code`, `issues`, and `max_bytes`, and the bearer
security scheme.

Tests first: `tests/unit/test_api_estate_resources.py` (fake port; every
success shape; strict booleans; repeated query parameters; offset past end; O5
server half), `tests/unit/test_api_estate_errors.py` (O4 server half),
`tests/unit/test_api_auth.py` (no token configured; correct, wrong, and missing
token; health exempt), `tests/unit/test_storage_bootstrap.py` (creates every
table on an empty SQLite engine; idempotent), additions to
`tests/unit/test_api_app.py` (route families per dependency combination;
existing reporting tests unchanged), `tests/unit/test_runtime_wiring.py`
(estate-only, estate plus reporting, invalid bootstrap value), and
`tests/unit/test_openapi_estate_paths.py`.

### EP-M4 (PR-C): CLI commands, rendering, and error mapping

In `ghillie/cli/control_plane.py` add
`ControlPlaneError(code, message, hint, status, issues)` with subclasses
`ControlPlaneHTTPError`, `ControlPlaneTransportError`, and
`ControlPlaneTimeoutError`, and
`request_json(method, path_segments, *, params=None, body=None)`, which quotes
each segment with `urllib.parse.quote(segment, safe="")`, serializes the body
once, and decodes leniently. In `ghillie/cli/output.py` add
`render_collection(items, *, columns, output, meta)` (aligned table; full
document for `json` and `yaml`) and `render_error(error, *, output)`.

Rewrite `ghillie/cli/commands/estate.py`: remove `_api_placeholder`; add a hint
table keyed by `code` (estate not found: run `ghillie estate list`; repository
not found: run `ghillie estate repo list --estate-key <key>`; catalogue
invalid: fix the listed issues; `not_found` with no specific code: the endpoint
is unavailable and the service may be in health-only mode (check
`GHILLIE_DATABASE_URL`); transport: check `--api-base-url`; timeout: the
operation may have completed and re-running is safe; `unauthorized`: set
`--auth-token` or `GHILLIE_AUTH_TOKEN`; otherwise see the service logs).
`estate import` reads the file as `utf-8-sig`, exits `2` with
`catalogue_file_unreadable` on I/O or decoding errors, `2` with
`invalid_estate_key` on a pattern mismatch, and `2` with `request_too_large`
when the serialized body exceeds the limit; it prints a prominent `SKIPPED`
line in table mode. Apply D2, D4, D5, D6, and D20. Keep
`ghillie/cli/commands/ingest.py` untouched.

Tests first: `tests/unit/cli/test_estate_commands.py` (method, path, query, and
body per verb via `httpx.MockTransport`; local validation exits `2` with no
request recorded; O4 client half; O5 client half; pattern equality),
`tests/unit/cli/test_output.py` additions,
`tests/unit/cli/test_estate_output_snapshots.py` (syrupy snapshots of `table`
and `yaml` output and of error output, from fixed fake responses; `json`
compared by parsed equality), `tests/unit/cli/test_estate_token_redaction.py`
(a distinctive token and an `--api-base-url` containing `user:pass@` never
appear in standard output, standard error, or logs captured with
`tests/helpers/femtologging_capture.py`, including for `500`, transport, and
non-JSON responses), and `tests/unit/cli/test_cli_import_closure.py` (O6).

### EP-M5 (PR-C): behavioural, snapshot, and end-to-end coverage

BDD harness. `tests/features/steps/test_estate_management_steps.py` uses a
synchronous fixture that owns one `asyncio.Runner`; inside it, it creates the
engine (`NullPool` for py-pglite, `StaticPool` for SQLite), runs
`init_all_storage`, builds the service and app, and wraps them in
`httpx.AsyncClient(transport=httpx.ASGITransport(app))`. A helper,
`tests/helpers/runner_transport.py` class
`RunnerTransport(httpx.BaseTransport)`, implements `handle_request` as
`runner.run(async_client.send(request))`. The fixture monkeypatches
`ghillie.cli.control_plane.httpx.Client` with a factory that adds
`transport=RunnerTransport(...)`, so the CLI's own client construction
(headers, timeout) still runs. All database access stays on the runner's loop.
Seed data through CLI steps; resolve catalogue paths against the repository
root.

`tests/features/estate_management.feature`:

```gherkin
Feature: Estate management through the operator CLI and HTTP API

  Background:
    Given a Ghillie service backed by an empty database

  Scenario: Operator imports a catalogue for a new estate
    When the operator imports "examples/wildside-catalogue.yaml" into estate "demo" at commit "c1"
    Then the command exits with code 0
    And the output reports at least 1 repository created
    And "estate list" lists the estate "demo"

  Scenario: Re-importing the same commit is skipped
    Given the operator has imported "examples/wildside-catalogue.yaml" into estate "demo" at commit "c1"
    When the operator imports "examples/wildside-catalogue.yaml" into estate "demo" at commit "c1" with JSON output
    Then the command exits with code 0
    And the JSON output field "skipped" is true
    And the JSON output field "skipped_reason" is "commit_already_imported"

  Scenario: A dry-run import changes nothing
    When the operator dry-run imports "examples/wildside-catalogue.yaml" into estate "demo" at commit "c1"
    Then the command exits with code 0
    And "estate list" lists no estates

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
    And the last sync reported "leynos/wildside" as left disabled

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
    And no HTTP request was sent
```

End-to-end. `tests/e2e/__init__.py`, `tests/e2e/conftest.py`, and
`tests/e2e/test_estate_management_e2e.py`, marked `e2e` (register the marker in
`pyproject.toml`) with `pytest.mark.timeout(120)`. The fixture:

1. Builds the child environment from `os.environ` minus every `PYTEST_*`
   variable, then sets `GHILLIE_HOST=127.0.0.1`, `GHILLIE_PORT`,
   `GHILLIE_DATABASE_URL=sqlite+aiosqlite:///<tmp_path>/ghillie.db`,
   `GHILLIE_DB_BOOTSTRAP=create-all`, and `GHILLIE_ALLOW_STUB_BROKER=1`. It
   does not set `GHILLIE_STATUS_MODEL_BACKEND`, proving estate routes do not
   need reporting configuration.
2. Starts `[sys.executable, "-m", "ghillie.runtime"]` with
   `start_new_session=True`, standard output and error redirected to files under
   `tmp_path`.
3. Polls `GET /estates` until `200 {"items": [], ...}` for up to 20 seconds,
   checking `proc.poll()` each iteration; on early exit it retries up to three
   times on a fresh port.
4. On teardown sends `SIGTERM` to the process group, waits 10 seconds, then
   `SIGKILL`; attaches the server log to any failure.

The test drives the journey with `[sys.executable, "-m", "ghillie.cli"]`
(import, list estates, sync, list, disable, re-import `c2`, re-sync, list
inactive) and once through the installed console script
(`Path(sys.executable).parent / "ghillie"`), and issues one raw `httpx` request
per endpoint to check the wire contract independently of the CLI. Confirm the
test runs in the CI `generate-coverage` step; document `-m "not e2e"` as the
opt-out. Regenerate snapshots with `-p no:xdist`.

### EP-M6 (PR-C): documentation, roadmap, and final gates

- `docs/users-guide.md`: an "Estate management through the CLI and API"
  section (each command and endpoint with request and response examples, error
  codes, dry runs, the toggle rules including re-added and ad hoc repositories,
  `repositories_conflicted`, a bulk re-enable recipe using
  `ghillie --output json estate repo list` with `jq`, start-up variables
  `GHILLIE_DB_BOOTSTRAP`, `GHILLIE_API_TOKEN`, `GHILLIE_ALLOW_STUB_BROKER`);
  update the "Operator CLI scaffold" wording; retitle the Python snippets as
  programmatic alternatives.
- `docs/mvp-cli-specification.md`: apply D2, D4, D5, D6, D7, D16; add request
  and response shapes and the error-code table; replace the 2.5.a placeholder
  note for estate verbs.
- `docs/ghillie-design.md`: new §8.5 "Estate-management control plane
  (Task 2.5.b)" recording D1, D2, D4–D10, D12–D21 and linking ADR-005; update
  §8.4's module tree and "Planned evolution" note to include
  `ghillie/api/estate/`; update §3.0 to say the estate verbs are live.
- `docs/developers-guide.md`: msgspec request and response structs (D8), the
  error-code convention (D7), the port-owned error vocabulary, the
  `RunnerTransport` BDD harness, running and opting out of `e2e` tests, and the
  docstring-only package-initializer rule for port packages.
- `docs/mvp-gap-analysis.md`: mark the estate-configuration gap closed.
- `docs/roadmap.md`: mark Task 2.5.b done with an "Implemented" note, and add
  the D15 hand-off items to Task 2.5.e.

## Milestones and plateaus

- EP-M1. Outcome: syncs preserve operator toggles and report cross-estate
  conflicts instead of failing. Requirements: `RM-2.5.b-TOGGLE`, `TDD-REG-SYNC`
  amended by ADR-005. Acceptance: O1 discharged. Conformance: `SyncResult`
  gains fields (additive); no schema change; Hecate passes with the new
  `domain_ports` prefix. Recovery: revert PR-A. Remaining gaps: no endpoints.
  Compatibility decision: none.
- EP-M2. Outcome: the estate service is usable from Python with full tests and
  a production caller. Requirements: `RM-2.5.b-IMPORT`, `-SYNC`, `-LIST`,
  `-TOGGLE` at the application layer. Acceptance: O2 and O3 discharged; service
  tests pass. Conformance: new Hecate prefixes as specified; importer change is
  keyword-only and additive. Recovery: the package is additive. Remaining gaps:
  no HTTP or CLI exposure. Compatibility decision: none.
- EP-M3. Outcome: five endpoints, error contract, optional auth, and opt-in
  bootstrap. Requirements: `SPEC-EST-PATHS`, `TDD-API-LAYER`, `SPEC-SEC`.
  Acceptance: O4 and O5 server halves; existing API tests pass unmodified
  except for assertions that now also see `code`. Conformance: additive error
  field only; no trust-boundary change unless `GHILLIE_API_TOKEN` is set.
  Recovery: revert PR-B. Remaining gaps: CLI placeholders. Compatibility
  decision: none.
- EP-M4. Outcome: all estate verbs call the API. Requirements:
  `SPEC-EST-CMDS` (amended), `SPEC-EXIT`, `TDD-CLI-THIN`. Acceptance: O4, O5
  client halves and O6. Recovery: revert the CLI commits. Compatibility
  decision: none (pre-1.0; the verbs were placeholders).
- EP-M5. Outcome: the journey is proven in-process and across processes.
  Requirements: `RM-2.5.b-DONE`. Acceptance: nine scenarios and the e2e test
  pass in `make test` and in CI. Compatibility decision: none.
- EP-M6. Outcome: documentation and roadmap match behaviour. Acceptance: all
  gates pass. Compatibility decision: none.

## Concrete steps

Run from the repository root, sequentially:

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

Focused loops, for example in EP-M1 (`--runxfail` shows the real failure behind
a strict `xfail`):

```bash
uv run pytest tests/unit/test_registry_service_sync.py -v -k preserves --runxfail
```

Expected red output:

```plaintext
FAILED tests/unit/test_registry_service_sync.py::test_sync_preserves_operator_disable - assert True is False
```

Manual check after EP-M3 (two terminals, repository root):

```bash
export GHILLIE_DATABASE_URL="sqlite+aiosqlite:///$PWD/.scratch-estate.db"
export GHILLIE_DB_BOOTSTRAP=create-all GHILLIE_ALLOW_STUB_BROKER=1
GHILLIE_HOST=127.0.0.1 GHILLIE_PORT=8089 uv run python -m ghillie.runtime
curl -s http://127.0.0.1:8089/estates
```

Expected:

```plaintext
{"items":[],"limit":50,"offset":0,"has_more":false,"next_offset":null}
```

Delete `.scratch-estate.db` afterwards.

## Validation and acceptance

- Tests: `make test` passes, including all new unit, property, state-machine,
  snapshot, BDD, and e2e tests; every red stage was observed and recorded in
  `Artefacts and notes`.
- Verification: O1–O6 discharged with their non-vacuity evidence and seeded
  mutations recorded.
- Lint and typecheck: `make check-fmt`, `make typecheck`, and `make lint`
  (Hecate, Ruff, Skylos) pass with no new suppressions beyond reasoned `noqa`
  comments of the kind already used for wide CLI commands.
- Documentation: `make markdownlint`, `make nixie`, and `make spelling` pass.
- Security: the token-redaction tests pass; the alias-bomb test completes
  within one second with `422`.

The end-to-end transcript in `Artefacts and notes` must show success criteria 1
to 5.

## Idempotence and recovery

Every step is re-runnable. Repeated imports of a `commit_sha` are skipped,
syncs are idempotent, toggles report `changed: false` when repeated, dry runs
roll back, and the bootstrap only creates missing tables. The e2e fixture uses
`tmp_path` and kills its process group. Roll back with `git revert` per pull
request.

## Artefacts and notes

Record here as work proceeds: red-stage failure lines, the O1 transition
counter, the O2 case count, seeded-mutation results, and the e2e transcript.

## Interfaces and dependencies

No new dependencies.

```python
# ghillie/estate/ports.py
class EstateManagement(typ.Protocol):
    async def list_estates(self, page: PageRequest) -> Page[EstateSummary]: ...
    async def import_catalogue(
        self, estate_key: str, *, catalogue_yaml: str, commit_sha: str,
        estate_name: str | None, dry_run: bool,
    ) -> CatalogueImportSummary: ...
    async def sync_registry(self, estate_key: str, *, dry_run: bool) -> RegistrySyncSummary: ...
    async def list_repositories(self, estate_key: str, query: RepositoryQuery) -> RepositoryPage: ...
    async def set_ingestion(self, owner: str, name: str, *, enabled: bool) -> IngestionToggleOutcome: ...

# ghillie/catalogue/loader.py
def parse_catalogue_text(text: str) -> Catalogue: ...

# ghillie/storage_bootstrap.py
async def init_all_storage(engine: AsyncEngine) -> None: ...

# ghillie/cli/control_plane.py
class ControlPlaneClient:
    def request_json(
        self, method: str, path_segments: cabc.Sequence[str], *,
        params: cabc.Mapping[str, str] | None = None,
        body: cabc.Mapping[str, object] | None = None,
    ) -> dict[str, object]: ...
```

Endpoint contract (all success bodies JSON):

| Method and path                                | Request                                                                   | Success                                                                                                                                                                                                                |
| ---------------------------------------------- | ------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /estates`                                 | query `limit?`, `offset?`                                                 | `200 {"items": [{"key", "name", "description", "last_import": {"commit_sha", "imported_at"} \| null}], "limit", "offset", "has_more", "next_offset"}`                                                                  |
| `POST /estates/{estate_key}/catalogue-import`  | query `dry_run?`; body `{"commit_sha", "estate_name"?, "catalogue_yaml"}` | `200 {"estate_key", "commit_sha", "state", "dry_run", "skipped", "skipped_reason", "registry_sync_required", "projects", "components", "repositories", "edges"}`, each count group `{"created", "updated", "deleted"}` |
| `POST /estates/{estate_key}/registry-sync`     | query `dry_run?`                                                          | `200 {"estate_key", "state", "dry_run", "repositories_created", "repositories_updated", "repositories_deactivated", "repositories_conflicted", "repositories_left_disabled", "repositories_left_disabled_count"}`      |
| `GET /estates/{estate_key}/repositories`       | query `ingestion_enabled?`, `limit?`, `offset?`                           | `200 {"estate_key", "items": [{"owner", "name", "default_branch", "ingestion_enabled", "documentation_paths"}], "limit", "offset", "has_more", "next_offset"}`                                                         |
| `PATCH /repositories/{owner}/{name}/ingestion` | body `{"ingestion_enabled": bool}`                                        | `200 {"owner", "name", "ingestion_enabled", "changed"}`                                                                                                                                                                |

Error contract:

| Endpoint              | Failure                                              | Status | `code`                   |
| --------------------- | ---------------------------------------------------- | ------ | ------------------------ |
| any non-health route  | token configured and missing or wrong                | 401    | `unauthorized`           |
| any                   | unroutable path (including keys containing `/`)      | 404    | `not_found`              |
| import                | key fails the creation pattern                       | 400    | `invalid_input`          |
| other estate routes   | key empty or longer than 64                          | 400    | `invalid_input`          |
| import, toggle        | not JSON, unknown, missing, null, or over-long field | 400    | `invalid_input`          |
| import, toggle        | unsupported media type                               | 415    | `unsupported_media_type` |
| import                | body over 1 MiB                                      | 413    | `payload_too_large`      |
| import                | YAML invalid, anchors or aliases, or schema failure  | 422    | `catalogue_invalid`      |
| sync, repository list | estate unknown                                       | 404    | `estate_not_found`       |
| list routes           | bad `limit`, `offset`, or `ingestion_enabled`        | 400    | `invalid_input`          |
| toggle                | repository unknown                                   | 404    | `repository_not_found`   |
| import, sync          | uniqueness conflict                                  | 409    | `conflict`               |
| any database route    | database unreachable                                 | 503    | `storage_unavailable`    |
| sync                  | other database failure                               | 500    | `registry_sync_failed`   |

## Revision note

- 2026-10-16: initial draft from Wyvern reconnaissance.
- 2026-10-16: revised after the expert-panel review (verdict: proceed with
  conditions). Changes: delivery split into three pull requests with
  per-request tolerances; port-owned error vocabulary and `domain_ports`
  placement for policy, models, errors, and ports; docstring-only package
  initializers; independent route-family predicates; cross-estate `CONFLICT`
  handling; corrected fail-closed claim; opt-in schema bootstrap and estate
  routes decoupled from reporting configuration (D13); optional bearer auth
  (D14); YAML anchor and alias rejection with threaded parsing; uniform
  `issues` shape and `code` on all errors including existing handlers and
  Falcon's own; paginated estate list with `next_offset`; strict booleans;
  `415`; request-body size semantics; timeout and route-miss CLI handling; dry
  runs (D20); estate rename fix (D18); concurrency and storage error mapping
  (D17); ADR-005 for D3; O1 re-targeted at the real sync code with an
  assertable transition counter; O2 made exhaustive; O3 corrected for Falcon's
  path decoding; new O5 (size agreement) and O6 (CLI import closure); a
  runner-owned event loop and a monkeypatched `httpx.Client` for the BDD
  harness; a hardened e2e fixture that strips `PYTEST_*` variables; expanded
  edge cases. Remaining work is unchanged in shape: approval, then EP-M1
  onwards.
