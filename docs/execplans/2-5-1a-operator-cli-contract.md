# Define and scaffold the operator CLI contract

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

Status: COMPLETE

## Purpose / big picture

Task 2.5.a is the entry task for Step 2.5 in `docs/roadmap.md`. Its job is to
turn the already-documented MVP operator contract into a runnable, testable
scaffold. After this task is implemented, a human operator will be able to run
one packaged `ghillie` command, inspect the full noun/verb tree, pass shared
control-plane options once at the root, and exercise validated option parsing
without relying on ad hoc scripts.

The deliverable is a scaffold, not a completed control plane. It must make the
operator grammar stable for the follow-on tasks that add real estate,
ingestion, reporting, export, and local runtime behaviours. Success is
observable when:

1. `uv run ghillie --help` lists the top-level nouns `stack`, `estate`,
   `ingest`, `export`, `report`, and `metrics`.
2. `uv run ghillie <noun> <verb> --help` works for the verbs documented in
   `docs/mvp-cli-specification.md`.
3. Shared root options such as `--api-base-url`, `--auth-token`, `--output`,
   and `--request-timeout-s` parse once and reach command handlers through one
   resolved context object.
4. The scaffold can build an `httpx` control-plane client and select a local
   runtime adapter named `cuprum` or `python-api`.
5. Unit tests and `pytest-bdd` scenarios fail before implementation and pass
   afterwards.
6. `docs/mvp-cli-specification.md`, `docs/users-guide.md`,
   `docs/ghillie-design.md`, and `docs/roadmap.md` are updated to match the
   implemented scaffold exactly.

## Constraints

- Treat `docs/mvp-cli-specification.md` as the contract source of truth for
  noun-first grammar, root nouns, documented verbs, shared options, config
  precedence, persisted state, and backend names.
- Keep the grammar `ghillie <noun> <verb> ...`. Do not introduce a second
  top-level grammar or preserve `scripts/local_k8s.py` as the primary operator
  entry point.
- Follow a hexagonal boundary from the start. The CLI is a driving adapter.
  The `httpx` control-plane client and local runtime adapters are driven
  adapters. Command handlers must stay thin and must not embed HTTP or local
  orchestration details directly.
- Deliver the scaffold inside the `ghillie/` package with a proper console
  entry point in `pyproject.toml`. Do not solve Task 2.5.a with another
  standalone script.
- Do not break the existing `scripts/local_k8s.py` workflow during this task.
  It remains a reference implementation and can coexist until later tasks move
  more operator behaviour into the packaged CLI.
- Do not silently pull Task 2.5.b, 2.5.c, 2.5.d, or 2.5.e into this change.
  The scaffold may expose commands for those later tasks, but it must not
  require their full backend behaviour to satisfy completion.
- Follow the repository TDD policy. New unit tests and behavioural tests must
  be written first, demonstrated failing, and then turned green by the
  implementation.
- The final implementation must pass `make check-fmt`, `make typecheck`,
  `make lint`, `make test`, `make markdownlint`, and `make nixie`.
- Keep Markdown wrapped and lint-clean under
  `docs/documentation-style-guide.md`.

## Tolerances

- Scope: if Task 2.5.a grows beyond roughly 16 to 20 files or requires
  substantial changes outside the CLI, documentation, and tests, stop and
  reassess whether later Step 2.5 work is being pulled in too early.
- Dependencies: if implementing real `cuprum` execution requires a new runtime
  dependency or a rename from the currently documented spelling, stop and
  resolve that contract question before continuing.
- Behaviour: if a command needs real Docker, Helm, Kubernetes, or live HTTP
  side effects merely to validate parsing and scaffolding, stop and redesign
  the seam so tests stay deterministic.
- Packaging: if the packaged CLI cannot run without importing from
  `scripts/`, stop and extract or defer that coupling explicitly rather than
  hiding it inside the scaffold.
- Interface: if Cyclopts cannot support root-scoped global options in a way
  that matches the spec and help output, stop and update the spec before
  implementation.
- Ambiguity: if the stray completion criterion about producing a
  multi-repository project evidence bundle is intended to be in scope for this
  task, stop and clarify it. That criterion belongs to project evidence work,
  not the CLI scaffold described in Task 2.5.a.

## Risks

