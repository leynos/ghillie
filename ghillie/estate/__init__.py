"""Estate-management driving port, models, and service.

The package initializer is deliberately docstring-only. Re-exporting the
service here would import the catalogue package (and its Dramatiq broker guard)
into every consumer of the pure models.
"""
