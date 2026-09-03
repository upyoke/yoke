"""Answering each harness's folder-trust prompt for one checkout or lane.

Approval posture and folder trust are separate gates, so these cover the
second one on its own terms: grant what is missing, never touch what the
operator or the harness already wrote, and skip a harness that is not here.
"""

from __future__ import annotations

import json
from pathlib import Path

from yoke_contracts.harness_folder_trust import (
    CLAUDE_PROJECTS_KEY,
    CLAUDE_TRUST_KEY,
    CURSOR_TRUST_FILENAME,
    cursor_project_slug,
)
from yoke_core.domain.harness_folder_trust_grant import grant_folder_trust
from yoke_core.tools.install_yoke_launcher_codex_config import parse_config

CHECKOUT = "/repos/example"


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


def test_every_present_harness_is_granted(tmp_path: Path):
    claude = _claude(tmp_path, {"projects": {}})
    codex = _codex(tmp_path)
    cursor = _cursor(tmp_path)
    granted = grant_folder_trust(
        CHECKOUT, claude_state=claude, codex_config=codex, cursor_file=cursor
    )
    assert len(granted) >= 3
    claude_payload = json.loads(claude.read_text())
    assert claude_payload[CLAUDE_PROJECTS_KEY][CHECKOUT][CLAUDE_TRUST_KEY] is True
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
    assert grant_folder_trust(
        CHECKOUT, claude_state=claude, codex_config=codex, cursor_file=cursor
    ) == []
    assert (claude.read_text(), codex.read_text(), cursor.read_text()) == before


def test_an_absent_harness_is_skipped_not_created(tmp_path: Path):
    missing_claude = tmp_path / "nothing" / ".claude.json"
    missing_codex = tmp_path / "nothing" / "config.toml"
    missing_cursor = tmp_path / "nothing" / "projects" / "x" / CURSOR_TRUST_FILENAME
    assert grant_folder_trust(
        CHECKOUT,
        claude_state=missing_claude,
        codex_config=missing_codex,
        cursor_file=missing_cursor,
    ) == []
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
    assert payload[CLAUDE_PROJECTS_KEY][CHECKOUT][CLAUDE_TRUST_KEY] is True
