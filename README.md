# Ghillie

Ghillie provides automated estate-level status reporting for GitHub
repositories. It watches your repositories so you don't have to. It ingests
activity from across your engineering estate, transforms raw events into
structured entities, and produces intelligent status reports at repository,
project, and estate levels.

## What is Ghillie?

If you've ever tried to synthesise the velocity, health, and compliance posture
of dozens (or thousands) of software repositories into a coherent narrative,
you'll know it's a thankless task. Ghillie automates that intelligence
gathering.

We built Ghillie to work alongside [Concordat][concordat], a governance control
plane. While Concordat enforces rules and tracks compliance, Ghillie acts as
the observational layer—capturing what's happening, structuring it, and turning
it into reports that humans (and machines) can actually use.

The goal isn't to replace human judgement; it's to give you the raw material
for better decisions without spending your weekends trawling through pull
requests.

## Architecture

Ghillie follows the **Medallion architecture** pattern, progressively refining
data through three layers:

- **Bronze** – Raw, append-only event storage. GitHub payloads land here
  unmodified, preserving auditability and enabling replay. Use this layer to
  debug ingestion or replay historical data.
- **Silver** – Refined entity tables. Deterministic transformers convert raw
  events into structured records: repositories, commits, pull requests, issues,
  and documentation changes. Query this layer for structured activity data.
- **Gold** – Aggregated intelligence. Report metadata, coverage tracking, and
  the machine summaries that power status narratives. Consume this layer for
  dashboards, notifications, and status pages.

This separation lets us reprocess historical data, debug transformation logic,
and evolve the schema without losing the original signals.

## Components

```text
ghillie/
├── catalogue/   # Estate configuration: projects, components, repositories
├── bronze/      # Raw event ingestion and storage
├── silver/      # Entity transformation and refinement
├── gold/        # Report metadata and coverage tracking
└── common/      # Shared utilities (timezone handling, etc.)
```

- **Catalogue** – YAML-based configuration for your estate. Define programmes,
  projects, components (even ones without repositories yet), and their
  relationships. The importer reconciles this into the database idempotently.
- **Bronze** – The `RawEventWriter` appends GitHub events with deduplication.
  Payloads are stored exactly as received.
- **Silver** – The `RawEventTransformer` hydrates entity tables from Bronze. A
  registry-based approach routes event types to their transformers.
- **Gold** – Report and coverage tables link generated reports back to the
  events they consumed, preventing double-counting on replay.

## Current status

Ghillie is under active development. **Phase 1 is complete**: we have a working
catalogue system, Bronze raw event storage, Silver entity tables, and Gold
report metadata schema.

We're now working toward **Phase 2**: repository-level status reporting with
LLM integration—the first directly consumable output.

See the [roadmap](docs/roadmap.md) for the full breakdown of phases and tasks.

## Getting started

The [users' guide](docs/users-guide.md) walks you through:

- Authoring and validating catalogue files
- Ingesting events into the Bronze layer
- Transforming events into Silver entities
- Creating reports with coverage tracking
- Running tests against Postgres with py-pglite

## Documentation

- [Users' guide](docs/users-guide.md) – Practical usage and examples
- [Roadmap](docs/roadmap.md) – Phases, steps, and completion criteria
- [Design document](docs/ghillie-design.md) – Architectural vision and rationale
- [Proposal](docs/ghillie-proposal.md) – Original problem statement and goals
- [Bronze/Silver architecture](docs/ghillie-bronze-silver-architecture-design.md)
  – Detailed Medallion layer design

## Related projects

- **Concordat** – The governance control plane that Ghillie complements. Ghillie
  ingests Concordat events and surfaces compliance state in reports (Phase 4).

## Licence

[ISC](LICENSE)

[concordat]: https://github.com/leynos/concordat
