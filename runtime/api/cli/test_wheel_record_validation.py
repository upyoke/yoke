"""Wheel RECORD and embedded-identity integrity tests."""

from __future__ import annotations

import base64
import hashlib
import zipfile
from pathlib import Path

import pytest

from yoke_core.tools import package_index, wheel_record_validation


def _hash(data: bytes, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm, data).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"{algorithm}={encoded}"


def _wheel_files(
    *,
    name: str = "yoke-cli",
    version: str = "0.2.0+gabc123",
) -> tuple[str, dict[str, bytes]]:
    dist = name.replace("-", "_")
    dist_info = f"{dist}-{version}.dist-info"
    metadata = (
        "Metadata-Version: 2.1\n"
        f"Name: {name}\n"
        f"Version: {version}\n"
    ).encode("utf-8")
    wheel_metadata = (
        b"Wheel-Version: 1.0\nGenerator: test\n"
        b"Root-Is-Purelib: true\nTag: py3-none-any\n"
    )
    files = {
        f"{dist_info}/METADATA": metadata,
        f"{dist_info}/WHEEL": wheel_metadata,
    }
    record_arcname = f"{dist_info}/RECORD"
    record_lines = [
        f"{arcname},{_hash(data)},{len(data)}"
        for arcname, data in files.items()
    ]
    record_lines.append(f"{record_arcname},,")
    files[record_arcname] = (
        "\n".join(record_lines) + "\n"
    ).encode("utf-8")
    return f"{dist}-{version}-py3-none-any.whl", files


def _write_wheel(
    directory: Path,
    *,
    filename: str | None = None,
    files: dict[str, bytes] | None = None,
) -> Path:
    default_filename, default_files = _wheel_files()
    path = directory / (filename or default_filename)
    with zipfile.ZipFile(path, "w") as archive:
        for arcname, data in (files or default_files).items():
            archive.writestr(arcname, data)
    return path


def _replace_record(
    files: dict[str, bytes],
    transform: str,
) -> dict[str, bytes]:
    changed = dict(files)
    record_arcname = next(
        name for name in changed if name.endswith(".dist-info/RECORD")
    )
    lines = changed[record_arcname].decode("utf-8").splitlines()
    wheel_index = next(
        index for index, line in enumerate(lines)
        if ".dist-info/WHEEL," in line
    )
    if transform == "bad-hash":
        path, _, size = lines[wheel_index].split(",")
        lines[wheel_index] = f"{path},sha256=AAAA,{size}"
    elif transform == "weak-hash":
        wheel_arcname = lines[wheel_index].split(",", 1)[0]
        lines[wheel_index] = (
            f"{wheel_arcname},{_hash(changed[wheel_arcname], 'sha1')},"
            f"{len(changed[wheel_arcname])}"
        )
    elif transform == "bad-size":
        path, hash_value, _ = lines[wheel_index].split(",")
        lines[wheel_index] = f"{path},{hash_value},999"
    elif transform == "missing-row":
        lines.pop(wheel_index)
    elif transform == "duplicate-row":
        lines.append(lines[wheel_index])
    else:
        raise AssertionError(transform)
    changed[record_arcname] = ("\n".join(lines) + "\n").encode("utf-8")
    return changed


def test_valid_record_accepts_deprecated_unlisted_signature(tmp_path: Path) -> None:
    filename, files = _wheel_files()
    record_arcname = next(
        name for name in files if name.endswith(".dist-info/RECORD")
    )
    files[record_arcname + ".jws"] = b"deprecated signature"
    wheel = _write_wheel(tmp_path, filename=filename, files=files)

    wheel_record_validation.assert_wheel_record_valid(wheel)


@pytest.mark.parametrize(
    "transform",
    ["bad-hash", "weak-hash", "bad-size", "missing-row", "duplicate-row"],
)
def test_record_corruption_fails_closed(
    tmp_path: Path,
    transform: str,
) -> None:
    filename, files = _wheel_files()
    wheel = _write_wheel(
        tmp_path,
        filename=filename,
        files=_replace_record(files, transform),
    )

    with pytest.raises(wheel_record_validation.WheelRecordError, match="RECORD"):
        wheel_record_validation.assert_wheel_record_valid(wheel)


def test_duplicate_archive_member_fails_closed(tmp_path: Path) -> None:
    wheel = _write_wheel(tmp_path)
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(wheel, "a") as archive:
            wheel_arcname = next(
                name for name in archive.namelist()
                if name.endswith(".dist-info/WHEEL")
            )
            archive.writestr(wheel_arcname, b"replacement")

    with pytest.raises(
        wheel_record_validation.WheelRecordError,
        match="duplicate archive member",
    ):
        wheel_record_validation.assert_wheel_record_valid(wheel)


def test_wheel_metadata_filename_identity_must_match(tmp_path: Path) -> None:
    _, files = _wheel_files(version="0.2.0+old")
    _write_wheel(
        tmp_path,
        filename="yoke_cli-0.2.0+new-py3-none-any.whl",
        files=files,
    )

    with pytest.raises(ValueError, match="filename identity"):
        package_index.read_wheel_records(tmp_path)
