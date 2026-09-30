"""Root rules reserve room for future standing instructions."""

from pathlib import Path

from yoke_contracts.startup_context_budget import root_rules_bytes


def test_codex_root_rules_reserve_ten_percent_headroom():
    root = Path(__file__).resolve().parents[3]
    budget = root_rules_bytes("codex")
    assert len((root / "AGENTS.md").read_bytes()) <= budget * 9 // 10, (
        "Move operation detail into the required agent-rules deep homes "
        "and re-sync the install bundle; preserve startup headroom."
    )
