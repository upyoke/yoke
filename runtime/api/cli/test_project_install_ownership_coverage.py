"""Every digest-tracked install destination has positive ownership evidence."""

import pytest

from runtime.api.cli.project_install_recovery_test_support import _commit, _file, _git
from yoke_cli.project_install import checkout_gate, install_recovery as recovery
from yoke_cli.project_install import (
    instruction_discovery,
    released_bundle_files as released,
)
from yoke_cli.project_install.bundle_apply import apply_bundle
from yoke_cli.project_install.files import ProjectInstallError, sha256_text
from yoke_contracts.project_contract.installed_layer import INSTALLED_LAYER_RECEIPT_REL
from yoke_core.domain.project_install_test_helpers import make_bundle


PATHS = (
    INSTALLED_LAYER_RECEIPT_REL,
    ".claude/rules/yoke.md",
    ".yoke/harness/claude/manifest.json",
    ".yoke/harness/codex/manifest.json",
    ".yoke/harness/cursor/manifest.json",
)


@pytest.mark.parametrize("rel", PATHS)
@pytest.mark.parametrize("operation", ["install", "refresh"])
@pytest.mark.parametrize("writer", ["installer", "local-edit", "other-commit"])
def test_pulled_installer_outputs_with_older_local_manifest(
    tmp_path, monkeypatch, rel, operation, writer
):
    """Checkout B keeps its old ignored manifest while pulling A's refresh."""
    monkeypatch.setattr(instruction_discovery.shutil, "which", lambda _: None)
    monkeypatch.setattr(released.ReleasedBundleFiles, "proves", lambda *a: False)
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    _git(first, "init", "-b", "main")
    _git(first, "config", "core.hooksPath", "/dev/null")
    _file(
        first, ".gitignore", ".yoke/install-manifest.json\n.yoke/install-pending.json\n"
    )
    old = make_bundle()
    old["files"] = [*old["files"], dict(path=rel, content="old release\n")]
    apply_bundle(first, old)
    _commit(first, "Install Yoke operating layer 1.0.0")
    _git(tmp_path, "clone", str(first), str(second))
    _git(second, "config", "core.hooksPath", "/dev/null")
    manifest = (first / ".yoke/install-manifest.json").read_bytes()
    (second / ".yoke/install-manifest.json").write_bytes(manifest)
    pulled = "another checkout's release\n"
    _file(first, rel, pulled)
    _commit(first, "Refresh installed Yoke operating layer to 1.0.1")
    _git(second, "pull", "--ff-only")
    assert not checkout_gate.porcelain(second)
    if writer == "local-edit":
        _file(second, rel, "local edit\n")
    elif writer == "other-commit":
        _file(second, rel, "user committed edit\n")
        _commit(second, "Edit project guidance")
    incoming = dict(
        old,
        files=[
            dict(e, content="next release\n") if e["path"] == rel else e
            for e in old["files"]
        ],
    )
    if writer != "installer":
        before = (second / rel).read_bytes()
        with pytest.raises(ProjectInstallError, match="install_drift_local_edits"):
            apply_bundle(second, incoming, operation=operation)
        assert (second / rel).read_bytes() == before
        assert not recovery.pending(second)
    else:
        report = apply_bundle(second, incoming, operation=operation)
        assert rel in report["install_drift"]["changed"]
        assert (second / rel).read_text() == "next release\n"


def test_built_bundle_has_history_and_source_proof_for_every_file(
    tmp_path, monkeypatch
):
    from yoke_core.domain import install_bundle, install_bundle_project as project
    from yoke_core.domain import project_policy_capabilities

    # Only project/database metadata is stubbed: all bundle files are real sources.
    monkeypatch.setattr(
        project, "_project_row", lambda *a: ("example", "Example", "main")
    )
    monkeypatch.setattr(project, "_contract_files", lambda *a: [])
    monkeypatch.setattr(project, "_strategy_files", lambda *a: [])
    monkeypatch.setattr(
        project_policy_capabilities, "ensure_default_policy_capabilities", lambda *a: {}
    )

    class Connection:
        def commit(self):
            pass

    bundle = project.build_project_bundle(1, Connection())
    root = install_bundle.server_tree_root()
    expected = set()
    for entry in bundle["files"]:
        rel = entry["path"]
        expected.add(rel)
        _file(tmp_path, rel, entry["content"])
        source = released._source_path(rel)
        if rel == INSTALLED_LAYER_RECEIPT_REL:
            assert source is None
        else:
            assert source is not None, rel
            assert (root / source).read_bytes() == entry["content"].encode(), rel
    _git(tmp_path, "init")
    _commit(tmp_path, "Refresh installed Yoke operating layer to 1.0.1")
    proof = recovery.GitOwnership(tmp_path)
    assert set(proof.writers) == expected


@pytest.mark.parametrize("rel", PATHS[1:])
def test_release_catalogue_proves_rules_and_harness_views(monkeypatch, rel):
    content = "released content\n"
    source = (
        "runtime/harness/claude/rules/yoke.md"
        if rel.startswith(".claude/")
        else rel.replace(".yoke/", "runtime/", 1)
    )
    monkeypatch.setattr(released, "source_checkout_root", lambda _: None)
    monkeypatch.setattr(
        released, "_catalogue", lambda: {source: [sha256_text(content)]}
    )
    proof = released.ReleasedBundleFiles()
    assert proof.proves(rel, content)
    assert not proof.proves(rel, "local edit\n")
