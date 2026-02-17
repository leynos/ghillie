# Add basic correctness checks for generated reports

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`, and
`Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: DONE

## Purpose / big picture

Task 2.4.a adds post-generation report validation so Ghillie does not persist
clearly broken model output. After this change, repository report generation
must validate that:

- output is not empty,
- output is not obviously truncated, and
- highlight counts are plausible relative to the evidence bundle event count.

If validation fails, the run must not silently store the invalid report. The
pipeline should retry generation a bounded number of times, then mark the run
for human review if it still fails validation.

Success is observable when:

1. Invalid report payloads are rejected before a `Report` row is inserted.
2. The service retries generation within configured bounds.
3. Failed retries create a human-review marker that operators can query.
4. On-demand API calls surface validation failure explicitly (not HTTP 200/204).
5. Unit tests and pytest-bdd scenarios demonstrate the behaviour end-to-end.
6. Documentation and roadmap entries are updated.
7. Quality gates pass: `make check-fmt`, `make typecheck`, `make lint`,
   `make test`, `make markdownlint`, and `make nixie`.

## Constraints

- Follow TDD in `AGENTS.md`: tests first, see failures, then implement.
- New functionality requires both unit tests (`pytest`) and behavioural tests
  (`pytest-bdd`).
- Keep the existing reporting architecture intact:
  `EvidenceBundleService` -> `StatusModel` -> `ReportingService` -> Gold layer.
- Do not silently downgrade invalid outputs to "best effort" reports.
- Keep constructor signatures within lint constraints (`max-args = 4`).
- No secrets in logs, docs, or tests.
- Keep docs wrapped to 80 columns and aligned with
  `docs/documentation-style-guide.md`.

## Tolerances (exception triggers)

- If satisfying "marked for human review" requires a larger schema redesign,
  stop and escalate with options.
- If this task requires changing `StatusModel` protocol signatures, stop and
  escalate before proceeding.
- If retries require introducing a new external dependency, stop and escalate.
- If behaviour conflicts between scheduled and on-demand paths cannot be
  resolved with one shared policy, stop and escalate with trade-offs.

## Risks

- Risk: Validation rules are too strict and reject valid reports.
  Mitigation: Start with conservative "clearly broken" heuristics and unit
  fixtures covering plausible edge cases.

- Risk: Validation rules are too weak and allow malformed reports.
  Mitigation: Add targeted failure fixtures (empty, truncated, implausible
  highlights) and assert rejection.

- Risk: Retry behaviour introduces duplicate review markers.
  Mitigation: Add a uniqueness strategy for review records per
  `(repository_id, window_start, window_end)` or update-in-place semantics.

- Risk: API error mapping regresses existing 200/204/404 behaviour.
  Mitigation: Extend unit and BDD API coverage with explicit 422 scenarios.

## Progress

- [x] Draft ExecPlan for Task 2.4.a.
- [x] Add failing unit tests for validation logic.
- [x] Add failing unit tests for service retry/review behaviour.
- [x] Add failing unit tests for API mapping of validation failures.
- [x] Add failing pytest-bdd scenario(s) for invalid report handling.
- [x] Implement validation module and service integration.
- [x] Implement human-review persistence for exhausted retries.
- [x] Update API error handlers and endpoint behaviour.
- [x] Update users' guide and design docs.
- [x] Mark roadmap Task 2.4.a as done.
- [x] Run all quality gates and record outcomes.

## Surprises & discoveries

- The `execplans` skill is not installed in this environment. This plan uses
  the established `docs/execplans/` format already used in the repository.
- No existing Gold-layer table currently captures "needs human review" for
  invalid generated reports.
- Test fixtures using synthetic `event_fact_ids` caused FK constraint
  violations against py-pglite. Resolved by using empty tuples `()` in
  retry/review test bundles, since validation does not depend on event fact
  rows.
- The lint agent refactored `_persist_report` to derive `repository_id`,
  `window_start`, and `window_end` from the `bundle` parameter, reducing
  argument count to satisfy `PLR0913`. This was safe because `generate_report`
  always provides a bundle with matching metadata.
- Section 9.6.1 of the design document was drafted as part of the plan phase
  and did not require further updates during implementation.

## Decision log

1. **Validate before persistence.**
   A report that fails correctness checks must never be inserted into `reports`
   or written to Markdown sinks.

2. **Bounded retry inside `ReportingService`.**
   Validation retry attempts should live in service logic so both scheduled and
   on-demand paths share one policy.

3. **Explicit human-review marker in Gold layer.**
   After retries are exhausted, persist a review marker row containing scope,
   window, and validation failure reasons. This is preferred over relying only
   on logs.