- Risk: the repo already has an older broad Step 2.5 draft in
  `docs/execplans/2-5-1-operator-cli-contract.md`, and its implementation
  suggestions include a package path that would clash with the existing
  `ghillie/runtime.py` module. Mitigation: this plan keeps the new scaffold
  under `ghillie/cli/` and avoids proposing a conflicting `ghillie.runtime.*`
  package.

- Risk: `docs/mvp-cli-specification.md` and `docs/roadmap.md` both use the
  backend name `cuprum`, but the repo's existing scripting guidance and
  dependencies are centred on `plumbum`. Mitigation: preserve `cuprum` as the
  user-visible selector for Task 2.5.a, treat it as an adapter label rather
  than a concrete dependency, and record any future rename decision explicitly
  in the design docs.

- Risk: `pyproject.toml` currently carries `cyclopts` only in the development
  dependency group, so the packaged CLI could be accidentally non-runnable in a
  non-dev installation. Mitigation: promote the CLI's true runtime dependencies
  into `[project.dependencies]` as part of implementation, and cover the
  console entry point with tests.

- Risk: the current local runtime logic lives under `scripts/local_k8s/`, which
  is suitable for scripts but not yet a clean packaged adapter boundary.
  Mitigation: Task 2.5.a should validate adapter selection without depending on
  full runtime execution. Any extraction of reusable orchestration logic should
  be minimal and only done if required to keep the packaged CLI clean.

- Risk: behavioural tests for a CLI can become brittle if they shell out to a
  live environment. Mitigation: keep `pytest-bdd` scenarios black-box at the
  parsing/help layer and use pure-Python doubles for config resolution, client
  construction, and adapter selection.

## Progress

- [x] 2026-03-13 Read `AGENTS.md`, the `execplans` skill, and the
  `hexagonal-architecture` skill.
- [x] 2026-03-13 Queried project notes for architecture, tooling, gotchas, and
  prior Step 2.5 decisions.
- [x] 2026-03-13 Read `docs/roadmap.md`,
  `docs/mvp-cli-specification.md`, `docs/ghillie-design.md`,
  `docs/ghillie-proposal.md`,
  `docs/ghillie-bronze-silver-architecture-design.md`,
  `docs/async-sqlalchemy-with-pg-and-falcon.md`,
  `docs/testing-async-falcon-endpoints.md`, and
  `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`.
- [x] 2026-03-13 Inspected `pyproject.toml`, `scripts/local_k8s.py`, the
  existing local-k8s CLI tests, and the earlier Step 2.5 draft ExecPlan.
- [x] 2026-03-13 Drafted this Task 2.5.a ExecPlan.
- [x] 2026-03-14 Added failing unit tests for the packaged CLI app, command
  tree, shared root options, config precedence, control-plane client wiring,
  and runtime adapter selection. The red phase failed with
  `ModuleNotFoundError: No module named 'ghillie.cli'`.
- [x] 2026-03-14 Added failing `pytest-bdd` scenarios for the
  operator-visible grammar and validation rules. The red phase failed with the
  same missing-package error before implementation.
- [x] 2026-03-14 Implemented the packaged CLI scaffold under `ghillie/cli/`
  and exposed it as the `ghillie` console entry point in `pyproject.toml`.
- [x] 2026-03-14 Updated the CLI spec, users' guide, design document, and
  roadmap entry to match the scaffold.
- [x] 2026-03-14 Ran all quality gates and captured the final evidence below.

## Surprises & Discoveries

- `docs/mvp-cli-specification.md` already captures most of the contract needed
  for Task 2.5.a, including the noun-first grammar, root nouns, config
  precedence, state persistence, and backend names. The main work is to make
  that contract executable and testable.
- The repo already contains a small Cyclopts reference in
  `scripts/local_k8s.py` and structure tests in
  `scripts/tests/test_local_k8s_cli.py`. Those files are the closest local
  precedent for command registration and CLI test style.
- There is no packaged `ghillie` console entry point today.
  `pyproject.toml` has no `[project.scripts]` section for the operator CLI.
- `httpx` is already a runtime dependency, which lowers the cost of adding a
  control-plane client. `cyclopts` is not yet a runtime dependency.
- The broad Step 2.5 draft in
  `docs/execplans/2-5-1-operator-cli-contract.md` is directionally useful, but
  one of its suggested package moves would conflict with the existing
  `ghillie/runtime.py` module. This plan avoids that mistake.
- The extra completion criterion supplied with this request, "At least one
  multi-repository project can produce a complete project evidence bundle from
  catalogue and repository data", does not match Task 2.5.a and should be
  treated as out of scope unless the roadmap itself is changed.
