# Define report Markdown and storage

This execution plan (ExecPlan) is a living document. The sections `Progress`,
`Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must
be kept up to date as work proceeds.

## Purpose / big picture

Task 2.3.b defines a Markdown format for repository reports and implements a
storage mechanism, so operators can navigate to a repository's latest report via
a predictable file path. This bridges the gap between Gold layer database
storage (already implemented in 2.3.a) and human-readable report output.

The Markdown renderer reads from `Report.machine_summary` (the structured JSON
data) plus repository metadata and produces a well-structured Markdown
document. A `ReportSink` protocol (port) enables pluggable storage backends,
with a filesystem adapter as the initial implementation.

Success is observable when:

1. A Markdown renderer converts `Report` + repository metadata into a
   structured Markdown document
2. A `ReportSink` protocol (port) defines the storage interface following
   hexagonal architecture
3. A filesystem adapter writes reports to
   `{base_path}/{owner}/{name}/latest.md` and
   `{base_path}/{owner}/{name}/{date}-{report_id}.md`
4. `ReportingService` optionally invokes the sink after generating a report
   (backwards-compatible)
5. Configuration via `GHILLIE_REPORT_SINK_PATH` controls the base directory
6. The rendered Markdown content matches the data stored in the database

## Progress

- [x] Write unit tests for Markdown renderer
- [x] Write unit tests for `ReportingConfig` extension
- [x] Write unit tests for filesystem sink adapter
- [x] Write unit tests for `ReportingService` sink integration
- [x] Write Behaviour-Driven Development (BDD) feature and step definitions
- [x] Implement `ReportingConfig` extension (`report_sink_path`)
- [x] Implement Markdown renderer module
- [x] Implement `ReportSink` protocol
- [x] Implement filesystem sink adapter
- [x] Integrate sink into `ReportingService`
- [x] Integrate sink creation into Dramatiq actors
- [x] Update `ghillie/reporting/__init__.py` exports
- [x] Update `docs/users-guide.md` with usage documentation
- [x] Update `docs/ghillie-design.md` with design section
- [x] Mark Task 2.3.b as done in `docs/roadmap.md`
- [x] All quality gates passed (check-fmt, typecheck, lint, markdownlint,
  test, nixie)

## Surprises and discoveries

1. **Python 3.14 incompatibility:** `uv` selected Python 3.14 by default,
   which is incompatible with granian (pyo3 build failure). Fixed by explicitly
   specifying `--python 3.12` for `uv venv` and `uv sync`.

2. **Lint strictness:** The project configures `max-args = 4` for
   `PLR0913`, which triggered on several new functions that necessarily have
   more than four parameters (Protocol methods, constructors with dependency
   injection). Addressed with targeted `# noqa: PLR0913` annotations.

3. **`PERF401` preference:** Ruff prefers `lines.extend(generator)` over
   `for item in list: lines.append(f"- {item}")`. Refactored the renderer to
   use `extend()` with generator expressions.

4. **`S101` in production code:** `assert` statements in production code
   are flagged by ruff. Replaced with defensive `if \u2026 return` guards in
   `_write_to_sink()`.

## Decision log

1. **Markdown renderer location:** `ghillie/reporting/markdown.py` --
   co-located with reporting service per "group by feature, not layer"
   principle.

2. **ReportSink protocol location:** `ghillie/reporting/sink.py` -- the
   protocol is a port specific to reporting, not a general infrastructure
   concern.

3. **Filesystem adapter location:** `ghillie/reporting/filesystem_sink.py`
   -- adapter implements the port, same package.

4. **Optional sink dependency:** `ReportSink` is injected via an optional
   constructor parameter on `ReportingService`. When `None`, no Markdown is
   written. This preserves backwards compatibility.

5. **Renderer reads from `machine_summary`, not `human_text`:** The
   `machine_summary` is the structured data produced by `to_machine_summary()`
   from the `RepositoryStatusResult`. By rendering from this structured data,
   the Markdown content is guaranteed to match the database exactly, satisfying
   the completion criteria. The `human_text` field remains untouched and
   continues to store the raw LLM summary string.

