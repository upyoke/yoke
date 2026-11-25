"""Codex hook trust mirrored from a checkout into its linked worktrees.

Codex keys hook trust by the literal path of the hooks file it loaded, so a
worktree starts out with none of the checkout's trust and its hooks never
fire. These tests pin the mirroring contract: trust is copied only onto
hook content that matches after CRLF normalization. Existing config bytes are
never rewritten, and repeated runs are no-ops.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from yoke_contracts.codex_hook_trust_toml import _toml_string
from yoke_contracts.harness_folder_trust import codex_path_spellings

import pytest

import tomllib

from yoke_core.domain.codex_hook_trust_identity import (
    codex_hook_hashes,
    codex_hook_hashes_from_document,
)
from yoke_contracts.codex_lane_hook_trust import (
    REASON_CONTENT_DIFFERS,
    REASON_SOURCE_UNTRUSTED,
    codex_config_path,
    inspect_hook_trust,
    mirror_hook_trust,
)


START_COMMAND = "yoke hook evaluate SessionStart"
TOOL_COMMAND = "yoke hook evaluate PreToolUse"
HOOKS_DOCUMENT = {
    "hooks": {
        "SessionStart": [
            {
                "matcher": "startup|resume",
                "hooks": [{"type": "command", "command": START_COMMAND}],
            }
        ],
        "PreToolUse": [
            {
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": TOOL_COMMAND}],
            }
        ],
    }
}
HOOKS_BODY = json.dumps(HOOKS_DOCUMENT)
SUFFIXES = ("session_start:0:0", "pre_tool_use:0:0")


def _checkout(root: Path, name: str, hooks_body: str = HOOKS_BODY) -> Path:
    """Create a checkout-shaped directory exposing a Codex hooks file."""
    checkout = root / name
    (checkout / ".codex").mkdir(parents=True)
    (checkout / ".codex" / "hooks.json").write_text(hooks_body, encoding="utf-8")
    return checkout


def _config(path: Path, trusted: dict) -> Path:
    """Write a Codex config carrying the given ``key -> hash`` trust."""
    lines = ['model = "gpt-5.6-luna"\n']
    for key, value in trusted.items():
        lines.append(
            f'\n[hooks.state.{_toml_string(str(key))}]\ntrusted_hash = "{value}"\n'
        )
    path.write_text("".join(lines), encoding="utf-8")
    return path


def _trust_for(checkout: Path) -> dict:
    hooks = checkout / ".codex" / "hooks.json"
    return {
        f"{hooks}:{suffix}": digest
        for suffix, digest in codex_hook_hashes(hooks).items()
    }


@pytest.fixture()
def lanes(tmp_path: Path):
    """A trusted source checkout, an untrusted worktree, and a config."""
    source = _checkout(tmp_path, "checkout")
    worktree = _checkout(tmp_path / "checkout" / ".worktrees", "lane")
    config = _config(tmp_path / "config.toml", _trust_for(source))
    return source, worktree, config


def _state(config: Path) -> dict:
    return tomllib.loads(config.read_text(encoding="utf-8"))["hooks"]["state"]


def test_untrusted_worktree_reads_as_a_dead_zone(lanes):
    source, worktree, config = lanes

    result = inspect_hook_trust(str(source), str(worktree), config_path=config)

    assert result.dead_zone is True
    assert result.hooks_fire is False
    assert set(result.missing) == set(SUFFIXES)


@pytest.mark.parametrize("lane_newline", [b"\n", b"\r\n"], ids=["lf", "crlf"])
def test_mirroring_grants_the_worktree_the_source_hashes(lanes, lane_newline):
    source, worktree, config = lanes
    source_body = json.dumps(HOOKS_DOCUMENT, indent=2).encode("utf-8") + b"\n"
    (source / ".codex/hooks.json").write_bytes(source_body)
    (worktree / ".codex/hooks.json").write_bytes(
        source_body.replace(b"\n", lane_newline)
    )

    result = mirror_hook_trust(str(source), str(worktree), config_path=config)

    assert set(result.mirrored) == set(SUFFIXES)
    assert result.hooks_fire is True
    inspected = inspect_hook_trust(str(source), str(worktree), config_path=config)
    assert not inspected.blocked_reason
    assert inspected.hooks_fire
    state = _state(config)
    target_hooks = worktree / ".codex" / "hooks.json"
    for suffix in SUFFIXES:
        source_key = f"{source / '.codex' / 'hooks.json'}:{suffix}"
        for spelling in codex_path_spellings(target_hooks):
            assert (
                state[f"{spelling}:{suffix}"]["trusted_hash"]
                == state[source_key]["trusted_hash"]
            )


def test_mirroring_leaves_existing_config_bytes_untouched(lanes):
    source, worktree, config = lanes
    before = config.read_bytes()

    mirror_hook_trust(str(source), str(worktree), config_path=config)

    assert config.read_bytes().startswith(before)


def test_mirroring_appends_a_separator_when_the_config_lacks_one(lanes):
    source, worktree, config = lanes
    config.write_text(config.read_text(encoding="utf-8").rstrip("\n"), encoding="utf-8")

    mirror_hook_trust(str(source), str(worktree), config_path=config)

    assert len(_state(config)) == (1 + len(codex_path_spellings(worktree))) * len(SUFFIXES)


def test_mirroring_twice_writes_nothing_the_second_time(lanes):
    source, worktree, config = lanes
    mirror_hook_trust(str(source), str(worktree), config_path=config)
    after_first = config.read_bytes()

    again = mirror_hook_trust(str(source), str(worktree), config_path=config)

    assert again.mirrored == ()
    assert again.hooks_fire is True
    assert config.read_bytes() == after_first


def test_differing_hook_content_is_never_granted_trust(tmp_path: Path):
    source = _checkout(tmp_path, "checkout")
    worktree = _checkout(
        tmp_path / "checkout" / ".worktrees",
        "lane",
        hooks_body=HOOKS_BODY.replace(START_COMMAND, START_COMMAND + " changed"),
    )
    config = _config(tmp_path / "config.toml", _trust_for(source))

    result = mirror_hook_trust(str(source), str(worktree), config_path=config)

    assert result.blocked_reason == REASON_CONTENT_DIFFERS
    assert result.mirrored == ()
    assert len(_state(config)) == len(SUFFIXES)


def test_an_entry_carrying_a_different_hash_reads_as_stale(lanes):
    source, worktree, config = lanes
    trusted = _trust_for(source)
    hooks = worktree / ".codex" / "hooks.json"
    modified = json.loads(HOOKS_BODY)
    modified["hooks"]["SessionStart"][0]["hooks"][0]["command"] += " changed"
    trusted[f"{hooks}:{SUFFIXES[0]}"] = codex_hook_hashes_from_document(modified)[
        SUFFIXES[0]
    ]
    _config(config, trusted)

    result = inspect_hook_trust(str(source), str(worktree), config_path=config)

    assert result.stale == (SUFFIXES[0],)
    assert result.hooks_fire is False


def test_hash_normalization_includes_codex_command_defaults():
    identity = {
        "event_name": "stop",
        "hooks": [
            {
                "async": False,
                "command": "yoke hook evaluate Stop",
                "timeout": 600,
                "type": "command",
            }
        ],
    }
    canonical = json.dumps(
        identity, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    expected = f"sha256:{hashlib.sha256(canonical).hexdigest()}"

    actual = codex_hook_hashes_from_document(
        {
            "hooks": {
                "Stop": [
                    {
                        "matcher": "ignored",
                        "hooks": [
                            {"command": "yoke hook evaluate Stop", "type": "command"}
                        ],
                    }
                ]
            }
        }
    )

    assert actual == {"stop:0:0": expected}


def test_an_untrusted_source_has_nothing_to_mirror(tmp_path: Path):
    source = _checkout(tmp_path, "checkout")
    worktree = _checkout(tmp_path / "checkout" / ".worktrees", "lane")
    config = _config(tmp_path / "config.toml", {})

    result = mirror_hook_trust(str(source), str(worktree), config_path=config)

    assert result.blocked_reason == REASON_SOURCE_UNTRUSTED
    assert result.dead_zone is False


def test_a_missing_config_blocks_without_raising(tmp_path: Path):
    source = _checkout(tmp_path, "checkout")
    worktree = _checkout(tmp_path / "checkout" / ".worktrees", "lane")

    result = mirror_hook_trust(
        str(source),
        str(worktree),
        config_path=tmp_path / "absent.toml",
    )

    assert result.blocked_reason
    assert result.mirrored == ()


def test_a_quote_in_a_lane_path_stays_valid_toml(tmp_path: Path):
    source = _checkout(tmp_path, "checkout")
    worktree = _checkout(
        tmp_path / "checkout" / ".worktrees", "la=ne" if os.name == "nt" else 'la"ne'
    )
    config = _config(tmp_path / "config.toml", _trust_for(source))

    result = mirror_hook_trust(str(source), str(worktree), config_path=config)

    assert set(result.mirrored) == set(SUFFIXES)
    hooks = worktree / ".codex" / "hooks.json"
    assert f"{hooks}:{SUFFIXES[0]}" in _state(config)


def test_codex_home_selects_the_config_that_is_read(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))

    assert codex_config_path() == tmp_path / "codex" / "config.toml"


def test_stale_source_blocks_mirroring_without_marking_lane_modified(lanes):
    source, worktree, config = lanes
    source_hooks = source / ".codex/hooks.json"
    document = json.loads(source_hooks.read_text())
    document["hooks"]["SessionStart"][0]["hooks"][0]["command"] += " changed"
    source_hooks.write_text(json.dumps(document))
    before = config.read_bytes()

    result = mirror_hook_trust(str(source), str(worktree), config_path=config)

    assert result.blocked_reason
    assert not result.hooks_fire
    assert result.stale == ()
    assert result.mirrored == ()
    assert config.read_bytes() == before


@pytest.mark.windows_only(reason="Codex uses both drive-letter spellings on native Windows")
def test_mirroring_repairs_the_missing_lowercase_lane_path(lanes):
    source, worktree, config = lanes
    hooks = worktree / ".codex/hooks.json"
    upper, lower = codex_path_spellings(hooks)
    hashes = codex_hook_hashes(hooks)
    original = _config(config, {
        **_trust_for(source),
        **{f"{upper}:{suffix}": digest for suffix, digest in hashes.items()},
    }).read_bytes()

    result = inspect_hook_trust(str(source), str(worktree), config_path=config)
    assert not result.hooks_fire
    assert result.untrusted_paths == (lower,)
    assert lower in result.summary()

    result = mirror_hook_trust(str(source), str(worktree), config_path=config)
    assert result.hooks_fire
    assert config.read_bytes().startswith(original)
    assert {key: _state(config)[f"{lower}:{key}"]["trusted_hash"] for key in hashes} == hashes
