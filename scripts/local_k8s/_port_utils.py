"""Port parsing helpers for k3d cluster metadata."""

from __future__ import annotations

# Port range constants for validation
_MIN_PORT = 1024
_MAX_PORT = 65535


def _is_http_port(container_port: str) -> bool:
    """Check if the container port is HTTP (port 80).

    Args:
        container_port: Container port string (e.g., "80/tcp").

    Returns:
        True if the port is HTTP port 80.

    """
    return container_port.startswith("80/")


def _parse_host_port(host_port_str: str) -> int | None:
    """Parse a host port string to an integer.

    Only valid port numbers in the range 1024-65535 are accepted.

    Args:
        host_port_str: Host port string to parse.

    Returns:
        The parsed port number, or None if parsing fails or port is invalid.

    """
    try:
        port = int(host_port_str)
    except ValueError:
        return None
    else:
        if _MIN_PORT <= port <= _MAX_PORT:
            return port
        return None


def _find_host_port_in_mappings(mappings: list[dict] | None) -> int | None:
    """Find the first valid host port from a list of port mappings.

    Args:
        mappings: List of port mapping dicts with "HostPort" keys.

    Returns:
        The first valid host port, or None if not found.

    """
    for mapping in mappings or []:
        host_port_str = mapping.get("HostPort")
        if host_port_str:
            port = _parse_host_port(host_port_str)
            if port is not None:
                return port
    return None


def _find_http_port_in_node(node: dict) -> int | None:
    """Find HTTP host port in a single node's port mappings.

    Returns the first valid HTTP host port mapping found in the node.

    Args:
        node: k3d node dict with portMappings.

    Returns:
        Host port mapped to container port 80, or None if not found.

    """
    port_mappings = node.get("portMappings") or {}
    for container_port, mappings in port_mappings.items():
        if _is_http_port(container_port):
            port = _find_host_port_in_mappings(mappings)
            if port is not None:
                return port
    return None


def _extract_http_host_port(cluster: dict) -> int | None:
    """Extract HTTP host port from cluster node port mappings.

    Searches through cluster nodes for port mappings that map container port 80
    to a host port. Returns the first valid HTTP host port found across all
    cluster nodes.

    Args:
        cluster: k3d cluster dict from JSON output.

    Returns:
        Host port mapped to container port 80, or None if not found.

    """
    for node in cluster.get("nodes") or []:
        port = _find_http_port_in_node(node)
        if port is not None:
            return port
    return None
