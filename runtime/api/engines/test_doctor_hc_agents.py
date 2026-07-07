"""Tests for agent prompt consistency health checks."""

from __future__ import annotations

from yoke_core.engines import doctor_hc_agents
from yoke_core.engines import doctor_hc_agents_hooks
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _write_agent(root, command: str) -> None:
    path = root / ".claude" / "agents" / "yoke-test.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            [
                "---",
                "name: yoke-test",
                "hooks:",
                "  PreToolUse:",
                "  - hooks:",
                "    - type: command",
                f"      command: YOKE_HOOK_AGENT_TYPE=test {command}",
                "---",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_agent_consistency_accepts_path_resolved_yoke_cli(tmp_path, monkeypatch) -> None:
    _write_agent(tmp_path, "yoke hook evaluate PreToolUse")
    monkeypatch.setattr(doctor_hc_agents._base, "_resolve_repo_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        doctor_hc_agents_hooks.shutil,
        "which",
        lambda name: "/opt/homebrew/bin/yoke" if name == "yoke" else None,
    )

    rec = RecordCollector()
    doctor_hc_agents.hc_agent_consistency(None, DoctorArgs(), rec)

    assert rec.results[0].result == "PASS"
