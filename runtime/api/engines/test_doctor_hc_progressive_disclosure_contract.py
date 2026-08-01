"""Static contract-shape tests for progressive disclosure direction."""

from yoke_project_checks import check_progressive_disclosure_direction as mod
from yoke_project_checks.check_progressive_disclosure_direction import (
    TIER_DIRECTION_RULES,
    VAGUE_DENIAL_MARKERS,
)


def test_required_function_ids_consumed_from_upstream():
    """HC consumes REQUIRED_FUNCTION_IDS from the Task 001 scaffold."""

    from yoke_core.engines import doctor_registry_tier_discipline as up

    assert mod.REQUIRED_FUNCTION_IDS is up.REQUIRED_FUNCTION_IDS


def test_tier_direction_rules_shape():
    """TIER_DIRECTION_RULES has the documented tiers and forward shape."""

    assert set(TIER_DIRECTION_RULES) == {0, 2, 4, 5, 6}
    for tier in (0, 2, 4, 5):
        assert tier in TIER_DIRECTION_RULES[tier]  # same-tier allowed
        assert 1 in TIER_DIRECTION_RULES[tier]  # Tier 1 (in-memory) reachable
    for tier in (2, 4, 5):
        assert 0 in TIER_DIRECTION_RULES[tier]  # substrate authority reachable
    assert 4 in TIER_DIRECTION_RULES[5]  # skill -> agent allowed
    assert 5 not in TIER_DIRECTION_RULES[0]  # AGENTS.md cannot cite skill


def test_vague_denial_markers_contains_canonical_phrases():
    """Module-level constant exposes the spec-canonical phrases."""

    assert "use function dispatch" in VAGUE_DENIAL_MARKERS
    assert "via the function-call surface" in VAGUE_DENIAL_MARKERS


def test_strategy_view_tier_does_not_require_rendered_cache(tmp_path):
    """Logical strategy views remain Tier 3 when their cache is absent."""

    cited = ".yoke/strategy/FOCUSED-PLAN.md"
    assert not (tmp_path / cited).exists()
    assert mod._classify_path(cited, tmp_path) == 3


def test_bare_citation_resolution_ignores_strategy_render_cache(tmp_path):
    """An ignored cache cannot change an ambiguous basename's meaning."""

    citing = ".agents/skills/yoke/strategize/research.md"
    cited = "MASTER-PLAN.md"
    expected = ".agents/skills/yoke/strategize/MASTER-PLAN.md"
    assert mod._normalize_cited(cited, citing, tmp_path) == expected

    rendered = tmp_path / ".yoke/strategy" / cited
    rendered.parent.mkdir(parents=True)
    rendered.write_text("# rendered cache\n", encoding="utf-8")
    assert mod._normalize_cited(cited, citing, tmp_path) == expected
