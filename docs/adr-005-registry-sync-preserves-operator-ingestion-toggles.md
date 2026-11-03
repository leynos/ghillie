# ADR-005: Registry sync preserves operator ingestion toggles

## Status

Accepted (implemented on 2026-11-03)

## Date

2026-11-03.

## Context and problem statement

`RepositoryRegistryService.sync_from_catalogue()` projects catalogue
repositories into the Silver `repositories` table. Until now it wrote
`ingestion_enabled = catalogue.is_active` on every sync. An operator who ran
`ghillie estate repository disable leynos/wildside` therefore had that decision
silently reverted by the next catalogue import and sync, with no record that
anything had changed.

An import and a sync can follow each other many times a day. The Silver toggle
is the only per-repository switch the ingestion worker consults, so losing it
means the worker resumes GitHub polling for a repository an operator had
deliberately silenced.

## Decision drivers

- An operator's explicit toggle must survive routine imports and syncs.
- A repository removed from the catalogue must stop ingesting, without being
  deleted, so historical reports stay joinable.
- A repository owned by another estate must never be captured, disabled, or
  otherwise mutated by this estate's sync.
- The rule must be testable without a database, and the order-dependent
  behaviour must be exercised against the real ORM code.
- No schema change and no new dependency: this is an MVP delivery.

## Options considered

### Option A: Keep writing `catalogue.is_active`

Rejected. It is the defect: every sync discards the operator's decision.

### Option B: Add an operator-override column

Rejected. A new column needs a migration and a distinction between "unset" and
"set to the default", and it duplicates a flag that already exists.

### Option C: Treat the Silver flag as authoritative once a row is linked

Accepted. Sync owns creation and removal; the operator owns the flag of a
linked row that is still in the catalogue.

### Option D: Unlink removed rows instead of disabling them

Rejected. `ghillie/evidence/project_service.py` joins on
`catalogue_repository_id`, so unlinking would silently drop historical evidence
from reports.

### Option E: Move a row to the estate whose catalogue now names it

Rejected. There is no safe ownership rule while both estates exist, and taking
a row from a live estate would disable ingestion for repositories that estate
still relies on.

## Decision outcome

Sync decides each row with two pure functions in `ghillie.registry.policy`,
which import only `dataclasses` and `enum`:

- `decide_for_catalogue_repository(current, *, catalogue_active)` for a slug
  this estate's catalogue names:
  - no Silver row, or an unlinked row of this estate: `ADOPT`, taking
    `catalogue_active`;
  - a linked row of this estate: `PRESERVE` when the catalogue entry is
    active, `DISABLE_INACTIVE` when it is not;
  - a row owned by another estate: `CONFLICT`, leaving the row untouched and
    reporting the slug in `SyncResult.repositories_conflicted`.
- `decide_for_removed_repository(current)` for a row of this estate absent
  from the catalogue: `DISABLE_REMOVED` for a linked row, `PRESERVE` for an
  unlinked ad hoc row, and `CONFLICT` (unreported) for another estate's row.

Sync writes `ingestion_enabled` only when the decided value differs, which
narrows the window in which a concurrent toggle can be lost. A repository that
was removed and later re-added keeps its disabled flag until an operator
enables it, and the sync response lists it in `repositories_left_disabled` (the
first 100 slugs, plus an exact count in `repositories_left_disabled_count`).

A toggle applied to an unlinked ad hoc row survives only until the row is
adopted by a catalogue entry, at which point `ADOPT` takes the catalogue's
active flag. This is documented in the users' guide.

## Known risks and limitations

- `PRESERVE` means an operator must re-enable ingestion by hand after a
  removal and re-add. The sync response names those repositories so the state
  is visible rather than silent.
- A row claimed by another estate is reported, not reconciled. Resolving the
  overlap needs an operator decision, which is outside sync's authority.
- The bounded preview hides the tail of a very large estate; the exact count
  remains available.

## Architectural rationale

Ownership of the ingestion flag follows the lifetime of the row. Sync owns the
transitions it causes — creation, adoption, and removal — and the operator owns
the steady state of a linked row. Making that split a pure function keeps it
exhaustively testable, and keeping the ORM projection thin means the
model-based test can drive the real importer, sync, and toggle code instead of
a stand-in.
