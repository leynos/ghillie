@llm @integration
Feature: LLM integration for status generation
  As a Ghillie user
  I want status reports generated using an LLM
  So that I get intelligent summaries of repository activity

  Background:
    Given a repository with evidence bundle

  Scenario: Generate status using OpenAI model
    Given the LLM service is available
    When I request a status report using the OpenAI model
    Then I receive a structured status result
    And the result contains a summary mentioning the repository
    And the result contains a valid status code

  Scenario: Handle API timeout gracefully
    Given the LLM service is configured to timeout
    When I request a status report using the OpenAI model
    Then an API timeout error is raised
    And the error message indicates a timeout occurred

  Scenario: Handle malformed response gracefully
    Given the LLM service returns invalid JSON
    When I request a status report using the OpenAI model
    Then a response shape error is raised
    And the error message indicates invalid JSON
