# Ghillie roadmap

## Overview

Ghillie provides automated, estate-level status reporting for GitHub
repositories, working alongside Concordat as the governance control plane. It
ingests events from GitHub and Concordat, models repositories and projects as
part of an estate, and produces narrative and metric-based status reports at
repository, project, and estate level.

This roadmap concentrates on early, high-leverage capabilities that deliver
useful reports quickly, while leaving room for later expansion into richer
governance integration and developer experience features. Work is structured
into phases, steps, and tasks. Phases describe broad capability shifts, steps
group related workstreams, and tasks describe concrete, measurable outcomes.

______________________________________________________________________

## Phase 1: Establish core estate model and ingestion pipeline

Phase 1 creates the foundation on which all later reporting and governance
features depend. The outcome is a reliable model of the engineering estate,
backed by a durable ingestion and storage pipeline for GitHub events.

### Step 1.1: Define estate catalogue and configuration

**Goal:** Provide a single, version-controlled source of truth for projects,
components, repositories, and their relationships.

- [x] **Task 1.1.a – Define catalogue schema**  
  Define a YAML-based configuration schema for:
  - projects and programmes (for example, Wildside, Limela, mxd,
    Episodic),
  - components within each project, including components that do not yet
    have repositories,
  - repository mappings and default branches,
  - component-to-component relationships (depends on, blocked by,
    emits events to),
  - noise filters and status configuration per project.

  *Completion criteria:* At least one multi-repository project is fully
  represented in the catalogue, including planned components without
  repositories, and the schema is validated by a documented linter or JSON
  Schema.

- [x] **Task 1.1.b – Implement catalogue importer and reconciler**  
  Implement a background service that watches the catalogue repository, parses
  project definitions, and reconciles them into the database tables for
  estates, projects, components, component edges, and repositories.

  *Completion criteria:* Running the importer on a changed catalogue commit
  updates the database idempotently. Invalid configuration fails fast with a
  clear error and does not partially update state.

- [x] **Task 1.1.c – Support per-project noise control and status settings**  
  Extend the catalogue schema to store:
  - labels, authors, and paths to ignore when creating events,
  - any repository-specific documentation paths (for example,
    roadmap files, ADR directories),
  - project-level knobs that influence status generation
    (for example, whether dependency PRs are summarised or ignored).

  *Completion criteria:* At least one project has custom noise rules and
  documentation locations defined in the catalogue, and these settings are
  visible to downstream services.

### Step 1.2: Implement core data model and Medallion layers

**Goal:** Provide a storage model that separates raw events from refined
entities and reporting outputs, enabling replay and reprocessing.

- [x] **Task 1.2.a – Implement Bronze raw event store**  
  Introduce an append-only `raw_events` store that captures unmodified payloads
  from GitHub (and later Concordat), tagged with event type, repository
  identity, and ingestion timestamp.

  *Completion criteria:* Every ingestion run writes raw GitHub events to the
  Bronze store. Re-running the transformation job on the same events produces
  identical Silver-layer records.

- [x] **Task 1.2.b – Implement Silver entity tables**  
  Define relational tables for repositories, commits, pull requests, issues,
  and documentation changes, alongside JSON-capable columns for flexible
  payloads where necessary. Implement transformation jobs that hydrate these
  tables from `raw_events`.

  *Completion criteria:* For a pilot set of repositories, commits, pull
  requests, issues, and documentation changes appear in Silver tables with
  correct foreign keys to repositories and stable identifiers for later
  reporting.

- [x] **Task 1.2.c – Implement Gold report metadata schema**  
  Define tables for reports and report coverage, including fields for scope
  (repository, project, estate), reporting window, and machine summaries.

  *Completion criteria:* Repository and project records can be linked to zero
  or more report records, and the schema supports storing the IDs of events
  consumed by each report.

### Step 1.3: Build GitHub ingestion service

**Goal:** Ingest GitHub activity for the managed estate into the Bronze and
Silver layers with controlled noise and back-pressure.

- [x] **Task 1.3.a – Implement repository discovery and registration**
  Derive the managed repository set from the estate catalogue and any allowlist
  labels or naming conventions. Store GitHub owner, name, and default branch,
  along with any metadata required by later stages.

  *Completion criteria:* The system maintains an accurate list of active
  repositories for at least one organisation and can enable or disable
  ingestion per repository.

