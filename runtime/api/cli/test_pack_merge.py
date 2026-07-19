from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from yoke_cli.packs.merge import plan_get, plan_update


def test_get_refuses_to_overwrite_an_existing_project_file(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("project version\n", encoding="utf-8")

    plan = plan_get(tmp_path, [_text_entry("app.py", "pack version\n")])

    assert plan["creates"] == []
    assert plan["conflicts"] == [
        {"path": "app.py", "reason": "existing_project_file"}
    ]


def test_update_merges_non_overlapping_pack_and_project_changes(tmp_path: Path) -> None:
    base = "title=base\nkeep=one\nkeep=two\nproject=base\n"
    (tmp_path / "config.txt").write_text(
        "title=base\nkeep=one\nkeep=two\nproject=custom\n", encoding="utf-8"
    )

    plan = plan_update(
        tmp_path,
        [_text_entry("config.txt", base)],
        [_text_entry("config.txt", "title=new\nkeep=one\nkeep=two\nproject=base\n")],
    )

    assert plan["conflicts"] == []
    assert plan["updates"][0]["content"] == (
        "title=new\nkeep=one\nkeep=two\nproject=custom\n"
    )


def test_update_reports_overlapping_customization_without_writing_markers(
    tmp_path: Path,
) -> None:
    (tmp_path / "config.txt").write_text("value=project\n", encoding="utf-8")

    plan = plan_update(
        tmp_path,
        [_text_entry("config.txt", "value=base\n")],
        [_text_entry("config.txt", "value=pack\n")],
    )

    assert plan["updates"] == []
    assert plan["conflicts"] == [
        {
            "path": "config.txt",
            "reason": "overlapping_customization",
            "content_conflict": True,
            "mode_conflict": False,
        }
    ]
    assert "<<<<<<<" not in (tmp_path / "config.txt").read_text(encoding="utf-8")


def test_update_keeps_a_file_removed_by_the_new_pack(tmp_path: Path) -> None:
    (tmp_path / "retired.txt").write_text("project keeps this\n", encoding="utf-8")

    plan = plan_update(
        tmp_path,
        [_text_entry("retired.txt", "old pack\n")],
        [],
    )

    assert plan["changed"] is False
    assert plan["retained_project_files"] == [
        {"path": "retired.txt", "reason": "removed_upstream_project_keeps_file"}
    ]
    assert (tmp_path / "retired.txt").read_text(encoding="utf-8") == (
        "project keeps this\n"
    )


def test_update_replaces_unchanged_binary_and_refuses_customized_binary(
    tmp_path: Path,
) -> None:
    old = _binary_entry("asset.bin", b"old")
    new = _binary_entry("asset.bin", b"new")
    (tmp_path / "asset.bin").write_bytes(b"old")

    clean = plan_update(tmp_path, [old], [new])

    assert clean["conflicts"] == []
    assert clean["updates"] == [new]

    (tmp_path / "asset.bin").write_bytes(b"custom")
    customized = plan_update(tmp_path, [old], [new])

    assert customized["updates"] == []
    assert customized["conflicts"] == [
        {"path": "asset.bin", "reason": "customized_binary_file"}
    ]


def _text_entry(path: str, content: str, mode: int = 0o644) -> dict[str, object]:
    return {
        "path": path,
        "content": content,
        "encoding": "utf-8",
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "mode": mode,
    }


def _binary_entry(path: str, content: bytes, mode: int = 0o644) -> dict[str, object]:
    return {
        "path": path,
        "content": base64.b64encode(content).decode("ascii"),
        "encoding": "base64",
        "sha256": hashlib.sha256(content).hexdigest(),
        "mode": mode,
    }
