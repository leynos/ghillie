# Define project evidence structure (Task 3.1.a)

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`, and
`Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: DONE

## Purpose / big picture

Task 3.1.a introduces domain models and a service for project-level evidence
bundles. A project evidence bundle aggregates catalogue metadata (project
description, component list, lifecycle stages, dependency graph) with the
latest repository-level machine summaries from the Gold layer into a single
immutable structure suitable for downstream project-level summarisation (Task
3.1.b) and persistence (Task 3.1.c).

After this change:

1. `ProjectEvidenceBundle` frozen msgspec Struct captures project metadata,
   component evidence (with optional repository summaries), and dependency
   edges.
2. `ProjectEvidenceBundleService` builds a complete bundle by querying
   catalogue storage (projects, components, edges, repositories) and gold
   storage (latest repository reports).
3. At least one multi-repository project (Wildside-like fixture) can produce
   a complete project evidence bundle from catalogue and repository data.
4. Unit and pytest-bdd coverage validates model construction, service logic,
   and end-to-end bundle generation.
5. Docs and roadmap reflect the delivered capability.
6. Quality gates pass: `make check-fmt`, `make typecheck`, `make lint`,
   and `make test`.

## Constraints

- Follow existing hexagonal architecture: domain models are frozen msgspec
  Structs; services use injected session factories.
- Follow test-driven development (TDD) per AGENTS.md: write failing tests
  first, then implement.
- Reuse existing enums (`ReportStatus`) and Gold layer models (`Report`,
  `ReportProject`, `ReportScope`).
- No API endpoint changes (Task 3.1.c scope).
- No status model changes (Task 3.1.b scope).
- Quality gates must pass: `make check-fmt`, `make typecheck`, `make lint`,
  `make test`.
- Markdown must comply with project style (80-col wrap, dash bullets).
- The project evidence bundle is a domain model only -- no new persistence
  tables.

## Tolerances (exception triggers)

- If catalogue and gold/silver storage require different database connections
  in future, the two-session-factory design accommodates this without code
  changes.
- If the number of components per project becomes very large, the service
  may need batching; for now, projects are small enough for single-pass queries.

## Risks

- Risk: Catalogue and silver/gold ORM models use different `Base` classes.
  Mitigation: Service accepts two session factories and joins results in Python
  rather than cross-schema SQL joins.

- Risk: A component's repository may not have a Silver `Repository` record
  (not yet synced). Mitigation: Missing Silver repositories are handled
  gracefully; `ComponentEvidence.repository_summary` remains `None`.

- Risk: A repository may have no Gold reports yet.
  Mitigation: `ComponentRepositorySummary` is optional (`None`) when no report
  exists.

## Progress

- [x] Write ExecPlan (this document).
- [x] Add failing unit tests for domain models (`ProjectMetadata`,
  `ComponentEvidence`, `ComponentRepositorySummary`,
  `ComponentDependencyEvidence`, `ProjectEvidenceBundle`).
- [x] Implement domain models in `ghillie/evidence/models.py`.
- [x] Update `ghillie/evidence/__init__.py` exports.
- [x] Add failing unit tests for `ProjectEvidenceBundleService`.
- [x] Implement `ProjectEvidenceBundleService` in
  `ghillie/evidence/project_service.py`.
- [x] Write BDD feature (`project_evidence_bundle.feature`) and step
  definitions.
- [x] Update `docs/users-guide.md` with project evidence bundle section.
- [x] Update `docs/ghillie-design.md` with project evidence design
  decisions.
- [x] Mark Task 3.1.a as `[x]` in `docs/roadmap.md`.
- [x] Run quality gates and record outcomes.

## Surprises & discoveries

- The Wildside catalogue's `wildside-engine` component has a `blocked_by`
  edge targeting `ortho-config`, which belongs to the `df12-foundations`
  project. This is a cross-project edge. The service correctly filters these
  out by checking whether both endpoints resolve within the project's component
  set. The initial test assumed the edge would be included; the test was
  corrected to assert exclusion instead.

- The `ComponentRecord.repository` relationship points to the catalogue
  `RepositoryRecord`, not directly to a Silver `Repository`. The service must
  first collect `catalogue_repository_id` values from the catalogue, then look
  up Silver `Repository` rows by that ID, then fetch Gold reports by Silver
  repository ID. This three-hop join is done in Python via dictionary lookups.

## Decision log

1. **Domain models in `ghillie/evidence/models.py`.**
   Project evidence structs go alongside existing repository evidence structs.
   This keeps all evidence domain models co-located and avoids a parallel
   module hierarchy for project-level concerns.

2. **Separate `ProjectEvidenceBundleService` class.**
   Created in `ghillie/evidence/project_service.py` rather than extending
   `EvidenceBundleService`. The project service queries different stores
   (catalogue + gold) than the repository service (silver + gold), and its
   construction logic is fundamentally different. Separation follows single
   responsibility.

3. **Two session factories.**
   The service accepts `catalogue_session_factory` and `gold_session_factory`
   to keep the option of separate databases open. In tests both point to the
   same engine via `conftest.py`.

4. **Flat dependency edge representation.**
   Component edges are represented as a flat tuple of
   `ComponentDependencyEvidence` on the bundle, not nested within
   `ComponentEvidence`. This avoids circular references and simplifies
   serialisation.

5. **Repository summary from Gold `Report.machine_summary`.**
   For each component with a repository, the latest repository-scope Report's
   `machine_summary` dict is captured as a `ComponentRepositorySummary` frozen
   struct.

6. **Lifecycle drives status for non-repository components.**
   Components without repositories use their catalogue lifecycle field. A
   future task (3.2.a) will add manual status support; the
   `ComponentEvidence.notes` field provides a hook for this.

## Outcomes & retrospective

All acceptance criteria met:

- 5 frozen msgspec domain models implemented in
  `ghillie/evidence/models.py`: `ProjectMetadata`,
  `ComponentRepositorySummary`, `ComponentEvidence`,
  `ComponentDependencyEvidence`, `ProjectEvidenceBundle`.
- `ProjectEvidenceBundleService` in `ghillie/evidence/project_service.py`
  builds complete bundles from catalogue and gold storage.
- 31 unit tests for domain models, 14 unit tests for service logic, and
  4 BDD scenarios all pass.
- Wildside multi-repository project produces a complete bundle with 4
  components (3 active, 1 planned), dependency edges, and optional repository
  summaries.
- Quality gates: `make check-fmt`, `make typecheck`, `make lint`,
  `make test` (704 passed, 35 skipped) all green.
- `docs/users-guide.md`, `docs/ghillie-design.md`, and `docs/roadmap.md`
  updated.
