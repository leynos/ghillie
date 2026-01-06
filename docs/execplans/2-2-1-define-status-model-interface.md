# Define status model interface

This execution plan (ExecPlan) is a living document. The sections `Progress`,
`Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must
be kept up to date as work proceeds.

## Purpose / Big Picture

This task introduces the abstraction layer for LLM-backed summarization in
Ghillie. The `StatusModel` protocol defines how evidence bundles are
transformed into structured status reports with summary text, status codes,
highlights, risks, and next steps. Success is observable when at least one
implementation (a mock that returns deterministic responses) is available with
tests that mock model responses. The design aligns with the proposal in
`docs/ghillie-proposal.md` Section 9 and extends the evidence bundle
architecture documented in `docs/ghillie-design.md` Section 9.

## Progress

- [x] Created unit tests for status model (14 tests)
- [x] Created BDD tests for status model (3 scenarios)
- [x] Implemented `ghillie/status/models.py` with `RepositoryStatusResult`
- [x] Implemented `ghillie/status/protocol.py` with `StatusModel` protocol
- [x] Implemented `ghillie/status/mock.py` with `MockStatusModel`
- [x] Created `ghillie/status/__init__.py` with public exports
- [x] Added Section 9.4 to `docs/ghillie-design.md`
- [x] Marked Task 2.2.a as done in `docs/roadmap.md`
- [x] All quality gates passed (check-fmt, typecheck, lint, test, nixie)

## Surprises & Discoveries

1. **ReportStatus enum reuse:** The `ReportStatus` enum was already defined in
   `ghillie/evidence/models.py`, so we reused it rather than duplicating.

2. **Lint rules:** The codebase uses strict linting with `ruff` that requires:
   - `dt.UTC` instead of `dt.timezone.utc`
   - `typ.TypedDict` instead of `from typing import TypedDict`
   - `list.extend()` instead of loops with `append()`
   - `# noqa: TC001` for runtime-required type imports

3. **Test fixtures pattern:** BDD tests use `typ.TypedDict` for context sharing
   between steps, with `asyncio.run()` wrappers for async operations.

## Decision Log

1. **Reuse ReportStatus:** Decided to reuse the existing `ReportStatus` enum
   from `ghillie.evidence.models` rather than creating a duplicate in the
   status package. This maintains single source of truth for status codes.

2. **Async protocol methods:** Made `summarize_repository` async even though
   the mock implementation is synchronous, to support future LLM API calls.

3. **Runtime checkable protocol:** Used `@runtime_checkable` decorator to
   support `isinstance` checks for dependency injection patterns.

4. **Heuristic priority order:** Mock status determination follows priority:
   empty → UNKNOWN, previous risks → AT_RISK, bugs > features → AT_RISK,
   otherwise → ON_TRACK.

## Outcomes & Retrospective

**What went well:**

- Clean implementation following existing codebase patterns
- All 308 tests pass including 14 new tests for status model
- Design documentation integrated smoothly into existing Section 9

**What could be improved:**

- Consider adding more edge case tests for the mock heuristics
- Future work could add project/estate summarization methods

**Artifacts created:**

- `ghillie/status/__init__.py`, `models.py`, `protocol.py`, `mock.py`
- `tests/unit/test_status_model.py` (14 tests)
- `tests/features/status_model.feature` (3 scenarios)
- `tests/features/steps/test_status_model_steps.py`

## Context and Orientation

### Existing Structures

The evidence bundle architecture is complete:

- **Evidence models** (`ghillie/evidence/models.py`):
  `RepositoryEvidenceBundle`,
  `ReportStatus` enum (ON_TRACK, AT_RISK, BLOCKED, UNKNOWN), `WorkType` enum,
  and all evidence structs use `msgspec.Struct` with `kw_only=True, frozen=True`
- **Gold layer** (`ghillie/gold/storage.py`): `Report` SQLAlchemy model with
  `machine_summary` JSON column ready to store structured output
- **Proposal pattern** (`docs/ghillie-proposal.md` Section 9): Specifies
  `StatusModel(Protocol)` with methods for repo/project/estate summarization

### Key Patterns to Follow

1. **msgspec Structs**: All output models must use `msgspec.Struct` with
   `kw_only=True, frozen=True` for immutability and JSON serialization
