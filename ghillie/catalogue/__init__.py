"""Estate catalogue utilities, importer, and watcher APIs.

This package spans three slices of the catalogue story:

* **Schema & validation** - typed msgspec models, YAML loading, and JSON
  Schema generation for catalogue files.
* **Importer & storage** - reconciliation of catalogue commits into relational
  tables, with Dramatiq actors for async execution and helpers to initialise
  schemas.
* **Watchers** - a git watcher that spots new commits in the catalogue repo and
  enqueues imports.

Quick examples
--------------

Validate a catalogue file::

    >>> from ghillie.catalogue import lint_catalogue
    >>> catalogue = lint_catalogue("examples/wildside-catalogue.yaml")

Export schema and validated JSON::

    >>> from ghillie.catalogue import build_catalogue_schema
    >>> schema = build_catalogue_schema()

Import into a database (async)::

    >>> from pathlib import Path
    >>> from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    >>> from ghillie.catalogue import CatalogueImporter, init_catalogue_storage
    >>> engine = create_async_engine("sqlite+aiosqlite:///catalogue.db")
    >>> await init_catalogue_storage(engine)
    >>> importer = CatalogueImporter(async_sessionmaker(engine, expire_on_commit=False))
    >>> await importer.import_path(
    ...     Path("examples/wildside-catalogue.yaml"), commit_sha="abc123"
    ... )

Run via Dramatiq actor from a watcher::

    >>> from ghillie.catalogue import GitCatalogueWatcher, import_catalogue_job
    >>> watcher = GitCatalogueWatcher(
    ...     Path("/repo/engineering-catalogue"),
    ...     "catalogue.yaml",
    ...     "sqlite:///catalogue.db",
    ... )
    >>> watcher.tick()  # enqueues import_catalogue_job with the latest commit
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
    CatalogueImportRecord,
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
    "CatalogueImportRecord",
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
