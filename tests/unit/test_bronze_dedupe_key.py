"""Unit tests for Bronze dedupe key generation."""

from __future__ import annotations

import datetime as dt

import pytest

from ghillie.bronze import RawEventEnvelope, TimezoneAwareRequiredError, make_dedupe_key


def test_make_dedupe_key_changes_when_inputs_change() -> None:
    """Dedupe key changes when any input dimension changes."""
    occurred_at = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    base = make_dedupe_key(
        RawEventEnvelope(
            source_system="github",
            event_type="github.push",
            source_event_id="evt-1",
            repo_external_id="org/repo",
            occurred_at=occurred_at,
            payload={"a": 1},
        )
    )
    changed_repo = make_dedupe_key(
        RawEventEnvelope(
            source_system="github",
            event_type="github.push",
            source_event_id="evt-1",
            repo_external_id="org/other",
            occurred_at=occurred_at,
            payload={"a": 1},
        )
    )
    changed_payload = make_dedupe_key(
        RawEventEnvelope(
            source_system="github",
            event_type="github.push",
            source_event_id="evt-1",
            repo_external_id="org/repo",
            occurred_at=occurred_at,
            payload={"a": 2},
        )
    )

    assert base != changed_repo
    assert base != changed_payload


def test_make_dedupe_key_rejects_naive_occurred_at() -> None:
    """Naive occurred_at values are rejected for dedupe key generation."""
    envelope = RawEventEnvelope(
        source_system="github",
        event_type="github.push",
        source_event_id="evt-naive",
        repo_external_id="org/repo",
        occurred_at=dt.datetime(2024, 1, 1, 12, 0),  # noqa: DTZ001
        payload={"a": 1},
    )

    with pytest.raises(TimezoneAwareRequiredError) as excinfo:
        make_dedupe_key(envelope)
    assert "occurred_at" in str(excinfo.value)


def test_make_dedupe_key_normalizes_occurred_at_timezones() -> None:
    """occurred_at hashes the same for equal instants across timezones."""
    instant_utc = dt.datetime(2024, 1, 1, 12, 0, tzinfo=dt.timezone.utc)
    instant_offset = instant_utc.astimezone(dt.timezone(dt.timedelta(hours=1)))

    envelope_utc = RawEventEnvelope(
        source_system="github",
        event_type="github.push",
        source_event_id="evt-1",
        repo_external_id="org/repo",
        occurred_at=instant_utc,
        payload={"a": 1},
    )
    envelope_offset = RawEventEnvelope(
        source_system="github",
        event_type="github.push",
        source_event_id="evt-1",
        repo_external_id="org/repo",
        occurred_at=instant_offset,
        payload={"a": 1},
    )

    assert make_dedupe_key(envelope_utc) == make_dedupe_key(envelope_offset)


def test_make_dedupe_key_payload_determinism_and_timezone_awareness() -> None:
    """Payload hashing is deterministic and rejects naive datetimes."""
    occurred_at = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    payload_a = {"a": 1, "b": 2}
    payload_b = {"b": 2, "a": 1}

    env_a = RawEventEnvelope(
        source_system="github",
        event_type="github.push",
        source_event_id="evt-1",
        repo_external_id="org/repo",
        occurred_at=occurred_at,
        payload=payload_a,
    )
    env_b = RawEventEnvelope(
        source_system="github",
        event_type="github.push",
        source_event_id="evt-1",
        repo_external_id="org/repo",
        occurred_at=occurred_at,
        payload=payload_b,
    )

    assert make_dedupe_key(env_a) == make_dedupe_key(env_b)

    env_aware = RawEventEnvelope(
        source_system="github",
        event_type="github.push",
        source_event_id="evt-2",
        repo_external_id="org/repo",
        occurred_at=occurred_at,
        payload={
            "timestamp": dt.datetime(2024, 1, 1, 12, 0, tzinfo=dt.timezone.utc),
            "value": 42,
        },
    )

    assert make_dedupe_key(env_aware) == make_dedupe_key(env_aware)

    env_naive = RawEventEnvelope(
        source_system="github",
        event_type="github.push",
        source_event_id="evt-3",
        repo_external_id="org/repo",
        occurred_at=occurred_at,
        payload={"timestamp": dt.datetime(2024, 1, 1, 12, 0), "value": 42},  # noqa: DTZ001
    )

    with pytest.raises(TimezoneAwareRequiredError) as excinfo:
        make_dedupe_key(env_naive)
    assert "payload" in str(excinfo.value).lower()