2. **Tuples over lists**: Use `tuple[T, ...]` for immutable collections
3. **Async methods**: All service methods are async (matching
   `EvidenceBundleService` pattern)
4. **Protocol with runtime_checkable**: Use `typing.Protocol` for interface
   definition
5. **Comprehensive docstrings**: Include Attributes sections in NumPy format

### Files to Reference

- `ghillie/evidence/models.py` - Struct patterns, `ReportStatus` enum
- `ghillie/evidence/service.py` - Service class pattern with session factory
- `ghillie/evidence/__init__.py` - Export pattern
- `tests/unit/test_evidence_service.py` - Unit test patterns
- `tests/features/evidence_bundle.feature` - BDD scenario patterns
- `tests/features/steps/test_evidence_bundle_steps.py` - Step definition
  patterns

## Plan of Work

### Phase 1: Write failing tests first (AGENTS.md requirement)

Create unit tests and BDD scenarios before implementation:

- Unit tests in `tests/unit/test_status_model.py` covering struct creation,
  protocol compliance, and mock heuristics
- BDD feature in `tests/features/status_model.feature` with scenarios for
  normal activity, at-risk status, and no activity

### Phase 2: Define output structures

Create `RepositoryStatusResult` msgspec.Struct in `ghillie/status/models.py`
with fields: summary (str), status (ReportStatus), highlights (tuple[str,
…]), risks (tuple[str, …]), next_steps (tuple[str, …]). Include a
`to_machine_summary()` helper for JSON conversion.

### Phase 3: Define the protocol

Create `StatusModel` protocol in `ghillie/status/protocol.py` with async
`summarize_repository(evidence: RepositoryEvidenceBundle) -> RepositoryStatusResult`
 method. Use `@runtime_checkable` decorator.

### Phase 4: Implement MockStatusModel

Create `MockStatusModel` in `ghillie/status/mock.py` with deterministic
heuristics:

- Empty evidence → UNKNOWN
- Previous risks carried forward → AT_RISK
- Bug activity > feature activity → AT_RISK
- Otherwise → ON_TRACK

### Phase 5: Update documentation and roadmap

- Add status model section to `docs/ghillie-design.md`
- Mark Task 2.2.a as done in `docs/roadmap.md`

## Concrete Steps

1. Create `tests/unit/test_status_model.py` with failing tests:
   - `test_repository_status_result_creation`
   - `test_repository_status_result_is_frozen`
   - `test_to_machine_summary_format`
   - `test_mock_status_model_implements_protocol`
   - `test_mock_returns_unknown_for_empty_evidence`
   - `test_mock_returns_on_track_for_normal_activity`
   - `test_mock_returns_at_risk_when_previous_risks_exist`
   - `test_mock_returns_at_risk_when_bugs_exceed_features`
   - `test_mock_generates_summary_with_event_counts`
   - `test_mock_extracts_highlights_from_features`
   - `test_mock_carries_forward_previous_risks`

2. Create `tests/features/status_model.feature` with scenarios:
   - Generate status for repository with normal activity
   - Generate status for repository at risk from previous report
   - Generate status for repository with no activity

3. Create `tests/features/steps/test_status_model_steps.py` with step
   definitions following the pattern in `test_evidence_bundle_steps.py`.

4. Create `ghillie/status/models.py`:

   ```python
   class RepositoryStatusResult(msgspec.Struct, kw_only=True, frozen=True):
       summary: str
       status: ReportStatus
       highlights: tuple[str, ...] = ()
       risks: tuple[str, ...] = ()
       next_steps: tuple[str, ...] = ()

   def to_machine_summary(result: RepositoryStatusResult) -> dict[str, object]:
       ...
   ```

5. Create `ghillie/status/protocol.py`:

   ```python
   @typ.runtime_checkable
   class StatusModel(typ.Protocol):
       async def summarize_repository(
           self, evidence: RepositoryEvidenceBundle
       ) -> RepositoryStatusResult: ...
   ```

6. Create `ghillie/status/mock.py` with `MockStatusModel` class implementing
   heuristic-based status determination.

7. Create `ghillie/status/__init__.py` with exports:
   - `StatusModel`, `RepositoryStatusResult`, `MockStatusModel`,
     `to_machine_summary`

