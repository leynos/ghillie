# Ghillie Developers' Guide

This guide covers local development setup, tooling, and deployment workflows
for contributors to the Ghillie project.

## Spelling policy

Run `make spelling` to enforce en-GB-oxendict prose spelling. The generated
`typos.toml` starts from the shared estate dictionary, refreshes its untracked
local cache only when the authority is newer, and then applies the narrow
repository policy in `typos.local.toml`. Edit the local policy and regenerate
the configuration rather than changing generated entries by hand.

## Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) for dependency management
- Docker (for k3d local previews)
- Helm 3.x (for chart development and testing)
- Node.js (optional, for py-pglite Postgres tests)

## Development setup

Clone the repository and install dependencies:

```bash
git clone https://github.com/leynos/ghillie.git
cd ghillie
make build
```

Run the quality gate chain to verify the development environment:

```bash
make all
```

This runs formatting checks, linting, type checking, and tests.

## Quality gates

The project enforces these quality gates before commits:

| Target                    | Description                                     |
| ------------------------- | ----------------------------------------------- |
| `make fmt`                | Format Python and Markdown sources              |
| `make check-architecture` | Run Hecate import-direction architecture checks |
| `make lint`               | Run Hecate and Ruff lint checks                 |
| `make check-fmt`          | Verify formatting without changes               |
| `make typecheck`          | Run the type checker                            |
| `make test`               | Run pytest with parallel execution              |
| `make helm-lint`          | Lint the Ghillie Helm chart                     |
| `make helm-test`          | Run Helm chart tests                            |

Run all gates before committing:

```bash
make check-fmt && make lint && make typecheck && make test && make helm-lint
```

## Workflow pins and Dependabot

Dependabot owns the upgrade of GitHub Actions and reusable workflows, including
calls into `leynos/shared-actions`. Contract tests that assert a caller's exact
commit SHA create a lockstep dependency: every time Dependabot opens a bump PR,
the test fails until a human edits the pinned constant to match. That defeats
the purpose of automated dependency updates and turns a routine bump into a
manual chore.

Contract tests may still verify the *shape* of a reusable-workflow caller. They
must not verify the specific SHA value.

- Do assert the workflow references the correct reusable workflow path.
- Do assert the ref is pinned to a full 40-character commit SHA, not a
  mutable branch such as `main` or `rolling`.
- Do assert the expected `on:` triggers, least-privilege `permissions:`, and
  the inputs the caller relies on.
- Do not hard-code the current SHA value as an expected string. Match it with
  a pattern instead.
- Do not fail a test purely because Dependabot bumped the pinned SHA.

```python
import re

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def test_uses_pinned_full_sha(caller_step):
    ref = caller_step["uses"].split("@")[-1]
    assert SHA_RE.match(ref), f"expected a 40-hex commit SHA, got {ref!r}"
```

If a workflow's behaviour genuinely depends on a feature only present from a
particular commit onwards, express that as a comment or a changelog note, not
as a test assertion on the SHA string.

## Architecture checks

Ghillie uses Hecate as the static architecture fitness function for Python
import direction. Run it directly with:

```bash
make check-architecture
```

The same check runs before Ruff as part of `make lint`, so CI and local linting
share the same architecture gate.

The Hecate policy is stored in `[tool.hecate]` in `pyproject.toml`. When adding
or moving modules:

- update the policy if the module introduces a new package boundary;
- put specific prefixes before broad prefixes because Hecate uses first-match
  group classification;
- keep composition-root prefixes narrow and explicit;
- prefer refactoring a dependency edge over adding `ignore_imports`;
- if an ignore rule is unavoidable, include a precise reason that explains why
  the edge is intentional; and
- run `make check-architecture` before opening a pull request.

The current policy groups modules as composition roots, domain ports,
application modules, inbound adapters, and outbound adapters. The adoption
rationale is recorded in `docs/adr-003-adopt-hecate-for-architecture-checks.md`.

## Code style and type handling