6. **Synchronous filesystem I/O via `asyncio.to_thread`:** The
   `ReportSink.write_report` method is `async` because future adapters (S3, Git
   push) will require async I/O. The filesystem adapter uses
   `asyncio.to_thread()` for the actual write, avoiding blocking the event loop
   without introducing an `aiofiles` dependency.

7. **Date format in paths:** Use ISO date `YYYY-MM-DD` derived from
   `report.window_end` for the dated report file, providing chronological sort
   order.

8. **Config extension over new config class:** Add `report_sink_path` to
   existing `ReportingConfig` rather than creating a separate config class,
   since the config is small and the sink is an integral part of reporting.

## Outcomes and retrospective

All implementation tasks are complete and all quality gates pass.

**Test counts:**

- 9 unit tests for Markdown renderer
  (`tests/unit/test_reporting_markdown.py`)
- 6 unit tests for filesystem sink
  (`tests/unit/test_filesystem_sink.py`)
- 6 new tests across `tests/unit/test_reporting_config.py` and
  `tests/unit/test_reporting_sink_integration.py` (3 config, 3 sink integration)
- 2 BDD scenarios in `tests/features/report_markdown.feature`
- Full suite: 558 passed, 35 skipped (pre-existing helm/integration/LLM
  skips)

**Quality gates:**

- `make check-fmt`: 172 files already formatted
- `make typecheck`: All checks passed (ty 0.0.15)
- `make lint`: All checks passed
- `make markdownlint`: 0 errors
- `make nixie`: All diagrams validated
- `make test`: 558 passed, 35 skipped

**What went well:**

- The hexagonal architecture (ReportSink protocol) kept the service layer
  clean and testable.
- Test-first approach caught several design issues early (for example, the
  need for `asyncio.to_thread()` wrapper).
- The pure function approach for the Markdown renderer made unit testing
  straightforward.

**What could be improved:**

- The `PLR0913` rule (`max-args = 4`) conflicts with dependency injection
  patterns used throughout the codebase. A project-wide discussion about
  adjusting this threshold may be warranted.

## Context and orientation

### Existing structures

The reporting module (`ghillie/reporting/`) already provides:

- **`ReportingService`** (`ghillie/reporting/service.py`): Orchestrates
  evidence bundle construction, status model invocation, and report
  persistence. Constructor takes `session_factory`, `evidence_service`,
  `status_model`, and optional `config`.
- **`ReportingConfig`** (`ghillie/reporting/config.py`): Frozen dataclass
  with `window_days` and `from_env()` classmethod reading
  `GHILLIE_REPORTING_WINDOW_DAYS`.
- **`Report`** (`ghillie/gold/storage.py`): SQLAlchemy model with
  `human_text`, `machine_summary`, `repository_id`, `window_start`,
  `window_end`, `generated_at`, `model`.
- **`Report.machine_summary`**: A `dict[str, Any]` with keys `status`,
  `summary`, `highlights` (list), `risks` (list), `next_steps` (list) --
  produced by `to_machine_summary()`.
- **`Repository`** (`ghillie/silver/storage.py`): SQLAlchemy model with
  `github_owner`, `github_name`.
- **Dramatiq actors** (`ghillie/reporting/actor.py`): `_build_service()`
  constructs a `ReportingService` for each actor invocation.

### Key patterns to follow

1. **Configuration dataclass**: `@dataclasses.dataclass(frozen=True,
   slots=True)` with `from_env()` classmethod (see `ghillie/reporting/config.py
   `, `ghillie/status/config.py`).
2. **Protocol ports**: `@typ.runtime_checkable` Protocol classes (see
   `ghillie/status/protocol.py`).
3. **Constructor injection**: Optional parameters with `None` defaults
   (see `ReportingService.__init__` for `config`).
4. **Import conventions**: `from __future__ import annotations`,
   `typing as typ`, `datetime as dt`, `collections.abc as cabc`.
5. **Docstrings**: NumPy-style with Parameters/Returns/Raises sections.
6. **`__all__` exports**: Explicit in package `__init__.py`.
7. **Test-first**: Write failing tests before implementation per AGENTS.md.
8. **BDD + unit**: Both pytest-bdd scenarios and unit tests required for
   new features.

### Files to reference

