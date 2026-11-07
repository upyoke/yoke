"""Root rules reserve room for future standing instructions."""

from pathlib import Path

from yoke_contracts.startup_context_budget import root_rules_bytes


def test_codex_root_rules_reserve_ten_percent_headroom():
    root = Path(__file__).resolve().parents[3]
    budget = root_rules_bytes("codex")
    assert len((root / "AGENTS.md").read_bytes()) <= budget * 9 // 10, (
        "Move judgment into .yoke/docs/agents/rules.md and procedure into "
        "its reference doc, then re-sync the install bundle; preserve "
        "startup headroom."
    )
