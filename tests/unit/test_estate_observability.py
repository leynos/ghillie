"""D21 record rendering for estate mutations.

These tests exercise the recorder directly, so the record vocabulary, its
escaping, and its timing are pinned without going through a database or the
service.
"""

import typing as typ

import pytest

from ghillie.estate.models import (
    CatalogueImportSummary,
    CountSummary,
    RegistrySyncSummary,
)
from ghillie.estate.observability import (
    MutationOutcome,
    MutationRecorder,
    failure_details,
    import_details,
    sync_details,
)
from tests.helpers.femtologging_capture import capture_femto_logs

if typ.TYPE_CHECKING:
    from tests.helpers.femtologging_capture import FemtoLogCapture


class _Cancelled(BaseException):
    """Stand-in for ``asyncio.CancelledError`` in rendering tests."""


class _FixedClock:
    """A clock the test advances by hand, so a duration can be asserted exactly.

    ``0.25`` seconds is exact in binary, so ``0.25 * 1000`` renders as
    ``250.0`` without a floating-point rounding surprise in the assertion.
    """

    def __init__(self) -> None:
        """Start the clock at zero."""
        self._now = 0.0

    def __call__(self) -> float:
        """Return the current instant in seconds."""
        return self._now

    def advance(self, seconds: float) -> None:
        """Move the clock forward."""
        self._now += seconds


def _messages(logs: FemtoLogCapture) -> list[str]:
    """Return the captured messages in emission order."""
    logs.wait_for_timeout()
    return [record.message for record in logs.records]


def _import_summary() -> CatalogueImportSummary:
    """Build an import summary with distinguishable counts in every family."""
    return CatalogueImportSummary(
        estate_key="demo",
        commit_sha="c1",
        state="succeeded",
        dry_run=False,
        skipped=False,
        skipped_reason=None,
        registry_sync_required=True,
        projects=CountSummary(created=1, updated=2, deleted=3),
        components=CountSummary(created=4, updated=5, deleted=6),
        repositories=CountSummary(created=7, updated=8, deleted=9),
        edges=CountSummary(created=10, updated=11, deleted=12),
    )


def test_record_mutation_escapes_request_fields_onto_one_line() -> None:
    """A hostile estate key or commit cannot forge a second record."""
    recorder = MutationRecorder()
    mutation = recorder.begin_mutation(
        operation="estate.import",
        estate_key="demo\nestate.import outcome=succeeded",
        commit_sha="c1\nestate.import outcome=succeeded",
        dry_run=True,
    )

    with capture_femto_logs("ghillie.estate.observability") as logs:
        recorder.record_mutation(
            mutation,
            outcome=MutationOutcome.SUCCEEDED,
            details="projects=1/0/0",
        )
        messages = _messages(logs)

    assert len(messages) == 1, "one mutation attempt should emit one record"
    message = messages[0]
    assert "\n" not in message, "the record must stay on a single line"
    assert "\\n" in message, "the control character should appear as an escape"
    assert message.startswith("estate.import estate_key="), (
        "the record should open with the operation"
    )
    assert "dry_run=True" in message, "the record should carry the dry-run flag"
    assert "projects=1/0/0" in message, "the record should carry the counts"
    assert "duration_ms=" in message, "the record should carry its duration"
    assert message.endswith("outcome=succeeded"), "the outcome should close the record"


def test_record_mutation_renders_a_missing_commit_as_a_dash() -> None:
    """A mutation with no commit still leaves a field in a fixed position."""
    recorder = MutationRecorder()
    mutation = recorder.begin_mutation(
        operation="estate.registry-sync",
        estate_key="demo",
        commit_sha=None,
        dry_run=False,
    )

    with capture_femto_logs("ghillie.estate.observability") as logs:
        recorder.record_mutation(
            mutation,
            outcome=MutationOutcome.FAILED,
            details="error=ValueError message='boom'",
        )
        message = _messages(logs)[0]

    assert "commit_sha='-'" in message, (
        "a missing commit should render as a quoted dash in the field's position"
    )
    assert message.endswith("outcome=failed"), "the outcome should close the record"


