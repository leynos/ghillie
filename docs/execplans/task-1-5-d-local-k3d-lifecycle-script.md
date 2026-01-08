# Implement local k3d lifecycle script (Task 1.5.d)

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`, and
`Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: DRAFT

This document must be maintained in accordance with `docs/execplans/PLANS.md`
(if it exists) and the execplans skill guidance.

## Purpose / Big Picture

Provide a Python script (`scripts/local_k8s.py`) and Makefile targets that
enable developers to create a local k3d-based preview environment for Ghillie.
After this change, running `make local-k8s-up` will:

1. Create a k3d cluster with loopback-only ingress
2. Install CloudNativePG and Valkey operators
3. Create Postgres and Valkey instances
4. Build and import the Ghillie Docker image
5. Deploy the Ghillie Helm chart
6. Print a preview URL (e.g., `http://127.0.0.1:49213/`)

The user can then access the Ghillie health endpoint at that URL, verify pod
status with `make local-k8s-status`, and tear down with `make local-k8s-down`.

This mirrors the ephemeral previews architecture while running entirely on the
developer's workstation, enabling local validation before pushing to CI/CD.

## Constraints

Hard invariants that must hold throughout implementation:

- The script must follow `docs/scripting-standards.md`: use Cyclopts for CLI,
  plumbum for subprocess execution, and pathlib for filesystem operations.
- The script must be a uv-runnable script with inline dependencies (shebang
  `#!/usr/bin/env -S uv run python` and `# /// script` block).
- All quality gates must pass: `make check-fmt`, `make lint`, `make typecheck`,
  `make test`.
- Tests must use `cmd-mox` for mocking external executables; no real k3d
  clusters are created during test runs.
- The existing `values_local.yaml` fixture at
  `tests/helm/fixtures/values_local.yaml` must be used for Helm installation.
- Makefile targets must follow existing patterns (use `$(UV_ENV)`, depend on
  `build` where needed).
- The script must not modify any existing files beyond adding Makefile targets.

## Tolerances (Exception Triggers)

Thresholds that trigger escalation when breached:

- Scope: if implementation requires more than 600 lines of Python (excluding
  tests) or touches more than 5 existing files, stop and escalate.
- Dependencies: if external dependencies beyond `cyclopts`, `plumbum`, and
  `cmd-mox` are required in the script, stop and escalate.
- Iterations: if tests still fail after 3 attempts to fix, stop and escalate.
- Ambiguity: if the Valkey operator CRD differs materially from the documented
  API, stop and present options.

## Risks

- **Risk:** Valkey operator API differs from hyperspike/valkey-operator docs.
  Severity: medium. Likelihood: low. Mitigation: Review operator repository for
  current CRD schema before implementing; make manifest generation a separate
  function for easy updates.

- **Risk:** CNPG secret naming convention changes.
  Severity: low. Likelihood: low. Mitigation: Use consistent naming
  (`pg-ghillie`) and verify secret name pattern in unit tests.

- **Risk:** cmd-mox does not capture all edge cases in subprocess mocking.
  Severity: medium. Likelihood: medium. Mitigation: Write comprehensive mock
  expectations; add integration test markers for optional real-cluster testing.

## Progress

- [ ] Stage 1: Scaffold CLI structure and Config dataclass
- [ ] Stage 2: Implement port selection and executable verification helpers
- [ ] Stage 3: Implement k3d cluster lifecycle helpers
- [ ] Stage 4: Implement namespace and CNPG helpers
- [ ] Stage 5: Implement Valkey helpers
- [ ] Stage 6: Implement application secret and image helpers
- [ ] Stage 7: Implement Helm chart installation helpers
- [ ] Stage 8: Wire up `up`, `down`, `status`, `logs` commands
- [ ] Stage 9: Add Makefile targets
- [ ] Stage 10: Add BDD behavioral tests
- [ ] Stage 11: Update users' guide documentation
- [ ] Stage 12: Update roadmap to mark task complete

## Surprises & Discoveries

(To be updated during implementation)

