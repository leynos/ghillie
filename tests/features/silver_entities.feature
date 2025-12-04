Feature: Silver entity tables

  Scenario: GitHub entity events hydrate Silver tables
    Given an empty Bronze and Silver store for Silver entities
    When I ingest GitHub entity events for "octo/reef"
    And I transform pending raw events for Silver entities
    Then the Silver repositories table contains "octo/reef"
    And the Silver commits table includes commit "abc123" for "octo/reef"
    And the Silver pull requests table includes number 17 for "octo/reef"
    And the Silver issues table includes number 5 for "octo/reef"
    And the Silver documentation changes table includes "docs/roadmap.md" for commit "abc123"

  Scenario: GitHub entity events are idempotent on replay
    Given an empty Bronze and Silver store for Silver entities
    When I ingest GitHub entity events for "octo/reef"
    And I transform pending raw events for Silver entities
    And I ingest GitHub entity events for "octo/reef"
    And I transform pending raw events for Silver entities
    Then the Silver entity counts do not increase
    And the Silver entity state and metadata remain unchanged
