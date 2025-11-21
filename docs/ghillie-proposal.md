# Ghillie proposal

This proposal outlines an “estate-level” status system that actually
understands what’s going on, not just counts commits.

The narrative works top‑down, then zooms into the bits that matter: repo
relationships, multi-repo projects, previous status awareness, and where the
giant context windows actually help.

______________________________________________________________________

## 1. High‑level picture

Conceptually, the system uses three layers:

1. **Ingest & normalise**
Pull structured “events” from GitHub for each repo:

- roadmap docs
- design docs / ADRs
- recent commits to default branch
- open PRs with recent activity
- new / updated issues
- previous status reports

1. **Model the estate**

- Repositories
- Logical projects / programmes (Wildside, Limela, mxd, Episodic, etc.)
- Components (including those that doesn’t yet have repos)
- Explicit relationships: “this repo belongs to Wildside”, “this component
  depends on that repo”, etc.

1. **Generate statuses**

- Per‑repo status updates, only about _new_ developments since the last report,
  but with directional context.
- Per‑project summary across multiple repos + planned components.
- Optional “estate overview” (top risks, big movements).

LLMs sit in layer 3, but the system derives most of the value from getting
layers 1 and 2 right.

______________________________________________________________________

## 2. Data model

Think database, not just prompts. Something like Postgres with these core
tables:

### 2.1 Repositories and projects

```text
repositories
- id
- github_owner
- github_name
- default_branch
- active (bool)
- metadata (jsonb)      -- language, service type, etc.

projects
- id
- key                   -- "wildside", "limela", etc.
- name
- description
- status_config (jsonb) -- knobs per project (e.g. ignore labels, doc locations)

project_components
- id
- project_id (fk)
- key                   -- "wildside-gateway", "episodic-scheduler"
- name
- type                  -- "service", "library", "ui", "data-pipeline", "planned"
- has_repo (bool)
- repo_id (fk nullable)
- external_links (jsonb) -- RFCs in another system, tickets, etc.
- lifecycle_stage       -- "planned", "in_discovery", "in_development", "deprecated"

project_component_edges
- id
- from_component_id
- to_component_id
- relationship_type     -- "depends_on", "blocked_by", "uses_api", "emits_events_to"

```

### 2.2 Events and reports

```text
events
- id
- repo_id
- type           -- "commit", "pr", "issue", "doc_change", "adr_change", "roadmap_change"
- source_id      -- commit SHA, PR number, issue number, file path + commit, etc.
- occurred_at
- payload (jsonb) -- title, body, labels, diff summary, links

reports
- id
- scope_type     -- "repo", "project", "estate"
- scope_id       -- repo_id or project_id or NULL for estate
- generated_at
- window_start
- window_end
- model          -- "gpt-5.1-thinking", "gemini-3-pro"
- human_text     -- rendered Markdown / HTML
- machine_summary (jsonb)  -- structured facts for future runs (optional)

```

The system also wants:

```text
report_coverage
- report_id
- event_id

```

So the system can tell which events have already been “consumed” into a report.

______________________________________________________________________

## 3. Configuring relationships between repositories

The system explicitly asked for a mechanism to define relationships where
manifests don’t help. This design would treat this as a separate _catalogue_
config, not an afterthought.

### 3.1 A “catalogue” config repo

Have a dedicated repo, e.g. `engineering-catalogue` or `estate-config`, that
stores YAML describing projects, components, and repo mappings. Something like:

```yaml
# projects/wildside.yaml
project:
  key: wildside
  name: Wildside
  description: >
    Transactional streaming platform for X.

  components:
    - key: wildside-core
      name: Wildside Core Service
      type: service
      repo: wildside/core-service
      lifecycle_stage: in_development
      depends_on:
        - mxd-api
        - episodic-scheduler

    - key: wildside-ui
      name: Wildside Admin UI
      type: ui
      repo: wildside/admin-ui
      lifecycle_stage: planned

    - key: wildside-ingestion
      name: Wildside Ingestion Pipeline
      type: data-pipeline
      has_repo: false
      lifecycle_stage: planned
      external_links:
        - type: "design_doc"
          url: "https://github.com/org/wildside-rfcs/blob/main/ingestion.md"

```

For a multi-repo project like Episodic, the system just lists all
component→repo mappings, plus any planned components with `has_repo: false`.

A small daemon in the system watches this config repo:

