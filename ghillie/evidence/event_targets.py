"""Extract event targets for evidence bundle selection."""

from __future__ import annotations

import dataclasses as dc
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from ghillie.silver.storage import EventFact


@dc.dataclass(slots=True)
class EventTargets:
    """Identifiers extracted from event facts for entity lookup."""

    commit_shas: set[str] = dc.field(default_factory=set)
    pull_request_ids: set[int] = dc.field(default_factory=set)
    issue_ids: set[int] = dc.field(default_factory=set)
    doc_change_keys: set[tuple[str, str]] = dc.field(default_factory=set)


class EventTargetExtractor:
    """Extract entity identifiers from event fact payloads."""

    @staticmethod
    def _coerce_int(value: typ.Any) -> int | None:  # noqa: ANN401
        """Coerce a payload value into an integer, if possible."""
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    def _handle_commit_event(
        self, targets: EventTargets, payload: dict[str, typ.Any]
    ) -> None:
        sha = payload.get("sha")
        if isinstance(sha, str):
            targets.commit_shas.add(sha)

    def _handle_pull_request_event(
        self, targets: EventTargets, payload: dict[str, typ.Any]
    ) -> None:
        pr_id = self._coerce_int(payload.get("id"))
        if pr_id is not None:
            targets.pull_request_ids.add(pr_id)

    def _handle_issue_event(
        self, targets: EventTargets, payload: dict[str, typ.Any]
    ) -> None:
        issue_id = self._coerce_int(payload.get("id"))
        if issue_id is not None:
            targets.issue_ids.add(issue_id)

    def _handle_doc_change_event(
        self, targets: EventTargets, payload: dict[str, typ.Any]
    ) -> None:
        commit_sha = payload.get("commit_sha")
        path = payload.get("path")
        if isinstance(commit_sha, str) and isinstance(path, str):
            targets.doc_change_keys.add((commit_sha, path))

    _EVENT_HANDLERS: typ.ClassVar[
        dict[
            str,
            cabc.Callable[
                [EventTargetExtractor, EventTargets, dict[str, typ.Any]], None
            ],
        ]
    ] = {
        "github.commit": _handle_commit_event,
        "github.pull_request": _handle_pull_request_event,
        "github.issue": _handle_issue_event,
        "github.doc_change": _handle_doc_change_event,
    }

    def extract(self, event_facts: list[EventFact]) -> EventTargets:
        """Extract entity identifiers from uncovered event facts."""
        targets = EventTargets()
        handlers = self._EVENT_HANDLERS
        for fact in event_facts:
            handler = handlers.get(fact.event_type)
            if handler is None:
                continue
            handler(self, targets, fact.payload or {})
        return targets
