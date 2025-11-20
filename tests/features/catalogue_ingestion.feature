Feature: Catalogue validation

  Scenario: Example catalogue validates and retains planned components
    Given the catalogue example at "examples/wildside-catalogue.yaml"
    When I lint the catalogue with the built in validator
    Then the project "wildside" exposes a planned component "wildside-ingestion" without a repository
    And the component "wildside-core" depends on "wildside-engine"
    And the catalogue conforms to the JSON schema via pajv
