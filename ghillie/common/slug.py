"""Repository slug utilities.

Repository slugs are GitHub identifiers in ``owner/name`` format. They are not
filesystem paths, even though they use ``/`` as a separator, so they should be
parsed using these helpers rather than ``pathlib``.
"""

from __future__ import annotations


def repo_slug(owner: str, name: str) -> str:
    """Build a repository slug from owner and name.

    Combines the repository owner and name into the standard GitHub slug
    notation used throughout the catalogue and Silver layers.

    Parameters
    ----------
    owner:
        GitHub repository owner (organisation or user).
    name:
        GitHub repository name.

    Returns
    -------
    str
        Slug in ``owner/name`` format.

    Examples
    --------
    >>> repo_slug("leynos", "ghillie")
    'leynos/ghillie'

    """
    return f"{owner}/{name}"


def parse_repo_slug(slug: str) -> tuple[str, str]:
    """Parse a repository slug into owner and name.

    Parameters
    ----------
    slug:
        Repository slug in ``owner/name`` format.

    Returns
    -------
    tuple[str, str]
        ``(owner, name)``.

    Raises
    ------
    ValueError
        If the slug is not in ``owner/name`` format.

    Examples
    --------
    >>> parse_repo_slug("leynos/ghillie")
    ('leynos', 'ghillie')

    """
    if slug.count("/") != 1:
        msg = f"Invalid repository slug: expected 'owner/name', got {slug!r}"
        raise ValueError(msg)

    owner, name = slug.split("/")
    if not owner or not name:
        msg = f"Invalid repository slug: expected 'owner/name', got {slug!r}"
        raise ValueError(msg)

    return owner, name
