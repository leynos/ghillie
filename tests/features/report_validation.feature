Feature: Report validation and retry workflow

  Generated reports are validated for basic correctness before
  persistence. Invalid reports trigger retries; exhausted retries
  create a human-review marker and surface the failure through the
  API as HTTP 422.

  Scenario: Retry succeeds after initial validation failure
    Given a repository with events and a status model that fails then succeeds
    When I run the reporting service for the repository
    Then a valid Gold report is persisted
    And the status model was invoked twice

  Scenario: Mark for human review after retries exhausted
    Given a repository with events and a status model that always fails validation
    When I run the reporting service expecting failure
    Then a human-review marker is created for the repository
    And no report is persisted

  Scenario: API returns 422 for validation failure
    Given a running API with a status model that always fails validation
    When I POST to trigger report generation
    Then the response status is 422
    And the response body contains validation issues and a review reference
