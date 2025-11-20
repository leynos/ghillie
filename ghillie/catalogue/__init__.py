"""Estate catalogue schema and validation utilities."""

from __future__ import annotations

from .loader import lint_catalogue, load_catalogue
from .models import (
    Catalogue,
    Component,
    ComponentLink,
    NoiseFilters,
    Programme,
    Project,
    Repository,
    StatusSettings,
)
from .schema import build_catalogue_schema, write_catalogue_schema
from .validation import CatalogueValidationError, validate_catalogue

__all__ = [
    "Catalogue",
    "CatalogueValidationError",
    "Component",
    "ComponentLink",
    "NoiseFilters",
    "Programme",
    "Project",
    "Repository",
    "StatusSettings",
    "build_catalogue_schema",
    "lint_catalogue",
    "load_catalogue",
    "validate_catalogue",
    "write_catalogue_schema",
]
