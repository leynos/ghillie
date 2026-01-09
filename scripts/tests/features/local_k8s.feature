Feature: Local k3d preview environment lifecycle

  The local_k8s.py script provides commands to create and manage a local k3d
  preview environment for Ghillie. The script orchestrates k3d, CloudNativePG,
  Valkey, Docker, and Helm to deploy a complete preview environment.

  Background:
    Given the CLI tools docker, k3d, kubectl, and helm are available

  Scenario: Create preview environment from scratch
    Given no k3d cluster named ghillie-local exists
    When I run local_k8s up
    Then a k3d cluster named ghillie-local is created
    And the CNPG operator is installed
    And a CNPG Postgres cluster is created
    And the Valkey operator is installed
    And a Valkey instance is created
    And a secret named ghillie exists with DATABASE_URL and VALKEY_URL
    And the Docker image is built and imported
    And the Ghillie Helm chart is installed
    And the preview URL is printed to stdout
    And the exit code is 0

  Scenario: Idempotent up reuses existing cluster
    Given a k3d cluster named ghillie-local exists
    When I run local_k8s up
    Then the existing cluster is not deleted
    And the Helm release is upgraded
    And the exit code is 0

  Scenario: Delete preview environment
    Given a k3d cluster named ghillie-local exists
    When I run local_k8s down
    Then the k3d cluster is deleted
    And the exit code is 0

  Scenario: Status shows pod information
    Given a k3d cluster named ghillie-local exists
    When I run local_k8s status
    Then pod status is printed
    And the exit code is 0

  Scenario: Status for missing cluster
    Given no k3d cluster named ghillie-local exists
    When I run local_k8s status
    Then the output contains "does not exist"
    And the exit code is 1

  Scenario: Up with skip-build does not build or import image
    Given no k3d cluster named ghillie-local exists
    When I run local_k8s up with skip-build
    Then Docker image is not built or imported
    And the output contains "Skipping Docker build"
    And the exit code is 0
