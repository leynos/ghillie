Feature: Report Markdown rendering and storage

  Rendered Markdown reports allow operators to navigate to a
  repository's latest report via a predictable file path.

  Scenario: Render and store a repository report as Markdown
    Given a repository with events and a filesystem sink
    When I generate a report with the sink
    Then a latest.md file exists at the predictable path
    And the Markdown content includes the repository name
    And the Markdown content includes the status summary
    And a dated report file also exists

  Scenario: Report generation works without a sink
    Given a repository with events but no sink
    When I generate a report without a sink
    Then a Gold report is created successfully
    And no Markdown files are written
