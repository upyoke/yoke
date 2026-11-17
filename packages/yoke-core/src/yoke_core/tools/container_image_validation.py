"""Validate every installed core module and its real project bundle once."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
from importlib.metadata import distribution
import io
from pathlib import Path
import sys
import zipfile

from yoke_core.tools.product_wheel_validation import verify_installed_boot


def verify_bundle():
    # Keep bundle imports behind the tracked complete-module import pass.
    from yoke_core.tools.container_bundle_validation import verify_project_bundle

    return verify_project_bundle()


def verify_installed_wheels(root: Path) -> None:
    """Compare wheel RECORD hashes with installed RECORDs and actual files.

    Installers add entry points and bytecode to RECORD, so compare the original
    hashed rows rather than the installer-owned RECORD file's bytes.
    """
    wheels = sorted(root.glob("*.whl"))
    if len(wheels) != 4:
        raise ValueError("installed_wheel_set_mismatch: supply all four product wheels")
    for path in wheels:
        with zipfile.ZipFile(path) as wheel:
            record = next(
                n for n in wheel.namelist() if n.endswith(".dist-info/RECORD")
            )
            metadata = next(
                n for n in wheel.namelist() if n.endswith(".dist-info/METADATA")
            )
            from email.parser import BytesParser

            name = BytesParser().parsebytes(wheel.read(metadata))["Name"]
            installed = distribution(name)
            rows = list(csv.reader(io.StringIO(wheel.read(record).decode())))
        try:
            installed_record = installed.locate_file(record).read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(
                f"installed_wheel_record_mismatch: {name} RECORD unavailable; rebuild from the verified wheels"
            ) from exc
        installed_rows = {
            row[0]: row[1:] for row in csv.reader(io.StringIO(installed_record))
        }
        checked = 0
        for filename, digest, size in rows:
            if not digest:
                continue
            content = installed.locate_file(filename).read_bytes()
            algorithm, expected = digest.split("=", 1)
            actual = (
                base64.urlsafe_b64encode(hashlib.new(algorithm, content).digest())
                .decode()
                .rstrip("=")
            )
            if (
                installed_rows.get(filename) != [digest, size]
                or actual != expected
                or len(content) != int(size)
            ):
                raise ValueError(
                    f"installed_wheel_record_mismatch: {name} {filename}; rebuild from the verified wheels"
                )
            checked += 1
        if not checked:
            raise ValueError(
                f"installed_wheel_record_empty: {name}; rebuild the product wheel"
            )
        print(f"Installed wheel RECORD verified: {path.name} ({checked} hashes)")


def main() -> int:
    failed = False
    for name, check in (
        ("installed core modules", verify_installed_boot),
        ("installed project bundle", verify_bundle),
    ):
        try:
            check()
        except (Exception, SystemExit) as exc:
            failed = True
            print(
                f"container_image_validation_failed: {name}: {exc}; "
                "fix the installed product and rebuild the image",
                file=sys.stderr,
            )
        else:
            print(f"container image validation passed: {name}")
    return int(failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheels", type=Path)
    args = parser.parse_args()
    if args.wheels:
        try:
            verify_installed_wheels(args.wheels)
        except (Exception, SystemExit) as exc:
            print(
                f"container_image_validation_failed: {exc}; rebuild from verified wheels",
                file=sys.stderr,
            )
            raise SystemExit(1)
    else:
        raise SystemExit(main())
