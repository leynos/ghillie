# Upgrade Python to 3.14: UUIDv7 for storage identifiers

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`, and
`Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: DRAFT

No `PLANS.md` file exists in this repository.

## Purpose / big picture

Ghillie currently generates primary-key identifiers with `uuid.uuid4()` in
storage models. Python 3.14 supports UUID version 7 generation
(`uuid.uuid7()`), which provides time-ordered identifiers with better index
locality while retaining UUID string compatibility.

This activity migrates storage defaults from UUIDv4 to UUIDv7 in a controlled
way, without changing column types or existing data.

Success is observable when:

1. Storage model defaults use UUIDv7 generation.
2. Existing schema compatibility is preserved (still `String(36)` UUID text).
3. New tests verify UUIDv7 properties for generated identifiers.
4. Full quality gates pass.

## Constraints

- Keep storage schema unchanged (no column type changes, no migrations required
  for this activity).
- Do not alter external API payload shapes or identifier field names.
- Keep scope to identifier generation logic in storage models and related
  helper/tests.
- Do not add dependencies.
- Maintain backward compatibility with existing persisted UUIDv4 rows.

## Tolerances (exception triggers)

- Scope: if changes exceed 9 files or 260 net lines, stop and escalate.
- Interface: if any public model field or API contract must change, stop and
  escalate.
- Data: if migration appears to require data backfill or destructive rewrite,
  stop and escalate.
- Iterations: if database or storage tests fail after 3 focused attempts, stop
  and escalate.
- Ambiguity: if UUID ordering assumptions conflict with current query logic,
  stop and present trade-offs.

## Risks

- Risk: UUIDv7 lexical ordering assumptions may be misapplied. Severity:
  medium. Likelihood: low. Mitigation: constrain ordering claims to generation
  time locality and avoid introducing logic that depends on strict global sort
  guarantees.
- Risk: duplicated lambda defaults across models can drift. Severity: medium.
  Likelihood: medium. Mitigation: centralise generation in one helper and reuse
  it.
- Risk: tests could become flaky if they assert strict monotonic ordering.
  Severity: medium. Likelihood: medium. Mitigation: test UUID version and basic
  non-decreasing timestamp characteristics only.

## Progress

- [x] (2026-02-24 00:00Z) Draft ExecPlan at
  `docs/execplans/upgrade-python-to-3-14-uuid7-for-storage-ids.md`.
- [ ] Add failing tests for shared ID helper (UUIDv7 shape/properties).
- [ ] Introduce a shared UUIDv7 string helper in common utilities.
- [ ] Update storage model defaults to use the helper.
- [ ] Confirm no schema changes are needed.
- [ ] Run full quality gates.

## Surprises & Discoveries

- None yet. Record implementation details during execution.

## Decision Log

- Decision: use a shared helper instead of inline lambdas in every model.
  Rationale: keeps UUID policy in one place and reduces copy-paste drift.
- Decision: preserve `String(36)` columns and canonical UUID text format.
  Rationale: avoids migrations and keeps external contracts stable.

## Outcomes & Retrospective

Not started. Populate after implementation.

## Context and orientation

Current UUID defaults in storage models:

- `ghillie/catalogue/storage.py`
- `ghillie/silver/storage.py`
- `ghillie/gold/storage.py`

Each currently uses `default=lambda: str(uuid.uuid4())`. This activity replaces
those call sites with a shared UUIDv7 generator.

## Plan of work

Stage A is tests-first. Add focused unit tests for the planned UUID helper,
including version checks and format checks.

Stage B adds a shared helper (for example in `ghillie/common/`) that returns a
canonical UUIDv7 string.

Stage C updates storage model defaults to call the helper, then validates
existing storage and reporting tests plus full quality gates.

## Concrete steps

1. Add failing tests before implementation.

   - Create `tests/unit/test_common_ids.py` covering:
     - generated value parses as UUID,
     - UUID version is 7,
     - output is canonical string form.

2. Implement shared helper.

   - Add `ghillie/common/ids.py` with a function such as
     `new_uuid7_str() -> str`.
   - Export helper from `ghillie/common/__init__.py` if needed.

3. Update storage defaults.

   - Replace inline `str(uuid.uuid4())` defaults in:
     - `ghillie/catalogue/storage.py`
     - `ghillie/silver/storage.py`
     - `ghillie/gold/storage.py`

4. Validate schema compatibility.

   - Confirm all identifier columns remain `String(36)` and no migration files
     are required.

5. Run gates.

   - `set -o pipefail; make check-fmt 2>&1 | tee /tmp/ghillie-uuid7-check-fmt.log`
   - `set -o pipefail; make lint 2>&1 | tee /tmp/ghillie-uuid7-lint.log`
   - `set -o pipefail; make typecheck 2>&1 | tee /tmp/ghillie-uuid7-typecheck.log`
   - `set -o pipefail; make test 2>&1 | tee /tmp/ghillie-uuid7-test.log`

## Validation and acceptance

The activity is complete when:

1. No storage model default uses `uuid.uuid4()`.
2. UUID generation is centralised through a UUIDv7 helper.
3. New helper tests pass and verify UUIDv7 output properties.
4. `make check-fmt`, `make lint`, `make typecheck`, and `make test` pass.

## Idempotence and recovery

This migration is additive and reversible. If an issue appears, revert the
model-default call sites to the previous helper/lambda path, then reapply one
module at a time with targeted storage tests between each step.
