"""Port parsing helpers for k3d cluster metadata."""

from __future__ import annotations

_MIN_PORT = 1024
_MAX_PORT = 65535


def _is_http_port(container_port: str) -> bool:
    """Return True when the container port refers to HTTP (port 80)."""
    return container_port.startswith("80/")


def _parse_host_port(host_port_str: str | None) -> int | None:
    """Parse a host port string into an integer within the valid range."""
    if not host_port_str:
        return None
    try:
        port = int(host_port_str)
    except ValueError:
        return None
    if _MIN_PORT <= port <= _MAX_PORT:
        return port
    return None


def _find_host_port_in_mappings(mappings: list[dict] | None) -> int | None:
    """Return the first valid host port from a list of port mappings."""
    if not mappings:
        return None
    for mapping in mappings:
        port = _parse_host_port(mapping.get("HostPort"))
        if port is not None:
            return port
    return None


def extract_http_host_port(cluster: dict) -> int | None:
    """Extract the HTTP host port from a k3d cluster definition."""
    nodes = cluster.get("nodes")
    if not nodes:
        return None
    for node in nodes:
        port_mappings = node.get("portMappings")
        if not port_mappings:
            continue
        for container_port, mappings in port_mappings.items():
            if not _is_http_port(container_port):
                continue
            port = _find_host_port_in_mappings(mappings)
            if port is not None:
                return port
    return None
