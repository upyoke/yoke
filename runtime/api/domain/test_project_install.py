"""Tests for ``yoke project install``/``refresh`` file + manifest behavior.

Drives :func:`project_install.apply_bundle` (the network-free core) with a
fake bundle dict against a tmp repo; the seed-if-missing contract pass
lives in ``test_project_install_contract.py``; hook-merge specifics and
uninstall in ``test_project_install_hooks.py``.
"""

from __future__ import annotations

from runtime.api.domain.project_install_test_support import (
    MANIFEST_REL as MANIFEST_REL,
    _tree_bytes as _tree_bytes,
)


import json

import pytest

from yoke_cli.project_install.runner import ProjectInstallError, apply_bundle
from yoke_core.domain.project_install_test_helpers import (
    DEFAULT_FILES,
    make_bundle,
)


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


def _manifest(repo) -> dict:
    return json.loads((repo / MANIFEST_REL).read_text(encoding="utf-8"))


def test_fresh_install_writes_files_manifest_and_hooks(repo) -> None:
    report = apply_bundle(repo, make_bundle(), source="test")

    for entry in DEFAULT_FILES:
        assert (repo / entry["path"]).read_text("utf-8") == entry["content"]
    assert sorted(report["files_written"]) == sorted(e["path"] for e in DEFAULT_FILES)
    manifest = _manifest(repo)
    assert manifest["manifest_schema"] == 1
    assert manifest["yoke_version"] == "9.9.9"
    assert manifest["project_id"] == 7
    assert set(manifest["files"]) == {e["path"] for e in DEFAULT_FILES}
    assert manifest["created_settings_files"] == [
        ".claude/settings.json",
        ".codex/hooks.json",
    ]
    assert (repo / ".claude/settings.json").is_file()
    assert (repo / ".codex/hooks.json").is_file()
    assert MANIFEST_REL not in manifest["files"]
    assert report["machine_config_newly_registered"] is False


