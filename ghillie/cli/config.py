"""Configuration resolution for the packaged operator CLI."""

from __future__ import annotations

import dataclasses
import json
import tomllib
import typing as typ
from pathlib import Path
from urllib.parse import urlparse

OutputFormat = typ.Literal["table", "json", "yaml"]
CliLogLevel = typ.Literal["debug", "info", "warn", "error"]
ApiBaseUrlSource = typ.Literal["flag", "env", "profile", "state", "fallback"]

_OUTPUT_VALUES = {"table", "json", "yaml"}
_LOG_LEVEL_VALUES = {"debug", "info", "warn", "error"}
_DEFAULT_API_BASE_URL = "http://127.0.0.1:8080"
_DEFAULT_NON_INTERACTIVE = True
_DEFAULT_DRY_RUN = False


@dataclasses.dataclass(frozen=True, slots=True)
class GlobalOptions:
    """Raw root-global options captured before noun dispatch."""

    api_base_url: str | None = None
    auth_token: str | None = None
    output: OutputFormat | None = None
    log_level: CliLogLevel | None = None
    request_timeout_s: float | None = None
    non_interactive: bool | None = None
    dry_run: bool | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class ResolvedCliConfig:
    """Effective CLI configuration after precedence resolution."""

    api_base_url: str
    api_base_url_source: ApiBaseUrlSource
    auth_token: str | None
    output: OutputFormat
    log_level: CliLogLevel
    request_timeout_s: float
    non_interactive: bool
    dry_run: bool


def default_profile_path() -> Path:
    """Return the default CLI profile path."""
    return Path.home() / ".config" / "ghillie" / "cli.toml"


def default_state_path() -> Path:
    """Return the default persisted state path."""
    return Path.home() / ".config" / "ghillie" / "state.json"


@dataclasses.dataclass(frozen=True, slots=True)
class _ScalarFields:
    """Intermediate scalar configuration fields."""

    output: OutputFormat
    log_level: CliLogLevel
    request_timeout_s: float
    non_interactive: bool
    dry_run: bool


def _resolve_scalar_fields(
    options: GlobalOptions,
    environment: typ.Mapping[str, str],
    profile_global: typ.Mapping[str, object],
) -> _ScalarFields:
    """Resolve scalar configuration fields using documented precedence."""
    output = _coerce_output(
        _first_non_none(
            options.output,
            environment.get("GHILLIE_OUTPUT"),
            profile_global.get("output"),
            "table",
        )
    )
    log_level = _coerce_log_level(
        _first_non_none(
            options.log_level,
            environment.get("GHILLIE_LOG_LEVEL"),
            profile_global.get("log_level"),
            "info",
        )
    )
    request_timeout_s = _coerce_float(
        _first_non_none(
            options.request_timeout_s,
            environment.get("GHILLIE_REQUEST_TIMEOUT_S"),
            profile_global.get("request_timeout_s"),
            30.0,
        ),
        field="request_timeout_s",
    )
    non_interactive = _coerce_bool(
        _first_non_none(
            options.non_interactive,
            environment.get("GHILLIE_NON_INTERACTIVE"),
            profile_global.get("non_interactive"),
            _DEFAULT_NON_INTERACTIVE,
        ),
        field="non_interactive",
    )
    dry_run = _coerce_bool(
        _first_non_none(
            options.dry_run,
            environment.get("GHILLIE_DRY_RUN"),
            profile_global.get("dry_run"),
            _DEFAULT_DRY_RUN,
        ),
        field="dry_run",
    )
    return _ScalarFields(
        output=output,
        log_level=log_level,
        request_timeout_s=request_timeout_s,
        non_interactive=non_interactive,
        dry_run=dry_run,
    )


def resolve_cli_config(
    options: GlobalOptions,
    *,
    env: typ.Mapping[str, str] | None = None,
    profile_path: Path | None = None,
    state_path: Path | None = None,
) -> ResolvedCliConfig:
    """Resolve the effective CLI configuration using documented precedence."""
    environment = dict(env or {})
    profile = _load_profile(profile_path or default_profile_path())
    state = _load_state(state_path or default_state_path())
    global_section = profile.get("global", {})
    if not isinstance(global_section, dict):
        type_name = type(global_section).__name__
        msg = f"[global] section in profile must be a table, found {type_name}"
        raise TypeError(msg)
    profile_global = typ.cast("typ.Mapping[str, object]", global_section)

    api_base_url, api_base_url_source = _resolve_api_base_url(
        options,
        environment,
        profile_global,
        state,
    )
    auth_token = _resolve_auth_token(options, environment, profile_global)
    scalars = _resolve_scalar_fields(options, environment, profile_global)

    return ResolvedCliConfig(
        api_base_url=api_base_url,
        api_base_url_source=api_base_url_source,
        auth_token=auth_token,
        output=scalars.output,
        log_level=scalars.log_level,
        request_timeout_s=scalars.request_timeout_s,
        non_interactive=scalars.non_interactive,
        dry_run=scalars.dry_run,
    )


def _resolve_api_base_url(
    options: GlobalOptions,
    env: typ.Mapping[str, str],
    profile_global: typ.Mapping[str, object],
    state: typ.Mapping[str, object],
) -> tuple[str, ApiBaseUrlSource]:
    sources: tuple[tuple[ApiBaseUrlSource, object], ...] = (
        ("flag", options.api_base_url),
        ("env", env.get("GHILLIE_API_BASE_URL")),
        ("profile", profile_global.get("api_base_url")),
        ("state", state.get("api_base_url")),
        ("fallback", _DEFAULT_API_BASE_URL),
    )
    for source, value in sources:
        if value is None:
            continue
        return _validate_api_base_url(str(value)), source
    return _DEFAULT_API_BASE_URL, "fallback"


def _resolve_auth_token(
    options: GlobalOptions,
    env: typ.Mapping[str, str],
    profile_global: typ.Mapping[str, object],
) -> str | None:
    if options.auth_token:
        return options.auth_token
    if env_token := env.get("GHILLIE_AUTH_TOKEN"):
        return env_token
    auth_token_env = profile_global.get("auth_token_env")
    if isinstance(auth_token_env, str) and auth_token_env:
        return env.get(auth_token_env)
    return None


def _load_profile(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("rb") as file_obj:
        content = tomllib.load(file_obj)
    return content if isinstance(content, dict) else {}


def _load_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    content = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        type_name = type(content).__name__
        msg = f"state.json must contain a JSON object, found {type_name}"
        raise TypeError(msg)
    return content


def _validate_api_base_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        msg = f"api_base_url must be an absolute HTTP(S) URL: {value}"
        raise ValueError(msg)
    return value


def _coerce_output(value: object) -> OutputFormat:
    text = str(value)
    if text not in _OUTPUT_VALUES:
        msg = f"output must be one of: {', '.join(sorted(_OUTPUT_VALUES))}"
        raise ValueError(msg)
    return typ.cast("OutputFormat", text)


def _coerce_log_level(value: object) -> CliLogLevel:
    text = str(value)
    if text not in _LOG_LEVEL_VALUES:
        msg = f"log_level must be one of: {', '.join(sorted(_LOG_LEVEL_VALUES))}"
        raise ValueError(msg)
    return typ.cast("CliLogLevel", text)


def _coerce_float(value: object, *, field: str) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        msg = f"{field} must be a float"
        raise ValueError(msg) from exc


def _coerce_bool(value: object, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    msg = f"{field} must be a boolean"
    raise ValueError(msg)


def _first_non_none(*values: object) -> object:
    for value in values:
        if value is not None:
            return value
    msg = "Expected at least one value"
    raise ValueError(msg)
