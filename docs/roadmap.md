# Ghillie roadmap

This roadmap translates the Ghillie design set into an outcome-oriented
delivery sequence. It is grounded in
[ghillie-design.md](ghillie-design.md), [Bronze and Silver design](ghillie-bronze-silver-architecture-design.md),
the [MVP CLI specification](mvp-cli-specification.md), and the decision
records in [docs/adrs](adrs/). It does not promise dates.

The roadmap follows the Goals, Ideas, Steps, Tasks (GIST) model. Each phase
states one testable idea. Each step is a workstream that validates or falsifies
part of that idea and answers a question that affects later work. Each task is
a review-sized execution unit with observable success criteria. Dependencies
use dotted roadmap notation so that sequencing survives restructuring.

Phases 1 and 2 together constitute the initial Ghillie MVP: a system that
reliably ingests GitHub activity for a managed set of repositories, constructs
evidence bundles, and produces repository-level status reports on a regular
cadence. Later phases extend the same evidence and summarization loop to
projects, the estate, governance data, developer portals, and trend analysis.

## 1. Establish a trustworthy estate model and ingestion pipeline

Idea: if Ghillie settles the estate catalogue, the Medallion storage model, and
one GitHub ingestion path before reporting work begins, later reports can be
regenerated from durable evidence rather than depending on ad hoc API calls or
transient state.

Phase 1 creates the foundation on which every later phase depends. The outcome
is a reliable model of the engineering estate, backed by a durable ingestion
and storage pipeline that can replay raw events into refined entities.

### 1.1. Define the estate catalogue and configuration

This step answers whether one version-controlled catalogue can describe
projects, components, repositories, and their relationships precisely enough to
drive ingestion and reporting. Its outcome determines the configuration surface
used by every later phase. See ghillie-design.md §3.4 and
ghillie-bronze-silver-architecture-design.md §9.1.

- [x] 1.1.1. Define the estate catalogue schema.
  - Define a YAML-based configuration schema for:
    - projects and programmes (for example, Wildside, Limela, mxd,
      Episodic),
    - components within each project, including components that do not yet
      have repositories,
    - repository mappings and default branches,
    - component-to-component relationships (depends on, blocked by,
      emits events to),
    - noise filters and status configuration per project.
  - See ghillie-design.md §3.4.
  - Success: At least one multi-repository project is fully represented in
    the catalogue, including planned components without repositories, and the
    schema is validated by a documented linter or JSON Schema.
- [x] 1.1.2. Implement the catalogue importer and reconciler.
  - Implement a background service that watches the catalogue repository,
    parses project definitions, and reconciles them into the database tables
    for estates, projects, components, component edges, and repositories.
  - Requires 1.1.1.
  - See ghillie-bronze-silver-architecture-design.md §9.1.
  - Success: Running the importer on a changed catalogue commit updates the
    database idempotently. Invalid configuration fails fast with a clear error
    and does not partially update state.
- [x] 1.1.3. Support per-project noise control and status settings.
  - Extend the catalogue schema to store:
    - labels, authors, and paths to ignore when creating events,
    - any repository-specific documentation paths (for example, roadmap
      files, ADR directories),
    - project-level knobs that influence status generation (for example,
      whether dependency pull requests are summarized or ignored).
  - Requires 1.1.1.
  - See ghillie-design.md §3.4.
  - Success: At least one project has custom noise rules and documentation
    locations defined in the catalogue, and these settings are visible to
    downstream services.

### 1.2. Implement the core data model and Medallion layers

This step answers whether raw GitHub activity can be stored immutably and
refined into stable reporting entities without losing provenance. Its outcome
determines whether later reports can be replayed and reprocessed safely. See
ghillie-design.md §§2.1-2.3 and ghillie-bronze-silver-architecture-design.md
§§3-6.

- [x] 1.2.1. Implement the Bronze raw event store.
  - Introduce an append-only `raw_events` store that captures unmodified
    payloads from GitHub (and later Concordat), tagged with event type,
    repository identity, and ingestion timestamp.
  - See ghillie-bronze-silver-architecture-design.md §3.1.
  - Success: Every ingestion run writes raw GitHub events to the Bronze
    store. Re-running the transformation job on the same events produces
    identical Silver-layer records.
- [x] 1.2.2. Implement the Silver entity tables.
  - Define relational tables for repositories, commits, pull requests,
    issues, and documentation changes, alongside JSON-capable columns for
    flexible payloads where necessary. Implement transformation jobs that
    hydrate these tables from `raw_events`.
  - Requires 1.2.1.
  - See ghillie-bronze-silver-architecture-design.md §§3.2 and 6.
  - Success: For a pilot set of repositories, commits, pull requests, issues,
    and documentation changes appear in Silver tables with correct foreign
    keys to repositories and stable identifiers for later reporting.
- [x] 1.2.3. Implement the Gold report metadata schema.
  - Define tables for reports and report coverage, including fields for scope
    (repository, project, estate), reporting window, and machine summaries.
  - Requires 1.2.2.
  - See ghillie-bronze-silver-architecture-design.md §10.1.
  - Success: Repository and project records can be linked to zero or more
    report records, and the schema supports storing the identifiers of events
    consumed by each report.

### 1.3. Build the GitHub ingestion service

This step answers whether Ghillie can ingest GitHub activity for the managed
estate with controlled noise and back-pressure. Its outcome provides the event
volume that later evidence bundles and reports consume. See ghillie-design.md
§§3.1-3.2 and §8.2, and ghillie-bronze-silver-architecture-design.md §5.2.

