"""Unit tests for the product-wheel sibling Requires-Dist pinner."""

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
        f"{arcname},{_record_hash(data)},{len(data)}"
        for arcname, data in files.items()
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
            name for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        )
        message = Parser().parsestr(archive.read(metadata_arcname).decode("utf-8"))
    return list(message.get_all("Requires-Dist") or [])


def _wheel(wheelhouse: Path, name: str, version: str = "0.2.0") -> Path:
    dist = name.replace("-", "_")
    return wheelhouse / f"{dist}-{version}-py3-none-any.whl"


def test_bare_siblings_are_pinned(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    _build_wheelhouse(wheelhouse)

    version = wheel_sibling_pins.pin_wheelhouse_product_siblings(
        wheelhouse, package_index.PRODUCT_PACKAGE_NAMES
    )

    assert version == "0.2.0"
    assert sorted(_requires_dist(_wheel(wheelhouse, "yoke-core"))) == [
        "yoke-cli==0.2.0",
        "yoke-contracts==0.2.0",
        "yoke-harness==0.2.0",
    ]
    assert _requires_dist(_wheel(wheelhouse, "yoke-cli")) == ["yoke-contracts==0.2.0"]
    # yoke-contracts has no siblings and is left untouched.
    assert _requires_dist(_wheel(wheelhouse, "yoke-contracts")) == []


def test_non_sibling_requirements_untouched(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    _build_wheelhouse(
        wheelhouse,
        core_requires=(
            "pydantic>=2",
            "pyfiglet",
            "yoke-contracts",
            "yoke-cli",
            "yoke-harness",
        ),
    )

    wheel_sibling_pins.pin_wheelhouse_product_siblings(
        wheelhouse, package_index.PRODUCT_PACKAGE_NAMES
    )

    pinned = _requires_dist(_wheel(wheelhouse, "yoke-core"))
    assert "pydantic>=2" in pinned
    assert "pyfiglet" in pinned
    assert "yoke-cli==0.2.0" in pinned


def test_version_skew_fails(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    _build_wheelhouse(wheelhouse, versions={"yoke-harness": "0.3.0"})

    with pytest.raises(
        wheel_sibling_pins.WheelSiblingPinError, match="share one version"
    ):
        wheel_sibling_pins.pin_wheelhouse_product_siblings(
            wheelhouse, package_index.PRODUCT_PACKAGE_NAMES
        )


def test_missing_product_wheel_fails_before_rewrite(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    _build_wheelhouse(wheelhouse)
    cli = _wheel(wheelhouse, "yoke-cli")
    core = _wheel(wheelhouse, "yoke-core")
    core_before = core.read_bytes()
    cli.unlink()

    with pytest.raises(
        wheel_sibling_pins.WheelSiblingPinError,
        match="exactly one wheel per product",
    ):
        wheel_sibling_pins.pin_wheelhouse_product_siblings(
            wheelhouse, package_index.PRODUCT_PACKAGE_NAMES
        )

    assert core.read_bytes() == core_before


@pytest.mark.parametrize(
    ("core_requires", "message"),
    [
        (("yoke-contracts", "yoke-cli"), "missing required product sibling"),
        (
            ("yoke-contracts", "yoke-cli", "yoke-cli", "yoke-harness"),
            "duplicate product sibling",
        ),
        (
            (
                "yoke-contracts",
                "yoke-cli @ https://example.invalid/yoke-cli.whl",
                "yoke-harness",
            ),
            "direct URL",
        ),
        (
            ("yoke-contracts", "yoke-cli", "yoke-harness", "yoke-core"),
            "unexpected product sibling",
        ),
    ],
)
def test_product_dependency_contract_fails_closed(
    tmp_path: Path,
    core_requires: tuple[str, ...],
    message: str,
) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    _build_wheelhouse(wheelhouse, core_requires=core_requires)

    with pytest.raises(wheel_sibling_pins.WheelSiblingPinError, match=message):
        wheel_sibling_pins.pin_wheelhouse_product_siblings(
            wheelhouse, package_index.PRODUCT_PACKAGE_NAMES
        )


def test_already_pinned_is_idempotent(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    _build_wheelhouse(
        wheelhouse,
        core_requires=(
            "yoke-contracts==0.2.0",
            "yoke-cli==0.2.0",
            "yoke-harness==0.2.0",
        ),
    )
    core = _wheel(wheelhouse, "yoke-core")
    before = core.read_bytes()

    wheel_sibling_pins.pin_wheelhouse_product_siblings(
        wheelhouse, package_index.PRODUCT_PACKAGE_NAMES
    )

    # An already-correctly-pinned wheel is left byte-identical (no repack).
    assert core.read_bytes() == before


def test_wrongly_pinned_sibling_fails(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    _build_wheelhouse(
        wheelhouse,
        core_requires=("yoke-harness==0.18.0", "yoke-cli", "yoke-contracts"),
    )
    before = {
        wheel.name: wheel.read_bytes()
        for wheel in wheelhouse.glob("*.whl")
    }

    with pytest.raises(
        wheel_sibling_pins.WheelSiblingPinError, match="0.18.0"
    ):
        wheel_sibling_pins.pin_wheelhouse_product_siblings(
            wheelhouse, package_index.PRODUCT_PACKAGE_NAMES
        )
    assert {
        wheel.name: wheel.read_bytes()
        for wheel in wheelhouse.glob("*.whl")
    } == before


def test_signed_product_wheel_fails_before_rewrite(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    _build_wheelhouse(wheelhouse)
    core = _wheel(wheelhouse, "yoke-core")
    with zipfile.ZipFile(core, "a") as archive:
        record_arcname = next(
            name for name in archive.namelist()
            if name.endswith(".dist-info/RECORD")
        )
        archive.writestr(record_arcname + ".jws", b"deprecated signature")

    with pytest.raises(
        wheel_sibling_pins.WheelSiblingPinError,
        match="signed product wheels",
    ):
        wheel_sibling_pins.pin_wheelhouse_product_siblings(
            wheelhouse, package_index.PRODUCT_PACKAGE_NAMES
        )


def test_record_hash_and_size_updated(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    _build_wheelhouse(wheelhouse)

    wheel_sibling_pins.pin_wheelhouse_product_siblings(
        wheelhouse, package_index.PRODUCT_PACKAGE_NAMES
    )

    core = _wheel(wheelhouse, "yoke-core")
    with zipfile.ZipFile(core) as archive:
        metadata_arcname = next(
            name for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        )
        record_arcname = next(
            name for name in archive.namelist()
            if name.endswith(".dist-info/RECORD")
        )
        metadata_bytes = archive.read(metadata_arcname)
        record_text = archive.read(record_arcname).decode("utf-8")

    row = next(
        line for line in record_text.splitlines()
        if line.startswith(metadata_arcname + ",")
    )
    _, recorded_hash, recorded_size = row.rsplit(",", 2)
    assert recorded_hash == _record_hash(metadata_bytes)
    assert int(recorded_size) == len(metadata_bytes)


def test_repack_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _build_wheelhouse(first)
    _build_wheelhouse(second)

    wheel_sibling_pins.pin_wheelhouse_product_siblings(
        first, package_index.PRODUCT_PACKAGE_NAMES
    )
    wheel_sibling_pins.pin_wheelhouse_product_siblings(
        second, package_index.PRODUCT_PACKAGE_NAMES
    )

    # Same input bytes → byte-identical rewritten wheels (SOURCE_DATE_EPOCH-safe).
    assert (
        _wheel(first, "yoke-core").read_bytes()
        == _wheel(second, "yoke-core").read_bytes()
    )


def test_repack_preserves_archive_comment(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    comment = b"product wheel provenance"
    _build_wheelhouse(
        wheelhouse,
        archive_comments={"yoke-core": comment},
    )

    wheel_sibling_pins.pin_wheelhouse_product_siblings(
        wheelhouse, package_index.PRODUCT_PACKAGE_NAMES
    )

    with zipfile.ZipFile(_wheel(wheelhouse, "yoke-core")) as archive:
        assert archive.comment == comment
