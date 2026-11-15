# Migration guide

This guide records behaviour changes that need action when upgrading between
releases. The repository has not yet published a 2.0.0 release:
`pyproject.toml` declares version 1.0.0, and the changes below ship in the next
major release. They apply to any deployment upgrading from the 1.x
registry-sync semantics.

## Registry synchronization in 2.0.0

### Ingestion toggles belong to the operator

In 1.x, every sync wrote `ingestion_enabled` from the catalogue's active flag,
so the next import and sync silently reverted an operator's explicit disable.

From 2.0.0, sync never re-enables a linked repository of the estate. A
catalogue entry that becomes active again leaves the row disabled until an
operator enables it. The rule and its rationale are recorded in
[ADR-005](adr-005-registry-sync-preserves-operator-ingestion-toggles.md).

**Action after upgrading.** Re-apply any disable that a 1.x sync reverted.
Compare the repositories an operator expects to be off with
`list_active_repositories()`, and call `disable_ingestion()` for each one that
is unexpectedly enabled.

### Cross-estate conflicts are reported, not fatal

In 1.x, a repository named by two estates was inserted a second time and failed
the global unique `(github_owner, github_name)` constraint, which aborted the
whole estate sync.

From 2.0.0, the row stays with the estate that owns it, the slug is reported in
`SyncResult.repositories_conflicted`, and the rest of the sync completes. A
genuine integrity failure that no owner/name race explains still raises
`RegistrySyncError` and keeps its cause for the HTTP 409 mapping.

**Action after upgrading.** Read `repositories_conflicted` after the first sync
and remove the reported slugs from the estate that does not own them.

### New result fields

`SyncResult` gains three additive fields; no existing field, HTTP response
field, CLI verb, or persisted schema changes:

- `repositories_conflicted` lists catalogue slugs another estate owns.
- `repositories_left_disabled` previews, in slug order, the first 100 active
  catalogue repositories whose linked row was disabled in the view the sync
  loaded and that the sync left disabled.
- `repositories_left_disabled_count` carries the total across the estate.

The preview and count observe that view plus the sync's own writes rather than
re-reading committed state, so a toggle another writer commits after the load
is not seen and is not overwritten. Two paths reload a single row from
committed state to judge ownership: a lost adoption claim and a lost owner/name
insert race. A row reloaded that way is reported from the reloaded state, so a
toggle committed before the reload can be seen, and a row it makes enabled is
not reported as left disabled. They say that ingestion is off, not why: a row
can have been disabled by an operator or by an earlier removal.
`repositories_deactivated` counts only removed rows that this sync turned from
enabled to disabled, so a removed row an operator had already disabled is not
counted again.

### Dry runs

`sync_from_catalogue(estate_key, dry_run=True)` runs the same projection inside
its transaction, flushes so constraints are evaluated, and then rolls back. The
returned counts describe what a real run would have done, and nothing is
persisted.

## Estate management HTTP API in 2.0.0

The estate-management HTTP API is part of this release. Its clients
authenticate with a bearer token and branch on a structured error `code` rather
than on response prose.

### Bearer authentication

The 2.0.0 specification replaces the earlier `ApiKeyAuth` scheme with
`BearerAuth`. `ApiKeyAuth` was an `apiKey` header declaration that the
specification itself described as a placeholder for future endpoints, and no
route enforced it, so nothing that only called the shipped routes changes
behaviour by itself. Authentication is itself optional: with a token
configured, every route except `GET /health` and `GET /ready` requires it,
which includes the report route that already shipped as well as the new estate
routes. Set `GHILLIE_API_TOKEN` and send `Authorization: Bearer <token>` with
every request. A missing or wrong token returns 401 `unauthorized` with a
`WWW-Authenticate: Bearer` challenge. When the variable is unset, the API stays
open and start-up logs a warning; when it is set but blank, start-up fails.

**Action after upgrading.** Provision `GHILLIE_API_TOKEN` as a secret and send
the bearer header from every API client. Leave the variable unset only when the
API is not exposed beyond a trusted local environment.

### Structured error envelope

Every failure uses one JSON envelope. `code`, `title`, and `description` are
always present. `field` names the input that failed validation, `issues` lists
catalogue or report validation problems, and `max_bytes` accompanies a 413.

```json
{
  "title": "Invalid input",
  "description": "must be an integer",
  "code": "invalid_input",
  "field": "limit"
}
```

**Action after upgrading.** Read `code` for control flow and use `description`
only for display. Do not match on prose, and treat an unknown `code` as an
unexpected failure.

### Route families

`GHILLIE_DATABASE_URL` enables the estate routes. The report route additionally
requires `GHILLIE_STATUS_MODEL_BACKEND`; without that variable the runtime does
not build a reporting service and does not register the route.

**Action after upgrading.** Set both variables for clients that call the report
route, and leave both unset to run health-only.

## References

- [Users' guide](users-guide.md) for the day-to-day sync workflow.
- [Developers' guide](developers-guide.md) for the service API and its
  guarantees.
- [ADR-005](adr-005-registry-sync-preserves-operator-ingestion-toggles.md) for
  the toggle-ownership decision.