- [x] 1.3.1. Implement repository discovery and registration.
  - Derive the managed repository set from the estate catalogue and any
    allowlist labels or naming conventions. Store GitHub owner, name, and
    default branch, along with any metadata required by later stages.
  - Requires 1.1.2.
  - See ghillie-bronze-silver-architecture-design.md §9.2.
  - Success: The system maintains an accurate list of active repositories for
    at least one organization and can enable or disable ingestion per
    repository.
- [x] 1.3.2. Implement incremental GitHub ingestion.
  - Implement a worker that, per repository, fetches new commits to the
    default branch, pull requests, issues, and selected documentation changes
    since the last ingestion time, using the GitHub GraphQL API where
    practical.
  - Requires 1.3.1 and 1.2.1.
  - See ghillie-design.md §§3.1-3.2 and §8.2, and
    ghillie-bronze-silver-architecture-design.md §5.2.
  - Success: For pilot repositories, commits, pull requests, issues, and
    documentation changes are captured into `raw_events` within a bounded
    delay after they occur.
- [x] 1.3.3. Apply noise filters from configuration.
  - Apply project-specific filters to ignore events from known bots,
    dependency update tools, or paths deemed irrelevant, as defined in the
    catalogue.
  - Requires 1.3.2 and 1.1.3.
  - See ghillie-design.md §3.4.
  - Success: Noise filters can be enabled or disabled per project. Toggling a
    filter changes the set of events ingested for the next run without code
    changes.
- [x] 1.3.4. Add observability for ingestion health.
  - Emit metrics and logs for ingestion throughput, failures, and backlog, and
    define basic alerts for stalled ingestion.
  - Requires 1.3.2.
  - See ghillie-design.md §3.4.
  - Success: Operators can see ingestion lag per repository and can identify
    failing ingestion runs through the metrics and logs alone.
- [x] 1.3.5. Migrate to the femtologging library.
  - Replace Python standard-library logging with femtologging across the
    codebase. Femtologging provides async-friendly logging with bounded
    queues, aligning with Ghillie's async architecture and supporting the
    structured logging patterns required for observability.
  - Prerequisite: femtologging provides `exc_info` and `stack_info` support
    and the `v0.1.0` standard-library-compatibility methods in commit
    `691a73962df8f99308a82348d99c4f707c245e63`.
  - See adrs/adr-0001-adoption-of-femtologging-library.md.
  - Success: All logging usage in ingestion, observability, runtime start-up,
    and tests is migrated to femtologging. Logging configuration is
    centralized at application entry points (runtime server, worker, and
    CLI). The exception and logging guidelines in
    `.rules/python-exception-design-raising-handling-and-logging.md` are
    updated to reflect femtologging patterns.

### 1.4. Secure integration with GitHub

This step answers whether Ghillie can access GitHub with least privilege and
operationally manageable credentials. Its outcome determines whether production
ingestion can be trusted and rotated safely. See ghillie-design.md §8.1 and
github-application-configuration.md.

- [x] 1.4.1. Configure a GitHub App with least-privilege scopes.
  - Document the requirements for a GitHub App with read-only access to
    metadata and documentation paths required for Ghillie. Avoid direct
    source code blob access where possible.
  - See ghillie-design.md §8.1.
  - Success: A document `docs/github-application-configuration.md` is created
    that clearly sets out the process for creation of this application and
    the capabilities needed. The document must be easy to follow for someone
    unfamiliar with this process.
- [ ] 1.4.2. Implement secure credential storage and rotation.
  - Store GitHub App secrets in an approved secrets manager and define a
    documented process for rotating keys, including any required restarts or
    reloads.
  - Requires 1.4.1.
  - See ghillie-design.md §8.1.
  - Success: GitHub credentials can be rotated without redeploying ingestion
    services, and failed authentication is surfaced as a clear operational
    alert.

### 1.5. Provide a local Kubernetes preview environment

This step answers whether a repeatable local k3d preview can mirror the
ephemeral previews platform and exercise the Ghillie Helm chart. Its outcome
reduces deployment risk before hosted environments exist. See
local-k8s-preview-design.md and k3d-python-example.md.

- [x] 1.5.1. Document the local preview design.
  - Create a design document that specifies the Helm chart interface,
    container build, and local k3d lifecycle script, including compatibility
    with the GitOps ephemeral previews architecture.
  - See k3d-python-example.md.
  - Success: The document `docs/local-k8s-preview-design.md` exists and covers
    all required design elements, including chart, Dockerfile, and script
    sketches.
- [x] 1.5.2. Implement the Ghillie Helm chart for previews.
  - Build the `charts/ghillie` Helm chart with support for local and GitOps
    environments, including configurable ingress and external secrets.
  - Requires 1.5.1.
  - See local-k8s-preview-design.md.
  - Success: `helm lint charts/ghillie` passes, and the chart can be installed
    with local values or HelmRelease values in the GitOps flow.
- [x] 1.5.3. Define the container image for preview workloads.
  - Add a multi-stage Dockerfile and runtime entrypoint suitable for
    Kubernetes, with configuration driven by environment variables and chart
    values.
  - Requires 1.5.1.
  - See local-k8s-preview-design.md.
  - Success: A local build produces an image that starts the runtime entrypoint
    without errors when deployed.
