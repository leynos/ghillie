"""Repository slug utilities."""

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