- On changes, it re-syncs the DB (`projects`, `project_components`,
  `repositories`).
- It also lets the system define overrides for when manifests lie or are
  incomplete.

### 3.2 Auto‑inference, then override

The system can still infer relations from package manifests:

- `pyproject.toml`, `Cargo.toml`, `package.json`, etc.
- Dependencies that point to other repos in the GitHub org (e.g.
  `git+ssh://git@github.com/org/mxd-api.git`).

Use those to build a _suggested_ dependency graph. Then use the catalogue YAML
to:

- Confirm (“yes, that’s part of Wildside”).
- Override (“this shared library belongs to xyz project”).
- Add non-code components (“episodic-data-contracts”,
  “limela-analytics-dashboard”, etc.).

______________________________________________________________________

## 4. GitHub ingestion pipeline

### 4.1 Discovery

Either:

- Maintain an explicit allowlist of repos in the catalogue; or
- Periodically scan orgs and match against a naming convention / label (e.g.
  repos labelled `estate-managed`).

Store them in `repositories`.

### 4.2 What to ingest

For each repo, since `last_ingested_at`:

- **Commits on default branch**

- SHA, author, date, message
- Files changed (paths, approximate diff summary)
- **Pull requests**

- Open PRs with activity since `last_ingested_at`
- Recently merged PRs
- Fields: title, body, labels, assignees, merge status, list of files
- **Issues**

- Newly opened or updated issues
- Labels, milestone, assignee, current status
- **Docs / design / roadmap / ADRs**

- File patterns configurable per repo/project:

- `docs/**/adr*.md`
- `doc/adr/**`
- `docs/architecture/**`
- `ROADMAP.md`, `docs/roadmap*.md`
- `design/**`, `rfcs/**`
- For each changed file:

- Path, commit, author, date
- Minimal diff summary: e.g. new headings added/removed, changed sections.
- **Previous status reports**

- If the system commit generated reports back into `STATUS.md` or similar, the
  system can ingest them too, but the system need not; the system already has
  them in the DB.

Implementation‑wise, the system would likely use:

- GitHub GraphQL for efficiency (one query to fetch PRs, issues, etc.)
- REST for diff/patch where needed.

Each item becomes an `events` row with a `type` and `payload`.

### 4.3 Noise control

The system _really_ wants this configurable:

- Disregard PRs carrying labels such as `dependencies`, `ci`, or `chore`.
- Skip issues marked `triage` while they remain untriaged.
- Exclude commits from bots (dependabot, renovate, etc.) unless explicitly
  requested.

Store noise filters per repo / per project in the catalogue YAML.

______________________________________________________________________

## 5. Using previous status updates properly

Two complementary mechanisms:

### 5.1 Time windows and coverage

For each report, define `[window_start, window_end]`. For a weekly report:

- `window_start` = last report’s `window_end`
- `window_end` = now (or a scheduled report cut‑off)

When querying `events`, filter by:

- `occurred_at >= window_start`
- `occurred_at < window_end`

Then mark included events as covered in `report_coverage`.

This guarantees the system doesn’t re‑use the same raw events in two reports.
That alone avoids most repetition.

### 5.2 Directional context

To give continuity, the system also includes:

- The **last 1–2 reports** for that repo/project as context for the LLM.

So the prompt gets:

- “Here’s what the design previously said.”
- “Here are the _new_ events.”

Instruction to the model: _describe the new developments relative to the prior
context; do not repeat items that haven’t materially changed, except to note
continued progress or unchanged risks._

The system can also ask the model to emit a structured machine summary
alongside the prose, e.g.:

```json
{
  "status": "on_track",
  "highlights": [
    {"id": "feat-x", "kind": "feature", "summary": "Initial version of X behind feature flag"},
    ...
  ],
  "risks": [
    {"id": "external-dep-y", "summary": "Blocked on API changes in mxd-api"}
  ]
}

```

Those `id`s can be reused across runs to track ongoing work at the “feature” or
“risk” level, not just events.

______________________________________________________________________

## 6. Repo‑level status generation

### 6.1 Evidence bundle

For each repo + time window, build an “evidence bundle”, e.g.:

- Short repo description (from catalogue).
- Last repo report(s) (1–2).
- New events grouped roughly as:

