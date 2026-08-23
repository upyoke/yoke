"""Codex machine inventory requires exact normalized handler trust."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from yoke_cli.project_install.harness_inventory import (
    collect_harness_inventory as collect_cli_inventory,
)
from yoke_contracts.codex_hook_trust import normalized_codex_hook_hashes
from yoke_core.domain.harness_machine_inventory import (
    collect_harness_inventory as collect_core_inventory,
)


COLLECTORS = (collect_core_inventory, collect_cli_inventory)


def _payload(command: str = "echo hello") -> dict:
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": command}],
                }
            ]
        }
    }


def _write_hooks(checkout: Path, payload: object) -> Path:
    hooks = checkout / ".codex" / "hooks.json"
    hooks.parent.mkdir(parents=True, exist_ok=True)
    hooks.write_text(json.dumps(payload), encoding="utf-8")
    return hooks


def _write_config(home: Path, hooks: Path, trusted: dict[str, str]) -> None:
    home.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for suffix, digest in trusted.items():
        lines.extend(
            [
                f'\n[hooks.state."{hooks}:{suffix}"]\n',
                f'trusted_hash = "{digest}"\n',
            ]
        )
    (home / "config.toml").write_text("".join(lines), encoding="utf-8")


def _report(collector, checkout: Path) -> dict:
    return {row["harness_id"]: row for row in collector(checkout)}["codex"]


@pytest.fixture(params=COLLECTORS, ids=("core", "cli"))
def collector(request):
    return request.param


def test_normalized_hash_matches_codex_handler_identity() -> None:
    assert normalized_codex_hook_hashes(_payload()) == {
        "pre_tool_use:0:0": (
            "sha256:0db5a87976e34500eb1936b70b9d77f3e711825aa7f3a688eb4bbb0aeb07c0e7"
        )
    }


def test_every_matching_handler_is_approved(
    collector,
    monkeypatch,
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "project"
    payload = _payload()
    hooks = _write_hooks(checkout, payload)
    home = tmp_path / "codex-home"
    _write_config(home, hooks, normalized_codex_hook_hashes(payload) or {})
    monkeypatch.setenv("CODEX_HOME", str(home))

    report = _report(collector, checkout)

    assert report["glue_malformed"] is False
    assert report["approval_state"] == "approved"


def test_modified_handler_is_unapproved(
    collector,
    monkeypatch,
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "project"
    payload = _payload()
    hooks = _write_hooks(checkout, payload)
    home = tmp_path / "codex-home"
    _write_config(home, hooks, normalized_codex_hook_hashes(payload) or {})
    _write_hooks(checkout, _payload("echo modified"))
    monkeypatch.setenv("CODEX_HOME", str(home))

    assert _report(collector, checkout)["approval_state"] == "unapproved"


def test_missing_trust_entry_is_unapproved(
    collector,
    monkeypatch,
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "project"
    hooks = _write_hooks(checkout, _payload())
    home = tmp_path / "codex-home"
    _write_config(home, hooks, {})
    monkeypatch.setenv("CODEX_HOME", str(home))

    assert _report(collector, checkout)["approval_state"] == "unapproved"


def test_added_handler_is_unapproved(
    collector,
    monkeypatch,
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "project"
    payload = _payload()
    hooks = _write_hooks(checkout, payload)
    home = tmp_path / "codex-home"
    _write_config(home, hooks, normalized_codex_hook_hashes(payload) or {})
    expanded = deepcopy(payload)
    expanded["hooks"]["PreToolUse"][0]["hooks"].append(
        {"type": "command", "command": "echo second"}
    )
    _write_hooks(checkout, expanded)
    monkeypatch.setenv("CODEX_HOME", str(home))

    assert _report(collector, checkout)["approval_state"] == "unapproved"


def test_malformed_handler_is_unapproved(
    collector,
    monkeypatch,
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "project"
    payload = _payload()
    payload["hooks"]["PreToolUse"][0]["hooks"][0].pop("command")
    hooks = _write_hooks(checkout, payload)
    home = tmp_path / "codex-home"
    _write_config(home, hooks, {"pre_tool_use:0:0": "sha256:old"})
    monkeypatch.setenv("CODEX_HOME", str(home))

    report = _report(collector, checkout)

    assert report["glue_malformed"] is True
    assert report["approval_state"] == "unapproved"


def test_stale_trust_entry_is_unapproved(
    collector,
    monkeypatch,
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "project"
    payload = _payload()
    hooks = _write_hooks(checkout, payload)
    trusted = normalized_codex_hook_hashes(payload) or {}
    trusted["stop:9:9"] = "sha256:stale"
    home = tmp_path / "codex-home"
    _write_config(home, hooks, trusted)
    monkeypatch.setenv("CODEX_HOME", str(home))

    assert _report(collector, checkout)["approval_state"] == "unapproved"


def test_trust_for_another_literal_path_is_unapproved(
    collector,
    monkeypatch,
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "project"
    payload = _payload()
    _write_hooks(checkout, payload)
    other_hooks = tmp_path / "other" / ".codex" / "hooks.json"
    home = tmp_path / "codex-home"
    _write_config(home, other_hooks, normalized_codex_hook_hashes(payload) or {})
    monkeypatch.setenv("CODEX_HOME", str(home))

    assert _report(collector, checkout)["approval_state"] == "unapproved"