## Decision Log

- **Decision:** Use Cyclopts with environment variable support rather than
  argparse. Rationale: Aligns with `docs/scripting-standards.md`; provides
  cleaner parameter handling and env var integration for CI use. Date:
  2026-01-08

- **Decision:** Place script at `scripts/local_k8s.py` with tests at
  `scripts/tests/`. Rationale: Matches the pattern documented in
  `docs/scripting-standards.md` where tests mirror script locations. Date:
  2026-01-08

- **Decision:** Use `cmd-mox` for all external command mocking in tests.
  Rationale: Specified in `docs/scripting-standards.md`; enables testing
  without requiring Docker or k3d on CI runners. Date: 2026-01-08

## Outcomes & Retrospective

(To be completed after implementation)

## Context and Orientation

The Ghillie project already has:

- **Helm chart** at `charts/ghillie/` with templates for Deployment, Service,
  Ingress, ServiceAccount, ConfigMap, and ExternalSecret.
- **Dockerfile** with multi-stage build producing `ghillie:local` image.
- **Runtime module** at `ghillie/runtime.py` exposing `/health` and `/ready`
  endpoints via Falcon/Granian.
- **Local values fixture** at `tests/helm/fixtures/values_local.yaml`
  configured for k3d (hostless ingress, `image.tag=local`,
  `secrets.existingSecretName=ghillie`).
- **Design document** at `docs/local-k8s-preview-design.md` specifying the CLI
  shape, helper functions, and workflow.

The implementation will create:

- `scripts/local_k8s.py` - Main CLI script
- `scripts/tests/conftest.py` - pytest configuration with cmd-mox
- `scripts/tests/test_local_k8s.py` - Unit tests for helpers
- `scripts/tests/features/local_k8s.feature` - BDD scenarios
- `scripts/tests/features/steps/test_local_k8s_steps.py` - Step definitions

Key external tools the script will invoke:

- `docker` - Build images
- `k3d` - Create/delete clusters, import images
- `kubectl` - Kubernetes operations
- `helm` - Chart operations

## Plan of Work

### Stage 1: Scaffold CLI structure and Config dataclass

Create `scripts/local_k8s.py` with:

- uv script header with dependencies: `cyclopts>=2.9`, `plumbum`, `cmd-mox`
- `Config` dataclass with fields matching the design document class diagram
- Cyclopts `App` with `up`, `down`, `status`, `logs` subcommands (stubs)
- Basic argument parsing with environment variable support

Create `scripts/tests/conftest.py` with cmd-mox plugin registration.

Create `scripts/tests/test_local_k8s.py` with initial tests:

- `test_config_defaults` - verify Config dataclass defaults
- `test_cli_has_subcommands` - verify all four subcommands exist

Validation: `make check-fmt && make lint && make typecheck && make test`

### Stage 2: Implement port selection and executable verification helpers

Add to `scripts/local_k8s.py`:

    def require_exe(name: str) -> None:
        """Verify a CLI tool is available in PATH. Raises SystemExit if not."""

    def pick_free_loopback_port() -> int:
        """Find an available TCP port on 127.0.0.1 using socket.bind."""

    def b64decode_k8s_secret_field(b64_text: str) -> str:
        """Decode a base64-encoded Kubernetes secret value."""

Add tests:

- `test_require_exe_succeeds_for_python`
- `test_require_exe_raises_for_missing_executable`
- `test_pick_free_loopback_port_returns_valid_port`
- `test_b64decode_k8s_secret_field_decodes_correctly`

Validation: Quality gates pass.

### Stage 3: Implement k3d cluster lifecycle helpers

Add to `scripts/local_k8s.py`:

    def cluster_exists(cluster_name: str) -> bool:
        """Check if a k3d cluster exists by parsing k3d cluster list -o json."""

    def create_k3d_cluster(cluster_name: str, port: int, agents: int = 1) -> None:
        """Create a k3d cluster with loopback port mapping."""

    def delete_k3d_cluster(cluster_name: str) -> None:
        """Delete a k3d cluster."""

    def write_kubeconfig(cluster_name: str) -> Path:
        """Write kubeconfig for cluster and return the path."""

    def kubeconfig_env(cluster_name: str) -> dict[str, str]:
        """Return environment dict with KUBECONFIG set."""