- [x] 1.5.4. Implement the local k3d lifecycle script.
  - Provide a Python script and Makefile targets to create a k3d cluster,
    install platform dependencies, deploy the Ghillie chart, and surface the
    preview URL.
  - Requires 1.5.2 and 1.5.3.
  - See local-k8s-preview-design.md.
  - Success: `make local-k8s-up` and `make local-k8s-down` succeed end to end,
    and `make local-k8s-status` reports ready pods.
- [x] 1.5.5. Provision Valkey via valkey-operator.
  - Install `valkey-operator` in the local development cluster and create a
    minimal Valkey instance for Ghillie to consume, mirroring the platform
    approach.
  - Requires 1.5.4.
  - See local-k8s-preview-design.md.
  - Success: The Valkey operator reconciles a Valkey resource, and the local
    preview script wires its connection details into the Ghillie Secret.
- [x] 1.5.6. Document local preview usage.
  - Update the users' guide with instructions for running the local preview
    workflow and troubleshooting common issues.
  - Requires 1.5.4 and 1.5.5.
  - See users-guide.md.
  - Success: The users' guide includes a local preview section with validated
    commands and expected outcomes.

### 1.6. Guard architecture boundaries

This step answers whether architecture drift can be made visible before it
reaches review or continuous integration (CI). Its outcome protects the
hexagonal dependency rule as later phases add adapters. See
adrs/adr-0003-adopt-hecate-for-architecture-checks.md.

- [x] 1.6.1. Adopt Hecate architecture checks.
  - Add Hecate as the repository's static import-direction gate for the
    hexagonal architecture policy.
  - See adrs/adr-0003-adopt-hecate-for-architecture-checks.md.
  - Success: `make check-architecture` runs the pinned Hecate checker against
    `[tool.hecate]`, `make lint` runs the architecture gate before Ruff, CI
    uses the combined lint target, and the adoption is recorded in ADR-003.

______________________________________________________________________

## 2. Deliver repository-level status reporting for the MVP

Idea: if repository evidence bundles and an abstracted status model can produce
trustworthy scheduled reports through stable operator interfaces, Ghillie
delivers a useful MVP before project, estate, or governance views exist.

Phase 2 delivers a minimum viable product (MVP): regular, repository-level
status reports generated from ingested events and stored in the Gold layer.
These reports are the first directly consumable output of Ghillie.

### 2.1. Implement evidence bundle generation

This step answers whether Silver-layer data can be assembled into a complete,
idempotent evidence bundle for one repository window. Its outcome determines
what the status model sees and whether reports can avoid repeating covered
events. See ghillie-design.md §§9.1-9.3.

- [x] 2.1.1. Define the repository evidence structure.
  - Design an in-memory representation for a repository reporting window that
    includes:
    - basic repository metadata,
    - previous one or two repository reports (where available),
    - new commits, pull requests, issues, and documentation changes within
      the reporting window,
    - groupings by work type (for example, feature, bug, refactor, chore)
      based on labels and heuristics.
  - Requires 1.2.2 and 1.2.3.
  - See ghillie-design.md §§9.1-9.3.
  - Success: The evidence structure is fully populated for the pilot
    repositories, and unit tests confirm correct grouping of events.
- [x] 2.1.2. Implement event selection and grouping per window.
  - Add logic to select events between `window_start` and `window_end`,
    excluding any events already covered by previous reports via the report
    coverage table.
  - Requires 2.1.1.
  - See ghillie-design.md §9.2.
  - Success: For a given repository and reporting window, evidence bundles
    include only new events. Re-running the reporting job does not change the
    bundle unless new events have arrived.

### 2.2. Integrate large language models behind an abstraction

This step answers whether LLM-backed summarization can remain independent of
vendor choices and context-window sizes. Its outcome determines how reporting
work selects and configures a model. See ghillie-design.md §§9.4-9.5 and §10.

- [x] 2.2.1. Define the status model interface.
  - Define an interface for a status model with operations to summarize a
    repository evidence bundle and return structured output, including
    summary text, status code (for example, on track, at risk, blocked,
    unknown), highlights, risks, and suggested next steps.
  - Requires 2.1.1.
  - See ghillie-design.md §9.4.
  - Success: At least one implementation of the interface is available in
    code, with tests that mock model responses.
- [x] 2.2.2. Implement the initial LLM integration.
  - Implement an integration with a chosen model (for example,
    GPT-5.1-thinking) using the status model interface. Include prompt
    templates that:
    - provide previous reports and new events,
    - instruct the model not to repeat unchanged information,
    - request both narrative and structured JSON output.
  - Requires 2.2.1.
  - See ghillie-design.md §9.5 and §10.
  - Success: For test evidence bundles, the model returns parseable JSON and
    narrative text that passes basic quality checks (no hallucinated
    repositories, correct reflection of event counts).
- [x] 2.2.3. Provide configuration for model selection.
  - Allow operators to select the model backend and key configuration
    (temperature, maximum tokens) per environment.
  - Requires 2.2.2.
  - See ghillie-design.md §9.4.
  - Success: The same reporting job can be run against two different model
    backends without code changes, by configuration alone.

### 2.3. Generate and store repository reports

This step answers whether reports can be produced and persisted on a regular
schedule from the evidence and model integrations. Its outcome gives operators
a predictable report location and an on-demand trigger. See ghillie-design.md
§§9.6-9.7 and §8.4.

