"""Tests for the retired repo-local data/projects disposition guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import local_shape_disposition as lsd


def test_current_repo_local_shape_paths_are_explicitly_classified() -> None:
    repo_root = Path(__file__).resolve().parents[3]

    report = lsd.assert_explicit_local_shape_disposition(repo_root)

    assert not report.has_unclassified
    assert not report.entries
    assert "projects" not in {
        entry.path.split("/", 1)[0] for entry in report.entries
    }


def test_unclassified_data_path_fails_guard() -> None:
    with pytest.raises(lsd.LocalShapeDispositionError) as excinfo:
        lsd.assert_explicit_local_shape_disposition(
            tracked_paths=["data/new-authority.json"],
        )

    assert "data/new-authority.json" in str(excinfo.value)


def test_unclassified_project_name_fails_guard() -> None:
    report = lsd.audit_local_shape_disposition(
        tracked_paths=[
            "projects/externalwebapp/infra/Pulumi.yaml",
            "projects/new-product/config",
        ],
    )

    assert [(entry.path, entry.bucket) for entry in report.entries] == [
        ("projects/externalwebapp/infra/Pulumi.yaml", lsd.BUCKET_UNCLASSIFIED),
        ("projects/new-product/config", lsd.BUCKET_UNCLASSIFIED),
    ]


def test_tracked_project_tree_fails_guard() -> None:
    with pytest.raises(lsd.LocalShapeDispositionError) as excinfo:
        lsd.assert_explicit_local_shape_disposition(
            tracked_paths=[
                "projects/.gitkeep",
                "projects/externalwebapp/workflows/externalwebapp-deploy.yml",
                "projects/yoke/infra/Pulumi.yaml",
            ],
        )

    assert "projects/.gitkeep" in str(excinfo.value)
    assert "projects/externalwebapp/workflows/externalwebapp-deploy.yml" in str(excinfo.value)
    assert "projects/yoke/infra/Pulumi.yaml" in str(excinfo.value)


def test_report_rendering_is_deterministic() -> None:
    report = lsd.audit_local_shape_disposition(
        tracked_paths=[
            "data/new-authority.json",
            "projects/new-product/config",
        ],
    )

    rendered = lsd.render_local_shape_disposition_report(report)

    assert rendered.startswith("# Repo-Local Shape Disposition\n")
    assert "- unclassified: 2\n" in rendered
    assert rendered.index("| data/new-authority.json |") < rendered.index(
        "| projects/new-product/config |"
    )
