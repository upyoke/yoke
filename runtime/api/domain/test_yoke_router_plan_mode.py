"""Static coverage for Yoke router plan-mode dispatch guidance."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ROUTER_PATHS = (
    ROOT / ".agents" / "skills" / "yoke" / "SKILL.md",
    ROOT / ".claude" / "skills" / "yoke" / "SKILL.md",
)


def test_router_documents_execute_class_plan_mode_auto_exit() -> None:
    for path in ROUTER_PATHS:
        text = path.read_text(encoding="utf-8")
        assert "Plan-mode guard" in text
        assert "ExitPlanMode" in text
        assert "advance" in text
        assert "conduct" in text
        assert "usher" in text
        assert "polish" in text
        assert "Plan mode auto-exited — Yoke ticket is the plan." in text
        assert "Planning-class commands" in text