- `ghillie/reporting/service.py` -- Service to modify with sink integration
- `ghillie/reporting/config.py` -- Config to extend with sink path
- `ghillie/reporting/actor.py` -- Actors to pass sink to service
- `ghillie/reporting/__init__.py` -- Package exports to update
- `ghillie/status/protocol.py` -- Protocol pattern to follow
- `ghillie/gold/storage.py` -- Report model
- `ghillie/silver/storage.py` -- Repository model
- `ghillie/status/models.py` -- `to_machine_summary()` for understanding
  machine_summary structure
- `ghillie/evidence/models.py` -- `ReportStatus` enum
- `tests/unit/test_reporting_config.py` -- Config unit tests
- `tests/unit/test_reporting_sink_integration.py` -- Sink integration tests
- `tests/features/reporting_workflow.feature` -- Existing BDD to reference
- `tests/features/steps/test_reporting_workflow_steps.py` -- BDD step
  pattern

## Plan of work

### Phase 1: Write failing tests first (AGENTS.md requirement)

Create all test files before any implementation:

#### 1a. Unit tests for Markdown renderer

File: `tests/unit/test_reporting_markdown.py`

Test the `render_report_markdown()` function in isolation:

- `test_render_includes_title_with_repo_and_dates` -- The Markdown title
  line contains `owner/name` and the window date range.
- `test_render_includes_status_indicator` -- The status section shows the
  correct status value.
- `test_render_includes_summary_section` -- The summary section contains
  the text from `machine_summary["summary"]`.
- `test_render_includes_highlights_as_bullets` -- Each highlight appears as
  a bullet point under a "Highlights" heading.
- `test_render_includes_risks_as_bullets` -- Each risk appears as a bullet
  point under a "Risks" heading.
- `test_render_includes_next_steps_as_bullets` -- Each next step appears as
  a bullet point under a "Next steps" heading.
- `test_render_includes_metadata_footer` -- Footer includes model
  identifier, generated_at timestamp, and window range.
- `test_render_omits_empty_sections` -- When highlights/risks/next_steps
  are empty lists, their headings are omitted.
- `test_render_handles_missing_machine_summary_keys_gracefully` -- If a key
  is missing from machine_summary, the section is omitted rather than raising.

#### 1b. Unit tests for ReportingConfig extension

Add tests in `tests/unit/test_reporting_config.py` within the
`TestReportingConfig` class:

- `test_config_report_sink_path_defaults_to_none` -- The new
  `report_sink_path` field defaults to `None`.
- `test_config_from_env_reads_report_sink_path` --
  `GHILLIE_REPORT_SINK_PATH` is read and stored as a `Path`.
- `test_config_from_env_report_sink_path_unset_yields_none` -- When the env
  var is unset, `report_sink_path` is `None`.

#### 1c. Unit tests for filesystem sink

File: `tests/unit/test_filesystem_sink.py`

- `test_write_creates_owner_name_directory` -- The sink creates
  `{base_path}/{owner}/{name}/` directory if it does not exist.
- `test_write_creates_latest_md` -- A file `latest.md` is written at the
  expected path.
- `test_write_creates_dated_report` -- A dated file is written alongside
  `latest.md`.
- `test_latest_md_content_matches_rendered_markdown` -- The content of
  `latest.md` matches the Markdown string passed in.
- `test_write_overwrites_existing_latest` -- Writing a new report replaces
  the existing `latest.md`.
- `test_dated_reports_accumulate` -- Multiple writes produce multiple dated
  files without overwriting.

#### 1d. Unit tests for ReportingService sink integration

Add `TestReportingServiceSinkIntegration` class in
`tests/unit/test_reporting_sink_integration.py`:

- `test_generate_report_calls_sink_when_provided` -- When a `ReportSink` is
  injected, `write_report` is called after report generation.
- `test_generate_report_works_without_sink` -- When no sink is provided
  (default), report generation succeeds without error.
- `test_run_for_repository_calls_sink_when_provided` -- The full workflow
  method also invokes the sink.

#### 1e. BDD feature

File: `tests/features/report_markdown.feature`

