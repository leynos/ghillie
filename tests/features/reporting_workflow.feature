Feature: Scheduled reporting workflow

  The reporting workflow orchestrates evidence bundle construction,
  status model invocation, and report persistence in the Gold layer.

  Scenario: Generate report for repository with events
    Given an empty store with a repository containing events
    When I run the reporting service for the repository
    Then a Gold report is created with the evidence bundle
    And the report links to the consumed event facts

  Scenario: Window computation follows previous report
    Given a repository with a previous report ending on July 7th
    When I compute the next reporting window as of July 14th
    Then the window starts on July 7th and ends on July 14th

  Scenario: Skip report when no events in window
    Given an empty store with a repository but no events
    When I run the reporting service for the repository
    Then no report is generated
