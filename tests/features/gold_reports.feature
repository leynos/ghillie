Feature: Gold report metadata

  Scenario: Repository report links scope and coverage
    Given an empty Bronze, Silver, and Gold store for reports
    When I create a repository report covering new GitHub events
    Then the Gold report records the repository scope and window
    And the Gold report coverage records the consumed events
    And the repository is linked to the Gold report

  Scenario: Project report stores machine summary
    Given an empty Bronze, Silver, and Gold store for reports
    When I create a project-level report
    Then the Gold report stores the project scope and summary
