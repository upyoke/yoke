"""Tracked operating-layer provenance in project install bundles."""

from __future__ import annotations

import json

from yoke_contracts.project_contract.install_manifest import INSTALL_MANIFEST_REL
from yoke_contracts.project_contract.installed_layer import (
    INSTALLED_LAYER_RECEIPT_REL,
    installed_layer_receipt_entry,
    read_installed_layer_receipt,
)
from yoke_core.domain import install_bundle as bundle_sources
from yoke_core.domain import install_bundle_managed
from yoke_core.domain import install_bundle_project
from yoke_core.domain import project_policy_capabilities


class _Connection:
    def commit(self) -> None:
        pass


def test_receipt_reader_finds_the_checkout_from_a_nested_path(tmp_path) -> None:
    project = tmp_path / "project"
    nested = project / "src" / "feature"
    nested.mkdir(parents=True)
    entry = installed_layer_receipt_entry("0.1.1+launch.44")
    receipt_path = project / entry["path"]
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(entry["content"], encoding="utf-8")

    receipt = read_installed_layer_receipt(nested)

    assert receipt is not None
    assert receipt.project_root == project
    assert receipt.source_engine_release == "0.1.1+launch.44"


def test_receipt_reader_retains_source_build_identity(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    entry = installed_layer_receipt_entry(
        "source-content-digest",
        source_build="abc123",
    )
    (project / entry["path"]).write_text(entry["content"], encoding="utf-8")

    receipt = read_installed_layer_receipt(project)

    assert receipt is not None
    assert receipt.source_engine_release == "source-content-digest"
    assert receipt.source_build == "abc123"


def test_legacy_install_manifest_supplies_pre_receipt_provenance(tmp_path) -> None:
    project = tmp_path / "legacy-project"
    nested = project / "src"
    nested.mkdir(parents=True)
    manifest = project / INSTALL_MANIFEST_REL
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"yoke_version": "0.1.1+launch.43"}),
        encoding="utf-8",
    )

    receipt = read_installed_layer_receipt(nested)

    assert receipt is not None
    assert receipt.project_root == project
    assert receipt.source_engine_release == "0.1.1+launch.43"


def test_reader_stops_at_nearest_managed_project_boundary(tmp_path) -> None:
    outer = tmp_path / "outer"
    outer.mkdir()
    entry = installed_layer_receipt_entry("0.1.1+launch.44")
    (outer / entry["path"]).write_text(entry["content"], encoding="utf-8")
    inner = outer / "inner"
    nested = inner / "src"
    nested.mkdir(parents=True)
    (inner / ".yoke").mkdir()

    assert read_installed_layer_receipt(nested) is None


def test_receipt_reader_ignores_malformed_or_missing_receipts(tmp_path) -> None:
    project = tmp_path / "project"
    receipt_path = project / INSTALLED_LAYER_RECEIPT_REL
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text('{"schema":1}\n', encoding="utf-8")

    assert read_installed_layer_receipt(project) is None
    assert read_installed_layer_receipt(tmp_path / "absent") is None


def test_project_bundle_receipt_matches_top_level_engine_release(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        install_bundle_project,
        "_project_row",
        lambda project_id, conn: ("sample", "Sample"),
    )
    monkeypatch.setattr(install_bundle_project, "_contract_files", lambda name: [])
    monkeypatch.setattr(
        install_bundle_project,
        "_strategy_files",
        lambda project_id, name, conn: [],
    )
    monkeypatch.setattr(
        project_policy_capabilities,
        "ensure_default_policy_capabilities",
        lambda conn, project_id: {},
    )
    monkeypatch.setattr(bundle_sources, "server_tree_root", lambda: tmp_path)
    monkeypatch.setattr(bundle_sources, "_skill_files", lambda root: [])
    monkeypatch.setattr(bundle_sources, "_agent_files", lambda root: [])
    monkeypatch.setattr(bundle_sources, "_rules_files", lambda root: [])
    monkeypatch.setattr(bundle_sources, "_hooks_block", lambda: {})
    monkeypatch.setattr(
        bundle_sources, "yoke_version", lambda: "0.1.1+launch.45"
    )
    monkeypatch.setattr(install_bundle_managed, "docs_bundle_files", lambda root: [])
    monkeypatch.setattr(
        install_bundle_managed, "managed_bundle_keys", lambda root: {}
    )

    bundle = install_bundle_project.build_project_bundle(7, _Connection())

    assert bundle["yoke_version"] == "0.1.1+launch.45"
    receipt_entry = next(
        entry
        for entry in bundle["files"]
        if entry["path"] == INSTALLED_LAYER_RECEIPT_REL
    )
    receipt = json.loads(receipt_entry["content"])
    assert receipt == {
        "schema": 1,
        "source_engine_release": bundle["yoke_version"],
    }
