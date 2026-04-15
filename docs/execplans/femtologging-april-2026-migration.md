# Upgrade Ghillie to femtologging SHA 691a73962df8f99308a82348d99c4f707c245e63

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & discoveries`,
`Decision log`, and `Outcomes & retrospective` must be kept up to date as work
proceeds.

Status: COMPLETE

## Purpose / big picture

Ghillie already runs on an older pre-release `femtologging` snapshot,
`7c139fb7aca18f9277e00b88604b8bf5eb471be0`. This plan upgrades Ghillie to the
new upstream `femtologging` commit `691a73962df8f99308a82348d99c4f707c245e63`,
which includes the `v0.1.0` migration changes and additional stdlib-style
Python APIs such as `getLogger`, `FemtoLogger.exception()`,
`FemtoLogger.info()`, and `FemtoLogger.isEnabledFor()`.

Success is observable when all of the following are true:

1. `pyproject.toml` and `uv.lock` both resolve `femtologging` to
   `691a73962df8f99308a82348d99c4f707c245e63`.
2. Ghillie's focused logging tests fail before the dependency bump and pass
   after it, proving the new upstream surface is available and Ghillie's
   wrappers and test helpers still work.
3. Ghillie's runtime, ingestion, reporting, and API middleware continue to
   emit the same event names, message schemas, and warning-level behaviour as
   before.
4. Repository documentation stops describing the old snapshot as current and
   no longer documents builder names removed by the `v0.1.0` migration guide.
5. `make fmt`, `make markdownlint`, `make nixie`, `make check-fmt`,
   `make lint`, `make typecheck`, and `make test` all pass when run
   sequentially.

## Constraints

- Upgrade the dependency to the exact upstream `femtologging` Git commit
  `691a73962df8f99308a82348d99c4f707c245e63`.
- Preserve Ghillie's current emitted event identifiers and field schemas,
  especially the observability events in `ghillie/github/observability.py` and
  `ghillie/reporting/observability.py`.
- Preserve Ghillie's percent-style logging wrapper contract in
  `ghillie/logging.py`. The new upstream convenience methods still require
  pre-formatted strings and do not support stdlib-style lazy `%` arguments.
- Treat `docs/execplans/adopt-femtologging.md` as a historical record unless
  the user explicitly asks to rewrite historical plans.
- Add or update tests before changing production code or the dependency pin,
  following the repository's red/green/refactor rules.
- Update the relevant docs in `docs/` so they describe the new dependency and
  API reality accurately.
- Run all quality gates through `tee` with `set -o pipefail`, and run Make
  targets sequentially because `make typecheck` and `make test` both rebuild
  `.venv`.

If any constraint cannot be met, stop and escalate.

## Tolerances

- Scope: if the upgrade requires changing more than 14 files outside
  `docs/`, `pyproject.toml`, `uv.lock`, `ghillie/logging.py`, and logging
  tests, stop and escalate. That would indicate upstream API drift beyond the
  expected migration surface.
- Behaviour: if event names, log message layouts, or `WARN` versus `WARNING`
  assertions must change in Ghillie's observability tests, stop and escalate.
- Dependency health: if `uv lock` cannot resolve the target SHA or the
  resulting wheel cannot be installed on the repository's Python 3.14 baseline,
  stop and escalate.
- Test helper compatibility: if `tests/helpers/femtologging_capture.py`
  requires more than small compatibility adjustments to keep working with the
  target SHA, stop and escalate.
- Documentation drift: if synchronizing `docs/femtologging-users-guide.md`
  requires a wholesale rewrite that cannot be reviewed confidently against the
  upstream guide for the target SHA, stop and escalate.

## Risks

- Risk: the custom capture helper in
  `tests/helpers/femtologging_capture.py` depends on `FemtoLogger.level`,
  `FemtoLogger.propagate`, `set_level()`, `set_propagate()`, `add_handler()`,
  and `remove_handler()`, none of which are mentioned in the upstream migration
  guide. Mitigation: add focused compatibility tests and run them immediately
  after updating the dependency.
- Risk: the repository's local `docs/femtologging-users-guide.md` is already
  stale relative to the target upstream users guide. Mitigation: compare the
  local guide against the upstream `docs/users-guide.md` at the target SHA and
  prefer synchronizing exact sections over ad hoc paraphrase.
- Risk: the new stdlib-like methods tempt a broad rewrite from
  `ghillie.logging.log_*` helpers to raw `logger.info()` calls, but that would
  silently lose percent-style formatting if done naively. Mitigation: keep the
  wrapper API stable for this migration and treat broader simplification as a
  separate follow-up.
- Risk: historical docs still describe the old snapshot commit and pre-v0.1.0
  limitations. Mitigation: update the ADR, roadmap, and current user docs, but
  leave the completed historical execplan untouched unless instructed otherwise.

## Progress

- [x] (2026-04-08 UTC) Verified that the requested SHA
  `691a73962df8f99308a82348d99c4f707c245e63` is an upstream `femtologging`
  commit, not a `ghillie` commit.
- [x] (2026-04-08 UTC) Inspected Ghillie's current `femtologging` usage,
  dependency pin, wrapper module, tests, and bundled docs.
- [x] (2026-04-08 UTC) Drafted this ExecPlan in
  `docs/execplans/femtologging-april-2026-migration.md`.
- [x] (2026-04-08 UTC) Added focused red/green logging tests proving the old
  pin lacked `getLogger`, `isEnabledFor`, and convenience methods, then
  verifying those surfaces after the upgrade.
- [x] (2026-04-08 UTC) Updated `pyproject.toml` and `uv.lock` to femtologging
  commit `691a73962df8f99308a82348d99c4f707c245e63`.
- [x] (2026-04-08 UTC) Kept `ghillie/logging.py` and
  `tests/helpers/femtologging_capture.py` unchanged because they remained
  compatible; only small type-checking cleanups were needed elsewhere to pass
  repository gates.
- [x] (2026-04-08 UTC) Updated current docs (`docs/femtologging-users-guide.md`,
  `docs/adr-001-adoption-of-femtologging-library.md`, and `docs/roadmap.md`) so
  they describe the new API and dependency reality.
- [x] (2026-04-08 UTC) Ran the full sequential quality gates and captured
  passing evidence for `make fmt`, `make markdownlint`, `make nixie`,
  `make check-fmt`, `make lint`, `make typecheck`, and `make test`.

## Surprises & discoveries

- Discovery: `git cat-file -t 691a73962df8f99308a82348d99c4f707c245e63`
  fails in this repository because the SHA is not a `ghillie` object. A GitHub
  API lookup confirms it is a `femtologging` commit dated
  2026-04-05.[^femtologging-sha]
- Discovery: Ghillie's production code does not call
  `StreamHandlerBuilder.with_flush_timeout_ms()` or
  `FileHandlerBuilder.with_flush_record_interval()` directly. The concrete
  `v0.1.0` breakage surface in this repository is mostly the dependency pin and
  stale documentation, not handler-builder code.
- Discovery: Ghillie's own wrapper in `ghillie/logging.py` exists mainly to
  preserve percent-style interpolation and to centralize `exc_info` handling.
  That wrapper is still useful after the upstream API becomes more stdlib-like.
- Discovery: `docs/femtologging-users-guide.md` still says convenience methods
  are not implemented and still documents `.with_flush_timeout_ms(...)`, which
  is inconsistent with the target SHA's upstream users guide.
- Discovery: `docs/adr-001-adoption-of-femtologging-library.md` and
  `docs/roadmap.md` still pin the old snapshot commit and describe the old API
  limitations as current facts.
- Discovery: the femtologging upgrade itself did not require runtime wrapper or
  capture-helper changes; the target SHA was backward-compatible with Ghillie's
  existing integration boundary.
- Discovery: recreating `.venv` for `make typecheck` surfaced three unrelated
  strict-typing issues in Falcon constructor calls and CLI float coercion.
  Minimal `typing.Any` casts replaced ineffective inline ignore comments so the
  repository gates stayed green.

[^femtologging-sha]:
    GitHub API lookup:
    `https://api.github.com/repos/leynos/femtologging/commits/691a73962df8f99308a82348d99c4f707c245e63`.
    The response identifies the commit as
    `https://github.com/leynos/femtologging/commit/691a73962df8f99308a82348d99c4f707c245e63`
    with author date `2026-04-05T17:29:10Z`.

