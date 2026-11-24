"""Answering each harness's folder-trust prompt for one checkout or lane.

Approval posture and folder trust are separate gates, so these cover the
second one on its own terms: grant what is missing, never touch what the
operator or the harness already wrote, and skip a harness that is not here.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

from yoke_contracts import harness_settings_ledger as ledger
from yoke_contracts.harness_folder_trust import (
    CLAUDE_PROJECTS_KEY,
    CLAUDE_TRUST_KEY,
    CURSOR_TRUST_FILENAME,
    claude_trust_key,
    cursor_project_slug,
    trust_key,
)
from yoke_contracts.harness_folder_trust_grant import grant_folder_trust
from yoke_contracts.codex_config_posture import parse_config

# A checkout on this machine: folder trust keys local absolute paths.
CHECKOUT = str(Path("/repos/example").absolute())


def _claude(tmp_path: Path, payload: dict) -> Path:
    target = tmp_path / ".claude.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def _cursor(tmp_path: Path) -> Path:
    projects = tmp_path / "projects"
    projects.mkdir(parents=True)
    return projects / cursor_project_slug(CHECKOUT) / CURSOR_TRUST_FILENAME


def _codex(tmp_path: Path, text: str = "") -> Path:
    home = tmp_path / ".codex"
    home.mkdir(parents=True)
    target = home / "config.toml"
    target.write_text(text, encoding="utf-8")
    return target


def test_cursor_slug_matches_the_shape_cursor_writes():
    """Verified against the entries Cursor itself wrote for these paths."""
    assert cursor_project_slug("/Users/me") == "Users-me"
    assert cursor_project_slug("/Users/me/.claude/jobs/x/cl_silent") == (
        "Users-me-claude-jobs-x-cl-silent"
    )
    assert cursor_project_slug("/Users/me/yoke/.worktrees/YOK-1") == (
        "Users-me-yoke-worktrees-YOK-1"
    )


def test_claude_key_is_forward_slash_while_native_key_stays(monkeypatch):
    windows = PureWindowsPath(r"C:\Users\u\proj")
    monkeypatch.setattr(
        "yoke_contracts.harness_folder_trust.Path",
        lambda _value: SimpleNamespace(expanduser=lambda: windows),
    )
    assert claude_trust_key("ignored") == "C:/Users/u/proj"
    assert trust_key("ignored") == r"C:\Users\u\proj"


def test_claude_grant_and_ledger_use_the_claude_key(tmp_path: Path, monkeypatch):
    sentinel = "C:/sentinel/claude-key"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    monkeypatch.setattr(
        "yoke_contracts.harness_folder_trust_grant.claude_trust_key",
        lambda _checkout: sentinel,
    )
    claude = _claude(tmp_path, {"projects": {}})
    grant_folder_trust(CHECKOUT, harnesses=("claude-code",), claude_state=claude)
    projects = json.loads(claude.read_text())[CLAUDE_PROJECTS_KEY]
    assert list(projects) == [sentinel]
    assert projects[sentinel][CLAUDE_TRUST_KEY] is True
    [entry] = ledger.read()
    assert entry["keys"][1] == sentinel


def test_every_present_harness_is_granted(tmp_path: Path):
    claude = _claude(tmp_path, {"projects": {}})
    codex = _codex(tmp_path)
    cursor = _cursor(tmp_path)
    granted = grant_folder_trust(
        CHECKOUT, claude_state=claude, codex_config=codex, cursor_file=cursor
    )
    assert len(granted) >= 3
    claude_payload = json.loads(claude.read_text())
    assert claude_payload[CLAUDE_PROJECTS_KEY][claude_trust_key(CHECKOUT)][CLAUDE_TRUST_KEY] is True
    assert parse_config(codex.read_text())["projects"][CHECKOUT]["trust_level"] == (
        "trusted"
    )
    assert json.loads(cursor.read_text())["workspacePath"] == CHECKOUT


def test_granting_twice_changes_nothing(tmp_path: Path):
    claude = _claude(tmp_path, {"projects": {}})
    codex = _codex(tmp_path)
    cursor = _cursor(tmp_path)
    grant_folder_trust(
        CHECKOUT, claude_state=claude, codex_config=codex, cursor_file=cursor
    )
    before = (claude.read_text(), codex.read_text(), cursor.read_text())
    assert (
        grant_folder_trust(
            CHECKOUT, claude_state=claude, codex_config=codex, cursor_file=cursor
        )
        == []
    )
    assert (claude.read_text(), codex.read_text(), cursor.read_text()) == before


def test_an_absent_harness_is_skipped_not_created(tmp_path: Path):
    missing_claude = tmp_path / "nothing" / ".claude.json"
    missing_codex = tmp_path / "nothing" / "config.toml"
    missing_cursor = tmp_path / "nothing" / "projects" / "x" / CURSOR_TRUST_FILENAME
    assert (
        grant_folder_trust(
            CHECKOUT,
            claude_state=missing_claude,
            codex_config=missing_codex,
            cursor_file=missing_cursor,
        )
        == []
    )
    assert not missing_claude.exists()
    assert not missing_codex.exists()
    assert not missing_cursor.exists()


def test_claude_keeps_every_unrelated_project_and_key(tmp_path: Path):
    claude = _claude(
        tmp_path,
        {
            "projects": {"/other": {"allowedTools": ["x"]}},
            "someTopLevelSetting": 7,
        },
    )
    grant_folder_trust(
        CHECKOUT,
        claude_state=claude,
        codex_config=tmp_path / "gone" / "config.toml",
        cursor_file=tmp_path / "gone" / "x",
    )
    payload = json.loads(claude.read_text())
    assert payload["someTopLevelSetting"] == 7
    assert payload[CLAUDE_PROJECTS_KEY]["/other"] == {"allowedTools": ["x"]}
    assert payload[CLAUDE_PROJECTS_KEY][claude_trust_key(CHECKOUT)][CLAUDE_TRUST_KEY] is True


def test_cursor_grant_preserves_native_microseconds(tmp_path: Path, monkeypatch):
    frozen = datetime(
        2026, 10, 9, 23, 45, 12, 123456, tzinfo=timezone(timedelta(hours=5, minutes=45))
    )
    monkeypatch.setattr(
        "yoke_contracts.harness_folder_trust_grant.utc_now", lambda: frozen
    )
    cursor = _cursor(tmp_path)
    grant_folder_trust(
        CHECKOUT,
        claude_state=tmp_path / "absent-claude",
        codex_config=tmp_path / "absent-codex",
        cursor_file=cursor,
    )
    payload = json.loads(cursor.read_text())
    assert payload["trustedAt"] == "2026-10-09T18:00:12.123456Z"
    assert payload["workspacePath"] == CHECKOUT


def test_cursor_workspace_folder_yoke_made_is_removed_with_its_trust(
    tmp_path: Path, monkeypatch
):
    from yoke_contracts.harness_settings_revert import revert_recorded

    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    cursor = _cursor(tmp_path)
    grant_folder_trust(
        CHECKOUT,
        claude_state=tmp_path / "absent-claude",
        codex_config=tmp_path / "absent-codex",
        cursor_file=cursor,
    )
    assert cursor.is_file()
    lines, failures = revert_recorded()
    assert failures == []
    assert not cursor.parent.exists()
    assert cursor.parent.parent.is_dir()  # Cursor's own projects folder stays.
    assert f"removed empty {cursor.parent}" in lines