- Cyclopts `2.9.x` evaluates function annotations at import time via
  `inspect.signature(..., eval_str=True)`. That means command modules cannot
  hide runtime annotation imports such as `Path` behind `TYPE_CHECKING` guards
  without breaking app import and help rendering.
- The installed Cyclopts version does not expose newer root-dispatch hooks
  that would make shared option propagation trivial. The scaffold therefore
  uses a small explicit pre-parser at the app boundary to collect root-global
  options before dispatching to the noun tree. This preserves the documented
  contract while keeping handlers thin and testable.

## Decision Log

1. The packaged CLI will live under `ghillie/cli/`, and the console entry point
   will resolve there.

   Rationale: the roadmap explicitly asks for a single CLI without ad hoc
   scripts. `ghillie/cli/` is the least surprising place to add a driving
   adapter without colliding with `ghillie/runtime.py`.

2. Task 2.5.a will scaffold every documented noun and verb, but handlers for
   later tasks will remain thin placeholders with deterministic behaviour.

   Rationale: the operator grammar must stabilize now, while the actual estate,
   ingestion, reporting, export, and runtime workflows are split into later
   roadmap tasks.

3. Backend selection for `cuprum` and `python-api` will be validated as part of
   the public contract even if only lightweight placeholder adapters exist at
   this stage.

   Rationale: validated option parsing is part of the completion criteria, and
   later tasks need the selector to exist before they can attach real runtime
   behaviour.

4. The scaffold will resolve all global configuration into one typed context
   object before it reaches noun handlers.

   Rationale: this is the cleanest way to keep Cyclopts parsing, config
   precedence, `httpx` client construction, and adapter selection testable in
   isolation.

5. The plan preserves the documented `cuprum` spelling for now.

   Rationale: the roadmap and CLI specification already publish that selector.
   Renaming it in implementation without a documented decision would create
   contract drift.

6. Task 2.5.a does not include the project-evidence completion criterion from
   the user prompt.

   Rationale: that criterion belongs to multi-repository project evidence work
   and is not part of the roadmap text for Task 2.5.a. The plan calls this out
   explicitly rather than smuggling unrelated work into the scaffold.

## Context and orientation

The key repository facts a new implementor needs are these.

`docs/roadmap.md` defines Task 2.5.a as the entry task for the operator-facing
control plane. It requires a noun/verb CLI grammar, shared global options,
`httpx` control-plane client plumbing, and local runtime adapter selection.

`docs/mvp-cli-specification.md` already describes the desired operator contract
in detail. It names the shared options, config precedence, persisted state
files, root command tree, and backend labels. The implementation must follow
that document and update it only when reality forces a clarifying change.

The current reusable runtime and API surfaces are limited:

- `ghillie/api/app.py` and related API modules expose the current Falcon ASGI
  application and the on-demand repository report endpoint.
- `ghillie/runtime.py` is the current server entry point and must not be
  disturbed by the CLI scaffold.
- `scripts/local_k8s.py` is a working Cyclopts script for the local preview
  workflow, backed by modules under `scripts/local_k8s/`. It is a reference for
  command structure and tests, not the final operator CLI.

The tests already show the repo's preferred patterns:

- unit tests for CLI structure and pure config logic,
- Falcon endpoint tests at the application boundary, and
- `pytest-bdd` scenarios with feature files under `tests/features/` and step
  implementations under `tests/features/steps/`.

The new CLI scaffold should reuse those patterns rather than inventing new ones.

## Implementation plan

## Milestone 1: lock the contract with failing tests

Begin with tests that describe the scaffold, not later business logic.

Create new unit tests under `tests/unit/cli/` for the packaged app and the
small typed pieces that make it work. A good first cut is:

- `tests/unit/cli/test_app.py`
- `tests/unit/cli/test_global_options.py`
- `tests/unit/cli/test_config_resolution.py`
- `tests/unit/cli/test_control_plane_client.py`
- `tests/unit/cli/test_runtime_adapter_selection.py`

These tests should assert, before any implementation exists, that:

1. there is a packaged app object named `ghillie`,
2. the root nouns match the spec exactly,
3. each noun exposes the documented verbs,
4. root-global options parse before the noun and end up in one resolved config
   object,
5. config precedence is flag, environment, profile file, persisted state, then
   hard fallback,
6. the control-plane client builder turns config into `httpx` base URL,
   timeout, and auth headers correctly, and