```gherkin
Feature: Report Markdown rendering and storage

  Rendered Markdown reports allow operators to navigate to a
  repository's latest report via a predictable file path.

  Scenario: Render and store a repository report as Markdown
    Given a repository with events and a filesystem sink
    When I generate a report with the sink
    Then a latest.md file exists at the predictable path
    And the Markdown content includes the repository name
    And the Markdown content includes the status summary
    And a dated report file also exists

  Scenario: Report generation works without a sink
    Given a repository with events but no sink
    When I generate a report without a sink
    Then a Gold report is created successfully
    And no Markdown files are written
```

File: `tests/features/steps/test_report_markdown_steps.py` -- step definitions
following the pattern in
`tests/features/steps/test_reporting_workflow_steps.py`.

### Phase 2: Implement configuration extension

Modify: `ghillie/reporting/config.py`

Add `report_sink_path: Path | None = None` field to `ReportingConfig`. Update
`from_env()` to read `GHILLIE_REPORT_SINK_PATH`:

```python
report_sink_path: Path | None = None

@classmethod
def from_env(cls) -> ReportingConfig:
    # ... existing window_days parsing ...
    raw_sink_path = os.environ.get("GHILLIE_REPORT_SINK_PATH", "")
    report_sink_path: Path | None = None
    if raw_sink_path.strip():
        from pathlib import Path as P
        report_sink_path = P(raw_sink_path.strip())
    return cls(
        window_days=window_days,
        report_sink_path=report_sink_path,
    )
```

### Phase 3: Implement Markdown renderer

Create: `ghillie/reporting/markdown.py`

A pure function `render_report_markdown()` that takes a `Report` plus `owner`
and `name` keyword arguments and returns a Markdown string. No I/O, no database
access.

The rendered document follows this structure:

```markdown
# {owner}/{name} -- Status report ({window_start} to {window_end})

**Status:** {On Track | At Risk | Blocked | Unknown}

## Summary

{machine_summary.summary}

## Highlights

- {highlight 1}
- {highlight 2}

## Risks

- {risk 1}
- {risk 2}

## Next steps

- {step 1}
- {step 2}

---

*Generated at {generated_at} by {model} | Window: {window_start}
to {window_end} | Report ID: {report_id}*
```

Rules:

- Sections with empty lists are omitted entirely.
- Dates are formatted as `YYYY-MM-DD`.
- The metadata footer uses Markdown emphasis for visual separation.

### Phase 4: Implement ReportSink protocol

Create: `ghillie/reporting/sink.py`

Define `ReportSink` as a `@typ.runtime_checkable` Protocol with a single async
method `write_report()`. Parameters: `markdown` (str) and a keyword-only
`metadata` parameter of type `ReportMetadata` (a frozen dataclass grouping
`owner`, `name`, `report_id`, and `window_end`).

### Phase 5: Implement filesystem sink adapter

Create: `ghillie/reporting/filesystem_sink.py`

`FilesystemReportSink` constructor accepts a `Path` base directory. The
`write_report()` method:

1. Constructs `{base_path}/{owner}/{name}/` directory
2. Creates it with `parents=True, exist_ok=True` via
   `asyncio.to_thread()`
3. Writes `latest.md` (overwritten each time)
4. Writes `{window_end}-{report_id}.md` (accumulates)

### Phase 6: Integrate sink into ReportingService

Modify: `ghillie/reporting/service.py`

1. Add `report_sink: ReportSink | None = None` to `__init__()`.
2. After `generate_report()` persists the report, call a new private method
   `_write_to_sink()`.
3. `_write_to_sink()` fetches the `Repository` record (for
   `github_owner`/`github_name`), calls `render_report_markdown()`, then calls
   `self._report_sink.write_report()`.

### Phase 7: Wire sink into Dramatiq actors

Modify: `ghillie/reporting/actor.py`

Update `_build_service()` to create a `FilesystemReportSink` when
`ReportingConfig.report_sink_path` is set:

```python
report_sink: ReportSink | None = None
if config.report_sink_path is not None:
    from ghillie.reporting.filesystem_sink import FilesystemReportSink
    report_sink = FilesystemReportSink(config.report_sink_path)
```

### Phase 8: Update package exports and documentation

- Update `ghillie/reporting/__init__.py` with new exports:
  `render_report_markdown`, `ReportSink`, `FilesystemReportSink`.
- Add "Report Markdown and storage (Phase 2.3.b)" section to
  `docs/users-guide.md`.
