"""Tracked operating-layer provenance in project install bundles."""

from __future__ import annotations

import json
import subprocess

import pytest

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
from yoke_core.domain.install_bundle_sources import HARNESS_MANIFEST_SOURCES


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
        source_build="a" * 40,
    )
    (project / entry["path"]).write_text(entry["content"], encoding="utf-8")

    receipt = read_installed_layer_receipt(project)

    assert receipt is not None
    assert receipt.source_engine_release == "source-content-digest"
    assert receipt.source_build == "a" * 40


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
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        install_bundle_project,
        "_project_row",
        lambda project_id, conn: ("sample", "Sample", "main"),
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
    monkeypatch.setattr(bundle_sources, "yoke_version", lambda: "0.1.1+launch.45")
    monkeypatch.setattr(install_bundle_managed, "docs_bundle_files", lambda root: [])
    monkeypatch.setattr(install_bundle_managed, "managed_bundle_keys", lambda root: {})

    for rel in HARNESS_MANIFEST_SOURCES:
        source = tmp_path / rel
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("{}\n")
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


@pytest.mark.parametrize("build", ["abc123", "A" * 40, "g" * 40, "a" * 41, " " + "a" * 40])
def test_receipt_refuses_malformed_source_build(tmp_path, build) -> None:
    with pytest.raises(ValueError, match="Rebuild from the declared full candidate commit"):
        installed_layer_receipt_entry("source-content", source_build=build)
    (tmp_path / INSTALLED_LAYER_RECEIPT_REL).write_text(json.dumps({
        "schema": 1, "source_engine_release": "source-content", "source_build": build,
    }))
    assert read_installed_layer_receipt(tmp_path) is None


@pytest.mark.parametrize("build", [None, ""])
def test_receipt_accepts_missing_or_empty_source_build(tmp_path, build) -> None:
    payload = {"schema": 1, "source_engine_release": "released"}
    if build is not None:
        payload["source_build"] = build
    (tmp_path / INSTALLED_LAYER_RECEIPT_REL).write_text(json.dumps(payload))
    assert read_installed_layer_receipt(tmp_path).source_build == ""


def _committed_checkout(root):
    (root / "runtime/harness").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "yoke"\n')
    (root / "AGENTS.md").write_text("teaching\n")
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(root), *args], check=True,
            capture_output=True, text=True,
        ).stdout.strip()
    git("init", "-q")
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.com",
        "-c", "core.hooksPath=/dev/null", "commit", "-qm", "Initial source")
    return git("rev-parse", "HEAD")


def test_proven_source_build_preserves_dirty_checkout_head(tmp_path) -> None:
    head = _committed_checkout(tmp_path)
    assert install_bundle_project.proven_source_build(tmp_path, require_clean=True) == head
    (tmp_path / "AGENTS.md").write_text("changed teaching\n")
    assert install_bundle_project.proven_source_build(tmp_path) == head
    with pytest.raises(install_bundle_project.CandidateIdentityError) as error:
        install_bundle_project.proven_source_build(tmp_path, require_clean=True)
    assert error.value.paths == ("AGENTS.md",)
    assert "CANDIDATE_TREE_DIRTY AGENTS.md" in str(error.value)
    assert "commit or discard" in str(error.value)


def test_proven_source_build_does_not_run_git_for_packaged_root(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("packaged roots must not spawn git")
    monkeypatch.setattr(install_bundle_project.subprocess, "run", unexpected)
    assert install_bundle_project.proven_source_build(tmp_path) == ""
    assert install_bundle_project.proven_source_build(tmp_path, require_clean=True) == ""


def test_proven_source_build_returns_empty_for_uncommitted_source(tmp_path):
    (tmp_path / "runtime/harness").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "yoke"\n')
    assert install_bundle_project.proven_source_build(tmp_path) == ""


@pytest.mark.parametrize("resolved,exists", [("abc123", 0), ("A" * 40, 0), ("a" * 40, 1)])
def test_proven_source_build_requires_a_resolvable_full_commit(
    tmp_path, monkeypatch, resolved, exists,
):
    monkeypatch.setattr(install_bundle_project, "is_yoke_source_checkout", lambda root: True)

    def run(args, **kwargs):
        if args[3] == "rev-parse":
            return subprocess.CompletedProcess(args, 0, resolved + "\n", "")
        assert args[3:] == ["cat-file", "-e", f"{resolved}^{{commit}}"]
        return subprocess.CompletedProcess(args, exists, "", "")

    monkeypatch.setattr(install_bundle_project.subprocess, "run", run)
    assert install_bundle_project.proven_source_build(tmp_path) == ""
