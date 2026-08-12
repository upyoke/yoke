"""Validate the universe asset contract inside a built product wheel."""

from __future__ import annotations

import zipfile
from pathlib import Path

from yoke_contracts.universe_asset_contract import UNIVERSE_ASSETS

from yoke_core.tools import package_index


def validate_universe_asset_contract(wheels_dir: Path) -> None:
    """Fail unless the built core wheel contains every contracted asset."""

    core_wheels = [
        record.source
        for record in package_index.read_wheel_records(wheels_dir)
        if record.canonical_name == "yoke-core"
    ]
    if len(core_wheels) != 1:
        raise ValueError(
            "this build does not emit the universe contract: "
            "expected exactly one yoke-core wheel"
        )
    try:
        with zipfile.ZipFile(core_wheels[0]) as archive:
            members = set(archive.namelist())
            for asset in UNIVERSE_ASSETS:
                if asset.artifact_member not in members:
                    _raise_contract_error(asset.public_path, asset.marker, "is missing")
                content = archive.read(asset.artifact_member).decode("utf-8")
                if asset.marker not in content:
                    _raise_contract_error(asset.public_path, asset.marker, "lacks")
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise ValueError(
            "this build does not emit the universe contract: "
            f"cannot inspect {core_wheels[0].name}: {exc}"
        ) from exc


def _raise_contract_error(public_path: str, marker: str, problem: str) -> None:
    raise ValueError(
        "this build does not emit the universe contract: "
        f"{public_path} {problem}; expected marker {marker!r}"
    )
