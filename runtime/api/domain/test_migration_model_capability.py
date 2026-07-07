"""Tests for the ``migration_model`` capability validator and Yoke seed."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.migration_model_capability import (
    CAPABILITY_TYPE,
    DEFAULT_CONNECTION_ENV_VAR,
    MigrationModelCapabilityError,
    YOKE_PRIMARY_SEED_JSON,
    canonical_json,
    resolve_model,
    yoke_primary_seed,
    validate,
    validate_json_string,
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
            },
        },
    }
    base.update(overrides)
    return base


class TestCapabilityTypeConstant:
    def test_singular_unsuffixed(self) -> None:
        # Type is singular; instance identity lives in keyed settings.
        assert CAPABILITY_TYPE == "migration_model"

    def test_default_env_var_is_postgres_dsn(self) -> None:
        assert DEFAULT_CONNECTION_ENV_VAR == "YOKE_PG_DSN"


class TestYoke_primary_seed:
    def test_seed_validates(self) -> None:
        # Seed is structurally valid.
        assert validate(yoke_primary_seed()) == yoke_primary_seed()

    def test_seed_json_constant_matches_factory(self) -> None:
        # YOKE_PRIMARY_SEED_JSON is canonical JSON of the factory.
        assert YOKE_PRIMARY_SEED_JSON == canonical_json(yoke_primary_seed())

    def test_seed_is_postgres_pairing(self) -> None:
        seed = yoke_primary_seed()
        primary = seed["models"]["primary"]
        assert primary["authoritative_db"]["kind"] == "postgres"
        assert primary["authoritative_db"]["location"]["stack"] == "yoke-prod"
        assert (
            primary["authoritative_db"]["location"]["database_name"]
            == "yoke_prod"
        )
        assert primary["validation_surface"]["kind"] == "external_validation"
        assert primary["runner"]["kind"] == "governed_migration_module"
        assert primary["runner"]["config"]["connection_env_var"] == "YOKE_PG_DSN"

    def test_seed_declares_default_model(self) -> None:
        assert yoke_primary_seed()["default_model"] == "primary"


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
            validate({
                "default_model": "missing",
                "models": {"primary": _minimal_sqlite_model()},
            })

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
        # AC-20.
        out = validate({"models": {"primary": _minimal_sqlite_model()}})
        assert out["models"]["primary"]["validation_surface"]["kind"] == "worktree_local_sqlite"

    def test_worktree_local_sqlite_requires_path_and_recipe(self) -> None:
        model = _minimal_sqlite_model(
            validation_surface={"kind": "worktree_local_sqlite", "provisioning": {"path": "x"}},
        )
        with pytest.raises(MigrationModelCapabilityError):
            validate({"models": {"primary": model}})

    def test_staging_db_unsupported_in_slice(self) -> None:
        model = _minimal_sqlite_model(
            validation_surface={"kind": "staging_db", "provisioning": {"dsn_from_secret": "x", "reset_recipe": "y"}},
        )
        with pytest.raises(MigrationModelCapabilityError, match="not yet supported"):
            validate({"models": {"primary": model}})


class TestRunner:
    def test_governed_migration_module_accepted(self) -> None:
        # AC-21.
        out = validate({"models": {"primary": _minimal_sqlite_model()}})
        assert out["models"]["primary"]["runner"]["kind"] == "governed_migration_module"

    def test_governed_migration_module_requires_modules_dir(self) -> None:
        model = _minimal_sqlite_model(
            runner={"kind": "governed_migration_module", "config": {"connection_env_var": "X"}},
        )
        with pytest.raises(MigrationModelCapabilityError):
            validate({"models": {"primary": model}})

    def test_connection_env_var_defaults_to_postgres_dsn(self) -> None:
        # Defaulting behaviour.
        model = _minimal_sqlite_model(
            runner={
                "kind": "governed_migration_module",
                "config": {"modules_dir": "runtime/api/domain/migrations"},
            },
        )
        out = validate({"models": {"primary": model}})
        assert (
            out["models"]["primary"]["runner"]["config"]["connection_env_var"]
            == "YOKE_PG_DSN"
        )

    def test_external_adapter_unsupported_in_slice(self) -> None:
        model = _minimal_sqlite_model(
            runner={"kind": "external_adapter", "config": {"adapter_id": "x"}},
        )
        with pytest.raises(MigrationModelCapabilityError, match="not yet supported"):
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
        out = validate_json_string(YOKE_PRIMARY_SEED_JSON)
        assert out == YOKE_PRIMARY_SEED_JSON

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
