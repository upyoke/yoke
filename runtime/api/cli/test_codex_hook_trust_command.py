"""CLI coverage for stale Codex hook-trust cleanup."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_cli.commands import codex_hook_trust
from yoke_cli.commands.tool_shaped import resolve_tool_shaped


def _config(tmp_path: Path) -> tuple[Path, Path]:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    config = codex_home / "config.toml"
    existing = tmp_path / "existing"
    hooks = existing / ".codex/hooks.json"
    hooks.parent.mkdir(parents=True)
    hooks.write_text("{}", encoding="utf-8")
    gone = tmp_path / "gone"
    config.write_text(
        f'''model = "gpt-5.6-luna"

[hooks.state."{hooks}:session_start:0:0"]
trusted_hash = "keep"

[hooks.state."{gone}/.codex/hooks.json:session_start:0:0"]
trusted_hash = "remove"

[projects."{existing}"]
trust_level = "trusted"

[projects."{gone}"]
trust_level = "trusted"
''',
        encoding="utf-8",
    )
    return config, gone


def test_command_is_registered_as_tool_shaped():
    resolved = resolve_tool_shaped(["codex", "hook-trust", "sweep", "--dry-run"])

    assert resolved is not None
    adapter, remaining = resolved
    assert adapter is codex_hook_trust.codex_hook_trust_sweep
    assert remaining == ["--dry-run"]


def test_dry_run_reports_counts_without_changing_config(
    monkeypatch, tmp_path: Path, capsys
):
    config, _gone = _config(tmp_path)
    before = config.read_bytes()
    monkeypatch.setenv("CODEX_HOME", str(config.parent))

    assert codex_hook_trust.codex_hook_trust_sweep(["--dry-run", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["stale_hook_paths"] == 1
    assert payload["hook_entries_removed"] == 1
    assert payload["project_entries_removed"] == 1
    assert payload["changed"] is True
    assert payload["dry_run"] is True
    assert config.read_bytes() == before


def test_sweep_removes_only_gone_paths(monkeypatch, tmp_path: Path, capsys):
    config, gone = _config(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(config.parent))

    assert codex_hook_trust.codex_hook_trust_sweep(["--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    text = config.read_text(encoding="utf-8")
    assert payload["changed"] is True
    assert str(gone) not in text
    assert str(tmp_path / "existing") in text
    assert 'trusted_hash = "keep"' in text


def test_invalid_config_refuses_with_recovery(monkeypatch, tmp_path: Path, capsys):
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    config = codex_home / "config.toml"
    config.write_text("not valid toml = [", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    assert codex_hook_trust.codex_hook_trust_sweep([]) == 1

    error = capsys.readouterr().err
    assert str(config) in error
    assert "refused" in error
    assert "yoke codex hook-trust sweep" in error
