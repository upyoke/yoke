"""Fail-closed validation for a materialized product release directory."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import unquote

from yoke_core.tools import (
    package_index,
    product_release_version,
    wheel_record_validation,
    wheel_sibling_pins,
)


_LINK_RE = re.compile(
    r'<a\s+href=(?P<q>["\'])(?P<href>.*?)(?P=q)\s*>(?P<text>[^<]*)</a>',
    re.IGNORECASE,
)


def validate_product_release_records(
    records: Sequence[Mapping[str, object]],
) -> None:
    """Require exactly one internally consistent record per product."""

    wheel_records = [
        package_index.WheelRecord(
            name=str(record["name"]),
            version=str(record["version"]),
            filename=str(record["filename"]),
            sha256=str(record["sha256"]),
            size=int(record["size"]),
            source=Path(str(record["filename"])),
        )
        for record in records
    ]
    package_index.validate_records(wheel_records)
    names = [record.canonical_name for record in wheel_records]
    expected_names = set(package_index.PRODUCT_PACKAGE_NAMES)
    if len(names) != len(expected_names) or set(names) != expected_names:
        raise ValueError(
            "release records must contain exactly one record per product"
        )
    filenames = [record.filename for record in wheel_records]
    if len(filenames) != len(set(filenames)):
        raise ValueError("release records contain duplicate filenames")
    for source, record in zip(records, wheel_records):
        if str(source["project"]) != record.project_name:
            raise ValueError(
                f"{record.filename} project does not match its package name"
            )


def validate_wheel_records_match(
    records: Sequence[Mapping[str, object]], wheels_dir: Path
) -> None:
    """Cross-check release records against embedded wheel identities."""

    actual_records = package_index.read_wheel_records(wheels_dir)
    actual_by_filename = {
        record.filename: record.to_record_entry()
        for record in actual_records
    }
    expected_by_filename = {
        str(record["filename"]): {
            "project": str(record["project"]),
            "name": str(record["name"]),
            "version": str(record["version"]),
            "filename": str(record["filename"]),
            "sha256": str(record["sha256"]),
            "size": int(record["size"]),
        }
        for record in records
    }
    if set(actual_by_filename) != set(expected_by_filename):
        raise ValueError(
            "release wheel files do not exactly match release records"
        )
    for filename, expected in expected_by_filename.items():
        if actual_by_filename[filename] != expected:
            raise ValueError(
                f"{filename} release record does not match wheel metadata"
            )


def validate_sibling_pins(
    records: Sequence[Mapping[str, object]], wheels_dir: Path
) -> None:
    """Require an unforgeable shared version and the exact sibling DAG."""

    versions = {str(record["version"]) for record in records}
    if len(versions) != 1:
        raise ValueError(
            "release records span multiple versions: "
            + ", ".join(sorted(versions))
        )
    expected_version = versions.pop()
    product_release_version.assert_public_index_unforgeable(expected_version)
    for record in records:
        wheel = wheels_dir / str(record["filename"])
        wheel_record_validation.assert_wheel_record_valid(wheel)
        wheel_sibling_pins.assert_wheel_siblings_pinned(
            wheel,
            package_index.PRODUCT_PACKAGE_NAMES,
            expected_version,
        )


def validate_simple_index(
    simple_dir: Path,
    by_filename: Mapping[str, dict[str, object]],
) -> None:
    """Require simple-index links for every recorded wheel and digest."""

    root_index = simple_dir / package_index.ROOT_INDEX_FILENAME
    if not root_index.is_file():
        raise ValueError(f"simple index is missing: {root_index}")
    root_html = root_index.read_text(encoding="utf-8")
    projects = {str(record["project"]) for record in by_filename.values()}
    linked: dict[str, str] = {}
    for project in projects:
        if f'href="{project}/"' not in root_html:
            raise ValueError(f"simple root index missing project link: {project}")
        project_index = simple_dir / project / package_index.ROOT_INDEX_FILENAME
        if not project_index.is_file():
            raise ValueError(f"simple project index is missing: {project_index}")
        for match in _LINK_RE.finditer(project_index.read_text(encoding="utf-8")):
            url, _, fragment = match.group("href").partition("#sha256=")
            if not fragment:
                raise ValueError(f"simple index wheel link missing sha256: {url}")
            linked[unquote(url.rstrip("/").rsplit("/", 1)[-1])] = fragment
    for filename, record in by_filename.items():
        sha = linked.get(filename)
        if sha is None:
            raise ValueError(f"simple index does not list wheel: {filename}")
        if sha != str(record["sha256"]):
            raise ValueError(f"simple index sha256 mismatch for {filename}")
