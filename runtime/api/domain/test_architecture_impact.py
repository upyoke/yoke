"""Tests for ``architecture_impact``: enum validator + readiness gate."""

from __future__ import annotations

import pytest

from yoke_core.domain import architecture_impact as ai


class TestValidateValue:
    @pytest.mark.parametrize("value", sorted(ai.ALLOWED_VALUES))
    def test_known_value_round_trips(self, value):
        assert ai.validate_value(value) == value

    @pytest.mark.parametrize("raw,canonical", [
        ("  none  ", "none"),
        ("NONE", "none"),
        ("Path_Context_Only", "path_context_only"),
        ("\tUNCERTAIN\n", "uncertain"),
    ])
    def test_normalizes_whitespace_and_case(self, raw, canonical):
        assert ai.validate_value(raw) == canonical

    def test_empty_string_rejected(self):
        with pytest.raises(ai.ArchitectureImpactError, match="empty"):
            ai.validate_value("")

    def test_unknown_value_rejected(self):
        with pytest.raises(
            ai.ArchitectureImpactError, match="not a known value"
        ):
            ai.validate_value("major_refactor")

    def test_non_string_rejected(self):
        with pytest.raises(
            ai.ArchitectureImpactError, match="must be a string"
        ):
            ai.validate_value(42)  # type: ignore[arg-type]


class TestReadinessResolution:
    @pytest.mark.parametrize("value", [
        ai.IMPACT_NONE,
        ai.IMPACT_PATH_CONTEXT_ONLY,
        ai.IMPACT_ARCHITECTURE_MODEL_CHANGE,
    ])
    def test_resolved_values_pass_readiness(self, value):
        assert ai.is_readiness_resolved(value) is True

    def test_uncertain_blocks_readiness(self):
        assert ai.is_readiness_resolved(ai.IMPACT_UNCERTAIN) is False


class TestNegativeDefault:
    def test_negative_default_is_none_enum(self):
        assert ai.NEGATIVE_DEFAULT == ai.IMPACT_NONE
        assert ai.NEGATIVE_DEFAULT in ai.ALLOWED_VALUES


class TestFieldSurfaceRegistration:
    def test_structured_field_writer_canonicalizes_architecture_impact(self):
        from yoke_core.domain.items_writes_validation import apply_field_validators

        assert (
            apply_field_validators(
                "architecture_impact", " architecture_model_change\n"
            )
            == "architecture_model_change"
        )

    def test_write_and_read_allowlists_include_architecture_impact(self):
        from yoke_core.domain.backlog_queries import VALID_STRUCTURED_FIELDS
        from yoke_core.domain.items_constants import (
            CONTENT_FIELDS,
            LARGE_TEXT_FIELDS,
            STRUCTURED_FIELDS,
        )
        from yoke_core.api.service_client_items_parsing import (
            _QI_ALL_FIELDS,
            _QI_LARGE_TEXT_FIELDS,
        )

        assert "architecture_impact" in VALID_STRUCTURED_FIELDS
        assert "architecture_impact" in STRUCTURED_FIELDS
        assert "architecture_impact" in LARGE_TEXT_FIELDS
        assert "architecture_impact" in _QI_ALL_FIELDS
        assert "architecture_impact" in _QI_LARGE_TEXT_FIELDS
        assert "architecture_impact" not in CONTENT_FIELDS
