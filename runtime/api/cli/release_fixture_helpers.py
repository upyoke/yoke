"""Test fixture builders for public distribution release directories."""

from __future__ import annotations

import base64
import hashlib
import zipfile
from pathlib import Path

from yoke_core.tools import (
    migration_history_release_artifact,
    package_index,
    release_artifacts,
)

SOURCE_COMMIT = "a" * 40


def sample_release(
    wheels_dir: Path,
    *,
    version: str = "0.2.0",
    sibling_specifier: str | None = None,
) -> tuple[list[dict[str, object]], list[package_index.WheelRecord]]:
    """Write product wheels with optionally overridden sibling pins."""
    specifier = f"=={version}" if sibling_specifier is None else sibling_specifier
    for name in package_index.PRODUCT_PACKAGE_NAMES:
        dist = name.replace("-", "_")
        lines = [
            "Metadata-Version: 2.1",
            f"Name: {name}",
            f"Version: {version}",
        ]
        lines += [
            f"Requires-Dist: {dep}{specifier}"
            for dep in package_index.PRODUCT_SIBLING_DEPENDENCIES[name]
        ]
        metadata = ("\n".join(lines) + "\n").encode("utf-8")
        wheel_metadata = (
            b"Wheel-Version: 1.0\nGenerator: test\n"
            b"Root-Is-Purelib: true\nTag: py3-none-any\n"
        )
        dist_info = f"{dist}-{version}.dist-info"
        files = {
            f"{dist_info}/METADATA": metadata,
            f"{dist_info}/WHEEL": wheel_metadata,
        }
        if name == "yoke-core":
            files["yoke_core/domain/migrations/0001_test_entry.py"] = (
                b"def apply(conn):\n    pass\n"
            )
        record_arcname = f"{dist_info}/RECORD"
        record_lines = [
            f"{arcname},{_wheel_record_hash(data)},{len(data)}"
            for arcname, data in files.items()
        ]
        record_lines.append(f"{record_arcname},,")
        files[record_arcname] = ("\n".join(record_lines) + "\n").encode("utf-8")
        with zipfile.ZipFile(
            wheels_dir / f"{dist}-{version}-py3-none-any.whl", "w"
        ) as archive:
            for arcname, data in files.items():
                archive.writestr(arcname, data)
    wheel_records = package_index.read_wheel_records(wheels_dir)
    records = package_index.build_records_manifest(wheel_records)
    manifest = migration_history_release_artifact.write_release_manifest(
        wheels_dir.parent / release_artifacts.MIGRATION_HISTORY_MANIFEST_FILENAME,
        wheel_records,
        source_commit=SOURCE_COMMIT,
    )
    migration_history_release_artifact.write_release_evidence(
        wheels_dir.parent
        / release_artifacts.MIGRATION_HISTORY_RELEASE_EVIDENCE_FILENAME,
        manifest,
    )
    return records, wheel_records


def _wheel_record_hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"sha256={encoded}"
