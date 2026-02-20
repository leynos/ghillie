"""OpenAI-compatible implementation of StatusModel protocol."""

from __future__ import annotations

import json
import typing as typ

import httpx
import msgspec

from ghillie.evidence.models import ReportStatus, RepositoryEvidenceBundle
from ghillie.status.errors import (
    OpenAIAPIError,
    OpenAIConfigError,
    OpenAIResponseShapeError,
)
from ghillie.status.metrics import ModelInvocationMetrics
from ghillie.status.models import RepositoryStatusResult
from ghillie.status.prompts import SYSTEM_PROMPT, build_user_prompt

if typ.TYPE_CHECKING:
    from ghillie.status.config import OpenAIStatusModelConfig

_HTTP_ERROR_STATUS_THRESHOLD = 400
_HTTP_RATE_LIMITED = 429


def _to_int_or_none(value: object) -> int | None:
    """Return ``int`` for integer values, else ``None``."""
    if isinstance(value, int):
        return value
    return None


def _get_retry_after(response: httpx.Response) -> int | None:
    """Extract Retry-After header value if present and numeric."""
    retry_after = response.headers.get("Retry-After")
    if retry_after and retry_after.isdigit():
        return int(retry_after)
    return None


def _get_nested(data: dict[str, object], *keys: str) -> object:
    """Traverse nested dict path, returning None for missing keys."""
    current: object = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current_dict = typ.cast("dict[str, object]", current)
        current = current_dict.get(key)
    return current


class LLMStatusResponse(msgspec.Struct, kw_only=True):
    """Parsed response from LLM for status report.

    Attributes
    ----------
    status
        Status string from the LLM (on_track, at_risk, blocked, unknown).
    summary
        Narrative summary of repository status.
    highlights
        Key achievements (up to 5 items).
    risks
        Identified risks (up to 5 items).
    next_steps
        Suggested actions (up to 5 items).

    """

    status: str
    summary: str
    highlights: list[str] = msgspec.field(default_factory=list)
    risks: list[str] = msgspec.field(default_factory=list)
    next_steps: list[str] = msgspec.field(default_factory=list)


def _parse_status(status_str: str) -> ReportStatus:
    """Parse status string to ReportStatus enum.

    Parameters
    ----------
    status_str
        Status string from LLM response.

    Returns
    -------
    ReportStatus
        Parsed enum value, or UNKNOWN if unrecognised.

    """
    normalised = status_str.lower().replace("-", "_")
    try:
        return ReportStatus(normalised)
    except ValueError:
        return ReportStatus.UNKNOWN


