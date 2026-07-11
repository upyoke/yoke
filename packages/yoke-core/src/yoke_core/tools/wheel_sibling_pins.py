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
earliest lockstep guard), and rewrites each product-sibling ``Requires-Dist``
entry from its bare form to ``<name>==<shared version>`` while preserving any
environment markers or extras. The built wheels then declare exact pins so a
pip-based install can only ever resolve the real siblings from the same channel.

Editing wheel metadata means the wheel's ``RECORD`` (which carries a
``sha256=...,<size>`` row per file) must be updated for the rewritten
``METADATA`` and the zip repacked. The repack preserves each original
``ZipInfo`` (filename, date_time, compress_type, external_attr) and only
substitutes the ``METADATA`` and ``RECORD`` payloads, so artifacts stay
byte-reproducible under an exported ``SOURCE_DATE_EPOCH``.
"""

from __future__ import annotations

import base64
import hashlib
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Iterable

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name


class WheelSiblingPinError(ValueError):
    """Raised when product wheels cannot be pinned to one shared version."""


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
    product_wheels = [
        wheel
        for wheel in sorted(wheelhouse.glob("*.whl"))
        if _wheel_name(wheel) in product_canonical
    ]
    if not product_wheels:
        raise WheelSiblingPinError(f"no product wheels found in {wheelhouse}")

    versions = {_wheel_version(wheel) for wheel in product_wheels}
    if len(versions) != 1:
        raise WheelSiblingPinError(
            "product wheels must share one version: " + ", ".join(sorted(versions))
        )
    version = versions.pop()
    for wheel in product_wheels:
        _pin_one_wheel(wheel, product_canonical, version)
    return version


def assert_wheel_siblings_pinned(
    wheel: Path, product_names: Iterable[str], expected_version: str
) -> None:
    """Fail unless every product-sibling ``Requires-Dist`` pins ``expected_version``.

    Non-product requirements are ignored. A product sibling whose specifier is
    not exactly ``=={expected_version}`` (bare, or pinned to another version)
    raises :class:`WheelSiblingPinError`.
    """

    product_canonical = _canonical_set(product_names)
    target = {f"=={expected_version}"}
    for raw in wheel_requires_dist(wheel):
        requirement = Requirement(raw)
        if canonicalize_name(requirement.name) not in product_canonical:
            continue
        if {str(spec) for spec in requirement.specifier} != target:
            raise WheelSiblingPinError(
                f"{wheel.name}: product sibling '{requirement.name}' must be "
                f"pinned to =={expected_version}, found '{raw.strip()}'"
            )


def wheel_requires_dist(wheel: Path) -> list[str]:
    """Return a wheel's ``Requires-Dist`` values from its ``dist-info`` METADATA."""

    with zipfile.ZipFile(wheel) as archive:
        metadata_arcname = _single_metadata_arcname(archive, wheel)
        message = Parser().parsestr(
            archive.read(metadata_arcname).decode("utf-8")
        )
    return list(message.get_all("Requires-Dist") or [])


def _pin_one_wheel(
    wheel: Path, product_canonical: set[str], version: str
) -> None:
    with zipfile.ZipFile(wheel) as archive:
        metadata_arcname = _single_metadata_arcname(archive, wheel)
        metadata_raw = archive.read(metadata_arcname)
        new_metadata, changed = _rewrite_metadata(
            metadata_raw, product_canonical, version
        )
        if not changed:
            # Nothing to pin (no siblings, or already pinned): leave the wheel
            # byte-identical and never touch its RECORD.
            return
        record_arcname = _dist_info_dir(metadata_arcname) + "/RECORD"
        record_raw = archive.read(record_arcname)
        infos = archive.infolist()
        payloads = {info.filename: archive.read(info.filename) for info in infos}

    new_record = _rewrite_record(
        record_raw,
        metadata_arcname,
        _record_hash(new_metadata),
        len(new_metadata),
    )
    payloads[metadata_arcname] = new_metadata
    payloads[record_arcname] = new_record
    _repack(wheel, infos, payloads)


def _rewrite_metadata(
    raw: bytes, product_canonical: set[str], version: str
) -> tuple[bytes, bool]:
    """Rewrite bare product-sibling ``Requires-Dist`` header lines in place.

    Only the RFC822 header block (before the first blank line) is scanned so a
    ``Requires-Dist:`` occurrence inside the long-description body is never
    touched. Line endings are preserved so the payload stays byte-stable.
    """

    lines = raw.decode("utf-8").splitlines(keepends=True)
    out: list[str] = []
    changed = False
    in_headers = True
    for line in lines:
        stripped = line.rstrip("\r\n")
        newline = line[len(stripped):]
        if in_headers and stripped == "":
            in_headers = False
            out.append(line)
            continue
        if in_headers and stripped.lower().startswith("requires-dist:"):
            value = stripped.partition(":")[2].strip()
            pinned = _maybe_pin_requirement(value, product_canonical, version)
            if pinned is not None and pinned != value:
                out.append(f"Requires-Dist: {pinned}{newline}")
                changed = True
                continue
        out.append(line)
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

    lines = raw.decode("utf-8").splitlines(keepends=True)
    out: list[str] = []
    found = False
    for line in lines:
        stripped = line.rstrip("\r\n")
        newline = line[len(stripped):]
        if stripped.startswith(metadata_arcname + ","):
            out.append(f"{metadata_arcname},{new_hash},{new_size}{newline}")
            found = True
        else:
            out.append(line)
    if not found:
        raise WheelSiblingPinError(
            f"RECORD is missing a METADATA row for {metadata_arcname}"
        )
    return "".join(out).encode("utf-8")


def _repack(
    wheel: Path, infos: list[zipfile.ZipInfo], payloads: dict[str, bytes]
) -> None:
    """Rewrite the wheel zip, reusing each original ``ZipInfo`` for reproducibility."""

    tmp = wheel.with_name(wheel.name + ".pin.tmp")
    with zipfile.ZipFile(tmp, "w") as archive:
        for info in infos:
            archive.writestr(info, payloads[info.filename])
    tmp.replace(wheel)


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


def _wheel_name(wheel: Path) -> str:
    return canonicalize_name(_wheel_metadata(wheel)["Name"])


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
