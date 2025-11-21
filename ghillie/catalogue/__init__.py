"""Estate catalogue schema and validation utilities.

This package exposes typed models, YAML loading helpers, validation rules, and
JSON Schema generation for the Ghillie estate catalogue format.

Examples
--------
Load and validate a catalogue file::

    >>> from ghillie.catalogue import lint_catalogue
    >>> catalogue = lint_catalogue("examples/wildside-catalogue.yaml")

Generate and export the JSON Schema::

    >>> from ghillie.catalogue import build_catalogue_schema
    >>> schema = build_catalogue_schema()

Perform programmatic validation::

    >>> from ghillie.catalogue import load_catalogue, validate_catalogue
    >>> catalogue = load_catalogue("path/to/catalogue.yaml")
    >>> validated = validate_catalogue(catalogue)

"""

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
