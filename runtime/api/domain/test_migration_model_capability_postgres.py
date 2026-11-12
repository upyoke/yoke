"""Postgres authoritative migration_model pairing coverage."""

from __future__ import annotations

import pytest

from yoke_core.domain.migration_model_capability import (
    MigrationModelCapabilityError,
    RUNNER_KIND_GOVERNED_MODULE,
    validate,
)
from runtime.api.fixtures.migration_model_test import (
    POSTGRES_AUTHORITY_LOCATION,
)

_LEDGER = {
    "table": "applied_migrations",
    "entry_column": "migration_name",
    "digest_column": "content_sha256",
    "semantics": "membership",
    "serving_floor_column": "minimum_serving_version",
}


def _postgres_model(location: dict) -> dict:
    return {
        "authoritative_db": {"kind": "postgres", "location": location},
        "validation_surface": {
            "kind": "external_validation",
            "provisioning": {
                "trigger": "postgres_authority",
                "evidence_contract": "aurora_connected_environment",
            },
        },
        "runner": {
            "kind": RUNNER_KIND_GOVERNED_MODULE,
            "config": {
                "modules_dir": "runtime/api/domain/migrations",
                "connection_env_var": "YOKE_PG_DSN",
                "ledger": _LEDGER,
            },
        },
    }


def _location(**overrides) -> dict:
    base = dict(POSTGRES_AUTHORITY_LOCATION)
    base.update(overrides)
    return base


def test_postgres_authoritative_pairing_validates() -> None:
    out = validate({
        "default_model": "primary",
        "models": {"primary": _postgres_model(_location())},
    })

    model = out["models"]["primary"]
    assert model["authoritative_db"]["kind"] == "postgres"
    assert model["authoritative_db"]["location"] == _location()
    assert model["validation_surface"]["kind"] == "external_validation"
    assert model["runner"]["kind"] == RUNNER_KIND_GOVERNED_MODULE


def test_postgres_authoritative_location_rejects_unknown_keys() -> None:
    with pytest.raises(MigrationModelCapabilityError, match="unknown keys"):
        validate({
            "models": {
                "primary": _postgres_model(_location(password="nope")),
            },
        })


def test_postgres_authoritative_location_requires_only_database_name() -> None:
    loc = {"database_name": "registry_db"}
    out = validate({"models": {"primary": _postgres_model(loc)}})
    assert out["models"]["primary"]["authoritative_db"]["location"] == loc


@pytest.mark.parametrize("value", [None, "", 42, False])
def test_postgres_authoritative_location_requires_database_name(value) -> None:
    with pytest.raises(MigrationModelCapabilityError, match="missing required"):
        validate({"models": {"primary": _postgres_model({"database_name": value})}})


@pytest.mark.parametrize(
    "key", ["stack", "endpoint_output", "secret_arn_output", "state_backend", "region"]
)
@pytest.mark.parametrize("value", [None, "", 42, False])
def test_optional_postgres_coordinates_must_be_nonempty_strings(key, value) -> None:
    with pytest.raises(MigrationModelCapabilityError, match=rf"location\.{key} must be"):
        validate({"models": {"primary": _postgres_model(_location(**{key: value}))}})


@pytest.mark.parametrize(
    "key", ["stack", "endpoint_output", "secret_arn_output", "state_backend", "region"]
)
def test_optional_postgres_coordinates_are_preserved(key) -> None:
    loc = {"database_name": "registry_db", key: "declared-value"}
    out = validate({"models": {"primary": _postgres_model(loc)}})
    assert out["models"]["primary"]["authoritative_db"]["location"] == loc
