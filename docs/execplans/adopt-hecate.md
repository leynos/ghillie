# Adopt Hecate for hexagonal architecture checks

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`,
and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: COMPLETE

The user approved implementation on 2026-06-01. The branch now carries the
plan, prior review material, the Hecate architecture gate, documentation
updates, validation results, and incremental implementation commits.

## Purpose / big picture

Ghillie currently documents a hexagonal ports-and-adapters architecture and
maintains important seams with protocol-focused unit and behavioural tests, but
it does not have a dedicated automated import-direction gate. After this plan
is approved and implemented, Ghillie will use
[Hecate](https://github.com/leynos/hecate) at commit
`46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12` as the canonical architecture
fitness function for Python import boundaries.

A maintainer will be able to run `make check-architecture` from the repository
root and see Hecate check `ghillie` imports against a TOML policy. Continuous
Integration (CI) will run the same gate before tests. Behavioural tests will
remain responsible for runtime behaviour, while Hecate will own static
dependency-direction drift detection.

This work uses the `leta`, `hexagonal-architecture`, and `execplans` skills. Use
`leta` for code navigation, the `hexagonal-architecture` skill for boundary
decisions, and the `execplans` skill for keeping this plan current. If Rust
code is touched unexpectedly, route through the `rust-router` skill before
making changes.

## Constraints

- Do not implement this plan until the user explicitly approves it.
- Pin Hecate to commit `46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12`; do not use a
  floating branch or version range for the initial adoption.
- Keep project behaviour unchanged. This migration adds a development and CI
  architecture gate; it must not alter the public `ghillie` Python API, the
  `ghillie` command-line interface (CLI), HTTP API responses, storage schema,
  or runtime configuration.
- Keep behaviour-heavy tests for reporting, CLI user experience, model
  selection, ingestion, local Kubernetes tooling, and storage semantics.
  Replace only tests or assertions that exist solely to enforce import
  boundaries or protocol placement.
- Prefer Makefile targets over direct commands. Use `tee` for long-running
  gates, writing logs under `/tmp`.
- Run `make check-fmt`, `make lint`, `make typecheck`, and `make test`
  sequentially before every CodeRabbit review request and before committing
  implementation changes.
- Run documentation gates after Markdown changes: `make markdownlint` and
  `make nixie`.
- Do not mark any roadmap task done until the Hecate migration itself is
  implemented, validated, reviewed, and committed. This planning branch must
  not claim feature completion.

## Tolerances (exception triggers)

- Scope: if implementation requires changes to more than 12 files or more than
  500 net lines outside generated lockfile changes, stop, and request approval.
- Interface: if any public API signature, CLI option, HTTP route, database
  table, or environment variable must change, stop and request approval.
- Dependencies: Hecate is the only new dependency authorized by this plan. If
  another dependency appears necessary, stop and request approval.
- Policy exceptions: if more than five `[[tool.hecate.ignore_imports]]` entries
  are required for the initial pass, stop and present the violations for human
  review.
- Architecture ambiguity: if a module can reasonably belong to two groups and
  the choice changes allowed imports, record the alternatives and ask for
  direction.
- Validation: if any gate still fails after two focused fix attempts, stop,
  document the failure, and ask for direction.
- CodeRabbit: if CodeRabbit raises a concern after a milestone, clear it or
  document why it is not applicable before moving to the next milestone.

## Risks

- Risk: Hecate's first-match group ordering may classify a module into a broad
  group before a more specific one. Severity: high. Likelihood: medium.
  Mitigation: order specific composition-root and adapter prefixes before
  broader package prefixes, and add a policy test that checks representative
  modules land in the intended groups.

- Risk: Ghillie's current module layout mixes Medallion data layers, application
  services, and adapters, so an overly strict first policy could produce noisy
  violations. Severity: high. Likelihood: medium. Mitigation: start with a
  documented policy that matches the current intended boundaries, add only
  justified ignores, and escalate if the policy would require structural
  refactoring beyond this adoption.

- Risk: replacing broad protocol or wiring tests with Hecate could accidentally
  remove behaviour coverage. Severity: medium. Likelihood: medium. Mitigation:
  remove or rewrite only assertions that duplicate import-boundary checks. Keep
  tests that exercise user-visible behaviour, runtime adapter behaviour, retry
  logic, metrics, and CLI output.

- Risk: pinning Hecate from Git may make CI sensitive to network or resolver
  behaviour. Severity: medium. Likelihood: low. Mitigation: add Hecate to the
  existing `uv` dependency workflow, commit the lockfile update if one is
  produced, and validate in a clean `make build`.

- Risk: Hecate's pinned CLI uses Cyclopts APIs that are incompatible with
  Ghillie's previous `cyclopts>=2.9,<3` runtime constraint, while Cyclopts
  `3.24.0` still lacks Hecate's `result_action` keyword. Severity: medium.
  Likelihood: high. Mitigation: update the existing Cyclopts dependency to
  `cyclopts>=3,<4` and run Hecate through a narrow repository-local
  compatibility wrapper that strips only the unsupported keyword before
  importing Hecate's CLI.

- Risk: developers may not know how to update the policy when adding modules.
  Severity: medium. Likelihood: medium. Mitigation: update
  `docs/developers-guide.md` with the new gate, group ordering convention, and
  ignore-entry rules.

## Progress

- [x] (2026-05-24T19:03:55Z) Loaded the requested `leta`,
  `hexagonal-architecture`, and `execplans` skills.
- [x] (2026-05-24T19:03:55Z) Created the Leta workspace for this worktree with
  `leta workspace add`.
- [x] (2026-05-24T19:03:55Z) Renamed the branch to `adopt-hecate`, pushed it,
  and set it to track `origin/adopt-hecate`.
- [x] (2026-05-24T19:03:55Z) Used a Wyvern agent team for read-only planning
  reconnaissance across repository documents, existing architecture seams, and
  Hecate source documentation.
- [x] (2026-05-24T19:03:55Z) Confirmed there is no existing `hecate` target,
  dedicated check-architecture target, or repo-local check-architecture script.
- [x] (2026-05-24T19:03:55Z) Drafted this pre-implementation ExecPlan.
- [x] (2026-06-01T21:44:55Z) User approved implementation and requested work
  proceed from this ExecPlan.
- [x] (2026-06-01T21:44:55Z) Reloaded `leta` and
  `hexagonal-architecture`, confirmed the Leta workspace already exists, and
  re-opened the pinned Hecate documentation.
- [x] (2026-06-01T21:44:55Z) Added the pinned Hecate dependency, initial
  `[tool.hecate]` policy, `make check-architecture`, and CI lint-step naming
  update.
- [x] (2026-06-01T21:44:55Z) Ran `make build`; it installed Hecate from the
  pinned commit and updated the lockfile.
- [x] (2026-06-01T21:44:55Z) First `make check-architecture` attempt failed
  before checking imports because Hecate's CLI passes `result_action` to
  Cyclopts while Ghillie still constrained Cyclopts to `<3`.
- [x] (2026-06-01T21:44:55Z) Tested preserving Cyclopts `2.9.9`; this failed
  because Hecate also uses callable `cyclopts.Parameter`, which is unavailable
  in that version.
- [x] (2026-06-01T21:44:55Z) Updated the existing Cyclopts dependency to
  `cyclopts>=3,<4` and kept `scripts/check_architecture.py` for the remaining
  `result_action` compatibility gap.
- [x] (2026-06-01T21:44:55Z) Stage B validation passed:
  `make build`, `make check-architecture`, and `make lint` all exit `0`.
- [x] (2026-06-01T21:44:55Z) Milestone gate passed before commit:
  `make check-fmt`, `make lint`, `make typecheck`, `make test`,
  `make markdownlint`, `make nixie`, and `mbake validate Makefile` all exit
  `0`; tests report 809 passed, 11 skipped, and 24 warnings.
- [x] (2026-06-01T21:44:55Z) Committed Stage B as
      `d9a5078 Add Hecate architecture gate`.
- [x] (2026-06-01T21:44:55Z) Ran `coderabbit review --agent` after Stage B
  gates; CodeRabbit reported 0 findings.
- [x] (2026-06-01T21:44:55Z) Reviewed candidate structural tests named in
  Stage C. They cover runtime selection, status model factory behaviour,
  runtime-checkable protocols, report sink effects, CLI command shape, config
  precedence, context handling, and control-plane client behaviour. No tests
  were removed because none solely duplicated Hecate import-boundary checks.
- [x] (2026-06-01T21:44:55Z) Added
  `docs/adr-003-adopt-hecate-for-architecture-checks.md` for the Hecate
  adoption decision.
- [x] (2026-06-01T21:44:55Z) Updated `docs/ghillie-design.md`,
  `docs/ghillie-bronze-silver-architecture-design.md`,
  `docs/developers-guide.md`, and `docs/roadmap.md` for the Hecate gate, policy
  maintenance rules, and completed roadmap task.
- [x] (2026-06-01T21:44:55Z) Confirmed `docs/users-guide.md` does not need a
  change because this implementation adds a development/CI gate and does not
  change public runtime behaviour, CLI commands, or library APIs.
- [x] (2026-06-01T21:44:55Z) Documentation validation passed with
  `make markdownlint` and `make nixie`. `make fmt` was attempted but failed on
  pre-existing repository-wide Markdown line-length findings outside this
  change; unrelated formatter edits were restored.
- [x] (2026-06-01T21:44:55Z) Documentation milestone gate passed before
  commit: `make check-fmt`, `make lint`, `make typecheck`, `make test`,
  `make markdownlint`, `make nixie`, and `mbake validate Makefile` all exit
  `0`; tests report 809 passed, 11 skipped, and 24 warnings.
- [x] (2026-06-01T22:08:04Z) Committed the documentation and roadmap milestone
  as `6e60b16 Document Hecate architecture checks`.
- [x] (2026-06-01T22:08:04Z) Ran `coderabbit review --agent` after the
  documentation milestone gates; CodeRabbit reported 0 findings.
- [x] (2026-06-01T22:08:04Z) Implemented Hecate adoption after approval.
- [x] (2026-06-01T22:08:04Z) Validated implementation with local gates,
  CodeRabbit, and review.
- [x] (2026-06-01T22:08:04Z) Marked the relevant roadmap entry done after
  implementation, validation, and review.

## Surprises & discoveries

- Observation: The repository does not currently contain a dedicated
  automated hexagonal architecture check. Evidence: Searches across `Makefile`,
  `.github`, `scripts`, `tests`, `ghillie`, and `docs` found protocol and
  behaviour tests, but no Hecate, check-architecture target, or import-boundary
  script. Impact: The migration is best treated as adding a new canonical
  static gate and retiring only any future-discovered structural assertions,
  not as a one-for-one script replacement.

- Observation: One reconnaissance pass initially found report correctness
  checks rather than architecture-boundary checks. Evidence: The referenced
  files were `docs/ghillie-design.md` section 9.6.1 and `docs/users-guide.md`
  report validation text, which cover LLM report validation, not Python import
  boundaries. Impact: Do not update report correctness behaviour unless
  implementation work independently touches it.

- Observation: Hecate `0.1.0` at
  `46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12` declares an unbounded
  `Requires-Dist: cyclopts`, but its CLI uses
  `cyclopts.App(..., result_action=...)`. Evidence: the first local
  `make check-architecture` run raised
  `TypeError: App.__init__() got an unexpected keyword argument 'result_action'`
  with Cyclopts `2.9.9`; preserving Cyclopts `2.9.9` then failed on callable
  `cyclopts.Parameter`. Impact: this adoption needs a Cyclopts 3 compatibility
  update plus a shim until Hecate's declared dependency range and CLI code are
  aligned.

- Observation: Stage C did not identify an existing repository-local
  architecture test to delete. Evidence: the candidate tests assert runtime
  behaviour and public contracts rather than parsing imports or enforcing layer
  direction. Impact: Hecate adoption adds a new canonical static gate and keeps
  the existing behaviour coverage intact.

## Decision log

- Decision: Treat this branch as a pre-implementation planning branch.
  Rationale: The `execplans` skill requires explicit approval before execution,
  and the user specifically reminded that the plan must be approved before it
  is implemented. Date/Author: 2026-05-24T19:03:55Z / AI-proposed.

- Decision: Add Hecate as a development and CI gate rather than a public
  Ghillie CLI feature. Rationale: Hecate checks repository architecture during
  development. Exposing it through `ghillie` would create a new public
  interface that is not needed for the requested migration. Date/Author:
  2026-05-24T19:03:55Z / AI-proposed.

- Decision: Record the adoption in an Architecture Decision Record (ADR) during
  implementation. Rationale: Replacing informal architecture enforcement with a
  pinned external checker is a substantive engineering practice decision, not
  only a local Makefile change. Date/Author: 2026-05-24T19:03:55Z / AI-proposed.

- Decision: Keep behavioural tests unless they solely assert structural import
  boundaries. Rationale: Hecate can prove static dependency direction, but it
  cannot prove CLI behaviour, adapter runtime selection, report formatting,
  retry semantics, or storage effects. Date/Author: 2026-05-24T19:03:55Z /
  AI-proposed.

- Decision: Proceed with implementation on this branch. Rationale: The user
  explicitly requested implementation of `docs/execplans/adopt-hecate.md` on
  2026-06-01, satisfying the plan approval constraint. Date/Author:
  2026-06-01T21:44:55Z / User-approved, AI-recorded.

- Decision: Raise Ghillie's existing Cyclopts constraint from `>=2.9,<3` to
  `>=3,<4` and call Hecate through `scripts/check_architecture.py`. Rationale:
  Hecate is the only new dependency, but the pinned CLI cannot run on Cyclopts
  2.9. Cyclopts 3 satisfies Hecate's callable `Parameter` usage, and the
  wrapper removes the remaining unsupported `result_action` keyword before
  importing Hecate's CLI. Date/Author: 2026-06-01T21:44:55Z / AI-proposed.

- Decision: Do not update `docs/users-guide.md` for this adoption. Rationale:
  the new gate is a developer and CI practice. It does not change Ghillie's
  runtime behaviour, public Python APIs, HTTP routes, CLI command surface, or
  user configuration. Date/Author: 2026-06-01T21:44:55Z / AI-proposed.

## Outcomes & retrospective

Implementation is complete.

Ghillie now pins Hecate to
`46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12`, stores the import-direction policy
in `[tool.hecate]`, exposes `make check-architecture`, and runs that gate before
Ruff through `make lint` and CI. The pinned Hecate CLI requires Cyclopts 3 and a
small repository wrapper for the remaining `result_action` compatibility gap.

No public Ghillie CLI command, HTTP route, Python API, storage schema, runtime
configuration, or user-facing behaviour changed. Existing behaviour tests were
kept because the Stage C review found no tests that solely duplicated Hecate's
static import-boundary responsibility.

Validation completed with `make check-fmt`, `make lint`, `make typecheck`,
`make test`, `make markdownlint`, `make nixie`, and
`mbake validate Makefile`, all exiting `0`. CodeRabbit reviewed both the Hecate
gate milestone and the documentation milestone with 0 findings.

## Context and orientation

Ghillie is a Python 3.14 project under `ghillie/`. The architecture combines a
Medallion data model with hexagonal ports and adapters:

- Bronze modules such as `ghillie/bronze/services.py` and
  `ghillie/bronze/storage.py` handle raw event persistence.
- Silver modules such as `ghillie/silver/services.py`,
  `ghillie/silver/storage.py`, and `ghillie/silver/transformers.py` materialize
  structured entities.
- Gold modules such as `ghillie/gold/storage.py` persist report metadata.
- Application services live across modules such as `ghillie/reporting`,
  `ghillie/evidence`, `ghillie/registry`, and `ghillie/github/ingestion.py`.
- Inbound adapters include `ghillie/api`, `ghillie/cli`, and
  `ghillie/catalogue/cli.py`.
- Outbound adapters include concrete filesystem, OpenAI, GitHub GraphQL, and
  SQLAlchemy integrations.
- Ports are currently represented by protocols such as
  `ghillie/reporting/sink.py::ReportSink`,
  `ghillie/status/protocol.py::StatusModel`,
  `ghillie/cli/runtime_adapters.py::LocalRuntimeAdapter`, and
  `ghillie/github/client.py::GitHubActivityClient`.

The design source of truth for this work is:

- `docs/ghillie-design.md`, especially section 8.4 for HTTP API
  ports-and-adapters structure and section 9 for evidence/reporting services.
- `docs/ghillie-proposal.md`, for the original governance and reporting
  direction.
- `docs/ghillie-bronze-silver-architecture-design.md`, for Bronze and Silver
  component boundaries.
- `docs/developers-guide.md`, for contributor-facing quality gates and
  internally facing conventions.
- `docs/documentation-style-guide.md`, for Markdown, ADR, and roadmap
  conventions.
- `docs/roadmap.md`, for the eventual completion marker after implementation.

The Hecate source documents for the pinned adoption are:

- Hecate users' guide:
  <https://raw.githubusercontent.com/leynos/hecate/46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12/docs/users-guide.md>
- Hecate migration notes:
  <https://raw.githubusercontent.com/leynos/hecate/46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12/docs/migration-episodic.md>
- Hecate configuration guide:
  <https://raw.githubusercontent.com/leynos/hecate/46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12/docs/configuration.md>

Hecate reads `[tool.hecate]` from `pyproject.toml` by default. It supports
ordered `[[tool.hecate.groups]]` tables, `allowed` group lists,
`[[tool.hecate.ignore_imports]]` entries with reasons, `--format json`,
`--show-ignored`, and `--fail-on-unmatched-ignore`. Exit code `0` means pass,
`1` means architecture violations, and `2` means configuration or package-root
validation failed.

## Plan of work

### Stage A: baseline and policy inventory

Confirm the current branch, status, and clean starting point. Use `leta files`
and `leta grep` for code navigation. Use text search only for documentation,
configuration, and literal strings.

Inventory imports and architecture seams without changing code. Identify which
modules should belong to each Hecate group. Start from these candidate groups,
then adjust only with documented evidence:

- `composition_root`: narrow wiring modules that are allowed to import across
  groups, such as `ghillie.runtime`, `ghillie.api.app`, `ghillie.api.factory`,
  `ghillie.cli.app`, and `ghillie.status.factory`.
- `domain_ports`: protocol and model modules that must stay inward-facing,
  such as `ghillie.status.protocol`, `ghillie.reporting.sink`,
  `ghillie.evidence.models`, `ghillie.catalogue.models`, and common value
  helpers under `ghillie.common`.
- `application`: orchestration and transformation modules, such as
  `ghillie.reporting.service`, `ghillie.reporting.metrics_service`,
  `ghillie.evidence.service`, `ghillie.evidence.project_service`,
  `ghillie.registry.service`, `ghillie.registry.sync`,
  `ghillie.bronze.services`, and `ghillie.silver.services`.
- `inbound_adapter`: external entrypoints such as `ghillie.api`,
  `ghillie.cli`, and `ghillie.catalogue.cli`.
- `outbound_adapter`: concrete infrastructure integrations such as
  `ghillie.github.client`, `ghillie.status.openai_client`,
  `ghillie.reporting.filesystem_sink`, and SQLAlchemy storage modules.

The exact policy may differ after inventory. If a module is both a port and an
adapter today, record that ambiguity in the decision log before choosing a
group.

Stage A validation is documentary: update this plan with any discoveries and do
not proceed if the group map is ambiguous enough to change public behaviour or
require broad refactoring.

### Stage B: add the Hecate gate

Add Hecate to `pyproject.toml` in the `dev` dependency group as a Git-pinned
dependency:

```toml
"hecate @ git+https://github.com/leynos/hecate@46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12",
```

Run `make build` so `uv` updates the environment and lockfile if required.

Add `[tool.hecate]` to `pyproject.toml` with `root_packages = ["ghillie"]` and
ordered `[[tool.hecate.groups]]` entries. Put specific prefixes before broad
ones. Use `[[tool.hecate.ignore_imports]]` only for intentional edges with
non-empty reasons.

Add a Makefile target named `check-architecture`:

```make
check-architecture: build ## Run hexagonal architecture import checks
	$(UV_ENV) uv run hecate check --show-ignored --fail-on-unmatched-ignore
