"""Local k3d preview environment management package."""

from __future__ import annotations

from local_k8s.cnpg import (
    create_cnpg_cluster,
    install_cnpg_operator,
    read_pg_app_uri,
    wait_for_cnpg_ready,
)
from local_k8s.config import Config, HelmOperatorSpec
from local_k8s.deployment import (
    build_docker_image,
    create_app_secret,
    install_ghillie_chart,
    print_status,
    tail_logs,
)
from local_k8s.k3d import (
    cluster_exists,
    create_k3d_cluster,
    delete_k3d_cluster,
    get_cluster_ingress_port,
    import_image_to_k3d,
    kubeconfig_env,
    write_kubeconfig,
)
from local_k8s.k8s import (
    create_namespace,
    ensure_namespace,
    namespace_exists,
)
from local_k8s.operators import install_helm_operator
from local_k8s.orchestration import (
    setup_environment,
    show_environment_status,
    stream_environment_logs,
    teardown_environment,
)
from local_k8s.validation import (
    ExecutableNotFoundError,
    LocalK8sError,
    PortMismatchError,
    SecretDecodeError,
    b64decode_k8s_secret_field,
    pick_free_loopback_port,
    require_exe,
)
from local_k8s.valkey import (
    create_valkey_instance,
    install_valkey_operator,
    read_valkey_uri,
    wait_for_valkey_ready,
)

# Mark the recommended public surface for consumers
PUBLIC_API = [
    "Config",
    "HelmOperatorSpec",
    "setup_environment",
    "teardown_environment",
    "show_environment_status",
    "stream_environment_logs",
]
# Keep __all__ as-is for now; PUBLIC_API helps guide future slimming.

__all__ = [
    "Config",
    "ExecutableNotFoundError",
    "HelmOperatorSpec",
    "LocalK8sError",
    "PortMismatchError",
    "SecretDecodeError",
    "b64decode_k8s_secret_field",
    "build_docker_image",
    "cluster_exists",
    "create_app_secret",
    "create_cnpg_cluster",
    "create_k3d_cluster",
    "create_namespace",
    "create_valkey_instance",
    "delete_k3d_cluster",
    "ensure_namespace",
    "get_cluster_ingress_port",
    "import_image_to_k3d",
    "install_cnpg_operator",
    "install_ghillie_chart",
    "install_helm_operator",
    "install_valkey_operator",
    "kubeconfig_env",
    "namespace_exists",
    "pick_free_loopback_port",
    "print_status",
    "read_pg_app_uri",
    "read_valkey_uri",
    "require_exe",
    "setup_environment",
    "show_environment_status",
    "stream_environment_logs",
    "tail_logs",
    "teardown_environment",
    "wait_for_cnpg_ready",
    "wait_for_valkey_ready",
    "write_kubeconfig",
]
