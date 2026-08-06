"""Tests for the external-capable project hook-config Doctor check."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.engines import doctor_hc_project_hook_config as check
from yoke_core.engines.doctor_applicability_declarations import applicability_for
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_CLAUDE = {
    "hooks": {
        "Stop": [{
            "hooks": [{"type": "command", "command": "echo stopped"}],
        }],
    },
}
_CURSOR = {
    "version": 1,
    "hooks": {
        "stop": [{"command": "echo stopped", "timeout": 5}],
    },
}


def _seed(root: Path) -> None:
    claude = root / ".claude/settings.json"
    cursor = root / ".cursor/hooks.json"
    claude.parent.mkdir(parents=True)
    cursor.parent.mkdir(parents=True)
    claude.write_text(json.dumps(_CLAUDE), encoding="utf-8")
    cursor.write_text(json.dumps(_CURSOR), encoding="utf-8")


def _run(root: Path | None, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        check,
        "resolve_context",
        lambda _conn, _args: SimpleNamespace(source_checkout=root),
    )
    records = RecordCollector()
    check.hc_project_hook_config_validity(
        None, DoctorArgs(project="external"), records,
    )
    assert len(records.results) == 1
    return records.results[0]


def test_valid_external_project_configs_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed(tmp_path)

    result = _run(tmp_path, monkeypatch)

    assert result.result == "PASS"


@pytest.mark.parametrize(
    ("parent_rel", "config_rel"),
    [
        (Path(".claude"), Path(".claude/settings.json")),
        (Path(".cursor"), Path(".cursor/hooks.json")),
    ],
)
def test_symlinked_config_parent_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_rel: Path,
    config_rel: Path,
) -> None:
    _seed(tmp_path)
    parent = tmp_path / parent_rel
    real_parent = tmp_path / f"{parent_rel.name}-real"
    parent.rename(real_parent)
    parent.symlink_to(real_parent.name, target_is_directory=True)

    result = _run(tmp_path, monkeypatch)

    assert result.result == "FAIL"
    assert f"{config_rel} crosses symlink component {parent_rel}" in result.detail


@pytest.mark.parametrize(
    "config_rel",
    [Path(".claude/settings.json"), Path(".cursor/hooks.json")],
)
def test_symlinked_config_leaf_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_rel: Path,
) -> None:
    _seed(tmp_path)
    config = tmp_path / config_rel
    real_config = config.with_name(f"{config.name}.real")
    config.rename(real_config)
    config.symlink_to(real_config.name)

    result = _run(tmp_path, monkeypatch)

    assert result.result == "FAIL"
    assert f"{config_rel} crosses symlink component {config_rel}" in result.detail


@pytest.mark.parametrize(
    "config_rel",
    [Path(".claude/settings.json"), Path(".cursor/hooks.json")],
)
def test_non_regular_config_leaf_fails_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_rel: Path,
) -> None:
    _seed(tmp_path)
    config = tmp_path / config_rel
    config.unlink()
    config.mkdir()

    result = _run(tmp_path, monkeypatch)

    assert result.result == "FAIL"
    assert f"{config_rel} is not a regular file" in result.detail


@pytest.mark.parametrize(
    "config_rel",
    [Path(".claude/settings.json"), Path(".cursor/hooks.json")],
)
def test_malformed_json_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_rel: Path,
) -> None:
    _seed(tmp_path)
    (tmp_path / config_rel).write_text("{not json", encoding="utf-8")

    result = _run(tmp_path, monkeypatch)

    assert result.result == "FAIL"
    assert f"{config_rel} is not valid JSON" in result.detail


@pytest.mark.parametrize(
    ("config_rel", "raw"),
    [
        (Path(".claude/settings.json"), "[]"),
        (Path(".claude/settings.json"), "null"),
        (Path(".cursor/hooks.json"), "[]"),
        (Path(".cursor/hooks.json"), "null"),
    ],
)
def test_non_object_top_level_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_rel: Path,
    raw: str,
) -> None:
    _seed(tmp_path)
    (tmp_path / config_rel).write_text(raw, encoding="utf-8")

    result = _run(tmp_path, monkeypatch)

    assert result.result == "FAIL"
    assert f"{config_rel} top level must be a JSON object" in result.detail


@pytest.mark.parametrize("version", [None, 0, True, 1.0, "1"])
def test_cursor_requires_integer_schema_version_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version,
) -> None:
    _seed(tmp_path)
    payload = {**_CURSOR, "version": version}
    (tmp_path / ".cursor/hooks.json").write_text(
        json.dumps(payload), encoding="utf-8",
    )

    result = _run(tmp_path, monkeypatch)

    assert result.result == "FAIL"
    assert "must declare schema version 1" in result.detail


@pytest.mark.parametrize(
    ("config_rel", "payload", "message"),
    [
        (
            Path(".claude/settings.json"),
            {"hooks": {"Stop": [{"hooks": [{"command": "echo bad"}]}]}},
            "invalid command hook",
        ),
        (
            Path(".cursor/hooks.json"),
            {"version": 1, "hooks": {"stop": [{"timeout": 5}]}},
            "invalid Cursor hook entry",
        ),
    ],
)
def test_invalid_hook_entry_schema_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_rel: Path,
    payload: dict,
    message: str,
) -> None:
    _seed(tmp_path)
    (tmp_path / config_rel).write_text(json.dumps(payload), encoding="utf-8")

    result = _run(tmp_path, monkeypatch)

    assert result.result == "FAIL"
    assert message in result.detail


def test_missing_source_checkout_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run(None, monkeypatch)

    assert result.result == "FAIL"
    assert "source checkout is unavailable" in result.detail


def test_check_is_global_source_checkout_shape() -> None:
    declaration = applicability_for("project-hook-config-validity")

    assert declaration.requires_source_checkout is True
    assert declaration.project_scope == "any"
