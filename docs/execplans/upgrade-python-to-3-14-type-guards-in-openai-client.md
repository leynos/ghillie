# Upgrade Python to 3.14: type guards in OpenAI client

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`, and
`Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: DRAFT

No `PLANS.md` file exists in this repository.

## Purpose / big picture

`ghillie/status/openai_client.py` currently narrows JSON-shaped objects with
`isinstance(...)` checks followed by `typ.cast(...)`. Python 3.14 lets us adopt
modern type guards (`typing.TypeIs`) so narrowing logic is explicit and type
checker-friendly without casts.

This activity introduces private type-guard helpers in the OpenAI client,
replaces cast-heavy code paths with guard-based narrowing, and keeps runtime
behaviour unchanged.

Success is observable when:

1. `ghillie/status/openai_client.py` no longer relies on `typ.cast(...)` for
   response-shape narrowing.
2. Existing OpenAI parsing behaviour and error mapping stay unchanged.
3. Unit tests and quality gates pass.

## Constraints

- Limit code scope to `ghillie/status/openai_client.py` and related tests under
  `tests/unit/status/`.
- Preserve all externally visible behaviour, including raised exception types
  and error messages.
- Do not change `OpenAIStatusModel` public method signatures.
- Do not add external dependencies.
- Keep helper functions private to the module unless a wider reuse need is
  proven in this activity.

## Tolerances (exception triggers)

- Scope: if implementation requires changes to more than 6 files or 240 net
  lines, stop and escalate.
- Interface: if a public API signature change appears necessary, stop and
  escalate.
- Dependencies: if `typing_extensions` appears required, stop and escalate.
- Iterations: if `make typecheck` or OpenAI parsing tests still fail after
  3 fix attempts, stop and escalate.
- Ambiguity: if `TypeIs` semantics differ between type checkers in a way that
  forces behavioural compromise, stop and present options.

## Risks

- Risk: a guard helper could be too permissive, allowing malformed objects to
  pass deeper into parsing. Severity: medium. Likelihood: medium. Mitigation:
  expand unit tests around malformed payload branches.
- Risk: a guard helper could be too strict, changing current fallback behaviour
  and exceptions. Severity: medium. Likelihood: low. Mitigation: keep
  behaviour-focused tests as the source of truth before and after refactor.
- Risk: type checker support differences for `TypeIs` can create noise in CI.
  Severity: low. Likelihood: medium. Mitigation: verify with project
  `make typecheck` and keep guard signatures minimal.

## Progress

- [x] (2026-02-24 00:00Z) Draft ExecPlan at
  `docs/execplans/upgrade-python-to-3-14-type-guards-in-openai-client.md`.
- [ ] Confirm current cast locations and narrowing branches.
- [ ] Add or refine tests first to lock expected parsing and error behaviour.
- [ ] Implement private `TypeIs` helpers and remove casts.
- [ ] Run targeted status parsing tests.
- [ ] Run full quality gates.

## Surprises & Discoveries

- None yet. Record concrete findings while implementing.

## Decision Log

- Decision: apply `TypeIs` only in the OpenAI client first. Rationale: this is
  a high-value, low-risk pilot before broader adoption in GitHub parsers.
- Decision: keep behaviour-led tests authoritative over static-style goals.
  Rationale: runtime correctness matters more than eliminating every cast.

## Outcomes & Retrospective

Not started. Populate after implementation with outcomes and follow-ups.

## Context and orientation

Key code and tests:

- `ghillie/status/openai_client.py`
- `tests/unit/status/test_openai_parsing.py`
- `tests/unit/status/test_openai_errors.py`

Current cast usage appears in `_get_nested`, `_extract_usage_metrics`, and
`_extract_content`. The goal is to replace this narrowing style with private
`TypeIs` helpers such as object-dict and non-empty-choice checks.

## Plan of work

Stage A establishes behaviour and typing baseline. Run focused OpenAI parsing
unit tests and confirm current narrowing branches.

Stage B is tests-first. Add tests that pin behaviour for malformed payloads and
successful extraction paths touched by narrowing code.

Stage C implements guard-based narrowing. Introduce small, private `TypeIs`
helpers and replace casts while preserving exceptions and return values.

Stage D validates end to end with targeted and full project gates.

## Concrete steps

1. Baseline and inventory.

   - `rg -n "typ\.cast\(" ghillie/status/openai_client.py`
   - Run `uv run pytest tests/unit/status/test_openai_parsing.py` with
     `set -o pipefail`, then capture output with
     `tee /tmp/tg-openai-baseline.log`.

2. Update tests first.

   - Add or extend tests in `tests/unit/status/test_openai_parsing.py` for
     malformed `choices`, malformed `usage`, and nested content extraction
     branches that rely on narrowing.
   - Confirm new/updated tests fail before code changes.

3. Implement type guards.

   - Add private helpers in `ghillie/status/openai_client.py` using
     `typing.TypeIs` for narrowing JSON-like objects.
   - Replace `typ.cast(...)` call sites with guard-based branches.
   - Keep exception paths and messages unchanged.

4. Validate targeted tests.

   - Run `uv run pytest tests/unit/status/test_openai_parsing.py` and
     `tests/unit/status/test_openai_errors.py` with `set -o pipefail`, then
     capture output with `tee /tmp/tg-openai-targeted.log`.

5. Run full gates.

   - `set -o pipefail; make check-fmt 2>&1 | tee /tmp/ghillie-type-guards-openai-check-fmt.log`
   - `set -o pipefail; make lint 2>&1 | tee /tmp/ghillie-type-guards-openai-lint.log`
   - `set -o pipefail; make typecheck 2>&1 | tee /tmp/ghillie-type-guards-openai-typecheck.log`
   - `set -o pipefail; make test 2>&1 | tee /tmp/ghillie-type-guards-openai-test.log`

## Validation and acceptance

The activity is complete when:

1. Narrowing in `ghillie/status/openai_client.py` uses `TypeIs` helpers and no
   longer depends on `typ.cast(...)` for JSON shape handling.
2. OpenAI parsing and error behaviour remain unchanged in unit tests.
3. `make check-fmt`, `make lint`, `make typecheck`, and `make test` pass.

## Idempotence and recovery

This refactor is safe to rerun. If behaviour changes, revert the module and
re-apply helper introduction in one narrowed function at a time, validating
with targeted parsing tests between each step.
