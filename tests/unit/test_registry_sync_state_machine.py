"""Model-based test for catalogue-to-Silver ingestion transitions.

Invariant O1: a linked Silver row that belongs to this estate is never moved
from disabled to enabled by a sync, and a present, active, linked row keeps the
operator's last toggle. The decision defect was order-dependent and lived in
the ORM application rather than in the pure policy, so this machine drives the
real ``CatalogueImporter``, ``sync_from_catalogue``, and
``enable/disable_ingestion`` against an in-memory database.

Hypothesis owns the ordering; the model below owns the expectation. Every
observed transition is counted so the test can prove it was not vacuous.
"""

import asyncio
import collections
import dataclasses
import typing as typ

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    precondition,
    rule,
    run_state_machine_as_test,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ghillie.catalogue import (
    Catalogue,
    CatalogueImporter,
    Component,
    Estate,
    Project,
    RepositoryRecord,
    init_catalogue_storage,
)
from ghillie.catalogue import (
    Repository as CatalogueRepository,
)
from ghillie.registry import RepositoryRegistryService, SyncResult
from ghillie.registry.policy import IngestionTransition
from ghillie.silver import init_silver_storage
from ghillie.silver.storage import Repository as SilverRepository

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

_THIS_ESTATE = "this-estate"
_OTHER_ESTATE = "other-estate"

# Four slugs from the wildside example keep the generated space small enough to
# search while still allowing distinct rows to move through different paths.
_REPOSITORIES: tuple[tuple[str, str], ...] = (
    ("leynos", "wildside"),
    ("leynos", "wildside-engine"),
    ("leynos", "wildside-mockup"),
    ("leynos", "ortho-config"),
)
_SLUGS = tuple(f"{owner}/{name}" for owner, name in _REPOSITORIES)

_INDEX = st.integers(min_value=0, max_value=len(_REPOSITORIES) - 1)
_SUBSET = st.frozensets(_INDEX)

# The witness sequence below needs three of the four slugs; the fourth stays
# absent so ``create_ad_hoc`` remains reachable.
_WITNESS_PRESENT = frozenset({0, 1, 2})
_WITNESS_REMAINING = frozenset({0})


def _build_catalogue(indexes: typ.Iterable[int]) -> Catalogue:
    """Build a one-project catalogue containing the selected repositories."""
    components = [
        Component(
            key=f"component-{index}",
            name=f"Component {index}",
            repository=CatalogueRepository(owner=owner, name=name),
        )
        for index, (owner, name) in enumerate(_REPOSITORIES)
        if index in indexes
    ]
    return Catalogue(
        version=1,
        projects=[
            Project(
                key="estate-fixture",
                name="Estate Fixture",
                components=components,
            )
        ],
    )


@dataclasses.dataclass
class _ExpectedRepository:
    """Model of one slug's Silver row and its catalogue membership."""

    exists: bool = False
    # "none" before any estate claims the row, then "this" or "other".
    owner: typ.Literal["none", "this", "other"] = "none"
    linked: bool = False
    enabled: bool = False
    in_catalogue: bool = False
    active: bool = True