```

Add `check-architecture` to `.PHONY` and make it a dependency of the existing
`lint` target so `make lint` runs Hecate before `ruff check`. Do not add a
separate `check-architecture` entry to the `all` dependency chain, because
`all` already runs `lint`. Update `.github/workflows/ci.yml` only if the lint
step name needs to stop saying "Run ruff" once `make lint` covers both Hecate
and Ruff.

The resulting lint target should keep Ruff as the Python linter while making
Hecate the first lint-stage dependency:

```make
lint: check-architecture ruff ## Run linters
	ruff check
```

Stage B validation:

```bash
make build 2>&1 | tee /tmp/build-ghillie-adopt-hecate.out
make check-architecture 2>&1 | tee /tmp/check-architecture-ghillie-adopt-hecate.out
make lint 2>&1 | tee /tmp/lint-ghillie-adopt-hecate.out
```

Expected result: all commands exit `0`. If Hecate exits `1`, inspect the
violations and either correct the policy or escalate if the code requires
refactoring beyond this plan. If Hecate exits `2`, fix configuration before
continuing.

### Stage C: replace structural checks without losing behaviour coverage

Search tests for assertions that only protect architecture structure. Candidate
test files to review include:

- `tests/unit/cli/test_runtime_adapter_selection.py`
- `tests/unit/status/test_factory.py`
- `tests/unit/test_status_protocol.py`
- `tests/unit/test_reporting_sink_integration.py`
- `tests/unit/test_filesystem_sink.py`
- `tests/unit/cli/test_config_resolution.py`
- `tests/unit/cli/test_app.py`
- `tests/unit/cli/test_global_options.py`
- `tests/unit/cli/test_control_plane_client.py`
- `tests/unit/cli/test_context.py`

Keep tests that exercise runtime selection, CLI output, error handling, report
writing, metrics, storage, or service behaviour. Remove or rewrite only
assertions that duplicate Hecate's import-boundary responsibility. If no such
assertions exist, record that the implementation adds a new gate and does not
delete tests.

Add a small policy test if useful, for example
`tests/unit/test_architecture_policy.py`, that runs Hecate in JSON mode against
the repository policy or validates representative group classification if
Hecate exposes a stable API. Do not duplicate Hecate's own semantic test suite
inside Ghillie.

Stage C validation:

```bash
make check-architecture 2>&1 | tee /tmp/check-architecture-ghillie-adopt-hecate.out
make test 2>&1 | tee /tmp/test-ghillie-adopt-hecate.out
```

Expected result: both commands exit `0`, and any removed tests are replaced by
the Make/CI architecture gate or narrower behaviour tests.

### Stage D: documentation and decision records

Create `docs/adr-003-adopt-hecate-for-architecture-checks.md` using the style
of the existing ADR files. Record the decision to use Hecate, the pinned
commit, the alternatives considered, the consequences, and the rollback path.

Update `docs/ghillie-design.md` near section 8.4 to describe Hecate as the
static architecture fitness function for ports-and-adapters import direction.
Reference the ADR for the full rationale.

Update `docs/ghillie-bronze-silver-architecture-design.md` only if the final
policy documents Bronze and Silver module group conventions that are not
already stated there.

Update `docs/developers-guide.md` to add `make check-architecture` to the
quality-gate table and to document contributor conventions:

- update `[tool.hecate]` when adding a new package boundary;
- place specific prefixes before broad prefixes;
- prefer refactoring over `ignore_imports`;
- every ignore must include a precise reason;
- run `make check-architecture` before opening a pull request.

Update `docs/users-guide.md` only if implementation changes public Ghillie
runtime behaviour, CLI behaviour, or library API. A development-only Makefile
gate does not need user-facing documentation.

Update `docs/roadmap.md` after implementation, validation, and review. If no
existing roadmap task precisely covers this adoption, add or update the narrow
relevant entry according to `docs/documentation-style-guide.md`, then mark it
done in the same implementation branch once the feature is complete.

Stage D validation:

```bash
make fmt 2>&1 | tee /tmp/fmt-ghillie-adopt-hecate.out
make markdownlint 2>&1 | tee /tmp/markdownlint-ghillie-adopt-hecate.out
make nixie 2>&1 | tee /tmp/nixie-ghillie-adopt-hecate.out
```

Expected result: Markdown formatting, linting, and Mermaid validation pass.

### Stage E: full gates, CodeRabbit, commits, and PR update

Run the full required local gate sequence sequentially:

```bash
make check-fmt 2>&1 | tee /tmp/check-fmt-ghillie-adopt-hecate.out
make lint 2>&1 | tee /tmp/lint-ghillie-adopt-hecate.out
make typecheck 2>&1 | tee /tmp/typecheck-ghillie-adopt-hecate.out
make test 2>&1 | tee /tmp/test-ghillie-adopt-hecate.out
```

Request CodeRabbit review only after these deterministic gates pass:

```bash
coderabbit review --agent
```

Clear all actionable CodeRabbit concerns before moving on. Commit each
validated milestone with a file-based commit message. Push the branch and
update the draft pull request summary to mention
`docs/execplans/adopt-hecate.md`.

## Concrete steps

1. Confirm branch and status:

   ```bash
   git branch --show-current
   git status --short --branch
   ```

   Expected output includes:

   ```plaintext
   adopt-hecate
   ## adopt-hecate...origin/adopt-hecate
   ```

2. After approval, inspect source structure with Leta:

   ```bash
   leta files ghillie
   leta grep ".*" "ghillie/(api|cli|reporting|status|github|bronze|silver|gold)" -k function,method,class
   ```

3. Add the Hecate dependency and `[tool.hecate]` policy in `pyproject.toml`.

4. Add `check-architecture` to `Makefile` and wire it through `make lint`.

5. Run the Stage B validation commands and record results in this plan.

6. Review candidate tests and remove only structural duplication.

7. Add or update docs and ADRs from Stage D.

8. Run the full Stage E gates and CodeRabbit review.

9. Mark the relevant roadmap entry done after implementation is complete.

10. Commit, push, and update the draft pull request.

## Validation and acceptance

The implementation is accepted when all the following are true:

- `make check-architecture` exits `0` and checks `ghillie` with Hecate pinned to
  `46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12`.
- CI runs `make lint` before tests, and `make lint` runs
  `check-architecture` before Ruff.
- `make check-fmt`, `make lint`, `make typecheck`, and `make test` all exit
  `0`.
- `make markdownlint` and `make nixie` exit `0` after documentation changes.
- CodeRabbit review has no unresolved actionable concerns.
- The ADR records the Hecate adoption decision.
- `docs/developers-guide.md` documents the new gate and maintenance practice.
- `docs/ghillie-design.md` references Hecate as the architecture fitness
  function.
- `docs/users-guide.md` is updated if and only if public user-visible behaviour
  changes.
- The relevant roadmap entry is marked done only after the feature is
  implemented and validated.

## Idempotence and recovery

The Makefile and Hecate checks are safe to rerun. If `make build` changes the
lockfile, keep the lockfile with the dependency change and rerun all gates.

If the Hecate policy causes many violations, do not hide them with broad
ignores. Revert the policy edits for the current milestone, record the
violations in this plan, and ask whether to broaden the implementation into a
module refactor.

If CodeRabbit reports a concern, fix it in a focused commit and rerun the
deterministic gates before requesting another review.

Rollback for the implementation is straightforward: remove the Hecate
dependency, `[tool.hecate]` table, `check-architecture` Makefile target, lint
dependency, and any tests or docs that depend on the new gate. Do not remove
the ADR unless the decision itself is reversed; supersede it with a new ADR if
needed.

## Artifacts and notes

Initial planning evidence:

```plaintext
git branch --show-current
adopt-hecate