def test_record_toggle_escapes_the_repository_identity() -> None:
    """The owner and name come from the request, so both are quoted."""
    recorder = MutationRecorder()
    toggle = recorder.begin_toggle(
        owner="org\nestate.set-ingestion outcome=succeeded",
        name="alpha\nforged",
        enabled=False,
    )

    with capture_femto_logs("ghillie.estate.observability") as logs:
        recorder.record_toggle(
            toggle,
            outcome=MutationOutcome.SUCCEEDED,
            details="previous=True changed=True",
        )
        messages = _messages(logs)

    assert len(messages) == 1, "one toggle should emit one record"
    message = messages[0]
    assert "\n" not in message, "the record must stay on a single line"
    assert "\\n" in message, "the control character should appear as an escape"
    assert "enabled=False" in message, "the record should carry the requested state"
    assert "previous=True changed=True" in message, (
        "the record should carry the state change"
    )


def test_recorder_times_the_record_with_its_injected_clock() -> None:
    """The recorder measures the attempt with the clock it was given."""
    clock = _FixedClock()
    recorder = MutationRecorder(clock=clock)
    mutation = recorder.begin_mutation(
        operation="estate.import",
        estate_key="demo",
        commit_sha="c1",
        dry_run=False,
    )
    clock.advance(0.25)

    with capture_femto_logs("ghillie.estate.observability") as logs:
        recorder.record_mutation(
            mutation,
            outcome=MutationOutcome.SUCCEEDED,
            details="projects=0/0/0",
        )
        message = _messages(logs)[0]

    assert "duration_ms=250.0" in message, (
        "the duration should come from the injected clock"
    )


def test_recorder_times_a_toggle_with_its_injected_clock() -> None:
    """A toggle record uses the same injected clock as a mutation record."""
    clock = _FixedClock()
    recorder = MutationRecorder(clock=clock)
    toggle = recorder.begin_toggle(owner="org", name="alpha", enabled=True)
    clock.advance(0.001)

    with capture_femto_logs("ghillie.estate.observability") as logs:
        recorder.record_toggle(
            toggle,
            outcome=MutationOutcome.SUCCEEDED,
            details="previous=False changed=True",
        )
        message = _messages(logs)[0]

    assert "duration_ms=1.0" in message, "the toggle should be timed by the same clock"


def test_failure_details_quote_the_message() -> None:
    """A message that quotes client text cannot break the line."""
    details = failure_details(ValueError("bad\nvalue"))

    assert details == "error=ValueError message='bad\\nvalue'", (
        "failure details should name the class and quote the message"
    )


def test_failure_details_accept_a_base_exception() -> None:
    """Cancellation derives from ``BaseException`` and is still recordable."""
    details = failure_details(_Cancelled())

    assert details.startswith("error=_Cancelled "), (
        "a BaseException should be rendered like any other failure"
    )


def test_import_details_render_every_count_family() -> None:
    """Each family reads created/updated/deleted, in a fixed order."""
    details = import_details(_import_summary())

    assert details == (
        "projects=1/2/3 components=4/5/6 repositories=7/8/9 edges=10/11/12"
    ), "the counts should render in family order"


def test_sync_details_count_conflicts_and_left_disabled() -> None:
    """The sync record reports conflict count, not the conflicting slugs."""
    summary = RegistrySyncSummary(
        estate_key="demo",
        state="succeeded",
        dry_run=False,
        repositories_created=1,
        repositories_updated=2,
        repositories_deactivated=3,
        repositories_conflicted=("a/one", "b/two"),
        repositories_left_disabled=("a/one",),
        repositories_left_disabled_count=4,
    )

    assert sync_details(summary) == (
        "created=1 updated=2 deactivated=3 conflicted=2 left_disabled=4"
    ), "conflicts should be counted rather than listed"


def test_the_outcome_vocabulary_is_closed() -> None:
    """D21 records exactly these outcomes and no free-text alternative."""
    assert {outcome.value for outcome in MutationOutcome} == {
        "succeeded",
        "skipped",
        "failed",
        "cancelled",
    }, "the outcome vocabulary should not grow silently"


@pytest.mark.parametrize("outcome", list(MutationOutcome))
def test_every_outcome_renders_its_own_value(outcome: MutationOutcome) -> None:
    """``%s`` on a ``StrEnum`` member must yield the bare value."""
    recorder = MutationRecorder()
    mutation = recorder.begin_mutation(
        operation="estate.import",
        estate_key="demo",
        commit_sha="c1",
        dry_run=False,
    )

    with capture_femto_logs("ghillie.estate.observability") as logs:
        recorder.record_mutation(mutation, outcome=outcome, details="projects=0/0/0")
        message = _messages(logs)[0]

    assert message.endswith(f"outcome={outcome.value}"), (
        f"{outcome.name} should render as {outcome.value}"
    )
