"""Render the Yoke product PEP 503 "simple" package index.

Yoke hosts a private PEP 503 index that lists only the product wheels
(``yoke-contracts``, ``yoke-cli``, ``yoke-harness``, ``yoke-core``) — the
engine ships on the channel like every other product wheel; safety comes from
the DSN authority boundary, not from keeping engine code off machines.
Third-party dependencies (pydantic, textual, pyfiglet, and their transitive
closure) are resolved by ``uv``/``pip`` from the explicit public PyPI default
and are never hosted here. The Yoke index remains first so product packages
cannot be shadowed. Each wheel link carries a ``#sha256=<hex>`` fragment so the
resolver verifies wheel integrity on download.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import re
import sys
import zipfile
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import quote

from packaging.utils import (
    canonicalize_name as canonicalize_package_name,
    parse_wheel_filename,
)
from packaging.version import Version


PRODUCT_SIBLING_DEPENDENCIES = {
    "yoke-contracts": (),
    "yoke-cli": ("yoke-contracts",),
    "yoke-harness": ("yoke-contracts", "yoke-cli"),
    "yoke-core": ("yoke-contracts", "yoke-cli", "yoke-harness"),
}
PRODUCT_PACKAGE_NAMES = tuple(PRODUCT_SIBLING_DEPENDENCIES)
ROOT_INDEX_FILENAME = "index.html"

_NAME_NORMALIZE = re.compile(r"[-_.]+")


@dataclass(frozen=True)
class WheelRecord:
    name: str
    version: str
    filename: str
    sha256: str
    size: int
    source: Path

    @property
    def canonical_name(self) -> str:
        return canonical_name(self.name)

    @property
    def project_name(self) -> str:
        return normalize_project_name(self.name)

    def to_record_entry(self) -> dict[str, object]:
        """Per-wheel sha256/size record used by the publish-verify step."""

        return {
            "project": self.project_name,
            "name": self.name,
            "version": self.version,
            "filename": self.filename,
            "sha256": self.sha256,
            "size": self.size,
        }


def generate_index(
    *,
    wheel_dir: Path,
    index_dir: Path,
    wheel_base_url: str,
) -> dict[str, list[WheelRecord]]:
    """Render the PEP 503 root + per-project index pages from product wheels.

    ``wheel_base_url`` is the directory URL the wheel links resolve against; the
    rendered ``<a href>`` joins ``wheel_base_url`` + the wheel filename and
    appends ``#sha256=<hex>``. Only the product wheels are listed.
    """

    records = read_wheel_records(wheel_dir)
    validate_records(records)
    product_records = [
        record for record in records if record.canonical_name in PRODUCT_PACKAGE_NAMES
    ]
    write_simple_index(
        index_dir=index_dir,
        records=product_records,
        wheel_base_url=wheel_base_url,
    )
    by_project: dict[str, list[WheelRecord]] = {}
    for record in product_records:
        by_project.setdefault(record.project_name, []).append(record)
    return by_project


def write_simple_index(
    *,
    index_dir: Path,
    records: Sequence[WheelRecord],
    wheel_base_url: str,
) -> None:
    """Write ``index_dir/index.html`` (root) and ``index_dir/<project>/index.html``."""

    by_project: dict[str, list[WheelRecord]] = {}
    for record in records:
        by_project.setdefault(record.project_name, []).append(record)
    index_dir.mkdir(parents=True, exist_ok=True)
    _write_root_index(index_dir, sorted(by_project))
    for project, project_records in by_project.items():
        project_dir = index_dir / project
        project_dir.mkdir(parents=True, exist_ok=True)
        _write_project_index(
            project_dir=project_dir,
            project=project,
            records=sorted(project_records, key=lambda record: record.filename),
            wheel_base_url=wheel_base_url,
        )


def build_records_manifest(
    records: Iterable[WheelRecord],
) -> list[dict[str, object]]:
    """Stable per-wheel record list (project/sha256/size) for publish-verify."""

    product_records = [
        record
        for record in records
        if record.canonical_name in PRODUCT_PACKAGE_NAMES
    ]
    return [
        record.to_record_entry()
        for record in sorted(
            product_records,
            key=lambda record: (record.project_name, record.filename),
        )
    ]


def read_wheel_records(wheel_dir: Path) -> list[WheelRecord]:
    wheels = sorted(wheel_dir.glob("*.whl"))
    if not wheels:
        raise ValueError(f"no wheel files found in {wheel_dir}")
    return [_read_wheel_record(path) for path in wheels]


def validate_records(records: Sequence[WheelRecord]) -> None:
    by_name: dict[str, list[WheelRecord]] = {}
    for record in records:
        by_name.setdefault(record.canonical_name, []).append(record)

    missing = [name for name in PRODUCT_PACKAGE_NAMES if name not in by_name]
    if missing:
        raise ValueError("missing product wheel(s): " + ", ".join(missing))


def canonical_name(name: str) -> str:
    return name.lower().replace("_", "-")


def normalize_project_name(name: str) -> str:
    """PEP 503 normalized project name: lowercase, runs of [-_.] -> single '-'."""

    return _NAME_NORMALIZE.sub("-", name).lower()


def _write_root_index(index_dir: Path, projects: Sequence[str]) -> None:
    lines = [
        "<!DOCTYPE html>",
        '<html><head><meta name="pypi:repository-version" content="1.0">'
        "<title>Yoke product index</title></head><body>",
    ]
    for project in projects:
        escaped = html.escape(project)
        href = quote(project, safe="") + "/"
        lines.append(f'<a href="{href}">{escaped}</a>')
    lines.extend(["</body></html>", ""])
    (index_dir / ROOT_INDEX_FILENAME).write_text("\n".join(lines), encoding="utf-8")


def _write_project_index(
    *,
    project_dir: Path,
    project: str,
    records: Sequence[WheelRecord],
    wheel_base_url: str,
) -> None:
    title = html.escape(f"Links for {project}")
    lines = [
        "<!DOCTYPE html>",
        '<html><head><meta name="pypi:repository-version" content="1.0">'
        f"<title>{title}</title></head><body>",
        f"<h1>{title}</h1>",
    ]
    base = wheel_base_url.rstrip("/")
    for record in records:
        wheel_url = base + "/" + quote(record.filename, safe="%")
        href = f"{wheel_url}#sha256={record.sha256}"
        text = html.escape(record.filename)
        lines.append(f'<a href="{html.escape(href, quote=True)}">{text}</a>')
    lines.extend(["</body></html>", ""])
    (project_dir / ROOT_INDEX_FILENAME).write_text("\n".join(lines), encoding="utf-8")


def _read_wheel_record(path: Path) -> WheelRecord:
    metadata, metadata_arcname = _wheel_metadata(path)
    name = metadata.get("Name")
    version = metadata.get("Version")
    if not name or not version:
        raise ValueError(f"wheel metadata missing Name/Version: {path}")
    _validate_wheel_identity(
        path=path,
        metadata_arcname=metadata_arcname,
        name=name,
        version=version,
    )
    data = path.read_bytes()
    return WheelRecord(
        name=canonical_name(name),
        version=version,
        filename=path.name,
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        source=path,
    )


def _wheel_metadata(path: Path) -> tuple[dict[str, str], str]:
    with zipfile.ZipFile(path) as wheel:
        metadata_files = [
            name for name in wheel.namelist()
            if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            raise ValueError(f"wheel has no single METADATA file: {path}")
        message = Parser().parsestr(
            wheel.read(metadata_files[0]).decode("utf-8")
        )
    return (
        {key: value for key, value in message.items()},
        metadata_files[0],
    )


def _validate_wheel_identity(
    *,
    path: Path,
    metadata_arcname: str,
    name: str,
    version: str,
) -> None:
    filename_name, filename_version, _, _ = parse_wheel_filename(path.name)
    metadata_name = canonicalize_package_name(name)
    metadata_version = Version(version)
    if metadata_name != filename_name or metadata_version != filename_version:
        raise ValueError(
            f"wheel filename identity does not match METADATA: {path}"
        )
    dist_info_name = str(metadata_name).replace("-", "_")
    expected_metadata_arcname = (
        f"{dist_info_name}-{metadata_version}.dist-info/METADATA"
    )
    if metadata_arcname != expected_metadata_arcname:
        raise ValueError(
            f"wheel dist-info identity does not match METADATA: {path}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Render the Yoke product PEP 503 simple index from product wheels."
        ),
    )
    parser.add_argument("wheel_dir", type=Path)
    parser.add_argument("index_dir", type=Path)
    parser.add_argument(
        "--wheel-base-url",
        required=True,
        help="Directory URL the wheel links resolve against.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        generate_index(
            wheel_dir=args.wheel_dir,
            index_dir=args.index_dir,
            wheel_base_url=args.wheel_base_url,
        )
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"package-index: {exc}", file=sys.stderr)
        return 1
    print(str(args.index_dir / ROOT_INDEX_FILENAME))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