Prefer code and type signatures that the checker can prove without help. Use
`typ.cast(...)` only at boundaries where a third-party API or framework returns
values that are correct at runtime but too loose for static analysis.

Typical cases in this repository include framework constructor parameters and
validated values pulled from generic dictionaries. Keep the cast narrow and
close to the boundary instead of spreading `Any` through the rest of the code.

```python
import typing as typ

if typ.TYPE_CHECKING:
    from falcon._typing import AsyncMiddleware as FalconAsyncMiddleware

middleware: list[FalconAsyncMiddleware] = []
middleware.append(typ.cast("FalconAsyncMiddleware", build_middleware()))

raw_timeout = config_data["timeout_seconds"]
timeout_seconds = float(
    typ.cast("str | bytes | bytearray | typ.SupportsFloat", raw_timeout)
)
```

Use `typ.cast(...)` to document intent, not to silence the checker blindly. If
the value can be validated or narrowed with normal control flow, prefer that
over a cast. When a cast is necessary, add it at the smallest possible scope
and keep the surrounding code explicit about why the cast is safe.

Use `if typ.TYPE_CHECKING:` when the type checker needs a private or
heavyweight framework symbol that should never be imported at runtime. The
Falcon middleware alias is the concrete pattern in this repository: guard the
`falcon._typing.AsyncMiddleware` import, then reference it only in annotations
or stringified `typ.cast(...)` targets. Do not dereference guarded imports in
runtime expressions.

See the canonical `FalconAsyncMiddleware` example above for the exact
`middleware` and `build_middleware()` pattern.

### Logging integration

Application code should obtain loggers through `ghillie.logging`, which wraps
the underlying `femtologging` logger and preserves the repository's
percent-formatting, level normalization, and `exc_info` handling rules. Call
sites should go through that wrapper instead of importing `femtologging`
directly.

To obtain a named logger, use the helpers in `ghillie.logging`. Keep named
logger acquisition behind that wrapper so the module remains the single
translation layer for the femtologging integration boundary.

Tests that need to inspect emitted logs should use the
`capture_femto_logs(name)` context manager from
`tests.helpers.femtologging_capture`. It captures the records emitted by the
named logger without routing through `logging.getLogger`, which would bypass
the femtologging integration entirely.

## Helm chart for local and GitOps (Git-driven operations) previews

The `charts/ghillie` Helm chart deploys Ghillie to Kubernetes clusters for both
local k3d development and GitOps ephemeral preview environments. The chart
follows the design specified in `docs/local-k8s-preview-design.md`.

### Chart structure

```text
charts/ghillie/
  Chart.yaml              # Chart metadata (version 0.1.0)
  values.yaml             # Default values with full interface
  values.schema.json      # JSON Schema for values validation
  templates/
    _helpers.tpl          # Helper functions (fullname, labels, secretName)
    deployment.yaml       # Application deployment
    service.yaml          # ClusterIP service
    ingress.yaml          # Ingress with hostless support for k3d
    serviceaccount.yaml   # Optional service account
    externalsecret.yaml   # Optional External Secrets Operator support
    configmap.yaml        # Non-sensitive environment visibility
    NOTES.txt             # Post-install instructions
```

### Installing for local k3d development

Local k3d uses hostless ingress (empty `host: ""`), relying on Traefik as the
default ingress controller in k3s. The local workflow expects a pre-created
Kubernetes Secret containing `DATABASE_URL` and `VALKEY_URL`.

```bash
# Create the application secret (example values)
kubectl create secret generic ghillie \
  --from-literal=DATABASE_URL='postgresql://user:pass@host:5432/db' \
  --from-literal=VALKEY_URL='redis://valkey:6379'

# Install with local values
helm install ghillie charts/ghillie \
  --set image.repository=ghillie \
  --set image.tag=local \
  --set secrets.existingSecretName=ghillie
```

Or use a values file:

