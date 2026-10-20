"""Packaged install bundles attribute their receipt to the installed build."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.project_contract.installed_layer import (
    INSTALLED_LAYER_RECEIPT_REL,
)
from yoke_core.domain import install_bundle as bundle_sources
from yoke_core.domain import install_bundle_managed
from yoke_core.domain import install_bundle_project
from yoke_core.domain import project_policy_capabilities

RELEASE_SHA = "0123456789abcdef0123456789abcdef01234567"


class _Connection:
    def commit(self) -> None:
        pass


def _wheel_provenance(sha: str, kind: str = "installed_wheel"):
    return lambda: {"source_sha": sha, "install_kind": kind, "install_path": "/x"}


@pytest.fixture
def packaged_root(tmp_path, monkeypatch):
    """A packaged tree root standing in for ``yoke_core.install_bundle_tree``."""
    root = tmp_path / "install_bundle_tree"
    root.mkdir()
    monkeypatch.setattr(bundle_sources, "packaged_tree_root", lambda: root)
    monkeypatch.setattr(
        install_bundle_project.subprocess,
        "run",
        lambda *a, **k: pytest.fail("packaged roots must not spawn git"),
    )
    return root


def _receipt(monkeypatch, root) -> dict:
    """Render the real project bundle from ``root`` and read its receipt."""
    monkeypatch.setattr(
        install_bundle_project,
        "_project_row",
        lambda project_id, conn: ("sample", "Sample", "main"),
    )
    monkeypatch.setattr(install_bundle_project, "_contract_files", lambda name: [])
    monkeypatch.setattr(
        install_bundle_project, "_strategy_files", lambda pid, name, conn: []
    )
    monkeypatch.setattr(
        project_policy_capabilities,
        "ensure_default_policy_capabilities",
        lambda conn, project_id: {},
    )
    monkeypatch.setattr(bundle_sources, "server_tree_root", lambda: root)
    for name in ("_skill_files", "_agent_files", "_rules_files"):
        monkeypatch.setattr(bundle_sources, name, lambda root: [])
    monkeypatch.setattr(bundle_sources, "_hooks_block", lambda: {})
    monkeypatch.setattr(bundle_sources, "yoke_version", lambda: "0.2.0")
    monkeypatch.setattr(install_bundle_managed, "docs_bundle_files", lambda r: [])
    monkeypatch.setattr(install_bundle_managed, "managed_bundle_keys", lambda r: {})
    monkeypatch.setattr(
        "yoke_core.domain.install_bundle_sources.harness_manifest_files",
        lambda root: [],
    )
    bundle = install_bundle_project.build_project_bundle(7, _Connection())
    entry = next(e for e in bundle["files"] if e["path"] == INSTALLED_LAYER_RECEIPT_REL)
    return json.loads(entry["content"])


def test_packaged_bundle_receipt_carries_the_installed_build(
    packaged_root, monkeypatch
) -> None:
    monkeypatch.setattr(
        install_bundle_project,
        "collect_execution_provenance",
        _wheel_provenance(RELEASE_SHA),
    )

    assert _receipt(monkeypatch, packaged_root) == {
        "schema": 1,
        "source_engine_release": "0.2.0",
        "source_build": RELEASE_SHA,
    }


@pytest.mark.parametrize(
    "sha,kind",
    [
        ("unknown", "installed_wheel"),
        (RELEASE_SHA[:12], "installed_wheel"),
        (RELEASE_SHA.upper(), "installed_wheel"),
        ("0.2.0.202610192204", "installed_wheel"),
        (RELEASE_SHA, "uv_tool"),
        (RELEASE_SHA, "unknown"),
    ],
)
def test_packaged_bundle_claims_no_build_without_full_wheel_provenance(
    packaged_root, monkeypatch, sha, kind
) -> None:
    monkeypatch.setattr(
        install_bundle_project,
        "collect_execution_provenance",
        _wheel_provenance(sha, kind),
    )

    receipt = _receipt(monkeypatch, packaged_root)

    assert receipt == {"schema": 1, "source_engine_release": "0.2.0"}


def test_custom_tree_override_never_borrows_the_loaded_build(
    packaged_root, tmp_path, monkeypatch
) -> None:
    override = tmp_path / "custom-tree"
    override.mkdir()
    monkeypatch.setattr(
        install_bundle_project,
        "collect_execution_provenance",
        _wheel_provenance(RELEASE_SHA),
    )

    assert install_bundle_project.bundle_source_build(override) == ""
    assert _receipt(monkeypatch, override) == {
        "schema": 1,
        "source_engine_release": "0.2.0",
    }


def test_missing_packaged_tree_claims_no_build(tmp_path, monkeypatch) -> None:
    def missing():
        raise bundle_sources.InstallBundleError("packaged tree is missing")

    monkeypatch.setattr(bundle_sources, "packaged_tree_root", missing)
    monkeypatch.setattr(
        install_bundle_project,
        "collect_execution_provenance",
        _wheel_provenance(RELEASE_SHA),
    )

    assert install_bundle_project.bundle_source_build(tmp_path) == ""


def test_source_checkout_keeps_git_attribution(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        install_bundle_project, "is_yoke_source_checkout", lambda root: True
    )
    monkeypatch.setattr(
        install_bundle_project,
        "proven_source_build",
        lambda root, require_clean=False: "f" * 40,
    )
    monkeypatch.setattr(
        install_bundle_project,
        "collect_execution_provenance",
        lambda: pytest.fail("a checkout proves its own HEAD"),
    )

    assert install_bundle_project.bundle_source_build(tmp_path) == "f" * 40
