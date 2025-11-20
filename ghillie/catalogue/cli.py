"""Command-line helpers for catalogue validation and schema export."""

from __future__ import annotations

import argparse
from pathlib import Path

import msgspec

from .loader import lint_catalogue
from .schema import write_catalogue_schema
from .validation import CatalogueValidationError


def main(argv: list[str] | None = None) -> int:
    """Validate a catalogue file and optionally export JSON and schema artefacts.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments. ``None`` defaults to ``sys.argv``.

    Returns
    -------
    int
        Exit code: 0 on success, 1 when validation fails.

    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalogue", type=Path, help="YAML catalogue to validate")
    parser.add_argument(
        "--schema-out",
        type=Path,
        default=None,
        help="Optional path to write the generated JSON Schema",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write the validated catalogue as JSON",
    )
    args = parser.parse_args(argv)

    catalogue_path: Path = args.catalogue
    try:
        catalogue = lint_catalogue(catalogue_path)
    except CatalogueValidationError as exc:  # pragma: no cover - exercised in CLI tests
        print(f"Catalogue validation failed for {catalogue_path}:")
        for issue in exc.issues:
            print(f"  - {issue}")
        return 1

    if args.schema_out:
        write_catalogue_schema(args.schema_out)

    if args.json_out:
        args.json_out.write_bytes(msgspec.json.encode(catalogue))

    print(
        f"catalogue {catalogue_path} is valid "
        f"({len(catalogue.projects)} projects / "
        f"{sum(len(project.components) for project in catalogue.projects)} components)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
