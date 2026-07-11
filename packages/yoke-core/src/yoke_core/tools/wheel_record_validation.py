"""Validate the integrity manifest embedded in a wheel archive."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import zipfile
from collections import Counter
from pathlib import Path


_RECORD_SIGNATURE_SUFFIXES = (".jws", ".p7s")
_MINIMUM_DIGEST_SIZE = hashlib.sha256().digest_size


class WheelRecordError(ValueError):
    """Raised when a wheel's archive members and RECORD disagree."""


def assert_wheel_record_valid(wheel: Path) -> None:
    """Fail unless RECORD securely covers every required archive file."""

    with zipfile.ZipFile(wheel) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        duplicates = sorted(
            name for name, count in Counter(names).items() if count > 1
        )
        if duplicates:
            raise WheelRecordError(
                f"{wheel.name}: duplicate archive member(s): "
                + ", ".join(duplicates)
            )

        metadata_arcname = _single_member(
            names, ".dist-info/METADATA", wheel
        )
        dist_info_dir = metadata_arcname.rsplit("/", 1)[0]
        wheel_arcname = dist_info_dir + "/WHEEL"
        record_arcname = dist_info_dir + "/RECORD"
        if _single_member(names, ".dist-info/WHEEL", wheel) != wheel_arcname:
            raise WheelRecordError(
                f"{wheel.name}: WHEEL is outside the METADATA dist-info directory"
            )
        if _single_member(names, ".dist-info/RECORD", wheel) != record_arcname:
            raise WheelRecordError(
                f"{wheel.name}: RECORD is outside the METADATA dist-info directory"
            )
        payloads = {
            info.filename: archive.read(info)
            for info in infos
            if not info.is_dir()
        }

    rows = _read_record_rows(payloads[record_arcname], wheel)
    recorded: dict[str, tuple[str, str]] = {}
    for row_number, row in enumerate(rows, start=1):
        if len(row) != 3:
            raise WheelRecordError(
                f"{wheel.name}: RECORD row {row_number} must have three fields"
            )
        path, hash_value, size_value = row
        if not path:
            raise WheelRecordError(
                f"{wheel.name}: RECORD row {row_number} has an empty path"
            )
        if path in recorded:
            raise WheelRecordError(
                f"{wheel.name}: duplicate RECORD row for {path}"
            )
        recorded[path] = (hash_value, size_value)

    signature_names = {
        record_arcname + suffix for suffix in _RECORD_SIGNATURE_SUFFIXES
    }
    expected_names = set(payloads) - signature_names
    missing = sorted(expected_names - set(recorded))
    extra = sorted(set(recorded) - expected_names)
    if missing or extra:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise WheelRecordError(
            f"{wheel.name}: RECORD file list mismatch: " + "; ".join(details)
        )

    for path in sorted(expected_names):
        hash_value, size_value = recorded[path]
        if path == record_arcname:
            if hash_value or size_value:
                raise WheelRecordError(
                    f"{wheel.name}: RECORD must not hash or size itself"
                )
            continue
        _assert_secure_hash(
            wheel=wheel,
            path=path,
            data=payloads[path],
            hash_value=hash_value,
        )
        if not size_value:
            raise WheelRecordError(
                f"{wheel.name}: RECORD size is missing for {path}"
            )
        try:
            recorded_size = int(size_value)
        except ValueError as exc:
            raise WheelRecordError(
                f"{wheel.name}: RECORD size is invalid for {path}: {size_value}"
            ) from exc
        if recorded_size != len(payloads[path]):
            raise WheelRecordError(
                f"{wheel.name}: RECORD size mismatch for {path}"
            )


def has_record_signature(names: list[str], record_arcname: str) -> bool:
    """Return whether deprecated signature payloads accompany RECORD."""

    return any(
        record_arcname + suffix in names
        for suffix in _RECORD_SIGNATURE_SUFFIXES
    )


def _read_record_rows(raw: bytes, wheel: Path) -> list[list[str]]:
    try:
        text = raw.decode("utf-8")
        return list(csv.reader(io.StringIO(text, newline="")))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise WheelRecordError(
            f"{wheel.name}: RECORD is not valid UTF-8 CSV"
        ) from exc


def _assert_secure_hash(
    *,
    wheel: Path,
    path: str,
    data: bytes,
    hash_value: str,
) -> None:
    algorithm, separator, recorded_digest = hash_value.partition("=")
    if (
        not separator
        or algorithm not in hashlib.algorithms_guaranteed
        or algorithm in {"md5", "sha1"}
    ):
        raise WheelRecordError(
            f"{wheel.name}: RECORD hash algorithm is invalid for {path}"
        )
    digest = hashlib.new(algorithm)
    if digest.digest_size < _MINIMUM_DIGEST_SIZE:
        raise WheelRecordError(
            f"{wheel.name}: RECORD hash is weaker than sha256 for {path}"
        )
    digest.update(data)
    expected_digest = (
        base64.urlsafe_b64encode(digest.digest()).rstrip(b"=").decode("ascii")
    )
    if recorded_digest != expected_digest:
        raise WheelRecordError(
            f"{wheel.name}: RECORD hash mismatch for {path}"
        )


def _single_member(names: list[str], suffix: str, wheel: Path) -> str:
    matches = [name for name in names if name.endswith(suffix)]
    if len(matches) != 1:
        raise WheelRecordError(
            f"{wheel.name}: archive has no single {suffix.rsplit('/', 1)[-1]}"
        )
    return matches[0]
