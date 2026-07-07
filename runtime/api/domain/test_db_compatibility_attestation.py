"""Shape and validator tests for db_compatibility_attestation."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.db_compatibility_attestation import (
    DbCompatibilityAttestationError,
    NEGATIVE_DEFAULT,
    NEGATIVE_DEFAULT_JSON,
    canonical_json,
    check_authored_fields_frozen,
    negative_default,
    validate,
    validate_json_string,
)


class TestNegativeDefault:
    def test_empty_object(self) -> None:
        assert NEGATIVE_DEFAULT == {}

    def test_empty_object_json(self) -> None:
        assert NEGATIVE_DEFAULT_JSON == "{}"

    def test_factory_returns_copy(self) -> None:
        a = negative_default()
        a["frozen_at"] = "2026-01-01T00:00:00Z"
        assert negative_default() == {}


class TestValidatorShape:
    def test_accepts_empty(self) -> None:
        assert validate({}) == {}

    def test_rejects_non_dict(self) -> None:
        with pytest.raises(DbCompatibilityAttestationError):
            validate("not a dict")
        with pytest.raises(DbCompatibilityAttestationError):
            validate([])

    def test_rejects_unknown_keys(self) -> None:
        with pytest.raises(DbCompatibilityAttestationError):
            validate({"unknown": "x"})


class TestAuthoredFields:
    def test_accepts_full_authored_block(self) -> None:
        payload = {
            "pre_merge_readers_writers": [
                {"path": "a.py", "symbol": "foo", "role": "reader"},
                {"path": "b.py", "role": "writer"},
            ],
            "invariants": ["items.status values are canonical"],
            "rehearsal_commands": ["python3 -m pytest runtime/api/"],
            "residual_risk_notes": "Cross-worktree reader risk only.",
        }
        out = validate(payload)
        assert out["invariants"] == ["items.status values are canonical"]
        assert out["rehearsal_commands"][0].startswith("python3")
        assert out["residual_risk_notes"].startswith("Cross")

    def test_rejects_bad_role(self) -> None:
        with pytest.raises(DbCompatibilityAttestationError):
            validate({
                "pre_merge_readers_writers": [{"path": "a.py", "role": "overseer"}],
            })

    def test_rejects_missing_path(self) -> None:
        with pytest.raises(DbCompatibilityAttestationError):
            validate({
                "pre_merge_readers_writers": [{"role": "reader"}],
            })

    def test_rejects_non_list_invariants(self) -> None:
        with pytest.raises(DbCompatibilityAttestationError):
            validate({"invariants": "just one"})

    def test_rejects_empty_invariant_string(self) -> None:
        with pytest.raises(DbCompatibilityAttestationError):
            validate({"invariants": [""]})


class TestFrozenAt:
    def test_accepts_utc_iso8601(self) -> None:
        out = validate({"frozen_at": "2026-04-22T17:52:49Z"})
        assert out["frozen_at"] == "2026-04-22T17:52:49Z"

    def test_accepts_null(self) -> None:
        out = validate({"frozen_at": None})
        assert out["frozen_at"] is None

    def test_rejects_non_utc_format(self) -> None:
        with pytest.raises(DbCompatibilityAttestationError):
            validate({"frozen_at": "2026-04-22T17:52:49"})


class TestAppendOnlyCompanions:
    def test_accepts_rehearsal_outcomes(self) -> None:
        out = validate({
            "rehearsal_outcomes": [
                {"command": "pytest", "verdict": "pass", "observed_at": "2026-04-22T17:52:49Z"},
            ],
        })
        assert out["rehearsal_outcomes"][0]["verdict"] == "pass"

    def test_accepts_class_escalations(self) -> None:
        out = validate({
            "class_escalations": [
                {"from": "pre_merge_safe", "to": "pre_merge_breaking", "reason": "scanner hit"},
            ],
        })
        assert out["class_escalations"][0]["to"] == "pre_merge_breaking"

    def test_rejects_non_list_outcomes(self) -> None:
        with pytest.raises(DbCompatibilityAttestationError):
            validate({"rehearsal_outcomes": {"command": "x"}})


class TestCanonicalJson:
    def test_roundtrip_preserves_shape(self) -> None:
        payload = {
            "frozen_at": None,
            "invariants": ["a", "b"],
            "rehearsal_commands": ["x"],
            "residual_risk_notes": "none",
            "pre_merge_readers_writers": [{"path": "p", "role": "reader"}],
        }
        out = validate(payload)
        serialized = canonical_json(out)
        again = json.loads(serialized)
        assert again == out

    def test_validate_json_string_rejects_empty(self) -> None:
        with pytest.raises(DbCompatibilityAttestationError):
            validate_json_string("")

    def test_validate_json_string_rejects_malformed(self) -> None:
        with pytest.raises(DbCompatibilityAttestationError):
            validate_json_string("{not json")

    def test_validate_json_string_accepts_empty_object(self) -> None:
        assert validate_json_string("{}") == "{}"


class TestFreezeImmutability:
    """Direct coverage for ``check_authored_fields_frozen``.

    The write path reads the currently stored attestation JSON and calls
    this helper to defend the freeze lock.  The joint gate at ``idea ->
    refining-idea`` owns stamping and clearing ``frozen_at`` — the write
    path only rejects attempts to edit around it.
    """

    _FROZEN = {
        "frozen_at": "2026-04-22T17:52:49Z",
        "pre_merge_readers_writers": [
            {"path": "runtime/api/domain/projects.py", "symbol": "load", "role": "reader"}
        ],
        "invariants": ["items.status in canonical lifecycle enum"],
        "rehearsal_commands": ["python3 -m pytest runtime/api/"],
        "residual_risk_notes": "Dashboard view one-cycle lag.",
    }

    def test_allows_writes_when_not_frozen(self) -> None:
        current = canonical_json({})
        new = canonical_json({"invariants": ["freshly authored"]})
        assert check_authored_fields_frozen(current, new) is None

    def test_allows_writes_when_current_is_null(self) -> None:
        new = canonical_json({"invariants": ["freshly authored"]})
        assert check_authored_fields_frozen(None, new) is None
        assert check_authored_fields_frozen("", new) is None

    def test_allows_rewrite_preserving_authored_fields(self) -> None:
        current = canonical_json(self._FROZEN)
        # Candidate re-writes authored fields byte-for-byte and also appends
        # a rehearsal outcome (permitted — append-only companion).
        candidate = dict(self._FROZEN)
        candidate["rehearsal_outcomes"] = [{"command": "x", "verdict": "pass"}]
        assert check_authored_fields_frozen(current, canonical_json(candidate)) is None

    def test_rejects_mutating_authored_field(self) -> None:
        current = canonical_json(self._FROZEN)
        mutated = dict(self._FROZEN)
        mutated["invariants"] = ["tampered invariant"]
        err = check_authored_fields_frozen(current, canonical_json(mutated))
        assert err is not None
        assert "invariants" in err
        assert "refining-idea" in err

    def test_rejects_clearing_frozen_at(self) -> None:
        current = canonical_json(self._FROZEN)
        cleared = dict(self._FROZEN)
        cleared["frozen_at"] = None
        err = check_authored_fields_frozen(current, canonical_json(cleared))
        assert err is not None
        assert "frozen_at" in err
        assert "refining-idea" in err

    def test_rejects_changing_frozen_at_stamp(self) -> None:
        current = canonical_json(self._FROZEN)
        moved = dict(self._FROZEN)
        moved["frozen_at"] = "2030-01-01T00:00:00Z"
        err = check_authored_fields_frozen(current, canonical_json(moved))
        assert err is not None
        assert "frozen_at" in err

    def test_rejects_dropping_authored_field(self) -> None:
        current = canonical_json(self._FROZEN)
        dropped = dict(self._FROZEN)
        dropped.pop("residual_risk_notes")
        err = check_authored_fields_frozen(current, canonical_json(dropped))
        assert err is not None
        assert "residual_risk_notes" in err

    def test_garbage_current_json_is_noop(self) -> None:
        # Malformed stored content should not crash the freeze check —
        # validator / integrity concerns belong to separate paths.
        assert check_authored_fields_frozen("{not json", "{}") is None

    def test_garbage_new_json_is_noop(self) -> None:
        current = canonical_json(self._FROZEN)
        assert check_authored_fields_frozen(current, "{not json") is None
