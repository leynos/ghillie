# Adopt femtologging for Ghillie logging

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`, and
`Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: COMPLETED

No PLANS.md exists in this repository.

## Purpose / Big Picture

Adopt the femtologging library in Ghillie using the specified repo snapshot so
that ingestion observability logs and application diagnostics continue to work
with async-friendly logging and exception support. Success is observable when
existing ingestion flows log the same events and errors as before, the new
pytest unit tests and pytest-bdd scenarios pass, and `make check-fmt`,
`make typecheck`, `make lint`, and `make test` succeed.

## Constraints

- Use femtologging from the snapshot commit:

    <git+https://github.com/leynos/femtologging@7c139fb7aca18f9277e00b88604b8bf5eb471be0>
- Preserve user-visible log schemas and ingestion observability event names
  unless the users guide and BDD tests are updated to match.
- Keep Python compatibility at `requires-python = ">=3.12"`.
- Add unit tests with pytest and behavioural tests with pytest-bdd before
  implementing code changes.
- Update documentation in `docs/` to reflect the migration, including the
  ADR, design documentation, and `docs/users-guide.md`.
- Follow the documentation style guide and 80-column wrapping rules.
- Run `make check-fmt`, `make typecheck`, `make lint`, and `make test` to
  gate every commit. For Markdown-only changes, also run `make markdownlint`
  and `make nixie`, plus `make fmt` after doc edits.

If any constraint cannot be met, stop and escalate.

## Tolerances (Exception Triggers)

- Scope: if changes require more than 25 files or 800 net LOC, stop and
  escalate.
- Interfaces: if public CLI options, configuration schema, or log event names
  must change, stop and escalate.
- Dependencies: if any new external dependency is required beyond
  femtologging, stop and escalate.
- Iterations: if tests still fail after two fix attempts, stop and escalate.
- Ambiguity: if femtologging's exception API in the snapshot is unclear,
  stop and confirm the intended usage before proceeding.

## Risks

- Risk: femtologging's snapshot API differs from the user guide, causing
  mismatched exception logging behaviour. Severity: medium Likelihood: medium
  Mitigation: inspect the installed snapshot API and add targeted unit tests
  for exception logging before refactoring production code.
- Risk: logging behaviour changes break pytest-bdd scenarios that assert
  observability event output. Severity: medium Likelihood: medium Mitigation:
  update BDD steps and users guide intentionally and keep log message formats
  stable where possible.
- Risk: async logging drops records under load, masking ingestion issues.
  Severity: low Likelihood: medium Mitigation: document drop counter usage and
  preserve existing warning logs.

## Progress

- [x] (2026-01-31 00:00Z) Draft ExecPlan in
  `docs/execplans/adopt-femtologging.md`.
- [x] (2026-01-31 00:00Z) ExecPlan approved; status updated to IN PROGRESS.
- [x] (2026-01-31 00:00Z) Review logging usage and entry points, then confirm
  femtologging exception API against the snapshot.
- [x] (2026-01-31 00:00Z) Add failing unit and BDD tests that describe the new
  logging behaviour and exception handling.
- [x] (2026-01-31 00:00Z) Implement femtologging adoption and configuration,
  update documentation, and pass all quality gates.
- [x] (2026-01-31 00:00Z) Validate quality gates: `make check-fmt`,
  `make typecheck`, `make lint`, `make test`, `make markdownlint`, and
  `make nixie`.

## Surprises & Discoveries

- Observation: femtologging's `handle_record` hook exposes structured
  `exc_info` and `stack_info` payloads in the record dict. Evidence: the
  snapshot's `record_to_dict` helper adds `exc_info` and `stack_info` keys when
  provided. Impact: tests can assert exception capture without stdlib `caplog`.
- Observation: femtologging normalizes warning levels to `WARN` in emitted
  records even when `WARNING` is passed. Impact: tests should assert `WARN` for
  warning-level log records.

## Decision Log

- Decision: Use the femtologging snapshot commit
  `7c139fb7aca18f9277e00b88604b8bf5eb471be0` as the dependency source.
  Rationale: required for internal dogfooding before release. Date/Author:
  2026-01-31, Codex.