- [x] **Task 1.3.b – Implement incremental GitHub ingestion**  
  Implement a worker that, per repository, fetches new commits to the default
  branch, pull requests, issues, and selected documentation changes since the
  last ingestion time, using the GitHub GraphQL API where practical.

  *Completion criteria:* For pilot repositories, commits, pull requests,
  issues, and documentation changes are captured into `raw_events` within a
  bounded delay after they occur.

- [x] **Task 1.3.c – Apply noise filters from configuration**  
  Apply project-specific filters to ignore events from known bots, dependency
  update tools, or paths deemed irrelevant, as defined in the catalogue.

  *Completion criteria:* Noise filters can be enabled or disabled per project.
  Toggling a filter changes the set of events ingested for the next run without
  code changes.

- [ ] **Task 1.3.d – Add observability for ingestion health**
  Emit metrics and logs for ingestion throughput, failures, and backlog, and
  define basic alerts for stalled ingestion.

  *Completion criteria:* Operators can see ingestion lag per repository and can
  identify failing ingestion runs through the metrics and logs alone.

- [ ] **Task 1.3.e – Migrate to femtologging library**
  Replace Python stdlib logging with femtologging across the codebase.
  Femtologging provides async-friendly logging with bounded queues, aligning
  with Ghillie's async architecture and supporting the structured logging
  patterns required for observability.

  *Prerequisites:* Femtologging must implement `exc_info` and
  `logger.exception()` support before migration can proceed. See ADR-001 for
  details.

  *Completion criteria:* All logging calls use femtologging. Logging
  configuration is centralised at application entry points. The exception and
  logging guidelines in
  `.rules/python-exception-design-raising-handling-and-logging.md` are updated
  to reflect femtologging patterns.

### Step 1.4: Secure integration with GitHub

**Goal:** Ensure Ghillie’s access to GitHub is secure, minimal, and
operationally manageable.

- [ ] **Task 1.4.a – Configure a GitHub App with least privilege scopes**  
  Create and configure a GitHub App with read-only access to metadata and
  documentation paths required for Ghillie. Avoid direct source code blob
  access where possible.

  *Completion criteria:* All GitHub traffic for Ghillie uses the configured
  App. The system operates correctly when the App’s permissions are audited or
  rotated.

- [ ] **Task 1.4.b – Implement secure credential storage and rotation**  
  Store GitHub App secrets in an approved secrets manager and define a
  documented process for rotating keys, including any required restarts or
  reloads.

  *Completion criteria:* GitHub credentials can be rotated without redeploying
  ingestion services, and failed authentication is surfaced as a clear
  operational alert.

______________________________________________________________________

## Phase 2: Deliver repository-level status reporting (MVP)

Phase 2 delivers a minimum viable product: regular, repository-level status
reports generated from ingested events and stored in the Gold layer. These
reports represent the first directly consumable output of Ghillie.

### Step 2.1: Implement evidence bundle generation

**Goal:** Provide structured, per-repository evidence bundles from Silver-layer
data, ready for summarisation.

- [ ] **Task 2.1.a – Define repository evidence structure**  
  Design an in-memory representation for a repository reporting window that
  includes:
  - basic repository metadata,
  - previous one or two repository reports (where available),
  - new commits, pull requests, issues, and documentation changes within
    the reporting window,
  - groupings by work type (for example, feature, bug, refactor,
    chore) based on labels and heuristics.

  *Completion criteria:* The evidence structure is fully populated for the
  pilot repositories, and unit tests confirm correct grouping of events.

- [ ] **Task 2.1.b – Implement event selection and grouping per window**  
  Add logic to select events between `window_start` and `window_end`, excluding
  any events already covered by previous reports via the report coverage table.

  *Completion criteria:* For a given repository and reporting window, evidence
  bundles include only new events. Re-running the reporting job does not change
  the bundle unless new events have arrived.

### Step 2.2: Integrate large language models behind an abstraction

**Goal:** Introduce LLM-backed summarisation while keeping vendor choices and
context window sizes abstracted.

- [ ] **Task 2.2.a – Define status model interface**  
  Define an interface for a status model with operations to summarise a
  repository evidence bundle and return structured output, including summary
  text, status code (for example, on track, at risk, blocked, unknown),
  highlights, risks, and suggested next steps.

  *Completion criteria:* At least one implementation of the interface is
  available in code, with tests that mock model responses.

