"""Client-local preview/apply/drift reconciliation safety."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from yoke_contracts.project_artifacts import PROJECT_ARTIFACT_MANIFEST_REL
from yoke_cli.project_artifacts.planner import build_plan
from yoke_cli.project_artifacts import runner
from yoke_cli.project_artifacts.validate import (
    ProjectArtifactError,
    json_digest,
    load_manifest,
    sha256_text,
    validate_bundle,
)
from yoke_cli.project_artifacts.writer import apply_plan


def _bundle(contents: dict[str, tuple[str, int]]) -> dict:
    entries = [
        {
            "path": path,
            "content": content,
            "sha256": sha256_text(content),
            "mode": mode,
        }
        for path, (content, mode) in sorted(contents.items())
    ]
    material = [
        {"path": e["path"], "sha256": e["sha256"], "mode": e["mode"]} for e in entries
    ]
    return {
        "bundle_schema": 1,
        "project_id": 71,
        "project_slug": "sample-service",
        "template": "webapp",
        "template_version": "webapp@1.2.3",
        "yoke_version": "1.2.3",
        "template_source": "packaged-template-mirror",
        "template_digest": "1" * 64,
        "settings_digest": "2" * 64,
        "content_digest": json_digest(material),
        "checkout_identity": {
            "project_id": 71,
            "project_slug": "sample-service",
            "github_repo": "example/sample-service",
            "github_web_url": "https://github.com",
        },
        "artifact_policy": {
            "generated_reference_prefix": ("docs/yoke-generated/deployment-reference/"),
            "project_owned_prefixes": [".yoke/runbooks/"],
            "deviation_policy": "preserve-and-refuse",
            "prune_policy": "manifest-owned-only",
        },
        "artifacts": entries,
        "pulumi_stack_config": {"included": False, "reason": "stack scoped"},
    }


def _preview(repo: Path, bundle: dict):
    entries = validate_bundle(bundle, source_dev_admin=False)
    manifest = load_manifest(repo)
    return entries, manifest, build_plan(repo, bundle, entries, manifest)


def test_apply_then_external_drift_verification_is_clean(tmp_path: Path) -> None:
    repo = tmp_path / "project"
    repo.mkdir()
    bundle = _bundle(
        {
            ".github/workflows/sample-service-deploy.yml": ("name: Deploy\n", 0o644),
            "docs/yoke-generated/deployment-reference/deploy.md": (
                "# Deploy\n",
                0o644,
            ),
            "ops/converge.py": ("#!/usr/bin/env python3\n", 0o755),
            "infra/program.py": ("# static\n", 0o644),
        }
    )
    entries, manifest, plan = _preview(repo, bundle)
    assert [row["path"] for row in plan["creates"]] == sorted(
        entry["path"] for entry in entries
    )
    result = apply_plan(repo, bundle, entries, manifest, plan)
    assert sorted(result["written"]) == sorted(entry["path"] for entry in entries)

    _entries, refreshed_manifest, clean = _preview(repo, bundle)
    assert refreshed_manifest is not None
    assert clean["drift"] is False
    assert clean["conflicts"] == []


def test_project_owned_deviation_is_reported_and_apply_refuses(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "project"
    target = repo / ".github/workflows/sample-service-deploy.yml"
    target.parent.mkdir(parents=True)
    target.write_text("name: Project-owned deployment\n")
    bundle = _bundle(
        {
            ".github/workflows/sample-service-deploy.yml": ("name: Deploy\n", 0o644),
        }
    )
    entries, manifest, plan = _preview(repo, bundle)
    assert plan["creates"] == []
    assert plan["conflicts"][0]["reason"] == "unowned_existing"
    before = target.read_bytes()
    with pytest.raises(ProjectArtifactError, match="conflicts remain"):
        apply_plan(repo, bundle, entries, manifest, plan)
    assert target.read_bytes() == before
    assert not (repo / PROJECT_ARTIFACT_MANIFEST_REL).exists()


def test_project_owned_runbook_is_outside_generic_manifest(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "project"
    runbook = repo / ".yoke/runbooks/deploy.md"
    runbook.parent.mkdir(parents=True)
    runbook.write_text("# Project-specific deploy help\n")
    before = runbook.read_bytes()
    bundle = _bundle(
        {
            "docs/yoke-generated/deployment-reference/deploy.md": (
                "# Generic generated reference\n",
                0o644,
            ),
        }
    )
    entries, manifest, plan = _preview(repo, bundle)
    apply_plan(repo, bundle, entries, manifest, plan)
    assert runbook.read_bytes() == before
    refreshed = load_manifest(repo)
    assert refreshed is not None
    assert ".yoke/runbooks/deploy.md" not in refreshed["artifacts"]


def _write_install_binding(repo: Path, project_id: int) -> None:
    path = repo / ".yoke/install-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "manifest_schema": 1,
                "project_id": project_id,
            }
        )
    )


def _repo_bytes(repo: Path) -> dict[str, bytes]:
    return {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(repo).parts
    }


def test_cross_project_bundle_refuses_before_planning_or_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "project-b"
    repo.mkdir()
    _write_install_binding(repo, 72)
    runbook = repo / ".yoke/runbooks/deploy.md"
    runbook.parent.mkdir(parents=True, exist_ok=True)
    runbook.write_text("# Project B\n")
    bundle = _bundle({"ops/converge.py": ("wanted\n", 0o755)})
    bundle["template_source"] = "source-dev-admin-template-tree"
    monkeypatch.setattr(runner, "_fetch_bundle", lambda *args, **kwargs: bundle)
    before = _repo_bytes(repo)

    with pytest.raises(ProjectArtifactError, match="does not match"):
        runner.refresh(
            repo,
            project="sample-service",
            apply=True,
            source_dev_admin=True,
        )

    assert _repo_bytes(repo) == before
    assert not (repo / PROJECT_ARTIFACT_MANIFEST_REL).exists()


def test_wrong_git_origin_refuses_before_planning_or_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "project"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "remote",
            "add",
            "origin",
            "https://github.com/example/other-service.git",
        ],
        check=True,
        capture_output=True,
    )
    _write_install_binding(repo, 71)
    marker = repo / "project-owned.txt"
    marker.write_text("preserve\n")
    bundle = _bundle({"ops/converge.py": ("wanted\n", 0o755)})
    monkeypatch.setattr(runner, "_fetch_bundle", lambda *args, **kwargs: bundle)
    before = _repo_bytes(repo)

    with pytest.raises(ProjectArtifactError, match="live origin does not match"):
        runner.refresh(repo, project="sample-service", apply=True)

    assert _repo_bytes(repo) == before
    assert not (repo / PROJECT_ARTIFACT_MANIFEST_REL).exists()


def test_local_project_without_repository_binding_can_preview(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "local-project"
    repo.mkdir()
    _write_install_binding(repo, 71)
    bundle = _bundle({"ops/converge.py": ("wanted\n", 0o755)})
    bundle["checkout_identity"] = {
        "project_id": 71,
        "project_slug": "sample-service",
        "github_repo": None,
        "github_web_url": None,
    }
    monkeypatch.setattr(runner, "_fetch_bundle", lambda *args, **kwargs: bundle)

    report = runner.refresh(repo, project="sample-service")

    assert report["operation"] == "preview"
    assert report["drift"] is True
    assert report["plan"]["creates"][0]["path"] == "ops/converge.py"


def test_modified_managed_file_and_safe_prune_are_both_exact(tmp_path: Path) -> None:
    repo = tmp_path / "project"
    repo.mkdir()
    initial = _bundle(
        {
            "ops/modified.py": ("old\n", 0o755),
            "ops/removed.py": ("removed\n", 0o755),
        }
    )
    entries, manifest, plan = _preview(repo, initial)
    apply_plan(repo, initial, entries, manifest, plan)
    (repo / "ops/modified.py").write_text("project change\n")

    fresh = _bundle({"ops/modified.py": ("new\n", 0o755)})
    _entries, _manifest, drift = _preview(repo, fresh)
    assert [row["path"] for row in drift["conflicts"]] == ["ops/modified.py"]
    assert [row["path"] for row in drift["prunes"]] == ["ops/removed.py"]


def test_manifest_traversal_and_symlink_parent_fail_before_mutation(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "project"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "ops").symlink_to(outside, target_is_directory=True)
    bundle = _bundle({"ops/converge.py": ("safe\n", 0o755)})
    entries = validate_bundle(bundle, source_dev_admin=False)
    with pytest.raises(ProjectArtifactError, match="symlink component"):
        build_plan(repo, bundle, entries, None)
    assert list(outside.iterdir()) == []

    manifest_path = repo / PROJECT_ARTIFACT_MANIFEST_REL
    manifest_path.parent.mkdir(exist_ok=True)
    payload = {
        "manifest_schema": 1,
        "project_id": 71,
        "project_slug": "sample-service",
        "template": "webapp",
        "template_version": "webapp@1.2.3",
        "yoke_version": "1.2.3",
        "template_source": "packaged-template-mirror",
        "template_digest": "1" * 64,
        "settings_digest": "2" * 64,
        "content_digest": "3" * 64,
        "checkout_identity": {
            "project_id": 71,
            "project_slug": "sample-service",
            "github_repo": "example/sample-service",
            "github_web_url": "https://github.com",
        },
        "artifact_policy": {
            "generated_reference_prefix": ("docs/yoke-generated/deployment-reference/"),
            "project_owned_prefixes": [".yoke/runbooks/"],
            "deviation_policy": "preserve-and-refuse",
            "prune_policy": "manifest-owned-only",
        },
        "artifacts": {"../outside/owned": {"sha256": "4" * 64, "mode": 0o644}},
    }
    manifest_path.write_text(json.dumps(payload))
    with pytest.raises(ProjectArtifactError, match="unsafe managed artifact path"):
        load_manifest(repo)
    assert list(outside.iterdir()) == []


def test_bundle_checkout_identity_slug_must_match_bundle_slug() -> None:
    bundle = _bundle({"ops/converge.py": ("safe\n", 0o755)})
    bundle["checkout_identity"]["project_slug"] = "different-project"

    with pytest.raises(ProjectArtifactError, match="project slug does not match"):
        validate_bundle(bundle, source_dev_admin=False)


def test_source_dev_bundle_rejects_unknown_template_provenance() -> None:
    bundle = _bundle({"ops/converge.py": ("safe\n", 0o755)})
    bundle["template_source"] = "arbitrary-local-tree"

    with pytest.raises(ProjectArtifactError, match="unknown template source"):
        validate_bundle(bundle, source_dev_admin=True)
