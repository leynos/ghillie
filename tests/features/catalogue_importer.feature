Feature: Catalogue importer reconciliation

  Scenario: Importing a catalogue commit populates the estate idempotently
    Given a fresh catalogue database
    And the importer uses catalogue at "examples/wildside-catalogue.yaml"
    When the catalogue importer processes commit "abc123"
    Then the repository table contains "leynos/wildside" on branch "main"
    And the component graph includes "wildside-core" depends_on "wildside-engine"
    And the catalogue row counts are 2 projects, 7 components, 6 repositories
    And project "wildside" retains catalogue configuration
    And repository "leynos/wildside" exposes documentation paths
    And repository "leynos/wildside-engine" has no documentation paths
    When the catalogue importer processes commit "abc123" again
    Then no catalogue rows are duplicated
