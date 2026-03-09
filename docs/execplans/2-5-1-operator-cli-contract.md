# Define and scaffold the operator command-line interface (CLI) contract

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`, and
`Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: DRAFT

## Purpose / big picture

Task 2.5.a establishes the operator-facing command surface for the minimum
viable product (MVP). After this change, Ghillie has a packaged `ghillie`
command that exposes the noun and verb tree defined in
`docs/mvp-cli-specification.md`, accepts shared global options for
control-plane access, and routes those options into two stable seams:

1. an `httpx` control-plane client for HTTP APIs, and
2. a local runtime adapter selector for `cuprum` and `python-api` stack
   integrations.

This task is intentionally a scaffold, not the full control plane. The work
must deliver a runnable CLI skeleton that can be extended by Tasks 2.5.b
through 2.5.d without changing the operator grammar. The direct user-visible
outcome is that an operator can run commands such as `ghillie --help`,
`ghillie stack up --help`, `ghillie estate import --help`, and
`ghillie report run --help`, see the documented global options, and get stable
validation of the command tree and option values.

Success is observable when:

1. `uv run ghillie --help` shows the root nouns `stack`, `estate`, `ingest`,
   `export`, `report`, and `metrics`.
2. `uv run ghillie stack up --help` and the corresponding help for the other
   nouns show the documented verb structure.
3. Global options such as `--api-base-url`, `--auth-token`, `--output`, and
   `--request-timeout-s` parse from the root and are available to command
   handlers through one shared context object.
4. The CLI can build a configured `httpx` control-plane client and can select
   either the `cuprum` or `python-api` local runtime adapter without ad hoc
   scripts.
5. Unit tests and `pytest-bdd` scenarios fail before implementation and pass
   after implementation.
6. `docs/mvp-cli-specification.md`, `docs/users-guide.md`, and the relevant
   design documentation reflect the scaffold accurately.
7. `docs/roadmap.md` marks Task 2.5.a as done only after the implementation,
   tests, and documentation are complete.
8. Quality gates pass: `make check-fmt`, `make typecheck`, `make lint`,
   `make test`, `make markdownlint`, and `make nixie`.

## Constraints

- Treat `docs/mvp-cli-specification.md` as the contract source of truth for
  command grammar, configuration precedence, root nouns, and option names.
- Keep the grammar noun-first: `ghillie <noun> <verb> ...`. Do not introduce a
  second top-level grammar.
- Follow a hexagonal split. The CLI is a driving adapter. The HTTP client and
  local runtime integrations are driven adapters. Command handlers must not
  embed infrastructure details directly.
- Do not remove or break the existing `scripts/local_k8s.py` workflow during
  Task 2.5.a. The new CLI scaffold may wrap or coexist with it, but must not
  regress the current local preview path.
- Avoid ad hoc subprocess scripts for control-plane actions. The new scaffold
  must live under the `ghillie/` package and be exposed as a proper console
  entry point.
- Do not change the existing Falcon runtime contract in `ghillie/runtime.py`
  or the current report API path `POST /reports/repositories/{owner}/{name}`.
- Do not add a new external dependency for Task 2.5.a unless the user approves
  it. The scaffold can model `cuprum` as a selectable backend name without
  implementing concrete `cuprum` command execution yet.
- Follow the repository test-driven development (TDD) policy from
  `AGENTS.md`: write the new unit tests and behavioural tests first, confirm
  they fail, then implement.
- Keep documentation wrapped and lint-clean under the repo markdown rules.

## Tolerances (exception triggers)

- Scope: if Task 2.5.a cannot be completed within roughly 18 files or 1400 net
  lines of code, stop and reassess the split between scaffold and later tasks.
- Interface: if implementing the scaffold requires changing the operator
  grammar already documented in `docs/mvp-cli-specification.md`, stop and
  update the spec first before writing code.
- Dependencies: if real `cuprum` support requires adding a new runtime
  dependency in this task, stop and present the trade-off between adding that
  dependency now and keeping adapter selection abstract until Task 2.5.d.
- Behaviour: if the CLI needs to perform real estate-management or ingestion
  actions to validate the scaffold, stop. Those behaviours belong to later
  tasks and should not be silently pulled into 2.5.a.
- Testing: if the CLI cannot be validated with deterministic unit and BDD
  tests without invoking Docker, Helm, or Kubernetes, stop and redesign the
  adapter seam.
- Ambiguity: if Cyclopts cannot support the documented root-global-option
  behaviour cleanly, stop and document the viable alternatives before
  proceeding.