Add tests using cmd-mox:

- `test_cluster_exists_returns_true_when_present`
- `test_cluster_exists_returns_false_when_absent`
- `test_create_k3d_cluster_invokes_correct_command`
- `test_create_k3d_cluster_uses_loopback_port_mapping`
- `test_delete_k3d_cluster_invokes_delete_command`

Validation: Quality gates pass.

### Stage 4: Implement namespace and CNPG helpers

Add to `scripts/local_k8s.py`:

    def namespace_exists(namespace: str, env: dict[str, str]) -> bool:
        """Check if a Kubernetes namespace exists."""

    def create_namespace(namespace: str, env: dict[str, str]) -> None:
        """Create a Kubernetes namespace."""

    def install_cnpg_operator(cfg: Config, env: dict[str, str]) -> None:
        """Install CloudNativePG operator via Helm."""

    def create_cnpg_cluster(cfg: Config, env: dict[str, str]) -> None:
        """Create a CNPG Postgres cluster by applying a manifest."""

    def wait_for_cnpg_ready(cfg: Config, env: dict[str, str], timeout: int = 600) -> None:
        """Wait for CNPG cluster pods to be ready."""

    def read_pg_app_uri(cfg: Config, env: dict[str, str]) -> str:
        """Extract DATABASE_URL from CNPG *-app secret."""

Add private helper for CNPG manifest generation:

    def _cnpg_cluster_manifest(namespace: str, cluster_name: str = "pg-ghillie") -> str:
        """Generate CNPG Cluster YAML manifest."""

Add tests:

- `test_namespace_exists_returns_true_when_present`
- `test_namespace_exists_returns_false_when_absent`
- `test_create_namespace_invokes_kubectl`
- `test_install_cnpg_operator_adds_helm_repo`
- `test_install_cnpg_operator_installs_chart`
- `test_create_cnpg_cluster_applies_manifest`
- `test_read_pg_app_uri_decodes_secret`

Validation: Quality gates pass.

### Stage 5: Implement Valkey helpers

Add to `scripts/local_k8s.py`:

    def install_valkey_operator(cfg: Config, env: dict[str, str]) -> None:
        """Install Valkey operator via Helm from hyperspike chart."""

    def create_valkey_instance(cfg: Config, env: dict[str, str]) -> None:
        """Create a Valkey instance by applying a manifest."""

    def wait_for_valkey_ready(cfg: Config, env: dict[str, str], timeout: int = 300) -> None:
        """Wait for Valkey pods to be ready."""

    def read_valkey_uri(cfg: Config, env: dict[str, str]) -> str:
        """Extract VALKEY_URL from Valkey secret."""

Add private helper:

    def _valkey_manifest(namespace: str, name: str = "valkey-ghillie") -> str:
        """Generate Valkey CR YAML manifest."""

Add tests:

- `test_install_valkey_operator_adds_helm_repo`
- `test_install_valkey_operator_installs_chart`
- `test_create_valkey_instance_applies_manifest`
- `test_read_valkey_uri_extracts_connection_string`

Validation: Quality gates pass.

### Stage 6: Implement application secret and image helpers

Add to `scripts/local_k8s.py`:

    def create_app_secret(
        cfg: Config,
        env: dict[str, str],
        database_url: str,
        valkey_url: str,
    ) -> None:
        """Create the ghillie Kubernetes Secret with connection URLs."""

    def build_docker_image(image_repo: str, image_tag: str) -> None:
        """Build the Docker image locally."""

    def import_image_to_k3d(cluster_name: str, image_repo: str, image_tag: str) -> None:
        """Import the Docker image into the k3d cluster."""

Add tests:

