# Upgrade Python to 3.14: lazy annotations

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & discoveries`, `Decision log`, and
`Outcomes & retrospective` must be kept up to date as work proceeds.

Status: COMPLETE

No `PLANS.md` file exists in this repository.

## Purpose / big picture

Python 3.14 evaluates annotations lazily by default. Ghillie previously
carried many `from __future__ import annotations` statements and Ruff enforced
them via rule `FA`. This activity removes those future imports where Python
3.14 semantics make them redundant, aligns lint and packaging metadata with
Python 3.14, and keeps future imports only in modules where runtime annotation
inspection still requires them to preserve behaviour.

Success is observable when:

1. `pyproject.toml` no longer enforces Ruff `FA` and now declares Python 3.14.
2. Future imports are removed from simple executable modules and retained only
   where `msgspec` or runtime annotation inspection still require them.
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
  materialization behaviour. Severity: medium. Likelihood: low. Mitigation: run
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
- [x] (2026-03-09 03:08Z) Confirm baseline: `rg` found 200 executable Python
  files with `from __future__ import annotations`; `pyproject.toml` initially
  set Ruff `target-version = "py312"`, `requires-python = ">=3.12"`, and
  included Ruff rule `FA`.
- [x] (2026-03-09 03:08Z) Record behavioural baseline by running targeted tests
  before refactor: `uv run pytest tests/unit/test_runtime.py` passed (9 tests)
  and `uv run pytest tests/unit/status/test_openai_parsing.py` passed (28
  tests).
- [x] (2026-03-09 03:10Z) Remove future-annotations imports from executable
  Python files in `ghillie/`, `tests/`, and `scripts/`.
- [x] (2026-03-09 03:11Z) Update `pyproject.toml` lint configuration to drop
  `FA` enforcement.
- [x] (2026-03-09 03:11Z) Update docs that prescribe
  `from __future__ import annotations` as a required convention.
- [x] (2026-03-09 03:14Z) Align repository Python baseline with the new source
  semantics by updating `pyproject.toml`, `Dockerfile`, and primary developer
  documentation to Python 3.14.
- [x] (2026-03-09 03:24Z) Run formatting, linting, type checking, tests, and
  Markdown gates. `make fmt`, `make check-fmt`, `make lint`, `make typecheck`,
  `make test`, `make markdownlint`, and `make nixie` all passed. Full test
  suite result: 712 passed, 35 skipped.

## Surprises & discoveries

- `python --version` in the base shell is still 3.12.3, but `uv run` selected
  CPython 3.14.3 and created `.venv` on first use.
- The mechanical removal touched exactly 200 executable Python files, which
  stayed within the 260-file tolerance.
- The first `make lint` run showed that keeping `target-version = "py312"` and
  `requires-python = ">=3.12"` makes the migration inconsistent: Ruff emitted
  `TC004` and `F821` diagnostics because the declared baseline still assumed
  pre-3.14 annotation handling.
- `msgspec.Struct` on Python 3.14.3 currently does not populate struct fields
  correctly under default lazy annotations, but works when the defining module
  keeps `from __future__ import annotations`.
- `pytest-bdd`, `unittest.mock(spec=...)`, and other annotation-inspection
  paths can evaluate annotations at runtime under Python 3.14. Modules that
  hide required names behind `TYPE_CHECKING` therefore still need the future
  import unless those imports are made runtime-visible.

## Decision log

- Decision: keep this activity focused on annotation semantics and lint policy,
  not broader Python 3.14 feature adoption. Rationale: limits blast radius and
  makes regressions easier to isolate.
- Decision: remove future imports only from executable Python sources in this
  task. Rationale: code snippets in historical design notes can be addressed in
  a separate documentation cleanup if required.
- Decision: do not widen `pyproject.toml` Python metadata in this change even
  though `uv run` uses Python 3.14. Rationale: the accepted success criteria
  for this ExecPlan are removal of executable future imports and Ruff `FA`
  enforcement, not the broader repository baseline uplift tracked by other
  Python 3.14 plans.
- Decision: reverse the earlier metadata-scoping assumption and uplift the
  declared Python baseline to 3.14 in this change. Rationale: once executable
  sources rely on default lazy annotations, advertising Python 3.12 support is
  incorrect for both package consumers and Ruff's static analysis.
- Decision: retain `from __future__ import annotations` in modules that define
  `msgspec.Struct` types or depend on runtime annotation inspection while
  continuing to remove it elsewhere. Rationale: this is the smallest
  behaviour-preserving workaround available with current dependencies and test
  tooling on Python 3.14.

## Outcomes & retrospective

- Changed: upgraded declared Python baseline to 3.14, removed Ruff `FA`,
  removed redundant future imports from many executable modules, and updated
  core developer/operator documentation to the new baseline.
- Worked: targeted behavioural tests plus full quality gates caught the exact
  modules that still depend on stringified annotations.
- Follow-up: when `msgspec` and the repository's annotation-inspection paths
  become fully Python-3.14-native, a smaller cleanup can remove the remaining
  125 future imports.

## Context and orientation

Key files and references:

- `pyproject.toml` now needs Ruff `target-version = "py314"`, no `FA` lint
  rule, and `requires-python = ">=3.14"` so metadata matches source semantics.
- `ghillie/`, `tests/`, and `scripts/` currently include many
  `from __future__ import annotations` lines.
- Existing tests validating broad runtime behaviour include:
  - `tests/unit/test_runtime.py`
  - `tests/unit/test_reporting_run_for_repository.py`
  - `tests/unit/status/test_openai_parsing.py`

This migration remained behaviour-preserving, but it was not purely
mechanical. Python 3.14 exposed two compatibility classes that still require
stringified annotations today: `msgspec` struct definitions and modules whose
annotations are inspected at runtime while referenced names live under
`TYPE_CHECKING`.

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
   - Set `requires-python = ">=3.14"` and `target-version = "py314"` so lint
     and packaging both reflect lazy-annotation semantics.
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

1. Ruff no longer enforces `FA` in `pyproject.toml`, and repository metadata
   reflects Python 3.14.
2. Future imports are removed everywhere they are behaviourally redundant and
   retained only in compatibility-critical modules.
3. `make check-fmt`, `make lint`, `make typecheck`, `make test`,
   `make markdownlint`, and `make nixie` pass.
4. Targeted pre-refactor behavioural tests still pass after migration.

## Idempotence and recovery

The migration is idempotent: removing an already-removed future import,
reinstating it in a compatibility-critical module, and re-running gates are
safe operations. If behaviour changes unexpectedly, restore the affected
files, re-run baseline tests, and re-apply the migration in smaller batches by
compatibility class (`msgspec`, runtime annotation inspection, then simple
modules).
