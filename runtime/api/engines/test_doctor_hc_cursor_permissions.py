"""Tests for the Cursor approval and network-sandbox health checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.cursor_permissions import (
    CURSOR_CLI_ALLOW,
    CURSOR_CLI_REL,
    CURSOR_SANDBOX_REL,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks import check_cursor_permissions as mod

CONFIGURED_ORIGIN = "control.example.test"


@pytest.fixture
def machine_config(tmp_path: Path, monkeypatch) -> Path:
    """Machine config declaring one https control plane.

    Engines tests are isolated from the live machine config through
    ``YOKE_MACHINE_CONFIG_FILE``, so this overrides that same variable
    rather than the machine home the file would otherwise be found under.
    """
    path = tmp_path / "machine-config.json"
    path.write_text(
        json.dumps(
            {
                "connections": {
                    "prod": {
                        "transport": "https",
                        "api_url": f"https://{CONFIGURED_ORIGIN}/api/orgs/acme",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(path))
    return path


def _seed(root: Path, *, allow=None, origins=None) -> None:
    cursor = root / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    (root / CURSOR_CLI_REL).write_text(
        json.dumps(
            {"permissions": {"allow": list(CURSOR_CLI_ALLOW if allow is None else allow)}}
        ),
        encoding="utf-8",
    )
    (root / CURSOR_SANDBOX_REL).write_text(
        json.dumps(
            {
                "networkPolicy": {
                    "default": "deny",
                    "allow": [CONFIGURED_ORIGIN] if origins is None else origins,
                }
            }
        ),
        encoding="utf-8",
    )


def _run(fn, root: Path, monkeypatch):
    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: str(root))
    records = RecordCollector()
    fn(None, DoctorArgs(), records)
    assert len(records.results) == 1
    return records.results[0]


def _user_config(tmp_path: Path, monkeypatch, payload) -> None:
    path = tmp_path / "cli-config.json"
    if payload is not None:
        path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(mod, "_USER_CLI_CONFIG", path)


def test_declares_cursor_permission_checks() -> None:
    assert [check.slug for check in mod.PROJECT_HEALTH_CHECKS] == [
        "cursor-permission-config",
        "cursor-approval-posture",
    ]


def test_complete_config_passes(monkeypatch, tmp_path, machine_config) -> None:
    _seed(tmp_path)

    result = _run(mod.hc_cursor_permission_config, tmp_path, monkeypatch)

    assert result.result == "PASS"


def test_missing_config_names_the_repair(monkeypatch, tmp_path, machine_config) -> None:
    result = _run(mod.hc_cursor_permission_config, tmp_path, monkeypatch)

    assert result.result == "FAIL"
    assert "yoke project install" in result.detail


def test_empty_allow_list_is_the_abort_class(
    monkeypatch, tmp_path, machine_config,
) -> None:
    _seed(tmp_path, allow=[])

    result = _run(mod.hc_cursor_permission_config, tmp_path, monkeypatch)

    assert result.result == "FAIL"
    assert "aborts every run" in result.detail


def test_symlinked_config_is_reported(monkeypatch, tmp_path, machine_config) -> None:
    _seed(tmp_path)
    (tmp_path / CURSOR_CLI_REL).unlink()
    (tmp_path / CURSOR_CLI_REL).symlink_to("elsewhere.json")

    result = _run(mod.hc_cursor_permission_config, tmp_path, monkeypatch)

    assert result.result == "FAIL"
    assert "symlink" in result.detail


def test_missing_control_plane_origin_is_reported(
    monkeypatch, tmp_path, machine_config,
) -> None:
    _seed(tmp_path, origins=["unrelated.example.test"])

    result = _run(mod.hc_cursor_permission_config, tmp_path, monkeypatch)

    assert result.result == "FAIL"
    assert CONFIGURED_ORIGIN in result.detail


def test_posture_check_prints_the_settings_to_change(
    monkeypatch, tmp_path, machine_config,
) -> None:
    _user_config(tmp_path, monkeypatch, {"permissions": {"allow": ["Shell(ls)"]}})

    result = _run(mod.hc_cursor_approval_posture, tmp_path, monkeypatch)

    assert result.result == "WARN"
    assert "Run Everything" in result.detail
    assert "does not allow the yoke command family" in result.detail


def test_posture_check_warns_when_user_config_is_absent(
    monkeypatch, tmp_path, machine_config,
) -> None:
    _user_config(tmp_path, monkeypatch, None)

    result = _run(mod.hc_cursor_approval_posture, tmp_path, monkeypatch)

    assert result.result == "WARN"
    assert "Run Everything" in result.detail


def test_posture_check_passes_on_an_allowing_config(
    monkeypatch, tmp_path, machine_config,
) -> None:
    _user_config(
        tmp_path, monkeypatch, {"permissions": {"allow": ["Shell(yoke *)"], "deny": []}},
    )

    result = _run(mod.hc_cursor_approval_posture, tmp_path, monkeypatch)

    assert result.result == "PASS"


def test_posture_check_flags_deny_entries_for_reconciliation(
    monkeypatch, tmp_path, machine_config,
) -> None:
    _user_config(
        tmp_path,
        monkeypatch,
        {"permissions": {"allow": ["Shell(yoke *)"], "deny": ["Shell(git push*)"]}},
    )

    result = _run(mod.hc_cursor_approval_posture, tmp_path, monkeypatch)

    assert result.result == "WARN"
    assert "permissions.deny carries 1 entry(s)" in result.detail
