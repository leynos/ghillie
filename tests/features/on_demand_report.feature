Feature: On-demand report generation via HTTP API

  Operators can trigger report generation for a specific repository
  through the HTTP API endpoint. The endpoint reuses the same pipeline
  as scheduled reports.

  Scenario: Generate report for a repository with events
    Given a running API with a repository that has events
    When I POST to /reports/repositories/{owner}/{name}
    Then the response status is 200
    And the response body contains report metadata

  Scenario: Return 204 when no events in window
    Given a running API with a repository but no events
    When I POST to /reports/repositories/{owner}/{name}
    Then the response status is 204

  Scenario: Return 404 for unknown repository
    Given a running API with no repositories
    When I POST to /reports/repositories/unknown/repo
    Then the response status is 404
    And the response body contains an error description