## Decision log

- Decision: treat this work as an upgrade of the existing femtologging
  adoption, not a fresh migration away from stdlib logging. Rationale: Ghillie
  already depends on femtologging and routes all production logging through
  `ghillie/logging.py`.
- Decision: keep `ghillie/logging.py` as the public integration boundary during
  this upgrade. Rationale: it preserves percent-style formatting and lets the
  implementation switch between `logger.log(...)` and the new convenience
  methods without churn across runtime, ingestion, reporting, and tests.
- Decision: do not mass-rename `get_logger()` to `getLogger()` in Ghillie.
  Rationale: `get_logger()` remains supported, and the alias is primarily a
  compatibility feature for downstream callers, not a required codebase style
  change.
- Decision: do not plan around `StdlibHandlerAdapter` unless a concrete Ghillie
  use case appears during implementation. Rationale: Ghillie already has a
  working Python `handle_record` capture helper, and no current module uses a
  stdlib `logging.Handler` subclass.
- Decision: leave `docs/execplans/adopt-femtologging.md` unchanged unless the
  user asks otherwise. Rationale: it documents the January 2026 adoption work
  and should remain auditable as historical context.

## Context and orientation

The dependency pin previously lived in `pyproject.toml` and `uv.lock` at the
older femtologging snapshot `7c139fb7aca18f9277e00b88604b8bf5eb471be0`. Those
files now resolve to `691a73962df8f99308a82348d99c4f707c245e63`.