## Risks

- Risk: Cyclopts global-option propagation for nested noun and verb commands
  may be awkward, leading to drift between help text and actual parsing.
  Severity: high Likelihood: medium Mitigation: define one explicit
  context/config dataclass and write failing parser tests before wiring
  handlers.

- Risk: There is no packaged `ghillie` console entry point today, so the first
  implementation could accidentally become another standalone script. Severity:
  high Likelihood: medium Mitigation: add the CLI under `ghillie/cli/` and
  expose it through `[project.scripts]` in `pyproject.toml`.

- Risk: The spec names `cuprum`, but the repo currently has no runtime
  dependency for it and already contains Python modules for local k8s
  orchestration. Severity: medium Likelihood: high Mitigation: keep backend
  selection abstract in 2.5.a and defer concrete backend execution to later
  work unless a dependency decision is made explicitly.

- Risk: Command handlers may accumulate business logic and violate the
  dependency rule. Severity: medium Likelihood: medium Mitigation: treat
  handlers as thin translation layers that call typed services, clients, or
  adapter ports only.

- Risk: Behavioural tests that shell out to the installed command can become
  flaky if they depend on the developer shell or external tools. Severity:
  medium Likelihood: medium Mitigation: keep BDD scenarios focused on help
  output, option validation, and backend selection using pure-Python test
  doubles.

## Progress

- [x] 2026-03-08 Read `AGENTS.md`, the ExecPlans skill, and the
  `hexagonal-architecture` skill.
- [x] 2026-03-08 Read roadmap, MVP CLI specification, runtime/API modules, and
  representative tests.
- [x] 2026-03-08 Draft this ExecPlan.
- [ ] Add failing unit tests for CLI packaging, command tree shape, shared
  global options, control-plane client config, and runtime adapter selection.
- [ ] Add failing behaviour-driven development (BDD) scenarios via
  `pytest-bdd` for operator-visible help and option parsing.
- [ ] Implement the packaged CLI scaffold under `ghillie/cli/`.
- [ ] Update docs and mark Task 2.5.a done in `docs/roadmap.md`.
- [ ] Run all quality gates and record the results.

## Surprises & Discoveries

- `docs/mvp-cli-specification.md` already contains most of the contract needed
  for Task 2.5.a, including noun-first grammar, configuration precedence, the
  root command tree, and backend names. The implementation task is mainly to
  make that contract executable and testable.
- The repo already contains a small but useful Cyclopts reference in
  `scripts/local_k8s.py` plus tests in `scripts/tests/test_local_k8s_cli.py`.
  That code shows how this repo currently tests Cyclopts app structure.
- The codebase has no packaged `ghillie` console script yet. The current
  user-facing command surfaces are Python modules and the standalone
  `scripts/local_k8s.py`.
- The current HTTP API surface is intentionally narrow. For this task, the
  `httpx` client plumbing should be real, but most noun handlers will remain
  skeletal until Tasks 2.5.b through 2.5.d add the corresponding APIs.

## Decision Log

1. The scaffold will be delivered as a packaged CLI inside `ghillie/cli/`,
   not as another script.

   Rationale: the roadmap explicitly asks for a single CLI without ad hoc
   scripts. The repo already uses the `ghillie/` package for runtime and API
   code, and `pyproject.toml` currently lacks a console entry point.

2. The CLI will follow a ports-and-adapters shape from the start.

   Rationale: this is the cleanest way to satisfy the user instruction to use
   the `hexagonal-architecture` skill. A thin inbound adapter layer under
   `ghillie/cli/commands/` can depend on typed context objects and ports, while
   concrete `httpx` and local-runtime adapters stay isolated.

3. Task 2.5.a will scaffold every documented noun and verb, but it will not
   silently implement the later control-plane behaviours.

   Rationale: the roadmap splits Step 2.5 into separate tasks with explicit
   prerequisites. The scaffold must keep the command surface stable without
   collapsing 2.5.b through 2.5.d into one oversized change.

4. Backend selection for `cuprum` and `python-api` will be part of the stable
   command contract even if only lightweight placeholder adapters exist in this
   task.

   Rationale: validated option parsing is part of the completion criteria, and
   later tasks need a stable backend selector. Concrete backend execution can
   remain deferred if required dependencies are not yet present.

