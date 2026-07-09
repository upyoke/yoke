"""Emit exact pip constraints for local wheels in a wheelhouse."""

from __future__ import annotations

import argparse
import email.parser
import sys
import zipfile
from pathlib import Path


def wheel_metadata(path: Path) -> dict[str, str]:
    """Return the wheel's core metadata fields."""
    with zipfile.ZipFile(path) as archive:
        metadata_path = next(
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        )
        payload = email.parser.Parser().parsestr(
            archive.read(metadata_path).decode("utf-8")
        )
    return {key: str(value) for key, value in payload.items()}


def constraints_for_wheelhouse(
    wheelhouse: Path, package_names: list[str]
) -> list[str]:
    """Return ``Name==Version`` rows for the requested wheelhouse packages."""
    requested = [_normalize(name) for name in package_names]
    found: dict[str, tuple[str, str]] = {}
    for wheel in sorted(wheelhouse.glob("*.whl")):
        metadata = wheel_metadata(wheel)
        name = metadata.get("Name", "")
        version = metadata.get("Version", "")
        normalized = _normalize(name)
        if normalized in requested and version:
            found[normalized] = (name, version)

    missing = [name for name in requested if name not in found]
    if missing:
        raise ValueError(
            "wheelhouse is missing local wheel(s): " + ", ".join(missing)
        )

    return [
        f"{found[name][0]}=={found[name][1]}"
        for name in requested
    ]


def _normalize(name: str) -> str:
    return name.replace("_", "-").lower()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit exact constraints for local wheels."
    )
    parser.add_argument("wheelhouse")
    parser.add_argument("packages", nargs="+")
    args = parser.parse_args(argv)

    try:
        rows = constraints_for_wheelhouse(
            Path(args.wheelhouse), list(args.packages)
        )
    except (OSError, ValueError, zipfile.BadZipFile, StopIteration) as exc:
        print(f"local-wheel-constraints: {exc}", file=sys.stderr)
        return 1

    for row in rows:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
