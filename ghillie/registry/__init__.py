"""Repository registry for managing GitHub ingestion targets.

The registry bridges the catalogue domain (source of truth for estate
configuration) with the Silver layer (operational data store for ingestion
and reporting). It provides:

- Synchronisation from catalogue RepositoryRecord to Silver Repository
- Enable/disable ingestion control per repository
- Listing of active repositories for the ingestion worker

Usage
-----
Synchronise catalogue repositories to Silver::

    from ghillie.registry import RepositoryRegistryService

    service = RepositoryRegistryService(
        catalogue_session_factory=catalogue_session_factory,
        silver_session_factory=silver_session_factory,
    )
    result = await service.sync_from_catalogue(estate_key="default")

List repositories enabled for ingestion::

    repos = await service.list_active_repositories()
    for repo in repos:
        print(f"{repo.slug}: enabled={repo.ingestion_enabled}")

Toggle ingestion for a repository::

    await service.disable_ingestion("leynos", "wildside")
    await service.enable_ingestion("leynos", "wildside")

"""

from ghillie.registry.errors import RegistrySyncError, RepositoryNotFoundError
from ghillie.registry.models import RepositoryInfo, SyncResult
from ghillie.registry.service import RepositoryRegistryService

__all__ = [
    "RegistrySyncError",
    "RepositoryInfo",
    "RepositoryNotFoundError",
    "RepositoryRegistryService",
    "SyncResult",
]
