# Local k3d preview design for Ghillie

This ExecPlan is a living document. The sections `Progress`,
`Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must
be kept up to date as work proceeds.

No `PLANS.md` file is present in this repository at the time of writing.

## Purpose / big picture

Deliver a design document for a repeatable, local Kubernetes preview flow for
Ghillie that mirrors the cloud-native ephemeral previews architecture. The
design must specify how a developer will build a Ghillie container image,
provision a k3d (k3s-in-Docker) cluster, install dependencies via Helm, deploy
the Ghillie Helm chart, and reach a ready state that is observable via
`kubectl` and application logs or a health endpoint. The same Helm chart and
container image must work in the GitOps-driven ephemeral previews environment
described in `../wildside/docs/cloud-native-ephemeral-previews.md`.

Success is observable when:

- A new design document exists at `docs/local-k8s-preview-design.md` that
  covers all requirements, including sketches for Helm charts, Dockerfiles, and
  local preview scripts.
- `docs/roadmap.md` is updated with implementation tasks aligned to the design
  and staged as an upcoming phase or step.
- Markdown quality gates pass (`make fmt`, `make markdownlint`, and `make
  nixie`).

## Progress

- [x] (2026-01-03 17:54Z) Drafted initial ExecPlan with sketches and
  compatibility notes.
- [x] (2026-01-03 18:03Z) Revised ExecPlan to focus on design deliverables and
  roadmap updates only.
- [x] (2026-01-03 19:00Z) Delivered the local preview design document in
  `docs/local-k8s-preview-design.md`.
- [x] (2026-01-03 19:00Z) Updated `docs/roadmap.md` with the implementation
  roadmap.
- [x] (2026-01-03 19:00Z) Evaluated valkey-operator for dev cluster Valkey
  services and recorded the decision in the design document.
- [x] (2026-01-03 19:15Z) Ran Markdown quality gates for the new and updated
  documentation (`make fmt`, `make markdownlint`, and `make nixie`).

## Surprises & Discoveries

- Observation: `docs/k3d-python-example.md` uses k3d loopback port mapping and
  relies on the default Traefik ingress in k3s without installing Traefik.
  Evidence: `docs/k3d-python-example.md` section "The Python script".
- Observation: CloudNativePG (CNPG) publishes a `uri` field in the `*-app`
  secret that is suitable as a single database URL for application config.
  Evidence: `docs/k3d-python-example.md` secret read logic.
- Observation: The ephemeral previews design emphasises GitOps, HelmRelease,
  and Kustomize overlays, with platform services (CNPG, Redis/Valkey, ingress,
  cert-manager, ExternalDNS) managed out-of-band. Evidence:
  `../wildside/docs/cloud-native-ephemeral-previews.md` executive summary and
  repository structure sections.
- Observation: `make fmt` and `make markdownlint` fail due to existing
  markdownlint errors in `docs/k3d-python-example.md` (missing reference links
  and an overlong line). Evidence: `/tmp/ghillie-fmt.log` and
  `/tmp/ghillie-markdownlint.log`.

## Decision Log

- Decision: Use a single Helm chart for the Ghillie application with
  environment-driven values, so the same chart works for local k3d and GitOps
  ephemeral previews. Rationale: Reduces drift between local and cloud
  workflows while matching the GitOps model that deploys Helm releases with
  overlays. Date/Author: 2026-01-03, Codex
- Decision: Keep dependencies (CNPG, Valkey, ingress, cert-manager,
  ExternalDNS) out of the Ghillie chart and provision them separately in the
  local script or platform repositories. Rationale: Matches the separation of
  concerns in the ephemeral preview architecture and keeps the app chart
  focused. Date/Author: 2026-01-03, Codex
- Decision: Provide optional ExternalSecret and hostless Ingress templates,
  gated by values, to support both local secrets and Vault-backed GitOps
  environments. Rationale: Enables the same chart to consume local secrets or
  external secrets without forked templates. Date/Author: 2026-01-03, Codex
- Decision: Use a single Python CLI with subcommands for local k3d lifecycle
  (up, down, status, logs) to keep cluster management logic in one place.
  Rationale: Shared logic reduces duplication and eases maintenance.
  Date/Author: 2026-01-03, Codex
- Decision: Store the design document at `docs/local-k8s-preview-design.md`.
  Rationale: Keeps design docs discoverable alongside other architecture notes
  without colliding with the ExecPlan filename. Date/Author: 2026-01-03, Codex
- Decision: Adopt valkey-operator for local Valkey provisioning to align with
  the ephemeral previews platform approach. Rationale: Reduces drift between
  local preview and GitOps environments while keeping platform services
  operator-driven. Date/Author: 2026-01-03, Codex.

## Outcomes & Retrospective

Delivered the design document and updated the roadmap to include the preview
implementation tasks. Markdown quality gates now pass after resolving
markdownlint issues in `docs/k3d-python-example.md`.

## Context and orientation

Ghillie is a Python project in `ghillie/` with a Medallion architecture
documented in `docs/`. There is no existing HTTP server in the repository, so
the runtime entrypoint for a long-lived service must be confirmed during
implementation. The local preview environment will run in a k3d cluster and
install platform dependencies with Helm, following the patterns in
`docs/k3d-python-example.md`.

The ephemeral previews architecture
(`../wildside/docs/cloud-native-ephemeral-previews.md`) uses GitOps (Git as the
single source of truth), FluxCD HelmRelease resources, and Kustomize overlays.
Platform services (ingress, cert-manager, ExternalDNS, CNPG, Redis/Valkey,
Vault, External Secrets Operator) live in a separate repository from
application releases. The Ghillie chart must therefore:

- accept image repository and tag values for GitOps-driven updates,
- tolerate external secrets injected by the platform, and
- define ingress rules compatible with automated DNS and TLS in the cloud, but
  remain usable without those services locally.

Terms:

- k3d: A tool that runs k3s (lightweight Kubernetes) inside Docker.
- Helm chart: A packaged set of Kubernetes templates and values.
- HelmRelease: A FluxCD custom resource that installs a Helm chart.
- GitOps: Git-driven operations where Git is the source of truth.
- External Secret: A Kubernetes resource that syncs secrets from Vault or
  another backend into a Secret.

## Plan of work

Start with discovery. Identify the runtime entrypoint and ports for a
long-lived Ghillie process, or define a minimal service entrypoint if one does
not exist. Confirm required environment variables (database URL, Valkey URL,
GitHub tokens, etc.) by inspecting the code under `ghillie/` and the users'
guide. Capture these findings in the design document.

Write a design document in `docs/local-k8s-preview-design.md` that specifies
the Helm chart shape, container build approach, and local k3d lifecycle script.
The design must define how each component works locally and how it aligns with
the GitOps ephemeral previews architecture. Include sketches for the chart
templates, Dockerfile, and Python script, plus a mapping of local values to the
ephemeral-preview overlays.

Assess whether `https://github.com/hyperspike/valkey-operator` is suitable for
providing Valkey services inside the local dev cluster while keeping parity
with the ephemeral previews platform. Capture the trade-offs and either adopt
the operator in the design or explicitly reject it with rationale, and reflect
the choice in the roadmap.

