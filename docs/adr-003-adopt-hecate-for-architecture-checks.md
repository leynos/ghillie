# ADR-003: Adoption of Hecate for architecture checks

## Status

Accepted (implemented on 2026-06-01)

## Context

Ghillie uses a hexagonal ports-and-adapters architecture over a Medallion data
pipeline. The design documents describe domain, application, inbound adapter,
outbound adapter, and composition-root responsibilities, but the repository did
not have a dedicated import-direction gate. Behavioural tests covered runtime
selection, factories, report sinks, storage effects, and CLI contracts, but
they did not continuously check that Python imports preserve the intended
architecture.

Architecture drift is likely when new modules are added because Python import
edges are easy to introduce during feature work. A static checker must
therefore be:

- runnable locally through Make,
- deterministic enough for Continuous Integration (CI),
- configured from repository source control,
- explicit about documented exceptions, and
- scoped to import direction rather than runtime behaviour.

Hecate is a Python import architecture checker for hexagonal projects. It reads
`[tool.hecate]` from `pyproject.toml`, classifies modules into ordered groups,
expands package re-exports, and reports forbidden group-to-group imports.

## Decision

Adopt Hecate as Ghillie's canonical static architecture fitness function using
commit `46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12`.

The project will:

1. Add Hecate to the development dependency group using the pinned Git commit.
2. Store the architecture policy in `[tool.hecate]` in `pyproject.toml`.
3. Provide `make check-architecture` as the local architecture gate.
4. Run `check-architecture` before Ruff as part of `make lint`.
5. Keep behaviour tests for runtime behaviour and use Hecate only for static
   import-boundary checks.

### Compatibility note

The pinned Hecate CLI cannot run directly with Ghillie's previous
`cyclopts>=2.9,<3` dependency because it uses callable `cyclopts.Parameter`.
Ghillie now permits `cyclopts>=3,<4`. Cyclopts `3.24.0` still lacks Hecate's
`result_action` keyword, so `make check-architecture` runs Hecate through
`scripts/check_architecture.py`, a narrow compatibility wrapper that removes
only that unsupported keyword before importing Hecate's CLI.

The wrapper is temporary. It should be removed when the pinned Hecate commit is
advanced to a version whose CLI dependency declaration and Cyclopts usage are
aligned.

## Consequences

### Positive

- Import-direction drift is caught by a deterministic local and CI gate.
- The Hecate policy lives beside other Python tooling configuration in
  `pyproject.toml`.
- Behaviour tests can stay focused on observable behaviour instead of acting as
  architecture sentinels.
- New module-boundary decisions require explicit policy updates or documented
  exceptions.

### Negative

- Hecate is pinned from Git rather than a package index release.
- The initial adoption needs a small compatibility wrapper for the pinned
  Hecate CLI.
- Contributors must maintain ordered Hecate groups when adding new package
  boundaries.

### Neutral

- No public Ghillie Python API, CLI command, HTTP route, storage schema, or
  runtime configuration changes.
- Existing behaviour tests remain in place.

## Alternatives considered

### Keep relying on tests and review

This requires reviewers to spot import-boundary drift manually and makes
architecture enforcement inconsistent. It was rejected because the repository
already has enough modules and adapters for accidental coupling to be plausible.

### Write a repository-local checker

A local checker would avoid the Hecate CLI compatibility wrapper, but it would
duplicate import parsing, package re-export handling, policy validation, and
diagnostic rendering. It was rejected in favour of a shared checker with its
own test suite.

### Adopt Import Linter

Import Linter is mature and widely used, but Hecate's policy model directly
matches the composition-root, domain-port, application, inbound-adapter, and
outbound-adapter grouping used by related df12 projects. Hecate was selected
for consistency with that ecosystem.

## Rollback

To roll back this decision:

1. Remove the Hecate development dependency and lockfile entry.
2. Remove `[tool.hecate]` from `pyproject.toml`.
3. Remove `scripts/check_architecture.py`.
4. Remove `check-architecture` from `Makefile` and `make lint`.
5. Remove the CI lint-step wording that mentions architecture checks.
6. Supersede this ADR with a replacement decision rather than deleting the
   historical record.

## References

- Hecate users' guide:
  <https://raw.githubusercontent.com/leynos/hecate/46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12/docs/users-guide.md>
- Hecate configuration guide:
  <https://raw.githubusercontent.com/leynos/hecate/46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12/docs/configuration.md>
- Hecate Episodic migration notes:
  <https://raw.githubusercontent.com/leynos/hecate/46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12/docs/migration-episodic.md>
- Implementation plan: `docs/execplans/adopt-hecate.md`
