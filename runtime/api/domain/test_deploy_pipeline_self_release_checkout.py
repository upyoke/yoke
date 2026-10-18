"""Locating a self-release checkout without the installed config schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import deploy_pipeline_pinned_source as pinned
from yoke_core.domain.deploy_pipeline_pinned_source import DeployPinnedSourceError


def _yoke_checkout(root: Path) -> Path:
    (root / "packages" / "yoke-core" / "src" / "yoke_core").mkdir(parents=True)
    return root


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, projects) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"active_env": "local", "connection_projects": {"local": projects}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        pinned.machine_config, "load_config", lambda: json.loads(path.read_text())
    )
    monkeypatch.setattr(pinned, "project_id_for_slug", lambda _p: 1)


def test_entry_shape_the_installed_rules_reject_still_locates_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Keys the installed contract does not know (or no longer allows) must not
    # stop the release that changes the contract from locating its own source.
    yoke = _yoke_checkout(tmp_path / "yoke")
    _config(
        tmp_path,
        monkeypatch,
        [
            {"checkout": str(yoke), "project_id": 1, "env": "prod-db-admin"},
            {"checkout": str(yoke), "project_id": 1, "future_key": {"x": 1}},
        ],
    )
    assert pinned.self_release_checkout("yoke") == yoke.resolve()


def test_non_yoke_checkout_drives_with_the_installed_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    _config(tmp_path, monkeypatch, [{"checkout": str(other), "project_id": 1}])
    assert pinned.self_release_checkout("other") is None


def test_unmapped_project_names_the_registration_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _config(tmp_path, monkeypatch, [{"checkout": "/elsewhere", "project_id": 2}])
    assert pinned.self_release_checkout("yoke") is None
    assert "yoke project register" in capsys.readouterr().err


def test_unresolvable_project_refuses_with_redrive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pinned, "project_id_for_slug", lambda _p: None)
    with pytest.raises(DeployPinnedSourceError, match="re-drive"):
        pinned.self_release_checkout("ghost")


def test_https_run_of_a_yoke_project_is_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The stage release runs over HTTPS; it must still execute the release
    # commit so its fleet rehearsal runs the migrations the release ships.
    yoke = _yoke_checkout(tmp_path / "yoke")
    monkeypatch.setattr(
        pinned.control_plane,
        "run_pin",
        lambda _r: {"release_lineage": "abc", "project": "yoke"},
    )
    monkeypatch.setattr(pinned, "self_release_checkout", lambda _p: yoke)
    monkeypatch.setattr(pinned, "retire_finished_driver_worktrees", lambda *_a: None)
    monkeypatch.setattr(
        pinned, "ensure_pinned_worktree", lambda _c, _r, _l: tmp_path / "pin"
    )
    monkeypatch.setattr(pinned, "_ensure_commit", lambda _c, _l: "a" * 40)
    prepared = pinned.prepare_self_deploy_driver("run-1")
    assert prepared == pinned.PinnedDriverSource(
        root=tmp_path / "pin", lineage="a" * 40
    )
