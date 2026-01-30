@status @configuration
Feature: Status model backend selection
  As an operator
  I want to configure which status model backend is used
  So that I can run the same reporting job against different model backends

  Background:
    Given the environment is clean

  Scenario: Select mock backend via environment
    Given GHILLIE_STATUS_MODEL_BACKEND is set to "mock"
    When I create a status model from environment configuration
    Then the model is a MockStatusModel

  Scenario: Select OpenAI backend via environment
    Given GHILLIE_STATUS_MODEL_BACKEND is set to "openai"
    And GHILLIE_OPENAI_API_KEY is set to "test-key-123"
    When I create a status model from environment configuration
    Then the model is an OpenAIStatusModel

  Scenario: Configure OpenAI temperature via environment
    Given GHILLIE_STATUS_MODEL_BACKEND is set to "openai"
    And GHILLIE_OPENAI_API_KEY is set to "test-key"
    And GHILLIE_OPENAI_TEMPERATURE is set to "0.7"
    When I create a status model from environment configuration
    Then the model uses temperature 0.7

  Scenario: Configure OpenAI max_tokens via environment
    Given GHILLIE_STATUS_MODEL_BACKEND is set to "openai"
    And GHILLIE_OPENAI_API_KEY is set to "test-key"
    And GHILLIE_OPENAI_MAX_TOKENS is set to "4096"
    When I create a status model from environment configuration
    Then the model uses max_tokens 4096

  Scenario: Error when backend not specified
    When I attempt to create a status model from environment configuration
    Then a StatusModelConfigError is raised
    And the error message mentions "GHILLIE_STATUS_MODEL_BACKEND"

  Scenario: Error when backend is invalid
    Given GHILLIE_STATUS_MODEL_BACKEND is set to "unknown-backend"
    When I attempt to create a status model from environment configuration
    Then a StatusModelConfigError is raised
    And the error message lists valid backend options
