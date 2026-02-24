# Upgrade Python to 3.14: template strings in prompts

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & discoveries`, `Decision log`, and
`Outcomes & retrospective` must be kept up to date as work proceeds.

Status: DRAFT

No `PLANS.md` file exists in this repository.

## Purpose / big picture

`ghillie/status/prompts.py` currently composes prompt content primarily with
f-strings. Python 3.14 adds template string literals (`t"..."`), which enable
structured interpolation workflows. This activity introduces template strings
in prompt construction while preserving the exact user-visible prompt output.

Success is observable when:

1. Prompt construction in `ghillie/status/prompts.py` uses template strings in
   the targeted sections.
2. Prompt output remains unchanged for the same evidence input.
3. Prompt-focused tests pass, and full quality gates pass.

## Constraints

- Treat Python-baseline uplift as a hard prerequisite: do not implement
  `t"..."` syntax until project metadata and tooling have moved to 3.14
  (`pyproject.toml` `requires-python` and Ruff `target-version`).
- Preserve prompt semantics and formatting; changes should be behaviour-neutral
  unless explicitly approved.
- Limit scope to prompt-building internals and prompt-related tests/docs.
- Do not change model invocation interfaces or response parsing.
- Do not add dependencies.
- Keep template adoption readable and maintainable for contributors unfamiliar
  with the feature.

## Tolerances (exception triggers)

- Scope: if implementation requires more than 5 files or 220 net lines, stop
  and escalate.
- Behaviour: if prompt output changes materially and requires updates beyond
  tests intended for exactness checks, stop and escalate.
- Complexity: if template-string support requires more than 120 lines of
  compatibility/helpers, stop and escalate.
- Iterations: if prompt tests fail after 3 fix attempts, stop and escalate.
- Ambiguity: if Python 3.14 template APIs are unclear in this environment,
  stop after prototyping and request direction.

## Risks

- Risk: template strings return structured template objects rather than `str`,
  which can cause accidental object-repr output if rendering is mishandled.
  Severity: high. Likelihood: medium. Mitigation: add explicit rendering tests
  and keep conversions local and obvious.
- Risk: subtle whitespace or newline changes alter prompt quality and model
  behaviour. Severity: medium. Likelihood: medium. Mitigation: add exact-output
  regression assertions for representative evidence bundles.
- Risk: contributor readability cost from unfamiliar syntax. Severity: low.
  Likelihood: medium. Mitigation: include concise comments explaining why
  template strings are used.

## Progress

- [x] (2026-02-24 00:00Z) Draft ExecPlan at
  `docs/execplans/upgrade-python-to-3-14-template-strings-in-prompts.md`.
- [ ] Confirm Python-baseline uplift is complete (`requires-python >=3.14` and
  Ruff `target-version = "py314"`).
- [ ] Prototype template-string rendering approach in tests first.
- [ ] Add failing regression tests for prompt output equivalence.
- [ ] Refactor prompt construction to template strings.
- [ ] Verify exact prompt-output stability.
- [ ] Run full quality gates.

## Surprises & discoveries

- None yet. Update with concrete findings from the prototype and refactor.

## Decision log

- Decision: include a dedicated prototype checkpoint before full refactor.
  Rationale: template strings are new and need validation in this codebase.
- Decision: prioritize output equivalence over maximal template-string usage.
  Rationale: prompt stability is more important than feature saturation.

## Outcomes & retrospective

Not started. Populate after implementation.

## Context and orientation

Primary files:

- `ghillie/status/prompts.py`
- `tests/unit/status/test_openai_prompts.py`

`build_user_prompt()` currently assembles a `list[str]` and uses f-strings for
interpolation. Existing unit tests check for key prompt content, but not all
assert exact full-output equivalence for representative bundles.

## Plan of work

Stage A verifies prerequisites and de-risks the rendering strategy. Confirm the
repository baseline has already moved to Python 3.14, then validate template
string behaviour in this runtime and define a minimal rendering pattern.

Stage B is tests-first. Add regression tests that lock representative prompt
outputs so refactoring does not silently change semantics.

Stage C introduces template strings in selected prompt-building paths and keeps
rendering explicit.

Stage D validates output equivalence and runs full quality gates.

## Concrete steps

1. Prototype template-string behaviour.

   - Add a focused unit test case (or helper test) to confirm template-string
     interpolation and conversion strategy used by prompt code.

2. Add failing prompt-regression tests first.

   - Extend `tests/unit/status/test_openai_prompts.py` with one or more
     representative bundle snapshots asserting expected prompt text fragments or
     exact output where stable.

3. Refactor prompt construction.

   - Update `ghillie/status/prompts.py` to adopt template strings in selected
     interpolated sections while keeping returned type `str`.
   - Keep helper functions small and readable.

4. Validate prompt behaviour.

   - Run `uv run pytest tests/unit/status/test_openai_prompts.py` with
     `set -o pipefail`, then capture output with
     `tee /tmp/ts-prompts-targeted.log`.

5. Run full gates.

   - `set -o pipefail; make check-fmt 2>&1 | tee /tmp/ghillie-template-prompts-check-fmt.log`
   - `set -o pipefail; make lint 2>&1 | tee /tmp/ghillie-template-prompts-lint.log`
   - `set -o pipefail; make typecheck 2>&1 | tee /tmp/ghillie-template-prompts-typecheck.log`
   - `set -o pipefail; make test 2>&1 | tee /tmp/ghillie-template-prompts-test.log`

## Validation and acceptance

This activity is complete when:

1. `ghillie/status/prompts.py` uses template strings in the agreed prompt
   construction path.
2. Prompt output for representative bundles remains unchanged unless an
   intentional and documented change is approved.
3. `tests/unit/status/test_openai_prompts.py` passes.
4. `make check-fmt`, `make lint`, `make typecheck`, and `make test` pass.

## Idempotence and recovery

The refactor is safe to repeat. If template rendering introduces any prompt
output drift, revert to the last passing state, re-run prompt tests, and
reintroduce template strings one helper at a time.
