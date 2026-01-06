# Implement Ghillie Helm chart for previews

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`, and
`Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: COMPLETE

No `PLANS.md` file exists in this repository.

## Purpose / Big Picture

Build the `charts/ghillie` Helm chart that deploys the Ghillie application to
Kubernetes clusters for both local k3d development and GitOps ephemeral
previews. After completion, developers can run `helm install` with local values
to deploy Ghillie to a k3d cluster, and the same chart works with FluxCD
HelmRelease for GitOps environments.

Observable success: `helm lint charts/ghillie` passes without errors, and
`helm template` renders valid Kubernetes manifests for both local and GitOps
value configurations.

## Constraints

- The chart must implement the values interface specified in
  `docs/local-k8s-preview-design.md` exactly.
- Templates must follow Helm best practices with `_helpers.tpl` for naming
  conventions.
- Ingress must support hostless mode for local k3d (empty `host: ""`).
- ExternalSecret must be optional and only render when
  `secrets.externalSecret.enabled` is true.
- All Python test code must pass `make check-fmt`, `make lint`, `make
  typecheck`, and `make test`.
- No modifications to existing application code; this task is chart-only plus
  tests.

## Tolerances (Exception Triggers)

- Scope: if implementation requires more than 20 files or 1500 lines of code
  (net), stop and escalate.
- Interface: if the values interface must deviate from the design document,
  stop and escalate.
- Dependencies: if Helm plugins or external tools beyond `helm` are required,
  stop and escalate.
- Iterations: if `helm lint` still fails after 3 attempts, stop and escalate.
- Ambiguity: if template rendering behaviour is unclear (e.g., edge cases in
  hostless ingress), stop and present options.

## Risks

- Risk: Helm template Go syntax errors not caught until runtime.
  Severity: medium Likelihood: medium Mitigation: Run `helm lint` after each
  template is created; use `helm template` with `--debug` for detailed errors.

- Risk: pytest-bdd step discovery issues due to directory structure.
  Severity: low Likelihood: medium Mitigation: Follow existing
  `tests/features/` patterns exactly; use `@scenario` decorators with correct
  relative paths.

- Risk: Hostless ingress may not render correctly (empty host edge case).
  Severity: medium Likelihood: low Mitigation: Test with explicit empty host
  value and verify rendered YAML omits `host` key or includes empty string
  correctly.

## Progress

- [x] (2026-01-05) Stage A: Create chart foundation (Chart.yaml, values.yaml, _helpers.tpl)
- [x] (2026-01-05) Stage B: Create core templates (deployment, service, serviceaccount)
- [x] (2026-01-05) Stage C: Create optional templates (ingress, externalsecret, configmap, NOTES.txt)
- [x] (2026-01-05) Stage D: Create values.schema.json for validation
- [x] (2026-01-05) Stage E: Create unit tests (tests/helm/test_template_render.py)
- [x] (2026-01-05) Stage F: Create BDD tests (tests/helm/features/)
- [x] (2026-01-05) Stage G: Add Makefile targets (helm-lint, helm-test)
- [x] (2026-01-05) Stage H: Update docs/roadmap.md to mark task complete
- [x] (2026-01-05) Stage I: Run all quality gates and commit

## Surprises & Discoveries

- Observation: ruamel.yaml required instead of PyYAML
  Evidence: PyYAML not in project dependencies; ruamel.yaml>=0.18.6 is
  Impact: Updated test code to use `ruamel.yaml.YAML()` instead of
  `yaml.safe_load_all()`

- Observation: JSON Schema validation enforces paths when setting hosts
  Evidence: Test `test_ingress_with_explicit_host` failed with "missing
  property 'paths'" when using --set
  Impact: Used values fixture file instead of --set for explicit host test

## Decision Log

- Decision: Use subprocess + PyYAML for Helm template testing
  Rationale: Matches existing test patterns in `test_catalogue_cli.py` and
  `test_catalogue_steps.py`; avoids adding new test dependencies Date/Author:
  2026-01-05 / Claude

