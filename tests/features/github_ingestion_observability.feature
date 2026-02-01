Feature: GitHub ingestion observability
  Operators can monitor ingestion health through structured log events
  and query ingestion lag per repository.

  Scenario: Successful ingestion run emits completion metrics
    Given a managed repository "octo/reef" is registered for ingestion
    And the GitHub API returns activity for "octo/reef"
    When the GitHub ingestion worker runs for "octo/reef"
    Then an ingestion run completed log event is emitted for "octo/reef"
    And the log event contains the total events ingested

  Scenario: Failed ingestion run emits error details
    Given a managed repository "octo/reef" is registered for ingestion
    And the GitHub API returns an error for "octo/reef"
    When the GitHub ingestion worker fails for "octo/reef"
    Then an ingestion run failed log event is emitted for "octo/reef"
    And the log event includes the error category "transient"

  Scenario: Ingestion lag is computable for tracked repositories
    Given a managed repository "octo/reef" is registered for ingestion
    And the GitHub API returns activity for "octo/reef"
    When the GitHub ingestion worker runs for "octo/reef"
    Then ingestion lag metrics are available for "octo/reef"
    And the repository is not marked as stalled

  Scenario: Repository with no ingestion is marked as stalled
    Given a managed repository "octo/coral" is registered for ingestion
    And the GitHub API returns no activity for "octo/coral"
    And the repository "octo/coral" has never been successfully ingested
    Then the repository "octo/coral" is marked as stalled
