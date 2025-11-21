# ghillie Users' Guide

## Estate catalogue (Phase 1.1)

Ghillie now ships a YAML 1.2 catalogue describing programmes, projects,
components, repositories, and their relationships. Catalogue files are
validated with `msgspec` and exposed as a JSON Schema for external linters.

### Authoring a catalogue

- Use lowercase, dash-separated keys for programmes, projects, and components
  (for example, `wildside-engine`). Keys must be unique across the estate.
- Components may omit `repository` when they represent planned work. When
  present, repositories require `owner`, `name`, and `default_branch`.
- Capture relationships with `depends_on`, `blocked_by`, and
  `emits_events_to`. Each entry includes the target `component` and an optional
  `kind` (`runtime`, `dev`, `test`, `ops`) plus a short rationale.
- Configure per-project noise and status preferences under `noise` and
  `status` blocks so ingestion and reporting can ignore bot traffic or
  dependency-only pull requests.
- See `examples/wildside-catalogue.yaml` for a complete multi-repository
  project with planned components and cross-project dependencies.

### Validating a catalogue

The catalogue linter enforces YAML 1.2 semantics (strings like `on` remain
strings) and referential integrity between components.

1. Generate schema and JSON artefacts from a catalogue file:

   ```bash
   python -m ghillie.catalogue.cli examples/wildside-catalogue.yaml \
     --schema-out schemas/catalogue.schema.json \
     --json-out .cache/catalogue.json
   ```

2. Validate against the JSON Schema with `pajv`:

   ```bash
   pajv -s schemas/catalogue.schema.json -d .cache/catalogue.json
   ```

3. A non-zero exit code indicates structural errors, such as missing
   components in dependency lists or duplicate keys.

### Example: Wildside

The catalogue example models Wildside as a multi-repository project:

- `leynos/wildside` (core API) depends on `wildside-engine` and df12 shared
  libraries (`ortho-config`, `pg-embedded-setup-unpriv`, `rstest-bdd`).
- `leynos/wildside-engine` underpins the core service and is blocked by
  shared configuration rollout.
- `leynos/wildside-mockup` models UI experiments and receives events from the
  core service.
- `wildside-ingestion` is marked `lifecycle: planned` to represent work with
  no repository yet.

Noise controls ignore dependency bots and generated documentation paths, so the
ingestion pipeline can focus on meaningful events.
