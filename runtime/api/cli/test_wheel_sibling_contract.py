"""Mandatory product-wheel dependency contract tests."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from runtime.api.cli.test_wheel_sibling_pins import (
    _build_wheelhouse,
    _requires_dist,
    _wheel,
)
from yoke_core.tools import package_index, wheel_sibling_pins


@pytest.mark.parametrize(
    "core_requires",
    [
        (
            "yoke-contracts",
            "yoke-cli",
            'yoke-harness; python_version < "3"',
        ),
        ("yoke-contracts", "yoke-cli[extra]", "yoke-harness"),
    ],
)
def test_qualified_required_sibling_fails(
    tmp_path: Path,
    core_requires: tuple[str, ...],
) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    _build_wheelhouse(wheelhouse, core_requires=core_requires)

    with pytest.raises(
        wheel_sibling_pins.WheelSiblingPinError,
        match="unconditional and have no extras",
    ):
        wheel_sibling_pins.pin_wheelhouse_product_siblings(
            wheelhouse, package_index.PRODUCT_PACKAGE_NAMES
        )


def test_quoted_record_rows_are_rewritten_atomically(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    _build_wheelhouse(wheelhouse)
    harness = _wheel(wheelhouse, "yoke-harness")
    with zipfile.ZipFile(harness) as archive:
        infos = archive.infolist()
        payloads = {
            info.filename: archive.read(info)
            for info in infos
        }
        comment = archive.comment
    record_arcname = next(
        name for name in payloads if name.endswith(".dist-info/RECORD")
    )
    rows = list(
        csv.reader(io.StringIO(payloads[record_arcname].decode("utf-8")))
    )
    output = io.StringIO(newline="")
    csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator="\n").writerows(rows)
    payloads[record_arcname] = output.getvalue().encode("utf-8")
    replacement = harness.with_suffix(".quoted")
    with zipfile.ZipFile(replacement, "w") as archive:
        archive.comment = comment
        for info in infos:
            archive.writestr(info, payloads[info.filename])
    replacement.replace(harness)

    wheel_sibling_pins.pin_wheelhouse_product_siblings(
        wheelhouse, package_index.PRODUCT_PACKAGE_NAMES
    )

    assert "yoke-cli==0.2.0" in _requires_dist(harness)


def test_folded_sibling_header_is_pinned(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    _build_wheelhouse(wheelhouse)
    harness = _wheel(wheelhouse, "yoke-harness")
    with zipfile.ZipFile(harness) as archive:
        infos = archive.infolist()
        payloads = {
            info.filename: archive.read(info)
            for info in infos
        }
        comment = archive.comment
    metadata_arcname = next(
        name for name in payloads if name.endswith(".dist-info/METADATA")
    )
    record_arcname = next(
        name for name in payloads if name.endswith(".dist-info/RECORD")
    )
    metadata = payloads[metadata_arcname].replace(
        b"Requires-Dist: yoke-contracts\n",
        b"Requires-Dist:\n yoke-contracts\n",
    )
    digest = hashlib.sha256(metadata).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    rows = list(
        csv.reader(io.StringIO(payloads[record_arcname].decode("utf-8")))
    )
    for row in rows:
        if row[0] == metadata_arcname:
            row[1:] = [f"sha256={encoded}", str(len(metadata))]
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(rows)
    payloads[metadata_arcname] = metadata
    payloads[record_arcname] = output.getvalue().encode("utf-8")
    replacement = harness.with_suffix(".folded")
    with zipfile.ZipFile(replacement, "w") as archive:
        archive.comment = comment
        for info in infos:
            archive.writestr(info, payloads[info.filename])
    replacement.replace(harness)

    wheel_sibling_pins.pin_wheelhouse_product_siblings(
        wheelhouse, package_index.PRODUCT_PACKAGE_NAMES
    )

    assert "yoke-contracts==0.2.0" in _requires_dist(harness)
