# k3d Python example

Here’s a pragmatic “one Python script + a couple of knobs” guide that does
exactly what you described:

- creates a k3d cluster
- picks a random free **loopback** port and maps it to Traefik’s HTTP entrypoint
- creates a **unique namespace** for *your* app
- installs **CloudNativePG (CNPG)** via Helm
- installs **Valkey** via Helm
- installs **your existing app Helm chart**
- creates a plain Kubernetes **Ingress** that Traefik will route

This leans on k3d’s recommended ingress pattern: expose port **80 on the k3d
load balancer** to a host port, then use a normal `Ingress` resource.
([K3D](https://k3d.io/v5.3.0/usage/exposing_services/)) k3s (which k3d runs)
ships Traefik by default and Traefik listens on 80/443 via a LoadBalancer
Service, so we don’t install Traefik separately.
([K3s](https://docs.k3s.io/networking/networking-services))

## Prereqs (WSL2-friendly)

You need these CLIs available inside the environment where you run the script:

- `docker` (usually Docker Desktop with WSL2 integration)
- `k3d`
- `kubectl`
- `helm`

k3d’s port mapping format supports binding to a specific IP (like `127.0.0.1`)
as `IP:HOSTPORT:CONTAINERPORT@nodefilter`, which is what we use for the
loopback-only ingress port.
([Loculus](https://loculus.org/for-administrators/setup-with-k3d-and-nginx/))

## The Python script

Save as `dev_up.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import textwrap
import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Config:
    # Your app chart: either a local path (./charts/myapp) or a repo ref (myrepo/myapp)
    app_chart: str
    # Release name for your app (Helm release)
    app_release: str = "app"
    # Service name backing the HTTP app (defaults to release name; override if your chart differs)
    app_service: Optional[str] = None

    # Set explicitly if you want a stable port; otherwise we pick a random free one.
    ingress_port: Optional[int] = None

    # CNPG bits
    cnpg_release: str = "cnpg"
    cnpg_namespace: str = "cnpg-system"

    # Valkey bits (Bitnami chart in this example)
    valkey_release: str = "valkey"
    # If you prefer auth, set VALKEY_PASSWORD in env and flip auth_enabled below.
    valkey_auth_enabled: bool = False

    # Cluster shape
    agents: int = 1


def require_exe(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"Missing required executable: {name!r} (not found in PATH)")


def run(
    cmd: list[str],
    *,
    env: Optional[dict[str, str]] = None,
    input_text: Optional[str] = None,
    capture: bool = False,
) -> str:
    printable = " ".join(shlex.quote(c) for c in cmd)
    print(f"+ {printable}")

    res = subprocess.run(
        cmd,
        input=input_text,
        text=True,
        env=env,
        stdout=subprocess.PIPE if (capture or input_text is not None) else None,
        stderr=subprocess.STDOUT if (capture or input_text is not None) else None,
        check=False,
    )
    out = (res.stdout or "").strip()

    if res.returncode != 0:
        msg = f"Command failed (exit {res.returncode}): {printable}"
        if out:
            msg += "\n\n--- output ---\n" + out
        raise RuntimeError(msg)

    return out


def pick_free_loopback_port() -> int:
    # Bind to port 0 to get a free ephemeral port on 127.0.0.1.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def b64decode_k8s_secret_field(b64_text: str) -> str:
    return base64.b64decode(b64_text.encode("ascii")).decode("utf-8")


def main() -> None:
    # ---- knobs via env ----
    app_chart = os.environ.get("APP_CHART", "").strip()
    if not app_chart:
        raise SystemExit(
            "Set APP_CHART to your chart path or ref, e.g.\n"
            "  APP_CHART=./charts/my-http-app\n"
            "or\n"
            "  APP_CHART=myrepo/my-http-app\n"
        )

    app_release = os.environ.get("APP_RELEASE", "app").strip()
    app_service = os.environ.get("APP_SERVICE")  # optional

    ingress_port_env = os.environ.get("INGRESS_PORT")
    ingress_port = int(ingress_port_env) if ingress_port_env else None

    valkey_password = os.environ.get("VALKEY_PASSWORD", "").strip()

    cfg = Config(
        app_chart=app_chart,
        app_release=app_release,
        app_service=app_service,
        ingress_port=ingress_port,
        valkey_auth_enabled=bool(valkey_password),  # enable auth if password supplied
    )

    # ---- prerequisites ----
    for exe in ("docker", "k3d", "kubectl", "helm"):
        require_exe(exe)

    suffix = uuid.uuid4().hex[:8]
    cluster = f"dev-{suffix}"
    namespace = f"dev-{suffix}"

    port = cfg.ingress_port or pick_free_loopback_port()

    # Map host 127.0.0.1:PORT -> load balancer container port 80 (Traefik listens on 80 in-cluster)
    port_mapping = f"127.0.0.1:{port}:80@loadbalancer"

    print("\n--- creating k3d cluster ---")
    run(
        ["k3d", "cluster", "create", cluster, "--agents", str(cfg.agents), "--port", port_mapping],
    )

    # Use a dedicated kubeconfig for this cluster (avoid polluting ~/.kube/config).
    kubeconfig_path = run(["k3d", "kubeconfig", "write", cluster], capture=True)
    kube_env = os.environ.copy()
    kube_env["KUBECONFIG"] = kubeconfig_path

    print("\n--- cluster sanity check ---")
    run(["kubectl", "cluster-info"], env=kube_env)

    print("\n--- creating unique namespace for the app ---")
    run(["kubectl", "create", "namespace", namespace], env=kube_env)

    print("\n--- adding helm repos ---")
    run(["helm", "repo", "add", "cnpg", "https://cloudnative-pg.github.io/charts", "--force-update"], env=kube_env)
    run(["helm", "repo", "add", "bitnami", "https://charts.bitnami.com/bitnami", "--force-update"], env=kube_env)
    run(["helm", "repo", "update"], env=kube_env)

    print("\n--- installing CNPG operator ---")
    run(
        [
            "helm", "upgrade", "--install", cfg.cnpg_release, "cnpg/cloudnative-pg",
            "--namespace", cfg.cnpg_namespace, "--create-namespace",
            "--wait", "--timeout", "10m",
        ],
        env=kube_env,
    )

    print("\n--- creating a small Postgres cluster via CNPG (in your unique namespace) ---")
    pg_name = f"pg-{suffix}"
    pg_manifest = textwrap.dedent(f"""\
        apiVersion: postgresql.cnpg.io/v1
        kind: Cluster
        metadata:
          name: {pg_name}
          namespace: {namespace}
        spec:
          instances: 1
          storage:
            size: 1Gi
          bootstrap:
            initdb:
              database: app
              owner: app
    """)
    run(["kubectl", "apply", "-f", "-"], env=kube_env, input_text=pg_manifest)

    # CNPG creates a secret named "<cluster>-app" by default (unless you override it).
    # It includes a ready-to-use connection URI.
    print("\n--- waiting for CNPG app secret (connection info) ---")
    run(
        [
            "kubectl", "wait", "--for=condition=Ready", "pod", "-l",
            f"cnpg.io/cluster={pg_name}", "-n", namespace, "--timeout=10m",
        ],
        env=kube_env,
    )

    secret_json = run(
        ["kubectl", "get", "secret", f"{pg_name}-app", "-n", namespace, "-o", "json"],
        env=kube_env,
        capture=True,
    )
    secret = json.loads(secret_json)
    uri_b64 = secret["data"].get("uri", "")
    pg_uri = b64decode_k8s_secret_field(uri_b64) if uri_b64 else "<no uri field found>"

    print(f"CNPG Postgres URI (from secret {pg_name}-app):\n  {pg_uri}")

    print("\n--- installing Valkey via Helm ---")
    valkey_args = [
        "helm", "upgrade", "--install", cfg.valkey_release, "bitnami/valkey",
        "--namespace", namespace, "--wait", "--timeout", "10m",
    ]
    if cfg.valkey_auth_enabled:
        valkey_args += ["--set", "auth.enabled=true", "--set", f"auth.password={valkey_password}"]
    else:
        valkey_args += ["--set", "auth.enabled=false"]

    run(valkey_args, env=kube_env)

    print("\n--- installing your app chart ---")
    # You can pass additional values via HELM_ARGS, e.g.
    #   HELM_ARGS="--values ./dev-values.yaml --set image.tag=local"
    extra = shlex.split(os.environ.get("HELM_ARGS", "").strip()) if os.environ.get("HELM_ARGS") else []
    run(
        [
            "helm", "upgrade", "--install", cfg.app_release, cfg.app_chart,
            "--namespace", namespace, "--wait", "--timeout", "10m",
            *extra,
        ],
        env=kube_env,
    )

    svc_name = cfg.app_service or cfg.app_release

    print("\n--- creating ingress (Traefik) for the app service ---")
    # Infer the service port (first port on the Service).
    svc_json = run(["kubectl", "get", "svc", svc_name, "-n", namespace, "-o", "json"], env=kube_env, capture=True)
    svc = json.loads(svc_json)
    svc_port = int(svc["spec"]["ports"][0]["port"])

    ingress_manifest = textwrap.dedent(f"""\
        apiVersion: networking.k8s.io/v1
        kind: Ingress
        metadata:
          name: {cfg.app_release}-ingress
          namespace: {namespace}
          annotations:
            ingress.kubernetes.io/ssl-redirect: "false"
        spec:
          rules:
          - http:
              paths:
              - path: /
                pathType: Prefix
                backend:
                  service:
                    name: {svc_name}
                    port:
                      number: {svc_port}
    """)
    run(["kubectl", "apply", "-f", "-"], env=kube_env, input_text=ingress_manifest)

    print("\n--- done ---")
    print(f"Namespace:   {namespace}")
    print(f"Cluster:     {cluster}")
    print(f"KUBECONFIG:  {kubeconfig_path}")
    print(f"URL:         http://127.0.0.1:{port}/")
    print("\nTip: to inspect what's running:\n  kubectl -n %s get all,ingress,secret\n" % namespace)


if __name__ == "__main__":
    main()
```

What the script relies on (so you can reason about it, not just chant the
incantations):

- It exposes Traefik by mapping **host port → port 80 on the k3d load balancer
  container**, which k3d recommends for ingress.
  ([K3D](https://k3d.io/v5.3.0/usage/exposing_services/))
- k3d’s `--port` format supports `127.0.0.1:HOSTPORT:CONTAINERPORT@...`, which
  lets you keep the ingress bound to loopback only.
  ([Loculus](https://loculus.org/for-administrators/setup-with-k3d-and-nginx/))
- The CNPG Helm repo and install command come from CloudNativePG’s chart docs.
  ([CloudNativePG](https://cloudnative-pg.io/charts/))
- CNPG generates an `*-app` secret by default that includes a ready-to-use
  connection URI (the script prints it).
  ([CloudNativePG](https://cloudnative-pg.io/docs/1.27/applications))
- Bitnami’s Helm repo add pattern comes from their charts page; the Valkey
  chart exists in the Bitnami charts tree.
  ([charts.bitnami.com](https://charts.bitnami.com/))

## Run it

From the same shell where `docker` can see your Docker Desktop engine:

```bash
chmod +x dev_up.py

# Minimum: point at your existing app chart
APP_CHART=./charts/my-http-app ./dev_up.py
```

Optional knobs you’ll actually use:

```bash
# Choose your Helm release name for the app
APP_CHART=./charts/my-http-app APP_RELEASE=myapp ./dev_up.py

# If your chart’s Service name doesn’t match release name
APP_CHART=./charts/my-http-app APP_RELEASE=myapp APP_SERVICE=myapp-web ./dev_up.py

# If you want to force a port instead of random
APP_CHART=./charts/my-http-app INGRESS_PORT=18080 ./dev_up.py

# Pass extra Helm args into the app install (values file, image tag, etc.)
APP_CHART=./charts/my-http-app \
HELM_ARGS="--values ./dev-values.yaml --set image.tag=local" \
./dev_up.py

# Turn Valkey auth on (script enables it if VALKEY_PASSWORD is set)
APP_CHART=./charts/my-http-app VALKEY_PASSWORD=devpass ./dev_up.py
```

It prints a URL like `http://127.0.0.1:49213/`.

## Cleanup

k3d clusters are disposable; delete the whole universe in one go:

```bash
k3d cluster delete dev-<suffix>
```

(If you kept the script output, it prints the exact cluster name.)

## A couple of sharp edges to know about (so they don’t bite you later)

IngressClass name weirdness: k3s historically didn’t always create a default
`IngressClass` called `traefik`, and different setups handle `ingressClassName`
differently. The script avoids that by creating an Ingress with no
`ingressClassName` and relies on k3s’ default Traefik behaviour, which k3d
documents in its ingress example.
([K3D](https://k3d.io/v5.3.0/usage/exposing_services/))

If your chart already creates an Ingress, skip the script’s Ingress step (or
you’ll end up with two). The clean way: move ingress creation into your chart
values and let Helm own it.

That’s the whole machine.

When you start wiring the app to Postgres + Valkey, the CNPG `*-app` secret
gives you an actual `uri` field you can inject straight into your Deployment
(or Helm values) without inventing service names.
([CloudNativePG](https://cloudnative-pg.io/docs/1.27/applications))
