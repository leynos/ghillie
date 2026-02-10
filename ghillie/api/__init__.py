"""Ghillie HTTP API layer.

This package provides the Falcon ASGI application and supporting
infrastructure for the Ghillie runtime HTTP surface.

Public API
----------
create_app
    Application factory that configures the Falcon ASGI app with
    health endpoints and optionally with domain endpoints when
    database dependencies are provided.
"""

from ghillie.api.app import create_app

__all__ = ["create_app"]
