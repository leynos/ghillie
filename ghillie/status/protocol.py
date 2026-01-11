"""StatusModel protocol for LLM-backed summarization."""

from __future__ import annotations

import typing as typ

if typ.TYPE_CHECKING:
    from ghillie.evidence.models import RepositoryEvidenceBundle
    from ghillie.status.models import RepositoryStatusResult


@typ.runtime_checkable
class StatusModel(typ.Protocol):
    """Protocol for status generation from evidence bundles.

    Implementations transform evidence bundles into structured status reports
    with narrative summaries, status codes, highlights, risks, and next steps.
    Future implementations will include LLM backends (OpenAI, OpenRouter/Gemini)
    while this protocol keeps the interface vendor-agnostic.

    The protocol is runtime_checkable to support isinstance checks for
    dependency injection and testing scenarios.

    Examples
    --------
    >>> from ghillie.status import MockStatusModel, StatusModel
    >>> model: StatusModel = MockStatusModel()
    >>> isinstance(model, StatusModel)
    True

    """

    async def summarize_repository(
        self,
        evidence: RepositoryEvidenceBundle,
    ) -> RepositoryStatusResult:
        """Generate a status report from repository evidence.

        Parameters
        ----------
        evidence
            Complete evidence bundle for the repository and reporting window,
            including commits, pull requests, issues, documentation changes,
            work type groupings, and optional previous report context.

        Returns
        -------
        RepositoryStatusResult
            Structured status report with narrative summary, status code
            (on_track, at_risk, blocked, unknown), highlights, risks,
            and suggested next steps.

        Notes
        -----
        Implementations should:

        - Generate a concise summary mentioning the repository and key changes
        - Determine status based on evidence patterns and previous context
        - Extract highlights from feature work and significant changes
        - Identify risks from bug activity and previous unresolved issues
        - Suggest next steps based on current status and open items

        """
        ...