leta workspace add /home/leynos/.lody/repos/github---leynos---ghillie/worktrees/9a262b6c-18f3-4aba-9e62-285e6acc9544
Added workspace: /home/leynos/.lody/repos/github---leynos---ghillie/worktrees/9a262b6c-18f3-4aba-9e62-285e6acc9544
```

Wyvern reconnaissance found no existing Hecate or check-architecture target in
`Makefile`, `.github/workflows/ci.yml`, or `scripts/`. It identified current
architecture seams in `ghillie/cli/runtime_adapters.py`,
`ghillie/status/protocol.py`, `ghillie/reporting/sink.py`,
`ghillie/status/factory.py`, `ghillie/api/factory.py`,
`ghillie/reporting/service.py`, and `ghillie/github/client.py`.

## Interfaces and dependencies

The implementation must introduce these interfaces:

```toml
[tool.hecate]
root_packages = ["ghillie"]

[[tool.hecate.groups]]
name = "composition_root"
prefixes = ["ghillie.runtime"]
allowed = [
    "application",
    "composition_root",
    "domain_ports",
    "inbound_adapter",
    "outbound_adapter",
]
```

The final policy will include additional groups and prefixes discovered during
Stage A. The exact allowed sets must preserve the hexagonal dependency rule:
domain and port modules do not import adapters; application modules depend on
ports and other application modules; adapters depend inward on application and
ports; composition roots may wire across groups.

The Makefile interface was expected to be:

```make
check-architecture: build ## Run hexagonal architecture import checks
	$(UV_ENV) uv run hecate check --show-ignored --fail-on-unmatched-ignore
```

Implementation uses this equivalent repository wrapper because the pinned
Hecate CLI passes a Cyclopts keyword unsupported by Cyclopts `3.24.0`:

```make
check-architecture: build ## Run hexagonal architecture import checks
	$(UV_ENV) uv run scripts/check_architecture.py
```

The dependency must be pinned exactly:

```toml
"hecate @ git+https://github.com/leynos/hecate@46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12",
```

Revision note:

Initial draft created on 2026-05-24. This revision establishes a
pre-implementation approval gate, records source-document findings, and defines
the staged migration from informal architecture seams to a pinned Hecate gate.
