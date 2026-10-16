"""Static contract-shape tests for progressive disclosure direction."""

import pytest

from yoke_project_checks import check_progressive_disclosure_direction as mod
from yoke_project_checks.check_progressive_disclosure_direction import (
    TIER_DIRECTION_RULES,
    VAGUE_DENIAL_MARKERS,
)


def test_required_function_ids_consumed_from_upstream():
    """HC consumes required function IDs from the shared registry."""

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


@pytest.mark.parametrize(
    "catalogue",
    (
        ".yoke/docs/agents/commands.md",
        ".yoke/docs/agents/maintenance-commands.md",
    ),
)
def test_generated_catalogues_resolve_skill_citations_and_keep_their_tier(
    tmp_path, catalogue
):
    targets = (
        ".agents/skills/yoke/amend/SKILL.md",
        ".agents/skills/yoke/amend/instructions.md",
        ".agents/skills/yoke/approve/instructions.md",
        ".agents/skills/yoke/shared/unique.md",
    )
    for target in targets:
        path = tmp_path / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Skill input\n", encoding="utf-8")
    text = (
        "# Catalogue\n### amend\nRead `instructions.md` and `unique.md`.\n"
        "Use `.agents/skills/yoke/amend/SKILL.md`.\n"
    )
    page = tmp_path / catalogue
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(text, encoding="utf-8")

    assert (2, page) in list(mod.iter_tier_paths(tmp_path))
    assert mod._classify_path(catalogue, tmp_path) == 2
    assert {
        cited for _, cited in mod._extract_citations(text, catalogue, tmp_path)
    } == {
        targets[0],
        targets[1],
        targets[3],
    }
    assert mod._scan_all(tmp_path) == []

    agent = tmp_path / "runtime/agents/tester.md"
    agent.parent.mkdir(parents=True)
    agent.write_text("# Agent\n", encoding="utf-8")
    page.write_text(text + "Read `runtime/agents/tester.md`.\n", encoding="utf-8")
    findings = mod._scan_all(tmp_path)
    assert len(findings) == 1
    assert (
        "tier 2 file references backward tier 4 file runtime/agents/tester.md"
        in findings[0]
    )


def test_help_inventory_lookup_does_not_allow_other_backward_directions(tmp_path):
    contents = {
        ".yoke/docs/agents/commands.md": "# Commands\n",
        ".yoke/docs/agents/maintenance-commands.md": "# Maintenance\n",
        ".agents/skills/yoke/help/SKILL.md": (
            "# Help\nFull inventory: `.yoke/docs/agents/commands.md`.\n"
        ),
    }
    for relative, text in contents.items():
        page = tmp_path / relative
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(text, encoding="utf-8")
    assert mod._scan_all(tmp_path) == []

    unrelated = tmp_path / ".agents/skills/yoke/other/SKILL.md"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("Read `.yoke/docs/agents/commands.md`.\n", encoding="utf-8")
    orientation = tmp_path / "docs/OVERVIEW.md"
    orientation.parent.mkdir(parents=True)
    orientation.write_text(
        "Read `.agents/skills/yoke/other/SKILL.md`.\n", encoding="utf-8"
    )
    help_page = tmp_path / ".agents/skills/yoke/help/SKILL.md"
    help_page.write_text(
        "Read `.yoke/docs/agents/maintenance-commands.md`.\n", encoding="utf-8"
    )
    findings = mod._scan_all(tmp_path)
    assert len(findings) == 3
    assert any("tier 2 file references backward tier 5" in row for row in findings)
    assert any(
        ".agents/skills/yoke/other/SKILL.md" in row
        and "tier 5 file references backward tier 2" in row
        for row in findings
    )
    assert any(
        ".agents/skills/yoke/help/SKILL.md" in row
        and "maintenance-commands.md" in row
        and "tier 5 file references backward tier 2" in row
        for row in findings
    )
