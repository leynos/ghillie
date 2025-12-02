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

  Scenario: Ingesting a GitHub event with a naive occurred_at fails
    Given an empty Bronze and Silver store
    And a raw GitHub push event payload with a naive occurred_at
    When I ingest the raw event expecting a timezone error
    Then a timezone error is raised during ingestion

  Scenario: EventFact mismatch marks the raw event failed without duplicates
    Given an empty Bronze and Silver store
    And a raw GitHub push event payload
    When I ingest the raw event twice
    And I transform pending raw events
    And I corrupt the raw event payload to differ from its event fact
    And I transform pending raw events
    Then the raw event is marked failed with a payload mismatch
    And the EventFact count remains one