- Decision: Introduce `ghillie/logging.py` to centralize log formatting,
  femtologging configuration, and exception logging helpers. Rationale: keeps
  call sites consistent and makes tests deterministic. Date/Author: 2026-01-31,
  Codex.
- Decision: Use a custom femtologging capture handler that implements
  `handle_record` for unit/BDD tests. Rationale: enables assertions on
  exception payloads without stdlib logging. Date/Author: 2026-01-31, Codex.

## Outcomes & Retrospective

- Adopted femtologging via the snapshot dependency and centralized logging
  helpers in `ghillie/logging.py` for formatting, configuration, and exception
  logging.
- Updated ingestion and runtime call sites plus tests to capture femtologging
  records, including structured exception payloads.
- Added unit and pytest-bdd coverage for failed ingestion logging and new
  helpers; all quality gates passed with existing pytest warning noise
  (pytest-bdd unknown marks and Python 3.13 deprecation warnings from
  `exc_info` usage).

## Context and Orientation

Ghillie currently uses stdlib `logging` in a small number of places. The ADR
`docs/adr-001-adoption-of-femtologging-library.md` lists these call sites and
notes that adoption was blocked by missing exception support. That limitation
is now resolved in the femtologging snapshot, so the ADR must be updated to
reflect the new status and the snapshot dependency.

The femtologging API and caveats are documented in
`docs/femtologging-users-guide.md`. Validate the guide against the snapshot API
and update the guide if it is now outdated on exception support.

Behavioral tests live in `tests/features/*.feature` with step definitions in
`tests/features/steps/*.py`. The ingestion observability feature file
`tests/features/github_ingestion_observability.feature` and steps in
`tests/features/steps/test_github_observability_steps.py` are the most likely
places to extend with new logging expectations.

Unit tests live under `tests/unit/`. Identify existing logging helpers or
configuration modules (search with `grepai search "logging" --json --compact`)
and decide whether to add a small `ghillie/logging.py` wrapper to centralize
femtologging usage and make it testable.

Consult the following design and testing references for configuration and
behavioural expectations:

- `docs/ghillie-design.md`
- `docs/ghillie-proposal.md`
- `docs/ghillie-bronze-silver-architecture-design.md`
- `docs/async-sqlalchemy-with-pg-and-falcon.md`
- `docs/testing-async-falcon-endpoints.md`
- `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`

## Plan of Work

Stage A: Baseline discovery and alignment (no code changes).

Review the ADR, the femtologging user guide, and current logging call sites.
Use `grepai search "logger.warning"` and `grepai search "logger.exception"` to
find all relevant usage. Identify application entry points (CLI, worker, web)
where logging configuration is set or should be added. Confirm the snapshot API
supports exception logging, and capture the exact usage pattern (e.g.,
`logger.exception(...)` or `logger.log("ERROR", ..., exc_info=exc)`). If the
API differs from the guide, note the difference for documentation updates and
test design.

Stage B: Tests-first updates.

Create or update unit tests that exercise the new logging wrapper or helper
functions. At minimum, add a unit test that verifies exception logging includes
exception details in the emitted message or structured payload. Add a
pytest-bdd scenario (likely in `github_ingestion_observability.feature`) that
asserts ingestion errors log the correct event name and include exception
context. Run the relevant tests and confirm they fail before code changes.

Stage C: Implement femtologging adoption.

Add the femtologging dependency to `pyproject.toml` using the snapshot URL and
regenerate `uv.lock`. Replace stdlib logging imports in the identified call
sites with femtologging usage, keeping log level names and messages stable.
Centralize configuration in a dedicated module if one does not exist, and
initialize femtologging in the main runtime entry points (worker, CLI, and any
API service startup). Ensure exception logging uses the snapshot-supported API
and that warning logs remain unchanged. Update unit and BDD tests to pass.

Stage D: Documentation, cleanup, and validation.

Update `docs/adr-001-adoption-of-femtologging-library.md` to note that
exception support is now available and that adoption uses the snapshot commit.
Update the design documentation (start with the observability section in
`docs/ghillie-design.md` or
`docs/ghillie-bronze-silver-architecture-design.md`) to record the logging
library choice. Update `docs/users-guide.md` to describe any user-visible
logging behaviour changes. If the femtologging user guide is outdated on
exception support, update it. Run `make fmt`, then `make markdownlint` and
`make nixie`, followed by `make check-fmt`, `make typecheck`, `make lint`, and
`make test` until all pass. Commit each logical change with gated checks as
required.

