"""Static distribution publishing contract tests."""

from __future__ import annotations

import json
from pathlib import Path

from runtime.api.cli.test_yoke_package_index import _record, _sample_release
from yoke_core.tools import distribution_publish, package_index, release_artifacts


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
        json.dumps(records, indent=2) + "\n", encoding="utf-8",
    )
    package_index.write_simple_index(
        index_dir=simple_dir,
        records=wheel_records,
        wheel_base_url=(
            f"https://api.upyoke.com/dist/releases/{url_version}/wheels"
        ),
    )

    assert distribution_publish.validate_release_directory(release_dir) == records

    channel = distribution_publish.channel_payload(
        channel="stable",
        version=version,
        index_url="https://api.upyoke.com/simple/",
        release_base_url=(
            f"https://api.upyoke.com/dist/releases/{url_version}"
        ),
        generated_at="2026-06-18T00:00:00+00:00",
    )
    assert channel["schema_version"] == 2
    assert channel["channel"] == "stable"
    assert channel["version"] == version
    assert channel["index_url"] == "https://api.upyoke.com/simple/"
    assert channel["installer"]["python_url"] == (
        "https://api.upyoke.com/dist/install.py"
    )
    assert channel["installer"]["shell_url"] == "https://api.upyoke.com/install"

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


def test_distribution_publish_rejects_simple_index_hash_drift(tmp_path: Path) -> None:
    output_root = tmp_path / "release"
    release_dir = output_root / "dist" / "releases" / "0.2.0"
    wheels_dir = release_dir / "wheels"
    simple_dir = output_root / "simple"
    wheels_dir.mkdir(parents=True)

    records, wheel_records = _sample_release(wheels_dir)
    (release_dir / release_artifacts.RELEASE_RECORDS_FILENAME).write_text(
        json.dumps(records, indent=2) + "\n", encoding="utf-8",
    )
    package_index.write_simple_index(
        index_dir=simple_dir,
        records=wheel_records,
        wheel_base_url="https://api.upyoke.com/dist/releases/0.2.0/wheels",
    )
    target = next(wheels_dir.glob("yoke_cli-*.whl"))
    original = target.read_bytes()
    target.write_bytes(b"\x00" * len(original))

    try:
        distribution_publish.validate_release_directory(release_dir)
    except ValueError as exc:
        assert "sha256" in str(exc)
    else:
        raise AssertionError("validate-release must reject hash drift")


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
        json.dumps(records, indent=2) + "\n", encoding="utf-8",
    )
    package_index.write_simple_index(
        index_dir=simple_dir,
        records=wheel_records,
        wheel_base_url=f"https://api.upyoke.com/dist/releases/{version}/wheels",
    )

    assert distribution_publish.validate_release_directory(release_dir) == records
