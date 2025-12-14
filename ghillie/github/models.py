"""Typed domain models for GitHub ingestion."""

from __future__ import annotations

import dataclasses
import typing as typ

if typ.TYPE_CHECKING:
    import datetime as dt


@dataclasses.dataclass(frozen=True, slots=True)
class GitHubIngestedEvent:
    """Raw event material ready for Bronze ingestion."""

    event_type: str
    source_event_id: str
    occurred_at: dt.datetime
    payload: dict[str, typ.Any]