Update `docs/roadmap.md` to include implementation tasks for the local preview
environment. The roadmap must split the work into measurable tasks and state
dependencies. Ensure the roadmap refers back to the new design document as the
source of truth.

## Concrete steps

Run all commands from the repository root unless noted otherwise. Prefer
Makefile targets and use `timeout 300` for commands unless they are already
bounded by `--timeout`. Use `set -o pipefail` and `tee` when running lint,
formatting, or test suites to preserve exit codes and logs.

1. Discover the runtime entrypoint and required environment:

    rg -n "main\\(|__main__|dramatiq|http" ghillie docs

2. Draft the design document in `docs/local-k8s-preview-design.md` using the
   sketches below as a starting point and include explicit references to
   `docs/k3d-python-example.md` and
   `../wildside/docs/cloud-native-ephemeral-previews.md`.

3. Update `docs/roadmap.md` to add the implementation work as a new step or
   phase, referencing the design document.

4. Run Markdown quality gates after documentation updates:

    set -o pipefail
    timeout 300 make fmt | tee /tmp/ghillie-fmt.log
    timeout 300 make markdownlint | tee /tmp/ghillie-markdownlint.log
    timeout 300 make nixie | tee /tmp/ghillie-nixie.log

5. If any Python code is updated during documentation (not expected), run the
   Python quality gates:

    set -o pipefail
    timeout 300 make lint | tee /tmp/ghillie-lint.log
    timeout 300 make typecheck | tee /tmp/ghillie-typecheck.log
    timeout 300 make test | tee /tmp/ghillie-test.log

