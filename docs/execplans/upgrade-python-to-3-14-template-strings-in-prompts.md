# Upgrade Python to 3.14: template strings in prompts

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & discoveries`, `Decision log`, and
`Outcomes & retrospective` must be kept up to date as work proceeds.

Status: BLOCKED on repository-wide Python 3.14 baseline uplift

No `PLANS.md` file exists in this repository.

## Purpose / big picture

`ghillie/status/prompts.py` currently builds the user prompt with ordinary
string literals and f-strings. Python 3.14 adds template string literals
(`t"..."`), which produce structured `string.templatelib.Template` values
instead of plain `str`. This activity adopts template strings in the prompt
construction path while preserving the exact prompt text sent to the model.

This is not a general prompt redesign. The work is only valuable if the
repository has already moved to Python 3.14 and if prompt output remains
byte-for-byte stable for representative evidence bundles.

Success is observable when:

1. `ghillie/status/prompts.py` uses template strings in the agreed
   interpolation-heavy prompt sections.
2. `build_user_prompt()` still returns `str`, and the prompt text is unchanged
   for the same evidence input.
3. Prompt-focused unit tests cover exact output for representative evidence
   bundles.
4. Full quality gates and Markdown gates pass.

## Constraints

- Treat the Python 3.14 baseline uplift as a hard prerequisite. As of
  2026-03-09, `pyproject.toml` still declares `requires-python = ">=3.12"` and
  Ruff still targets `py312`, so this task must not land syntax changes until
  that separate uplift is complete.
- Keep scope limited to `ghillie/status/prompts.py`, prompt-focused tests in
  `tests/unit/status/`, and any directly-related documentation updates.
- Preserve user-visible prompt semantics and formatting exactly unless a prompt
  content change is explicitly approved.
- Do not change `OpenAIStatusModel` request payload shape, prompt ordering, or
  response parsing behaviour.
- Do not add dependencies or introduce a compatibility layer for Python 3.12.
- Keep the template rendering approach obvious to contributors who have not yet
  used `string.templatelib`.

## Tolerances (exception triggers)

- Scope: if implementation requires changes to more than 6 files or 240 net
  lines, stop and escalate.
- Prerequisites: if the repository-wide Python 3.14 uplift has not been merged
  first, stop after updating this plan and do not implement code changes.
- Behaviour: if prompt output changes outside tests intended to prove exact
  equivalence, stop and escalate.
- Complexity: if rendering template strings back to `str` needs more than
  100 lines of helper code, stop and simplify or escalate.
- Iterations: if prompt tests or `make typecheck` fail after 3 focused fix
  attempts, stop and escalate.
- Ambiguity: if Python 3.14 template-string APIs behave differently than the
  prototype documented below, stop and record the discrepancy before changing
  production code.

## Risks

- Risk: template strings evaluate to `Template`, not `str`, so returning or
  serializing the object directly would change the payload sent to the OpenAI
  client. Severity: high. Likelihood: medium. Mitigation: keep rendering local
  to prompt helpers and add exact-output regression tests.
- Risk: newline or whitespace drift changes model behaviour even if the prompt
  still looks similar to a human reviewer. Severity: high. Likelihood: medium.
  Mitigation: use full-string assertions for representative evidence bundles,
  not only fragment assertions.
- Risk: partial Python 3.14 uplift leaves the task in a state where `t"..."`
  parses in one environment but fails in project tooling. Severity: high.
  Likelihood: medium. Mitigation: make the baseline uplift an explicit
  prerequisite and verify `requires-python` plus Ruff target before editing
  prompt code.
- Risk: overusing template strings in static sections reduces readability with
  no practical value. Severity: low. Likelihood: medium. Mitigation: limit
  adoption to interpolation-heavy lines and keep plain literals for static
  blocks.

## Progress

- [x] (2026-02-24 00:00Z) Draft ExecPlan created at
  `docs/execplans/upgrade-python-to-3-14-template-strings-in-prompts.md`.
- [x] (2026-03-09 00:00Z) Confirm current repository baseline is still Python
  3.12 (`pyproject.toml` has `requires-python = ">=3.12"` and Ruff target
  `py312`).
- [x] (2026-03-09 00:00Z) Confirm prompt construction currently lives only in
  `ghillie/status/prompts.py` and is consumed by
  `ghillie/status/openai_client.py`.
- [x] (2026-03-09 00:00Z) Prototype Python 3.14 template-string behaviour in
  the local `.venv` interpreter and record the rendering implications below.
- [ ] Wait for the repository-wide Python 3.14 baseline uplift to merge.
- [ ] Add failing exact-output prompt tests in
  `tests/unit/status/test_openai_prompts.py`.
- [ ] Refactor selected prompt-building lines to template strings while keeping
  `build_user_prompt()` return type as `str`.
- [ ] Run targeted prompt tests and then full quality gates.
- [ ] Run Markdown gates for this updated ExecPlan.

## Surprises & discoveries

- As of 2026-03-09, this task is genuinely blocked on the repository baseline:
  the source tree is still configured for Python 3.12, so `t"..."` syntax would
  be invalid in normal project tooling even though a local `uv`-managed Python
  3.14 environment can be created.
- A local prototype under `./.venv/bin/python` confirmed that
  `t"Repository: {name}"` produces `string.templatelib.Template`, with
  `strings`, `interpolations`, and `values` accessors. Iterating a template
  yields alternating literal strings and `Interpolation(...)` objects rather
  than a rendered string.
- The prompt module is smaller than the draft implied. Today the relevant
  interpolation sites are concentrated in:
  - `_format_previous_reports()`
  - `_format_work_type_breakdown()`
  - `_format_pull_requests()`
  - `_format_issues()`
  - the opening section of `build_user_prompt()`
- Current tests in `tests/unit/status/test_openai_prompts.py` assert the
  presence of important fragments, but they do not yet lock the exact prompt
  output for a rich evidence bundle. That is the main regression gap this task
  must close before refactoring.
- Prior project notes already document a Python 3.14 compatibility issue with
  Granian. `docs/execplans/2-3-3-on-demand-reporting-entry-point.md` records
  that the constraint must allow Granian 2.7.1+ for Python 3.14 support. This
  plan assumes that prerequisite uplift is solved elsewhere rather than trying
  to solve it here.

## Decision log

- Decision: mark this ExecPlan as blocked rather than pretending the baseline
  uplift is already complete. Rationale: the repository state on 2026-03-09
  does not satisfy the documented prerequisite.
- Decision: use a tiny private rendering helper in `ghillie/status/prompts.py`
  if one is needed, but do not create a general templating abstraction.
  Rationale: prompt code has only a handful of interpolation sites.
- Decision: add exact full-output tests before refactoring prompt code.
  Rationale: prompt formatting is part of model behaviour, so fragment-only
  tests are not strict enough for this migration.
- Decision: limit template-string adoption to dynamic prompt lines, not the
  large static `SYSTEM_PROMPT` block. Rationale: the system prompt does not
  currently interpolate values, so `t"..."` would add novelty without benefit.

## Outcomes & retrospective

Not started. Populate after the Python 3.14 uplift is complete and the prompt
refactor lands.

## Context and orientation

Primary code and tests:

- `ghillie/status/prompts.py`
- `ghillie/status/openai_client.py`
- `tests/unit/status/test_openai_prompts.py`
- `pyproject.toml`

Current prompt flow:

1. `OpenAIStatusModel.summarize_repository()` calls `build_user_prompt()`.
2. `build_user_prompt()` returns a plain string built from a `list[str]` and
   `"\n".join(...)`.
3. `_build_payload()` embeds that string directly into the `"messages"` list
   sent to the OpenAI-compatible endpoint.

Prototype findings from Python 3.14:

```python
from string.templatelib import Template