5. CLI handlers should stay synchronous at the boundary and use explicit
   bridging for async infrastructure.

   Rationale: Cyclopts usage in this repo is synchronous, and the existing API
   infrastructure uses async `httpx` and SQLAlchemy. Using a thin `asyncio.run`
   bridge from command handlers into async clients keeps parser tests simple
   and avoids spreading async concerns through the command tree.

## Context and orientation

The current repo state matters because Task 2.5.a is mostly about integration
shape, not novel domain logic.

`docs/mvp-cli-specification.md` already defines the intended operator contract.
It specifies:

- the noun-first grammar,
- the six top-level nouns,
- the verb tree under each noun,
- shared global options,
- configuration precedence,
- persisted CLI state,
- and the backend names `cuprum` and `python-api`.

`ghillie/api/app.py` and `ghillie/api/factory.py` provide the first reusable
control-plane HTTP surface and service factory. Today, the only concrete
operator API is on-demand repository reporting through
`POST /reports/repositories/{owner}/{name}`.

`scripts/local_k8s.py` is the existing Cyclopts-based local operator tool. It
is important as a reference, but it is not the final operator CLI because it is
script-local, verb-first, and limited to local preview lifecycle management.

`ghillie/runtime.py` remains the runtime entry point and must not be disturbed
by this work.

The test suite already uses:

- unit tests for Cyclopts structure,
- Falcon test clients for HTTP behaviour,
- and `pytest-bdd` feature files with step modules under `tests/features/`.

This task should follow the same patterns instead of inventing a separate test
framework.

## Implementation plan

## Milestone 1: Lock the contract with failing tests

Start with tests that describe the scaffold, not the future business logic.

Add unit tests under a new CLI-focused area, for example:

- `tests/unit/cli/test_app.py`
- `tests/unit/cli/test_global_options.py`
- `tests/unit/cli/test_control_plane_client.py`
- `tests/unit/cli/test_runtime_adapters.py`

These tests should assert:

1. a packaged app object exists and is named `ghillie`,
2. the root nouns match the spec,
3. each noun exposes the documented verbs,
4. global options parse into one shared configuration object,
5. config precedence is flag, env, profile, state, fallback,
6. the control-plane client builder translates config into `httpx` base URL,
   timeout, and auth headers,
7. runtime adapter selection accepts `cuprum` and `python-api` and rejects
   unknown values.

Add behavioural coverage with `pytest-bdd` for the operator-visible contract.
Create a feature file such as `tests/features/operator_cli_contract.feature`
and a step module such as `tests/features/steps/test_operator_cli_steps.py`.

The BDD scenarios should stay black-box and user-facing. Cover at least these
cases:

1. `ghillie --help` lists the six nouns.
2. `ghillie stack up --help` exposes the documented backend and wait options.
3. `ghillie --api-base-url http://127.0.0.1:9999 report run --help` parses
   successfully, proving root-global options are accepted before the noun.
4. `ghillie stack up --backend invalid` fails fast with a validation error.

Run the new targeted tests first and confirm they fail before any code is added.

Suggested red-phase commands:

```bash
UV_CACHE_DIR=.uv-cache UV_TOOL_DIR=.uv-tools uv run pytest tests/unit/cli -v
UV_CACHE_DIR=.uv-cache UV_TOOL_DIR=.uv-tools uv run pytest tests/features/steps/test_operator_cli_steps.py -v
```

## Milestone 2: Build the packaged CLI core

Add a proper CLI package under `ghillie/cli/`. Keep the package small and
composed of explicit modules.

Create or update these files:

- `ghillie/cli/__init__.py`
- `ghillie/cli/__main__.py`
- `ghillie/cli/app.py`
- `ghillie/cli/context.py`
- `ghillie/cli/config.py`
- `ghillie/cli/control_plane.py`
- `ghillie/cli/runtime/ports.py`
- `ghillie/cli/runtime/factory.py`

Update `pyproject.toml` to expose a console entry point:

```toml
[project.scripts]
ghillie = "ghillie.cli:main"
```

The CLI core should provide four stable types:

1. `GlobalOptions`
   A frozen dataclass capturing root-global values such as API base URL, auth
   token, output format, timeout, non-interactive mode, and dry-run.

2. `ResolvedCliConfig`
   A frozen dataclass representing the post-precedence configuration that
   handlers actually use.

3. `ControlPlaneClient`
   A thin `httpx` wrapper responsible for building requests and carrying auth,
   base URL, and timeout configuration. For Task 2.5.a it may expose only a
   small smoke surface or placeholder methods, but the object itself must be
   real and tested.

