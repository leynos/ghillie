# Upgrade Python to 3.14: readonly attributes

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`, and
`Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: DRAFT

No `PLANS.md` file exists in this repository.

## Purpose / big picture

Python 3.14 typing supports `typing.ReadOnly` for `TypedDict` keys. Ghillie
already uses `TypedDict` to describe persisted JSON payloads and scenario
contexts, but immutable fields are not currently encoded as readonly in type
contracts.

This activity introduces `ReadOnly` annotations where fields are logically
immutable so type checking prevents accidental reassignment in future changes,
without changing runtime behaviour.

Success is observable when:

1. Production `TypedDict` payload types use `ReadOnly` for immutable keys.
2. Type checking passes with the stronger contracts.
3. Runtime behaviour and tests remain unchanged.

## Constraints

- Prioritise production code contracts first (for example
  `ghillie/gold/storage.py`) before optional test-context cleanup.
- Do not change runtime payload shape, database schema, or JSON serialisation.
- Do not add external dependencies.
- Keep scope focused on type annotations and related test adjustments only.
- Preserve backwards-compatible APIs and data formats.

## Tolerances (exception triggers)

- Scope: if more than 10 files or 220 net lines are required, stop and
  escalate.
- Interface: if introducing readonly typing requires changing a public function
  signature or payload shape, stop and escalate.
- Dependencies: if tooling requires backports such as `typing_extensions`, stop
  and escalate.
- Iterations: if `make typecheck` fails after 3 fix attempts, stop and
  escalate.
- Ambiguity: if a field's mutability intent is unclear, stop and request
  clarification before enforcing readonly.

## Risks

- Risk: over-constraining mutable test-context `TypedDict` values may create
  friction with pytest-bdd step wiring. Severity: low. Likelihood: medium.
  Mitigation: start with production payload types and only apply readonly in
  tests where immutability is clear.
- Risk: type checker interpretation of `ReadOnly` may vary across tools.
  Severity: medium. Likelihood: low. Mitigation: rely on the repository's
  configured type checker in `make typecheck` and keep usage simple.
- Risk: contributors may assume runtime immutability from type hints. Severity:
  low. Likelihood: medium. Mitigation: document that this is a static contract,
  not runtime enforcement.

## Progress

- [x] (2026-02-24 00:00Z) Draft ExecPlan at
  `docs/execplans/upgrade-python-to-3-14-readonly-attributes.md`.
- [ ] Audit all `TypedDict` definitions in production and tests.
- [ ] Decide the minimal safe first set of readonly keys.
- [ ] Update `TypedDict` annotations with `typing.ReadOnly`.
- [ ] Add or adjust tests/type assertions where useful.
- [ ] Run full quality gates.

## Surprises & Discoveries

- None yet. Record implementation-time findings here.

## Decision Log

- Decision: phase this as a conservative typing-hardening task beginning with
  production payload contracts only. Rationale: minimises disruption to
  behaviour-driven test contexts that are intentionally mutable.
- Decision: avoid introducing runtime wrappers for immutability in this task.
  Rationale: objective is static typing improvement, not runtime redesign.

## Outcomes & Retrospective

Not started. Populate after implementation.

## Context and orientation

Current `TypedDict` usage includes:

- Production payload type:
  `ghillie/gold/storage.py::ValidationIssuePayload`
- Many pytest-bdd context dictionaries under `tests/features/steps/`

The highest-value contract is `ValidationIssuePayload`, whose `code` and
`message` keys are treated as immutable snapshots when persisted to
`ReportReview.validation_issues`.

## Plan of work

Stage A audits and scopes. Inventory all `TypedDict` definitions and classify
which keys are truly immutable.

Stage B applies readonly to the approved first set in production modules.
Optionally extend to test-only `TypedDict` definitions where there is clear
benefit and no step-mutation conflict.

Stage C validates with type checking and full regression tests.

## Concrete steps

1. Audit `TypedDict` definitions.

   - `rg -n "class .*TypedDict|typ\.TypedDict" ghillie tests`

2. Establish baseline behaviour and typing.

   - `set -o pipefail; make typecheck 2>&1 | tee /tmp/ghillie-readonly-baseline-typecheck.log`

3. Apply readonly typing in production contracts.

   - Update `ghillie/gold/storage.py` to annotate immutable
     `ValidationIssuePayload` keys with `typing.ReadOnly`.
   - Keep runtime code unchanged.

4. Add or update tests if needed.

   - If helper-level type assertions are useful, add a focused unit test module
     without introducing brittle checker-specific directives.

5. Run gates.

   - `set -o pipefail; make check-fmt 2>&1 | tee /tmp/ghillie-readonly-check-fmt.log`
   - `set -o pipefail; make lint 2>&1 | tee /tmp/ghillie-readonly-lint.log`
   - `set -o pipefail; make typecheck 2>&1 | tee /tmp/ghillie-readonly-typecheck.log`
   - `set -o pipefail; make test 2>&1 | tee /tmp/ghillie-readonly-test.log`

## Validation and acceptance

This activity is complete when:

1. The chosen production `TypedDict` keys are annotated with
   `typing.ReadOnly`.
2. Type checking passes with no new suppressions.
3. Runtime behaviour and tests remain unchanged.
4. `make check-fmt`, `make lint`, `make typecheck`, and `make test` pass.

## Idempotence and recovery

Readonly annotation changes are idempotent and safe to reapply. If type
contracts prove too strict, revert the last `TypedDict` change, document the
case in `Decision Log`, and resume with a narrower readonly scope.
