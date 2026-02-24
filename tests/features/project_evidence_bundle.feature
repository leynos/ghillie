Feature: Project evidence bundle generation

  Project evidence bundles aggregate catalogue metadata, component lifecycle
  stages, repository report summaries, and component dependency graphs for
  project-level status reporting.

  Scenario: Build project evidence bundle for multi-component project
    Given an imported catalogue with a multi-component project
    When I build a project evidence bundle for "wildside"
    Then the bundle contains the project metadata
    And the bundle contains all four components
    And the bundle contains intra-project dependency edges

  Scenario: Bundle includes component with latest repository summary
    Given an imported catalogue with a multi-component project
    And a repository report exists for "leynos/wildside"
    When I build a project evidence bundle for "wildside"
    Then the component "wildside-core" has a repository summary
    And the repository summary status is "on_track"

  Scenario: Bundle includes planned component without repository
    Given an imported catalogue with a multi-component project
    When I build a project evidence bundle for "wildside"
    Then the component "wildside-ingestion" has no repository
    And the component "wildside-ingestion" has lifecycle "planned"

  Scenario: Bundle includes previous project report context
    Given an imported catalogue with a multi-component project
    And a previous project report exists for "wildside"
    When I build a project evidence bundle for "wildside"
    Then the bundle contains the previous project report summary
