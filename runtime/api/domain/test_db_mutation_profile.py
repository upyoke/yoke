"""Shape and validator tests for db_mutation_profile.

Freeze-immutability tests live in the sibling test_db_mutation_profile_freeze.py.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.db_mutation_profile import (
    COMPATIBILITY_PRE_MERGE_BREAKING,
    COMPATIBILITY_PRE_MERGE_SAFE,
    DbMutationProfileError,
    MUTATION_INTENT_APPLY,
    MUTATION_INTENT_RETIRE,
    NEGATIVE_DEFAULT,
    NEGATIVE_DEFAULT_JSON,
    STATE_DECLARED,
    STATE_NONE,
    canonical_json,
    negative_default,
    validate,
    validate_json_string,
)


class TestNegativeDefault:
    def test_negative_default_is_state_none(self) -> None:
        assert NEGATIVE_DEFAULT == {"state": STATE_NONE}

    def test_negative_default_json_roundtrips(self) -> None:
        assert json.loads(NEGATIVE_DEFAULT_JSON) == NEGATIVE_DEFAULT

    def test_negative_default_factory_returns_copy(self) -> None:
        a = negative_default()
        b = negative_default()
        a["mutated"] = True
        assert "mutated" not in b
        assert b == NEGATIVE_DEFAULT

    def test_negative_default_json_is_compact(self) -> None:
        # Canonical JSON has no whitespace between tokens.
        assert " " not in NEGATIVE_DEFAULT_JSON


class TestStateValidation:
    def test_accepts_state_none(self) -> None:
        assert validate({"state": STATE_NONE}) == {"state": STATE_NONE}

    def test_rejects_unknown_state(self) -> None:
        with pytest.raises(DbMutationProfileError):
            validate({"state": "declared-partial"})

    def test_rejects_retired_vocab(self) -> None:
        # The retired value ``db-touching-unknown-shape`` must not validate.
        with pytest.raises(DbMutationProfileError):
            validate({"state": "db-touching-unknown-shape"})

    def test_state_none_rejects_theorem_bearing_fields(self) -> None:
        # State='none' rejects presence of declared-only fields.
        for extra in ("model_name", "mutation_intent", "compatibility_class", "migration_modules"):
            with pytest.raises(DbMutationProfileError):
                validate({"state": STATE_NONE, extra: "x"})

    def test_state_declared_requires_keys(self) -> None:
        # Required keys when declared.
        for missing in ("model_name", "mutation_intent", "migration_modules", "compatibility_class"):
            payload = {
                "state": STATE_DECLARED,
                "model_name": "primary",
                "mutation_intent": MUTATION_INTENT_APPLY,
                "migration_modules": ["m1"],
                "compatibility_class": COMPATIBILITY_PRE_MERGE_SAFE,
                "migration_strategy": "additive_only",
            }
            payload.pop(missing)
            with pytest.raises(DbMutationProfileError):
                validate(payload)

    def test_state_declared_accepts_minimum(self) -> None:
        out = validate({
            "state": STATE_DECLARED,
            "model_name": "primary",
            "mutation_intent": MUTATION_INTENT_APPLY,
            "migration_modules": ["add_items_due_date"],
            "compatibility_class": COMPATIBILITY_PRE_MERGE_SAFE,
            "migration_strategy": "additive_only",
        })
        assert out["state"] == STATE_DECLARED
        assert out["model_name"] == "primary"
        assert out["mutation_intent"] == MUTATION_INTENT_APPLY
        assert out["migration_modules"] == ["add_items_due_date"]
        assert out["compatibility_class"] == COMPATIBILITY_PRE_MERGE_SAFE
        assert out["schema_kinds"] == []
        assert out["data_kinds"] == []
        assert out["affected_surfaces"] == []
        assert out["count_preserving"] is True

    def test_state_declared_retire(self) -> None:
        out = validate({
            "state": STATE_DECLARED,
            "model_name": "primary",
            "mutation_intent": MUTATION_INTENT_RETIRE,
            "migration_modules": ["never_applied_module"],
            "compatibility_class": COMPATIBILITY_PRE_MERGE_SAFE,
        })
        assert out["mutation_intent"] == MUTATION_INTENT_RETIRE


class TestVocabularyRejection:
    def test_rejects_bad_model_name(self) -> None:
        for bad in ("Primary", "primary db", "primary/db", "", "-leading-dash", "primary.db"):
            with pytest.raises(DbMutationProfileError):
                validate({
                    "state": STATE_DECLARED,
                    "model_name": bad,
                    "mutation_intent": MUTATION_INTENT_APPLY,
                    "migration_modules": ["m1"],
                    "compatibility_class": COMPATIBILITY_PRE_MERGE_SAFE,
                    "migration_strategy": "additive_only",
                })

    def test_rejects_bad_mutation_intent(self) -> None:
        with pytest.raises(DbMutationProfileError):
            validate({
                "state": STATE_DECLARED,
                "model_name": "primary",
                "mutation_intent": "erase",
                "migration_modules": ["m1"],
                "compatibility_class": COMPATIBILITY_PRE_MERGE_SAFE,
                "migration_strategy": "additive_only",
            })

    def test_rejects_bad_compatibility_class(self) -> None:
        with pytest.raises(DbMutationProfileError):
            validate({
                "state": STATE_DECLARED,
                "model_name": "primary",
                "mutation_intent": MUTATION_INTENT_APPLY,
                "migration_modules": ["m1"],
                "compatibility_class": "it_is_fine",
            })

    def test_rejects_bad_schema_kind(self) -> None:
        with pytest.raises(DbMutationProfileError):
            validate({
                "state": STATE_DECLARED,
                "model_name": "primary",
                "mutation_intent": MUTATION_INTENT_APPLY,
                "migration_modules": ["m1"],
                "compatibility_class": COMPATIBILITY_PRE_MERGE_SAFE,
                "migration_strategy": "additive_only",
                "schema_kinds": ["creative"],
            })


class TestMigrationModules:
    def test_rejects_empty_list(self) -> None:
        # Required, non-empty.
        with pytest.raises(DbMutationProfileError):
            validate({
                "state": STATE_DECLARED,
                "model_name": "primary",
                "mutation_intent": MUTATION_INTENT_APPLY,
                "migration_modules": [],
                "compatibility_class": COMPATIBILITY_PRE_MERGE_SAFE,
                "migration_strategy": "additive_only",
            })

    def test_rejects_path_in_identifier(self) -> None:
        with pytest.raises(DbMutationProfileError):
            validate({
                "state": STATE_DECLARED,
                "model_name": "primary",
                "mutation_intent": MUTATION_INTENT_APPLY,
                "migration_modules": ["dir/add_items_due_date"],
                "compatibility_class": COMPATIBILITY_PRE_MERGE_SAFE,
                "migration_strategy": "additive_only",
            })

    def test_rejects_extension_in_identifier(self) -> None:
        with pytest.raises(DbMutationProfileError):
            validate({
                "state": STATE_DECLARED,
                "model_name": "primary",
                "mutation_intent": MUTATION_INTENT_APPLY,
                "migration_modules": ["add_items_due_date.py"],
                "compatibility_class": COMPATIBILITY_PRE_MERGE_SAFE,
                "migration_strategy": "additive_only",
            })

    def test_rejects_duplicate_identifiers(self) -> None:
        with pytest.raises(DbMutationProfileError):
            validate({
                "state": STATE_DECLARED,
                "model_name": "primary",
                "mutation_intent": MUTATION_INTENT_APPLY,
                "migration_modules": ["m1", "m1"],
                "compatibility_class": COMPATIBILITY_PRE_MERGE_SAFE,
                "migration_strategy": "additive_only",
            })


class TestAffectedSurfaces:
    def test_normalizes_columns(self) -> None:
        out = validate({
            "state": STATE_DECLARED,
            "model_name": "primary",
            "mutation_intent": MUTATION_INTENT_APPLY,
            "migration_modules": ["m1"],
            "compatibility_class": COMPATIBILITY_PRE_MERGE_SAFE,
            "migration_strategy": "additive_only",
            "affected_surfaces": [
                {"table": "items", "columns": ["b", "a", "a"]},
            ],
        })
        assert out["affected_surfaces"] == [{"table": "items", "columns": ["a", "b"]}]

    def test_rejects_non_string_table(self) -> None:
        with pytest.raises(DbMutationProfileError):
            validate({
                "state": STATE_DECLARED,
                "model_name": "primary",
                "mutation_intent": MUTATION_INTENT_APPLY,
                "migration_modules": ["m1"],
                "compatibility_class": COMPATIBILITY_PRE_MERGE_SAFE,
                "migration_strategy": "additive_only",
                "affected_surfaces": [{"table": 42}],
            })

    def test_rejects_unknown_surface_keys(self) -> None:
        with pytest.raises(DbMutationProfileError):
            validate({
                "state": STATE_DECLARED,
                "model_name": "primary",
                "mutation_intent": MUTATION_INTENT_APPLY,
                "migration_modules": ["m1"],
                "compatibility_class": COMPATIBILITY_PRE_MERGE_SAFE,
                "migration_strategy": "additive_only",
                "affected_surfaces": [{"table": "items", "notes": "x"}],
            })


class TestCountPreserving:
    def test_defaults_true(self) -> None:
        out = validate({
            "state": STATE_DECLARED,
            "model_name": "primary",
            "mutation_intent": MUTATION_INTENT_APPLY,
            "migration_modules": ["m1"],
            "compatibility_class": COMPATIBILITY_PRE_MERGE_SAFE,
            "migration_strategy": "additive_only",
        })
        assert out["count_preserving"] is True

    def test_rejects_non_bool(self) -> None:
        with pytest.raises(DbMutationProfileError):
            validate({
                "state": STATE_DECLARED,
                "model_name": "primary",
                "mutation_intent": MUTATION_INTENT_APPLY,
                "migration_modules": ["m1"],
                "compatibility_class": COMPATIBILITY_PRE_MERGE_SAFE,
                "migration_strategy": "additive_only",
                "count_preserving": "true",
            })


class TestCanonicalJson:
    def test_compact_sorted_roundtrip(self) -> None:
        payload = {
            "state": STATE_DECLARED,
            "model_name": "primary",
            "mutation_intent": MUTATION_INTENT_APPLY,
            "migration_modules": ["z", "a"],  # raw input need not be sorted
            "compatibility_class": COMPATIBILITY_PRE_MERGE_BREAKING,
            "migration_strategy": "additive_only",
        }
        # migration_modules preserves author order (no dedup sort) — use canonical_json
        # on the validated output to check stable keying.
        out = validate(payload)
        serialized = canonical_json(out)
        again = json.loads(serialized)
        assert again == out

    def test_validate_json_string_rejects_empty(self) -> None:
        with pytest.raises(DbMutationProfileError):
            validate_json_string("")

    def test_validate_json_string_rejects_malformed(self) -> None:
        with pytest.raises(DbMutationProfileError):
            validate_json_string("{not json")

    def test_validate_json_string_returns_canonical(self) -> None:
        raw = json.dumps({"state": STATE_NONE})
        assert validate_json_string(raw) == NEGATIVE_DEFAULT_JSON


class TestAllowlistWiring:
    """AC-3: db_mutation_profile / db_compatibility_attestation are wired
    into the structured-field allowlists, content-tracking inventory, and
    the JSONB-column registry."""

    def test_valid_structured_fields_includes_both(self) -> None:
        from yoke_core.domain.backlog_queries import VALID_STRUCTURED_FIELDS

        assert "db_mutation_profile" in VALID_STRUCTURED_FIELDS
        assert "db_compatibility_attestation" in VALID_STRUCTURED_FIELDS

    def test_content_tracking_fields_includes_both(self) -> None:
        from yoke_core.domain.backlog_queries import CONTENT_TRACKING_FIELDS

        assert "db_mutation_profile" in CONTENT_TRACKING_FIELDS
        assert "db_compatibility_attestation" in CONTENT_TRACKING_FIELDS

    def test_items_content_fields_includes_both(self) -> None:
        from yoke_core.domain.items import CONTENT_FIELDS

        assert "db_mutation_profile" in CONTENT_FIELDS
        assert "db_compatibility_attestation" in CONTENT_FIELDS

    def test_jsonb_columns_registers_both(self) -> None:
        from yoke_core.domain.sql_json import JSONB_COLUMNS

        items_columns = JSONB_COLUMNS.get("items", ())
        assert "db_mutation_profile" in items_columns
        assert "db_compatibility_attestation" in items_columns