- Add design section to `docs/ghillie-design.md`.
- Mark Task 2.3.b as done in `docs/roadmap.md`.

## Concrete steps

1. Create `tests/unit/test_reporting_markdown.py` with 9 failing tests for
   the Markdown renderer (see Phase 1a).

2. Create `tests/unit/test_reporting_config.py` with 3 config tests and
   `tests/unit/test_reporting_sink_integration.py` with 3 sink integration
   tests (see Phase 1b and 1d).

3. Create `tests/unit/test_filesystem_sink.py` with 6 failing tests (see
   Phase 1c).

4. Create `tests/features/report_markdown.feature` with 2 BDD scenarios
   (see Phase 1e).

5. Create `tests/features/steps/test_report_markdown_steps.py` with step
   definitions following the `test_reporting_workflow_steps.py` pattern.

6. Modify `ghillie/reporting/config.py`: Add
   `report_sink_path: Path | None = None` field and update `from_env()` to read
   `GHILLIE_REPORT_SINK_PATH`.

7. Create `ghillie/reporting/markdown.py`: Implement
   `render_report_markdown()` pure function.

8. Create `ghillie/reporting/sink.py`: Define `ReportSink` protocol with
   `@runtime_checkable`.

9. Create `ghillie/reporting/filesystem_sink.py`: Implement
   `FilesystemReportSink` using `asyncio.to_thread()`.

10. Modify `ghillie/reporting/service.py`: Add optional `report_sink`
    parameter to `ReportingService.__init__()`, add `_write_to_sink()`
    private method, call it after report persistence in
    `generate_report()`.

11. Modify `ghillie/reporting/actor.py`: Update `_build_service()` to
    create `FilesystemReportSink` when `report_sink_path` is configured.

12. Modify `ghillie/reporting/__init__.py`: Add new exports.

13. Update `docs/users-guide.md`: Add "Report Markdown and storage
    (Phase 2.3.b)" section.

14. Update `docs/ghillie-design.md`: Add design section for Markdown
    rendering and storage.

15. Update `docs/roadmap.md`: Mark Task 2.3.b as done with implementation
    note.

16. Run quality gates:

    ```bash
    set -o pipefail; make check-fmt 2>&1 | tee /tmp/ghillie-check-fmt.log
    set -o pipefail; make typecheck 2>&1 | tee /tmp/ghillie-typecheck.log
    set -o pipefail; make lint 2>&1 | tee /tmp/ghillie-lint.log
    set -o pipefail; make test 2>&1 | tee /tmp/ghillie-test.log
    set -o pipefail; make markdownlint 2>&1 | tee /tmp/ghillie-mdlint.log
    set -o pipefail; make nixie 2>&1 | tee /tmp/ghillie-nixie.log
    ```

## Validation and acceptance

The change is accepted when:

1. `render_report_markdown()` produces valid Markdown matching the database
   `machine_summary` content
2. `ReportSink` protocol is `@runtime_checkable` and
   `FilesystemReportSink` passes `isinstance` check
3. `FilesystemReportSink` writes `latest.md` and dated reports to
   predictable paths
4. `ReportingService` works unchanged when no sink is provided
   (backwards-compatible)
5. `ReportingService` renders and writes Markdown when a sink is injected
6. `GHILLIE_REPORT_SINK_PATH` env var controls filesystem sink creation in
   actors
7. Users' guide documents the new configuration and path structure
8. Design document records the architectural decisions
9. Roadmap marks Task 2.3.b as complete
10. All quality gates pass: `make check-fmt`, `make typecheck`,
    `make lint`, `make test`, `make markdownlint`, `make nixie`

Expected test output:

```text
$ pytest tests/unit/test_reporting_markdown.py -v
~9 passed

$ pytest tests/unit/test_filesystem_sink.py -v
~6 passed

$ pytest tests/unit/test_reporting_config.py tests/unit/test_reporting_sink_integration.py -v
~6 passed

$ pytest tests/features -k report_markdown
~2 passed
```

## Idempotence and recovery

All steps are safe to rerun:

- File creation is additive (new modules)
- File modification extends existing code with new optional parameters
- Tests can be run incrementally
- Quality gates are read-only validations

If tests fail:

