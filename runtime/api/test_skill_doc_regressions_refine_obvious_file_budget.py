"""Doc regression for obvious File Budget repairs in /yoke refine."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UPDATE_PROTOCOL = ROOT / ".agents" / "skills" / "yoke" / "refine" / "update-protocol.md"


def test_refine_teaches_obvious_file_budget_repair_before_escalation() -> None:
    text = UPDATE_PROTOCOL.read_text(encoding="utf-8")
    assert "Obvious File Budget repair" in text
    assert "one obvious live owner" in text
    assert "widen the path claim" in text
    assert "Escalate only" in text
    assert "multiple plausible owners" in text
