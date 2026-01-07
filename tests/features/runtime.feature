Feature: Ghillie runtime service

  The Ghillie runtime provides HTTP endpoints for Kubernetes health probes.
  The service exposes /health and /ready endpoints on port 8080.

  Scenario: Health endpoint returns ok status
    Given a running Ghillie runtime app
    When I request GET /health
    Then the response status is 200
    And the response body is {"status": "ok"}

  Scenario: Ready endpoint returns ready status
    Given a running Ghillie runtime app
    When I request GET /ready
    Then the response status is 200
    And the response body is {"status": "ready"}
