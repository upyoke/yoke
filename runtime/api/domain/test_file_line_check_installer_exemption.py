"""Regression: installer-rendered files are line-limit exempt (GENERATED).

A receiving project's ``yoke project refresh`` commit carries upstream-rendered
agent adapters (e.g. ``.claude/agents/yoke-engineer.md``) — authored in Yoke,
rendered into the repo, un-splittable locally. They appear in the install
manifest's ``files`` map and must classify GENERATED, not AUTHORED, so an
oversized adapter does not force ``--no-verify`` on the refresh commit
. ``classify_path`` reads the manifest from ``repo_root``;
no git repo is needed.
"""
from __future__ import annotations

import json
import pathlib

from yoke_core.domain import file_line_check as flc


def _lines(n: int) -> str:
    return "\n".join(f"x{i}" for i in range(n)) + "\n"


def _write_manifest(repo_root: pathlib.Path, files: dict) -> None:
    manifest = repo_root / ".yoke" / "install-manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"manifest_schema": 1, "files": files}), encoding="utf-8",
    )


def test_installer_managed_file_is_generated(tmp_path: pathlib.Path) -> None:
    managed = ".claude/agents/yoke-engineer.md"
    _write_manifest(tmp_path, {managed: "deadbeef"})
    (tmp_path / managed).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / managed).write_text(_lines(800), encoding="utf-8")
    assert flc.classify_path(managed, repo_root=tmp_path) == flc.Classification.GENERATED


def test_unlisted_file_stays_authored(tmp_path: pathlib.Path) -> None:
    # The exemption is manifest-scoped, not a blanket .claude/ skip: a sibling
    # path absent from the manifest's `files` stays authored.
    _write_manifest(tmp_path, {".claude/agents/yoke-engineer.md": "x"})
    (tmp_path / "pkg").mkdir(parents=True, exist_ok=True)
    (tmp_path / "pkg" / "big.py").write_text(_lines(800), encoding="utf-8")
    assert flc.classify_path("pkg/big.py", repo_root=tmp_path) == flc.Classification.AUTHORED
