"""Tests for yoke_core.domain.browser_qa_metadata.

Covers validator contract, normalization rules, and JSON round-trip.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.browser_qa_metadata import (
    BrowserQaMetadataError,
    NEGATIVE_DEFAULT,
    NEGATIVE_DEFAULT_JSON,
    canonical_json,
    negative_default,
    validate,
    validate_json_string,
)


# ---------------------------------------------------------------------------
# NEGATIVE_DEFAULT
# ---------------------------------------------------------------------------

class TestNegativeDefault:
    def test_shape_is_all_empty_or_false(self):
        assert NEGATIVE_DEFAULT == {
            "browser_testable": False,
            "visual_outcome": False,
            "browser_routes": [],
            "browser_timing_hints_ms": [],
        }

    def test_validator_accepts_default(self):
        assert validate(NEGATIVE_DEFAULT) == NEGATIVE_DEFAULT

    def test_negative_default_helper_returns_fresh_copy(self):
        a = negative_default()
        b = negative_default()
        a["browser_routes"].append("/x")
        assert b["browser_routes"] == []
        assert NEGATIVE_DEFAULT["browser_routes"] == []

    def test_canonical_json_is_deterministic(self):
        assert NEGATIVE_DEFAULT_JSON == canonical_json(NEGATIVE_DEFAULT)
        # Key order must be lexicographic
        decoded = json.loads(NEGATIVE_DEFAULT_JSON)
        assert list(decoded.keys()) == sorted(decoded.keys())


# ---------------------------------------------------------------------------
# validate — shape errors
# ---------------------------------------------------------------------------

class TestValidateShape:
    def test_rejects_non_dict(self):
        with pytest.raises(BrowserQaMetadataError, match="must be a JSON object"):
            validate("not a dict")

    def test_rejects_missing_key(self):
        with pytest.raises(BrowserQaMetadataError, match="missing required keys"):
            validate({
                "browser_testable": False,
                "visual_outcome": False,
                "browser_routes": [],
            })

    def test_rejects_unknown_key(self):
        with pytest.raises(BrowserQaMetadataError, match="unknown keys"):
            validate({
                **NEGATIVE_DEFAULT,
                "extra": True,
            })


# ---------------------------------------------------------------------------
# validate — boolean strictness + contradiction
# ---------------------------------------------------------------------------

class TestValidateBooleans:
    def test_rejects_string_for_browser_testable(self):
        with pytest.raises(BrowserQaMetadataError, match="browser_testable"):
            validate({**NEGATIVE_DEFAULT, "browser_testable": "true"})

    def test_rejects_int_for_browser_testable(self):
        with pytest.raises(BrowserQaMetadataError, match="browser_testable"):
            validate({**NEGATIVE_DEFAULT, "browser_testable": 1})

    def test_rejects_none_for_browser_testable(self):
        with pytest.raises(BrowserQaMetadataError, match="browser_testable"):
            validate({**NEGATIVE_DEFAULT, "browser_testable": None})

    def test_rejects_visual_outcome_true_with_browser_testable_false(self):
        with pytest.raises(BrowserQaMetadataError, match="contradicts"):
            validate({
                **NEGATIVE_DEFAULT,
                "browser_testable": False,
                "visual_outcome": True,
            })

    def test_accepts_browser_testable_true_visual_outcome_true(self):
        result = validate({
            **NEGATIVE_DEFAULT,
            "browser_testable": True,
            "visual_outcome": True,
        })
        assert result["browser_testable"] is True
        assert result["visual_outcome"] is True


# ---------------------------------------------------------------------------
# validate — route normalization
# ---------------------------------------------------------------------------

class TestValidateRoutes:
    @pytest.mark.parametrize("raw, expected", [
        ("/login", "/login"),
        ("/Login", "/login"),
        ("/LOGIN/", "/login"),
        ("login", "/login"),
        ("/", "/"),
        ("/login/", "/login"),
        ("/search?q=foo", "/search"),
        ("/search#top", "/search"),
        ("/search?q=foo#top", "/search"),
        ("/forgot-password/", "/forgot-password"),
    ])
    def test_single_route_normalization(self, raw, expected):
        result = validate({
            **NEGATIVE_DEFAULT,
            "browser_testable": True,
            "browser_routes": [raw],
        })
        assert result["browser_routes"] == [expected]

    def test_rejects_empty_string_route(self):
        with pytest.raises(BrowserQaMetadataError, match="empty"):
            validate({
                **NEGATIVE_DEFAULT,
                "browser_testable": True,
                "browser_routes": [""],
            })

    def test_rejects_internal_whitespace(self):
        with pytest.raises(BrowserQaMetadataError, match="whitespace"):
            validate({
                **NEGATIVE_DEFAULT,
                "browser_testable": True,
                "browser_routes": ["/bad route"],
            })

    def test_rejects_query_only_route(self):
        with pytest.raises(BrowserQaMetadataError, match="reduced to empty"):
            validate({
                **NEGATIVE_DEFAULT,
                "browser_testable": True,
                "browser_routes": ["?q=foo"],
            })

    def test_dedup_and_sort(self):
        result = validate({
            **NEGATIVE_DEFAULT,
            "browser_testable": True,
            "browser_routes": ["/z", "/Login", "/login", "/a"],
        })
        assert result["browser_routes"] == ["/a", "/login", "/z"]

    def test_rejects_non_string_route(self):
        with pytest.raises(BrowserQaMetadataError, match="must be a string"):
            validate({
                **NEGATIVE_DEFAULT,
                "browser_testable": True,
                "browser_routes": [123],
            })

    def test_rejects_non_list_routes_value(self):
        with pytest.raises(BrowserQaMetadataError, match="browser_routes must be a list"):
            validate({
                **NEGATIVE_DEFAULT,
                "browser_testable": True,
                "browser_routes": "/login",
            })


# ---------------------------------------------------------------------------
# validate — timing hint normalization
# ---------------------------------------------------------------------------

class TestValidateTimings:
    def test_accepts_int_ms(self):
        result = validate({
            **NEGATIVE_DEFAULT,
            "browser_testable": True,
            "browser_timing_hints_ms": [2000, 7000],
        })
        assert result["browser_timing_hints_ms"] == [2000, 7000]

    def test_sorts_and_dedupes(self):
        result = validate({
            **NEGATIVE_DEFAULT,
            "browser_testable": True,
            "browser_timing_hints_ms": [7000, 2000, 2000, 1500],
        })
        assert result["browser_timing_hints_ms"] == [1500, 2000, 7000]

    def test_rounds_float(self):
        result = validate({
            **NEGATIVE_DEFAULT,
            "browser_testable": True,
            "browser_timing_hints_ms": [6999.5],
        })
        assert result["browser_timing_hints_ms"] == [7000]

    def test_rejects_zero(self):
        with pytest.raises(BrowserQaMetadataError, match="must be > 0"):
            validate({
                **NEGATIVE_DEFAULT,
                "browser_testable": True,
                "browser_timing_hints_ms": [0],
            })

    def test_rejects_negative(self):
        with pytest.raises(BrowserQaMetadataError, match="must be > 0"):
            validate({
                **NEGATIVE_DEFAULT,
                "browser_testable": True,
                "browser_timing_hints_ms": [-100],
            })

    def test_rejects_over_upper_bound(self):
        with pytest.raises(BrowserQaMetadataError, match="exceeds"):
            validate({
                **NEGATIVE_DEFAULT,
                "browser_testable": True,
                "browser_timing_hints_ms": [60001],
            })

    def test_accepts_upper_bound(self):
        result = validate({
            **NEGATIVE_DEFAULT,
            "browser_testable": True,
            "browser_timing_hints_ms": [60000],
        })
        assert result["browser_timing_hints_ms"] == [60000]

    def test_rejects_bool(self):
        with pytest.raises(BrowserQaMetadataError, match="not bool"):
            validate({
                **NEGATIVE_DEFAULT,
                "browser_testable": True,
                "browser_timing_hints_ms": [True],
            })

    def test_rejects_string(self):
        with pytest.raises(BrowserQaMetadataError, match="int or float"):
            validate({
                **NEGATIVE_DEFAULT,
                "browser_testable": True,
                "browser_timing_hints_ms": ["2000"],
            })


# ---------------------------------------------------------------------------
# validate_json_string
# ---------------------------------------------------------------------------

class TestValidateJsonString:
    def test_round_trip_is_canonical(self):
        raw = json.dumps({
            "browser_timing_hints_ms": [2000],
            "browser_routes": ["/Login", "/login"],
            "visual_outcome": True,
            "browser_testable": True,
        })
        out = validate_json_string(raw)
        assert out == canonical_json({
            "browser_testable": True,
            "visual_outcome": True,
            "browser_routes": ["/login"],
            "browser_timing_hints_ms": [2000],
        })

    def test_empty_string_rejected(self):
        with pytest.raises(BrowserQaMetadataError, match="empty"):
            validate_json_string("")

    def test_none_rejected(self):
        with pytest.raises(BrowserQaMetadataError, match="empty"):
            validate_json_string(None)  # type: ignore[arg-type]

    def test_malformed_json_rejected(self):
        with pytest.raises(BrowserQaMetadataError, match="malformed JSON"):
            validate_json_string("{not json")

    def test_schema_violation_rejected(self):
        with pytest.raises(BrowserQaMetadataError):
            validate_json_string(json.dumps({"browser_testable": "true"}))