- [ ] **Task 2.2.b – Implement initial LLM integration**  
  Implement an integration with a chosen model (for example, GPT-5.1-thinking)
  using the status model interface. Include prompt templates that:
  - provide previous reports and new events,
  - instruct the model not to repeat unchanged information,
  - request both narrative and structured JSON output.

  *Completion criteria:* For test evidence bundles, the model returns parseable
  JSON and narrative text that passes basic quality checks (no hallucinated
  repositories, correct reflection of event counts).

- [ ] **Task 2.2.c – Provide configuration for model selection**  
  Allow operators to select the model backend and key configuration
  (temperature, maximum tokens) per environment.

  *Completion criteria:* The same reporting job can be run against two
  different model backends without code changes, by configuration alone.

### Step 2.3: Generate and store repository reports

**Goal:** Produce and persist repository-level reports on a regular schedule,
using the evidence and model integrations.

- [ ] **Task 2.3.a – Implement reporting scheduler and workflow**  
  Add a scheduled job that, for each managed repository, determines the next
  reporting window, constructs an evidence bundle, invokes the status model,
  and writes a report record and associated report coverage records.

  *Completion criteria:* For pilot repositories, a full reporting run creates
  one report per repository within the configured window and marks all events
  in that window as covered.

- [ ] **Task 2.3.b – Define report Markdown and storage**  
  Define a Markdown format for repository reports, including status summary,
  highlights, risks, and next steps. Store the rendered Markdown either in a
  dedicated status repository or object storage bucket.

  *Completion criteria:* Operators can navigate to a repository’s latest report
  via a predictable path or URL, and the report content matches the data stored
  in the database.

- [ ] **Task 2.3.c – Provide an on-demand reporting entry-point**  
  Implement a CLI command or API endpoint that regenerates a repository’s
  current report window on demand (for example, to respond to a review
  request), while still respecting report coverage semantics for published
  reports.

  *Completion criteria:* An operator can trigger a fresh report for a
  repository and see the updated Markdown rendered through the same path as
  scheduled reports.

### Step 2.4: Instrument quality and operational feedback

**Goal:** Ensure repository reports are accurate enough to trust and
operationally safe to run.

- [ ] **Task 2.4.a – Add basic correctness checks for generated reports**  
  Implement post-generation validation that ensures the number of highlighted
  changes is plausible relative to the number of events in the evidence bundle
  and that the model has not produced empty or truncated output.

  *Completion criteria:* Invalid or clearly broken reports are rejected and
  retried or marked for human review, rather than silently stored.

- [ ] **Task 2.4.b – Capture reporting metrics and costs**  
  Emit metrics for the number of reports generated, average model latency, and
  approximate token usage per run.

  *Completion criteria:* Operators can see the total reporting cost and latency
  profile for the pilot estate over a given period.

______________________________________________________________________

## Phase 3: Add project and estate-level views

Phase 3 builds on repository-level reporting to provide narrative and metric
views for projects and the entire estate, using the catalogue’s component graph.

### Step 3.1: Implement project-level aggregation

**Goal:** Generate project-level reports that combine repository summaries,
component definitions, and cross-component dependencies.

- [ ] **Task 3.1.a – Define project evidence structure**  
  Create an evidence representation that includes:
  - project metadata and objectives from the catalogue,
  - component list with lifecycle stages,
  - latest repository machine summaries for components with repositories,
  - component dependencies and any known blocking relationships,
  - any manually specified status for components without repositories.

  *Completion criteria:* At least one multi-repository project can produce a
  complete project evidence bundle from catalogue and repository data.

- [ ] **Task 3.1.b – Extend status model for project summarisation**  
  Add a project-level summarisation method to the status model interface,
  prompting the model to produce project-level status, achievements, risks, and
  cross-repository dependencies.

  *Completion criteria:* The model generates project summaries that correctly
  reference underlying repository statuses and note cross-component
  dependencies without fabricating new components.

- [ ] **Task 3.1.c – Store and expose project-level reports**  
  Persist project reports in the Gold layer and expose them through the same
  storage and access path conventions as repository reports.

  *Completion criteria:* Project reports appear alongside repository reports,
  and consumers can navigate from a project report to its underlying repository
  reports.

### Step 3.2: Represent components without repositories

**Goal:** Ensure planned and non-code components are visible in project status,
even when no GitHub repository exists yet.

- [ ] **Task 3.2.a – Support manual status for non-code components**  
  Extend the catalogue or a dedicated metadata store to hold short status
  fields and external links for components without repositories (for example,
  design documents or tickets).

  *Completion criteria:* At least one project has a planned component with no
  repository, and its status appears in the project report.

