Feature: Operator CLI contract

  The packaged operator CLI should expose the MVP noun and verb grammar
  and validate the documented option surface before later tasks add
  real backend behaviour.

  Scenario: Root help lists the top-level nouns
    When I run the operator CLI with "--help"
    Then the operator CLI exits with code 0
    And the operator CLI output mentions "stack"
    And the operator CLI output mentions "estate"
    And the operator CLI output mentions "ingest"
    And the operator CLI output mentions "export"
    And the operator CLI output mentions "report"
    And the operator CLI output mentions "metrics"

  Scenario: Stack up help exposes backend and wait options
    When I run the operator CLI with "stack up --help"
    Then the operator CLI exits with code 0
    And the operator CLI output mentions "--backend"
    And the operator CLI output mentions "--wait"
    And the operator CLI output mentions "--no-wait"

  Scenario: Root global options parse before the noun command
    When I run the operator CLI with "--api-base-url http://127.0.0.1:9999 report run --help"
    Then the operator CLI exits with code 0
    And the operator CLI output mentions "Usage"
    And the operator CLI output mentions "--scope"

  Scenario: Invalid stack backend fails fast
    When I run the operator CLI with "stack up --backend invalid"
    Then the operator CLI exits with code 2
    And the operator CLI error mentions "invalid choice"
