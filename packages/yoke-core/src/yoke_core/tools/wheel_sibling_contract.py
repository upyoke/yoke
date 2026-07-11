"""Validate the mandatory dependency contract between product wheels."""

from __future__ import annotations

import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Iterable

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from yoke_core.tools import package_index


class WheelSiblingPinError(ValueError):
    """Raised when product wheels cannot use one safe dependency contract."""


def assert_wheel_siblings_pinned(
    wheel: Path, product_names: Iterable[str], expected_version: str
) -> None:
    """Fail unless the wheel has its exact mandatory sibling pins."""

    assert_wheel_sibling_contract(
        wheel,
        {canonicalize_name(name) for name in product_names},
        expected_version,
        require_pins=True,
    )


def assert_wheel_sibling_contract(
    wheel: Path,
    product_canonical: set[str],
    expected_version: str,
    *,
    require_pins: bool,
) -> None:
    """Validate exact sibling edges, optionally allowing bare build inputs."""

    wheel_name = _wheel_name(wheel)
    expected_siblings = set(
        package_index.PRODUCT_SIBLING_DEPENDENCIES.get(wheel_name, ())
    )
    if wheel_name not in package_index.PRODUCT_SIBLING_DEPENDENCIES:
        raise WheelSiblingPinError(
            f"{wheel.name}: no product dependency contract for {wheel_name}"
        )
    target = {f"=={expected_version}"}
    found: set[str] = set()
    for raw in wheel_requires_dist(wheel):
        requirement = Requirement(raw)
        sibling_name = canonicalize_name(requirement.name)
        if sibling_name not in product_canonical:
            continue
        if sibling_name in found:
            raise WheelSiblingPinError(
                f"{wheel.name}: duplicate product sibling '{requirement.name}'"
            )
        found.add(sibling_name)
        if sibling_name not in expected_siblings:
            raise WheelSiblingPinError(
                f"{wheel.name}: unexpected product sibling '{requirement.name}'"
            )
        if requirement.url is not None:
            raise WheelSiblingPinError(
                f"{wheel.name}: product sibling '{requirement.name}' "
                "must not use a direct URL"
            )
        if requirement.marker is not None or requirement.extras:
            raise WheelSiblingPinError(
                f"{wheel.name}: product sibling '{requirement.name}' must be "
                "unconditional and have no extras"
            )
        specifiers = {str(spec) for spec in requirement.specifier}
        if (require_pins and specifiers != target) or (
            not require_pins and specifiers and specifiers != target
        ):
            raise WheelSiblingPinError(
                f"{wheel.name}: product sibling '{requirement.name}' must be "
                f"pinned to =={expected_version}, found '{raw.strip()}'"
            )
    missing_siblings = sorted(expected_siblings - found)
    if missing_siblings:
        raise WheelSiblingPinError(
            f"{wheel.name}: missing required product sibling(s): "
            + ", ".join(missing_siblings)
        )


def wheel_requires_dist(wheel: Path) -> list[str]:
    """Return the Requires-Dist values from wheel core metadata."""

    with zipfile.ZipFile(wheel) as archive:
        metadata_files = [
            name for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            raise WheelSiblingPinError(
                f"wheel has no single METADATA file: {wheel}"
            )
        message = Parser().parsestr(
            archive.read(metadata_files[0]).decode("utf-8")
        )
    return list(message.get_all("Requires-Dist") or [])


def _wheel_name(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        metadata_files = [
            name for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            raise WheelSiblingPinError(
                f"wheel has no single METADATA file: {wheel}"
            )
        message = Parser().parsestr(
            archive.read(metadata_files[0]).decode("utf-8")
        )
    name = message.get("Name")
    if not name:
        raise WheelSiblingPinError(f"wheel metadata missing Name: {wheel}")
    return canonicalize_name(name)
