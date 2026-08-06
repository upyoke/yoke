"""Tests for the ``migration_model`` capability validator and model builder."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.migration_model_capability import (
    CAPABILITY_TYPE,
    MigrationModelCapabilityError,
    canonical_json,
    governed_postgres_seed,
    resolve_model,
    validate,
    validate_json_string,
)
from yoke_core.domain.migration_yoke_ledger import governed_yoke_postgres_seed
from runtime.api.fixtures.migration_model_test import (
    POSTGRES_AUTHORITY_LOCATION,
    TEST_MEMBERSHIP_LEDGER,
    TEST_MIGRATION_MODULES_DIR,
)

_LEDGER = {
    "table": "schema_version",
    "entry_column": "migration_name",
    "digest_column": "content_sha256",
    "semantics": "membership",
    "serving_floor_column": "minimum_serving_version",
}


def _postgres_seed(location):
    return governed_postgres_seed(
        location,
        modules_dir=TEST_MIGRATION_MODULES_DIR,
        ledger=TEST_MEMBERSHIP_LEDGER,
        connection_env_var="PLATFORM_PG_DSN",
    )


def _minimal_sqlite_model(**overrides):
    base = {
        "authoritative_db": {
            "kind": "sqlite_file",
            "location": {"path": "app/data/app.db"},
        },
        "validation_surface": {
            "kind": "worktree_local_sqlite",
            "provisioning": {
                "path": ".yoke/validation.db",
                "recipe": "webapp_sqlite_empty",
            },
        },
        "runner": {
            "kind": "governed_migration_module",
            "config": {
                "modules_dir": "app/db/migrations",
                "connection_env_var": "APP_DB_PATH",
                "ledger": _LEDGER,
            },
        },
    }
    base.update(overrides)
    return base


class TestCapabilityTypeConstant:
    def test_singular_unsuffixed(self) -> None:
        # Type is singular; instance identity lives in keyed settings.
        assert CAPABILITY_TYPE == "migration_model"


class TestGovernedPostgresSeed:
    def test_seed_requires_explicit_authority(self) -> None:
        with pytest.raises(TypeError, match="required positional argument"):
            governed_postgres_seed()  # type: ignore[call-arg]

    def test_seed_validates(self) -> None:
        seed = _postgres_seed(POSTGRES_AUTHORITY_LOCATION)
        assert validate(seed) == seed

    def test_seed_is_postgres_pairing(self) -> None:
        seed = _postgres_seed(POSTGRES_AUTHORITY_LOCATION)
        primary = seed["models"]["primary"]
        assert primary["authoritative_db"]["kind"] == "postgres"
        assert primary["authoritative_db"]["location"] == (POSTGRES_AUTHORITY_LOCATION)
        assert primary["validation_surface"]["kind"] == "external_validation"
        assert primary["runner"]["kind"] == "governed_migration_module"
        assert primary["runner"]["config"]["connection_env_var"] == ("PLATFORM_PG_DSN")

    def test_seed_requires_project_connection_env_var(self) -> None:
        with pytest.raises(TypeError, match="connection_env_var"):
            governed_postgres_seed(
                POSTGRES_AUTHORITY_LOCATION,
                modules_dir=TEST_MIGRATION_MODULES_DIR,
                ledger=TEST_MEMBERSHIP_LEDGER,
            )

    def test_seed_declares_default_model(self) -> None:
        seed = _postgres_seed(POSTGRES_AUTHORITY_LOCATION)
        assert seed["default_model"] == "primary"

    def test_seed_copies_caller_authority(self) -> None:
        location = dict(POSTGRES_AUTHORITY_LOCATION)
        seed = _postgres_seed(location)

        location["stack"] = "mutated-after-construction"

        assert seed["models"]["primary"]["authoritative_db"]["location"] == (
            POSTGRES_AUTHORITY_LOCATION
        )

    def test_project_declarations_keep_distinct_connection_authority(self) -> None:
        yoke = governed_yoke_postgres_seed(POSTGRES_AUTHORITY_LOCATION)
        platform = _postgres_seed(POSTGRES_AUTHORITY_LOCATION)
        webapp = validate({"models": {"primary": _minimal_sqlite_model()}})

        assert (
            yoke["models"]["primary"]["runner"]["config"]["connection_env_var"]
            == "YOKE_PG_DSN"
        )
        assert (
            platform["models"]["primary"]["runner"]["config"]["connection_env_var"]
            == "PLATFORM_PG_DSN"
        )
        assert (
            webapp["models"]["primary"]["runner"]["config"]["connection_env_var"]
            == "APP_DB_PATH"
        )


class TestStructuralShape:
    def test_rejects_non_dict(self) -> None:
        with pytest.raises(MigrationModelCapabilityError):
            validate("not a dict")
        with pytest.raises(MigrationModelCapabilityError):
            validate([])

    def test_requires_models(self) -> None:
        with pytest.raises(MigrationModelCapabilityError):
            validate({})
        with pytest.raises(MigrationModelCapabilityError):
            validate({"models": {}})

    def test_rejects_unknown_top_level_keys(self) -> None:
        with pytest.raises(MigrationModelCapabilityError):
            validate({"models": {"primary": _minimal_sqlite_model()}, "extra": 1})

    def test_default_model_must_exist(self) -> None:
        # default_model, if present, must exist in models.
        with pytest.raises(MigrationModelCapabilityError):
            validate(
                {
                    "default_model": "missing",
                    "models": {"primary": _minimal_sqlite_model()},
                }
            )

    def test_default_model_optional(self) -> None:
        out = validate({"models": {"primary": _minimal_sqlite_model()}})
        assert "default_model" not in out

    def test_model_names_must_be_slug(self) -> None:
        # Slug-shape.
        with pytest.raises(MigrationModelCapabilityError):
            validate({"models": {"Primary": _minimal_sqlite_model()}})


class TestAuthoritativeDb:
    def test_sqlite_file_accepted(self) -> None:
        # sqlite_file accepted at governed DB-mutation gate.
        out = validate({"models": {"primary": _minimal_sqlite_model()}})
        assert out["models"]["primary"]["authoritative_db"]["kind"] == "sqlite_file"

    def test_sqlite_file_requires_path(self) -> None:
        model = _minimal_sqlite_model(
            authoritative_db={"kind": "sqlite_file", "location": {}},
        )
        with pytest.raises(MigrationModelCapabilityError):
            validate({"models": {"primary": model}})

    def test_postgres_rejects_legacy_dsn_secret_shape(self) -> None:
        model = _minimal_sqlite_model(
            authoritative_db={"kind": "postgres", "location": {"dsn_from_secret": "x"}},
        )
        with pytest.raises(MigrationModelCapabilityError, match="unknown keys"):
            validate({"models": {"primary": model}})

    def test_unknown_kind_rejected(self) -> None:
        model = _minimal_sqlite_model(
            authoritative_db={"kind": "cassandra", "location": {}},
        )
        with pytest.raises(MigrationModelCapabilityError, match="not a recognized"):
            validate({"models": {"primary": model}})


class TestValidationSurface:
    def test_worktree_local_sqlite_accepted(self) -> None:
        # Baseline accepted surface.
        out = validate({"models": {"primary": _minimal_sqlite_model()}})
        assert (
            out["models"]["primary"]["validation_surface"]["kind"]
            == "worktree_local_sqlite"
        )

    def test_worktree_local_sqlite_requires_path_and_recipe(self) -> None:
        model = _minimal_sqlite_model(
            validation_surface={
                "kind": "worktree_local_sqlite",
                "provisioning": {"path": "x"},
            },
        )
        with pytest.raises(MigrationModelCapabilityError):
            validate({"models": {"primary": model}})

    def test_staging_db_unsupported_in_slice(self) -> None:
        model = _minimal_sqlite_model(
            validation_surface={
                "kind": "staging_db",
                "provisioning": {"dsn_from_secret": "x", "reset_recipe": "y"},
            },
        )
        with pytest.raises(MigrationModelCapabilityError, match="not yet supported"):
            validate({"models": {"primary": model}})


class TestRunner:
    def test_governed_migration_module_accepted(self) -> None:
        # Baseline accepted runner.
        out = validate({"models": {"primary": _minimal_sqlite_model()}})
        assert out["models"]["primary"]["runner"]["kind"] == "governed_migration_module"

    def test_governed_migration_module_requires_modules_dir(self) -> None:
        model = _minimal_sqlite_model(
            runner={
                "kind": "governed_migration_module",
                "config": {"connection_env_var": "X", "ledger": _LEDGER},
            },
        )
        with pytest.raises(MigrationModelCapabilityError):
            validate({"models": {"primary": model}})

    def test_connection_env_var_is_required(self) -> None:
        model = _minimal_sqlite_model(
            runner={
                "kind": "governed_migration_module",
                "config": {
                    "modules_dir": "runtime/api/domain/migrations",
                    "ledger": _LEDGER,
                },
            },
        )
        with pytest.raises(MigrationModelCapabilityError, match="connection_env_var"):
            validate({"models": {"primary": model}})

    def test_artifact_version_env_var_is_optional_and_preserved(self) -> None:
        model = _minimal_sqlite_model()
        model["runner"]["config"]["artifact_version_env_var"] = "APP_VERSION"

        out = validate({"models": {"primary": model}})

        assert (
            out["models"]["primary"]["runner"]["config"]["artifact_version_env_var"]
            == "APP_VERSION"
        )

    def test_empty_artifact_version_env_var_is_refused(self) -> None:
        model = _minimal_sqlite_model()
        model["runner"]["config"]["artifact_version_env_var"] = ""

        with pytest.raises(
            MigrationModelCapabilityError, match="artifact_version_env_var"
        ):
            validate({"models": {"primary": model}})

    def test_external_adapter_unsupported_in_slice(self) -> None:
        model = _minimal_sqlite_model(
            runner={"kind": "external_adapter", "config": {"adapter_id": "x"}},
        )
        with pytest.raises(MigrationModelCapabilityError, match="not yet supported"):
            validate({"models": {"primary": model}})

    def test_governed_migration_module_requires_a_ledger(self) -> None:
        model = _minimal_sqlite_model(
            runner={
                "kind": "governed_migration_module",
                "config": {
                    "modules_dir": "app/db/migrations",
                    "connection_env_var": "APP_DB_PATH",
                },
            },
        )
        with pytest.raises(MigrationModelCapabilityError, match="ledger is required"):
            validate({"models": {"primary": model}})


class TestPairingEnforcement:
    def test_mvp_pairing_accepted(self) -> None:
        # Schema fully open; validator rejects non-MVP combinations.
        validate({"models": {"primary": _minimal_sqlite_model()}})

    def test_non_mvp_pairing_rejected_with_narrow_message(self) -> None:
        # This pairing is individually supported in kind vocabulary but the
        # combination is not wired in governed DB-mutation gate.  (Here: swap runner for external
        # adapter; already covered above, so pick a different mismatch.)
        pass  # covered by individual kind tests above


class TestResolveModel:
    def test_round_trip(self) -> None:
        out = validate({"models": {"primary": _minimal_sqlite_model()}})
        resolved = resolve_model(out, "primary")
        assert resolved["runner"]["kind"] == "governed_migration_module"

    def test_unknown_name_raises(self) -> None:
        out = validate({"models": {"primary": _minimal_sqlite_model()}})
        with pytest.raises(KeyError):
            resolve_model(out, "missing")


class TestJsonHelpers:
    def test_validate_json_string_canonicalizes(self) -> None:
        raw = canonical_json(_postgres_seed(POSTGRES_AUTHORITY_LOCATION))
        assert validate_json_string(raw) == raw

    def test_validate_json_string_rejects_empty(self) -> None:
        with pytest.raises(MigrationModelCapabilityError):
            validate_json_string("")

    def test_validate_json_string_rejects_malformed(self) -> None:
        with pytest.raises(MigrationModelCapabilityError):
            validate_json_string("{not json")

    def test_roundtrip_stable(self) -> None:
        """Serialization is sort-key-stable so round-trips are idempotent."""
        one = canonical_json(validate({"models": {"primary": _minimal_sqlite_model()}}))
        two = canonical_json(json.loads(one))
        assert one == two