- Feature work (PRs/issues labelled `feature`, `enhancement`).
- Quality work (bugs, refactors, tests).
- Design/roadmap changes (doc/ADR/roadmap).
- Operational changes (CI, infra, SLO/SLA, etc., if visible).

Compress noisy details before hitting the model. For instance:

- Instead of full diffs, give: “Modified files: [list of paths]” and a very
  short summarised description of changes (which the system can get via a first
  small LLM call if the system like).

### 6.2 Prompt shape (conceptual)

In pseudo‑JSON for the responses API:

<!-- markdownlint-disable MD013 -->
```jsonc
{
  "model": "gpt-5.1-thinking",
  "input": [
    {
      "role": "system",
      "content": "The system are generating concise engineering status reports..."
    },
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "Repository: wildside/core-service\n\nPrevious status:\n...\n\nNew events this period:\n- COMMITS: ...\n- PULL REQUESTS: ...\n- ISSUES: ...\n- DOC CHANGES: ..."
        }
      ]
    }
  ],
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "RepoStatus",
      "schema": {
        "type": "object",
        "properties": {
          "summary": { "type": "string" },
          "status":  { "type": "string", "enum": ["on_track", "at_risk", "blocked", "unknown"] },
          "highlights": { "type": "array", "items": { "type": "string" } },
          "risks": { "type": "array", "items": { "type": "string" } },
          "next_steps": { "type": "array", "items": { "type": "string" } }
        },
        "required": ["summary", "status"]
      }
    }
  }
}

```
<!-- markdownlint-enable MD013 -->

The system then renders `summary/highlights/risks` as human Markdown, and store
the full JSON in `machine_summary`.

______________________________________________________________________

## 7. Project‑level (Wildside, Limela, mxd, Episodic, etc.)

For a logical project, the system wants the model to reason over:

- Repo‑level reports for all linked repos.
- Component graph (including planned components).
- Cross‑component dependencies (edges).
- Previous project‑level report(s).

### 7.1 Evidence bundle

For project `wildside`:

- Project metadata (description, owner, target dates, etc. from catalogue
  config).
- Component list with lifecycle stage and repo mapping:

- `wildside-core` → repo `wildside/core-service`, status: on_track
- `wildside-ui` → repo `wildside/admin-ui`, status: at_risk
- `wildside-ingestion` → planned, no repo yet
- Latest repo‑level machine summaries for all components with repos.
- Any component‑level annotations for planned components (which the system might
  maintain manually in the catalogue or in a separate “wildside-meta” repo).

Then ask the model for:

- A project‑level `status` (on_track/at_risk/blocked).
- Summary of overall progress towards key outcomes.
- Cross‑repo dependencies and risks:

- e.g. “Wildside is blocked on changes in mxd-api, which has seen no progress
  this period.”
- Explicit notes on planned/no‑repo components:

- e.g. “Ingestion pipeline remains in planned state; only design doc updated
  this period.”

### 7.2 Handling components without repos

The system model them exactly like real components, just with:

- `has_repo = false`
- `external_links` to whatever artefacts exist: RFCS, initial tickets,
  spreadsheets if the system is unlucky.

For these, events won’t come from GitHub; at first they’ll be static. Two
options:

1. **Manual updates**
For now, the system let humans attach a short free‑text status to such
components in the catalogue. The system ingests that as synthetic “events”.
2. **Later: multi‑source ingestion**
Extend the ingestion to e.g. JIRA/YouTrack/whatever to pull tickets for those
components. The system still treats them as events; they just doesn’t belong to
a repo.

Either way, the project‑level summariser can talk intelligently about
components that doesn’t have code yet.

______________________________________________________________________

## 8. Estate‑level overview

Once the system has repo‑ and project‑level structured summaries, an
estate-level report becomes cheap:

- Gather:

- Project statuses (with `status` and top risks).
- Maybe a small slice of metrics (PR throughput, lead time, incident count per
  project if the system track that elsewhere).

Push everything into the big context model and ask for:

- Top 5 risks across the estate.
- Top 5 achievements.
- Projects drifting vs roadmap.
- Emerging themes (e.g. too many teams blocked on one core library).

Because the system already has structured machine summaries, the estate call
doesn’t need to read raw GitHub data at all.

______________________________________________________________________

## 9. GPT‑5.1 vs Gemini 3 Pro via OpenRouter

The system listed:

