"""Static distribution publishing contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.cli.test_yoke_package_index import _record, _sample_release
from yoke_core.tools import distribution_publish, package_index, release_artifacts

SOURCE_COMMIT = "a" * 40


def _write_downloaded_release_artifact(
    artifact_dir: Path,
    *,
    version: str = "0.2.0+gabc123",
) -> list[dict[str, object]]:
    """Model actions/download-artifact output for the uploaded release_dir."""
    wheels_dir = artifact_dir / release_artifacts.WHEELS_DIR
    wheels_dir.mkdir(parents=True)
    records, _wheel_records = _sample_release(wheels_dir, version=version)
    (artifact_dir / release_artifacts.RELEASE_RECORDS_FILENAME).write_text(
        json.dumps(records, indent=2) + "\n",
        encoding="utf-8",
    )
    return records


def test_distribution_publish_validates_release_and_writes_channel(
    tmp_path: Path,
) -> None:
    version = "0.2.0+gabc123"
    url_version = "0.2.0%2Bgabc123"
    output_root = tmp_path / "release"
    release_dir = output_root / "dist" / "releases" / version
    wheels_dir = release_dir / "wheels"
    simple_dir = output_root / "simple"
    wheels_dir.mkdir(parents=True)

    records, wheel_records = _sample_release(wheels_dir, version=version)
    (release_dir / release_artifacts.RELEASE_RECORDS_FILENAME).write_text(
        json.dumps(records, indent=2) + "\n",
        encoding="utf-8",
    )
    package_index.write_simple_index(
        index_dir=simple_dir,
        records=wheel_records,
        wheel_base_url=(f"https://api.upyoke.com/dist/releases/{url_version}/wheels"),
    )

    assert distribution_publish.validate_release_directory(release_dir) == records

    channel = distribution_publish.channel_payload(
        channel="stable",
        version=version,
        index_url="https://api.upyoke.com/simple/",
        release_base_url=(f"https://api.upyoke.com/dist/releases/{url_version}"),
        generated_at="2026-06-18T00:00:00+00:00",
        migration_manifest_sha256=(
            json.loads(
                (
                    release_dir
                    / release_artifacts.MIGRATION_HISTORY_RELEASE_EVIDENCE_FILENAME
                ).read_text(encoding="utf-8")
            )["manifest"]["sha256"]
        ),
        source_commit=SOURCE_COMMIT,
    )
    assert channel["schema_version"] == 3
    assert channel["channel"] == "stable"
    assert channel["version"] == version
    assert channel["index_url"] == "https://api.upyoke.com/simple/"
    assert channel["installer"]["python_url"] == (
        "https://api.upyoke.com/dist/install.py"
    )
    assert channel["installer"]["shell_url"] == "https://api.upyoke.com/install"
    assert channel["migration_history"]["source_commit"] == SOURCE_COMMIT

    checks = distribution_publish.build_url_checks(
        base_url=f"https://api.upyoke.com/dist/releases/{url_version}/",
        records=records,
        index_url="https://api.upyoke.com/simple/",
        include_mutable=True,
        mutable_channel="stable",
    )
    urls = {check.url: check for check in checks}
    assert urls["https://api.upyoke.com/simple/"].cache_control_contains == "max-age=60"
    assert (
        urls["https://api.upyoke.com/simple/yoke-cli/"].cache_control_contains
        == "max-age=60"
    )
    wheel_url = (
        f"https://api.upyoke.com/dist/releases/{url_version}/wheels/"
        "yoke_cli-0.2.0%2Bgabc123-py3-none-any.whl"
    )
    assert urls[wheel_url].cache_control_contains == "immutable"
    assert urls[wheel_url].sha256 == _record(records, "yoke-cli")["sha256"]
    assert urls[wheel_url].size == _record(records, "yoke-cli")["size"]
    assert "https://api.upyoke.com/dist/channels/stable.json" in urls
    assert "https://api.upyoke.com/dist/channels/latest.json" not in urls
    assert "https://api.upyoke.com/install" in urls


def test_validate_downloaded_release_artifact_flat_payload(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "validated-release"
    records = _write_downloaded_release_artifact(artifact_dir)

    assert (
        distribution_publish.validate_release_artifact_directory(
            artifact_dir,
            expected_source_commit=SOURCE_COMMIT,
        )
        == records
    )


def test_validate_downloaded_release_artifact_rejects_wheel_tampering(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "validated-release"
    _write_downloaded_release_artifact(artifact_dir)
    wheel = next((artifact_dir / release_artifacts.WHEELS_DIR).glob("*.whl"))
    original = wheel.read_bytes()
    wheel.write_bytes(b"\x00" * len(original))

    with pytest.raises(ValueError, match="sha256 does not match release record"):
        distribution_publish.validate_release_artifact_directory(artifact_dir)


def test_validate_downloaded_release_artifact_rejects_evidence_tampering(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "validated-release"
    _write_downloaded_release_artifact(artifact_dir)
    evidence_path = (
        artifact_dir / release_artifacts.MIGRATION_HISTORY_RELEASE_EVIDENCE_FILENAME
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["manifest"]["sha256"] = "f" * 64
    evidence_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not bind"):
        distribution_publish.validate_release_artifact_directory(artifact_dir)


def test_validate_release_artifact_cli_reports_tampering(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_dir = tmp_path / "validated-release"
    _write_downloaded_release_artifact(artifact_dir)
    wheel = next((artifact_dir / release_artifacts.WHEELS_DIR).glob("*.whl"))
    wheel.write_bytes(b"tampered")

    result = distribution_publish.main(
        [
            "validate-release-artifact",
            str(artifact_dir),
            "--source-commit",
            SOURCE_COMMIT,
        ]
    )

    assert result == 1
    stderr = capsys.readouterr().err
    assert "distribution-publish:" in stderr
    assert "size does not match release record" in stderr


@pytest.mark.parametrize(
    "relative_release_dir",
    (
        Path("0.2.0+gabc123"),
        Path("dist/releases/0.2.0+gabc123/nested"),
    ),
    ids=("shallow", "deep"),
)
def test_validate_release_rejects_noncanonical_layout(
    tmp_path: Path,
    relative_release_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release_dir = tmp_path / relative_release_dir

    result = distribution_publish.main(["validate-release", str(release_dir)])

    assert result == 1
    stderr = capsys.readouterr().err
    assert "<output-root>/dist/releases/<version>" in stderr


def test_validate_release_rejects_missing_simple_index(tmp_path: Path) -> None:
    version = "0.2.0+gabc123"
    release_dir = tmp_path / "dist" / "releases" / version
    _write_downloaded_release_artifact(release_dir, version=version)

    with pytest.raises(ValueError, match="simple index is missing"):
        distribution_publish.validate_release_directory(release_dir)


def test_channel_contract_preserves_v2_and_requires_evidence_for_v3() -> None:
    legacy = {
        "schema_version": 2,
        "channel": "stable",
        "version": "0.1.0+launch.190",
    }
    distribution_publish.validate_channel_pointer(legacy)
    try:
        distribution_publish.validate_channel_pointer(
            legacy,
            require_content_evidence=True,
        )
    except ValueError as exc:
        assert "schema v2" in str(exc)
    else:
        raise AssertionError("content adoption accepted a legacy v2 pointer")

    candidate = {**legacy, "schema_version": 3}
    try:
        distribution_publish.validate_channel_pointer(
            candidate,
            require_content_evidence=True,
        )
    except ValueError as exc:
        assert "lacks migration_history" in str(exc)
    else:
        raise AssertionError("candidate channel accepted missing release evidence")


def test_distribution_publish_rejects_simple_index_hash_drift(tmp_path: Path) -> None:
    version = "0.2.0+gabc123"
    output_root = tmp_path / "release"
    release_dir = output_root / "dist" / "releases" / version
    wheels_dir = release_dir / "wheels"
    simple_dir = output_root / "simple"
    wheels_dir.mkdir(parents=True)

    records, wheel_records = _sample_release(wheels_dir, version=version)
    (release_dir / release_artifacts.RELEASE_RECORDS_FILENAME).write_text(
        json.dumps(records, indent=2) + "\n",
        encoding="utf-8",
    )
    package_index.write_simple_index(
        index_dir=simple_dir,
        records=wheel_records,
        wheel_base_url=("https://api.upyoke.com/dist/releases/0.2.0%2Bgabc123/wheels"),
    )
    record = records[0]
    project_index = simple_dir / str(record["project"]) / "index.html"
    original_sha = str(record["sha256"])
    drifted_sha = ("0" if original_sha[0] != "0" else "1") + original_sha[1:]
    project_index.write_text(
        project_index.read_text(encoding="utf-8").replace(
            original_sha,
            drifted_sha,
        ),
        encoding="utf-8",
    )

    try:
        distribution_publish.validate_release_directory(release_dir)
    except ValueError as exc:
        assert "simple index sha256 mismatch" in str(exc)
    else:
        raise AssertionError("validate-release must reject hash drift")


def test_distribution_publish_rejects_migration_evidence_tampering(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "release"
    release_dir = output_root / "dist" / "releases" / "0.2.0+gabc123"
    wheels_dir = release_dir / "wheels"
    wheels_dir.mkdir(parents=True)
    records, wheel_records = _sample_release(
        wheels_dir,
        version="0.2.0+gabc123",
    )
    (release_dir / release_artifacts.RELEASE_RECORDS_FILENAME).write_text(
        json.dumps(records, indent=2) + "\n",
        encoding="utf-8",
    )
    package_index.write_simple_index(
        index_dir=output_root / "simple",
        records=wheel_records,
        wheel_base_url=("https://api.upyoke.com/dist/releases/0.2.0%2Bgabc123/wheels"),
    )
    evidence_path = (
        release_dir / release_artifacts.MIGRATION_HISTORY_RELEASE_EVIDENCE_FILENAME
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["manifest"]["sha256"] = "f" * 64
    evidence_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    try:
        distribution_publish.validate_release_directory(release_dir)
    except ValueError as exc:
        assert "does not bind" in str(exc)
    else:
        raise AssertionError("release validation must reject evidence tampering")


def test_validate_release_matches_url_quoted_local_version_links(
    tmp_path: Path,
) -> None:
    version = "0.2.0+gabc123"
    output_root = tmp_path / "release"
    release_dir = output_root / "dist" / "releases" / version
    wheels_dir = release_dir / "wheels"
    simple_dir = output_root / "simple"
    wheels_dir.mkdir(parents=True)

    records, wheel_records = _sample_release(wheels_dir, version=version)
    (release_dir / release_artifacts.RELEASE_RECORDS_FILENAME).write_text(
        json.dumps(records, indent=2) + "\n",
        encoding="utf-8",
    )
    package_index.write_simple_index(
        index_dir=simple_dir,
        records=wheel_records,
        wheel_base_url=f"https://api.upyoke.com/dist/releases/{version}/wheels",
    )

    assert distribution_publish.validate_release_directory(release_dir) == records
