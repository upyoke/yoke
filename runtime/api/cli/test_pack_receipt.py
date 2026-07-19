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
    authority = tmp_path / ".yoke" / "packs.json"
    authority.parent.mkdir()
    authority.write_text(json.dumps(receipt), encoding="utf-8")

    loaded = load_receipt(tmp_path)

    assert loaded is not None
    assert loaded["schema"] == 2
    assert loaded["packs"]["sample"]["files"]["app.py"]["path"] == "app.py"


def _receipt() -> dict[str, object]:
    content = b"print('sample')\n"
    digest = hashlib.sha256(content).hexdigest()
    return json.loads(
        json.dumps(
            {
                "schema": 2,
                "project_id": 9,
                "project_slug": "sample",
                "packs": {
                    "sample": {
                        "version": "1.0.0",
                        "content_digest": digest,
                        "render_values": {"project_name": "sample"},
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