- [x] 2.3.1. Implement the reporting scheduler and workflow.
  - Add a scheduled job that, for each managed repository, determines the
    next reporting window, constructs an evidence bundle, invokes the status
    model, and writes a report record and associated report coverage records.
  - Requires 2.1.2 and 2.2.2.
  - See ghillie-design.md §9.6.
  - Success: For pilot repositories, a full reporting run creates one report
    per repository within the configured window and marks all events in that
    window as covered.
  - Implemented: `ghillie.reporting` module with `ReportingService`,
    `ReportingConfig`, and Dramatiq actors (`generate_report_job`,
    `generate_reports_for_estate_job`). Window computation continues from the
    previous report's end time. Behaviour-Driven Development (BDD) and unit
    tests cover report generation, window computation, and estate-wide
    scheduling.
- [x] 2.3.2. Implement report Markdown rendering and filesystem storage.
  - Implement a Markdown renderer for repository reports covering status
    summary, highlights, risks, and next steps. Provide a filesystem storage
    adapter that writes rendered reports to a configurable base directory.
  - Requires 2.3.1.
  - See ghillie-design.md §9.7.
  - Success: Operators can navigate to a repository's latest report via a
    predictable path or URL, and the report content matches the data stored
    in the database.
  - Implemented: `ghillie.reporting.markdown` module with
    `render_report_markdown()` pure function rendering from
    `Report.machine_summary`. `ReportSink` protocol (port) with
    `FilesystemReportSink` adapter writing to
    `{base_path}/{owner}/{name}/latest.md` and dated archive files.
    `ReportingService` optionally invokes the sink
    after report persistence. `GHILLIE_REPORT_SINK_PATH` environment variable
    controls filesystem sink creation in Dramatiq actors. Unit tests (nine
    renderer tests, six sink, six config/integration) and BDD scenarios (two)
    validate the implementation.
- [x] 2.3.3. Provide an on-demand reporting entry-point.
  - Implement `POST /reports/repositories/{owner}/{name}` as an HTTP API
    endpoint. Use the modular `ghillie/api/` package structure from Section
    8.4 of the design document. Reuse `ReportingService.run_for_repository()`
    and render Markdown through the same `ReportSink` as scheduled reports.
    Return 200 with report metadata, 204 when no events are in the window, or
    404 for unknown repositories.
  - Requires 2.3.2.
  - See ghillie-design.md §8.4 and §9.7.
  - Success: An operator can trigger a fresh report for a repository and see
    the updated Markdown rendered through the same path as scheduled reports.
  - Implemented: The endpoint reuses the existing
    `ReportingService.run_for_repository()` pipeline and renders Markdown
    through the same `ReportSink` as scheduled reports.

### 2.4. Instrument quality and operational feedback

This step answers whether repository reports are accurate enough to trust and
operationally safe to run. Its outcome determines whether broken model output
is rejected and whether cost and latency are observable. See ghillie-design.md
§§9.6.1-9.6.2.

- [x] 2.4.1. Add basic correctness checks for generated reports.
  - Implement post-generation validation that ensures the number of
    highlighted changes is plausible relative to the number of events in the
    evidence bundle and that the model has not produced empty or truncated
    output.
  - Requires 2.3.1.
  - See ghillie-design.md §9.6.1.
  - Success: Invalid or clearly broken reports are rejected and retried or
    marked for human review, rather than silently stored.
  - Implemented: `ghillie.reporting.validation` module with three heuristic
    checks (non-empty summary, truncation detection, highlight plausibility).
    `ReportingService.generate_report` retries model invocation up to
    `validation_max_attempts` times (default 2). Exhausted retries persist a
    `ReportReview` Gold-layer marker with failure details and lifecycle state.
    The on-demand API returns HTTP 422 with validation failure details and a
    review reference. Unit tests (validation rules, retry and review
    behaviour, API mapping), schema tests (ReportReview persistence and
    uniqueness), and `pytest-bdd` scenarios cover the new behaviour.
- [x] 2.4.2. Capture reporting metrics and costs.
  - Emit metrics for the number of reports generated, average model latency,
    and approximate token usage per run.
  - Requires 2.3.1.
  - See ghillie-design.md §9.6.2.
  - Success: Operators can see the total reporting cost and latency profile
    for the pilot estate over a given period.
  - Implemented: Gold `Report` metadata now stores nullable
    `model_latency_ms`, `prompt_tokens`, `completion_tokens`, and
    `total_tokens` fields per generated report. `ReportingService` captures
    service-level model latency and adapter token usage for each invocation,
    while `ReportingEventLogger` emits structured lifecycle events
    (`reporting.report.started`, `reporting.report.completed`,
    `reporting.report.failed`). `ReportingMetricsService` provides aggregate
    period and estate snapshots (total reports, average and p95 latency,
    token totals), and on-demand API report responses include a `metrics`
    payload.

### 2.5. Provide an operator-facing MVP control plane and CLI

This step answers whether the full MVP workflow can be executed through stable
HTTP APIs and a single `cyclopts` command-line interface (CLI), without ad hoc
scripts. Its outcome determines the operator surface that later export,
metrics, and runtime-profile tasks extend. See mvp-cli-specification.md,
ghillie-design.md §3.0, §8.4, and §8.5.

