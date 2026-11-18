"""Render ``docs/event-catalog.md`` from the code event catalog.

The table comes from :data:`yoke_core.domain.event_catalog.EVENT_CATALOG`
alone, so the rendered file is a pure function of the source tree: the same
checkout always renders the same bytes. Hand-authored prose below
``APPENDIX_SENTINEL`` is preserved verbatim.

Resolver precedence for the checkout the file is written into:

1. Explicit ``--repo-root`` argument.
2. ``YOKE_REPO_ROOT`` env var (explicit pin, used by the hook runner).
3. ``YOKE_ROOT`` env var (a trailing ``data/`` segment is stripped, but
   ``.worktrees/<branch>/`` segments are preserved so a lane renders into
   its own tree rather than into main's).
4. ``git rev-parse --show-toplevel`` from cwd.

Run ``python3 -m yoke_core.domain.event_catalog_render`` from a Yoke checkout
after editing the catalog, and commit the result.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

from yoke_core.domain.event_catalog import EVENT_CATALOG
from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)

APPENDIX_SENTINEL = "<!-- catalog-appendix-start -->"
EVENT_CATALOG_RELPATH = "docs/event-catalog.md"

_HEADER = (
    "# Event Catalog",
    "",
    "> Generated from `yoke_core.domain.event_catalog`. Edit that table, then run",
    "> `python3 -m yoke_core.domain.event_catalog_render` from a Yoke checkout.",
    "> Every boot makes `event_registry` match the same table.",
    "",
    "| Event Name | Kind | Type | Owner Service | Severity | Description |",
    "|---|---|---|---|---|---|",
)


def _normalize_yoke_root(yoke_root: str) -> Path:
    """Strip a trailing ``data/`` segment without collapsing worktree paths."""
    candidate = Path(yoke_root.rstrip("/") or yoke_root)
    if candidate.name == "data":
        candidate = candidate.parent
    return candidate


def resolve_repo_root(repo_root: Optional[str] = None) -> Path:
    if repo_root:
        return Path(repo_root).resolve()
    env_root = os.environ.get("YOKE_REPO_ROOT")
    if env_root:
        return Path(env_root).resolve()
    yoke_root = os.environ.get("YOKE_ROOT")
    if yoke_root:
        candidate = _normalize_yoke_root(yoke_root)
        if candidate.is_dir():
            return candidate.resolve()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise RuntimeError(
            "Cannot determine the Yoke checkout; pass --repo-root or run inside one"
        ) from exc


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def catalog_appendix(existing: str) -> str:
    """Return the hand-authored text after the sentinel, or an empty string."""
    if APPENDIX_SENTINEL not in existing:
        return ""
    return existing.split(APPENDIX_SENTINEL, 1)[1]


def render_catalog_text(appendix: str = "") -> str:
    """Return the full catalog document for the current code catalog."""
    lines = list(_HEADER)
    for spec in sorted(EVENT_CATALOG.values()):
        lines.append("| " + " | ".join(_cell(value) for value in spec) + " |")
    content = "\n".join(lines) + "\n"
    if appendix:
        content += "\n" + APPENDIX_SENTINEL + appendix
    return content


def render_event_catalog(repo_root: Path) -> Path:
    """Write ``docs/event-catalog.md`` under *repo_root* and return its path."""
    catalog_path = repo_root / EVENT_CATALOG_RELPATH
    assert_target_under_session_work_authority(catalog_path)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    existing = catalog_path.read_text(encoding="utf-8") if catalog_path.exists() else ""
    catalog_path.write_text(render_catalog_text(catalog_appendix(existing)), encoding="utf-8", newline="\n")
    return catalog_path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="event-catalog-render",
        description="Render docs/event-catalog.md from the code event catalog.",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Yoke checkout to write into (defaults to YOKE_REPO_ROOT / YOKE_ROOT / git).",
    )
    args = parser.parse_args(argv)
    path = render_event_catalog(resolve_repo_root(args.repo_root))
    print(f"{path}: {len(EVENT_CATALOG)} events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
