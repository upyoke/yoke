"""QA reporting, status output, and baseline management.

Extracted from ``yoke_core.domain.qa`` to keep the parent module under 800
lines.  All public symbols are re-exported from the parent so existing callers
are unaffected.

Owner: ``yoke_core.domain.qa`` (orchestration layer).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Sequence

from yoke_core.domain.db_helpers import connect, iso8601_now, query_one, query_rows, query_scalar
from yoke_core.domain.qa_artifact_handle import local_handle, serialize_handle
from yoke_core.domain.sql_json import json_get


# ---------------------------------------------------------------------------
# Shared helpers (tiny, duplicated to avoid circular imports)
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _coalesce(val: Any, default: str = "") -> str:
    if val is None:
        return default
    return str(val)


def _pipe_row(row, cols: Optional[Sequence[str]] = None) -> str:
    if cols:
        return "|".join(_coalesce(row[c]) for c in cols)
    return "|".join(_coalesce(row[i]) for i in range(len(row)))


# ---------------------------------------------------------------------------
# Baseline path helpers
# ---------------------------------------------------------------------------

def _route_slug(route: str) -> str:
    """Convert a route path to a slug: strip leading /, replace / with -, lowercase."""
    return route.lstrip("/").replace("/", "-").lower()


def _baseline_path(route: str, width: int, height: int) -> str:
    """Derive the baseline file path from route + viewport dimensions."""
    slug = _route_slug(route)
    return f"test/baselines/{slug}-{width}x{height}.png"


# ---------------------------------------------------------------------------
# Baseline management
# ---------------------------------------------------------------------------

def cmd_baseline_record(
    *,
    db_path: Optional[str] = None,
    route: str,
    width: int,
    height: int,
    branch: str = "",
    commit: str = "",
    project: Optional[str] = None,
    screenshot_path: str,
    update: bool = False,
) -> int:
    """Record a baseline or candidate baseline. Returns the artifact ID."""
    if not route:
        print("Error: --route is required", file=sys.stderr)
        sys.exit(2)
    if not width:
        print("Error: --width is required", file=sys.stderr)
        sys.exit(2)
    if not height:
        print("Error: --height is required", file=sys.stderr)
        sys.exit(2)
    if not screenshot_path:
        print("Error: --screenshot-path is required", file=sys.stderr)
        sys.exit(2)

    storage = _baseline_path(route, width, height)
    now = _now_iso()

    meta = json.dumps({
        "route": route,
        "viewport": f"{width}x{height}",
        "captured_at": now,
        "branch": branch,
        "commit": commit,
    })

    # Determine artifact type
    art_type = "candidate_baseline"
    if update or branch == "main":
        art_type = "baseline_image"

    # If recording as baseline_image, copy file to baseline path in project repo
    if art_type == "baseline_image" and project:
        try:
            from yoke_core.domain.db_helpers import connect as _connect
            from yoke_core.domain.project_checkout_locations import checkout_for_project

            copy_conn = _connect(path=db_path)
            try:
                checkout = checkout_for_project(copy_conn, project)
            finally:
                copy_conn.close()
            if checkout is not None and Path(checkout).is_dir():
                dest = Path(checkout) / storage
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(screenshot_path, str(dest))
        except Exception:
            pass  # best-effort file copy

    conn = connect(path=db_path)
    try:
        cur = conn.execute(
            """INSERT INTO qa_artifacts (qa_run_id, artifact_type, content_type, artifact_handle, metadata, created_at)
               VALUES (NULL, %s, 'image/png', %s, %s, %s) RETURNING id""",
            (art_type, serialize_handle(local_handle(storage)), meta, iso8601_now()),
        )
        inserted_id = int(cur.fetchone()[0])
        conn.commit()
    finally:
        conn.close()

    print(inserted_id)
    return inserted_id


def cmd_baseline_list(
    *,
    db_path: Optional[str] = None,
    project: Optional[str] = None,
) -> List[str]:
    """List baseline_image artifacts (pipe-delimited)."""
    conn = connect(path=db_path)
    try:
        sql = (
            f"SELECT id, COALESCE(artifact_handle,''), "
            f"COALESCE({json_get('metadata', '$.route')},''), "
            f"COALESCE({json_get('metadata', '$.viewport')},''), "
            f"COALESCE({json_get('metadata', '$.captured_at')},''), "
            f"COALESCE({json_get('metadata', '$.branch')},''), "
            f"COALESCE({json_get('metadata', '$.commit')},''), "
            f"created_at FROM qa_artifacts "
            f"WHERE artifact_type = 'baseline_image' ORDER BY id"
        )
        rows = query_rows(conn, sql)
    finally:
        conn.close()

    lines = []
    for row in rows:
        line = _pipe_row(row)
        print(line)
        lines.append(line)
    return lines


def cmd_baseline_get(
    route: str,
    viewport: str,
    *,
    db_path: Optional[str] = None,
) -> str:
    """Get baseline metadata for route+viewport. Returns the formatted line."""
    if not route or not viewport:
        print("Usage: qa baseline-get <route> <viewport>", file=sys.stderr)
        print("  e.g.: qa baseline-get /settings/profile 1920x1080", file=sys.stderr)
        sys.exit(2)

    conn = connect(path=db_path)
    try:
        row = query_one(
            conn,
            f"SELECT id, COALESCE(artifact_handle,''), COALESCE(metadata,''), created_at "
            f"FROM qa_artifacts "
            f"WHERE artifact_type = 'baseline_image' "
            f"AND {json_get('metadata', '$.route')} = %s "
            f"AND {json_get('metadata', '$.viewport')} = %s "
            f"ORDER BY id DESC LIMIT 1",
            (route, viewport),
        )
    finally:
        conn.close()

    if row is None:
        print(f"Error: no baseline found for route='{route}' viewport='{viewport}'", file=sys.stderr)
        sys.exit(1)

    line = _pipe_row(row)
    print(line)
    return line


def cmd_baseline_promote(
    artifact_id: int,
    *,
    db_path: Optional[str] = None,
) -> None:
    """Promote a candidate_baseline to baseline_image."""
    if artifact_id is None:
        print("Usage: qa baseline-promote <artifact-id>", file=sys.stderr)
        sys.exit(2)

    conn = connect(path=db_path)
    try:
        # Verify it is a candidate_baseline
        art_type = query_scalar(conn, "SELECT artifact_type FROM qa_artifacts WHERE id = %s", (artifact_id,))
        if art_type is None:
            print(f"Error: artifact {artifact_id} not found", file=sys.stderr)
            sys.exit(1)
        if art_type != "candidate_baseline":
            print(f"Error: artifact {artifact_id} is '{art_type}', not 'candidate_baseline'", file=sys.stderr)
            sys.exit(1)

        # Get metadata to derive the baseline storage path
        meta_str = query_scalar(conn, "SELECT metadata FROM qa_artifacts WHERE id = %s", (artifact_id,))
        meta = json.loads(meta_str) if meta_str else {}
        route = meta.get("route", "")
        viewport = meta.get("viewport", "")

        # Parse viewport WxH
        parts = viewport.split("x")
        width = int(parts[0]) if len(parts) >= 2 else 0
        height = int(parts[1]) if len(parts) >= 2 else 0

        bl_path = _baseline_path(route, width, height)

        # Update the artifact record
        conn.execute(
            "UPDATE qa_artifacts SET artifact_type = 'baseline_image', artifact_handle = %s WHERE id = %s",
            (serialize_handle(local_handle(bl_path)), artifact_id),
        )
        conn.commit()
    finally:
        conn.close()

    print(f"Promoted artifact {artifact_id} to baseline_image at {bl_path}")
