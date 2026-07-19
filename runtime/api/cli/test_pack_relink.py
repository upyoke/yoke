from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from yoke_cli.packs import relink
from yoke_cli.packs.receipt import load_receipt, write_receipt


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _receipt(content: str = "baseline\n") -> dict:
    digest = _digest(content)
    return {
        "schema": 2,
        "project_id": 9,
        "project_slug": "sample",
        "packs": {
            "feature": {
                "version": "1.0.0",
                "content_digest": digest,
                "render_values": {},
                "files": {
                    "feature.txt": {
                        "path": "feature.txt",
                        "sha256": digest,
                        "mode": 0o644,
                    }
                },
            }
        },
    }


def _install_transport_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        relink,
        "_fetch_bundle",
        lambda *args, **kwargs: {
            "project_id": 9,
            "project_slug": "sample",
        },
    )
    monkeypatch.setattr(relink, "_assert_checkout_project", lambda *args: None)
    monkeypatch.setattr(relink, "_report_receipt", lambda *args, **kwargs: {})


def test_relink_previews_customized_destination_without_changing_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_receipt(tmp_path, _receipt())
    (tmp_path / "moved").mkdir()
    (tmp_path / "moved" / "feature.txt").write_text("customized\n")
    _install_transport_fakes(monkeypatch)

    report = relink.run_pack_relink(
        tmp_path,
        project="sample",
        pack="feature",
        from_path="feature.txt",
        to_path="moved/feature.txt",
    )

    assert report["applied"] is False
    assert report["destination_is_customized"] is True
    assert (
        load_receipt(tmp_path)["packs"]["feature"]["files"]["feature.txt"]["path"]
        == "feature.txt"
    )


def test_relink_apply_updates_only_receipt_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_receipt(tmp_path, _receipt())
    (tmp_path / "moved").mkdir()
    destination = tmp_path / "moved" / "feature.txt"
    destination.write_text("baseline\n")
    _install_transport_fakes(monkeypatch)

    report = relink.run_pack_relink(
        tmp_path,
        project="sample",
        pack="feature",
        from_path="feature.txt",
        to_path="moved/feature.txt",
        apply=True,
    )

    assert report["applied"] is True
    assert report["destination_matches_baseline"] is True
    assert destination.read_text() == "baseline\n"
    assert (
        load_receipt(tmp_path)["packs"]["feature"]["files"]["feature.txt"]["path"]
        == "moved/feature.txt"
    )


def test_relink_refuses_when_original_path_still_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_receipt(tmp_path, _receipt())
    (tmp_path / "feature.txt").write_text("baseline\n")
    (tmp_path / "moved.txt").write_text("baseline\n")
    _install_transport_fakes(monkeypatch)

    with pytest.raises(relink.PackClientError, match="still exists"):
        relink.run_pack_relink(
            tmp_path,
            project="sample",
            pack="feature",
            from_path="feature.txt",
            to_path="moved.txt",
        )
