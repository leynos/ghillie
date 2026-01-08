"""Pytest configuration for scripts tests.

Adds the scripts directory to the Python path for imports.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add scripts directory to path so we can import local_k8s
_scripts_dir = Path(__file__).resolve().parents[1]
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))
