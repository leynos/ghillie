"""Shared constants for status model configuration.

This module provides constants used across the status model subsystem,
ensuring consistent validation bounds and configuration values.

Constants
---------
MIN_TEMPERATURE : float
    Minimum allowed temperature value for OpenAI API requests (0.0).
MAX_TEMPERATURE : float
    Maximum allowed temperature value for OpenAI API requests (2.0).

Usage
-----
Import and reference constants directly::

    from ghillie.status.constants import MIN_TEMPERATURE, MAX_TEMPERATURE

    if not MIN_TEMPERATURE <= value <= MAX_TEMPERATURE:
        raise ValueError("Temperature out of range")

Notes
-----
These constants are used by:
- ``ghillie.status.config`` for validation during configuration parsing
- ``ghillie.status.errors`` for generating descriptive error messages

"""

from __future__ import annotations

# Validation bounds for temperature (OpenAI API range)
MIN_TEMPERATURE: float = 0.0
MAX_TEMPERATURE: float = 2.0