class OpenAIStatusModel:
    """OpenAI-compatible implementation of StatusModel protocol.

    This implementation calls an OpenAI-compatible chat completions endpoint
    to generate repository status reports from evidence bundles.

    Parameters
    ----------
    config
        Configuration for the OpenAI API client.
    http_client
        Optional httpx.AsyncClient for testing. If not provided,
        the instance creates and owns its own client.

    Examples
    --------
    >>> import asyncio
    >>> from ghillie.status import OpenAIStatusModel, OpenAIStatusModelConfig
    >>> config = OpenAIStatusModelConfig(api_key="sk-...")
    >>> model = OpenAIStatusModel(config)
    >>> # result = asyncio.run(model.summarize_repository(evidence))
    >>> asyncio.run(model.aclose())

    """

    def __init__(
        self,
        config: OpenAIStatusModelConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialise the client with configuration."""
        if not config.api_key.strip():
            raise OpenAIConfigError.empty_api_key()

        self._config = config
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            timeout=config.timeout_s,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
        )
        self._last_invocation_metrics: ModelInvocationMetrics | None = None

    @property
    def config(self) -> OpenAIStatusModelConfig:
        """Read-only access to the client configuration.

        Returns
        -------
        OpenAIStatusModelConfig
            The configuration used to initialise this client.

        """
        return self._config

    @property
    def last_invocation_metrics(self) -> ModelInvocationMetrics | None:
        """Return metrics captured from the most recent invocation."""
        return self._last_invocation_metrics

    async def aclose(self) -> None:
        """Close any owned HTTP resources."""
        if self._owns_client:
            await self._client.aclose()

    async def summarize_repository(
        self,
        evidence: RepositoryEvidenceBundle,
    ) -> RepositoryStatusResult:
        """Generate a status report from repository evidence.

        Parameters
        ----------
        evidence
            Complete evidence bundle for the repository and reporting window.

        Returns
        -------
        RepositoryStatusResult
            Structured status report with narrative summary, status code,
            highlights, risks, and suggested next steps.

        Raises
        ------
        OpenAIAPIError
            If the API returns an error response or times out.
        OpenAIResponseShapeError
            If the response is missing expected fields or contains invalid JSON.

        """
        user_prompt = build_user_prompt(evidence)
        response_content = await self._call_chat_completion(user_prompt)
        parsed = self._parse_response(response_content)
        return self._build_result(parsed)

    async def _call_chat_completion(self, user_prompt: str) -> str:
        """Call the chat completions endpoint and return assistant content.

        Parameters
        ----------
        user_prompt
            User message content for the completion request.

        Returns
        -------
        str
            Assistant message content from the response.

        Raises
        ------
        OpenAIAPIError
            If the request fails or returns an error status.

        """
        payload = self._build_payload(user_prompt)
        response = await self._send_request(payload)
        self._check_response_errors(response)
        return self._parse_json_response(response)

    def _build_payload(self, user_prompt: str) -> dict[str, object]:
        """Construct the request payload for chat completion.

        Parameters
        ----------
        user_prompt
            User message content for the completion request.

        Returns
        -------
        dict[str, object]
            Request payload dictionary for the API call.

        """
        return {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "response_format": {"type": "json_object"},
        }

    async def _send_request(
        self,
        payload: dict[str, object],
    ) -> httpx.Response:
        """Perform HTTP POST request to the chat completions endpoint.

        Parameters
        ----------
        payload
            Request payload dictionary for the API call.

        Returns
        -------
        httpx.Response
            Raw HTTP response from the API.

        Raises
        ------
        OpenAIAPIError
            If a timeout or network error occurs.

        """
        try:
            return await self._client.post(
                self._config.endpoint,
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise OpenAIAPIError.timeout() from exc
        except httpx.RequestError as exc:
            raise OpenAIAPIError.network_error(str(exc)) from exc

    def _check_response_errors(self, response: httpx.Response) -> None:
        """Validate HTTP response status code.

        Parameters
        ----------
        response
            HTTP response to validate.

        Raises
        ------
        OpenAIAPIError
            If the response indicates rate limiting or other HTTP error.

        """
        if response.status_code == _HTTP_RATE_LIMITED:
            raise OpenAIAPIError.rate_limited(_get_retry_after(response))

        if response.status_code >= _HTTP_ERROR_STATUS_THRESHOLD:
            raise OpenAIAPIError.http_error(response.status_code)

    def _parse_json_response(self, response: httpx.Response) -> str:
        """Parse JSON response and extract assistant message content.

        Parameters
        ----------
        response
            HTTP response containing JSON body.

        Returns
        -------
        str
            Content string from the assistant message.

        Raises
        ------
        OpenAIResponseShapeError
            If the response is not valid JSON or missing expected fields.

        """
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise OpenAIResponseShapeError.invalid_json(response.text) from exc
        self._last_invocation_metrics = self._extract_usage_metrics(data)
        return self._extract_content(data)

    def _extract_usage_metrics(
        self,
        data: dict[str, object],
    ) -> ModelInvocationMetrics:
        """Extract token usage metrics from the API response payload."""
        usage = data.get("usage")
        if not isinstance(usage, dict):
            return ModelInvocationMetrics()

        usage_dict = typ.cast("dict[str, object]", usage)
        return ModelInvocationMetrics(
            prompt_tokens=_to_int_or_none(usage_dict.get("prompt_tokens")),
            completion_tokens=_to_int_or_none(usage_dict.get("completion_tokens")),
            total_tokens=_to_int_or_none(usage_dict.get("total_tokens")),
        )

    def _extract_content(self, data: dict[str, object]) -> str:
        """Extract assistant message content from API response.

        Parameters
        ----------
        data
            Parsed JSON response from the API.

        Returns
        -------
        str
            Content string from the assistant message.

        Raises
        ------
        OpenAIResponseShapeError
            If the response is missing expected fields.

        """
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise OpenAIResponseShapeError.missing("choices")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise OpenAIResponseShapeError.missing("choices[0]")

        first_choice_dict = typ.cast("dict[str, object]", first_choice)
        content = _get_nested(first_choice_dict, "message", "content")
        if not isinstance(content, str):
            raise OpenAIResponseShapeError.missing("choices[0].message.content")

        return content

    def _parse_response(self, content: str) -> LLMStatusResponse:
        """Parse JSON response content into typed structure.

        Parameters
        ----------
        content
            JSON string from the assistant message.

        Returns
        -------
        LLMStatusResponse
            Parsed response structure.

        Raises
        ------
        OpenAIResponseShapeError
            If the content is not valid JSON or missing required fields.

        """
        try:
            return msgspec.json.decode(content, type=LLMStatusResponse)
        except msgspec.DecodeError as exc:
            raise OpenAIResponseShapeError.invalid_json(content) from exc

    def _build_result(self, parsed: LLMStatusResponse) -> RepositoryStatusResult:
        """Convert parsed LLM response to RepositoryStatusResult.

        Parameters
        ----------
        parsed
            Parsed LLM response structure.

        Returns
        -------
        RepositoryStatusResult
            Structured status result for storage.

        """
        status = _parse_status(parsed.status)

        return RepositoryStatusResult(
            summary=parsed.summary,
            status=status,
            highlights=tuple(parsed.highlights[:5]),
            risks=tuple(parsed.risks[:5]),
            next_steps=tuple(parsed.next_steps[:5]),
        )
