"""Unit coverage for Yoke cloud DB authority helpers."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.yoke_cloud_db_authority import (
    PostgresAuthorityLocation,
    PostgresSecret,
    build_libpq_dsn,
    endpoint_and_secret_arn,
    redacted_dsn,
)


def test_location_round_trips_to_settings_shape() -> None:
    raw = {
        "stack": "yoke-prod",
        "state_backend": "s3://yoke-pulumi-state?region=us-east-1",
        "region": "us-east-1",
        "database_name": "yoke_prod",
        "endpoint_output": "databaseClusterEndpoint",
        "secret_arn_output": "databaseSecretArn",
    }

    loc = PostgresAuthorityLocation.from_mapping(raw)

    assert loc.stack == "yoke-prod"
    assert loc.as_settings_location() == raw


def test_secret_json_requires_username_and_password() -> None:
    secret = PostgresSecret.from_json(
        json.dumps({"username": "admin", "password": "pw", "port": "5433"})
    )

    assert secret.username == "admin"
    assert secret.password == "pw"
    assert secret.port == 5433

    with pytest.raises(ValueError, match="password"):
        PostgresSecret.from_json(json.dumps({"username": "admin"}))


def test_endpoint_and_secret_arn_use_declared_output_names() -> None:
    loc = PostgresAuthorityLocation.from_mapping({
        "stack": "prod",
        "database_name": "db",
        "endpoint_output": "endpoint",
        "secret_arn_output": "secret",
    })

    assert endpoint_and_secret_arn(
        {"endpoint": "host.example", "secret": "arn:secret"}, loc
    ) == ("host.example", "arn:secret")


def test_dsn_quoting_and_redaction() -> None:
    secret = PostgresSecret(username="sun day", password="p w")
    dsn = build_libpq_dsn(
        host="127.0.0.1",
        port=15432,
        database="yoke_prod",
        secret=secret,
    )

    assert "user='sun day'" in dsn
    assert "password='p w'" in dsn
    assert "dbname=yoke_prod" in dsn
    assert redacted_dsn(dsn) == (
        "host=127.0.0.1 port=15432 user=sun day "
        "password=<redacted> dbname=yoke_prod"
    )

