"""Installing Claude's status line into a project without taking it over.

Claude allows one status line per session and it is the only surface that
states the served context window, so this pass has to do two things that
pull against each other: reach every installed project, and never overwrite
a status line an operator wrote. These pin both halves, plus the uninstall
that must remove only what the install actually seeded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli.project_install.files import ProjectInstallError
from yoke_cli.project_install.settings_status_line import (
    apply_settings_status_line,
    preview_settings_status_line,
    remove_settings_status_line,
)


_MANAGED = {"type": "command", "command": "/bin/sh -c 'yoke hook status-line'"}
_SETTINGS = ".claude/settings.json"


def _write_settings(root: Path, payload: dict) -> Path:
    target = root / _SETTINGS
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def _read_settings(root: Path) -> dict:
    return json.loads((root / _SETTINGS).read_text(encoding="utf-8"))


def test_a_project_with_no_status_line_gets_yokes(tmp_path: Path) -> None:
    _write_settings(tmp_path, {"hooks": {}})

    record, report = apply_settings_status_line(tmp_path, _MANAGED)

    assert record == {"seeded": True}
    assert report["changed"]
    assert _read_settings(tmp_path)["statusLine"] == _MANAGED


def test_an_operators_own_status_line_is_never_overwritten(tmp_path: Path) -> None:
    """Taking the slot from under an operator is the failure to prevent."""
    theirs = {"type": "command", "command": "my-statusline.sh"}
    _write_settings(tmp_path, {"hooks": {}, "statusLine": theirs})

    record, report = apply_settings_status_line(tmp_path, _MANAGED)

    assert record == {"seeded": False}
    assert not report["changed"]
    assert _read_settings(tmp_path)["statusLine"] == theirs


def test_the_kept_line_says_what_the_project_gives_up(tmp_path: Path) -> None:
    """Silence would read as "the attestation is broken" rather than a choice."""
    _write_settings(
        tmp_path,
        {"statusLine": {"type": "command", "command": "mine.sh"}},
    )

    _record, report = apply_settings_status_line(tmp_path, _MANAGED)

    assert "context_window_tokens" in " ".join(report["actions"])


def test_a_refresh_converges_yokes_own_line(tmp_path: Path) -> None:
    """The command changes between releases; the seeded slot follows it."""
    _write_settings(
        tmp_path,
        {"statusLine": {"type": "command", "command": "stale"}},
    )

    record, report = apply_settings_status_line(tmp_path, _MANAGED, {"seeded": True})

    assert record == {"seeded": True}
    assert report["changed"]
    assert _read_settings(tmp_path)["statusLine"] == _MANAGED


def test_a_second_install_of_the_same_command_writes_nothing(
    tmp_path: Path,
) -> None:
    _write_settings(tmp_path, {"statusLine": dict(_MANAGED)})

    _record, report = apply_settings_status_line(tmp_path, _MANAGED, {"seeded": True})

    assert not report["changed"]


def test_uninstall_removes_only_a_line_this_install_seeded(
    tmp_path: Path,
) -> None:
    _write_settings(tmp_path, {"hooks": {}, "statusLine": dict(_MANAGED)})

    assert remove_settings_status_line(tmp_path, {"seeded": True}) == {"removed": True}
    assert "statusLine" not in _read_settings(tmp_path)


def test_uninstall_leaves_an_operators_status_line_alone(tmp_path: Path) -> None:
    theirs = {"type": "command", "command": "mine.sh"}
    _write_settings(tmp_path, {"statusLine": theirs})

    assert remove_settings_status_line(tmp_path, {"seeded": False}) == {
        "removed": False
    }
    assert _read_settings(tmp_path)["statusLine"] == theirs


def test_preview_reports_the_seed_without_writing(tmp_path: Path) -> None:
    _write_settings(tmp_path, {"hooks": {}})

    result = preview_settings_status_line(tmp_path, _MANAGED)

    assert result["would_change"]
    assert "statusLine" not in _read_settings(tmp_path)


def test_a_malformed_managed_region_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(ProjectInstallError):
        apply_settings_status_line(tmp_path, {"type": "command"})
    with pytest.raises(ProjectInstallError):
        apply_settings_status_line(tmp_path, {"command": "x", "type": "inline"})


def test_no_managed_region_is_a_no_op(tmp_path: Path) -> None:
    record, report = apply_settings_status_line(tmp_path, None)

    assert record == {}
    assert not report["changed"]
