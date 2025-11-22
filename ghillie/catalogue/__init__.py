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

from .importer import (
    CatalogueImporter,
    CatalogueImportResult,
    build_importer_from_url,
    import_catalogue_job,
)
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
from .storage import (
    ComponentEdgeRecord,
    ComponentRecord,
    Estate,
    ProjectRecord,
    RepositoryRecord,
    init_catalogue_storage,
)
from .validation import CatalogueValidationError, validate_catalogue
from .watch import GitCatalogueWatcher

__all__ = [
    "Catalogue",
    "CatalogueImportResult",
    "CatalogueImporter",
    "CatalogueValidationError",
    "Component",
    "ComponentEdgeRecord",
    "ComponentLink",
    "ComponentRecord",
    "Estate",
    "GitCatalogueWatcher",
    "NoiseFilters",
    "Programme",
    "Project",
    "ProjectRecord",
    "Repository",
    "RepositoryRecord",
    "StatusSettings",
    "build_catalogue_schema",
    "build_importer_from_url",
    "import_catalogue_job",
    "init_catalogue_storage",
    "lint_catalogue",
    "load_catalogue",
    "validate_catalogue",
    "write_catalogue_schema",
]
