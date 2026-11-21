"""Machine updates refresh the current installed project with the new CLI."""

import json
from types import SimpleNamespace

import pytest

from yoke_cli.config import project_update, self_update
from yoke_contracts.project_contract.install_error import ProjectInstallError


def test_update_outside_installed_project_does_not_refresh(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert project_update.refresh_current("/bin/yoke") == {"status": "not_installed"}


def test_update_refreshes_current_checkout_and_surfaces_failure(tmp_path, monkeypatch):
    folder = tmp_path / ".yoke"
    folder.mkdir()
    (folder / "install-manifest.json").write_text(
        json.dumps({"manifest_schema": 1, "mode": "copy", "files": {}})
    )
    nested = tmp_path / "src"
    nested.mkdir()
    monkeypatch.chdir(nested)
    calls = []

    def completed(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {"yoke_version": "1.0.0", "install_drift": {"missing": ["skill"]}}
            ),
            stderr="",
        )

    monkeypatch.setattr(project_update.subprocess, "run", completed)
    assert project_update.refresh_current("/updated/yoke")["status"] == "refreshed"
    assert calls == [["/updated/yoke", "project", "refresh", str(tmp_path), "--json"]]
    monkeypatch.setattr(
        project_update.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=1, stdout="", stderr="install_drift_local_edits: save edits"
        ),
    )
    with pytest.raises(
        ProjectInstallError,
        match="project_update_incomplete.*install_drift_local_edits",
    ):
        project_update.refresh_current("/updated/yoke")


def test_already_current_update_still_runs_project_refresh(monkeypatch):
    target = SimpleNamespace(
        version="1.0.0", channel="stable", base_url="https://example.test"
    )
    monkeypatch.setattr(
        self_update.install_binding,
        "require_packaged_install",
        lambda _: {"version": "1.0.0"},
    )
    monkeypatch.setattr(self_update.shutil, "which", lambda _: "/updated/yoke")
    monkeypatch.setattr(
        self_update.distribution,
        "recorded",
        lambda: {"channel": "stable", "origin": target.base_url},
    )
    monkeypatch.setattr(
        self_update.release_target, "channel_release_target", lambda **_: target
    )
    monkeypatch.setattr(
        self_update.github_repo_helper_reconnect, "restore_missing_bundle", lambda _: {}
    )
    calls = []
    monkeypatch.setattr(
        project_update,
        "refresh_current",
        lambda exe: calls.append(exe) or {"status": "refreshed"},
    )
    assert self_update.run_update()["already_current"]
    assert calls == ["/updated/yoke"]