- [x] 2.5.1. Define and scaffold the operator CLI contract.
  - Define the command grammar and command groups in
    `docs/mvp-cli-specification.md`, and scaffold a `cyclopts` CLI with the
    following features:
    - noun/verb command structure (`ghillie <noun> <verb>`),
    - shared global options for API URL, auth, output, and timeouts,
    - `httpx` control-plane client plumbing,
    - local runtime integration adapter selection (`cuprum` or direct Python
      API integrations for Docker, Helm, and Kubernetes).
  - See mvp-cli-specification.md and ghillie-design.md §3.0 and §8.4.
  - Success: A runnable CLI skeleton exists with the specified root command
    tree and validated option parsing.
  - Implemented: The packaged `ghillie` console entry point now lives under
    `ghillie/cli/` and exposes the full MVP noun tree (`stack`, `estate`,
    `ingest`, `export`, `report`, `metrics`). This task added root-global
    option parsing and precedence resolution, a reusable `httpx`
    control-plane client wrapper, runtime adapter selection for `cuprum` and
    `python-api`, unit tests for the CLI scaffold, and `pytest-bdd` coverage
    for help output, root option parsing, and invalid backend rejection.
- [x] 2.5.2. Add estate-management APIs and CLI commands.
  - Implement API endpoints and CLI commands for the following estate
    operations:
    - catalogue import per estate,
    - registry sync from catalogue,
    - repository listing and ingestion enable/disable toggles.
  - Requires 2.5.1.
  - See ghillie-design.md §8.5.
  - Success: An operator can configure estate repositories end to end via CLI
    and HTTP APIs, with no direct Python scripting.
  - Implemented: The runtime exposes five estate endpoints (catalogue import,
    registry sync, estate listing, repository listing, and ingestion
    toggling) documented in OpenAPI 3.1, and
    `ghillie estate import|sync|list|repo list|repo set` drives them from the
    CLI. Import and sync support dry runs; the live-only toggle refuses one
    locally. A registry sync preserves operator ingestion toggles (ADR-005),
    and the work is covered by unit tests, `pytest-bdd` scenarios, and an
    end-to-end test that runs the packaged console script against a real
    server process. Delivered as three stacked pull requests (D19); the
    runtime-profile hand-off remains in the runtime-profiles task.
- [ ] 2.5.3. Add manual ingestion run APIs with run-state tracking.
  - Implement explicit ingestion run triggering (`repository` or `estate`
    scope) with lookback window override and persistent run-state queries.
  - Requires 2.5.1.
  - See mvp-cli-specification.md.
  - Success: A two-week (`lookback_days=14`) ingestion run can be started,
    monitored, and completed through API and CLI alone.
- [ ] 2.5.4. Add manual reporting run APIs for repository and estate.
  - Extend on-demand reporting to support:
    - repository and estate run triggers,
    - explicit window and as-of overrides,
    - run-state retrieval for asynchronous workflows.
  - Requires 2.5.1 and 2.3.3.
  - See mvp-cli-specification.md.
  - Success: Operators can trigger LLM report generation for an explicit
    two-week window and monitor run state via API and CLI.
- [ ] 2.5.5. Add k3d and Helm runtime profiles and a provider setup path.
  - Provide explicit local runtime profiles (`api-only`, `ingestion-worker`,
    `reporting-worker`) and CLI-assisted provider configuration for GitHub
    and inference backends.
  - Requires 2.5.1 and 2.5.2.
  - See ghillie-design.md §8.4.
  - Success: `api-only` start-up with no background workers is a documented,
    repeatable command path with readiness checks.
  - Carried forward from the estate-management task (D15): the estate control
    plane needs a database and an optional bootstrap. `GHILLIE_DATABASE_URL`
    selects the database, `GHILLIE_DB_BOOTSTRAP=create-all` creates missing
    tables for local runs, and `GHILLIE_API_TOKEN` enables bearer auth. The
    runtime profiles added here should state which variables each profile
    expects and leave `GHILLIE_DB_BOOTSTRAP` unset in production, where
    migrations own the schema.
  - Two further D15 items remain open and belong to this task:
    - Add an import-time broker guard. Importing `ghillie.api.app` or
      `ghillie.api.factory` currently raises `RuntimeError: No Dramatiq broker
      configured` unless `GHILLIE_ALLOW_STUB_BROKER` is set, because the
      reporting actor is imported at module load. A worker-free `api-only`
      profile must not require a broker to start.
    - Reconcile the Helm environment and driver mismatch. The chart and the
      runtime disagree on the database variable name (`DATABASE_URL` versus
      `GHILLIE_DATABASE_URL`) and on the driver scheme (`postgresql://` versus
      the asyncpg driver the runtime expects). Reconcile both so a chart
      deployment reaches the database it configures.

### 2.6. Deliver structured exports and required MVP metrics

This step answers whether the required key performance indicator (KPI) and
export capabilities are available through stable operator interfaces. Its
outcome completes the MVP control-plane surface before optional analytics work
starts. See ghillie-design.md §6.2 and mvp-gap-analysis.md.

- [ ] 2.6.1. Implement structured export APIs and CLI commands.
  - Add export surfaces for collected events, derived evidence bundles, and
    report outputs with lineage metadata.
  - Requires 2.5.2, 2.5.3, and 2.5.4.
  - See mvp-gap-analysis.md.
  - Success: Operators can generate versioned structured exports (for
    example, JSON, JSONL, or CSV where applicable) for a selected two-week
    window using API or CLI.
- [ ] 2.6.2. Implement required metrics APIs and CLI commands.
  - Expose required MVP metrics per repository:
    - pull requests merged and closed counts,
    - average pull request open-to-merge duration,
    - resolved and outstanding issue counts,
    - issue open duration for resolved and unresolved issues.
  - Requires 2.5.2, 2.5.3, and 2.5.4.
  - See ghillie-design.md §6.2.
  - Success: Required metrics are queryable by repository and estate scope
    for an operator-selected reporting window.
