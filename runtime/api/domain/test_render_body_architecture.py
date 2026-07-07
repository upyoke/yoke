"""Tests for the architecture-impact body-section renderer."""

from __future__ import annotations

import pytest

from yoke_core.domain.render_body_architecture import (
    render_architecture_impact_section,
)


class TestRenderArchitectureImpactSection:
    @pytest.mark.parametrize("value", [None, "", "  ", "none", "NONE"])
    def test_empty_or_none_emits_nothing(self, value):
        assert render_architecture_impact_section(value) == ""

    def test_path_context_only_emits_section(self):
        out = render_architecture_impact_section("path_context_only")
        assert out.startswith("## Architecture Impact")
        assert "`path_context_only`" in out
        assert "inherited path-context families" in out

    def test_architecture_model_change_emits_section(self):
        out = render_architecture_impact_section("architecture_model_change")
        assert out.startswith("## Architecture Impact")
        assert "`architecture_model_change`" in out
        assert "modifies the project architecture model" in out

    def test_uncertain_emits_section(self):
        out = render_architecture_impact_section("uncertain")
        assert out.startswith("## Architecture Impact")
        assert "`uncertain`" in out
        assert "Architect" in out

    def test_unknown_value_emits_terse_section(self):
        out = render_architecture_impact_section("future_class")
        assert out.startswith("## Architecture Impact")
        assert "`future_class`" in out