```yaml
# values-local.yaml
image:
  repository: ghillie
  tag: local
  pullPolicy: IfNotPresent

ingress:
  enabled: true
  hosts:
    - host: ""
      paths:
        - path: /
          pathType: Prefix

secrets:
  existingSecretName: ghillie
  externalSecret:
    enabled: false
```

```bash
helm install ghillie charts/ghillie -f values-local.yaml
```

**Expected outcome:**

- Deployment creates a single pod running `ghillie:local`
- Service exposes port 8080 as ClusterIP
- Ingress routes all traffic (hostless) to the service
- Pod loads `DATABASE_URL` and `VALKEY_URL` from the `ghillie` secret
- Pod logs show the runtime entrypoint starting cleanly

Verify the installation:

```bash
kubectl get pods -l app.kubernetes.io/name=ghillie
kubectl logs -l app.kubernetes.io/name=ghillie -f
```

### Installing for GitOps ephemeral previews

GitOps environments use explicit hostnames and External Secrets Operator to
hydrate secrets from Vault or another backend. The chart creates an
ExternalSecret resource when `secrets.externalSecret.enabled` is true.

```yaml
# values-gitops.yaml
image:
  repository: ghcr.io/leynos/ghillie
  tag: sha-abc123

ingress:
  enabled: true
  hosts:
    - host: pr-123.preview.example.com
      paths:
        - path: /
          pathType: Prefix

secrets:
  externalSecret:
    enabled: true
    secretStoreRef: platform-vault
    refreshInterval: 1h
    data:
      - secretKey: DATABASE_URL
        remoteRef:
          key: ghillie/database
          property: url
      - secretKey: VALKEY_URL
        remoteRef:
          key: ghillie/valkey
          property: url
```

Deploy via FluxCD HelmRelease or directly:

```bash
helm install ghillie charts/ghillie -f values-gitops.yaml
```

**Expected outcome:**

- Deployment uses the immutable image tag (`sha-abc123`)
- ExternalSecret is created, referencing `platform-vault` ClusterSecretStore
- External Secrets Operator hydrates a Secret named after the release
- Ingress routes `pr-123.preview.example.com` to the service
- Pod starts with secrets injected from Vault

### Values interface

The chart supports the following configuration:

| Value                                    | Description                         | Default                      |
| ---------------------------------------- | ----------------------------------- | ---------------------------- |
| `image.repository`                       | Container image repository          | `ghillie`                    |
| `image.tag`                              | Container image tag                 | `local`                      |
| `image.pullPolicy`                       | Image pull policy                   | `IfNotPresent`               |
| `command`                                | Container command override          | `[]`                         |
| `args`                                   | Container arguments override        | `[]`                         |
| `replicaCount`                           | Number of replicas                  | `1`                          |
| `service.port`                           | Service port                        | `8080`                       |
| `service.type`                           | Service type                        | `ClusterIP`                  |
| `ingress.enabled`                        | Enable ingress                      | `true`                       |
| `ingress.className`                      | Ingress class name                  | `""`                         |
| `ingress.annotations`                    | Ingress annotations                 | `{}`                         |
| `ingress.hosts`                          | Ingress hosts configuration         | hostless default             |
| `ingress.tls`                            | TLS configuration                   | `[]`                         |
| `env.normal`                             | Non-sensitive environment variables | `{GHILLIE_ENV: development}` |
| `secrets.existingSecretName`             | Pre-created secret name             | `""`                         |
| `secrets.externalSecret.enabled`         | Enable ExternalSecret creation      | `false`                      |
| `secrets.externalSecret.secretStoreRef`  | ClusterSecretStore name             | `""`                         |
| `secrets.externalSecret.refreshInterval` | Secret refresh interval             | `1h`                         |
| `secrets.externalSecret.data`            | Secret data mappings                | `[]`                         |
| `resources`                              | Resource limits/requests            | `{}`                         |
| `securityContext`                        | Container security context          | `{}`                         |
| `podSecurityContext`                     | Pod security context                | `{}`                         |
| `serviceAccount.create`                  | Create service account              | `true`                       |
| `serviceAccount.name`                    | Service account name override       | `""`                         |
| `serviceAccount.annotations`             | Service account annotations         | `{}`                         |

