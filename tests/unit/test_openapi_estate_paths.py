"""The published OpenAPI document describes the estate endpoints.

The specification is the operator-facing contract for ``curl`` and for the
CLI. These tests pin the operation identifiers, the bearer security scheme,
and the structured error envelope.
"""

import typing as typ
from pathlib import Path

import pytest
import yaml

_SPEC_PATH = Path(__file__).resolve().parents[2] / "specs" / "openapi.yml"

_ESTATE_OPERATIONS = {
    "/estates": "get",
    "/estates/{estate_key}/catalogue-import": "post",
    "/estates/{estate_key}/registry-sync": "post",
    "/estates/{estate_key}/repositories": "get",
    "/repositories/{owner}/{name}/ingestion": "patch",
}

_EXPECTED_OPERATION_IDS = {
    "listEstates",
    "importCatalogue",
    "syncRegistry",
    "listEstateRepositories",
    "setRepositoryIngestion",
}


@pytest.fixture(scope="module")
def spec() -> dict[str, typ.Any]:
    """Load the OpenAPI document."""
    return yaml.safe_load(_SPEC_PATH.read_text(encoding="utf-8"))


def test_every_documented_estate_path_is_present(
    spec: dict[str, typ.Any],
) -> None:
    """All five operations exist under their documented paths."""
    paths = spec["paths"]
    for path, method in _ESTATE_OPERATIONS.items():
        assert path in paths, path
        assert method in paths[path], f"{method.upper()} {path}"


def test_estate_operations_have_stable_ids(spec: dict[str, typ.Any]) -> None:
    """Each operation carries its documented ``operationId``."""
    operation_ids = {
        spec["paths"][path][method]["operationId"]
        for path, method in _ESTATE_OPERATIONS.items()
    }
    assert operation_ids == _EXPECTED_OPERATION_IDS, "operation ids should be stable"


def test_bearer_security_scheme_is_declared(
    spec: dict[str, typ.Any],
) -> None:
    """The document declares an HTTP bearer scheme and uses it globally."""
    schemes = spec["components"]["securitySchemes"]
    bearer = [scheme for scheme in schemes.values() if scheme.get("scheme") == "bearer"]
    assert len(bearer) == 1, "exactly one bearer scheme should exist"
    assert bearer[0]["type"] == "http", "bearer scheme should use http"
    name = next(
        key for key, scheme in schemes.items() if scheme.get("scheme") == "bearer"
    )
    assert spec["security"] == [{name: []}], "global security should name the scheme"

    for path in ("/health", "/ready"):
        assert spec["paths"][path]["get"]["security"] == [], (
            "health and ready should be public"
        )


def test_error_response_carries_the_stable_code(
    spec: dict[str, typ.Any],
) -> None:
    """``ErrorResponse`` requires ``code`` and allows ``issues`` and size."""
    error = spec["components"]["schemas"]["ErrorResponse"]
    assert "code" in error["required"], "error envelope should require a code"
    properties = error["properties"]
    assert properties["code"]["type"] == "string", "error code should be a string"
    assert properties["issues"]["type"] == "array", "issues should be an array"
    issue = properties["issues"]["items"]
    assert set(issue["required"]) == {"code", "message"}, (
        "each issue should require code and message"
    )
    assert properties["max_bytes"]["type"] == "integer", (
        "max_bytes should be an integer"
    )


def test_import_request_body_uses_the_json_upload_shape(
    spec: dict[str, typ.Any],
) -> None:
    """The catalogue import takes a JSON object, never a raw YAML body."""
    operation = spec["paths"]["/estates/{estate_key}/catalogue-import"]["post"]
    content = operation["requestBody"]["content"]
    assert "application/json" in content, "import should accept JSON"
    schema = content["application/json"]["schema"]
    assert "$ref" in schema, "import schema should be a reference"
    request_schema = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    assert set(request_schema["required"]) == {"commit_sha", "catalogue_yaml"}, (
        "import should require both fields"
    )


def test_toggle_request_body_accepts_both_json_media_types(
    spec: dict[str, typ.Any],
) -> None:
    """The toggle accepts JSON and merge-patch JSON."""
    operation = spec["paths"]["/repositories/{owner}/{name}/ingestion"]["patch"]
    content = operation["requestBody"]["content"]
    assert "application/json" in content, "toggle should accept JSON"
    assert "application/merge-patch+json" in content, (
        "toggle should accept merge-patch JSON"
    )


def test_authenticated_report_operation_documents_unauthorized(
    spec: dict[str, typ.Any],
) -> None:
    """Global bearer security also applies when generating a report."""
    responses = spec["paths"]["/reports/repositories/{owner}/{name}"]["post"][
        "responses"
    ]

    assert "401" in responses, "generateReport should document its 401 response"


def test_documented_failure_statuses_are_present(
    spec: dict[str, typ.Any],
) -> None:
    """Every documented failure status appears on at least one operation."""
    seen: set[str] = set()
    for path, method in _ESTATE_OPERATIONS.items():
        seen.update(spec["paths"][path][method]["responses"])

    expected = {"200", "400", "401", "404", "409", "413", "415", "422", "500", "503"}
    assert expected <= seen, "every failure status should be documented"


def test_optional_fields_use_json_schema_null_types(
    spec: dict[str, typ.Any],
) -> None:
    """OpenAPI 3.1 has no ``nullable`` keyword, so nullability is a union."""
    schemas = spec["components"]["schemas"]
    optional_fields = {
        ("EstateSummaryResponse", "description"),
        ("EstateListResponse", "next_offset"),
        ("CatalogueImportResponse", "skipped_reason"),
        ("RepositoryListResponse", "next_offset"),
    }

    for schema_name, field in optional_fields:
        field_spec = schemas[schema_name]["properties"][field]
        assert "null" in field_spec["type"], f"{schema_name}.{field}"

    def _has_nullable(value: object) -> bool:
        if isinstance(value, dict):
            return "nullable" in value or any(
                _has_nullable(child) for child in value.values()
            )
        if isinstance(value, list):
            return any(_has_nullable(child) for child in value)
        return False

    assert not _has_nullable(spec), "no schema should use the nullable keyword"


def test_estate_schemas_are_published(spec: dict[str, typ.Any]) -> None:
    """The response schemas named by the operations exist."""
    schemas = spec["components"]["schemas"]
    for name in (
        "EstateListResponse",
        "CatalogueImportResponse",
        "RegistrySyncResponse",
        "RepositoryListResponse",
        "IngestionToggleResponse",
    ):
        assert name in schemas, name
