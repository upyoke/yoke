"""Freeze-immutability coverage for db_mutation_profile.check_model_name_frozen.

Validator and shape tests live in test_db_mutation_profile.py.
"""

from __future__ import annotations

from yoke_core.domain.db_mutation_profile import (
    COMPATIBILITY_PRE_MERGE_SAFE,
    MUTATION_INTENT_APPLY,
    STATE_DECLARED,
    STATE_NONE,
    canonical_json,
    check_model_name_frozen,
)


class TestFreezeImmutability:
    """Direct coverage for ``check_model_name_frozen``.

    The write path reads the currently stored attestation and profile JSON
    and calls this helper before committing a new profile.  The freeze is
    keyed on the sibling attestation's ``frozen_at`` field.
    """

    _FROZEN_ATTESTATION = canonical_json({
        "frozen_at": "2026-04-22T17:52:49Z",
        "invariants": ["x"],
        "rehearsal_commands": ["y"],
        "residual_risk_notes": "z",
        "pre_merge_readers_writers": [{"path": "p", "role": "reader"}],
    })

    _DECLARED_PROFILE = canonical_json({
        "state": STATE_DECLARED,
        "model_name": "primary",
        "mutation_intent": MUTATION_INTENT_APPLY,
        "migration_modules": ["add_col"],
        "compatibility_class": COMPATIBILITY_PRE_MERGE_SAFE,
        "schema_kinds": ["additive"],
        "data_kinds": [],
        "affected_surfaces": [],
        "count_preserving": True,
    })

    _DECLARED_PROFILE_RENAMED = canonical_json({
        "state": STATE_DECLARED,
        "model_name": "secondary",
        "mutation_intent": MUTATION_INTENT_APPLY,
        "migration_modules": ["add_col"],
        "compatibility_class": COMPATIBILITY_PRE_MERGE_SAFE,
        "schema_kinds": ["additive"],
        "data_kinds": [],
        "affected_surfaces": [],
        "count_preserving": True,
    })

    def test_allows_write_when_attestation_not_frozen(self) -> None:
        assert check_model_name_frozen(
            canonical_json({}),
            self._DECLARED_PROFILE,
            self._DECLARED_PROFILE_RENAMED,
        ) is None

    def test_allows_write_when_attestation_null(self) -> None:
        assert check_model_name_frozen(
            None,
            self._DECLARED_PROFILE,
            self._DECLARED_PROFILE_RENAMED,
        ) is None

    def test_allows_initial_declaration_from_state_none(self) -> None:
        # No prior model_name → initial declaration, even if the
        # attestation is already frozen (anomalous but handled
        # defensively).
        assert check_model_name_frozen(
            self._FROZEN_ATTESTATION,
            canonical_json({"state": STATE_NONE}),
            self._DECLARED_PROFILE,
        ) is None

    def test_allows_rewrite_with_same_model_name(self) -> None:
        assert check_model_name_frozen(
            self._FROZEN_ATTESTATION,
            self._DECLARED_PROFILE,
            self._DECLARED_PROFILE,
        ) is None

    def test_rejects_model_name_change_under_freeze(self) -> None:
        err = check_model_name_frozen(
            self._FROZEN_ATTESTATION,
            self._DECLARED_PROFILE,
            self._DECLARED_PROFILE_RENAMED,
        )
        assert err is not None
        assert "model_name" in err
        assert "refining-idea" in err

    def test_rejects_collapsing_to_state_none_under_freeze(self) -> None:
        err = check_model_name_frozen(
            self._FROZEN_ATTESTATION,
            self._DECLARED_PROFILE,
            canonical_json({"state": STATE_NONE}),
        )
        assert err is not None
        assert "model_name" in err

    def test_garbage_json_is_noop(self) -> None:
        assert check_model_name_frozen("{not json", self._DECLARED_PROFILE, "{}") is None