- `test_create_app_secret_creates_secret_with_urls`
- `test_create_app_secret_uses_correct_secret_name`
- `test_build_docker_image_invokes_docker_build`
- `test_import_image_to_k3d_invokes_k3d_import`

Validation: Quality gates pass.

### Stage 7: Implement Helm chart installation helpers

Add to `scripts/local_k8s.py`:

    def install_ghillie_chart(cfg: Config, env: dict[str, str]) -> None:
        """Install the Ghillie Helm chart using values_local.yaml."""

    def print_status(cfg: Config, env: dict[str, str]) -> None:
        """Print pod status for the preview environment."""

    def tail_logs(cfg: Config, env: dict[str, str], follow: bool = False) -> None:
        """Stream logs from Ghillie pods."""

Add tests:

- `test_install_ghillie_chart_uses_values_file`
- `test_install_ghillie_chart_sets_namespace`
- `test_print_status_invokes_kubectl_get_pods`
- `test_tail_logs_invokes_kubectl_logs`
- `test_tail_logs_with_follow_uses_follow_flag`

Validation: Quality gates pass.

### Stage 8: Wire up `up`, `down`, `status`, `logs` commands

Complete the Cyclopts command implementations:

    @app.command
    def up(
        *,
        cluster_name: Annotated[str, Parameter(env_var="GHILLIE_K3D_CLUSTER")] = "ghillie-local",
        namespace: Annotated[str, Parameter(env_var="GHILLIE_K3D_NAMESPACE")] = "ghillie",
        ingress_port: Annotated[int | None, Parameter(env_var="GHILLIE_K3D_PORT")] = None,
        skip_build: bool = False,
    ) -> int:
        """Create or update the local k3d preview environment."""
        # 1. Verify executables
        # 2. Check if cluster exists; create if not
        # 3. Install CNPG, create Postgres cluster, wait for ready
        # 4. Install Valkey operator, create instance, wait for ready
        # 5. Read DATABASE_URL and VALKEY_URL from secrets
        # 6. Create application secret
        # 7. Build and import Docker image (unless skip_build)
        # 8. Install Helm chart
        # 9. Print preview URL
        return 0

    @app.command
    def down(…) -> int:
        """Delete the local k3d cluster."""

    @app.command
    def status(…) -> int:
        """Show status of the local preview environment."""

    @app.command
    def logs(…) -> int:
        """Tail application logs from the preview environment."""

Add unit tests for command orchestration:

- `test_up_command_verifies_executables_first`
- `test_up_command_creates_cluster_when_absent`
- `test_up_command_reuses_cluster_when_present`
- `test_down_command_deletes_cluster`
- `test_status_command_prints_pod_status`

Validation: Quality gates pass.

### Stage 9: Add Makefile targets

Add to `Makefile` (after the `docker-run` target):

    local-k8s-up: build ## Create local k3d preview environment
    	$(UV_ENV) uv run scripts/local_k8s.py up

    local-k8s-down: ## Delete local k3d preview environment
    	$(UV_ENV) uv run scripts/local_k8s.py down

    local-k8s-status: ## Show local k3d preview status
    	$(UV_ENV) uv run scripts/local_k8s.py status

    local-k8s-logs: ## Tail logs from local preview
    	$(UV_ENV) uv run scripts/local_k8s.py logs --follow

Update `.PHONY` declaration to include new targets.

Validation: `make help` shows new targets; `make local-k8s-status` runs
(expected to fail without cluster, but should invoke the script).

### Stage 10: Add BDD behavioral tests

Create `scripts/tests/features/local_k8s.feature`:

    Feature: Local k3d preview environment lifecycle

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

Create step definitions in
`scripts/tests/features/steps/test_local_k8s_steps.py` using cmd-mox.

Validation: Quality gates pass; BDD tests pass with mocked externals.

### Stage 11: Update users' guide documentation

