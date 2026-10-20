"""The runtime image's packaged server tree must render an attributed bundle."""

import json
from pathlib import Path

import pytest

from yoke_contracts.project_contract.installed_layer import (
    INSTALLED_LAYER_RECEIPT_REL,
)
from yoke_core.domain import install_bundle, install_bundle_project
from yoke_core.domain.install_bundle_sources import HARNESS_MANIFEST_SOURCES
from yoke_core.domain.install_bundle_sources import InstallBundleTreeError
from yoke_core.tools.container_bundle_validation import (
    ContainerBundleError,
    verify_project_bundle,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGED = ROOT / "packages/yoke-core/src/yoke_core/install_bundle_tree"
BUILD = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def image_tree(tmp_path, monkeypatch):
    """Serve a copy of the packaged tree as an installed wheel would."""
    import shutil

    root = tmp_path / "install_bundle_tree"
    shutil.copytree(PACKAGED, root)
    monkeypatch.delenv("YOKE_SERVER_TREE_ROOT", raising=False)
    monkeypatch.setattr(install_bundle, "source_checkout_root", lambda f: None)
    monkeypatch.setattr(install_bundle, "packaged_tree_root", lambda: root)
    return root


def _wheel_build(monkeypatch, sha: str) -> None:
    monkeypatch.setattr(
        install_bundle_project,
        "collect_execution_provenance",
        lambda: {"source_sha": sha, "install_kind": "installed_wheel"},
    )


def _receipt(bundle: dict) -> dict:
    entry = next(e for e in bundle["files"] if e["path"] == INSTALLED_LAYER_RECEIPT_REL)
    return json.loads(entry["content"])


def test_image_bundle_receipt_carries_the_full_build(image_tree, monkeypatch):
    _wheel_build(monkeypatch, BUILD)
    bundle = verify_project_bundle(BUILD)
    assert bundle["project_slug"] == "image-check"
    assert bundle["project_contract_files"]
    assert _receipt(bundle)["source_build"] == BUILD


@pytest.mark.parametrize("build", ["", BUILD[:12]])
def test_image_without_full_build_renders_unattributed(image_tree, monkeypatch, build):
    _wheel_build(monkeypatch, build or "unknown")
    assert "source_build" not in _receipt(verify_project_bundle(build))


def test_image_gate_refuses_a_lost_build(image_tree, monkeypatch):
    _wheel_build(monkeypatch, "unknown")
    with pytest.raises(ContainerBundleError, match="IMAGE_BUNDLE_BUILD_MISMATCH"):
        verify_project_bundle(BUILD)


def test_image_gate_refuses_a_declared_tree_override(image_tree, tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_SERVER_TREE_ROOT", str(tmp_path))
    with pytest.raises(ContainerBundleError, match="IMAGE_SERVER_TREE_NOT_PACKAGED"):
        verify_project_bundle(BUILD)


@pytest.mark.parametrize("relative", HARNESS_MANIFEST_SOURCES)
def test_missing_image_manifest_fails_bundle_gate(image_tree, monkeypatch, relative):
    _wheel_build(monkeypatch, BUILD)
    (image_tree / relative).unlink()
    with pytest.raises(
        InstallBundleTreeError, match="install_bundle_source_unreadable"
    ):
        verify_project_bundle(BUILD)


def test_docker_build_gates_the_installed_packaged_tree():
    dockerfile = (ROOT / "Dockerfile").read_text()
    gate = "RUN python -m yoke_core.tools.container_bundle_validation verify\n"
    assert gate in dockerfile
    assert "stage-source-files" not in dockerfile
    assert dockerfile.index(gate) > dockerfile.index(
        "yoke_core.tools.product_wheel_validation"
    )
