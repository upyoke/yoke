"""The item UI reads the central effective File Budget and path-claim policies."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "packages" / "yoke-core" / "src" / "yoke_core" / "ui" / "static"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_item_ui_uses_central_effective_policies() -> None:
    facts = _read(UI / "item_view_facts.js")
    blitz = _read(UI / "universe_views_blitz.js")
    assert "workflow?.effective_policies?.file_budget" in facts
    assert "workflow?.effective_policies?.path_claims" in facts
    assert "workflow.effective_policies" in facts
    assert "workflow.effective_policies" in blitz
    assert "workflow?.policies?.file_budget" not in facts
    assert "workflow?.policies?.path_claims" not in facts
    assert "policies.file_budget" not in blitz
    assert "policies.path_claims" not in blitz
