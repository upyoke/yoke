from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from yoke_cli.packs.receipt import (
    PackReceiptError,
    load_receipt,
    validate_receipt,
    write_receipt,
)
from yoke_contracts.packs import PACK_RECEIPT_SCHEMA


def test_receipt_round_trip_preserves_the_version_render_baseline(
    tmp_path: Path,
) -> None:
    receipt = _receipt()

    path = write_receipt(tmp_path, receipt)

    assert path == tmp_path / ".yoke" / "packs.json"
    assert load_receipt(tmp_path) == receipt
    assert path.stat().st_mode & 0o777 == 0o644


def test_receipt_rejects_paths_outside_the_project(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["packs"]["sample"]["files"] = {
        "../outside": {
            "path": "outside",
            "sha256": "0" * 64,
            "mode": 0o644,
        }
    }

    with pytest.raises(PackReceiptError, match="unsafe"):
        validate_receipt(receipt)


def test_receipt_rejects_a_symlinked_authority_path(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".yoke").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PackReceiptError, match="symlink"):
        write_receipt(tmp_path, _receipt())


def test_receipt_rejects_missing_render_baseline(tmp_path: Path) -> None:
    receipt = _receipt()
    del receipt["packs"]["sample"]["render_values"]

    with pytest.raises(PackReceiptError, match="record 'sample' is invalid"):
        write_receipt(tmp_path, receipt)


def test_load_receipt_upgrades_original_paths_to_explicit_project_paths(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    receipt["schema"] = 1
    del receipt["packs"]["sample"]["files"]["app.py"]["path"]
    del receipt["packs"]["sample"]["source"]
    authority = tmp_path / ".yoke" / "packs.json"
    authority.parent.mkdir()
    authority.write_text(json.dumps(receipt), encoding="utf-8")

    loaded = load_receipt(tmp_path)

    assert loaded is not None
    assert loaded["schema"] == PACK_RECEIPT_SCHEMA
    assert loaded["packs"]["sample"]["files"]["app.py"]["path"] == "app.py"
    assert loaded["packs"]["sample"]["prerequisites"] == []


def test_load_receipt_upgrades_previous_explicit_paths_with_prerequisites(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    receipt["schema"] = 2
    del receipt["packs"]["sample"]["prerequisites"]
    del receipt["packs"]["sample"]["source"]
    authority = tmp_path / ".yoke" / "packs.json"
    authority.parent.mkdir()
    authority.write_text(json.dumps(receipt), encoding="utf-8")

    loaded = load_receipt(tmp_path)

    assert loaded is not None
    assert loaded["schema"] == PACK_RECEIPT_SCHEMA
    assert loaded["packs"]["sample"]["prerequisites"] == []
    assert loaded["packs"]["sample"]["files"]["app.py"]["path"] == "app.py"


def test_load_receipt_upgrades_schema_three_to_the_served_source(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    receipt["schema"] = 3
    receipt["packs"]["sample"]["prerequisites"] = [_prerequisite()]
    del receipt["packs"]["sample"]["source"]
    authority = tmp_path / ".yoke" / "packs.json"
    authority.parent.mkdir()
    authority.write_text(json.dumps(receipt), encoding="utf-8")

    loaded = load_receipt(tmp_path)

    assert loaded is not None
    assert loaded["schema"] == PACK_RECEIPT_SCHEMA
    assert loaded["packs"]["sample"]["source"] == {"kind": "served"}
    assert loaded["packs"]["sample"]["prerequisites"] == [_prerequisite()]


def test_receipt_records_a_merged_commit_source(tmp_path: Path) -> None:
    receipt = _receipt()
    receipt["packs"]["sample"]["source"] = {"kind": "commit", "commit": "a" * 40}

    write_receipt(tmp_path, receipt)

    assert load_receipt(tmp_path) == receipt


def test_receipt_rejects_a_pre_release_source_without_its_commit(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    receipt["packs"]["sample"]["source"] = {"kind": "commit"}

    with pytest.raises(PackReceiptError, match="must name its full commit"):
        write_receipt(tmp_path, receipt)


def _prerequisite() -> dict[str, object]:
    return {
        "tool": "pulumi",
        "minimum_version": "3.0.0",
        "probe": {"executable": "pulumi", "version_args": ["version"]},
        "install": {
            "darwin": "brew install pulumi",
            "linux": "curl -fsSL https://get.pulumi.com | sh",
            "windows": "choco install pulumi",
        },
    }


def _receipt() -> dict[str, object]:
    content = b"print('sample')\n"
    digest = hashlib.sha256(content).hexdigest()
    return json.loads(
        json.dumps(
            {
                "schema": PACK_RECEIPT_SCHEMA,
                "project_id": 9,
                "project_slug": "sample",
                "packs": {
                    "sample": {
                        "version": "1.0.0",
                        "content_digest": digest,
                        "render_values": {"project_name": "sample"},
                        "prerequisites": [],
                        "source": {"kind": "served"},
                        "files": {
                            "app.py": {
                                "path": "app.py",
                                "sha256": digest,
                                "mode": 0o644,
                            }
                        },
                    }
                },
            }
        )
    )
