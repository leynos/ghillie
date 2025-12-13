Feature: GitHub incremental ingestion
  The ingestion worker polls GitHub for new activity per managed repository
  and appends the results to the Bronze raw event store.

  Scenario: New GitHub activity is captured into raw events
    Given a managed repository "octo/reef" is registered for ingestion
    And the GitHub API returns activity for "octo/reef"
    When the GitHub ingestion worker runs for "octo/reef"
    Then Bronze raw events exist for "octo/reef"
    When the GitHub ingestion worker runs again for "octo/reef"
    Then no additional Bronze raw events are written for "octo/reef"

