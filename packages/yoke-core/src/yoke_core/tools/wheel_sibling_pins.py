"""Pin product-sibling ``Requires-Dist`` entries in built product wheels.

The four product wheels (``yoke-contracts``, ``yoke-cli``, ``yoke-harness``,
``yoke-core``) declare bare sibling dependencies in their static
``[project.dependencies]`` so editable/source-dev installs resolve the siblings
already present on ``site-packages``. ``uv build`` copies those bare names
verbatim into wheel ``Requires-Dist`` metadata. A bare requirement lets a
pip-based install resolve a *same-named* package from a public index (pip has no
index priority — the highest version wins), so a name-squatting stranger on PyPI
would be pulled in ahead of the real lockstep sibling.

This rewriter closes that gap at wheelhouse-build time: it reads each product
wheel's own version, asserts every product wheel shares one version (the
earliest lockstep guard), requires the exact unconditional product dependency
graph, and rewrites each product-sibling ``Requires-Dist`` entry from its bare
form to ``<name>==<shared version>``. The built wheels then declare exact pins
so a pip-based install can only resolve the real siblings from the same channel.
Release validation additionally requires the shared version to carry a PEP 440
local segment, which cannot be reproduced by a package on the public index.

Editing wheel metadata means the wheel's ``RECORD`` (which carries a
``sha256=...,<size>`` row per file) must be updated for the rewritten
``METADATA`` and the zip repacked. The repack preserves each original
``ZipInfo`` (filename, date_time, compress_type, external_attr) and only
substitutes the ``METADATA`` and ``RECORD`` payloads, so artifacts stay
byte-reproducible under an exported ``SOURCE_DATE_EPOCH``.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Iterable

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

from yoke_core.tools import package_index, wheel_record_validation
from yoke_core.tools.wheel_sibling_contract import (
    WheelSiblingPinError,
    assert_wheel_sibling_contract as _assert_wheel_sibling_contract,
    assert_wheel_siblings_pinned,
    normalize_requires_dist,
    wheel_requires_dist as wheel_requires_dist,
)


def pin_wheelhouse_product_siblings(
    wheelhouse: Path, product_names: Iterable[str]
) -> str:
    """Rewrite product wheels' sibling ``Requires-Dist`` to exact lockstep pins.

    Reads every product wheel's own version, asserts they share exactly one
    version (raising on skew — the earliest lockstep guard), rewrites each
    product-sibling requirement to ``==<shared version>``, and returns that
    shared version. Product wheels without sibling requirements (or already
    correctly pinned) are left byte-identical. A sibling already pinned to a
    different version raises rather than being silently repointed.
    """

    product_canonical = _canonical_set(product_names)
    wheels_by_name: dict[str, list[Path]] = {}
    for record in package_index.read_wheel_records(wheelhouse):
        if record.canonical_name in product_canonical:
            wheels_by_name.setdefault(record.canonical_name, []).append(
                record.source
            )
    missing = sorted(product_canonical - set(wheels_by_name))
    duplicates = sorted(
        name for name, wheels in wheels_by_name.items() if len(wheels) != 1
    )
    if missing or duplicates:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if duplicates:
            details.append("multiple wheels for " + ", ".join(duplicates))
        raise WheelSiblingPinError(
            "wheelhouse must contain exactly one wheel per product: "
            + "; ".join(details)
        )
    product_wheels = [
        wheels_by_name[name][0] for name in sorted(product_canonical)
    ]

    versions = {_wheel_version(wheel) for wheel in product_wheels}
    if len(versions) != 1:
        raise WheelSiblingPinError(
            "product wheels must share one version: " + ", ".join(sorted(versions))
        )
    version = versions.pop()
    for wheel in product_wheels:
        wheel_record_validation.assert_wheel_record_valid(wheel)
        _assert_wheel_unsigned(wheel)
        _assert_wheel_sibling_contract(
            wheel,
            product_canonical,
            version,
            require_pins=False,
        )
    staged: list[tuple[Path, Path]] = []
    try:
        for wheel in product_wheels:
            candidate = _stage_one_wheel(wheel, product_canonical, version)
            if candidate is not None:
                staged.append((candidate, wheel))
            else:
                candidate = wheel
            wheel_record_validation.assert_wheel_record_valid(candidate)
            assert_wheel_siblings_pinned(
                candidate, product_canonical, version
            )
        for candidate, wheel in staged:
            candidate.replace(wheel)
    finally:
        for candidate, _ in staged:
            candidate.unlink(missing_ok=True)
    return version


def _assert_wheel_unsigned(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        metadata_arcname = _single_metadata_arcname(archive, wheel)
        record_arcname = _dist_info_dir(metadata_arcname) + "/RECORD"
        if wheel_record_validation.has_record_signature(
            archive.namelist(), record_arcname
        ):
            raise WheelSiblingPinError(
                f"{wheel.name}: signed product wheels are not supported"
            )


def _stage_one_wheel(
    wheel: Path, product_canonical: set[str], version: str
) -> Path | None:
    with zipfile.ZipFile(wheel) as archive:
        metadata_arcname = _single_metadata_arcname(archive, wheel)
        metadata_raw = archive.read(metadata_arcname)
        new_metadata, changed = _rewrite_metadata(
            metadata_raw, product_canonical, version
        )
        if not changed:
            # Nothing to pin (no siblings, or already pinned): leave the wheel
            # byte-identical and never touch its RECORD.
            return None
        record_arcname = _dist_info_dir(metadata_arcname) + "/RECORD"
        if wheel_record_validation.has_record_signature(
            archive.namelist(), record_arcname
        ):
            raise WheelSiblingPinError(
                f"{wheel.name}: cannot rewrite a signed wheel"
            )
        record_raw = archive.read(record_arcname)
        infos = archive.infolist()
        payloads = {info.filename: archive.read(info.filename) for info in infos}
        comment = archive.comment

    new_record = _rewrite_record(
        record_raw,
        metadata_arcname,
        _record_hash(new_metadata),
        len(new_metadata),
    )
    payloads[metadata_arcname] = new_metadata
    payloads[record_arcname] = new_record
    return _repack(wheel, infos, payloads, comment)


def _rewrite_metadata(
    raw: bytes, product_canonical: set[str], version: str
) -> tuple[bytes, bool]:
    """Rewrite bare product-sibling ``Requires-Dist`` header lines in place.

    Only the RFC822 header block (before the first blank line) is scanned so a
    ``Requires-Dist:`` occurrence inside the long-description body is never
    touched. Line endings are preserved so the payload stays byte-stable.
    """

    text = raw.decode("utf-8")
    lines = text.splitlines(keepends=True)
    line_ending = "\r\n" if "\r\n" in text else "\n"
    out: list[str] = []
    changed = False
    index = 0
    while index < len(lines):
        first = lines[index].rstrip("\r\n")
        if first == "":
            out.extend(lines[index:])
            break
        field_lines = [lines[index]]
        index += 1
        while index < len(lines) and lines[index].startswith((" ", "\t")):
            field_lines.append(lines[index])
            index += 1
        if first.lower().startswith("requires-dist:"):
            parsed = Parser().parsestr("".join(field_lines))
            values = parsed.get_all("Requires-Dist") or []
            if len(values) != 1:
                raise WheelSiblingPinError(
                    "Requires-Dist header could not be parsed"
                )
            value = normalize_requires_dist(values[0])
            pinned = _maybe_pin_requirement(value, product_canonical, version)
            if pinned is not None and pinned != value:
                out.append(f"Requires-Dist: {pinned}{line_ending}")
                changed = True
                continue
        out.extend(field_lines)
    return "".join(out).encode("utf-8"), changed


def _maybe_pin_requirement(
    value: str, product_canonical: set[str], version: str
) -> str | None:
    """Return the pinned requirement string, or ``None`` when unchanged.

    Non-product requirements return ``None`` (leave untouched). A product
    sibling already pinned to ``version`` returns its input unchanged. A product
    sibling pinned to a different version raises.
    """

    requirement = Requirement(value)
    if canonicalize_name(requirement.name) not in product_canonical:
        return None
    if requirement.url is not None:
        raise WheelSiblingPinError(
            f"product sibling '{requirement.name}' must not use a direct URL"
        )
    existing = {str(spec) for spec in requirement.specifier}
    target = f"=={version}"
    if existing == {target}:
        return value
    if existing:
        raise WheelSiblingPinError(
            f"product sibling '{requirement.name}' is pinned to "
            f"{', '.join(sorted(existing))}, expected {target}"
        )
    requirement.specifier = SpecifierSet(target)
    return str(requirement)


def _rewrite_record(
    raw: bytes, metadata_arcname: str, new_hash: str, new_size: int
) -> bytes:
    """Update the ``METADATA`` row (hash + size) of a wheel ``RECORD``."""

    text = raw.decode("utf-8")
    rows = list(csv.reader(io.StringIO(text, newline="")))
    found = False
    for row in rows:
        if len(row) == 3 and row[0] == metadata_arcname:
            row[1:] = [new_hash, str(new_size)]
            found = True
    if not found:
        raise WheelSiblingPinError(
            f"RECORD is missing a METADATA row for {metadata_arcname}"
        )
    line_ending = "\r\n" if "\r\n" in text else "\n"
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator=line_ending).writerows(rows)
    return output.getvalue().encode("utf-8")


def _repack(
    wheel: Path,
    infos: list[zipfile.ZipInfo],
    payloads: dict[str, bytes],
    comment: bytes,
) -> Path:
    """Rewrite the wheel zip while preserving entry and archive metadata."""

    tmp = wheel.with_name(wheel.name + ".pin.tmp")
    with zipfile.ZipFile(tmp, "w") as archive:
        archive.comment = comment
        for info in infos:
            archive.writestr(info, payloads[info.filename])
    return tmp


def _record_hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"sha256={encoded}"


def _single_metadata_arcname(archive: zipfile.ZipFile, wheel: Path) -> str:
    names = [
        name
        for name in archive.namelist()
        if name.endswith(".dist-info/METADATA")
    ]
    if len(names) != 1:
        raise WheelSiblingPinError(f"wheel has no single METADATA file: {wheel}")
    return names[0]


def _dist_info_dir(metadata_arcname: str) -> str:
    return metadata_arcname.rsplit("/", 1)[0]


def _canonical_set(names: Iterable[str]) -> set[str]:
    return {canonicalize_name(name) for name in names}


def _wheel_version(wheel: Path) -> str:
    return _wheel_metadata(wheel)["Version"]


def _wheel_metadata(wheel: Path) -> dict[str, str]:
    with zipfile.ZipFile(wheel) as archive:
        metadata_arcname = _single_metadata_arcname(archive, wheel)
        message = Parser().parsestr(
            archive.read(metadata_arcname).decode("utf-8")
        )
    name = message.get("Name")
    version = message.get("Version")
    if not name or not version:
        raise WheelSiblingPinError(f"wheel metadata missing Name/Version: {wheel}")
    return {"Name": name, "Version": version}
