"""Neutral migration-model fixtures shared by runtime tests."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migration_model_capability import governed_postgres_seed


POSTGRES_AUTHORITY_LOCATION: dict[str, Any] = {
    "stack": "test-app-prod",
    "state_backend": "s3://test-app-state?region=us-east-1",
    "region": "us-east-1",
    "database_name": "test_app_prod",
    "endpoint_output": "databaseClusterEndpoint",
    "secret_arn_output": "databaseSecretArn",
}
TEST_MIGRATION_MODULES_DIR = "app/db/migrations"
TEST_MEMBERSHIP_LEDGER: dict[str, str] = {
    "table": "schema_version",
    "entry_column": "migration_name",
    "digest_column": "content_sha256",
    "semantics": "membership",
    "serving_floor_column": "minimum_serving_version",
}


def governed_postgres_test_seed() -> dict[str, Any]:
    """Build the standard test model with an explicit neutral authority."""
    return governed_postgres_seed(
        POSTGRES_AUTHORITY_LOCATION,
        modules_dir=TEST_MIGRATION_MODULES_DIR,
        ledger=TEST_MEMBERSHIP_LEDGER,
        connection_env_var="YOKE_PG_DSN",
    )


def membership_ledger_test_seed() -> dict[str, Any]:
    """Build the canonical per-entry membership ledger test declaration."""
    model = governed_postgres_test_seed()["models"]["primary"]
    return dict(model["runner"]["config"]["ledger"])
