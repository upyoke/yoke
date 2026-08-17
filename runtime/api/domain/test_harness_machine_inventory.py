"""Presence-only Codex orange: zero trust entries, no hashing."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.harness_machine_inventory import collect_harness_inventory


def test_codex_glue_with_zero_trust_entries_is_unapproved(
    monkeypatch, tmp_path: Path,
) -> None:
    checkout = tmp_path / "proj"
    hooks = checkout / ".codex" / "hooks.json"
    hooks.parent.mkdir(parents=True)
    hooks.write_text('{"hooks": {}}', encoding="utf-8")
    home = tmp_path / "codex-home"
    home.mkdir()
    (home / "config.toml").write_text("", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setattr(
        "yoke_core.domain.harness_machine_inventory.trust_entries_for",
        lambda _hooks: [],
    )

    reports = {row["harness_id"]: row for row in collect_harness_inventory(checkout)}

    assert reports["codex"]["glue_present"] is True
    assert reports["codex"]["approval_state"] == "unapproved"


def test_codex_trust_entries_mark_approved(monkeypatch, tmp_path: Path) -> None:
    checkout = tmp_path / "proj"
    hooks = checkout / ".codex" / "hooks.json"
    hooks.parent.mkdir(parents=True)
    hooks.write_text('{"hooks": {}}', encoding="utf-8")
    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setattr(
        "yoke_core.domain.harness_machine_inventory.trust_entries_for",
        lambda _hooks: [{"path": str(hooks)}],
    )

    reports = {row["harness_id"]: row for row in collect_harness_inventory(checkout)}

    assert reports["codex"]["approval_state"] == "approved"