## Concrete Steps

1. Inspect logging usage and entry points.

   - `grepai search "logger." --json --compact`
   - `grepai search "logging.getLogger" --json --compact`
   - `grepai search "get_logger" --json --compact`

2. Confirm femtologging snapshot API.

   - Update dependency locally, then inspect in a Python REPL or read the
     installed module docstrings to confirm how exception logging works.

3. Add tests (expected to fail initially).

   - Create/extend unit tests under `tests/unit/` for the logging wrapper or
     helper that handles exception logging.
   - Add/extend a pytest-bdd scenario under
     `tests/features/github_ingestion_observability.feature` with matching
     steps in `tests/features/steps/test_github_observability_steps.py`.

4. Implement femtologging adoption and configuration.

   - Update `pyproject.toml` with the snapshot dependency.
   - Regenerate `uv.lock` using `uv lock` or the project’s documented workflow.
   - Replace stdlib logging usage in
     `ghillie/silver/services.py`, `ghillie/github/ingestion.py`, and
     `tests/conftest.py` using the snapshot API.
   - Configure femtologging in the runtime entry points (locate via grepai).

5. Update documentation.

   - Update the ADR to reflect exception support and new status.
   - Record the design decision in the relevant design doc section.
   - Update `docs/users-guide.md` for end-user behaviour.
   - Update `docs/femtologging-users-guide.md` if it now mismatches reality.

6. Run quality gates with logged output.

   - `make fmt | tee /tmp/fmt-$(get-project)-$(git branch --show).out`
   - `LOG=/tmp/markdownlint-$(get-project)-$(git branch --show).out`
     `make markdownlint | tee "$LOG"`
   - `LOG=/tmp/nixie-$(get-project)-$(git branch --show).out`
     `make nixie | tee "$LOG"`
   - `LOG=/tmp/check-fmt-$(get-project)-$(git branch --show).out`
     `make check-fmt | tee "$LOG"`
   - `LOG=/tmp/typecheck-$(get-project)-$(git branch --show).out`
     `make typecheck | tee "$LOG"`
   - `LOG=/tmp/lint-$(get-project)-$(git branch --show).out`
     `make lint | tee "$LOG"`
   - `LOG=/tmp/test-$(get-project)-$(git branch --show).out`
     `make test | tee "$LOG"`

## Validation and Acceptance

- Unit tests: new pytest tests for logging and exception handling pass, and
  they fail before implementation.
- Behavioural tests: new pytest-bdd scenario passes and demonstrates that
  ingestion observability logs include the expected event name and exception
  details.
- Documentation: ADR updated to note exception support and the snapshot
  dependency; users guide updated to reflect log behaviour.
- Quality gates: `make check-fmt`, `make typecheck`, `make lint`, and
  `make test` all pass; for Markdown changes, `make markdownlint` and
  `make nixie` pass as well.

## Idempotence and Recovery

Steps are re-runnable. If a stage fails, revert the affected files with
`git restore` and re-apply the change, or amend the failing test expectations
before retrying. Re-running `uv lock`, `make fmt`, and the make-based quality
gates is safe and should converge on a clean state.

## Artifacts and Notes

Expected log shape (update if the snapshot emits a different format):

    INFO ghillie.github.observability [ingestion.run.completed] repo=…
    count=…

## Interfaces and Dependencies

- Dependency: add `femtologging` from the snapshot commit in
  `pyproject.toml`, and update `uv.lock` accordingly.
- Logging wrapper (if introduced): define a small module (for example
  `ghillie/logging.py`) that exposes `get_logger(name: str)` and an
  `log_exception(logger, message: str, exc: BaseException)` helper so call
  sites stay consistent and tests have a stable seam.
- Entry points: ensure femtologging initialization happens once in each
  runtime entry path (worker, CLI, API), and document the location.

## Revision note (2026-01-31)

Updated progress to reflect completed discovery and test scaffolding, and
captured femtologging record payload behaviour plus key design decisions. The
remaining work is focused on finishing the migration, updating documentation,
and passing quality gates.