All production call sites already funnel through `ghillie/logging.py`. The
relevant consumers are:

- `ghillie/runtime.py`
- `ghillie/github/ingestion.py`
- `ghillie/github/observability.py`
- `ghillie/reporting/observability.py`
- `ghillie/reporting/service.py`
- `ghillie/silver/services.py`
- `ghillie/api/middleware.py`
- `tests/conftest.py`

The most important test support module is
`tests/helpers/femtologging_capture.py`. It manipulates the live `FemtoLogger`
object directly and therefore provides the fastest signal for unexpected
upstream API drift.

The upstream `v0.1.0` migration guide only lists these breaking Python-facing
changes:

- `StreamHandlerBuilder.with_flush_timeout_ms(...)` was renamed to
  `.with_flush_after_ms(...)`.
- `FileHandlerBuilder.with_flush_record_interval(...)` and
  `RotatingFileHandlerBuilder.with_flush_record_interval(...)` were renamed to
  `.with_flush_after_records(...)`.
- `as_dict()` keys and related validation messages were renamed to match the
  new builder method names.

The same target SHA also adds new APIs that Ghillie may choose to rely on but
does not strictly need to adopt immediately:

- `getLogger`
- `FemtoLogger.debug/info/warning/error/critical/exception`
- `FemtoLogger.isEnabledFor`
- `StdlibHandlerAdapter`

The local repository docs that are known to require attention are:

- `docs/adr-001-adoption-of-femtologging-library.md`
- `docs/roadmap.md`
- `docs/femtologging-users-guide.md`
- Any user-facing guidance that still treats the old snapshot as current

## Plan of work