## Validation and acceptance

The work is acceptable when the following behaviours are observed:

- A design document exists at `docs/local-k8s-preview-design.md` that:
  - describes the local k3d flow end to end,
  - specifies Helm chart structure and values,
  - includes sketches for chart templates, Dockerfiles, and scripts, and
  - explains alignment with the GitOps ephemeral previews architecture.
- `docs/roadmap.md` includes new implementation tasks tied to the design.
- Documentation updates pass `make fmt`, `make markdownlint`, and `make nixie`.

## Idempotence and recovery

The design must specify idempotence and recovery for the future scripts. It
must state that the local script is safe to rerun, describe reuse or cleanup
for existing clusters, and explain how to recover from failed Helm installs.

## Artifacts and notes

The detailed Helm chart, Dockerfile, and local CLI sketches live in
`docs/local-k8s-preview-design.md` and should be treated as the source of
truth. This ExecPlan should only summarize the required artifacts so the design
work stays centralized.

- Helm chart layout plus template sketches for deployment, ingress, and
  ExternalSecret integration.
- Dockerfile stages for building and running the Ghillie container image.
- Python local-k8s CLI structure, including Config and subcommand flow.

Keep the sketches in the design document and reference them here to avoid drift.

## Interfaces and dependencies

Dependencies (to be documented in the design):

- `docker`, `k3d`, `kubectl`, and `helm` must be available on the PATH.
- Helm repositories: `cnpg` and `bitnami` for CNPG and Valkey.
- A container registry or local image import for k3d.

Python script interface in `scripts/local_k8s.py`:

    def main(argv: list[str] | None = None) -> int: …
    def cmd_up(cfg: Config) -> None: …
    def cmd_down(cfg: Config) -> None: …
    def cmd_status(cfg: Config) -> None: …
    def cmd_logs(cfg: Config) -> None: …

Environment variables (document and parse in the script):

    GHILLIE_CHART=./charts/ghillie
    GHILLIE_RELEASE=ghillie
    GHILLIE_NAMESPACE=ghillie-dev-<suffix>
    GHILLIE_IMAGE_REPO=ghillie
    GHILLIE_IMAGE_TAG=local
    INGRESS_PORT=0 (0 or unset means pick a free loopback port)
    HELM_ARGS="--values ./dev-values.yaml --set image.tag=local"

Helm values interface in `charts/ghillie/values.yaml` (documented in the
design):

- `image.repository` (string)
- `image.tag` (string)
- `image.pullPolicy` (string)
- `command` (list of strings)
- `args` (list of strings)
- `service.port` (integer)
- `ingress.enabled` (bool)
- `ingress.hosts` (list)
- `ingress.tls` (list)
- `env.normal` (map)
- `secrets.existingSecretName` (string)
- `secrets.externalSecret.enabled` (bool)
- `secrets.externalSecret.secretStoreRef` (string)
- `secrets.externalSecret.data` (list)

## Revision note (required when editing an ExecPlan)

Revised the plan to focus on design deliverables, added the target design
document path (`docs/local-k8s-preview-design.md`), and aligned section names
with the ExecPlan requirements.

Updated progress to reflect completed design and roadmap deliverables, recorded
the valkey-operator decision, and noted markdownlint blocking issues, so the
remaining work is limited to resolving documentation lint failures.

Marked Markdown quality gates as complete after fixing markdownlint issues and
rerunning `make fmt`, `make markdownlint`, and `make nixie`.

Refreshed the quality-gate timestamp after re-running the documentation checks.

Removed duplicate template sketches from the ExecPlan, referencing the design
document instead, and aligned ExternalSecret template guidance to use `toYaml`
for proper YAML rendering.
