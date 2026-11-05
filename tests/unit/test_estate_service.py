"""Catalogue-import behaviour for the estate-management service.

Every underlying failure type is translated at this boundary. HTTP and CLI
adapters therefore see only :mod:`ghillie.estate.errors`, which keeps the error
contract independent of SQLAlchemy and registry internals. Listing, sync, and
toggle behaviour live in ``test_estate_service_queries.py``.
"""

import asyncio
import gc
import typing as typ
import weakref

import pytest
from sqlalchemy import select
from sqlalchemy.exc import (
    IntegrityError,
    InterfaceError,
    OperationalError,
    SQLAlchemyError,
)

from ghillie.catalogue.importer import CatalogueImporter, CatalogueImportResult
from ghillie.catalogue.storage import Estate, ProjectRecord
from ghillie.catalogue.validation import CatalogueValidationError
from ghillie.estate.errors import (
    CatalogueRejectedError,
    EstateConflictError,
    InvalidEstateKeyError,
    StorageUnavailableError,
)
from tests.helpers.femtologging_capture import capture_femto_logs
from tests.unit.estate_test_helpers import count_rows, import_catalogue

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.estate.service import EstateManagementService
    from tests.helpers.femtologging_capture import FemtoLogCapture

_ESTATE_KEY = "demo"


# ---------------------------------------------------------------------------
# import_catalogue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_creates_estate_and_reports_counts(
    service: EstateManagementService,
) -> None:
    """A first import reports what it created and asks for a registry sync."""
    summary = await import_catalogue(service)

    assert summary.estate_key == _ESTATE_KEY, "estate key should match the import"
    assert summary.commit_sha == "c1", "commit sha should be c1"
    assert summary.state == "succeeded", "import should succeed"
    assert summary.dry_run is False, "import should not be a dry run"
    assert summary.skipped is False, "import should not be skipped"
    assert summary.skipped_reason is None, "skipped reason should be empty"
    assert summary.registry_sync_required is True, "registry sync should be required"
    assert (summary.projects.created, summary.projects.updated) == (1, 0), (
        "projects should report one created"
    )
    assert (summary.components.created, summary.components.updated) == (1, 0), (
        "components should report one created"
    )
    assert (summary.repositories.created, summary.repositories.updated) == (1, 0), (
        "repositories should report one created"
    )
    assert (summary.edges.created, summary.edges.updated) == (0, 0), (
        "edges should report no changes"
    )


@pytest.mark.asyncio
async def test_import_is_idempotent_for_the_same_commit(
    service: EstateManagementService,
) -> None:
    """A repeated commit is skipped and does no work."""
    await import_catalogue(service, commit_sha="c1")

    summary = await import_catalogue(service, commit_sha="c1")

    assert summary.skipped is True, "repeated commit should be skipped"
    assert summary.skipped_reason == "commit_already_imported", (
        "skip reason should name the commit"
    )
    assert summary.registry_sync_required is False, "no registry sync required"
    assert summary.projects.created == 0, "repeated commit creates no projects"
    assert summary.components.created == 0, "repeated commit creates no components"
    assert summary.repositories.created == 0, "repeat creates no repositories"


