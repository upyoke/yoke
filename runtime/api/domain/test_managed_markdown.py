"""Managed-markdown block placement, preservation, refresh, and removal."""

from __future__ import annotations

import pytest

from yoke_cli.project_install.files import ProjectInstallError
from yoke_cli.project_install.managed_markdown import (
    MANAGED_BLOCK_BEGIN,
    MANAGED_BLOCK_END,
    apply_managed_markdown,
    plan_markdown_block,
    plan_markdown_removal,
    preview_managed_markdown,
    remove_managed_markdown,
    render_block,
)


def _md(doctrine: str = "# Yoke rules\n\nDo the thing.") -> dict:
    return {
        "blocks": {"doctrine": doctrine, "shell": "# Codex shell\n"},
        "targets": [
            {"path": "AGENTS.md", "block": "doctrine"},
            {"path": "CLAUDE.md", "block": "doctrine"},
            {"path": "CODEX.md", "block": "shell"},
        ],
    }


def test_render_block_wraps_in_markers() -> None:
    block = render_block("hello")
    assert block.startswith(MANAGED_BLOCK_BEGIN)
    assert block.rstrip().endswith(MANAGED_BLOCK_END)
    assert "hello" in block
    assert "overwritten on refresh" in block


def test_create_when_absent(tmp_path) -> None:
    records, report = apply_managed_markdown(tmp_path, _md(), None)
    assert report["changed"] == 3
    for rel in ("AGENTS.md", "CLAUDE.md", "CODEX.md"):
        text = (tmp_path / rel).read_text(encoding="utf-8")
        assert MANAGED_BLOCK_BEGIN in text and MANAGED_BLOCK_END in text
        assert records[rel]["file_created"] is True
    assert "Do the thing." in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "Codex shell" in (tmp_path / "CODEX.md").read_text(encoding="utf-8")


def test_insert_preserves_user_content_below() -> None:
    existing = "# My project\n\nHouse rules the team wrote.\n"
    action, new = plan_markdown_block(existing, "YOKE DOCTRINE")
    assert action == "inserted"
    assert new.startswith(MANAGED_BLOCK_BEGIN)
    assert "House rules the team wrote." in new
    # user content sits after our block, untouched
    assert new.index("House rules") > new.index(MANAGED_BLOCK_END)


def test_refresh_overwrites_block_preserves_surroundings() -> None:
    above = "# Team title above\n\n"
    below = "\n\n## Our own notes\nkeep me\n"
    first = above + render_block("OLD DOCTRINE") + below
    action, new = plan_markdown_block(first, "NEW DOCTRINE")
    assert action == "refreshed"
    assert "NEW DOCTRINE" in new and "OLD DOCTRINE" not in new
    assert new.startswith("# Team title above")
    assert new.rstrip().endswith("keep me")


def test_idempotent_second_apply_unchanged(tmp_path) -> None:
    apply_managed_markdown(tmp_path, _md(), None)
    _records, report = apply_managed_markdown(tmp_path, _md(), None)
    assert report["changed"] == 0
    assert all("up to date" in line for line in report["actions"])


def test_uninstall_deletes_installer_created_file(tmp_path) -> None:
    records, _ = apply_managed_markdown(tmp_path, _md(), None)
    result = remove_managed_markdown(tmp_path, records)
    assert sorted(result["removed_files"]) == ["AGENTS.md", "CLAUDE.md", "CODEX.md"]
    assert not (tmp_path / "AGENTS.md").exists()


def test_uninstall_strips_block_but_keeps_user_file(tmp_path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "# Pre-existing\n\nteam content\n", encoding="utf-8"
    )
    records, _ = apply_managed_markdown(
        tmp_path,
        {"blocks": {"d": "DOCTRINE"}, "targets": [{"path": "AGENTS.md", "block": "d"}]},
        None,
    )
    assert records["AGENTS.md"]["file_created"] is False
    remove_managed_markdown(tmp_path, records)
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert (tmp_path / "AGENTS.md").exists()
    assert "team content" in text
    assert MANAGED_BLOCK_BEGIN not in text


def test_removal_planner_absent_block_is_noop() -> None:
    action, new = plan_markdown_removal("no block here\n", file_created=False)
    assert action == "absent"
    assert new == "no block here\n"


def test_preview_reports_without_writing(tmp_path) -> None:
    (tmp_path / "CLAUDE.md").write_text("mine\n", encoding="utf-8")
    result = preview_managed_markdown(tmp_path, _md())
    assert sorted(result["would_write"]) == ["AGENTS.md", "CLAUDE.md", "CODEX.md"]
    joined = "\n".join(result["actions"])
    assert "Would create: AGENTS.md" in joined
    assert "Would update: CLAUDE.md" in joined  # existing file -> insert block
    # nothing was written
    assert not (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == "mine\n"


def test_unsafe_paths_rejected(tmp_path) -> None:
    for rel in (".yoke/notes.md", "../escape.md", "AGENTS.txt"):
        with pytest.raises(ProjectInstallError):
            apply_managed_markdown(
                tmp_path,
                {"blocks": {"d": "x"}, "targets": [{"path": rel, "block": "d"}]},
                None,
            )