def test_second_run_is_a_no_op(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    before = _manifest(repo)

    report = apply_bundle(repo, make_bundle(), operation="refresh", source="test")

    assert report["files_written"] == []
    assert report["files_pruned"] == []
    assert report["hooks_added"] == {}
    assert report["warnings"] == []
    assert _manifest(repo) == before


def test_refresh_prunes_files_dropped_from_bundle(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    survivors = DEFAULT_FILES[:-1]

    report = apply_bundle(
        repo, make_bundle(survivors), operation="refresh", source="test"
    )

    dropped = DEFAULT_FILES[-1]["path"]
    assert report["files_pruned"] == [dropped]
    assert not (repo / dropped).exists()
    assert set(_manifest(repo)["files"]) == {e["path"] for e in survivors}


def test_refresh_preserves_locally_modified_dropped_file(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    dropped = DEFAULT_FILES[-1]["path"]
    (repo / dropped).write_text("operator edits\n", encoding="utf-8")

    before = _tree_bytes(repo)
    with pytest.raises(ProjectInstallError, match="install_drift_local_edits"):
        apply_bundle(
            repo, make_bundle(DEFAULT_FILES[:-1]), operation="refresh", source="test"
        )
    assert _tree_bytes(repo) == before
    assert dropped in _manifest(repo)["files"]


def test_bundle_refresh_refuses_real_local_edits(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    target = DEFAULT_FILES[0]["path"]
    (repo / target).write_text("local edits\n", encoding="utf-8")
    before = _tree_bytes(repo)
    with pytest.raises(ProjectInstallError, match="install_drift_local_edits"):
        apply_bundle(repo, make_bundle(), operation="refresh", source="test")
    assert _tree_bytes(repo) == before


@pytest.mark.parametrize(
    "bad_path",
    [
        "../escape.md",
        "/etc/absolute.md",
        ".yoke/notes.md",
        ".claude/settings.json",
    ],
)
def test_unsafe_bundle_paths_are_refused(repo, bad_path) -> None:
    bundle = make_bundle([{"path": bad_path, "content": "x"}])

    with pytest.raises(ProjectInstallError):
        apply_bundle(repo, bundle, source="test")
    assert not (repo / MANIFEST_REL).exists()


def test_unsupported_bundle_schema_is_refused(repo) -> None:
    with pytest.raises(ProjectInstallError) as exc_info:
        apply_bundle(repo, make_bundle(bundle_schema=999), source="test")
    assert "rerun the public installer" in str(exc_info.value)


def test_unsupported_manifest_schema_is_refused(repo) -> None:
    (repo / ".yoke").mkdir()
    (repo / MANIFEST_REL).write_text(
        json.dumps({"manifest_schema": 99}), encoding="utf-8"
    )

    with pytest.raises(ProjectInstallError):
        apply_bundle(repo, make_bundle(), source="test")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("files", ["not-a-map"]),
        ("contract_files", ".yoke/policy"),
        ("strategy_files", [".yoke/strategy/MISSION.md"]),
        ("created_settings_files", ".claude/settings.json"),
        ("hook_entries", []),
        ("git_hooks", ["unknown-hook"]),
        ("git_hook_hashes", [".git/hooks/pre-commit"]),
        ("worktrees_ignore_added", "yes"),
    ],
)
def test_malformed_prior_manifest_shape_fails_before_mutation(
    repo,
    field,
    value,
) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    manifest = _manifest(repo)
    manifest[field] = value
    (repo / MANIFEST_REL).write_text(json.dumps(manifest), encoding="utf-8")
    before = _tree_bytes(repo)

    with pytest.raises(ProjectInstallError):
        apply_bundle(repo, make_bundle(DEFAULT_FILES[:1]), source="test")

    assert _tree_bytes(repo) == before


def test_prior_manifest_escape_cannot_prune_outside_repo(repo, tmp_path) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("outside\n", encoding="utf-8")
    (repo / ".yoke").mkdir()
    (repo / MANIFEST_REL).write_text(
        json.dumps(
            {
                "manifest_schema": 1,
                "files": {
                    str(victim): (
                        "263c0bcd0f6c5a81149b9b65a7f4f319d80b48c704437b6125ee28e738b8b9ff"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )
    before = _tree_bytes(repo)

    with pytest.raises(ProjectInstallError, match="unsafe path"):
        apply_bundle(repo, make_bundle(), source="test")

    assert victim.read_text(encoding="utf-8") == "outside\n"
    assert _tree_bytes(repo) == before


@pytest.mark.parametrize(
    ("symlink_rel", "bundle_files"),
    [
        (".agents", [{"path": ".agents/skills/yoke/SKILL.md", "content": "x"}]),
        (".claude", DEFAULT_FILES),
        (".yoke", DEFAULT_FILES),
    ],
)
def test_symlink_parent_escape_fails_before_any_mutation(
    repo,
    tmp_path,
    symlink_rel,
    bundle_files,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / symlink_rel).symlink_to(outside, target_is_directory=True)
    before = _tree_bytes(repo)

    with pytest.raises(ProjectInstallError, match="resolves outside repo root"):
        apply_bundle(repo, make_bundle(bundle_files), source="test")

    assert _tree_bytes(repo) == before
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("git_symlink", ["git-dir", "hooks-dir"])
def test_git_hook_symlink_escape_fails_before_apply_mutation(
    repo,
    tmp_path,
    git_symlink,
) -> None:
    outside = tmp_path / "outside-git"
    (outside / "hooks").mkdir(parents=True)
    if git_symlink == "git-dir":
        (repo / ".git").symlink_to(outside, target_is_directory=True)
    else:
        (repo / ".git").mkdir()
        (repo / ".git/hooks").symlink_to(
            outside / "hooks",
            target_is_directory=True,
        )
    before = _tree_bytes(repo)

    with pytest.raises(ProjectInstallError, match="resolves outside repo root"):
        apply_bundle(repo, make_bundle(), source="test")

    assert _tree_bytes(repo) == before
    assert list((outside / "hooks").iterdir()) == []
