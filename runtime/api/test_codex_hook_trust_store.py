"""Mint, retire, and sweep Codex hook trust without harming live entries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 CI
    import tomli as tomllib  # type: ignore[no-redef]

from yoke_contracts.codex_hook_trust import codex_hook_hashes
from yoke_contracts.codex_hook_trust_store import (
    CodexHookTrustStoreError,
    inspect_hook_file_trust,
    mint_installed_checkout_trust,
    remove_checkout_trust,
    stale_trust_scan,
    sweep_stale_trust,
)


HOOKS = {
    "hooks": {
        "SessionStart": [
            {
                "matcher": "startup",
                "hooks": [
                    {"type": "command", "command": "yoke hook evaluate SessionStart"}
                ],
            }
        ],
        "Stop": [
            {"hooks": [{"type": "command", "command": "yoke hook evaluate Stop"}]}
        ],
    }
}


def _checkout(root: Path, name: str) -> Path:
    checkout = root / name
    hooks = checkout / ".codex/hooks.json"
    hooks.parent.mkdir(parents=True)
    hooks.write_text(json.dumps(HOOKS), encoding="utf-8")
    return checkout


def _config(path: Path, hook_entries=(), projects=()) -> Path:
    lines = ['model = "gpt-5.6-luna"\n']
    for key, digest in hook_entries:
        lines.extend([f'\n[hooks.state."{key}"]\n', f'trusted_hash = "{digest}"\n'])
    for project in projects:
        lines.extend([f'\n[projects."{project}"]\n', 'trust_level = "trusted"\n'])
    path.write_text("".join(lines), encoding="utf-8")
    return path


def _state(config: Path) -> dict:
    return tomllib.loads(config.read_text(encoding="utf-8"))


def _trust(checkout: Path) -> list[tuple[str, str]]:
    hooks = checkout / ".codex/hooks.json"
    return [
        (f"{hooks}:{suffix}", digest)
        for suffix, digest in codex_hook_hashes(hooks).items()
    ]


def test_install_mints_exact_hashes_and_replaces_stale_same_path(tmp_path: Path):
    checkout = _checkout(tmp_path, "project")
    hooks = checkout / ".codex/hooks.json"
    foreign = _checkout(tmp_path, "foreign")
    config = _config(
        tmp_path / "config.toml",
        [
            (f"{hooks}:session_start:0:0", "sha256:stale"),
            (f"{hooks}:retired_event:9:9", "sha256:retired"),
            *_trust(foreign),
        ],
        [str(foreign)],
    )

    result = mint_installed_checkout_trust(checkout, config_path=config)

    assert result.changed is True
    assert result.hook_entries_removed == 2
    assert result.hook_entries_written == 2
    assert inspect_hook_file_trust(hooks, config_path=config).approved is True
    state = _state(config)
    assert str(foreign) in state["projects"]
    for key, digest in _trust(foreign):
        assert state["hooks"]["state"][key]["trusted_hash"] == digest


def test_install_mint_is_idempotent(tmp_path: Path):
    checkout = _checkout(tmp_path, "project")
    config = _config(tmp_path / "config.toml")
    mint_installed_checkout_trust(checkout, config_path=config)
    before = config.read_bytes()

    result = mint_installed_checkout_trust(checkout, config_path=config)

    assert result.changed is False
    assert config.read_bytes() == before


def test_install_mint_creates_missing_codex_config_home(tmp_path: Path):
    checkout = _checkout(tmp_path, "project")
    config = tmp_path / "new-codex-home/config.toml"

    result = mint_installed_checkout_trust(checkout, config_path=config)

    assert result.changed is True
    assert config.is_file()
    assert inspect_hook_file_trust(
        checkout / ".codex/hooks.json", config_path=config
    ).approved


def test_install_refuses_an_unreadable_config_with_the_path(tmp_path: Path):
    checkout = _checkout(tmp_path, "project")
    config = tmp_path / "config.toml"
    config.write_text("[broken", encoding="utf-8")

    with pytest.raises(CodexHookTrustStoreError, match="config.toml"):
        mint_installed_checkout_trust(checkout, config_path=config)

    assert config.read_text(encoding="utf-8") == "[broken"


def test_retired_worktree_loses_hook_and_project_trust_only(tmp_path: Path):
    lane = _checkout(tmp_path, "lane")
    live = _checkout(tmp_path, "live")
    config = _config(
        tmp_path / "config.toml",
        [*_trust(lane), *_trust(live)],
        [str(lane), str(live)],
    )

    result = remove_checkout_trust(lane, config_path=config)

    assert result.hook_entries_removed == 2
    assert result.project_entries_removed == 1
    state = _state(config)
    assert str(lane) not in state["projects"]
    assert str(live) in state["projects"]
    assert all(not key.startswith(f"{lane}/") for key in state["hooks"]["state"])
    assert len(state["hooks"]["state"]) == 2


def test_sweep_dry_run_then_removes_only_deleted_paths(tmp_path: Path):
    live = _checkout(tmp_path, "live")
    gone = _checkout(tmp_path, "gone")
    gone_entries = _trust(gone)
    gone_hooks = gone / ".codex/hooks.json"
    gone_hooks.unlink()
    gone_hooks.parent.rmdir()
    gone.rmdir()
    config = _config(
        tmp_path / "config.toml",
        [*_trust(live), *gone_entries],
        [str(live), str(gone)],
    )
    before = config.read_bytes()

    scan = stale_trust_scan(config_path=config)
    preview = sweep_stale_trust(config_path=config, dry_run=True)

    assert len(scan.hook_keys) == 2
    assert scan.hook_paths == (str(gone_hooks),)
    assert scan.project_paths == (str(gone),)
    assert preview.changed is True
    assert preview.dry_run is True
    assert config.read_bytes() == before

    applied = sweep_stale_trust(config_path=config)
    assert applied.hook_entries_removed == 2
    assert applied.project_entries_removed == 1
    assert applied.stale_hook_paths == 1
    assert (
        inspect_hook_file_trust(live / ".codex/hooks.json", config_path=config).approved
        is True
    )


def test_sweep_preserves_unrecognized_and_relative_keys(tmp_path: Path):
    config = _config(
        tmp_path / "config.toml",
        [("bundled-browser-state", "sha256:foreign")],
        ["relative-project"],
    )

    result = sweep_stale_trust(config_path=config)

    assert result.changed is False
    state = _state(config)
    assert "bundled-browser-state" in state["hooks"]["state"]
    assert "relative-project" in state["projects"]


def test_sweep_parses_equals_signs_inside_quoted_paths(tmp_path: Path):
    gone = tmp_path / "deleted=checkout"
    hooks = gone / ".codex/hooks.json"
    config = _config(
        tmp_path / "config.toml",
        [(f"{hooks}:session_start:0:0", "sha256:stale")],
        [str(gone)],
    )

    result = sweep_stale_trust(config_path=config)

    assert result.hook_entries_removed == 1
    assert result.project_entries_removed == 1
    assert str(gone) not in config.read_text(encoding="utf-8")
