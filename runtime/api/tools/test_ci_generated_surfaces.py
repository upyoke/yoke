"""CI rejects generated teaching drift without changing the checkout."""

from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.tools import ci_generated_surfaces as checks
from yoke_core.tools import render_field_note_inline as field_notes
from yoke_core.tools import render_harness_capability_inline as capability


def test_generated_block_drift_is_rejected_without_writing(tmp_path):
    from yoke_core.tools import generated_block_render as blocks

    target = tmp_path / field_notes.INVENTORY[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    original = (
        "<!-- BEGIN GENERATED: feedback-directive -->\nstale\n"
        "<!-- END GENERATED: feedback-directive -->\n"
    )
    target.write_text(original)
    with patch.object(blocks, "FAMILY_MODULES", (field_notes.__name__,)):
        ok, detail = checks.check_generated_blocks(tmp_path, None)
    assert not ok
    assert field_notes.INVENTORY[0] in detail
    assert "Run `" in detail
    assert target.read_text() == original


def test_missing_block_renderer_fails_closed(tmp_path):
    from yoke_core.tools import generated_block_render as blocks

    with patch.object(blocks.importlib, "import_module", side_effect=ImportError):
        ok, detail = checks.check_generated_blocks(tmp_path, None)
    assert not ok
    assert "install/repair" in detail


def test_wake_render_drift_is_rejected_without_writing(tmp_path):
    target = tmp_path / capability.INVENTORY[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    original = (
        f"<!-- BEGIN GENERATED: {capability.SLUG} -->\nstale\n"
        f"<!-- END GENERATED: {capability.SLUG} -->\n"
    )
    target.write_text(original)
    ok, detail = checks.check_harness_capability(tmp_path, None)
    assert not ok
    assert str(capability.INVENTORY[0]) in detail
    assert capability.REPAIR_COMMAND in detail
    assert target.read_text() == original


@pytest.mark.parametrize("drift", [
    ["drift: runtime/harness/codex/agents/yoke-engineer.toml"],
    ["render-error: cannot load canonical seed"],
])
def test_agent_drift_and_render_errors_fail_with_recovery(tmp_path, drift):
    with patch(
        "yoke_core.domain.agents_render.detect_substrate_drift", return_value=drift,
    ):
        ok, detail = checks.check_agent_render(tmp_path, None)
    assert not ok
    assert drift[0] in detail
    assert "yoke agents render" in detail


@pytest.mark.parametrize("check", [
    checks.check_generated_blocks,
    checks.check_harness_capability,
    checks.check_agent_render,
])
def test_shipped_generated_surfaces_match_sources(check):
    root = Path(__file__).resolve().parents[3]
    ok, detail = check(root, None)
    assert ok, detail
