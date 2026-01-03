# Implement coverage-aware event selection for evidence bundles

This ExecPlan is a living document. The sections `Progress`,
`Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must
be kept up to date as work proceeds.

No `PLANS.md` exists in this repo, so this document is the sole execution
plan and should be maintained accordingly.

## Purpose / Big Picture

This work makes repository evidence bundles idempotent by excluding events
that have already been reported. After the change, a reporting run for a
repository and time window only includes new, uncovered events, and repeating
that run without new events produces the same bundle. Success is observable by
running the new unit and behavioural tests and by observing that evidence
bundles omit covered events while still honouring the window start/end
boundaries.

## Progress

- [x] (2026-01-03 00:00Z) Reviewed roadmap and evidence bundle design sections
  to scope Task 2.1.b and identify affected files.
- [ ] Add tests that fail without coverage-aware selection.
- [ ] Implement coverage-aware selection and event grouping logic.
- [ ] Update design and users' guide documentation.
- [ ] Mark roadmap Task 2.1.b as done and run full quality gates.

## Surprises & Discoveries

- Observation: None yet.
  Evidence: N/A.

## Decision Log

- Decision: Coverage exclusion is scope-specific and does not cross scopes.
  Rationale: Repository evidence bundles should be complete for their own
  windows even if project or estate reports have already consumed the same
  events. This keeps reporting order from affecting repository bundles and
  matches the requirement that dedupe is per-scope.
  Date/Author: 2026-01-03 (plan author).

## Outcomes & Retrospective

- Outcomes: Not started.
- Lessons learned: N/A.

## Context and Orientation

The evidence bundle logic lives in `ghillie/evidence/service.py`, which queries
Silver tables (`ghillie/silver/storage.py`) and builds in-memory evidence
structs (`ghillie/evidence/models.py`). Report coverage is stored in
`ghillie/gold/storage.py` via `ReportCoverage`, which links reports to
`EventFact` IDs. The evidence bundle currently selects all events in the
window and collects all EventFact IDs in that window; it does not exclude
covered EventFacts yet.

Relevant tests and fixtures:

- Unit tests: `tests/unit/test_evidence_service.py`.
- Behavioural tests: `tests/features/evidence_bundle.feature` and
  `tests/features/steps/test_evidence_bundle_steps.py`.
- Test event builders: `tests/helpers/event_builders.py`.

Reference docs for expected behaviour and design constraints:

- `docs/roadmap.md` (Task 2.1.b completion criteria).
- `docs/ghillie-design.md` (Section 9 evidence bundle decisions).
- `docs/ghillie-proposal.md` (Section 5.1 coverage semantics).
- `docs/ghillie-bronze-silver-architecture-design.md` (Gold coverage schema).
- `docs/users-guide.md` (report coverage behaviour for users).
- `docs/documentation-style-guide.md` (wrap at 80 columns).

## Plan of Work

Start by writing tests that assert evidence bundles exclude already covered
EventFacts. This includes a unit test that covers at least one event type and
asserts `event_fact_ids` only include uncovered IDs, plus a pytest-bdd scenario
that demonstrates coverage-aware behaviour end-to-end. These tests should fail
with the current implementation because it ignores `report_coverage`.

Then update `EvidenceBundleService` to select only uncovered EventFacts for the
window, where coverage is filtered to repository-scoped reports only. Use
those EventFacts as the source of truth for which commits, pull requests,
issues, and documentation changes should be included. This will likely require
a helper that:

- fetches EventFacts for the repo slug within `[window_start, window_end)`;
- excludes EventFacts already present in `report_coverage` for reports with
  `scope = repository`;
- groups uncovered EventFacts by `event_type` and extracts identifiers
  (commit SHA, PR ID, issue ID, doc change commit+path); and
- returns both the uncovered EventFacts (for `event_fact_ids`) and the
  identifier sets for querying Silver tables.

When querying Silver tables, use identifier lists instead of time-only filters
so that events are not dropped when the EventFact occurred within the window
but the entity timestamps fall outside the window (for example, a PR created
before the window but updated within it). Keep ordering stable by sorting using
the entity timestamps, and define a deterministic ordering for
`event_fact_ids` (for example, by `occurred_at` then `id`).

Update documentation to record any decisions about coverage scope and the new
behaviour of evidence bundles. Reflect the user-visible behaviour in
`docs/users-guide.md` and update `docs/ghillie-design.md` in the evidence
bundle section. Finally, mark Task 2.1.b as done in `docs/roadmap.md` and run
all quality gates.

## Concrete Steps

1. Re-read the evidence bundle implementation and existing tests:

   - `rg -n "EvidenceBundleService" ghillie/evidence/service.py`
   - `rg -n "event_fact" tests/unit/test_evidence_service.py`
   - `rg -n "Evidence bundle" tests/features/evidence_bundle.feature`

2. Add failing tests first.

   - In `tests/unit/test_evidence_service.py`, add a test that:
     - ingests at least two events in the window;
     - records `ReportCoverage` for one EventFact;
     - builds a bundle and asserts only the uncovered event appears and only
       the uncovered EventFact ID appears in `event_fact_ids`.
   - In `tests/features/evidence_bundle.feature`, add a scenario such as
     "Bundle excludes covered events" and implement steps in
     `tests/features/steps/test_evidence_bundle_steps.py` to create coverage
     and assert the exclusion behaviour.

3. Implement coverage-aware selection in `ghillie/evidence/service.py`.

   - Add a helper like `_fetch_uncovered_event_facts` that left-joins
     `ReportCoverage` and filters `ReportCoverage.event_fact_id is NULL`.
   - Extract identifiers from the uncovered EventFacts payload and query
     `Commit`, `PullRequest`, `Issue`, and `DocumentationChange` by ID/keys.
   - Update `_fetch_event_fact_ids` (or replace it) so `event_fact_ids` only
     include uncovered EventFacts and are ordered deterministically.

4. Update documentation and roadmap.

   - Add or update a section in `docs/users-guide.md` describing that evidence
     bundles exclude events already covered by previous reports.
   - Record any decisions in `docs/ghillie-design.md` Section 9.
   - Mark Task 2.1.b as done in `docs/roadmap.md`.

5. Run formatting, lint, typecheck, and tests with logs captured.

   - `set -o pipefail; make check-fmt 2>&1 | tee /tmp/ghillie-check-fmt.log`
   - `set -o pipefail; make typecheck 2>&1 | tee /tmp/ghillie-typecheck.log`
   - `set -o pipefail; make lint 2>&1 | tee /tmp/ghillie-lint.log`
   - `set -o pipefail; make test 2>&1 | tee /tmp/ghillie-test.log`
   - `set -o pipefail; make markdownlint 2>&1 | tee /tmp/ghillie-mdlint.log`
   - `set -o pipefail; make nixie 2>&1 | tee /tmp/ghillie-nixie.log`

## Validation and Acceptance

The change is accepted when all of the following are true:

- New unit tests demonstrate that covered EventFacts are excluded from the
  evidence bundle when coverage comes from repository-scoped reports, and that
  coverage from project/estate reports does not exclude events.
- `event_fact_ids` only include uncovered IDs for repository-scoped coverage.
- New pytest-bdd scenario demonstrates coverage-aware selection end-to-end.
- Evidence bundle still respects `window_start` inclusive and `window_end`
  exclusive semantics.
- Running the reporting job twice without new events yields the same evidence
  bundle (no uncovered events appear).
- `make check-fmt`, `make typecheck`, `make lint`, `make test`,
  `make markdownlint`, and `make nixie` all succeed.

Expected targeted test output examples (for quick iteration only):

    $ pytest tests/unit/test_evidence_service.py -k coverage
    1 passed

    $ pytest tests/features -k evidence_bundle
    1 passed

## Idempotence and Recovery

All steps are safe to rerun. If a test fails mid-run, fix the issue and rerun
that test first, then rerun the full quality gates. If documentation changes
break `make markdownlint` or `make nixie`, run `make fmt` and adjust wrapping
to 80 columns before re-running the markdown checks.

## Artifacts and Notes

Keep a short note in this section about any data-shape assumptions used for
EventFact payload extraction (for example, which payload keys are required for
commit, PR, issue, or doc change selection) and any edge cases discovered.

## Interfaces and Dependencies

Evidence bundle selection must expose the following behaviour in
`ghillie/evidence/service.py`:

- A helper that returns uncovered `EventFact` rows for a repo/window by
  checking `report_coverage` for `Report.scope == repository` and ordering by
  `occurred_at` then `id`.
- A mapping from uncovered EventFacts to identifier sets:
  - commits: payload `sha` (string)
  - pull requests: payload `id` (int)
  - issues: payload `id` (int)
  - documentation changes: payload `commit_sha` + `path` (string pair)
- Queries to `Commit`, `PullRequest`, `Issue`, and `DocumentationChange` that
  select only those identifiers and the target `repo_id`.
- `RepositoryEvidenceBundle.event_fact_ids` must contain only uncovered
  EventFact IDs.

Scope-specific filtering is required. Document it in the design doc and in the
users' guide.

## Revision note

Initial ExecPlan drafted for Task 2.1.b. No implementation changes yet.