- [ ] **Task 3.2.b – Integrate non-code components into summarisation**  
  Ensure project evidence bundles include non-code components and their
  statuses, and prompt the model to incorporate these into the narrative
  without overstating progress.

  *Completion criteria:* Project summaries explicitly mention planned
  components where relevant, distinguishing them from implemented services.

### Step 3.3: Provide estate-level overview reports

**Goal:** Introduce estate-level reports that highlight cross-project risks,
themes, and achievements.

- [ ] **Task 3.3.a – Define estate evidence structure**  
  Combine project-level machine summaries, high-level metrics, and any known
  estate-wide objectives into an evidence bundle suitable for estate
  summarisation.

  *Completion criteria:* An estate-level evidence bundle can be built from
  existing project reports without querying raw events.

- [ ] **Task 3.3.b – Implement estate-level summarisation**  
  Extend the status model interface to produce an estate-level report that
  identifies top risks, top achievements, and notable themes across projects.

  *Completion criteria:* Estate-level reports correctly reflect project
  statuses and do not contradict project narratives.

______________________________________________________________________

## Phase 4: Integrate governance information from Concordat

Phase 4 brings governance data from Concordat into Ghillie, making compliance
violations first-class inputs to status reports and allowing Concordat
enrolment to drive estate membership.

### Step 4.1: Ingest Concordat CloudEvents

**Goal:** Capture Concordat events in the Medallion pipeline, alongside GitHub
events.

- [ ] **Task 4.1.a – Implement CloudEvents-compatible ingestion endpoint**  
  Add an ingestion gateway that accepts CloudEvents-formatted events from
  Concordat, verifies their authenticity, and writes them into the Bronze
  `raw_events` store.

  *Completion criteria:* Sample enrolment and violation events from Concordat
  appear in `raw_events` with preserved metadata, including source, subject,
  and event time.

- [ ] **Task 4.1.b – Map CloudEvents to Silver-layer governance entities**  
  Transform Concordat events into structured Silver-layer records for
  enrolments and compliance violations, using JSON-capable columns for flexible
  rule payloads.

  *Completion criteria:* Active violations and enrolment state can be queried
  per repository or project without examining raw events.

### Step 4.2: Drive estate membership from Concordat enrolment

**Goal:** Use Concordat to define the managed estate implicitly through
enrolment.

- [ ] **Task 4.2.a – Treat enrolment events as repository lifecycle signals**  
  On receipt of an enrolment event, create or update the corresponding
  repository record and schedule a historical backfill of recent GitHub
  activity. On unenrolment, mark the repository as inactive for new reports.

  *Completion criteria:* Adding a repository to Concordat automatically causes
  Ghillie to start ingesting events and generating reports. The inverse holds
  for unenrolment.

### Step 4.3: Surface compliance state in reports

**Goal:** Embed governance posture into repository, project, and estate-level
reports.

- [ ] **Task 4.3.a – Compute per-repository compliance scorecards**  
  Derive a simple compliance score or grade per repository from active
  violations, emphasising severity and recency, and store it alongside
  repository metadata.

  *Completion criteria:* Each managed repository has a computed compliance
  score, and the underlying violations are queryable for drill-down.

- [ ] **Task 4.3.b – Include governance context in summarisation prompts**  
  Extend evidence bundles and prompts so that models take compliance scores and
  active violations into account, calling out critical governance issues
  alongside feature delivery.

  *Completion criteria:* Repository and project reports routinely juxtapose
  delivery progress with outstanding critical or high-severity violations.

______________________________________________________________________

## Phase 5: Developer experience and Backstage integration

Phase 5 focuses on making Ghillie’s outputs easy to consume through APIs and
developer portals, with an emphasis on Backstage integration.

### Step 5.1: Expose a read API for reports

**Goal:** Provide a stable, authenticated API for retrieving reports and
related metadata.

- [ ] **Task 5.1.a – Design report retrieval endpoints**  
  Define REST or GraphQL endpoints to retrieve latest and historical reports
  for repositories, projects, and the estate, as well as associated machine
  summaries.

  *Completion criteria:* A client can fetch a repository’s latest report and a
  list of previous reports using stable, documented endpoints.

- [ ] **Task 5.1.b – Enforce authorisation and tenancy boundaries**  
  Implement authentication and authorisation suitable for the deployment
  context, including any row-level security policies needed for multi-tenant
  use.

  *Completion criteria:* Attempts to access reports for unauthorised estates or
  projects are denied and logged.

### Step 5.2: Implement Backstage plugin