8. Update `docs/ghillie-design.md` Section 9 with status model design decisions.

9. Mark Task 2.2.a as done in `docs/roadmap.md`.

10. Run quality gates:

    ```bash
    set -o pipefail; make check-fmt 2>&1 | tee /tmp/ghillie-check-fmt.log
    set -o pipefail; make typecheck 2>&1 | tee /tmp/ghillie-typecheck.log
    set -o pipefail; make lint 2>&1 | tee /tmp/ghillie-lint.log
    set -o pipefail; make test 2>&1 | tee /tmp/ghillie-test.log
    set -o pipefail; make markdownlint 2>&1 | tee /tmp/ghillie-mdlint.log
    set -o pipefail; make nixie 2>&1 | tee /tmp/ghillie-nixie.log
    ```

## Validation and Acceptance

The change is accepted when:

1. `ghillie/status/` package exists with `models.py`, `protocol.py`, `mock.py`,
   `__init__.py`
2. `RepositoryStatusResult` is a frozen msgspec Struct with summary, status,
   highlights, risks, next_steps
3. `StatusModel` is a runtime_checkable Protocol with async
   `summarize_repository` method
4. `MockStatusModel` implements the protocol with deterministic heuristics
5. Unit tests verify struct creation, protocol compliance, and mock heuristics
6. BDD tests demonstrate end-to-end status generation scenarios
7. `to_machine_summary()` produces dict compatible with `Report.machine_summary`
8. Documentation updated in `ghillie-design.md` and `roadmap.md`
9. All quality gates pass: `make check-fmt`, `make typecheck`, `make lint`,
   `make test`, `make markdownlint`, `make nixie`

Expected test output examples:

```text
$ pytest tests/unit/test_status_model.py -v
11 passed

$ pytest tests/features -k status_model
3 passed
```

## Idempotence and Recovery

All steps are safe to rerun:

- Package creation is additive
- Tests can be run incrementally
- Documentation updates are idempotent
- Quality gates are read-only validations

If tests fail mid-run:

1. Fix the failing test or implementation
2. Rerun that specific test
3. Rerun full suite before commit

## Artefacts and Notes

**Key design decisions:**

- Reuse existing `ReportStatus` enum from `ghillie.evidence.models` rather than
  creating a duplicate
- `RepositoryStatusResult` maps directly to `Report.machine_summary` JSON
- Mock implementation provides baseline heuristics refinable from real usage
- Protocol method is async for future LLM API compatibility

**Edge cases:**

- Empty evidence bundle → UNKNOWN status, no highlights/risks
- Previous reports without machine_summary → Gracefully handle missing
  status/risks
- Multiple previous reports → Only consider most recent for heuristics

## Interfaces and Dependencies

**New public API:**

- `ghillie.status.StatusModel` - Protocol for summarization
- `ghillie.status.RepositoryStatusResult` - Structured output
- `ghillie.status.MockStatusModel` - Deterministic implementation
- `ghillie.status.to_machine_summary()` - Dict conversion helper

**Dependencies:**

- `ghillie.evidence.models.RepositoryEvidenceBundle` - Input type
- `ghillie.evidence.models.ReportStatus` - Status enum (reused)
- `ghillie.evidence.models.WorkType` - For heuristic classification

**Downstream consumers (Phase 2.3):**

- Reporting scheduler will call `StatusModel.summarize_repository()`
- Report storage will use `to_machine_summary()` for `Report.machine_summary`

## Critical Files

| File                                              | Action | Purpose                        |
| ------------------------------------------------- | ------ | ------------------------------ |
| `ghillie/status/__init__.py`                      | Create | Package exports                |
| `ghillie/status/models.py`                        | Create | RepositoryStatusResult struct  |
| `ghillie/status/protocol.py`                      | Create | StatusModel protocol           |
| `ghillie/status/mock.py`                          | Create | MockStatusModel implementation |
| `tests/unit/test_status_model.py`                 | Create | Unit tests                     |
| `tests/features/status_model.feature`             | Create | BDD scenarios                  |
| `tests/features/steps/test_status_model_steps.py` | Create | BDD steps                      |
| `docs/ghillie-design.md`                          | Modify | Add Section 9.4                |
| `docs/roadmap.md`                                 | Modify | Mark Task 2.2.a done           |