name = "octo/reef"
template = t"Repository: {name}"

assert type(template).__name__ == "Template"
assert template.strings == ("Repository: ", "")
assert template.interpolations[0].value == "octo/reef"
```

The important consequence is that this task needs an explicit rendering step.
The simplest acceptable approach is to keep template-string usage local and
convert each `Template` to `str` immediately when appending lines to the prompt
section lists.

## Plan of work

Stage A resolves the prerequisite boundary. Do not touch prompt syntax until
the repository-wide Python 3.14 uplift has landed and project tooling is
updated accordingly.

Stage B is tests-first. Expand `tests/unit/status/test_openai_prompts.py` with
exact-output assertions for a representative evidence bundle containing prior
reports, work-type groupings, pull requests, issues, and documentation changes.

Stage C performs the narrow refactor. Convert interpolation-heavy prompt lines
from f-strings to template strings, render them back to `str` locally, and
leave static prompt content alone.

Stage D validates behaviour and project health. Run targeted prompt tests, then
run the full repository gates required for Python and Markdown changes.

## Concrete steps

1. Confirm the prerequisite uplift is complete before coding.

   - `rg -n "requires-python|target-version" pyproject.toml`
   - Proceed only after the file reports Python 3.14-compatible values.
   - Confirm any Granian-related uplift work is already resolved; see
     `docs/execplans/2-3-3-on-demand-reporting-entry-point.md`.

2. Add failing regression tests first.

   - Extend `tests/unit/status/test_openai_prompts.py` with a rich evidence
     fixture and one exact-output assertion for the full prompt text.
   - Keep existing fragment assertions if they still add value, but the new
     full-string assertion becomes the main regression guard.
   - Run the targeted test file and confirm the new expectation fails before
     refactoring prompt code.

3. Refactor prompt construction narrowly.

   - Update `ghillie/status/prompts.py` so selected dynamic lines use
     template-string literals.
   - Keep `build_user_prompt()` returning `str`.
   - If a helper is needed, keep it private and tiny, for example a helper that
     converts a `Template` to `str` immediately at the append-site.
   - Do not change the structure or ordering of prompt sections.

4. Validate targeted prompt behaviour.

   - Run:

     ```bash
     set -o pipefail; uv run pytest tests/unit/status/test_openai_prompts.py 2>&1 | tee /tmp/ghillie-template-prompts-targeted.log
     ```

   - Review `/tmp/ghillie-template-prompts-targeted.log` to confirm the exact
     output regression test and the existing prompt tests all pass.

5. Run full quality and documentation gates.

   - Run:

     ```bash
     set -o pipefail; make fmt 2>&1 | tee /tmp/ghillie-template-prompts-fmt.log
     set -o pipefail; make check-fmt 2>&1 | tee /tmp/ghillie-template-prompts-check-fmt.log
     set -o pipefail; make lint 2>&1 | tee /tmp/ghillie-template-prompts-lint.log
     set -o pipefail; make typecheck 2>&1 | tee /tmp/ghillie-template-prompts-typecheck.log
     set -o pipefail; make test 2>&1 | tee /tmp/ghillie-template-prompts-test.log
     set -o pipefail; MDLINT=/root/.bun/bin/markdownlint-cli2 make markdownlint 2>&1 | tee /tmp/ghillie-template-prompts-markdownlint.log
     set -o pipefail; make nixie 2>&1 | tee /tmp/ghillie-template-prompts-nixie.log
     ```

## Validation and acceptance

This activity is complete when all of the following are true:

1. The repository baseline has already been uplifted to Python 3.14, including
   `pyproject.toml` metadata and Ruff target version.
2. `ghillie/status/prompts.py` uses template strings in the agreed dynamic
   prompt-building paths.
3. `build_user_prompt()` still returns `str`.
4. `tests/unit/status/test_openai_prompts.py` contains an exact-output
   regression test for a representative evidence bundle.
5. `make check-fmt`, `make lint`, `make typecheck`, `make test`,
   `make markdownlint`, and `make nixie` pass.

## Idempotence and recovery

This work is safe to repeat once the prerequisite uplift is present. If the
prompt text changes unexpectedly, revert the prompt-module edits, keep the new
exact-output tests, and reintroduce template strings one helper or section at a
time until the first differing line is isolated.