class EstateSyncMachine(RuleBasedStateMachine):
    """Drive real syncs while tracking what each slug's row should look like."""

    def __init__(self, transitions: collections.Counter[IngestionTransition]) -> None:
        """Create the databases and model before Hypothesis runs any rule."""
        super().__init__()
        self.transitions = transitions
        self._runner = asyncio.Runner()
        self._engine = self._runner.run(self._create_engine())
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        self._service = RepositoryRegistryService(
            self._session_factory, self._session_factory
        )
        self._importer = CatalogueImporter(
            self._session_factory,
            estate_key=_THIS_ESTATE,
            estate_name="This Estate",
        )
        self._other_importer = CatalogueImporter(
            self._session_factory,
            estate_key=_OTHER_ESTATE,
            estate_name="Other Estate",
        )
        self._other_catalogue: set[int] = set()
        self._commits = 0
        self._model = [_ExpectedRepository() for _ in _SLUGS]

    def teardown(self) -> None:
        """Dispose the engine and close the loop used for every rule."""
        self._runner.run(self._engine.dispose())
        self._runner.close()

    # -- database helpers -------------------------------------------------

    async def _create_engine(self) -> AsyncEngine:
        engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
        await init_catalogue_storage(engine)
        await init_silver_storage(engine)
        return engine

    def _next_commit(self) -> str:
        self._commits += 1
        return f"commit-{self._commits}"

    async def _estate_id(self, key: str) -> str | None:
        async with self._session_factory() as session:
            return await session.scalar(select(Estate.id).where(Estate.key == key))

    async def _silver_row(self, index: int) -> SilverRepository | None:
        owner, name = _REPOSITORIES[index]
        async with self._session_factory() as session:
            return await session.scalar(
                select(SilverRepository).where(
                    SilverRepository.github_owner == owner,
                    SilverRepository.github_name == name,
                )
            )

    def _assert_matches_db(self) -> None:
        self._runner.run(self._check_model())

    async def _check_model(self) -> None:
        this_id = await self._estate_id(_THIS_ESTATE)
        other_id = await self._estate_id(_OTHER_ESTATE)
        for index, slug in enumerate(_SLUGS):
            row = await self._silver_row(index)
            expected = self._model[index]
            if not expected.exists:
                assert row is None, f"unexpected Silver row for {slug}"
                continue
            assert row is not None, f"missing Silver row for {slug}"
            assert row.ingestion_enabled is expected.enabled, slug
            assert (row.catalogue_repository_id is not None) is expected.linked, slug
            if expected.owner == "other":
                assert row.estate_id == other_id, slug
            elif expected.linked:
                assert row.estate_id == this_id, slug
            else:
                assert row.estate_id is None, slug

    # -- rules ------------------------------------------------------------

    @initialize()
    def seed_every_transition(self) -> None:
        """Produce one of each transition so the counter can never be vacuous.

        Hypothesis chooses rule order; without this seed a short run could skip
        a transition entirely and still pass the model checks.
        """
        self.import_into_other_estate(1)
        self.import_subset(_WITNESS_PRESENT)
        self.sync()
        self.sync()
        self.mark_inactive(0)
        self.sync()
        self.import_subset(_WITNESS_REMAINING)
        self.sync()

    @rule(subset=_SUBSET)
    def import_subset(self, subset: frozenset[int]) -> None:
        """Import a fresh catalogue revision containing only ``subset``."""
        self._runner.run(self._import_subset(subset))
        for index, expected in enumerate(self._model):
            present = index in subset
            if expected.in_catalogue and not present and expected.owner != "other":
                # Removing the slug prunes the catalogue record, so a later
                # re-add starts from a fresh, active record.
                expected.active = True
            expected.in_catalogue = present
        self._assert_matches_db()

    @rule()
    def sync(self) -> None:
        """Sync this estate and replay every transition through the model."""
        disabled_before = {
            index
            for index, expected in enumerate(self._model)
            if expected.owner == "this" and expected.linked and not expected.enabled
        }
        result = self._runner.run(self._service.sync_from_catalogue(_THIS_ESTATE))
        for index in range(len(_SLUGS)):
            self._apply_transition(index, result)

        for index in disabled_before:
            assert not self._model[index].enabled, (
                f"sync re-enabled linked row {_SLUGS[index]}"
            )
        self._assert_matches_db()

    @rule(index=_INDEX, enabled=st.booleans())
    @precondition(lambda self: any(expected.exists for expected in self._model))
    def toggle(self, index: int, *, enabled: bool) -> None:
        """Toggle ingestion exactly as an operator would.

        Hypothesis passes only the machine to a precondition, so the per-index
        guard lives here: an index with no row yet is a no-op step.
        """
        if not self._model[index].exists:
            return
        owner, name = _REPOSITORIES[index]
        if enabled:
            changed = self._runner.run(self._service.enable_ingestion(owner, name))
        else:
            changed = self._runner.run(self._service.disable_ingestion(owner, name))
        expected = self._model[index]
        assert changed is (expected.enabled != enabled), (_SLUGS[index], enabled)
        expected.enabled = enabled
        self._assert_matches_db()

    @rule(index=_INDEX)
    @precondition(
        lambda self: any(
            expected.in_catalogue and expected.owner != "other"
            for expected in self._model
        )
    )
    def mark_inactive(self, index: int) -> None:
        """Mark a catalogue repository inactive, as YAML cannot express it."""
        expected = self._model[index]
        if not expected.in_catalogue or expected.owner == "other":
            return
        self._runner.run(self._mark_inactive(index))
        expected.active = False
        self._assert_matches_db()

    @rule(index=_INDEX)
    @precondition(lambda self: any(not expected.exists for expected in self._model))
    def create_ad_hoc(self, index: int) -> None:
        """Create a Silver row that no catalogue has ever named."""
        if self._model[index].exists:
            return
        self._runner.run(self._create_ad_hoc(index))
        expected = self._model[index]
        expected.exists = True
        expected.owner = "this"
        expected.linked = False
        expected.enabled = False
        self._assert_matches_db()

    @rule(index=_INDEX)
    @precondition(
        lambda self: any(
            not expected.exists and not expected.in_catalogue
            for expected in self._model
        )
    )
    def import_into_other_estate(self, index: int) -> None:
        """Let another estate claim a slug that this estate does not use."""
        target = self._model[index]
        if target.exists or target.in_catalogue:
            return
        self._other_catalogue.add(index)
        self._runner.run(self._sync_other_estate())
        expected = self._model[index]
        expected.exists = True
        expected.owner = "other"
        expected.linked = True
        expected.enabled = expected.active
        self._assert_matches_db()

    # -- model helpers ----------------------------------------------------

    def _apply_transition(self, index: int, result: SyncResult) -> None:
        """Replay the transition the real sync should have produced."""
        expected = self._model[index]
        if expected.owner == "other":
            if expected.in_catalogue:
                assert _SLUGS[index] in result.repositories_conflicted, _SLUGS[index]
                self.transitions[IngestionTransition.CONFLICT] += 1
            return
        if expected.owner == "none":
            if expected.in_catalogue:
                self._adopt(index)
            return
        if not expected.linked:
            if expected.in_catalogue:
                self._adopt(index)
            else:
                self.transitions[IngestionTransition.PRESERVE] += 1
            return
        if expected.in_catalogue:
            self._preserve_or_disable_inactive(index)
        else:
            expected.enabled = False
            self.transitions[IngestionTransition.DISABLE_REMOVED] += 1

    def _adopt(self, index: int) -> None:
        expected = self._model[index]
        expected.exists = True
        expected.owner = "this"
        expected.linked = True
        expected.enabled = expected.active
        self.transitions[IngestionTransition.ADOPT] += 1

    def _preserve_or_disable_inactive(self, index: int) -> None:
        expected = self._model[index]
        if expected.active:
            self.transitions[IngestionTransition.PRESERVE] += 1
        else:
            expected.enabled = False
            self.transitions[IngestionTransition.DISABLE_INACTIVE] += 1

    # -- async rule bodies ------------------------------------------------

    async def _import_subset(self, subset: frozenset[int]) -> None:
        await self._importer.import_catalogue(
            _build_catalogue(subset), commit_sha=self._next_commit()
        )

    async def _sync_other_estate(self) -> None:
        await self._other_importer.import_catalogue(
            _build_catalogue(self._other_catalogue), commit_sha=self._next_commit()
        )
        result = await self._service.sync_from_catalogue(_OTHER_ESTATE)
        assert result.repositories_conflicted == [], result.repositories_conflicted

    async def _mark_inactive(self, index: int) -> None:
        owner, name = _REPOSITORIES[index]
        async with self._session_factory() as session, session.begin():
            record = await session.scalar(
                select(RepositoryRecord).where(
                    RepositoryRecord.owner == owner,
                    RepositoryRecord.name == name,
                )
            )
            assert record is not None
            record.is_active = False

    async def _create_ad_hoc(self, index: int) -> None:
        owner, name = _REPOSITORIES[index]
        async with self._session_factory() as session, session.begin():
            session.add(
                SilverRepository(
                    github_owner=owner,
                    github_name=name,
                    default_branch="main",
                    ingestion_enabled=False,
                )
            )


@pytest.mark.timeout(120)
def test_sync_transitions_are_modelled() -> None:
    """The real sync never re-enables a linked row and every rule is exercised."""
    transitions: collections.Counter[IngestionTransition] = collections.Counter()

    def machine_factory() -> EstateSyncMachine:
        return EstateSyncMachine(transitions)

    run_state_machine_as_test(
        machine_factory,
        settings=settings(
            max_examples=15,
            stateful_step_count=15,
            deadline=None,
            suppress_health_check=[HealthCheck.too_slow],
        ),
    )

    missing = set(IngestionTransition) - set(transitions)
    assert not missing, f"transitions never exercised: {sorted(missing)}"
