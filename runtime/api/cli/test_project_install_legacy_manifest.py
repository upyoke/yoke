"""Compatibility and safety for legacy project-install manifest records."""

from __future__ import annotations

import json

import pytest

from yoke_cli.project_install import files as project_install_files
from yoke_cli.project_install.bundle_apply import apply_bundle
from yoke_core.domain.project_install_test_helpers import make_bundle


def _manifest(*, strategy_files: dict[str, str] | None = None) -> dict:
    return {
        "manifest_schema": 1,
        "files": {},
        "contract_files": {},
        "strategy_files": strategy_files or {},
        "git_hook_hashes": {},
        "created_settings_files": [],
        "hook_entries": {},
    }


def test_refresh_discards_noncanonical_prior_strategy_record(tmp_path) -> None:
    repo = tmp_path / "external-project"
    repo.mkdir()
    manifest_path = project_install_files.write_manifest(repo, _manifest())
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    inert_path = ".retired/strategy/MISSION.md"
    manifest["strategy_files"][inert_path] = "2" * 64
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    inert_file = repo / inert_path
    inert_file.parent.mkdir(parents=True)
    inert_file.write_text("project-owned\n", encoding="utf-8")

    report = apply_bundle(repo, make_bundle(), operation="refresh")

    assert report["prior_strategy_records_discarded"] == [inert_path]
    assert inert_file.read_text(encoding="utf-8") == "project-owned\n"
    refreshed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert inert_path not in refreshed["strategy_files"]
    assert "_discarded_prior_strategy_records" not in refreshed


def test_new_manifest_write_keeps_strategy_paths_strict(tmp_path) -> None:
    repo = tmp_path / "external-project"
    repo.mkdir()
    unsafe = _manifest(
        strategy_files={".legacy/strategy/MISSION.md": "3" * 64}
    )

    with pytest.raises(
        project_install_files.ProjectInstallError,
        match="unsafe strategy path",
    ):
        project_install_files.write_manifest(repo, unsafe)
