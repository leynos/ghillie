"""Replaceable collaborators for the estate-management service.

The service needs three things it does not own: something that builds a
catalogue importer, something that parses untrusted YAML, and something that
writes its D21 records. Grouping them in one value keeps the constructor
small, and gives tests a single seam for substituting a parse function, an
importer, or a deterministic clock.

Nothing here reaches for a module global at call time: the defaults name the
production implementations, and a caller can replace any of them.
"""

from __future__ import annotations

import collections.abc as cabc
import dataclasses
import typing as typ

from ghillie.catalogue.importer import CatalogueImporter
from ghillie.catalogue.loader import parse_catalogue_text
from ghillie.catalogue.models import Catalogue
from ghillie.estate.observability import MutationRecorder

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

ImporterFactory = cabc.Callable[..., CatalogueImporter]
"""Build an importer for one estate.

The parameters are the session factory plus keyword-only ``estate_key`` and
``estate_name``, which is exactly :class:`CatalogueImporter`'s signature. A
callable rather than a class keeps a test free to return a double.
"""

CatalogueParser = cabc.Callable[[str], Catalogue]
"""Parse the request's YAML text into a validated catalogue."""


def _default_importer_factory(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    estate_key: str,
    estate_name: str | None,
) -> CatalogueImporter:
    """Build the production importer over the service's session factory."""
    return CatalogueImporter(
        session_factory,
        estate_key=estate_key,
        estate_name=estate_name,
    )


@dataclasses.dataclass(frozen=True, slots=True)
class EstateCollaborators:
    """The importer, parser, and recorder an estate service uses.

    Attributes
    ----------
    importer_factory:
        Builds the catalogue importer for one estate.
    parse_catalogue:
        Parses untrusted YAML. The service runs it off the event loop.
    recorder:
        Writes the D21 mutation records and holds the clock those records use.

    """

    importer_factory: ImporterFactory = _default_importer_factory
    parse_catalogue: CatalogueParser = parse_catalogue_text
    recorder: MutationRecorder = dataclasses.field(default_factory=MutationRecorder)
