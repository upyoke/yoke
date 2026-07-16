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


def governed_postgres_test_seed() -> dict[str, Any]:
    """Build the standard test model with an explicit neutral authority."""
    return governed_postgres_seed(POSTGRES_AUTHORITY_LOCATION)
