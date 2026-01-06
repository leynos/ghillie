Feature: Ghillie Helm chart deployment

  The Ghillie Helm chart deploys the application to Kubernetes clusters
  for both local development (k3d) and GitOps environments.

  Scenario: Chart renders valid manifests with default values
    Given the Ghillie Helm chart
    When I render templates with default values
    Then the rendered manifests include a Deployment
    And the rendered manifests include a Service
    And the rendered manifests include an Ingress
    And the rendered manifests include a ServiceAccount

  Scenario: Chart supports local k3d configuration
    Given the Ghillie Helm chart
    And local k3d values with hostless ingress
    When I render templates with provided values
    Then the Ingress has no host specified
    And the Deployment uses the local image tag

  Scenario: Chart supports GitOps preview configuration
    Given the Ghillie Helm chart
    And GitOps values with explicit hostname and external secrets
    When I render templates with provided values
    Then the Ingress uses the configured hostname
    And an ExternalSecret is rendered
    And the Deployment references the external secret

  Scenario: Chart passes Helm lint validation
    Given the Ghillie Helm chart
    When I run helm lint
    Then lint passes without errors