**Goal:** Present Ghillie status information within Backstage’s component and
system pages.

- [ ] **Task 5.2.a – Map Backstage entities to Ghillie scopes**  
  Use Backstage catalogue metadata to map services and systems to repositories
  and projects in Ghillie.

  *Completion criteria:* Navigating to a service in Backstage allows the plugin
  to identify the corresponding repository or project in Ghillie without manual
  configuration.

- [ ] **Task 5.2.b – Build Backstage frontend components**  
  Implement a Backstage plugin that renders a status card with the latest
  summary, compliance indicator, and key metrics on the entity page, and links
  through to full reports.

  *Completion criteria:* The plugin displays the latest repository or project
  status for at least one pilot service, and updates as new reports are
  generated.

### Step 5.3: Add optional push channels

**Goal:** Allow teams to receive status summaries through channels such as chat
or email.

- [ ] **Task 5.3.a – Implement notification configuration model**  
  Define configuration for linking projects or repositories to notification
  targets, such as Slack channels or email lists.

  *Completion criteria:* At least one project can be configured to receive
  notifications on report generation.

- [ ] **Task 5.3.b – Send notifications on report creation**  
  Implement a worker that sends concise, linked summaries to configured targets
  when new reports are created.

  *Completion criteria:* For pilot projects, status summaries appear in the
  chosen channel whenever new reports are generated.

______________________________________________________________________

## Phase 6: Advanced analysis and automation

Phase 6 introduces more advanced capabilities that build on earlier phases
without being required for an initial launch.

### Step 6.1: Roadmap intent extraction and adherence metrics

**Goal:** Understand stated intent from roadmap documents and measure progress
against it.

- [ ] **Task 6.1.a – Extract structured initiatives from roadmap documents**  
  Use LLM-based extraction to convert roadmap documents into structured
  initiatives with status fields and related repositories or components.

  *Completion criteria:* Roadmap entries for pilot projects appear as
  structured records and can be linked to events or reports.

- [ ] **Task 6.1.b – Derive roadmap adherence indicators**  
  Compare roadmap initiatives to recent repository and project activity to
  derive high-level adherence signals (for example, initiatives that have seen
  no related activity within a defined period).

  *Completion criteria:* Project reports can include an explicit statement
  about roadmap alignment, distinguishing between on-track, drifting, and
  stalled initiatives.

### Step 6.2: Extended metrics and trend analysis

**Goal:** Surface trends in delivery and governance metrics over time.

- [ ] **Task 6.2.a – Compute and store key engineering and compliance
  metrics** Compute metrics such as deployment frequency, lead time for
  changes, and compliance score distributions per project and estate, and store
  them in a queryable form.

  *Completion criteria:* Metric time series exist for pilot repositories and
  projects and can be visualised alongside narrative reports.

- [ ] **Task 6.2.b – Incorporate trends into summaries**  
  Extend evidence bundles so that models can comment on improving or degrading
  trends in delivery and compliance.

  *Completion criteria:* Estate and project reports occasionally refer to
  trends, such as sustained improvement in lead time or persistent compliance
  issues.

### Step 6.3: Prepare for agentic remediation (future-facing)

**Goal:** Make Ghillie’s architecture ready for a future where models can
safely propose or initiate remediation actions.

- [ ] **Task 6.3.a – Define safe action surface**  
  Document a constrained set of actions that an automated agent might be
  allowed to propose or perform (for example, opening a pull request to add
  missing documentation or configuration files), including approval points.

  *Completion criteria:* The action surface and safety constraints are agreed
  and documented, without granting actual write access.

- [ ] **Task 6.3.b – Capture additional context required for safe
  remediation** Identify and, where appropriate, ingest any additional metadata
  needed for safe remediation (for example, code ownership information or
  escalation contacts) without changing the core Medallion pipeline.

  *Completion criteria:* The data model supports, but does not yet require, the
  context needed for agentic remediation scenarios.

______________________________________________________________________

## Early value and implementation guidance

Phases 1 and 2 together constitute the initial Ghillie MVP: a system that
reliably ingests GitHub activity for a managed set of repositories, constructs
evidence bundles, and produces repository-level status reports on a regular
cadence. Later phases build on this foundation to add project and estate views,
governance integration, and richer developer experience support.

The roadmap deliberately avoids calendar commitments. Each task is scoped to be
achievable, measurable, and incrementally valuable, so that Ghillie can start
delivering meaningful status reports early and evolve safely towards deeper
integration with Concordat and wider organisational tooling.