- Decision: Place Helm tests under `tests/helm/` as new directory
  Rationale: Keeps chart tests separate from Python unit tests; matches
  feature-based organisation principle Date/Author: 2026-01-05 / Claude

- Decision: ConfigMap created but env values also injected directly
  Rationale: ConfigMap provides visibility via kubectl; direct injection
  ensures values are available without mounting Date/Author: 2026-01-05 / Claude

- Decision: Include NOTES.txt template with post-install instructions
  Rationale: User requested post-install notes showing how to access the
  deployed service Date/Author: 2026-01-05 / User

- Decision: Skip Helm tests if helm binary is not available
  Rationale: Use pytest.skip() when helm is unavailable; allows tests to pass
  in environments without helm while still providing coverage when available
  Date/Author: 2026-01-05 / User

## Outcomes & Retrospective

**Outcomes:**
- Chart created at `charts/ghillie/` with all required templates
- `helm lint charts/ghillie` passes without errors
- 20 unit tests and 4 BDD tests all pass
- Makefile targets `helm-lint` and `helm-test` added
- Task 1.5.b marked complete in roadmap

**Lessons learned:**
- Using ruamel.yaml for YAML parsing aligns with project dependencies
- Schema validation with helm requires complete value structures, not partial --set
- Hostless ingress (empty host) works well for k3d local development

## Context and Orientation

This task implements Task 1.5.b from `docs/roadmap.md`. The design is fully
specified in `docs/local-k8s-preview-design.md`, which defines:

- Chart layout at `charts/ghillie/`
- Required values interface (image, service, ingress, secrets, resources)
- Template sketches for deployment, service, ingress, externalsecret
- Local vs GitOps value patterns

No `charts/` directory currently exists; this is greenfield implementation.

Key files to reference:

- `docs/local-k8s-preview-design.md` - authoritative design document
- `tests/features/steps/test_catalogue_steps.py` - BDD pattern reference
- `Makefile` - existing targets to extend

## Plan of Work

### Stage A: Chart Foundation

Create the chart directory structure and foundational files.

1. Create `charts/ghillie/Chart.yaml` with:
   - apiVersion: v2
   - name: ghillie
   - version: 0.1.0
   - appVersion: "0.1.0"
   - type: application

2. Create `charts/ghillie/values.yaml` with all required values:
   - image (repository, tag, pullPolicy)
   - command, args (entrypoint overrides)
   - service (port, type)
   - ingress (enabled, className, annotations, hosts, tls)
   - env.normal (non-sensitive environment)
   - secrets (existingSecretName, externalSecret.*)
   - resources, securityContext, podSecurityContext
   - serviceAccount (create, name, annotations)
   - replicaCount

3. Create `charts/ghillie/templates/_helpers.tpl` with:
   - ghillie.name
   - ghillie.fullname
   - ghillie.chart
   - ghillie.labels
   - ghillie.selectorLabels
   - ghillie.serviceAccountName
   - ghillie.secretName

Validation: `helm lint charts/ghillie` passes.

### Stage B: Core Templates

1. Create `charts/ghillie/templates/serviceaccount.yaml`:
   - Conditional on `.Values.serviceAccount.create`
   - Uses `ghillie.serviceAccountName` helper

2. Create `charts/ghillie/templates/deployment.yaml`:
   - Uses all helper functions for labels
   - Loads secrets via `envFrom` with `secretRef`
   - Injects `env.normal` values directly
   - Supports command/args overrides
   - Includes securityContext and resources

3. Create `charts/ghillie/templates/service.yaml`:
   - ClusterIP type by default
   - Port from `.Values.service.port`

Validation: `helm template test charts/ghillie` renders valid YAML.

### Stage C: Optional Templates

1. Create `charts/ghillie/templates/ingress.yaml`:
   - Conditional on `.Values.ingress.enabled`
   - Supports empty host for k3d (hostless ingress)
   - Optional ingressClassName
   - TLS configuration support

