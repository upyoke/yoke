"""Yoke-managed files stay stable when Git converts their line endings."""

from __future__ import annotations

from pathlib import Path

from yoke_cli.project_install.contract_files import (
    apply_contract_files,
    reconcile_gitignore,
)
from yoke_cli.project_install.files import apply_files, prune_files, sha256_text
from yoke_cli.project_install.managed_markdown import (
    apply_managed_markdown,
)

CONTENT = "# Settings\n\nline one\nline two\n"


def _crlf(text: str) -> bytes:
    return text.replace("\n", "\r\n").encode("utf-8")


def test_digest_ignores_crlf_conversion() -> None:
    assert sha256_text(CONTENT) == sha256_text(CONTENT.replace("\n", "\r\n"))
    assert sha256_text(CONTENT) != sha256_text(CONTENT + "x")


def test_crlf_checkout_of_bundle_file_is_not_rewritten(tmp_path: Path) -> None:
    target = tmp_path / ".claude" / "rules.md"
    target.parent.mkdir()
    target.write_bytes(_crlf(CONTENT))

    hashes, written = apply_files(tmp_path, [{"path": ".claude/rules.md", "content": CONTENT}])

    assert written == []
    assert hashes == {".claude/rules.md": sha256_text(CONTENT)}
    assert target.read_bytes() == _crlf(CONTENT)


def test_crlf_checkout_of_retired_file_is_pruned_not_preserved(tmp_path: Path) -> None:
    target = tmp_path / "old.md"
    target.write_bytes(_crlf(CONTENT))

    pruned, skipped, warnings = prune_files(
        tmp_path, {"old.md": sha256_text(CONTENT)}, []
    )

    assert (pruned, skipped, warnings) == (["old.md"], [], [])
    assert not target.exists()


def test_crlf_managed_block_is_unchanged_and_project_bytes_survive(
    tmp_path: Path,
) -> None:
    managed = {
        "blocks": {"doctrine": "# Yoke rules\n\nDo the thing."},
        "targets": [{"path": "AGENTS.md", "block": "doctrine"}],
    }
    apply_managed_markdown(tmp_path, managed, None)
    agents = tmp_path / "AGENTS.md"
    lf = agents.read_text(encoding="utf-8") + "\n# Project notes\n"
    agents.write_bytes(_crlf(lf))

    _records, report = apply_managed_markdown(tmp_path, managed, None)
    assert report["written"] == []
    assert agents.read_bytes() == _crlf(lf)

    managed["blocks"]["doctrine"] = "# Yoke rules\n\nDo the new thing."
    _records, report = apply_managed_markdown(tmp_path, managed, None)
    assert report["written"] == ["AGENTS.md"]
    refreshed = agents.read_bytes()
    assert b"Do the new thing." in refreshed
    assert refreshed.endswith(b"\r\n# Project notes\r\n")


def test_crlf_seeded_contract_file_is_adopted(tmp_path: Path) -> None:
    target = tmp_path / ".yoke" / "project.config"
    target.parent.mkdir()
    target.write_bytes(_crlf(CONTENT))

    contract, written, existing, adopted = apply_contract_files(
        tmp_path, [{"path": ".yoke/project.config", "content": CONTENT}], {}
    )

    assert adopted == [".yoke/project.config"]
    assert contract == {".yoke/project.config": sha256_text(CONTENT)}
    assert written == []


def test_gitignore_backfill_keeps_crlf(tmp_path: Path) -> None:
    target = tmp_path / ".yoke" / ".gitignore"
    target.parent.mkdir()
    target.write_bytes(b"local/\r\n")

    missing = reconcile_gitignore(
        tmp_path, [{"path": ".yoke/.gitignore", "content": "local/\nstrategy/\n"}]
    )

    assert missing == ["strategy/"]
    assert target.read_bytes() == b"local/\r\nstrategy/\r\n"