Add section to `docs/users-guide.md` after container image section:

    ## Local k3d preview

    Ghillie provides a local preview environment using k3d (k3s-in-Docker).
    This mirrors the ephemeral previews architecture while running on your
    workstation.

    ### Prerequisites

    Install:
    - docker (Docker Desktop with WSL2 or Docker Engine)
    - k3d (v5.x or later)
    - kubectl (v1.28 or later)
    - helm (v3.x)

    ### Creating a preview environment

        make local-k8s-up

    This creates a k3d cluster, installs Postgres and Valkey, builds the
    Docker image, and deploys the Helm chart. On success, it prints the
    preview URL.

    ### Environment variables

    | Variable              | Default       | Description           |
    | --------------------- | ------------- | --------------------- |
    | GHILLIE_K3D_CLUSTER   | ghillie-local | k3d cluster name      |
    | GHILLIE_K3D_NAMESPACE | ghillie       | Kubernetes namespace  |
    | GHILLIE_K3D_PORT      | (auto)        | Host port for ingress |

    ### Checking status

        make local-k8s-status

    ### Viewing logs

        uv run scripts/local_k8s.py logs
        uv run scripts/local_k8s.py logs --follow

    ### Deleting the environment

        make local-k8s-down

    ### Idempotency

    Running `make local-k8s-up` when a cluster exists is safe. The script
    reuses the existing cluster and upgrades the Helm release.

Validation: `make markdownlint && make nixie`

### Stage 12: Update roadmap to mark task complete

Edit `docs/roadmap.md` to change:

    - [ ] **Task 1.5.d – Implement local k3d lifecycle script**

to:

    - [x] **Task 1.5.d – Implement local k3d lifecycle script**

Validation: Roadmap reflects completion.

## Concrete Steps

All commands run from the repository root (`/data/leynos/Projects/ghillie`).

### Stage 1 commands

    # Create scripts directory
    mkdir -p scripts/tests/features/steps

    # Create conftest.py
    # (content via Edit tool)

    # Create local_k8s.py scaffold
    # (content via Edit tool)

    # Create test_local_k8s.py
    # (content via Edit tool)

    # Verify quality gates
    make check-fmt && make lint && make typecheck && make test

### Stage 9 commands (Makefile)

    # Edit Makefile to add targets
    # (content via Edit tool)

    # Validate Makefile
    mbake validate Makefile

    # Verify targets appear in help
    make help | grep local-k8s

### Stage 11 commands (documentation)

    # Edit docs/users-guide.md
    # (content via Edit tool)

    # Format and validate
    make fmt
    make markdownlint
    make nixie

### Final validation

    # Full quality gate check
    make all

    # Confirm test count increased
    make test 2>&1 | grep -E 'passed|failed'

## Validation and Acceptance

Quality criteria:

- **Tests:** All existing tests pass plus new tests for local_k8s module
- **Lint/typecheck:** `make lint` and `make typecheck` exit 0
- **Format:** `make check-fmt` exits 0
- **Markdown:** `make markdownlint` and `make nixie` exit 0

Quality method:

    make all  # runs check-fmt, lint, typecheck, test

Acceptance behaviour:

1. `make local-k8s-up` (with all externals mocked in tests) completes with
   exit code 0 and prints a preview URL.
2. `make local-k8s-down` deletes the cluster.
3. `make local-k8s-status` shows pod information.
4. Running `make local-k8s-up` twice is idempotent.

Integration validation (optional, not run in CI):

    # On a machine with Docker and k3d installed:
    make local-k8s-up
    curl http://127.0.0.1:<port>/health
    # Expected: {"status": "ok"}
    make local-k8s-status
    # Expected: ghillie pod in Running state
    make local-k8s-down

## Idempotence and Recovery

- Running `make local-k8s-up` multiple times is safe; existing clusters are
  reused.
- If a stage fails, the script exits with a non-zero code and a descriptive
  error message.
- To recover from a partial state, run `make local-k8s-down` to clean up,
  then `make local-k8s-up` again.
- All Helm installs use `upgrade --install` for idempotent behavior.

## Artifacts and Notes

