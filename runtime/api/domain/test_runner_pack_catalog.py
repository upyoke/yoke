"""Catalog and render contracts for the reusable runner-fleet Pack."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain import pack_catalog


ROOT = Path(__file__).resolve().parents[3]


def test_runner_fleet_patch_keeps_the_published_pack_contract_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: ROOT)

    descriptor = pack_catalog.load_pack_descriptor("self-hosted-runners")
    previous = descriptor["versions"]["1.3.0"]
    latest = descriptor["versions"]["1.3.2"]

    assert latest["source"] == "versions/1.3.2/files"
    stable_keys = (
        "documentation",
        "dependencies",
        "settings_schema",
        "files",
        "verification",
    )
    for key in stable_keys:
        assert latest[key] == previous[key]


def test_runner_fleet_latest_renders_its_smoke_workflow_and_no_stack_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pack_catalog,
        "resolve_project",
        lambda *args, **kwargs: SimpleNamespace(id=9, slug="sample"),
    )
    render_values = {
        "runner_fleet_architecture": "arm64",
        "runner_fleet_labels_json": '["self-hosted","linux","arm64"]',
        "runner_fleet_variable_name": "YOKE_RUNNER_LABELS",
    }

    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: ROOT)
    canonical = pack_catalog.build_pack_bundle(
        object(),
        project="sample",
        pack="self-hosted-runners",
        render_values=render_values,
    )
    assert canonical["version"] == "3.0.0"
    assert canonical["superseded_by"] == ""
    files = {row["path"]: row for row in canonical["files"]}
    assert not [path for path in files if path.endswith(".yaml.tmpl")]
    smoke = files[".github/workflows/runner-fleet-smoke.yml"]["content"]
    assert 'runs-on: ["self-hosted","linux","arm64"]' in smoke
    assert "vars.YOKE_RUNNER_LABELS" in smoke
    assert "{{runner_fleet_" not in smoke
    stack_config = files["infra/webapp_runner_fleet_stack_config.py"]["content"]
    assert 'pulumi.Config("yoke")' in stack_config
    assert 'project=text("project")' in stack_config


def test_runner_fleet_template_versions_name_their_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: ROOT)

    descriptor = pack_catalog.load_pack_descriptor("self-hosted-runners")
    for version, record in descriptor["versions"].items():
        ships_template = any(
            row["source"].endswith(".yaml.tmpl") for row in record["files"]
        )
        assert record.get("superseded_by") == ("3.0.0" if ships_template else None)
