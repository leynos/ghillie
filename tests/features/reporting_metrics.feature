Feature: Reporting metrics and costs

  Operators can inspect report generation cost and latency signals for
  repository reporting runs.

  Scenario: Report generation captures latency and token usage
    Given an empty store with a repository containing events for metrics
    When I generate a repository report for metrics tracking
    Then the generated report has model latency recorded
    And the generated report has token usage recorded

  Scenario: Operator can query aggregate reporting metrics for a period
    Given multiple reports have been generated in the current period
    When I query reporting metrics for the current period
    Then the snapshot includes total reports generated
    And the snapshot includes average model latency
    And the snapshot includes total token usage