2. Create `charts/ghillie/templates/externalsecret.yaml`:
   - Conditional on `.Values.secrets.externalSecret.enabled`
   - Uses ExternalSecretsOperator v1beta1 API
   - References ClusterSecretStore

3. Create `charts/ghillie/templates/configmap.yaml`:
   - Conditional on `.Values.env.normal` having content
   - Stores env values for visibility via kubectl

4. Create `charts/ghillie/templates/NOTES.txt`:
    - Display service access instructions after install
    - Show ingress URL when enabled
    - Provide kubectl port-forward command as fallback

Validation: `helm template` with various value overrides produces expected
manifests.

### Stage D: Values Schema

1. Create `charts/ghillie/values.schema.json`:
    - JSON Schema draft-07
    - Define all value types and constraints
    - Enforce enums for pullPolicy, pathType, service.type

Validation: `helm lint --strict charts/ghillie` passes with schema validation.

### Stage E: Unit Tests

1. Create `tests/helm/__init__.py` (empty)

2. Create `tests/helm/conftest.py`:
    - `chart_path` fixture returning `charts/ghillie` path
    - `fixtures_path` fixture for test values files
    - `require_helm` fixture that calls `pytest.skip()` if helm is not
      installed

3. Create `tests/helm/test_template_render.py`:
    - `_run_helm_template()` helper using subprocess
    - TestDeploymentRendering class:
      - test_deployment_uses_correct_image
      - test_deployment_command_override
      - test_deployment_env_from_secret
      - test_deployment_uses_existing_secret_name
    - TestIngressRendering class:
      - test_ingress_disabled
      - test_ingress_hostless_for_local
      - test_ingress_with_explicit_host
    - TestExternalSecretRendering class:
      - test_externalsecret_disabled_by_default
      - test_externalsecret_renders_when_enabled

4. Create `tests/helm/fixtures/values_local.yaml`:
    - Local k3d configuration with hostless ingress

5. Create `tests/helm/fixtures/values_gitops.yaml`:
    - GitOps configuration with explicit host and ExternalSecret

Validation: `uv run pytest tests/helm -v` passes.

### Stage F: BDD Tests

1. Create `tests/helm/features/helm_chart.feature`:
    - Scenario: Chart renders valid manifests with default values
    - Scenario: Chart supports local k3d configuration
    - Scenario: Chart supports GitOps preview configuration
    - Scenario: Chart passes Helm lint validation

2. Create `tests/helm/features/steps/__init__.py` (empty)

3. Create `tests/helm/features/steps/test_helm_steps.py`:
    - HelmContext TypedDict for step state
    - Given steps for chart and values fixtures
    - When steps for template rendering and lint
    - Then steps for manifest assertions
    - Use `require_helm` fixture to skip if helm unavailable

Validation: `uv run pytest tests/helm/features -v` passes.

### Stage G: Makefile Integration

1. Add to Makefile:
    - `helm-lint` target: `helm lint charts/ghillie`
    - `helm-test` target: `uv run pytest tests/helm -v`
    - Update `all` target to include `helm-lint`

Validation: `make helm-lint` and `make helm-test` pass.

### Stage H: Documentation Updates

1. Update `docs/roadmap.md`:
    - Mark Task 1.5.b as complete with `[x]`

2. Verify `docs/local-k8s-preview-design.md` aligns with implementation (no
    changes expected).

### Stage I: Quality Gates and Commit

1. Run all quality gates:
    - `make check-fmt`
    - `make lint`
    - `make typecheck`
    - `make test` (includes Helm tests)
    - `make helm-lint`

2. Commit with descriptive message following project conventions.

## Concrete Steps

All commands run from repository root `/data/leynos/Projects/ghillie`.

**Stage A:**

    mkdir -p charts/ghillie/templates

Create Chart.yaml, values.yaml, templates/_helpers.tpl (see template content in
Plan of Work).

    helm lint charts/ghillie