### Command and args overrides

The chart supports entrypoint overrides for running different Ghillie modes:

```yaml
# Run as ingestion worker
command: ["python", "-m", "ghillie.worker"]
args: ["--mode", "ingestion"]

# Run as transform worker
command: ["python", "-m", "ghillie.worker"]
args: ["--mode", "transform"]
```

### Linting and testing the chart

Validate the chart structure:

```bash
make helm-lint
# Or directly:
helm lint charts/ghillie
```

**Expected output:**

```text
==> Linting charts/ghillie
[INFO] Chart.yaml: icon is recommended

1 chart(s) linted, 0 chart(s) failed
```

Run the chart test suite:

```bash
make helm-test
# Or directly:
uv run pytest tests/helm -v
```

**Expected output:**

```text
tests/helm/test_template_render.py::TestDeploymentRendering::test_deployment_uses_correct_image PASSED
tests/helm/test_template_render.py::TestDeploymentRendering::test_deployment_uses_default_image PASSED
...
tests/helm/features/steps/test_helm_steps.py::test_chart_default_rendering PASSED
tests/helm/features/steps/test_helm_steps.py::test_chart_local_config PASSED
tests/helm/features/steps/test_helm_steps.py::test_chart_gitops_config PASSED
tests/helm/features/steps/test_helm_steps.py::test_chart_lint PASSED

24 passed in 6.92s
```

### Template rendering

Preview rendered manifests without installing:

```bash
# Default values
helm template test-release charts/ghillie

# With local values
helm template test-release charts/ghillie \
  -f tests/helm/fixtures/values_local.yaml

# With GitOps values
helm template test-release charts/ghillie \
  -f tests/helm/fixtures/values_gitops.yaml
```

**Expected: valid Kubernetes YAML with no template errors.**

### Dry-run installation

Validate against a cluster without deploying:

```bash
helm template test-release charts/ghillie | kubectl apply --dry-run=client -f -
```

**Expected output:**

```text
serviceaccount/test-release-ghillie created (dry run)
configmap/test-release-ghillie-config created (dry run)
service/test-release-ghillie created (dry run)
deployment.apps/test-release-ghillie created (dry run)
ingress.networking.k8s.io/test-release-ghillie created (dry run)
```

### Troubleshooting

**Chart lint fails with schema errors:**

The `values.schema.json` enforces value constraints. When using `--set`, ensure
complete structures are provided. For complex values, use a values file instead.

**Helm tests skip:**

Tests skip automatically if `helm` is not installed. Install Helm 3.x to run
the full test suite.

**Ingress not routing traffic:**

For local k3d, ensure Traefik is running as the default ingress controller. The
hostless ingress relies on Traefik's default routing behaviour.

```bash
kubectl get pods -n kube-system -l app.kubernetes.io/name=traefik
```

**ExternalSecret not creating Secret:**

Verify the External Secrets Operator is installed and the ClusterSecretStore
exists:

```bash
kubectl get clustersecretstores
kubectl get externalsecrets
kubectl describe externalsecret <release-name>-ghillie
```

## Running tests

### Unit and behavioural tests

```bash
make test
```

Tests run in parallel using pytest-xdist. The test suite uses py-pglite for
Postgres semantics when available, falling back to SQLite otherwise.

### Database backend selection

Force SQLite for faster local iteration:

```bash
GHILLIE_TEST_DB=sqlite make test
```

### Helm chart tests only

```bash
make helm-test
```

## Documentation

- Update `docs/users-guide.md` for user-facing feature documentation
- Update `docs/developers-guide.md` for development workflow changes
- Follow the style guide in `docs/documentation-style-guide.md`
- Run `make fmt` to format Markdown after changes
