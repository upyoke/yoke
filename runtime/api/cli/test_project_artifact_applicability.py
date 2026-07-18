"""CLI reconciliation behavior when the generic artifact contract is disabled."""

from __future__ import annotations

from pathlib import Path

from runtime.api.cli.test_project_artifact_reconciliation import (
    _bundle,
    _repo_bytes,
    _write_install_binding,
)
from yoke_cli.project_artifacts import runner
from yoke_cli.project_artifacts.validate import json_digest
from yoke_contracts.project_artifacts import PROJECT_ARTIFACT_MANIFEST_REL


def test_non_applicable_project_is_a_clean_no_op(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "specialized-project"
    repo.mkdir()
    _write_install_binding(repo, 71)
    artifact_manifest = repo / PROJECT_ARTIFACT_MANIFEST_REL
    artifact_manifest.write_text("not valid json\n")
    bundle = _bundle({"ops/converge.py": ("wanted\n", 0o755)})
    bundle.update(
        applicable=False,
        applicability_reason="a project-owned release factory applies",
        artifacts=[],
        content_digest=json_digest([]),
        checkout_identity={
            "project_id": 71,
            "project_slug": "sample-service",
            "github_repo": None,
            "github_web_url": None,
        },
    )
    monkeypatch.setattr(runner, "_fetch_bundle", lambda *args, **kwargs: bundle)
    before = _repo_bytes(repo)

    report = runner.refresh(repo, project="sample-service", apply=True)

    assert report["applicable"] is False
    assert report["skipped"] is True
    assert report["drift"] is False
    assert report["plan"]["creates"] == []
    assert report["applied"] is False
    assert _repo_bytes(repo) == before
