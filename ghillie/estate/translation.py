"""Translate catalogue validation failures into the estate error vocabulary.

Adapters depend on :mod:`ghillie.estate.errors` alone, so every failure has to
be translated before it leaves the service. Storage failures are classified at
the persistence boundary in :mod:`ghillie.estate.persistence`; this module keeps
only the pure catalogue translation, because a rejected document is a domain
outcome rather than a storage failure. The function here never logs, so the
service keeps ownership of the D21 record that accompanies each outcome.
"""

from __future__ import annotations

import typing as typ

from ghillie.estate.errors import CatalogueRejectedError, Issue

if typ.TYPE_CHECKING:
    from ghillie.catalogue.validation import CatalogueValidationError


def catalogue_rejected(exc: CatalogueValidationError) -> CatalogueRejectedError:
    """Translate catalogue validation messages into port issues.

    Parameters
    ----------
    exc:
        The validation failure raised while parsing the uploaded document.

    Returns
    -------
    CatalogueRejectedError
        One ``catalogue_schema`` issue per validation message.

    """
    issues = tuple(
        Issue(code="catalogue_schema", message=message) for message in exc.issues
    )
    return CatalogueRejectedError(issues)
