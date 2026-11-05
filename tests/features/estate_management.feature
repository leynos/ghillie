Feature: Estate management through the operator CLI and HTTP API

  Background:
    Given a Ghillie service backed by an empty database

  Scenario: Operator imports a catalogue for a new estate
    When the operator imports "examples/wildside-catalogue.yaml" into estate "demo" at commit "c1"
    Then the command exits with code 0
    And the output reports at least 1 repository created
    And "estate list" lists the estate "demo"

  Scenario: Re-importing the same commit is skipped
    Given the operator has imported "examples/wildside-catalogue.yaml" into estate "demo" at commit "c1"
    When the operator imports "examples/wildside-catalogue.yaml" into estate "demo" at commit "c1" with JSON output
    Then the command exits with code 0
    And the JSON output field "skipped" is true
    And the JSON output field "skipped_reason" is "commit_already_imported"

  Scenario: A dry-run import changes nothing
    When the operator dry-run imports "examples/wildside-catalogue.yaml" into estate "demo" at commit "c1"
    Then the command exits with code 0
    And "estate list" lists no estates

  Scenario: Operator syncs the registry and lists repositories
    Given the operator has imported "examples/wildside-catalogue.yaml" into estate "demo" at commit "c1"
    When the operator runs "estate sync --estate-key demo"
    Then the command exits with code 0
    And "estate repo list --estate-key demo --active" lists "leynos/wildside"

  Scenario: Operator disables ingestion and it survives a re-sync
    Given estate "demo" has been imported at commit "c1" and synced
    When the operator runs "estate repo set --owner leynos --name wildside --ingestion-disabled"
    And the operator imports estate "demo" at commit "c2" and syncs it
    Then "estate repo list --estate-key demo --inactive" lists "leynos/wildside"
    And the last sync reported "leynos/wildside" as left disabled

  Scenario: Syncing an unknown estate fails with a structured error
    When the operator runs "--output json estate sync --estate-key missing"
    Then the command exits with code 3
    And the error code is "estate_not_found"
    And the error hint mentions "estate list"

  Scenario: Importing an invalid catalogue is rejected
    Given a catalogue file containing "projects: 42"
    When the operator imports that file into estate "demo" at commit "bad"
    Then the command exits with code 3
    And the error code is "catalogue_invalid"

  Scenario: Toggling an unknown repository fails
    When the operator runs "estate repo set --owner nobody --name nothing --ingestion-enabled"
    Then the command exits with code 3
    And the error code is "repository_not_found"

  Scenario: Invalid pagination is rejected before any request
    When the operator runs "estate repo list --estate-key demo --limit 0"
    Then the command exits with code 2
    And no HTTP request was sent