4. **Conservative "clearly broken" heuristics for MVP.**
   Initial checks target obvious failures only: empty summary, obvious
   truncation markers, and highlight/event-count implausibility.

## Outcomes & retrospective

All acceptance criteria are met:

1. Invalid outputs (empty, truncated, implausible highlights) are rejected
   before `Report` persistence — verified by 9 validation unit tests and the
   `test_no_report_persisted_on_validation_failure` integration test.
2. Report generation retries within configured bounds — verified by
   `test_retries_then_succeeds` with a two-attempt mock.
3. Exhausted retries persist a `ReportReview` Gold-layer marker — verified
   by `test_marks_for_human_review` and schema-level uniqueness tests.
4. On-demand endpoint returns HTTP 422 with machine-readable details —
   verified by `TestReportResource422` unit tests and a pytest-bdd scenario.
5. Unit tests (22 new) and pytest-bdd scenarios (3 new) pass.
6. Quality gates pass: `make check-fmt`, `make typecheck`, `make lint`,
   `make test`, `make markdownlint`, and `make nixie`.
7. `docs/users-guide.md` documents the 422 behaviour, validation checks,
   retry policy, human review markers, and configuration.
8. `docs/ghillie-design.md` Section 9.6.1 documents the validation and
   retry workflow with a Mermaid flowchart.
9. `docs/roadmap.md` marks Task 2.4.a as done.

Key implementation files:

- `ghillie/reporting/validation.py` — validation module (3 checks)
- `ghillie/reporting/errors.py` — `ReportValidationError`
- `ghillie/gold/storage.py` — `ReportReview` model, `ReviewState` enum
- `ghillie/reporting/service.py` — retry loop and review marker persistence
- `ghillie/reporting/config.py` — `validation_max_attempts` setting
- `ghillie/api/errors.py` — 422 error handler
- `ghillie/api/app.py` — error handler registration

The TDD-first approach worked well. All tests were written and verified as
failing before implementation, then made green in Phase 2. The conservative
heuristic approach (three "clearly broken" checks) was appropriate for the MVP
scope — future work can tighten or add checks without changing the retry or
review marker infrastructure.

## Context and orientation

Current state:

- `ghillie/reporting/service.py` generates and persists reports immediately
  after model output, with no post-generation correctness validation.
- `ghillie/reporting/actor.py` and `ghillie/api/gold/resources.py` both rely on
  `ReportingService.run_for_repository()`.
- `ghillie/gold/storage.py` has `Report` and `ReportCoverage` tables only.
- Existing API response matrix for on-demand reporting is 200/204/404.
- Existing reporting BDD coverage is in
  `tests/features/reporting_workflow.feature` and
  `tests/features/on_demand_report.feature`.

Reference docs reviewed:

- `docs/roadmap.md` (Task 2.4.a objective and completion criteria)
- `docs/ghillie-design.md` (Sections 9.4-9.7 reporting and status model design)
- `docs/ghillie-proposal.md` (reporting and coverage semantics)
- `docs/ghillie-bronze-silver-architecture-design.md` (Gold schema context)
- `docs/async-sqlalchemy-with-pg-and-falcon.md`
- `docs/testing-async-falcon-endpoints.md`
- `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`

## Plan of work

### Phase 1: Add failing tests first

#### 1a. Unit tests for validation rules

Create `tests/unit/test_reporting_validation.py`:

- `test_valid_result_passes_basic_correctness_checks`
- `test_rejects_empty_summary`
- `test_rejects_obviously_truncated_summary`
- `test_rejects_implausible_highlight_count_for_event_volume`

Use real `RepositoryEvidenceBundle` + `RepositoryStatusResult` fixtures so
rules are exercised without database coupling.

#### 1b. Unit tests for retry and human-review behaviour

Extend `tests/unit/test_reporting_generate_report.py`:

- `test_generate_report_retries_after_validation_failure_then_succeeds`
- `test_generate_report_marks_for_human_review_after_exhausted_retries`
- `test_generate_report_does_not_persist_invalid_report`

Add schema-level tests in `tests/unit/test_gold_reports.py` for new review
marker table constraints.

#### 1c. Unit tests for API behaviour

Extend `tests/unit/test_api_report_resource.py`:

- `test_returns_422_when_report_fails_validation`
- `test_422_body_contains_review_reference`

#### 1d. Behavioural tests (pytest-bdd)

Extend or add feature coverage:

- `tests/features/reporting_workflow.feature`:
  Scenario: invalid generated report is retried and then marked for review.
- `tests/features/on_demand_report.feature`:
  Scenario: on-demand endpoint returns 422 when validation fails.

Update corresponding step definitions in
`tests/features/steps/test_reporting_workflow_steps.py` and
`tests/features/steps/test_on_demand_report_steps.py`.

