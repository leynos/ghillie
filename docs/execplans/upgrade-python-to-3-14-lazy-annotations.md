# Upgrade Python to 3.14: lazy annotations

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`, and
`Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: DRAFT

No `PLANS.md` file exists in this repository.

## Purpose / big picture

Python 3.14 evaluates annotations lazily by default. Ghillie currently carries
many `from __future__ import annotations` statements and Ruff enforces them via
rule `FA`. This activity removes those now-redundant future imports from
executable Python modules, aligns lint configuration with Python 3.14
semantics, and keeps runtime behaviour unchanged.

Success is observable when:

1. `rg -n "from __future__ import annotations" ghillie tests scripts` returns
   no matches.
2. `pyproject.toml` no longer enforces Ruff `FA`.
3. Runtime behaviour remains unchanged, and all quality gates pass.

## Constraints

- Keep scope limited to lazy-annotation migration.
- Do not change public interfaces, command-line contracts, API payload shapes,
  or persistence schemas.
- Do not introduce new dependencies.
- Preserve existing import conventions (`typing as typ`, `datetime as dt`, and
  similar aliases).
- Keep all Markdown updates wrapped at 80 columns and consistent with
  `docs/documentation-style-guide.md`.
- If this migration reveals a behavioural difference, stop and escalate instead
  of silently changing semantics.

## Tolerances (exception triggers)

- Scope: if migration requires changes to more than 260 files or 3500 net
  lines, stop and escalate.
- Interfaces: if any public API signature must change to complete this task,
  stop and escalate.
- Dependencies: if a compatibility helper from `typing_extensions` appears
  necessary, stop and escalate.
- Iterations: if quality gates fail after 3 focused fix attempts, stop and
  escalate.
- Ambiguity: if a module depends on stringified annotations at runtime and
  behaviour is uncertain, stop and present options with trade-offs.

## Risks

- Risk: some runtime reflection path may rely on the previous annotation
  materialisation behaviour. Severity: medium. Likelihood: low. Mitigation: run
  targeted runtime tests around SQLAlchemy models and reporting services, then
  run full quality gates.
- Risk: partial migration leaves stale `FA` lint policy or residual future
  imports. Severity: low. Likelihood: medium. Mitigation: use explicit `rg`
  checks in acceptance criteria.
- Risk: docs drift (Python guidance still references legacy annotation import).
  Severity: medium. Likelihood: medium. Mitigation: update developer-facing
  docs in the same change.

## Progress

- [x] (2026-02-24 00:00Z) Draft ExecPlan at
  `docs/execplans/upgrade-python-to-3-14-lazy-annotations.md`.
- [ ] Confirm baseline: count all future-annotations imports and current Ruff
  settings.
- [ ] Record behavioural baseline by running targeted tests before refactor.
- [ ] Remove future-annotations imports from executable Python files in
  `ghillie/`, `tests/`, and `scripts/`.
- [ ] Update `pyproject.toml` lint configuration to drop `FA` enforcement.
- [ ] Update docs that prescribe `from __future__ import annotations` as a
  required convention.
- [ ] Run formatting, linting, type checking, tests, and Markdown gates.

## Surprises & Discoveries

- None yet. Update this section with concrete findings during implementation.

## Decision Log

- Decision: keep this activity focused on annotation semantics and lint policy,
  not broader Python 3.14 feature adoption. Rationale: limits blast radius and
  makes regressions easier to isolate.
- Decision: remove future imports only from executable Python sources in this
  task. Rationale: code snippets in historical design notes can be addressed in
  a separate documentation cleanup if required.

## Outcomes & Retrospective

Not started. Populate after implementation with what changed, what worked, and
what should be improved in follow-up tasks.

## Context and orientation

Key files and references:

- `pyproject.toml` currently sets Ruff `target-version = "py312"` and includes
  `FA` in lint `select`.
- `ghillie/`, `tests/`, and `scripts/` currently include many
  `from __future__ import annotations` lines.
- Existing tests validating broad runtime behaviour include:
  - `tests/unit/test_runtime.py`
  - `tests/unit/test_reporting_run_for_repository.py`
  - `tests/unit/status/test_openai_parsing.py`

This migration is intentionally mechanical. It should not alter domain logic,
API behaviour, or storage behaviour.

## Plan of work

Stage A establishes a baseline. Count existing future imports, confirm current
Ruff settings, and run a targeted pre-refactor test slice so the refactor can
be validated as behaviour-preserving.

Stage B performs the mechanical code migration. Remove future-annotations
imports from executable Python files, then update Ruff lint selection so `FA`
is no longer required under Python 3.14.

Stage C updates docs and validates. Adjust developer documentation where
`from __future__ import annotations` is currently mandated. Run full quality
and Markdown gates and confirm the migration is complete with `rg` checks.

## Concrete steps

1. Baseline checks.

   - `rg -n "from __future__ import annotations" ghillie tests scripts`
   - `rg -n "\"FA\"|target-version|requires-python" pyproject.toml`

2. Run targeted pre-refactor tests.

   - Run `uv run pytest tests/unit/test_runtime.py` with `set -o pipefail`,
     then capture output with `tee /tmp/la-runtime.log`.
   - Run `uv run pytest tests/unit/status/test_openai_parsing.py` with
     `set -o pipefail`, then capture output with `tee /tmp/la-openai.log`.

3. Remove `from __future__ import annotations` lines from executable Python
   files (`ghillie/`, `tests/`, `scripts/`).

4. Update `pyproject.toml`.

   - Remove Ruff rule `FA` from `tool.ruff.lint.select`.
   - Update comments in lint config if they reference mandatory future imports.

5. Update documentation that currently mandates future annotations
   (for example `docs/scripting-standards.md` and any style references).

6. Run gates with logs.

   - `set -o pipefail; make fmt 2>&1 | tee /tmp/ghillie-lazy-annotations-fmt.log`
   - `set -o pipefail; make check-fmt 2>&1 | tee /tmp/ghillie-lazy-annotations-check-fmt.log`
   - `set -o pipefail; make lint 2>&1 | tee /tmp/ghillie-lazy-annotations-lint.log`
   - `set -o pipefail; make typecheck 2>&1 | tee /tmp/ghillie-lazy-annotations-typecheck.log`
   - `set -o pipefail; make test 2>&1 | tee /tmp/ghillie-lazy-annotations-test.log`
   - `set -o pipefail; make markdownlint 2>&1 | tee /tmp/ghillie-lazy-annotations-markdownlint.log`
   - `set -o pipefail; make nixie 2>&1 | tee /tmp/ghillie-lazy-annotations-nixie.log`

## Validation and acceptance

The activity is complete when all of the following are true:

1. No executable Python file in `ghillie/`, `tests/`, or `scripts/` contains
   `from __future__ import annotations`.
2. Ruff no longer enforces `FA` in `pyproject.toml`.
3. `make check-fmt`, `make lint`, `make typecheck`, `make test`,
   `make markdownlint`, and `make nixie` pass.
4. Targeted pre-refactor behavioural tests still pass after migration.

## Idempotence and recovery

The migration is idempotent: removing an already-removed future import and
re-running gates are safe operations. If behaviour changes unexpectedly,
restore the affected files, re-run baseline tests, and re-apply the migration
in smaller batches by package.