@pytest.mark.asyncio
async def test_import_dry_run_leaves_no_catalogue_rows(
    service: EstateManagementService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A dry run reports counts after flushing, then rolls back."""
    summary = await import_catalogue(service, dry_run=True)

    assert summary.projects.created == 1, "dry run should report a project"
    assert summary.repositories.created == 1, "dry run should report a repository"
    assert summary.dry_run is True, "summary should be a dry run"
    assert summary.registry_sync_required is False, "no registry sync required"
    assert await count_rows(session_factory, Estate) == 0, (
        "dry run should leave no estates"
    )
    assert await count_rows(session_factory, ProjectRecord) == 0, (
        "dry run should leave no project rows"
    )


@pytest.mark.asyncio
async def test_mutation_log_escapes_a_hostile_commit_sha(
    service: EstateManagementService,
) -> None:
    """D21: a control character cannot forge a second log line.

    ``commit_sha`` is client-supplied and only length-checked, so a newline
    followed by a plausible suffix must not split the structured record.
    """
    hostile = "c1\nestate.import estate_key=forged outcome=succeeded"

    with capture_femto_logs("ghillie.estate.service") as logs:
        await import_catalogue(service, commit_sha=hostile, dry_run=True)
        logs.wait_for_timeout()

    mutation_lines = [
        record.message for record in logs.records if "estate.import" in record.message
    ]
    assert mutation_lines, "the import should log one mutation line"
    assert all("\n" not in message for message in mutation_lines), (
        "the mutation record must stay on one line"
    )
    assert any("\\n" in message for message in mutation_lines), (
        "the control character should be visible as an escape"
    )


def _mutation_lines(logs: FemtoLogCapture, operation: str) -> list[str]:
    """Return the captured mutation records for one operation."""
    return [record.message for record in logs.records if operation in record.message]


@pytest.mark.asyncio
async def test_import_logs_one_terminal_record_when_it_succeeds(
    service: EstateManagementService,
) -> None:
    """D21: a successful import emits exactly one terminal record with edge counts."""
    with capture_femto_logs("ghillie.estate.service") as logs:
        await import_catalogue(service)
        logs.wait_for_timeout()

    lines = _mutation_lines(logs, "estate.import")
    assert len(lines) == 1, "a successful import should log exactly one record"
    assert "outcome=succeeded" in lines[0], "the record should name the outcome"
    assert "edges=0/0/0" in lines[0], "the record should report edge counts"
    assert "duration_ms=" in lines[0], "the record should report its duration"


@pytest.mark.asyncio
async def test_import_logs_one_terminal_record_when_it_is_skipped(
    service: EstateManagementService,
) -> None:
    """D21: a repeated commit logs one terminal record, not a success line."""
    await import_catalogue(service, commit_sha="c1")

    with capture_femto_logs("ghillie.estate.service") as logs:
        await import_catalogue(service, commit_sha="c1")
        logs.wait_for_timeout()

    lines = _mutation_lines(logs, "estate.import")
    assert len(lines) == 1, "a skipped import should log exactly one record"
    assert "outcome=skipped" in lines[0], "the record should name the skip"


@pytest.mark.asyncio
async def test_import_logs_one_terminal_record_when_it_fails(
    service: EstateManagementService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D21: a failed attempt logs one terminal record with its error class."""

    async def _conflict(
        _self: CatalogueImporter,
        _catalogue: object,
        *,
        commit_sha: str | None = None,
        dry_run: bool = False,
    ) -> CatalogueImportResult:
        raise IntegrityError("INSERT", {}, Exception("duplicate"))

    monkeypatch.setattr(CatalogueImporter, "import_catalogue", _conflict)

    with capture_femto_logs("ghillie.estate.service") as logs:
        with pytest.raises(EstateConflictError):
            await import_catalogue(service)
        logs.wait_for_timeout()

    lines = _mutation_lines(logs, "estate.import")
    assert len(lines) == 1, "a failed import should log exactly one record"
    assert "outcome=failed" in lines[0], "the record should name the failure"
    assert "error=EstateConflictError" in lines[0], "the record should name the error"
    assert "duration_ms=" in lines[0], "the record should report its duration"


@pytest.mark.asyncio
async def test_import_logs_a_rejected_document_as_a_failed_attempt(
    service: EstateManagementService,
) -> None:
    """D21: a document rejected before the lock still produces one record."""
    with capture_femto_logs("ghillie.estate.service") as logs:
        with pytest.raises(CatalogueRejectedError):
            await import_catalogue(service, catalogue_yaml="version: [unclosed")
        logs.wait_for_timeout()

    lines = _mutation_lines(logs, "estate.import")
    assert len(lines) == 1, "a rejection should log exactly one record"
    assert "outcome=failed" in lines[0], "the record should name the failure"
    assert "error=CatalogueRejectedError" in lines[0], (
        "the record should name the error"
    )


@pytest.mark.asyncio
async def test_import_uses_the_stored_name_when_none_is_supplied(
    service: EstateManagementService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """D18: a later import without a name does not rename the estate."""
    await import_catalogue(service, commit_sha="c1", estate_name="Demo Estate")

    await import_catalogue(service, commit_sha="c2", estate_name=None)

    async with session_factory() as session:
        estate = await session.scalar(select(Estate))
    assert estate is not None, "stored estate should exist"
    assert estate.name == "Demo Estate", "stored estate should keep its name"


@pytest.mark.asyncio
async def test_import_keeps_an_existing_description(
    service: EstateManagementService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """D18: catalogues carry no description, so an import must not clear one."""
    await import_catalogue(service, commit_sha="c1")
    async with session_factory() as session, session.begin():
        estate = await session.scalar(select(Estate))
        assert estate is not None, "stored estate should exist"
        estate.description = "Maintained by the platform team"

    await import_catalogue(service, commit_sha="c2", estate_name="Renamed")

    async with session_factory() as session:
        estate = await session.scalar(select(Estate))
    assert estate is not None, "stored estate should exist"
    assert estate.name == "Renamed", "import should rename the estate"
    assert estate.description == "Maintained by the platform team", (
        "import should keep the description"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("estate_key", ["", "-demo", ".demo", "demo/child"])
async def test_import_rejects_an_invalid_new_estate_key(
    service: EstateManagementService,
    estate_key: str,
) -> None:
    """D16: creating an estate requires the strict key pattern."""
    with pytest.raises(InvalidEstateKeyError):
        await import_catalogue(service, estate_key=estate_key)


@pytest.mark.asyncio
async def test_import_updates_an_estate_with_a_legacy_key(
    service: EstateManagementService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """D16: an estate created earlier through Python stays importable.

    The strict creation pattern applies only when the key does not exist yet.
    """
    legacy_key = "Wildside Estate"
    async with session_factory() as session, session.begin():
        session.add(Estate(key=legacy_key, name="Wildside Estate"))

    summary = await import_catalogue(service, estate_key=legacy_key)

    assert summary.estate_key == legacy_key, "import should reuse the legacy key"
    assert summary.state == "succeeded", "import into an existing estate should succeed"


@pytest.mark.asyncio
async def test_import_rejects_an_explicitly_empty_document(
    service: EstateManagementService,
) -> None:
    """An empty upload is rejected, not replaced by a default document.

    The test helper distinguishes an omitted document from an explicitly empty
    one so this case exercises the importer instead of the fixture.
    """
    with pytest.raises(CatalogueRejectedError, match="empty"):
        await import_catalogue(service, catalogue_yaml="")


@pytest.mark.asyncio
async def test_import_reports_catalogue_issues(
    service: EstateManagementService,
) -> None:
    """Invalid upload text becomes a catalogue rejection with issue codes."""
    with pytest.raises(CatalogueRejectedError) as raised:
        await import_catalogue(service, catalogue_yaml="version: [unclosed")

    assert raised.value.issues, "rejection should report issues"
    assert all(issue.code == "catalogue_schema" for issue in raised.value.issues), (
        "every issue should carry the catalogue code"
    )
    assert all(issue.message for issue in raised.value.issues), (
        "every issue should carry a message"
    )


@pytest.mark.asyncio
async def test_import_rejects_a_name_that_exceeds_storage(
    service: EstateManagementService,
) -> None:
    """An over-length name is a catalogue rejection, not a storage failure.

    Validation runs before the importer opens a session, so a dry run and a
    real import fail identically and nothing reaches a ``String(255)`` column.
    """
    document = "\n".join(
        [
            "version: 1",
            "projects:",
            "  - key: alpha",
            f"    name: {'x' * 256}",
            "    components: []",
        ]
    )

    with pytest.raises(CatalogueRejectedError, match="at most 255 characters"):
        await import_catalogue(service, catalogue_yaml=document)


@pytest.mark.asyncio
async def test_import_translates_validation_from_the_importer(
    service: EstateManagementService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A validation failure raised below the service is still a rejection."""

    async def _reject(
        _self: CatalogueImporter,
        _catalogue: object,
        *,
        commit_sha: str | None = None,
        dry_run: bool = False,
    ) -> CatalogueImportResult:
        raise CatalogueValidationError(["duplicate component key"])

    monkeypatch.setattr(CatalogueImporter, "import_catalogue", _reject)

    with pytest.raises(CatalogueRejectedError) as raised:
        await import_catalogue(service)

    assert raised.value.issues[0].message == "duplicate component key", (
        "validation should name the duplicate"
    )


@pytest.mark.asyncio
async def test_import_translates_an_integrity_error_to_conflict(
    service: EstateManagementService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D17: a uniqueness violation is a conflict, not a storage outage."""

    async def _conflict(
        _self: CatalogueImporter,
        _catalogue: object,
        *,
        commit_sha: str | None = None,
        dry_run: bool = False,
    ) -> CatalogueImportResult:
        raise IntegrityError("INSERT", {}, Exception("duplicate"))

    monkeypatch.setattr(CatalogueImporter, "import_catalogue", _conflict)

    with pytest.raises(EstateConflictError):
        await import_catalogue(service)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        OperationalError("SELECT", {}, Exception("down")),
        InterfaceError("SELECT", {}, Exception("broken")),
        SQLAlchemyError("unexpected"),
    ],
)
async def test_import_translates_storage_errors(
    service: EstateManagementService,
    monkeypatch: pytest.MonkeyPatch,
    error: SQLAlchemyError,
) -> None:
    """D17: connection and unexpected database failures are unavailable storage."""

    async def _fail(
        _self: CatalogueImporter,
        _catalogue: object,
        *,
        commit_sha: str | None = None,
        dry_run: bool = False,
    ) -> CatalogueImportResult:
        raise error

    monkeypatch.setattr(CatalogueImporter, "import_catalogue", _fail)

    with pytest.raises(StorageUnavailableError):
        await import_catalogue(service)


@pytest.mark.asyncio
async def test_import_lock_serializes_concurrent_imports(
    service: EstateManagementService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D17: one estate is never imported twice at once in this process."""
    active = 0
    max_active = 0

    async def _slow_import(
        self: CatalogueImporter,
        _catalogue: object,
        *,
        commit_sha: str | None = None,
        dry_run: bool = False,
    ) -> CatalogueImportResult:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        try:
            await asyncio.sleep(0.05)
            return CatalogueImportResult(self.estate_key, commit_sha)
        finally:
            active -= 1

    monkeypatch.setattr(CatalogueImporter, "import_catalogue", _slow_import)

    await asyncio.gather(
        import_catalogue(service, commit_sha="c1"),
        import_catalogue(service, commit_sha="c2"),
    )

    assert max_active == 1, "imports should not overlap"


@pytest.mark.asyncio
async def test_estate_locks_are_not_retained_after_use(
    service: EstateManagementService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D17: serialization does not leak one lock per key ever mentioned.

    An unauthenticated client can name any estate key, so a strong map would
    let it grow process memory indefinitely. The weak map must release an idle
    lock once the import block finishes.
    """
    created: list[weakref.ref[asyncio.Lock]] = []
    real_lock = asyncio.Lock

    class _RecordingLock(real_lock):
        def __init__(self) -> None:
            super().__init__()
            created.append(weakref.ref(self))

    monkeypatch.setattr(asyncio, "Lock", _RecordingLock)

    await import_catalogue(service, estate_key="alpha")
    await import_catalogue(service, estate_key="beta")
    gc.collect()

    assert created, "each import should create a per-estate lock"
    assert all(lock_ref() is None for lock_ref in created), (
        "idle locks should be released"
    )