### Config dataclass (from design document)

    @dataclasses.dataclass(frozen=True, slots=True)
    class Config:
        cluster_name: str = "ghillie-local"
        namespace: str = "ghillie"
        ingress_port: int | None = None
        chart_path: Path = Path("charts/ghillie")
        image_repo: str = "ghillie"
        image_tag: str = "local"
        cnpg_release: str = "cnpg"
        cnpg_namespace: str = "cnpg-system"
        valkey_release: str = "valkey-operator"
        valkey_namespace: str = "valkey-operator-system"
        values_file: Path = Path("tests/helm/fixtures/values_local.yaml")
        pg_cluster_name: str = "pg-ghillie"
        valkey_name: str = "valkey-ghillie"
        app_secret_name: str = "ghillie"

### CNPG Cluster manifest template

    apiVersion: postgresql.cnpg.io/v1
    kind: Cluster
    metadata:
      name: {pg_cluster_name}
      namespace: {namespace}
    spec:
      instances: 1
      storage:
        size: 1Gi
      bootstrap:
        initdb:
          database: ghillie
          owner: ghillie

### Valkey manifest template

    apiVersion: valkey.io/v1alpha1
    kind: Valkey
    metadata:
      name: {valkey_name}
      namespace: {namespace}
    spec:
      replicas: 1
      resources:
        requests:
          memory: "64Mi"
          cpu: "50m"

### k3d cluster create command pattern

    k3d cluster create {cluster_name} \
      --agents 1 \
      --port "127.0.0.1:{port}:80@loadbalancer"

## Interfaces and Dependencies

### Script dependencies (inline uv block)

    # /// script
    # requires-python = ">=3.13"
    # dependencies = ["cyclopts>=2.9", "plumbum", "cmd-mox"]
    # ///

### External CLI tools required

- `docker` - for `docker build`
- `k3d` - for cluster lifecycle and image import
- `kubectl` - for namespace, secret, and resource management
- `helm` - for chart and operator installation

### Helm repositories

- `cnpg` - https://cloudnative-pg.github.io/charts (for cloudnative-pg)
- `valkey-operator` - https://hyperspike.github.io/valkey-operator (for
  valkey-operator)

### Key function signatures

    def require_exe(name: str) -> None: …
    def pick_free_loopback_port() -> int: …
    def b64decode_k8s_secret_field(b64_text: str) -> str: …
    def cluster_exists(cluster_name: str) -> bool: …
    def create_k3d_cluster(cluster_name: str, port: int, agents: int = 1) -> None: …
    def delete_k3d_cluster(cluster_name: str) -> None: …
    def write_kubeconfig(cluster_name: str) -> Path: …
    def kubeconfig_env(cluster_name: str) -> dict[str, str]: …
    def namespace_exists(namespace: str, env: dict[str, str]) -> bool: …
    def create_namespace(namespace: str, env: dict[str, str]) -> None: …
    def install_cnpg_operator(cfg: Config, env: dict[str, str]) -> None: …
    def create_cnpg_cluster(cfg: Config, env: dict[str, str]) -> None: …
    def wait_for_cnpg_ready(cfg: Config, env: dict[str, str], timeout: int = 600) -> None: …
    def read_pg_app_uri(cfg: Config, env: dict[str, str]) -> str: …
    def install_valkey_operator(cfg: Config, env: dict[str, str]) -> None: …
    def create_valkey_instance(cfg: Config, env: dict[str, str]) -> None: …
    def wait_for_valkey_ready(cfg: Config, env: dict[str, str], timeout: int = 300) -> None: …
    def read_valkey_uri(cfg: Config, env: dict[str, str]) -> str: …
    def create_app_secret(cfg: Config, env: dict[str, str], database_url: str, valkey_url: str) -> None: …
    def build_docker_image(image_repo: str, image_tag: str) -> None: …
    def import_image_to_k3d(cluster_name: str, image_repo: str, image_tag: str) -> None: …
    def install_ghillie_chart(cfg: Config, env: dict[str, str]) -> None: …
    def print_status(cfg: Config, env: dict[str, str]) -> None: …
    def tail_logs(cfg: Config, env: dict[str, str], follow: bool = False) -> None: …