- [ ] 2.6.3. Align OpenAPI and user documentation with the runtime.
  - Ensure OpenAPI schemas and user-facing documentation match the
    implemented API responses, including validation failures and metrics
    payloads.
  - Requires 2.6.1 and 2.6.2.
  - Success: API behaviour, OpenAPI definitions, and documented examples are
    consistent and validated in CI.

### 2.7. Capture nice-to-have metrics inputs

This step answers whether the data model and ingestion signals needed for
optional engineering insight metrics exist. Its outcome enables later analytics
without widening the core Medallion pipeline. See ghillie-design.md §6.2.

- [ ] 2.7.1. Ingest and store pull request comments.
  - Extend GitHub ingestion and Silver storage to persist pull request
    comments and commenter identity for repository-scoped analytics.
  - Requires 2.6.1.
  - See ghillie-design.md §6.2.
  - Success: Comment counts by repository and commenter are queryable from
    persisted data.
- [ ] 2.7.2. Ingest and store per-pull-request commit and file statistics.
  - Extend ingestion to persist commit counts and changed-file statistics for
    each pull request.
  - Requires 2.6.1.
  - See ghillie-design.md §6.2.
  - Success: Commit counts per pull request and file-level change statistics
    are available for downstream metrics computations.
- [ ] 2.7.3. Implement source-line-of-code categorization and metrics
    exposure.
  - Implement deterministic change categorization for merged pull requests
    into application, documentation, tests, and supporting code (for example,
    CI workflows, Make, and Helm), and expose aggregate source-line-of-code
    metrics.
  - Requires 2.6.1.
  - See ghillie-design.md §6.2.
  - Success: Source lines of code for merged pull requests are queryable per
    repository and category through API and CLI.

______________________________________________________________________

## 3. Add project and estate-level views

Idea: if the same evidence-and-summarization loop extends from repositories to
projects and the estate without new ingestion paths, Ghillie scales by scope
rather than by bespoke aggregation code.

Phase 3 builds on repository-level reporting to provide narrative and metric
views for projects and the entire estate, using the catalogue's component graph.

### 3.1. Implement project-level aggregation

This step answers whether repository summaries, component definitions, and
cross-component dependencies can be combined into a trustworthy project
narrative. Its outcome determines how project reports are stored and exposed.
See ghillie-design.md §9.8.

- [x] 3.1.1. Define the project evidence structure.
  - Create an evidence representation that includes:
    - project metadata and objectives from the catalogue,
    - component list with lifecycle stages,
    - latest repository machine summaries for components with repositories,
    - component dependencies and any known blocking relationships,
    - any manually specified status for components without repositories.
  - Requires 1.1.2 and 2.1.1.
  - See ghillie-design.md §9.8.
  - Success: At least one multi-repository project can produce a complete
    project evidence bundle from catalogue and repository data.
  - Implemented: `ghillie.evidence.models` module with five frozen msgspec
    structures (`ProjectMetadata`, `ComponentEvidence`,
    `ComponentRepositorySummary`, `ComponentDependencyEvidence`, and
    `ProjectEvidenceBundle`). `ProjectEvidenceBundleService` in
    `ghillie/evidence/project_service.py` queries catalogue storage and
    Silver and Gold storage to build complete project evidence bundles. Unit
    tests (31 model tests, 14 service tests) and `pytest-bdd` scenarios (4)
    validate construction, lifecycle filtering, repository summary
    aggregation, dependency edge capture, and previous report context.
- [ ] 3.1.2. Extend the status model for project summarization.
  - Add a project-level summarization method to the status model interface,
    prompting the model to produce project-level status, achievements, risks,
    and cross-repository dependencies.
  - Requires 3.1.1 and 2.2.1.
  - See ghillie-design.md §9.8.
  - Success: The model generates project summaries that correctly reference
    underlying repository statuses and note cross-component dependencies
    without fabricating new components.
- [ ] 3.1.3. Store and expose project-level reports.
  - Persist project reports in the Gold layer and expose them through the
    same storage and access path conventions as repository reports.
  - Requires 3.1.2 and 2.3.2.
  - See ghillie-design.md §9.8.
  - Success: Project reports appear alongside repository reports, and
    consumers can navigate from a project report to its underlying repository
    reports.

### 3.2. Represent components without repositories

This step answers whether planned and non-code components remain visible in
project status even when no GitHub repository exists. Its outcome prevents
project reports from overstating implementation progress. See ghillie-design.md
§3.4.

- [ ] 3.2.1. Support manual status for non-code components.
  - Extend the catalogue or a dedicated metadata store to hold short status
    fields and external links for components without repositories (for
    example, design documents or tickets).
  - Requires 3.1.1 and 1.1.1.
  - See ghillie-design.md §3.4.
  - Success: At least one project has a planned component with no repository,
    and its status appears in the project report.
- [ ] 3.2.2. Integrate non-code components into summarization.
  - Ensure project evidence bundles include non-code components and their
    statuses, and prompt the model to incorporate these into the narrative
    without overstating progress.
  - Requires 3.2.1 and 3.1.2.
  - Success: Project summaries explicitly mention planned components where
    relevant, distinguishing them from implemented services.

### 3.3. Provide estate-level overview reports

This step answers whether project summaries, metrics, and estate objectives can
be combined into an estate overview. Its outcome determines how cross-project
risks and themes reach operators. See ghillie-design.md §4.1.

