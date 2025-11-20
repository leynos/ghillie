Feature: Catalogue validation

  Scenario: Example catalogue validates and retains planned components
    Given the catalogue example at "examples/wildside-catalogue.yaml"
    When I lint the catalogue with the built in validator
    Then the project "wildside" exposes a planned component "wildside-ingestion" without a repository
    And the component "wildside-core" depends on "wildside-engine"
    And the catalogue conforms to the JSON schema via pajv

  Scenario: Duplicate component keys are rejected
    Given the catalogue example at "tests/fixtures/catalogues/duplicate-component.yaml"
    When I lint the catalogue expecting failure
    Then validation reports contain "duplicate component key"

  Scenario: Invalid slug format is rejected
    Given the catalogue example at "tests/fixtures/catalogues/invalid-slug.yaml"
    When I lint the catalogue expecting failure
    Then validation reports contain "slug"
