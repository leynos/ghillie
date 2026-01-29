"""Step definitions for model selection feature tests."""

from __future__ import annotations

import os
import typing as typ
from unittest import mock

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ghillie.status.errors import StatusModelConfigError

if typ.TYPE_CHECKING:
    from ghillie.status.openai_client import OpenAIStatusModel
    from ghillie.status.protocol import StatusModel

# Register scenarios from the feature file
scenarios("../model_selection.feature")


class ModelSelectionContext(typ.TypedDict, total=False):
    """Context shared between BDD steps."""

    env_vars: dict[str, str]
    model: StatusModel
    error: Exception | None
    env_patcher: typ.Any  # mock._patch_dict type


@pytest.fixture
def model_context() -> ModelSelectionContext:
    """Provide shared context for model selection steps."""
    return ModelSelectionContext(env_vars={})


@given("the environment is clean")
def given_environment_clean(model_context: ModelSelectionContext) -> None:
    """Ensure environment starts clean for each scenario."""
    model_context["env_vars"] = {}
    model_context["error"] = None


@given(parsers.parse('GHILLIE_STATUS_MODEL_BACKEND is set to "{value}"'))
def given_backend_env_var(model_context: ModelSelectionContext, value: str) -> None:
    """Set GHILLIE_STATUS_MODEL_BACKEND environment variable."""
    model_context["env_vars"]["GHILLIE_STATUS_MODEL_BACKEND"] = value


@given(parsers.parse('GHILLIE_OPENAI_API_KEY is set to "{value}"'))
def given_api_key_env_var(model_context: ModelSelectionContext, value: str) -> None:
    """Set GHILLIE_OPENAI_API_KEY environment variable."""
    model_context["env_vars"]["GHILLIE_OPENAI_API_KEY"] = value


@given(parsers.parse('GHILLIE_OPENAI_TEMPERATURE is set to "{value}"'))
def given_temperature_env_var(model_context: ModelSelectionContext, value: str) -> None:
    """Set GHILLIE_OPENAI_TEMPERATURE environment variable."""
    model_context["env_vars"]["GHILLIE_OPENAI_TEMPERATURE"] = value


@given(parsers.parse('GHILLIE_OPENAI_MAX_TOKENS is set to "{value}"'))
def given_max_tokens_env_var(model_context: ModelSelectionContext, value: str) -> None:
    """Set GHILLIE_OPENAI_MAX_TOKENS environment variable."""
    model_context["env_vars"]["GHILLIE_OPENAI_MAX_TOKENS"] = value


@when("I create a status model from environment configuration")
def when_create_status_model(model_context: ModelSelectionContext) -> None:
    """Create status model from environment configuration."""
    from ghillie.status.factory import create_status_model

    with mock.patch.dict(os.environ, model_context["env_vars"], clear=True):
        model_context["model"] = create_status_model()


@when("I attempt to create a status model from environment configuration")
def when_attempt_create_status_model(model_context: ModelSelectionContext) -> None:
    """Attempt to create status model, capturing any errors."""
    from ghillie.status.factory import create_status_model

    with mock.patch.dict(os.environ, model_context["env_vars"], clear=True):
        try:
            model_context["model"] = create_status_model()
        except StatusModelConfigError as e:
            model_context["error"] = e


@then("the model is a MockStatusModel")
def then_model_is_mock(model_context: ModelSelectionContext) -> None:
    """Verify the model is a MockStatusModel instance."""
    from ghillie.status.mock import MockStatusModel

    model = model_context.get("model")
    assert model is not None, "Expected a model but got None"
    assert isinstance(model, MockStatusModel), (
        f"Expected MockStatusModel but got {type(model).__name__}"
    )


@then("the model is an OpenAIStatusModel")
def then_model_is_openai(model_context: ModelSelectionContext) -> None:
    """Verify the model is an OpenAIStatusModel instance."""
    from ghillie.status.openai_client import OpenAIStatusModel

    model = model_context.get("model")
    assert model is not None, "Expected a model but got None"
    assert isinstance(model, OpenAIStatusModel), (
        f"Expected OpenAIStatusModel but got {type(model).__name__}"
    )


def _verify_openai_model(model_context: ModelSelectionContext) -> OpenAIStatusModel:
    """Verify and return the model as an OpenAIStatusModel.

    Parameters
    ----------
    model_context
        The BDD step context containing the model.

    Returns
    -------
    OpenAIStatusModel
        The validated OpenAI status model instance.

    Raises
    ------
    AssertionError
        If the model is None or not an OpenAIStatusModel instance.

    """
    from ghillie.status.openai_client import OpenAIStatusModel

    model = model_context.get("model")
    assert model is not None, "Expected a model but got None"
    assert isinstance(model, OpenAIStatusModel), (
        f"Expected OpenAIStatusModel but got {type(model).__name__}"
    )
    return model


@then(parsers.parse("the model uses temperature {temperature:f}"))
def then_model_uses_temperature(
    model_context: ModelSelectionContext, temperature: float
) -> None:
    """Verify the model uses the specified temperature."""
    model = _verify_openai_model(model_context)
    assert model._config.temperature == temperature, (
        f"Expected temperature {temperature}, got {model._config.temperature}"
    )


@then(parsers.parse("the model uses max_tokens {max_tokens:d}"))
def then_model_uses_max_tokens(
    model_context: ModelSelectionContext, max_tokens: int
) -> None:
    """Verify the model uses the specified max_tokens."""
    model = _verify_openai_model(model_context)
    assert model._config.max_tokens == max_tokens, (
        f"Expected max_tokens {max_tokens}, got {model._config.max_tokens}"
    )


@then("a StatusModelConfigError is raised")
def then_status_model_config_error_raised(
    model_context: ModelSelectionContext,
) -> None:
    """Verify a StatusModelConfigError was raised."""
    error = model_context.get("error")
    assert error is not None, "Expected an error but none was raised"
    assert isinstance(error, StatusModelConfigError), (
        f"Expected StatusModelConfigError but got {type(error).__name__}: {error}"
    )


@then(parsers.parse('the error message mentions "{text}"'))
def then_error_message_mentions(
    model_context: ModelSelectionContext, text: str
) -> None:
    """Verify error message contains the specified text."""
    error = model_context.get("error")
    assert error is not None, "Expected an error but none was raised"
    assert text in str(error), f"Expected '{text}' in error message, got: {error}"


@then("the error message lists valid backend options")
def then_error_lists_valid_options(model_context: ModelSelectionContext) -> None:
    """Verify error message lists valid backend options."""
    error = model_context.get("error")
    assert error is not None, "Expected an error but none was raised"
    error_msg = str(error).lower()
    assert "mock" in error_msg, f"Expected 'mock' in error message, got: {error}"
    assert "openai" in error_msg, f"Expected 'openai' in error message, got: {error}"
