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


def test_postgres_authoritative_location_requires_stack_outputs() -> None:
    loc = _location()
    del loc["secret_arn_output"]

    with pytest.raises(MigrationModelCapabilityError, match="missing required"):
        validate({"models": {"primary": _postgres_model(loc)}})
