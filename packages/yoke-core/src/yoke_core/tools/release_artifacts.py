"""Public distribution artifact layout for Yoke product releases.

The release tree hosts a private PEP 503 "simple" index alongside immutable
versioned wheels. Layout under ``output_root``::

    dist/releases/<version>/wheels/<wheel>.whl   immutable versioned wheels
    dist/releases/<version>/release-records.json per-wheel sha256/size record
    simple/index.html                            PEP 503 root (lists projects)
    simple/<project>/index.html                  per-project wheel links (#sha256=)
    dist/channels/<channel>.json                 mutable channel -> version pointer
    dist/install.py                              installer asset
    install                                      root POSIX install shim

The ``simple/`` index is served at ``<base_url>/simple/`` and is the value of
``index_url`` an installer passes to ``uv``/``pip``. Its per-project pages link
to the immutable versioned wheel URLs, so a single ``simple/`` tree spans every
retained version. Third-party dependencies are never hosted here; the installer
selects this as the first index and public PyPI as the explicit default index.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.parse import quote

from yoke_core.domain import json_helper
from yoke_core.tools import package_index


DIST_ROOT = "dist"
CHANNELS_DIR = "channels"
RELEASES_DIR = "releases"
WHEELS_DIR = "wheels"
SIMPLE_DIR = "simple"
RELEASE_RECORDS_FILENAME = "release-records.json"
INSTALLER_ASSET_DIR = Path("packaging") / "public-installer"
INSTALL_PY = "install.py"
INSTALL_SHIM = "install"


@dataclass(frozen=True)
class ReleasePaths:
    output_root: Path
    dist_root: Path
    release_dir: Path
    wheels_dir: Path
    simple_dir: Path
    channels_dir: Path
    release_records_path: Path
    install_py: Path
    install_shim: Path
    channel_path: Path


@dataclass(frozen=True)
class ReleaseBuild:
    version: str
    channel: str
    generated_at: str
    index_url: str
    paths: ReleasePaths
    release_records: list[dict[str, object]]
    channel_payload: dict[str, object]

    def to_json(self) -> dict[str, object]:
        return {
            "version": self.version,
            "channel": self.channel,
            "generated_at": self.generated_at,
            "index_url": self.index_url,
            "output_root": str(self.paths.output_root),
            "release_dir": str(self.paths.release_dir),
            "wheels_dir": str(self.paths.wheels_dir),
            "simple_dir": str(self.paths.simple_dir),
            "release_records_path": str(self.paths.release_records_path),
            "install_py": str(self.paths.install_py),
            "install": str(self.paths.install_shim),
            "channel_path": str(self.paths.channel_path),
        }


class ReleaseBuildError(RuntimeError):
    """Release artifact generation failed."""


def materialize_release_artifacts(
    *,
    records: Sequence[package_index.WheelRecord],
    output_root: Path,
    version: str,
    channel: str,
    base_url: str,
    generated_at: str,
    installer_asset_dir: Path,
) -> ReleaseBuild:
    paths = _prepare_release_paths(
        output_root=output_root,
        version=version,
        channel=channel,
    )
    _copy_wheels(records, paths.wheels_dir)
    wheel_records = package_index.read_wheel_records(paths.wheels_dir)
    release_base_url = _join_url(base_url, DIST_ROOT, RELEASES_DIR, version)
    wheels_base_url = _join_url(release_base_url, WHEELS_DIR)
    package_index.write_simple_index(
        index_dir=paths.simple_dir,
        records=wheel_records,
        wheel_base_url=wheels_base_url,
    )
    release_records = package_index.build_records_manifest(wheel_records)
    json_helper._dump_json(paths.release_records_path, release_records)
    _copy_installer_assets(installer_asset_dir, paths)
    index_url = _join_url(base_url, SIMPLE_DIR) + "/"
    channel_payload = _channel_payload(
        channel=channel,
        version=version,
        generated_at=generated_at,
        release_base_url=release_base_url,
        index_url=index_url,
    )
    json_helper._dump_json(paths.channel_path, channel_payload)
    return ReleaseBuild(
        version=version,
        channel=channel,
        generated_at=generated_at,
        index_url=index_url,
        paths=paths,
        release_records=release_records,
        channel_payload=channel_payload,
    )


def _prepare_release_paths(
    *,
    output_root: Path,
    version: str,
    channel: str,
) -> ReleasePaths:
    dist_root = output_root / DIST_ROOT
    release_dir = dist_root / RELEASES_DIR / version
    wheels_dir = release_dir / WHEELS_DIR
    simple_dir = output_root / SIMPLE_DIR
    channels_dir = dist_root / CHANNELS_DIR
    for path in (wheels_dir, simple_dir, channels_dir):
        path.mkdir(parents=True, exist_ok=True)
    return ReleasePaths(
        output_root=output_root,
        dist_root=dist_root,
        release_dir=release_dir,
        wheels_dir=wheels_dir,
        simple_dir=simple_dir,
        channels_dir=channels_dir,
        release_records_path=release_dir / RELEASE_RECORDS_FILENAME,
        install_py=dist_root / INSTALL_PY,
        install_shim=output_root / INSTALL_SHIM,
        channel_path=channels_dir / f"{channel}.json",
    )


def _copy_wheels(
    records: Sequence[package_index.WheelRecord],
    wheels_dir: Path,
) -> None:
    for record in records:
        shutil.copy2(record.source, wheels_dir / record.filename)


def _copy_installer_assets(asset_dir: Path, paths: ReleasePaths) -> None:
    install_py_source = asset_dir / INSTALL_PY
    install_shim_source = asset_dir / INSTALL_SHIM
    missing = [
        str(path)
        for path in (install_py_source, install_shim_source)
        if not path.is_file()
    ]
    if missing:
        raise ReleaseBuildError(
            "missing installer asset(s): " + ", ".join(missing)
        )
    shutil.copy2(install_py_source, paths.install_py)
    shutil.copy2(install_shim_source, paths.install_shim)


def _channel_payload(
    *,
    channel: str,
    version: str,
    generated_at: str,
    release_base_url: str,
    index_url: str,
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "channel": channel,
        "version": version,
        "generated_at": generated_at,
        "index_url": index_url,
        "release_base_url": release_base_url,
        "installer": {
            "python_url": _join_url(release_base_url, "..", "..", INSTALL_PY),
            "shell_url": _join_url(release_base_url, "..", "..", "..", INSTALL_SHIM),
        },
    }


def _join_url(base: str, *parts: str) -> str:
    value = base.rstrip("/")
    for part in parts:
        if part == "..":
            value = value.rsplit("/", 1)[0]
            continue
        value += "/" + _quote_segment(part.strip("/"))
    return value


def _quote_segment(value: str) -> str:
    return quote(value, safe="%")