- [ ] 3.3.1. Define the estate evidence structure.
  - Combine project-level machine summaries, high-level metrics, and any
    known estate-wide objectives into an evidence bundle suitable for estate
    summarization.
  - Requires 3.1.3.
  - See ghillie-design.md §4.1.
  - Success: An estate-level evidence bundle can be built from existing
    project reports without querying raw events.
- [ ] 3.3.2. Implement estate-level summarization.
  - Extend the status model interface to produce an estate-level report that
    identifies top risks, top achievements, and notable themes across
    projects.
  - Requires 3.3.1 and 3.1.2.
  - Success: Estate-level reports correctly reflect project statuses and do
    not contradict project narratives.

______________________________________________________________________

## 4. Integrate governance information from Concordat

Idea: if Concordat CloudEvents enter the existing Medallion pipeline as
first-class governance evidence, Ghillie can report compliance alongside
delivery without maintaining a parallel integration stack.

Phase 4 brings governance data from Concordat into Ghillie, making compliance
violations first-class inputs to status reports and allowing Concordat
enrolment to drive estate membership.

### 4.1. Ingest Concordat CloudEvents

This step answers whether Concordat events can be captured and mapped into the
same Bronze and Silver layers as GitHub events. Its outcome determines whether
governance state is queryable without reading raw payloads. See
ghillie-design.md §§3.3, 5.3, and 8.4.

- [ ] 4.1.1. Refactor the API layer for domain endpoints.
  - Evolve the runtime module from a monolithic `ghillie/runtime.py` to a
    modular `ghillie/api/` structure with:
    - an application factory in `app.py`,
    - SQLAlchemy session middleware per
      `async-sqlalchemy-with-pg-and-falcon.md`,
    - domain exception handlers for HTTP error mapping,
    - health resources separated from domain resources.
  - See ghillie-design.md §8.4 and async-sqlalchemy-with-pg-and-falcon.md.
  - Success: Health endpoints continue to work unchanged.
    `ghillie/api/app.py` provides `create_app()` with session middleware
    configured. Tests verify request-scoped session lifecycle.
- [ ] 4.1.2. Implement a CloudEvents-compatible ingestion endpoint.
  - Add an ingestion gateway that accepts CloudEvents-formatted events from
    Concordat, verifies their authenticity, and writes them into the Bronze
    `raw_events` store.
  - Requires 4.1.1.
  - See ghillie-design.md §3.3.
  - Success: Sample enrolment and violation events from Concordat appear in
    `raw_events` with preserved metadata, including source, subject, and
    event time.
- [ ] 4.1.3. Map CloudEvents to Silver-layer governance entities.
  - Transform Concordat events into structured Silver-layer records for
    enrolments and compliance violations, using JSON-capable columns for
    flexible rule payloads.
  - Requires 4.1.2 and 1.2.2.
  - See ghillie-design.md §5.3.
  - Success: Active violations and enrolment state can be queried per
    repository or project without examining raw events.

### 4.2. Drive estate membership from Concordat enrolment

This step answers whether Concordat enrolment can define the managed estate
implicitly and keep repository lifecycle state current. Its outcome reduces
duplicate configuration between Concordat and Ghillie. See ghillie-design.md
§5.1.

- [ ] 4.2.1. Treat enrolment events as repository lifecycle signals.
  - On receipt of an enrolment event, create or update the corresponding
    repository record and schedule a historical backfill of recent GitHub
    activity. On unenrolment, mark the repository as inactive for new
    reports.
  - Requires 4.1.3.
  - See ghillie-design.md §5.1.
  - Success: Adding a repository to Concordat automatically causes Ghillie to
    start ingesting events and generating reports. The inverse holds for
    unenrolment.

### 4.3. Surface compliance state in reports

This step answers whether governance posture can be embedded into repository,
project, and estate-level reports. Its outcome makes compliance visible
alongside delivery progress. See ghillie-design.md §5.2.

- [ ] 4.3.1. Compute per-repository compliance scorecards.
  - Derive a simple compliance score or grade per repository from active
    violations, emphasizing severity and recency, and store it alongside
    repository metadata.
  - Requires 4.1.3.
  - See ghillie-design.md §5.2.
  - Success: Each managed repository has a computed compliance score, and the
    underlying violations are queryable for drill-down.
- [ ] 4.3.2. Include governance context in summarization prompts.
  - Extend evidence bundles and prompts so that models take compliance scores
    and active violations into account, calling out critical governance
    issues alongside feature delivery.
  - Requires 4.3.1 and 3.1.2.
  - See ghillie-design.md §5.2.
  - Success: Repository and project reports routinely juxtapose delivery
    progress with outstanding critical or high-severity violations.

______________________________________________________________________

## 5. Developer experience and Backstage integration

Idea: if the report read model is stable and mappable to Backstage entities,
developer portals and notification channels can consume Ghillie status without
coupling to its internals.

Phase 5 focuses on making Ghillie's outputs easy to consume through APIs and
developer portals, with an emphasis on Backstage integration.

### 5.1. Expose a read API for reports

This step answers whether reports and related metadata can be retrieved through
a stable, authenticated API. Its outcome determines how external clients and
portal plugins access Ghillie data. See ghillie-design.md §7 and §8.1.

- [ ] 5.1.1. Design report retrieval endpoints.
  - Define REST or GraphQL endpoints to retrieve latest and historical
    reports for repositories, projects, and the estate, as well as associated
    machine summaries.
  - Requires 2.3.2.
  - See ghillie-design.md §7.
  - Success: A client can fetch a repository's latest report and a list of
    previous reports using stable, documented endpoints.
