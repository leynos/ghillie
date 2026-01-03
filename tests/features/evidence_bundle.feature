Feature: Evidence bundle generation

  Evidence bundles aggregate repository activity within a reporting window,
  ready for LLM summarisation. Bundles include commits, pull requests, issues,
  documentation changes, and work type groupings.

  Scenario: Build evidence bundle for repository with activity
    Given an empty store for evidence bundles
    And a repository "octo/reef" with ingested GitHub events
    When I build an evidence bundle for "octo/reef" for the reporting window
    Then the bundle contains the repository metadata
    And the bundle contains commits within the window
    And the bundle contains pull requests within the window
    And the bundle contains issues within the window
    And the bundle contains documentation changes within the window
    And the bundle contains work type groupings

  Scenario: Bundle includes previous report context
    Given an empty store for evidence bundles
    And a repository "octo/reef" with a previous report
    When I build an evidence bundle for the next window
    Then the bundle contains the previous report summary
    And the previous report summary includes status and highlights

  Scenario: Work type classification from labels
    Given an empty store for evidence bundles
    And a repository "octo/reef" with a pull request labelled "bug"
    When I build an evidence bundle for "octo/reef" for the reporting window
    Then the pull request is classified as "bug"

  Scenario: Work type classification from title patterns
    Given an empty store for evidence bundles
    And a repository "octo/reef" with a commit message "fix: resolve login issue"
    When I build an evidence bundle for "octo/reef" for the reporting window
    Then the commit is classified as "bug"

  Scenario: Bundle excludes events covered by repository reports
    Given an empty store for evidence bundles
    And a repository "octo/reef" with ingested GitHub events
    And a repository report covers the commit event
    When I build an evidence bundle for "octo/reef" for the reporting window
    Then the bundle excludes the covered commit event

  Scenario: Project report coverage does not affect repository bundles
    Given an empty store for evidence bundles
    And a repository "octo/reef" with ingested GitHub events
    And a project report covers the commit event
    When I build an evidence bundle for "octo/reef" for the reporting window
    Then the bundle still includes the covered commit event
