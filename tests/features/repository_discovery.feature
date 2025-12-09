Feature: Repository discovery and registration

  The repository registry bridges the catalogue-defined repositories with the
  Silver layer ingestion pipeline, enabling controlled GitHub event ingestion.

  Scenario: Catalogue repositories are registered for ingestion
    Given a fresh database
    And the catalogue at "examples/wildside-catalogue.yaml" is imported
    When the repository registry syncs from catalogue
    Then the Silver layer contains repository "leynos/wildside"
    And repository "leynos/wildside" has ingestion enabled
    And repository "leynos/wildside" has documentation paths from catalogue

  Scenario: Removing a repository from catalogue disables ingestion
    Given a fresh database
    And the catalogue at "examples/wildside-catalogue.yaml" is imported
    And the repository registry syncs from catalogue
    When repository "leynos/wildside-engine" is removed from catalogue
    And the repository registry syncs from catalogue
    Then repository "leynos/wildside-engine" has ingestion disabled
    And repository "leynos/wildside-engine" still exists in Silver

  Scenario: Ingestion can be toggled per repository
    Given a fresh database
    And the catalogue at "examples/wildside-catalogue.yaml" is imported
    And the repository registry syncs from catalogue
    When ingestion is disabled for "leynos/wildside"
    Then repository "leynos/wildside" has ingestion disabled
    When ingestion is enabled for "leynos/wildside"
    Then repository "leynos/wildside" has ingestion enabled

  Scenario: Listing active repositories for ingestion
    Given a fresh database
    And the catalogue at "examples/wildside-catalogue.yaml" is imported
    And the repository registry syncs from catalogue
    And ingestion is disabled for "leynos/wildside-engine"
    When listing active repositories for ingestion
    Then the result includes "leynos/wildside"
    And the result excludes "leynos/wildside-engine"
