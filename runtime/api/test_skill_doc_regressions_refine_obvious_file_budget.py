"""Doc regression for obvious File Budget repairs in /yoke refine."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UPDATE_PROTOCOL = ROOT / ".agents" / "skills" / "yoke" / "refine" / "update-protocol.md"


def test_refine_teaches_obvious_file_budget_repair_before_escalation() -> None:
    text = " ".join(UPDATE_PROTOCOL.read_text(encoding="utf-8").split())
    assert "One verified missing owner in scope: add its budget row" in text
    assert "(widen if claims are on)" in text
    assert "more than one, or changed scope, escalates" in text