7. runtime adapter selection accepts `cuprum` and `python-api` and rejects any
   other value.

Add behavioural coverage with `pytest-bdd` using a feature file such as
`tests/features/operator_cli_contract.feature` and a step module such as
`tests/features/steps/test_operator_cli_steps.py`.

Keep the scenarios black-box and operator-visible. Cover at least:

1. `ghillie --help` lists the six top-level nouns,
2. `ghillie stack up --help` exposes the documented backend and wait options,
3. `ghillie --api-base-url http://127.0.0.1:9999 report run --help` parses
   successfully, proving that root-global options are accepted before the noun,
   and
4. `ghillie stack up --backend invalid` fails fast with a validation error.

Run the targeted tests first and capture the red phase before implementation.

Suggested commands:

```bash
set -o pipefail
UV_CACHE_DIR=.uv-cache UV_TOOL_DIR=.uv-tools uv run pytest tests/unit/cli -v 2>&1 | tee /tmp/ghillie-cli-unit-red.log
```

```bash
set -o pipefail
UV_CACHE_DIR=.uv-cache UV_TOOL_DIR=.uv-tools uv run pytest \
  tests/features/steps/test_operator_cli_steps.py -v 2>&1 | \
  tee /tmp/ghillie-cli-bdd-red.log
```

## Milestone 2: build the packaged CLI core

Add a new package rooted at `ghillie/cli/`. Keep it small, explicit, and easy
to extend.

Create or update these files:

- `ghillie/cli/__init__.py`
- `ghillie/cli/__main__.py`
- `ghillie/cli/app.py`
- `ghillie/cli/context.py`
- `ghillie/cli/config.py`
- `ghillie/cli/control_plane.py`
- `ghillie/cli/runtime.py` or `ghillie/cli/runtime_adapters.py`

Update `pyproject.toml` to expose the console entry point and to carry the CLI
runtime dependencies under `[project.dependencies]`, not only in the
development group.

The scaffold should define four stable concepts:

1. `GlobalOptions`, a frozen dataclass for the raw root options parsed by
   Cyclopts.
2. `ResolvedCliConfig`, a frozen dataclass for post-precedence values that
   handlers actually consume.
3. `ControlPlaneClient`, a small `httpx` wrapper that knows base URL, auth, and
   timeout.
4. `LocalRuntimeAdapter`, a port or protocol for stack-facing operations such
   as `up`, `down`, `status`, and `logs`.

Keep config loading separate from command registration. That separation makes
config precedence and client construction testable without spinning the full
command tree.

## Milestone 3: register the noun and verb tree

Implement the root Cyclopts app and one command group per noun:

- `stack`
- `estate`
- `ingest`
- `export`
- `report`
- `metrics`

Under each noun, register the verbs listed in `docs/mvp-cli-specification.md`.
A practical layout is one module per noun:

- `ghillie/cli/commands/stack.py`
- `ghillie/cli/commands/estate.py`
- `ghillie/cli/commands/ingest.py`
- `ghillie/cli/commands/export.py`
- `ghillie/cli/commands/report.py`
- `ghillie/cli/commands/metrics.py`

Each handler should do only the minimum needed in Task 2.5.a:

1. resolve the shared CLI context,
2. build the right client or adapter,
3. validate the documented options, and
4. return a deterministic placeholder for behaviours owned by later tasks.

Define the placeholder behaviour explicitly in the docs and tests. The easiest
contract is:

- `--help` always works,
- valid command invocations that belong to later tasks return a clear
  "not implemented in Task 2.5.a" message, and
- invalid options fail through normal Cyclopts validation.

Do not let placeholder handlers turn into arbitrary `print()` calls. They
should still route through one output policy so that `--output json` remains
predictable.

## Milestone 4: wire the driven adapters cleanly

Implement the control-plane client for real. Even if the CLI does not yet call
many endpoints, the object itself should be functional and tested. It should
own:

- base URL handling,
- timeout configuration,
- bearer-token header injection, and
- creation and cleanup of the `httpx` client.

Implement runtime adapter selection as a clean seam. For Task 2.5.a the
selection logic must be real even if execution remains skeletal:

- selecting `python-api` constructs the adapter class intended to host direct
  Python integrations later,
- selecting `cuprum` constructs a separate adapter class, which may remain a
  placeholder until a concrete dependency decision is made, and
- unknown adapter names fail validation before any side effects occur.

