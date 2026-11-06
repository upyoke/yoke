# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import base64

import hashlib

import zipfile

from email.parser import Parser

from pathlib import Path

import pytest

from yoke_core.tools import package_index, wheel_sibling_pins

_DATE_TIME = (1980, 1, 1, 0, 0, 0)


def _record_hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _write_wheel(
    wheelhouse: Path,
    *,
    name: str,
    version: str,
    requires_dist: tuple[str, ...] = (),
    compress_type: int = zipfile.ZIP_DEFLATED,
    archive_comment: bytes = b"",
) -> Path:
    """Emit a synthetic wheel with METADATA + WHEEL + a correct RECORD."""

    dist = name.replace("-", "_")
    dist_info = f"{dist}-{version}.dist-info"
    metadata_lines = [
        "Metadata-Version: 2.1",
        f"Name: {name}",
        f"Version: {version}",
    ]
    metadata_lines += [f"Requires-Dist: {entry}" for entry in requires_dist]
    metadata = ("\n".join(metadata_lines) + "\n").encode("utf-8")
    wheel_meta = (
        b"Wheel-Version: 1.0\nGenerator: test\n"
        b"Root-Is-Purelib: true\nTag: py3-none-any\n"
    )
    files = {
        f"{dist_info}/METADATA": metadata,
        f"{dist_info}/WHEEL": wheel_meta,
    }
    record_arcname = f"{dist_info}/RECORD"
    record_lines = [
        f"{arcname},{_record_hash(data)},{len(data)}" for arcname, data in files.items()
    ]
    record_lines.append(f"{record_arcname},,")
    files[record_arcname] = ("\n".join(record_lines) + "\n").encode("utf-8")

    path = wheelhouse / f"{dist}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.comment = archive_comment
        for arcname, data in files.items():
            info = zipfile.ZipInfo(arcname, date_time=_DATE_TIME)
            info.compress_type = compress_type
            archive.writestr(info, data)
    return path


def _build_wheelhouse(
    wheelhouse: Path,
    *,
    versions: dict[str, str] | None = None,
    core_requires: tuple[str, ...] | None = None,
    archive_comments: dict[str, bytes] | None = None,
) -> None:
    wheelhouse.mkdir(parents=True, exist_ok=True)
    for name in package_index.PRODUCT_PACKAGE_NAMES:
        version = (versions or {}).get(name, "0.2.0")
        if name == "yoke-core" and core_requires is not None:
            requires = core_requires
        else:
            requires = package_index.PRODUCT_SIBLING_DEPENDENCIES[name]
        _write_wheel(
            wheelhouse,
            name=name,
            version=version,
            requires_dist=requires,
            archive_comment=(archive_comments or {}).get(name, b""),
        )


def _requires_dist(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as archive:
        metadata_arcname = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        message = Parser().parsestr(archive.read(metadata_arcname).decode("utf-8"))
    return list(message.get_all("Requires-Dist") or [])


def _wheel(wheelhouse: Path, name: str, version: str = "0.2.0") -> Path:
    dist = name.replace("-", "_")
    return wheelhouse / f"{dist}-{version}-py3-none-any.whl"