### Phase 2: Implement validation and retry policy

Add new module `ghillie/reporting/validation.py`:

- `ReportValidationIssue` and `ReportValidationResult` frozen dataclasses.
- `validate_repository_report(bundle, result) -> ReportValidationResult`.
- Checks:
  - non-empty summary,
  - obvious truncation (for example trailing ellipsis or unterminated clause),
  - highlight plausibility relative to `bundle.total_event_count`.

Add new errors in `ghillie/reporting/errors.py`:

- `ReportValidationError` carrying validation issues.
- `ReportMarkedForReviewError` (optional if separate semantic is useful).

Extend `ghillie/reporting/config.py` with bounded retry configuration, for
example:

- `validation_enabled` (default `True`),
- `validation_max_attempts` (default `2`, minimum `1`),
- optional conservative thresholds if needed.

### Phase 3: Add human-review persistence

Extend `ghillie/gold/storage.py` with a Gold-layer review marker entity, e.g.
`ReportReview`:

- scope keys: repository ID + window bounds,
- failure payload: validation issue codes/messages,
- model identifier and attempt count,
- lifecycle state (`pending`, `resolved`) for operator follow-up,
- timestamp fields.

Expose exports in `ghillie/gold/__init__.py` as needed and add any required
storage initialization coverage.

### Phase 4: Integrate into reporting workflow

Update `ghillie/reporting/service.py`:

- run status generation and validation in an attempt loop,
- persist report and coverage only after successful validation,
- on exhausted attempts, persist review marker and raise validation error,
- keep sink writes only on valid persisted reports.

Update `ghillie/reporting/actor.py` and `ghillie/api/factory.py` wiring for any
new config parameters.

### Phase 5: Surface operational behaviour in API

Update API error mapping:

- add a domain/API mapping for report validation failures in
  `ghillie/api/errors.py`,
- register handler in `ghillie/api/app.py`,
- ensure `POST /reports/repositories/{owner}/{name}` returns 422 with
  machine-readable details when a report is marked for review.

### Phase 6: Documentation and roadmap updates

Update docs:

- `docs/ghillie-design.md`: add section describing report correctness
  validation, retry behaviour, and review-marker lifecycle.
- `docs/users-guide.md`: document user-visible 422 behaviour and operator
  workflow for reviewing flagged generations.
- `docs/roadmap.md`: mark Task 2.4.a as done once implementation and quality
  gates pass.

## Concrete steps

1. Add failing unit tests for validation, service retries, review persistence,
   and API mapping.
2. Run focused tests to verify failures are meaningful.
3. Implement validation module and error types.
4. Implement Gold review marker table/model and tests.
5. Integrate retry + review flow into `ReportingService`.
6. Update actor/API wiring and error handlers.
7. Add/update pytest-bdd feature scenarios and steps.
8. Update users' guide, design doc, and roadmap status.
9. Run full quality gates with `tee` logs:

   - `set -o pipefail; make check-fmt 2>&1 | tee /tmp/ghillie-check-fmt.log`
   - `set -o pipefail; make typecheck 2>&1 | tee /tmp/ghillie-typecheck.log`
   - `set -o pipefail; make lint 2>&1 | tee /tmp/ghillie-lint.log`
   - `set -o pipefail; make test 2>&1 | tee /tmp/ghillie-test.log`
   - `set -o pipefail; make markdownlint 2>&1 | tee /tmp/ghillie-mdlint.log`
   - `set -o pipefail; make nixie 2>&1 | tee /tmp/ghillie-nixie.log`

## Validation and acceptance

Task 2.4.a is complete when all of the following are true:

- Invalid outputs (empty, truncated, implausible highlights) are rejected
  before `Report` persistence.
- Report generation retries within configured bounds.
- Exhausted retries persist a human-review marker.
- Invalid generations do not silently appear in `reports` or sink output.
- On-demand endpoint surfaces validation failure explicitly (422).
- Unit tests and pytest-bdd scenarios pass for the new behaviour.
- `make check-fmt`, `make typecheck`, `make lint`, `make test`,
  `make markdownlint`, and `make nixie` pass.
- `docs/users-guide.md` and `docs/ghillie-design.md` reflect the delivered
  behaviour.
- `docs/roadmap.md` marks Task 2.4.a as done.

## Idempotence and recovery

- Tests and quality gates are safe to rerun.
- Review marker persistence must be idempotent for repeated failures in the
  same window (upsert or uniqueness guard).
- If retries still fail due to provider instability, the system should prefer
  deterministic review-marker creation over partial report persistence.

## Revision note

Initial draft created for roadmap Task 2.4.a planning.