- **GPT‑5.1‑thinking (responses API, 400k tokens)**
- **Gemini 3 Pro Preview via OpenRouter (1.05M tokens)**

A few points to keep it honest:

### 9.1 Context window reality

- 400k tokens is already huge. That’s enough for:

- Dozens of repo summaries
- Several prior reports
- A nice chunk of structured event data
- 1.05M is fun for “stuff the universe in and see what happens”, but at that
  scale the system often hits:

- Higher cost
- Higher latency
- More variability in what the model actually pays attention to

Given the system is _already_ building a structured event + summary layer, the
system doesn’t need million‑token contexts. A hierarchical approach scales much
better than “just shove everything in, YOLO”.

### 9.2 Model abstraction

This design would design a simple abstraction:

```python
class StatusModel(Protocol):
    def summarize_repo(self, evidence: RepoEvidence) -> RepoStatus: ...
    def summarize_project(self, evidence: ProjectEvidence) -> ProjectStatus: ...
    def summarize_estate(self, evidence: EstateEvidence) -> EstateStatus: ...

```

With two implementations:

- `OpenAIStatusModel` using GPT‑5.1‑thinking via the responses API.
- `OpenRouterStatusModel` using Gemini 3 Pro.

Both take the same structured `Evidence` objects; they differ only in the
backend call and max context.

That keeps the design from ossifying around one vendor, and it lets the system
benchmark:

- Quality of repo‑level summaries
- Ability to reason about cross‑repo dependencies
- Cost per report

### 9.3 Security/compliance reality check

Given the kind of org the system work for:

Sending the entire internal GitHub estate to _any_ external model needs serious
scrutiny:

- OpenAI direct vs OpenRouter proxy vs in‑house deployment matters for:

- Data residency
- Logging retention
- Regulatory posture (especially in finance)

Architecturally:

- Encapsulate the LLM calls behind a narrow interface (above).
- Make the infra pluggable so the system can swap:

- Cloud LLM → on‑prem / VPC deployment
- One vendor → another
- Keep as much summarisation as possible within the perimeter (e.g. first
  pass: reduce raw events down before calling any external model).

______________________________________________________________________

## 10. Implementation sketch (concrete enough to build)

Very roughly:

- **Service A – Ingestion**

- Written in Python.
- Periodic job (e.g. every hour):

- Reads catalogue config repo.
- Updates DB with projects/components/repos.
- Queries GitHub for events since last ingestion per repo.
- Inserts `events`, applying noise filters.
- Exposes nothing public; just writes to DB.
- **Service B – Reporting**

- Also Python.
- Scheduled weekly / ad‑hoc triggered.
- Steps:

1. For each repo with events in window:

- Build `RepoEvidence`.
- Call `StatusModel.summarize_repo`.
- Store `reports` and `report_coverage`.

1. For each project:

- Gather latest repo reports + component config.
- Build `ProjectEvidence`.
- Call `StatusModel.summarize_project`.
- Store project report.

1. Build estate evidence and call `summarize_estate`.

- Writes Markdown to:

- A “status” repo per estate (e.g. `status/2025-11-20.md`).
- Optionally a `STATUS.md` in each project meta repo.
- Also pushes to Slack / email / Teams if the system fancy.
- **Service C – UI & API (optional)**

- Simple web UI showing:

- Repo list with status.
- Project overviews.
- History of reports per scope.

______________________________________________________________________

## 11. Where the big contexts actually help

- **Repo‑level:** the system doesn’t need huge context here; the system is
  looking at <= 1 week of events.
- **Project‑level:** context window matters if:

- The project spans many repos, _and_
- The system wants the model to consider several weeks of history to detect
  trends.
- **Estate‑level:** big contexts shine for an “annual review”‑style report
  where the system feed in:

- 6–12 months of project summaries
- Organisational / roadmap docs
- And ask for a narrative about trajectory and systemic risks.

But for weekly/monthly operational reporting, a hierarchical design with
GPT‑5.1‑thinking and 400k tokens is already comfortably overpowered.

______________________________________________________________________

Bottom line: treat this as a data+domain modelling problem with an LLM bolted
on the front, not an LLM problem with some GitHub seasoning. Once the system
have clean events and a clear model of Wildside/Limela/mxd/Episodic as
_projects_ with explicit components and dependencies, the choice of GPT‑5.1 vs
Gemini becomes an implementation detail rather than an architectural constraint.