4. `LocalRuntimeAdapter`
   A port defining the stack-lifecycle actions that later tasks will need. Keep
   the methods small and noun/verb-aligned, such as `up`, `down`, `status`, and
   `logs`.

Keep config loading separate from command registration. That separation is what
allows unit tests to validate precedence without invoking the entire command
tree.

## Milestone 3: Register the noun and verb tree

Implement the root Cyclopts app and register one command group per noun:

- `stack`
- `estate`
- `ingest`
- `export`
- `report`
- `metrics`

Under each noun, register the verbs from `docs/mvp-cli-specification.md`. The
handlers for this task can remain skeletal as long as they are runnable and
validate options cleanly.

Use a dedicated module per noun, for example:

- `ghillie/cli/commands/stack.py`
- `ghillie/cli/commands/estate.py`
- `ghillie/cli/commands/ingest.py`
- `ghillie/cli/commands/export.py`
- `ghillie/cli/commands/report.py`
- `ghillie/cli/commands/metrics.py`

Each handler should do only one of these things in Task 2.5.a:

1. build the shared CLI context,
2. select the right adapter or client,
3. return a stable placeholder result for not-yet-implemented behaviours, or
4. call a very small proven surface that already exists.

Do not let placeholder handlers become unstructured print statements. Even the
scaffold should return stable machine-readable output for `--output json` and a
clean human-readable message for the default output mode.

For the backend seam:

- `ghillie/cli/runtime/factory.py` should map `cuprum` and `python-api` to
  concrete adapter classes.
- For `python-api`, prefer reusing or wrapping the existing Python
  orchestration modules under `scripts/local_k8s/` rather than duplicating
  their logic.
- For `cuprum`, it is acceptable in Task 2.5.a to provide a placeholder
  adapter class whose construction is validated even if its execution paths are
  left for later work.

## Milestone 4: Document the scaffold and leave the repo ready for 2.5.b-d

Update the documents that describe operator behaviour:

1. `docs/mvp-cli-specification.md`

   Reconcile any drift discovered during implementation. In particular,
   document the packaged entry point, the exact placeholder semantics for
   not-yet-implemented verbs, and any clarifications needed for root-global
   option parsing.

2. `docs/users-guide.md`

   Add a new operator CLI section that shows how to inspect the command tree
   and how global configuration resolution works at MVP scaffold level. Keep
   examples bounded to behaviours that actually exist after 2.5.a.

3. `docs/ghillie-design.md`

   Record the architectural decision that the operator CLI is a driving adapter
   with separate HTTP and local-runtime outbound adapters.

4. `docs/roadmap.md`

   Mark Task 2.5.a as done only after the code, tests, and documentation are
   merged and the quality gates pass.

## Validation and evidence

During implementation, use a red-green-refactor loop for the targeted CLI
tests, then run the full repository gates.

Suggested verification commands:

```bash
set -o pipefail && make fmt 2>&1 | tee /tmp/ghillie-make-fmt.log
set -o pipefail && make check-fmt 2>&1 | tee /tmp/ghillie-make-check-fmt.log
set -o pipefail && make typecheck 2>&1 | tee /tmp/ghillie-make-typecheck.log
set -o pipefail && make lint 2>&1 | tee /tmp/ghillie-make-lint.log
set -o pipefail && make test 2>&1 | tee /tmp/ghillie-make-test.log
set -o pipefail && MDLINT=/root/.bun/bin/markdownlint-cli2 make markdownlint 2>&1 | tee /tmp/ghillie-make-markdownlint.log
set -o pipefail && make nixie 2>&1 | tee /tmp/ghillie-make-nixie.log
```

Record brief evidence in this plan once implementation happens. At minimum,
capture:

- the help output proving the noun tree,
- one example of valid root-global option parsing,
- one example of invalid backend rejection,
- and the final gate results.

Expected operator evidence after completion should look roughly like this:

```plaintext
$ uv run ghillie --help
... stack ...
... estate ...
... ingest ...
... export ...
... report ...
... metrics ...

$ uv run ghillie stack up --backend invalid
Error: invalid value for --backend
```

## Outcomes & Retrospective

This section remains incomplete until Task 2.5.a is implemented.

The intended outcome is a repo-owned, packaged CLI scaffold that makes the
operator contract executable and testable without overreaching into the later
Step 2.5 tasks. A successful implementation leaves the command grammar stable,
the adapter seams explicit, the docs aligned, and the repo ready for
estate-management APIs, ingestion run orchestration, and report/export commands
in the next milestones.