1. Stage A: codify the target dependency surface with failing tests.

   Add focused tests before touching the dependency pin. Extend
   `tests/unit/test_logging.py` or add a sibling logging compatibility test
   module that proves the target SHA's expected upstream features are present
   and usable from Ghillie. The tests should check at least these cases:

   - `from femtologging import getLogger` succeeds and returns the same logger
     instance as `get_logger`.
   - `FemtoLogger` exposes `isEnabledFor(...)`.
   - `FemtoLogger.exception(...)` exists and captures `exc_info` in the same
     structured record payload path used by Ghillie's current capture helper.
   - Warning-level records still land in captured payloads as `WARN`, because
     several observability tests assert that exact value.

   Run only these focused tests first and confirm they fail against the old
   snapshot. If they already pass unexpectedly, document that in
   `Surprises & discoveries` before proceeding, because it would mean the
   current dependency already contains more of the target surface than the
   repository docs claim.

2. Stage B: bump the dependency and verify focused compatibility.

   Update `pyproject.toml` to pin
   `femtologging @ git+https://github.com/leynos/femtologging@691a73962df8f99308a82348d99c4f707c245e63`
    and refresh `uv.lock` using `uv lock` or the repository's standard
   dependency workflow. Re-run the focused logging tests immediately.

   If the only failures are in `tests/helpers/femtologging_capture.py` or
   `ghillie/logging.py`, fix them there first. Do not broaden the change into a
   call-site rewrite unless the focused failures prove the wrapper boundary is
   insufficient.

3. Stage C: keep Ghillie's integration boundary compatible.

   Decide whether `ghillie/logging.py` should remain implemented in terms of
   `logger.log(...)` or switch internally to the new convenience methods. The
   safe default is to keep the public wrapper signatures unchanged and only
   adjust internals if it reduces complexity without changing behaviour.

   If any call-site updates become necessary, keep them narrowly scoped to the
   modules that already import `ghillie.logging`. Preserve message text, event
   names, and exception payload handling. Do not replace wrapper calls with raw
   stdlib-style `logger.info("x %s", y)` patterns, because femtologging still
   expects a pre-formatted string.

4. Stage D: update bundled docs and current references.

   Update the current docs so they reflect the new dependency and API reality:

   - `docs/adr-001-adoption-of-femtologging-library.md` should replace the old
     snapshot pin, stop claiming convenience methods are absent, and describe
     the upgrade as the new current state.
   - `docs/roadmap.md` should stop pointing at the old snapshot commit in the
     completed femtologging task notes.
   - `docs/femtologging-users-guide.md` should be synchronized with the target
     upstream users guide sections that changed. At minimum, fix the builder
     method names, convenience-method guidance, and any notes about `getLogger`
     and `isEnabledFor`.

   Validate doc updates with grep as well as normal Markdown gates so the old
   renamed builder methods do not linger in current docs accidentally.

5. Stage E: run full repository validation and capture evidence.

   Once focused logging tests and docs are complete, run the full repository
   gates sequentially. Use the logged outputs both as proof of success and as
   immediate debugging input if a later gate fails after the dependency bump.

## Concrete commands

Use commands like the following during implementation. Keep them sequential,
capture output with `tee`, and inspect the logs if any command fails.

```bash
set -o pipefail
LOG=/tmp/ghillie-femtologging-focused-pytest.log
uv run pytest \
  tests/unit/test_logging.py \
  tests/unit/test_github_observability.py \
  tests/unit/test_github_ingestion_observability.py \
  tests/unit/test_reporting_observability.py \
  -v | tee "$LOG"
```

```bash
set -o pipefail
uv lock | tee /tmp/ghillie-femtologging-uv-lock.log
```

```bash
set -o pipefail
make fmt | tee /tmp/ghillie-femtologging-fmt.log
make markdownlint | tee /tmp/ghillie-femtologging-markdownlint.log
make nixie | tee /tmp/ghillie-femtologging-nixie.log
make check-fmt | tee /tmp/ghillie-femtologging-check-fmt.log
make lint | tee /tmp/ghillie-femtologging-lint.log
make typecheck | tee /tmp/ghillie-femtologging-typecheck.log
make test | tee /tmp/ghillie-femtologging-test.log
```

Use grep checks to confirm stale documentation and dependency pins are gone:

```bash
PATTERN="7c139fb7aca18f9277e00b88604b8bf5eb471be0"
PATTERN="$PATTERN|with_flush_timeout_ms|with_flush_record_interval"
PATTERN="$PATTERN|Convenience methods .*not implemented yet"
rg -n "$PATTERN" \
  pyproject.toml \
  uv.lock \
  docs/adr-001-adoption-of-femtologging-library.md \
  docs/roadmap.md \
  docs/femtologging-users-guide.md
```

The final grep should return no matches in those current docs or dependency
files.

## Validation and acceptance

The migration is complete only when all of the following are true:

1. The focused logging compatibility tests fail before the dependency bump and
   pass after it.
2. `pyproject.toml` and `uv.lock` both point at
   `691a73962df8f99308a82348d99c4f707c245e63`.
3. Existing observability tests still pass without changing event names,
   message structure, or the `WARN` expectation.
4. `docs/adr-001-adoption-of-femtologging-library.md`,
   `docs/roadmap.md`, and `docs/femtologging-users-guide.md` no longer describe
   the old snapshot as current.
5. Full sequential repository gates pass:
   `make fmt`, `make markdownlint`, `make nixie`, `make check-fmt`,
   `make lint`, `make typecheck`, and `make test`.

Expected high-signal evidence includes:

```plaintext
tests/unit/test_logging.py::test_femtologging_exposes_get_logger_alias PASSED
tests/unit/test_logging.py::test_femtologging_logger_exposes_is_enabled_for PASSED
tests/unit/test_logging.py::test_femtologging_logger_exception_captures_exc_info PASSED
tests/unit/test_logging.py::test_femtologging_logger_warning_method_uses_warn_level PASSED
```

```plaintext
Resolved femtologging dependency:
git+https://github.com/leynos/femtologging@691a73962df8f99308a82348d99c4f707c245e63
```

## Open questions and gaps

- The user request says, "plan the migration of `ghillie` to `femtologging` at
  SHA `691a73962df8f99308a82348d99c4f707c245e63`", but does not name the repo
  that SHA belongs to. Research shows it is a `femtologging` commit, not a
  `ghillie` commit. Implementation should proceed with that interpretation
  unless the user says otherwise.
- The local `docs/femtologging-users-guide.md` appears to be a bundled copy of
  upstream guidance and is already stale in multiple places. If the team wants
  this file to remain a verbatim upstream snapshot, the implementation should
  replace the relevant sections from upstream rather than editing the prose
  freely.
- The historical January 2026 execplan still points at the old snapshot. This
  plan assumes historical execplans remain unchanged, but if the team wants all
  repo references to point only at the current SHA, that policy needs explicit
  confirmation first.

## Outcomes & retrospective

- The dependency now resolves to femtologging commit
  `691a73962df8f99308a82348d99c4f707c245e63` in both `pyproject.toml` and
  `uv.lock`.
- Focused tests were added to `tests/unit/test_logging.py` to prove the new
  upstream surface exists: `getLogger`, `FemtoLogger.isEnabledFor()`,
  `FemtoLogger.exception()`, and `FemtoLogger.warning()` preserving `WARN`
  records. These tests failed before the bump and passed after it.
- Existing observability behaviour stayed intact. Focused post-upgrade
  validation passed for: `tests/unit/test_logging.py`,
  `tests/unit/test_github_observability.py`,
  `tests/unit/test_github_ingestion_observability.py`, and
  `tests/unit/test_reporting_observability.py`.
- Current documentation now matches the target upstream guide for the changed
  Python API surface and builder names, while the historical
  `docs/execplans/adopt-femtologging.md` record was intentionally left
  unchanged.
- Full gate evidence on 2026-04-08 UTC:
  - `make fmt`
  - `make markdownlint`
  - `make nixie`
  - `make check-fmt`
  - `make lint`
  - `make typecheck`
  - `make test` (`775 passed, 35 skipped`)
- Lesson: for dependency upgrades that rebuild `.venv`, expect current static
  analysis tools to re-evaluate nearby type suppressions. Keep compatibility
  fixes minimal and separate from the functional migration intent.
