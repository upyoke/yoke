"""Snapshot pre-warm helper for the done-transition engine.

Extracted from :mod:`yoke_core.engines.done_transition_runner` to keep
that module under its 350-line file-line cap. The single responsibility
is: after a commit lands, build (or look up) the ``path_snapshots`` row
for the project's new HEAD so subsequent activate / boundary callers do
not hit a cold-start miss before the global ``post-commit`` hook has
fired.

Failures here are advisory — a snapshot miss does not roll back the
done-transition; the next ``path-claim-activate`` call will surface a
clearer error if it matters.
"""

from __future__ import annotations

import subprocess


def ensure_snapshot_for_item(item_id: int) -> None:
    """Pre-warm the path-snapshot cache for the item's project at HEAD."""
    try:
        from yoke_core.domain import db_backend, db_helpers
        from yoke_core.domain.path_snapshots import ensure_snapshot_at
        from yoke_core.domain.project_checkout_locations import checkout_for_project_id

        conn = db_helpers.connect()
        try:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            project_row = conn.execute(
                "SELECT project_id FROM items "
                f"WHERE id = {p}",
                (item_id,),
            ).fetchone()
            project_id = (
                int(project_row[0]) if project_row and project_row[0]
                else 1
            )
            checkout = checkout_for_project_id(project_id)
            if checkout is None:
                return
            git_cmd = ["git", "-C", str(checkout), "rev-parse", "HEAD"]
            head = subprocess.run(
                git_cmd,
                capture_output=True, text=True, check=False,
            )
            if head.returncode == 0 and head.stdout.strip():
                ensure_snapshot_at(conn, project_id, head.stdout.strip())
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        print(f"  Note: ensure_snapshot_at advisory: {exc}")


__all__ = ["ensure_snapshot_for_item"]
