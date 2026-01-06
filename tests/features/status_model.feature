Feature: Status model summarization

  The status model transforms repository evidence bundles into structured
  status reports with narrative summaries, status codes, highlights, risks,
  and suggested next steps. The mock implementation uses deterministic
  heuristics for testing without LLM dependencies.

  Scenario: Generate status for repository with normal activity
    Given a repository "octo/reef" with feature activity
    And an evidence bundle for the reporting window
    When I summarize the evidence bundle using the mock status model
    Then the status result has status "on_track"
    And the status result summary mentions the repository slug
    And the status result contains highlights

  Scenario: Generate status for repository at risk from previous report
    Given a repository "octo/reef" with a previous report at risk
    And an evidence bundle with previous report context
    When I summarize the evidence bundle using the mock status model
    Then the status result has status "at_risk"
    And the status result risks include ongoing risks from previous report

  Scenario: Generate status for repository with no activity
    Given a repository "octo/reef" with no activity in window
    And an empty evidence bundle
    When I summarize the evidence bundle using the mock status model
    Then the status result has status "unknown"
    And the status result summary indicates no activity
