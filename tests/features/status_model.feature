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

  Scenario: Generate status for repository with bug-heavy activity
    Given a repository "octo/reef" with more bugs than features
    And an evidence bundle with bug-heavy activity
    When I summarize the evidence bundle using the mock status model
    Then the status result has status "at_risk"

  Scenario: AT_RISK status includes mitigation next step
    Given a repository "octo/reef" with a previous report at risk
    And an evidence bundle with previous report context
    When I summarize the evidence bundle using the mock status model
    Then the status result has status "at_risk"
    And the next steps include addressing risks

  Scenario: UNKNOWN status includes investigation next step
    Given a repository "octo/reef" with no activity in window
    And an empty evidence bundle
    When I summarize the evidence bundle using the mock status model
    Then the status result has status "unknown"
    And the next steps include investigating activity

  Scenario: Open PRs trigger review next step
    Given a repository "octo/reef" with open pull requests
    And an evidence bundle with open PRs
    When I summarize the evidence bundle using the mock status model
    Then the next steps include reviewing open PRs

  Scenario: Open issues trigger triage next step
    Given a repository "octo/reef" with open issues
    And an evidence bundle with open issues
    When I summarize the evidence bundle using the mock status model
    Then the next steps include triaging open issues
