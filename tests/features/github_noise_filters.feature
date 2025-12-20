Feature: GitHub ingestion noise filters
  The ingestion worker applies project noise filters from the catalogue so bot
  activity and low-signal updates do not flood the Bronze layer.

  Scenario: Toggling a noise filter changes subsequent ingestion
    Given a managed repository "octo/reef" exists in the catalogue with bot author filtering enabled
    And the GitHub API returns a bot commit and a human commit for "octo/reef"
    When the GitHub ingestion worker runs for "octo/reef"
    Then only the human commit is ingested for "octo/reef"
    When the catalogue disables bot author filtering for the repository project
    And the GitHub API returns a new bot commit for "octo/reef"
    And the GitHub ingestion worker runs again for "octo/reef"
    Then the new bot commit is ingested for "octo/reef"