Expected output: `1 chart(s) linted, 0 chart(s) failed`

**Stage B-C:**

Create each template file. After each template:

    helm template test charts/ghillie

Expected: valid YAML output with no errors.

**Stage D:**

Create values.schema.json.

    helm lint --strict charts/ghillie

Expected: passes with schema validation.

**Stage E-F:**

Create test files.

    uv run pytest tests/helm -v

Expected: all tests pass.

**Stage G:**

Update Makefile.

    make helm-lint
    make helm-test

Expected: both pass.

**Stage H-I:**

Update roadmap.md. Run full quality gates:

    make check-fmt && make lint && make typecheck && make test && make helm-lint

Expected: all pass.

## Validation and Acceptance

**Quality criteria:**

- Tests: `make test` passes with all new Helm tests included
- Lint/typecheck: `make lint && make typecheck` pass
- Helm lint: `helm lint charts/ghillie` passes without warnings
- BDD coverage: all four BDD scenarios pass

**Quality method:**

    # Run full quality gate chain
    make check-fmt && make lint && make typecheck && make test

    # Verify Helm-specific validation
    helm lint charts/ghillie
    helm template test charts/ghillie | kubectl apply --dry-run=client -f -

**Acceptance behaviour:**

- Running `helm lint charts/ghillie` produces no errors.
- Running `helm template test charts/ghillie` produces valid YAML.
- Running
  `helm template test charts/ghillie -f tests/helm/fixtures/values_local.yaml`
  produces an Ingress without a host field.
- Running
  `helm template test charts/ghillie -f tests/helm/fixtures/values_gitops.yaml`
  produces an Ingress with host `pr-123.preview.example.com` and an
  ExternalSecret resource.

## Idempotence and Recovery

All steps are idempotent:

- File creation overwrites existing files.
- `helm lint` and `helm template` are read-only operations.
- pytest tests are stateless.

If a step fails:

- Fix the error in the relevant template or test file.
- Re-run `helm lint` or `pytest` to verify.
- No cleanup required; proceed from the failing step.

## Artifacts and Notes

### Chart.yaml

    apiVersion: v2
    name: ghillie
    description: Ghillie application chart for repository status reporting
    type: application
    version: 0.1.0
    appVersion: "0.1.0"

### values.yaml (key sections)

    image:
      repository: ghillie
      tag: local
      pullPolicy: IfNotPresent

    ingress:
      enabled: true
      className: ""
      hosts:
        - host: ""
          paths:
            - path: /
              pathType: Prefix

    secrets:
      existingSecretName: ""
      externalSecret:
        enabled: false
        secretStoreRef: ""
        refreshInterval: 1h
        data: []

### Ingress template (hostless support)

    {{- if .Values.ingress.enabled -}}
    spec:
      rules:
        {{- range .Values.ingress.hosts }}
        - {{- if .host }}
          host: {{ .host | quote }}
          {{- end }}
          http:
            paths:
              …
        {{- end }}
    {{- end }}

## Interfaces and Dependencies

### Helm CLI

Required: `helm` version 3.x

### New files created

    charts/ghillie/
      Chart.yaml
      values.yaml
      values.schema.json
      templates/
        _helpers.tpl
        configmap.yaml
        deployment.yaml
        externalsecret.yaml
        ingress.yaml
        NOTES.txt
        service.yaml
        serviceaccount.yaml

    tests/helm/
      __init__.py
      conftest.py
      test_template_render.py
      fixtures/
        values_local.yaml
        values_gitops.yaml
      features/
        helm_chart.feature
        steps/
          __init__.py
          test_helm_steps.py

### Modified files

    Makefile (add helm-lint, helm-test targets)
    docs/roadmap.md (mark 1.5.b complete)

### Python dependencies

No new dependencies required. Tests use:

- pytest (existing)
- pytest-bdd (existing)
- PyYAML (existing, for parsing helm template output)
- subprocess (stdlib)
