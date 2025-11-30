Feature: Bronze raw event store

  Scenario: GitHub events are captured immutably and transform idempotently
    Given an empty Bronze and Silver store
    And a raw GitHub push event payload
    When I ingest the raw event twice
    Then the Bronze store contains exactly one raw event row
    And the stored payload matches the submitted payload
    When I transform pending raw events
    And I transform pending raw events again
    Then a single event fact exists for the raw event
    And the event fact payload matches the Bronze payload
