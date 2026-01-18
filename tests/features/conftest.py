"""Shared fixtures for BDD feature tests.

This module imports VidaiMock fixtures from integration tests to enable
LLM integration testing in BDD scenarios.
"""

from __future__ import annotations

# Re-export VidaiMock fixtures for BDD tests
from tests.integration.conftest import openai_config_for_vidaimock, vidaimock_server

__all__ = ["openai_config_for_vidaimock", "vidaimock_server"]
