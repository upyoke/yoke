"""Catalog-rendering helpers for the event-registry populator pipeline.

Sibling module of :mod:`yoke_core.domain.populate_registry`. Owns the
two helpers that resolve the repo root and render the
``docs/event-catalog.md`` markdown table from the populated
``event_registry`` rows.

Resolver precedence (output anchor for ``docs/event-catalog.md``):

1. Explicit ``repo_root`` argument.
2. ``YOKE_REPO_ROOT`` env var (explicit pin, used by the hook runner).
3. ``YOKE_ROOT`` env var (normalized verbatim — a trailing ``data/``
   segment is stripped, but ``.worktrees/<branch>/`` segments are
   preserved so worktree-anchored renders land in the worktree).
4. ``git rev-parse --show-toplevel`` from cwd (returns the worktree
   root when run inside a linked worktree).

Worktree anchoring matters because ``resolve_yoke_root`` strips
``.worktrees/<branch>/`` segments to anchor the **control-plane DB** to
the owning main checkout. Routing the **docs writer** through the same
helper silently anchored every worktree render into main's tree, where
the agent had no claim and no in-flight context — the regen overwrote
main's catalog with whatever the DB last saw, even on branches that had
intentionally diverged the registry data.

Helpers exported:

- :func:`_resolve_repo_root`: env-var-aware repo-root resolver.
- :func:`_render_catalog`: write ``docs/event-catalog.md`` and return the
  output path.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from yoke_core.domain.db_helpers import connect, query_rows
from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)


def _normalize_yoke_root(yoke_root: str) -> Path:
    """Strip a trailing ``data/`` segment without collapsing worktree paths."""
    candidate = Path(yoke_root.rstrip("/") or yoke_root)
    if candidate.name == "data":
        candidate = candidate.parent
    return candidate


def _resolve_repo_root(repo_root: Optional[str] = None) -> Path:
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
        raise RuntimeError("Cannot determine repo root") from exc


APPENDIX_SENTINEL = "<!-- catalog-appendix-start -->"


def _extract_appendix(catalog_path: Path) -> str:
    """Return hand-authored content below ``APPENDIX_SENTINEL`` if present.

    The sentinel comment lets operators add envelope-schema prose, links,
    or other narrative below the auto-rendered table that the next
    populate-and-render run preserves verbatim.
    """
    if not catalog_path.exists():
        return ""
    text = catalog_path.read_text()
    if APPENDIX_SENTINEL not in text:
        return ""
    return text.split(APPENDIX_SENTINEL, 1)[1]


def _render_catalog(db_path: Optional[str], repo_root: Path) -> Path:
    """Write ``docs/event-catalog.md`` and return the output path."""
    catalog_path = repo_root / "docs" / "event-catalog.md"
    assert_target_under_session_work_authority(catalog_path)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)

    appendix = _extract_appendix(catalog_path)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines: List[str] = []
    lines.append("# Event Catalog")
    lines.append("")
    lines.append(f"> Auto-generated on {timestamp}")
    lines.append("> Regenerate: `python3 -m yoke_core.domain.populate_registry`")
    lines.append("")
    lines.append("| Event Name | Kind | Type | Owner Service | Description | Severity | Status |")
    lines.append("|---|---|---|---|---|---|---|")

    conn = connect(db_path)
    try:
        rows = query_rows(
            conn,
            "SELECT event_name, event_kind, event_type, owner_service, "
            "COALESCE(description,''), severity_default, status "
            "FROM event_registry ORDER BY event_name ASC",
        )
    finally:
        conn.close()

    for row in rows:
        lines.append(
            "| {name} | {kind} | {etype} | {service} | {desc} | {severity} | {status} |".format(
                name=row[0],
                kind=row[1],
                etype=row[2],
                service=row[3],
                desc=row[4],
                severity=row[5],
                status=row[6],
            )
        )

    content = "\n".join(lines) + "\n"
    if appendix:
        content += "\n" + APPENDIX_SENTINEL + appendix
    catalog_path.write_text(content)
    return catalog_path
