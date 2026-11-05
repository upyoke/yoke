"""Staged release proof protects installer files without a local manifest."""

from __future__ import annotations

import hashlib
import subprocess

import pytest

from yoke_cli.project_install import released_bundle_files
from yoke_harness.git_hooks import installed_files, pre_commit
from runtime.api.tools.released_install_hashes import render


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args], check=True, capture_output=True,
        ).stdout

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    monkeypatch.setattr(released_bundle_files, "source_checkout_root", lambda _: None)
    monkeypatch.setattr(pre_commit, "_resolve_repo_root", lambda: str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path, git


@pytest.mark.parametrize("rel,key", [
    (".yoke/docs/projects/guide.md", "docs/projects/guide.md"),
    (".agents/skills/yoke/dash/SKILL.md", "skills/dash/SKILL.md"),
    (".claude/skills/yoke/dash/SKILL.md", "skills/dash/SKILL.md"),
    (".codex/skills/yoke/dash/SKILL.md", "skills/dash/SKILL.md"),
    (".cursor/skills/yoke/dash/SKILL.md", "skills/dash/SKILL.md"),
    (".claude/agents/yoke-engineer.md", "runtime/harness/claude/agents/yoke-engineer.md"),
    (".codex/agents/yoke-engineer.toml", "runtime/harness/codex/agents/yoke-engineer.toml"),
    (".cursor/agents/yoke-engineer.md", "runtime/harness/cursor/agents/yoke-engineer.md"),
])
def test_staged_proof_accepts_refresh_and_refuses_hand_edit(
    checkout, monkeypatch, capsys, rel, key,
):
    root, git = checkout
    content = "released bytes\n"
    digest = hashlib.sha256(content.encode()).hexdigest()
    monkeypatch.setattr(released_bundle_files, "_catalogue", lambda: {key: [digest]})
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    git("add", "--", rel)
    assert pre_commit.run() == 0
    git("-c", "core.hooksPath=/dev/null", "commit", "-qm", "Refresh installed layer")
    path.write_text("hand edit\n")
    git("add", "--", rel)
    path.write_text(content)  # Working-tree release bytes cannot excuse index edits.
    assert pre_commit.run() == 1
    diagnostic = capsys.readouterr().err
    assert "yoke (pre-commit): ERROR: installer_owned_file_modified" in diagnostic
    assert rel in diagnostic
    assert "This file belongs to Yoke's installer" in diagnostic
    assert "yoke feedback --to yoke" in diagnostic
    assert "project-owned file" in diagnostic
    git("add", "--", rel)
    path.write_text("unstaged hand edit\n")
    assert pre_commit.run() == 0


def test_ordinary_files_and_installer_deletions_pass(checkout):
    root, git = checkout
    (root / "guide.md").write_text("project-owned content\n")
    git("add", "guide.md")
    assert installed_files.check(root) is None
    path = root / ".yoke/docs/old.md"
    path.parent.mkdir(parents=True)
    path.write_text("retired release\n")
    git("add", ".yoke/docs/old.md")
    git("-c", "core.hooksPath=/dev/null", "commit", "-qm", "seed")
    git("rm", ".yoke/docs/old.md")
    assert installed_files.check(root) is None


def test_source_authorship_and_bundle_sync_remain_editable(checkout):
    root, git = checkout
    (root / "pyproject.toml").write_text('name = "yoke"\n')
    (root / "runtime/harness").mkdir(parents=True)
    for rel in (".agents/skills/yoke/dash/SKILL.md", "runtime/harness/codex/agents/yoke-engineer.toml"):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("new source\n")
        git("add", rel)
    assert installed_files.check(root) is None
    path = root / ".yoke/docs/guide.md"
    path.parent.mkdir(parents=True)
    path.write_text("hand edit\n")
    git("add", ".yoke/docs/guide.md")
    assert installed_files.check(root) is None


def test_catalogue_failure_names_recovery(checkout, monkeypatch):
    root, git = checkout
    path = root / ".yoke/docs/guide.md"
    path.parent.mkdir(parents=True)
    path.write_text("release\n")
    git("add", ".yoke/docs/guide.md")
    def unreadable():
        raise released_bundle_files.ProjectInstallError(
            "install_release_catalogue_unreadable: Reinstall the CLI"
        )
    monkeypatch.setattr(released_bundle_files, "_catalogue", unreadable)
    assert "install_release_catalogue_unreadable: Reinstall the CLI" in installed_files.check(root)


def test_catalogue_renders_agents_from_annotated_releases(checkout):
    root, git = checkout
    rel = "runtime/harness/codex/agents/yoke-engineer.toml"
    path = root / rel
    path.parent.mkdir(parents=True)
    path.write_text("released agent\n")
    git("add", rel)
    git("-c", "core.hooksPath=/dev/null", "commit", "-qm", "release")
    git("tag", "-a", "v1.0.0", "-m", "release")
    path.write_text("unreleased agent\n")
    catalogue = render(root)
    assert catalogue[rel] == [hashlib.sha256(b"released agent\n").hexdigest()]


@pytest.mark.parametrize("harness", ["agents", "claude", "codex", "cursor"])
def test_running_bundle_proves_exact_bytes_without_catalogue_or_source(
    checkout, monkeypatch, tmp_path, harness,
):
    monkeypatch.setattr(released_bundle_files, "_catalogue", lambda: {})
    bundle = tmp_path / "bundle"
    path = bundle / ".agents/skills/yoke/dash/merge.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"running release\n")
    monkeypatch.setattr(released_bundle_files, "files", lambda _: bundle)
    proof = released_bundle_files.ReleasedBundleFiles()
    assert proof.root is None
    rel = f".{harness}/skills/yoke/dash/merge.md"
    assert proof.proves(rel, "running release\n")
    assert not proof.proves(rel, "edited release\n")


@pytest.mark.parametrize("error", [OSError, ModuleNotFoundError, TypeError])
def test_running_bundle_lookup_failure_refuses(checkout, monkeypatch, error):
    monkeypatch.setattr(released_bundle_files, "_catalogue", lambda: {})
    def unavailable(_):
        raise error("bundle unavailable")
    monkeypatch.setattr(released_bundle_files, "files", unavailable)
    assert not released_bundle_files.ReleasedBundleFiles().proves(
        ".agents/skills/yoke/dash/merge.md", "release\n",
    )


@pytest.mark.parametrize("tag", ["v1.0.0", "0.2.0.202611041824"])
def test_current_annotated_tags_prove_releases_and_skip_lightweight(
    checkout, monkeypatch, tag,
):
    root, git = checkout
    canonical = ".agents/skills/yoke/dash/merge.md"
    path = root / canonical
    path.parent.mkdir(parents=True)
    path.write_text("released skill\n")
    git("add", canonical)
    git("-c", "core.hooksPath=/dev/null", "commit", "-qm", "release")
    git("tag", "-a", tag, "-m", "release")
    path.write_text("unreleased skill\n")
    git("add", canonical)
    git("-c", "core.hooksPath=/dev/null", "commit", "-qm", "unreleased")
    git("tag", "0.2.0.999999999999")
    catalogue = render(root)
    assert catalogue["skills/dash/merge.md"] == [
        hashlib.sha256(b"released skill\n").hexdigest(),
    ]
    monkeypatch.setattr(released_bundle_files, "_catalogue", lambda: {})
    monkeypatch.setattr(released_bundle_files, "files", lambda _: root / "empty-bundle")
    (root / "empty-bundle" / canonical).parent.mkdir(parents=True)
    (root / "empty-bundle" / canonical).write_text("other bytes\n")
    proof = released_bundle_files.ReleasedBundleFiles()
    proof.root = root
    assert proof.proves(canonical, "released skill\n")
    assert not proof.proves(canonical, "unreleased skill\n")