1. Check that `tmp_path` fixture is available for filesystem sink tests
2. Verify `session_factory` fixture provides a database with `Repository`
   table populated
3. Ensure `machine_summary` dict keys match expected structure
4. Check for path separator issues on the test platform

## Artefacts and notes

### Key design decisions

1. **Renderer operates on `machine_summary`, not `human_text`:** The
   `machine_summary` is the structured data that was produced by
   `to_machine_summary()` from the `RepositoryStatusResult`. By rendering from
   this structured data, we guarantee the Markdown content matches the database
   exactly, satisfying the completion criteria. The existing `human_text` field
   on `Report` continues to store the raw LLM summary string.

2. **No schema migration required:** This change adds no database columns.
   It only adds application-level Markdown rendering and filesystem output.

3. **`asyncio.to_thread()` over `aiofiles`:** The filesystem adapter uses
   `asyncio.to_thread()` for non-blocking I/O. This avoids adding `aiofiles` as
   a dependency while keeping the event loop responsive. For the small Markdown
   files involved, this approach is efficient.

### Future extensibility

The `ReportSink` protocol supports future adapters:

- S3/object storage adapter (Phase 5+)
- Git repository adapter (push to a dedicated status repo)
- Notification adapters (compose Markdown for Slack/email)

### Markdown template specification

The rendered Markdown document follows this structure:

```markdown
# {owner}/{name} -- Status report ({YYYY-MM-DD} to {YYYY-MM-DD})

**Status:** {On Track | At Risk | Blocked | Unknown}

## Summary

{summary text from machine_summary}

## Highlights

- {highlight 1}
- {highlight 2}

## Risks

- {risk 1}
- {risk 2}

## Next steps

- {step 1}
- {step 2}

---

*Generated at {YYYY-MM-DD HH:MM UTC} by {model} | Window:
{YYYY-MM-DD} to {YYYY-MM-DD} | Report ID: {uuid}*
```

Sections with empty lists are omitted. Missing `machine_summary` keys are
handled gracefully (section omitted, no exception raised).

## Interfaces and dependencies

### New public API

- `ghillie.reporting.render_report_markdown` -- Markdown renderer function
- `ghillie.reporting.ReportSink` -- Protocol for report storage backends
- `ghillie.reporting.FilesystemReportSink` -- Filesystem adapter

### Modified public API

- `ghillie.reporting.ReportingConfig` -- New optional `report_sink_path`
  field
- `ghillie.reporting.ReportingService` -- New optional `report_sink`
  constructor parameter

### Environment variables

- `GHILLIE_REPORT_SINK_PATH` -- Optional filesystem path for report
  storage

### External dependencies

None new. Uses only stdlib (`asyncio.to_thread`, `pathlib`).

### Downstream consumers

Task 2.3.c (on-demand reporting) will use the same sink infrastructure.

## Critical files

| File                                                 | Action | Purpose                        |
| ---------------------------------------------------- | ------ | ------------------------------ |
| `ghillie/reporting/markdown.py`                      | Create | Markdown renderer function     |
| `ghillie/reporting/sink.py`                          | Create | ReportSink protocol definition |
| `ghillie/reporting/filesystem_sink.py`               | Create | Filesystem adapter             |
| `ghillie/reporting/service.py`                       | Modify | Optional sink integration      |
| `ghillie/reporting/config.py`                        | Modify | Add report_sink_path config    |
| `ghillie/reporting/actor.py`                         | Modify | Wire sink into service builder |
| `ghillie/reporting/__init__.py`                      | Modify | Export new public API          |
| `tests/unit/test_reporting_markdown.py`              | Create | Renderer unit tests            |
| `tests/unit/test_filesystem_sink.py`                 | Create | Sink adapter unit tests        |
| `tests/unit/test_reporting_config.py`                | Create | Config unit tests              |
| `tests/unit/test_reporting_sink_integration.py`      | Create | Sink integration tests         |
| `tests/features/report_markdown.feature`             | Create | BDD scenarios                  |
| `tests/features/steps/test_report_markdown_steps.py` | Create | BDD step definitions           |
| `docs/users-guide.md`                                | Modify | Usage documentation            |
| `docs/ghillie-design.md`                             | Modify | Design section                 |
| `docs/roadmap.md`                                    | Modify | Mark task complete             |