- [ ] 5.1.2. Enforce authorization and tenancy boundaries.
  - Implement authentication and authorization suitable for the deployment
    context, including any row-level security policies needed for
    multi-tenant use.
  - Requires 5.1.1 and 4.1.1.
  - See ghillie-design.md §8.1.
  - Success: Attempts to access reports for unauthorized estates or projects
    are denied and logged.

### 5.2. Implement the Backstage plugin

This step answers whether Backstage catalogue metadata can map services and
systems to Ghillie scopes and present status in the portal. Its outcome
determines whether developers see Ghillie status where they already work. See
ghillie-design.md §§7.1-7.2.

- [ ] 5.2.1. Map Backstage entities to Ghillie scopes.
  - Use Backstage catalogue metadata to map services and systems to
    repositories and projects in Ghillie.
  - Requires 5.1.1.
  - See ghillie-design.md §7.2.
  - Success: Navigating to a service in Backstage allows the plugin to
    identify the corresponding repository or project in Ghillie without
    manual configuration.
- [ ] 5.2.2. Build the Backstage frontend components.
  - Implement a Backstage plugin that renders a status card with the latest
    summary, compliance indicator, and key metrics on the entity page, and
    links through to full reports.
  - Requires 5.2.1.
  - See ghillie-design.md §7.1.
  - Success: The plugin displays the latest repository or project status for
    at least one pilot service, and updates as new reports are generated.

### 5.3. Add optional push channels

This step answers whether teams can receive status summaries through channels
such as chat or email. Its outcome extends report consumption beyond pull
requests and portals.

- [ ] 5.3.1. Implement the notification configuration model.
  - Define configuration for linking projects or repositories to notification
    targets, such as Slack channels or email lists.
  - Requires 5.1.1.
  - Success: At least one project can be configured to receive notifications
    on report generation.
- [ ] 5.3.2. Send notifications on report creation.
  - Implement a worker that sends concise, linked summaries to configured
    targets when new reports are created.
  - Requires 5.3.1 and 2.3.1.
  - Success: For pilot projects, status summaries appear in the chosen
    channel whenever new reports are generated.

______________________________________________________________________

## 6. Advanced analysis and automation

Idea: if roadmap intent and historical metrics can be extracted from the same
evidence store, Ghillie can move from describing current status to explaining
trends and preparing bounded remediation without destabilizing the MVP.

This is the deferred-extensions phase. Phase 6 introduces capabilities that
build on earlier phases without being required for an initial launch. They
become worthwhile only once the core v1 promise is trustworthy and boring to
operate.

### 6.1. Roadmap intent extraction and adherence metrics

This step answers whether stated intent can be extracted from roadmap documents
and compared with delivery activity. Its outcome determines whether reports can
distinguish on-track, drifting, and stalled initiatives. See ghillie-design.md
§4.2.

- [ ] 6.1.1. Extract structured initiatives from roadmap documents.
  - Use LLM-based extraction to convert roadmap documents into structured
    initiatives with status fields and related repositories or components.
  - Requires 1.3.2.
  - See ghillie-design.md §4.2.
  - Success: Roadmap entries for pilot projects appear as structured records
    and can be linked to events or reports.
- [ ] 6.1.2. Derive roadmap adherence indicators.
  - Compare roadmap initiatives to recent repository and project activity to
    derive high-level adherence signals (for example, initiatives that have
    seen no related activity within a defined period).
  - Requires 6.1.1.
  - Success: Project reports can include an explicit statement about roadmap
    alignment, distinguishing between on-track, drifting, and stalled
    initiatives.

### 6.2. Extended metrics and trend analysis

This step answers whether delivery and governance metrics can be stored as time
series and interpreted as trends. Its outcome lets reports explain movement
rather than only current state. See ghillie-design.md §6.2.

- [ ] 6.2.1. Compute and store key engineering and compliance metrics.
  - Compute metrics such as deployment frequency, lead time for changes, and
    compliance score distributions per project and estate, and store them in
    a queryable form.
  - Requires 2.6.2 and 4.3.1.
  - See ghillie-design.md §6.2.
  - Success: Metric time series exist for pilot repositories and projects and
    can be visualized alongside narrative reports.
- [ ] 6.2.2. Incorporate trends into summaries.
  - Extend evidence bundles so that models can comment on improving or
    degrading trends in delivery and compliance.
  - Requires 6.2.1 and 3.3.2.
  - Success: Estate and project reports occasionally refer to trends, such as
    sustained improvement in lead time or persistent compliance issues.

### 6.3. Prepare for agentic remediation

This step answers what a safe automated action surface could be and which
metadata it would require. Its outcome constrains future agents without
granting write access.

- [ ] 6.3.1. Define the safe action surface.
  - Document a constrained set of actions that an automated agent might be
    allowed to propose or perform (for example, opening a pull request to add
    missing documentation or configuration files), including approval points.
  - See ghillie-design.md §8.3.
  - Success: The action surface and safety constraints are agreed and
    documented, without granting actual write access.
- [ ] 6.3.2. Capture additional context required for safe remediation.
  - Identify and, where appropriate, ingest any additional metadata needed
    for safe remediation (for example, code ownership information or
    escalation contacts) without changing the core Medallion pipeline.
  - Requires 6.3.1.
  - Success: The data model supports, but does not yet require, the context
    needed for agentic remediation scenarios.
