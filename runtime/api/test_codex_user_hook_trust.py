"""Codex trust for the user-level hooks file covers only Yoke's handlers."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_contracts.codex_hook_trust_store import (
    inspect_hook_file_trust,
    sweep_stale_trust,
)
from yoke_contracts.codex_hook_trust_toml import read_trust_state, entries_for
from yoke_harness.hooks.machine_hooks import ensure_machine_hooks, remove_machine_hooks


def _codex(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    home = tmp_path / ".codex"
    home.mkdir()
    return {"HOME": str(tmp_path)}, home / "hooks.json", home / "config.toml"


def _trusted(config: Path, hooks: Path) -> dict[str, str]:
    state, _ = read_trust_state(config)
    return entries_for(state, hooks)


def test_install_trusts_yoke_handlers_and_reinstall_is_a_noop(tmp_path):
    env, hooks, config = _codex(tmp_path)
    [result] = ensure_machine_hooks(["codex"], env)
    assert result.outcome == "installed", result.line()
    assert inspect_hook_file_trust(hooks, config_path=config).approved
    text = config.read_text()

    ensure_machine_hooks(["codex"], env)
    assert config.read_text() == text


def test_a_persons_untrusted_handler_stays_untrusted(tmp_path):
    env, hooks, config = _codex(tmp_path)
    mine = {"hooks": [{"type": "command", "command": "echo mine"}]}
    hooks.write_text(json.dumps({"hooks": {"Stop": [mine]}}))

    ensure_machine_hooks(["codex"], env)
    trusted = _trusted(config, hooks)
    assert "stop:0:0" not in trusted  # the person's own handler
    assert "stop:1:0" in trusted  # Yoke's handler, appended after it


def test_changed_file_is_retrusted(tmp_path):
    env, hooks, config = _codex(tmp_path)
    ensure_machine_hooks(["codex"], env)
    document = json.loads(hooks.read_text())
    document["hooks"]["Stop"][0]["hooks"][0]["command"] += " --stale"
    hooks.write_text(json.dumps(document))
    assert not inspect_hook_file_trust(hooks, config_path=config).approved

    ensure_machine_hooks(["codex"], env)
    assert inspect_hook_file_trust(hooks, config_path=config).approved


def test_uninstall_removes_yoke_trust_and_keeps_unrelated_config(tmp_path):
    env, hooks, config = _codex(tmp_path)
    config.write_text('model = "o5"\n')
    ensure_machine_hooks(["codex"], env)
    assert _trusted(config, hooks)

    results = {r.harness_id: r for r in remove_machine_hooks(env)}
    assert results["codex"].outcome == "deleted"
    assert _trusted(config, hooks) == {}
    assert 'model = "o5"' in config.read_text()


def test_sweep_keeps_the_user_level_entries(tmp_path):
    env, hooks, config = _codex(tmp_path)
    ensure_machine_hooks(["codex"], env)
    before = _trusted(config, hooks)

    result = sweep_stale_trust(config_path=config)
    assert result.hook_entries_removed == 0
    assert _trusted(config, hooks) == before


def test_codex_absent_writes_no_trust(tmp_path):
    [result] = ensure_machine_hooks(["codex"], {"HOME": str(tmp_path)})
    assert result.outcome == "codex_not_installed"
    assert not (tmp_path / ".codex").exists()
