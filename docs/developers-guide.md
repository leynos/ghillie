# Ghillie Developers' Guide

This guide covers local development setup, tooling, and deployment workflows
for contributors to the Ghillie project.

## Prerequisites

- Python 3.12+
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

Run the quality gate chain to verify your environment:

```bash
make all
```

This runs formatting checks, linting, type checking, and tests.

## Quality gates

The project enforces these quality gates before commits:

| Target           | Description                        |
| ---------------- | ---------------------------------- |
| `make fmt`       | Format Python and Markdown sources |
| `make lint`      | Run ruff linter                    |
| `make check-fmt` | Verify formatting without changes  |
| `make typecheck` | Run ty type checker                |
| `make test`      | Run pytest with parallel execution |
| `make helm-lint` | Lint the Ghillie Helm chart        |
| `make helm-test` | Run Helm chart tests               |

Run all gates before committing:

```bash
make check-fmt && make lint && make typecheck && make test && make helm-lint
```

## Helm chart for local and GitOps previews

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
