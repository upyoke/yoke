"""Client-side git commit for ``yoke strategy ingest --commit``.

Split from :mod:`yoke_cli.commands.adapters.strategy_render` for the authored
line cap. Stages exactly the rendered views the just-completed ingest
wrote (the docs carrying ``file_text``) and commits them; the commit runs
the repo's git pre-commit hook — including the strategy-freshness gate —
which passes because the write-back left every staged view fresh.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

from yoke_contracts.project_contract.strategy_docs_paths import strategy_view_path


def commit_written_views(target_root: Any, response: Any, message: str) -> int:
    """Stage + git-commit the views ingest re-rendered. Returns an exit code.

    A no-op ingest (no doc carried ``file_text``) commits nothing and
    returns 0. git add / commit failures surface the git stderr and
    return 1.
    """
    written = [
        d for d in (response.result or {}).get("docs", []) if d.get("file_text")
    ]
    if not written:
        print("nothing to commit (no strategy views changed)", file=sys.stderr)
        return 0
    paths = [str(strategy_view_path(target_root, str(d["slug"]))) for d in written]
    add = subprocess.run(
        ["git", "-C", str(target_root), "add", "--", *paths],
        capture_output=True, text=True,
    )
    if add.returncode != 0:
        print(f"error (git add failed): {add.stderr.strip()}", file=sys.stderr)
        return 1
    commit = subprocess.run(
        ["git", "-C", str(target_root), "commit", "-m", message],
        capture_output=True, text=True,
    )
    if commit.returncode != 0:
        detail = (commit.stderr or commit.stdout).strip()
        print(f"error (git commit failed): {detail}", file=sys.stderr)
        return 1
    slugs = ", ".join(str(d["slug"]) for d in written)
    print(f"committed {len(written)} strategy view(s): {slugs}", file=sys.stderr)
    return 0


__all__ = ["commit_written_views"]
