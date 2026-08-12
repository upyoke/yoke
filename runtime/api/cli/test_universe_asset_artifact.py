"""Built-wheel proofs for the hosted universe asset contract."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from yoke_contracts.universe_asset_contract import UNIVERSE_ASSETS
from yoke_core.tools import (
    distribution_release_validation,
    package_index,
    universe_asset_artifact,
)


def test_built_core_wheel_emits_the_universe_contract(tmp_path: Path) -> None:
    wheels_dir = _write_core_wheel(tmp_path)

    universe_asset_artifact.validate_universe_asset_contract(wheels_dir)


def test_release_validation_reports_a_missing_built_asset(tmp_path: Path) -> None:
    missing = UNIVERSE_ASSETS[0]
    wheels_dir = _write_core_wheel(tmp_path, omitted=missing.artifact_member)
    records = package_index.build_records_manifest(
        package_index.read_wheel_records(wheels_dir)
    )

    with pytest.raises(ValueError) as caught:
        distribution_release_validation.validate_wheel_records_match(
            records, wheels_dir
        )

    assert missing.public_path in str(caught.value)
    assert missing.marker in str(caught.value)


def test_universe_contract_reports_a_missing_marker(tmp_path: Path) -> None:
    mismatched = UNIVERSE_ASSETS[2]
    wheels_dir = _write_core_wheel(
        tmp_path,
        replacements={mismatched.artifact_member: b"export const unrelated = true;\n"},
    )

    with pytest.raises(ValueError) as caught:
        universe_asset_artifact.validate_universe_asset_contract(wheels_dir)

    assert mismatched.public_path in str(caught.value)
    assert mismatched.marker in str(caught.value)


def _write_core_wheel(
    root: Path,
    *,
    omitted: str | None = None,
    replacements: dict[str, bytes] | None = None,
) -> Path:
    wheels_dir = root / "wheels"
    wheels_dir.mkdir()
    wheel = wheels_dir / "yoke_core-0.2.0-py3-none-any.whl"
    files = {
        "yoke_core-0.2.0.dist-info/METADATA": (
            b"Metadata-Version: 2.1\nName: yoke-core\nVersion: 0.2.0\n"
        ),
        **{
            asset.artifact_member: asset.marker.encode("utf-8")
            for asset in UNIVERSE_ASSETS
            if asset.artifact_member != omitted
        },
        **(replacements or {}),
    }
    with zipfile.ZipFile(wheel, "w") as archive:
        for member, content in files.items():
            archive.writestr(member, content)
    return wheels_dir