Do not make the packaged CLI depend on imports from `scripts/` just to satisfy
Task 2.5.a. If a tiny shared helper must move to support clean packaging,
extract only that helper into `ghillie/cli/` or another non-conflicting package
inside `ghillie/`. Leave broader local runtime migration for later work.

## Milestone 5: update the contract documents

Update the documents that operators and future implementors will read.

`docs/mvp-cli-specification.md` must reflect the implemented command tree,
placeholder semantics, and any clarifications to config resolution or help
behaviour discovered during implementation.

`docs/users-guide.md` must gain an operator CLI section that shows:

- how to inspect the root command tree,
- how shared configuration is resolved, and
- what the scaffold can do at Task 2.5.a versus what remains for later tasks.

`docs/ghillie-design.md` must record the architectural decision that the
operator CLI is a driving adapter with separate control-plane and local-runtime
driven adapters.

`docs/roadmap.md` must mark Task 2.5.a as done only after the implementation,
tests, documentation updates, and quality gates all pass.

## Validation and evidence

Use a red-green-refactor loop for the targeted CLI tests, then run the full
repository gates sequentially. Run the Make targets through `tee` with
`set -o pipefail` so failures are preserved in the exit code and logs can be
inspected afterwards.

Suggested verification commands:

```bash
set -o pipefail
make fmt 2>&1 | tee /tmp/ghillie-make-fmt.log
```

```bash
set -o pipefail
make check-fmt 2>&1 | tee /tmp/ghillie-make-check-fmt.log
```

```bash
set -o pipefail
make typecheck 2>&1 | tee /tmp/ghillie-make-typecheck.log
```

```bash
set -o pipefail
make lint 2>&1 | tee /tmp/ghillie-make-lint.log
```

```bash
set -o pipefail
make test 2>&1 | tee /tmp/ghillie-make-test.log
```

```bash
set -o pipefail
MDLINT=/root/.bun/bin/markdownlint-cli2 make markdownlint 2>&1 | tee /tmp/ghillie-make-markdownlint.log
```

```bash
set -o pipefail
make nixie 2>&1 | tee /tmp/ghillie-make-nixie.log
```

Record concise evidence in this plan once implementation happens. At minimum,
capture:

- the help output proving the noun tree,
- one example showing a valid root-global option parse,
- one example showing invalid backend rejection, and
- the final gate results.

Expected operator-visible evidence after completion should look roughly like:

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

Task 2.5.a is implemented.

The repo now carries a packaged operator CLI scaffold under `ghillie/cli/` with
a console entry point named `ghillie`. The root app exposes the six documented
nouns, accepts shared configuration once at the root, resolves that
configuration into one typed context object, constructs a real `httpx`
control-plane client wrapper, and selects a local runtime adapter named
`cuprum` or `python-api`.

The command handlers intentionally remain deterministic placeholders for later
Step 2.5 tasks. Valid invocations return a stable
`not implemented in Task 2.5.a` status through a shared output policy, while
invalid options fail during parsing.

Operator-visible evidence captured during implementation:

```plaintext
$ uv run ghillie --help
... stack ...
... estate ...
... ingest ...
... export ...
... report ...
... metrics ...

$ uv run ghillie --api-base-url http://127.0.0.1:9999 report run --help
Usage: ghillie report run [OPTIONS]

$ uv run ghillie stack up --backend invalid
Error: invalid choice for --backend: "invalid"
```

Test and gate evidence captured during implementation:

- Targeted red phase:
  `uv run pytest tests/unit/cli -v` failed with
  `ModuleNotFoundError: No module named 'ghillie.cli'`.
- Targeted red phase:
  `uv run pytest tests/features/steps/test_operator_cli_steps.py -v` failed
  with the same missing-package error.
- Targeted green phase: `uv run pytest tests/unit/cli -v` passed with
  `14 passed`.
- Targeted green phase:
  `uv run pytest tests/features/steps/test_operator_cli_steps.py -v` passed
  with `4 passed`.
- Full repository gates passed:
  `make fmt`, `make check-fmt`, `make typecheck`, `make lint`, `make test`,
  `MDLINT=/root/.bun/bin/markdownlint-cli2 make markdownlint`, and `make nixie`.
- Final test suite result during the full gate run: `730 passed, 35 skipped`.

This leaves the grammar stable, the adapter boundaries explicit, the
documentation aligned, and the repository ready for the follow-on Task 2.5 work
without dragging later runtime behaviour into this entry task.
