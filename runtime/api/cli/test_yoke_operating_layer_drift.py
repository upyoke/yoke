"""Direction-aware comparison for tracked project teaching."""

from __future__ import annotations

from yoke_contracts.project_contract.installed_layer import (
    installed_layer_receipt_entry,
)
from yoke_cli import operating_layer_drift as drift
from yoke_cli.transport import source_build_skew


def _write_receipt(project, release: str, *, source_build: str = "") -> None:
    entry = installed_layer_receipt_entry(release, source_build=source_build)
    path = project / entry["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(entry["content"], encoding="utf-8")


def test_packaged_launch_numbers_establish_both_directions() -> None:
    ahead = drift.compare_running_to_release(
        "0.1.1+launch.245",
        running_version="0.1.1+launch.246",
        running_module_file="",
    )
    behind = drift.compare_running_to_release(
        "0.1.1+launch.246",
        running_version="0.1.1+launch.245",
        running_module_file="",
    )

    assert ahead.relationship == drift.RUNNING_AHEAD
    assert behind.relationship == drift.RUNNING_BEHIND


def test_installed_layer_comparison_retains_receipt_root(tmp_path) -> None:
    project = tmp_path / "project with spaces"
    nested = project / "src"
    nested.mkdir(parents=True)
    _write_receipt(project, "0.1.1+launch.245")

    comparison = drift.compare_installed_layer(
        nested,
        running_version="0.1.1+launch.246",
        running_module_file="",
    )

    assert comparison is not None
    assert comparison.layer_is_behind
    assert comparison.receipt.project_root == project
    assert drift.refresh_command(project) == (
        f"yoke project install '{project}'"
    )


def test_source_checkout_uses_git_relationship(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(drift, "source_checkout_root", lambda module: tmp_path)
    monkeypatch.setattr(
        source_build_skew,
        "compare_to_server_build",
        lambda root, build: source_build_skew.BuildComparison(
            source_build_skew.AHEAD,
            local_head="abc",
            server_build=build,
            ahead_by=1,
        ),
    )

    comparison = drift.compare_running_to_release(
        "0.1.1+launch.245",
        running_version="",
        running_module_file="/checkout/yoke_cli/__init__.py",
    )

    assert comparison.relationship == drift.RUNNING_AHEAD
    assert comparison.source_checkout == str(tmp_path)


def test_source_receipt_compares_its_recorded_build(
    tmp_path, monkeypatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_receipt(
        project,
        "source-content-digest",
        source_build="installed-head",
    )
    monkeypatch.setattr(drift, "source_checkout_root", lambda module: tmp_path)
    seen = {}

    def compare(root, build):
        seen.update(root=root, build=build)
        return source_build_skew.BuildComparison(
            source_build_skew.AHEAD,
            local_head="running-head",
            server_build=build,
            ahead_by=1,
        )

    monkeypatch.setattr(source_build_skew, "compare_to_server_build", compare)

    comparison = drift.compare_installed_layer(
        project,
        running_version="source-running-digest",
        running_module_file="/checkout/yoke_cli/__init__.py",
    )

    assert comparison is not None
    assert comparison.layer_is_behind
    assert seen == {"root": str(tmp_path), "build": "installed-head"}


def test_source_receipt_detects_content_change_at_same_commit(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(drift, "source_checkout_root", lambda module: tmp_path)
    monkeypatch.setattr(
        source_build_skew,
        "compare_to_server_build",
        lambda root, build: source_build_skew.BuildComparison(
            source_build_skew.EQUAL,
            local_head=build,
            server_build=build,
        ),
    )
    monkeypatch.setattr(
        drift,
        "_current_source_layer_release",
        lambda checkout: "source-new-content",
    )

    comparison = drift.compare_running_to_release(
        "source-old-content",
        running_version="source-running",
        running_module_file="/checkout/yoke_cli/__init__.py",
        reference_source_build="installed-head",
    )

    assert comparison.relationship == drift.RUNNING_AHEAD
    assert "content changed at the same commit" in comparison.detail


def test_legacy_source_receipt_compares_content_without_commit(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(drift, "source_checkout_root", lambda module: tmp_path)
    monkeypatch.setattr(
        drift,
        "_current_source_layer_release",
        lambda checkout: "source-new-content",
    )

    comparison = drift.compare_running_to_release(
        "source-old-content",
        running_version="source-running",
        running_module_file="/checkout/yoke_cli/__init__.py",
    )

    assert comparison.relationship == drift.RUNNING_AHEAD
    assert "legacy receipt" in comparison.detail


def test_unknown_release_fails_open() -> None:
    comparison = drift.compare_running_to_release(
        "source-deadbeef",
        running_version="source-cafebabe",
        running_module_file="",
    )
    fallback = drift.compare_running_to_release(
        "0.1.0",
        running_version="0.1.1+launch.246",
        running_module_file="",
    )

    assert comparison.relationship == drift.RUNNING_UNKNOWN
    assert fallback.relationship == drift.RUNNING_UNKNOWN
