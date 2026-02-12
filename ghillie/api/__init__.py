"""Ghillie HTTP API layer.

This package provides the Falcon Asynchronous Server Gateway Interface
(ASGI) application and supporting infrastructure for the Ghillie
runtime HTTP surface.

Usage
-----
Create and run the application::

    from ghillie.api import create_app

    app = create_app()              # health-only mode
    app = create_app(dependencies)  # full mode with domain endpoints

Public API
----------
create_app
    Application factory that configures the Falcon ASGI app with
    health endpoints and optionally with domain endpoints when
    database dependencies are provided.
"""

from ghillie.api.app import create_app

__all__ = ["create_app"]
