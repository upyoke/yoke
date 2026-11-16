"""Rename stored WSL-backed Test Machines from os ``windows`` to ``wsl``.

Until this entry, ``windows`` was the only Windows kind and every such machine
ran its SSH commands inside WSL2. ``windows`` now means native Windows, so each
stored ``test-machine:*`` row with os ``windows`` becomes ``wsl``. Settings are
rewritten with the canonical serializer the settings writer uses, so the
as-read settings token stays comparable. Replay is a no-op.
"""

import json

from yoke_core.domain.db_backend import connection_is_postgres


def apply(conn):
    """Convert every stored os=windows Test Machine to os=wsl."""
    p = "%s" if connection_is_postgres(conn) else "?"
    rows = conn.execute(
        f"SELECT id, settings FROM project_capabilities WHERE type LIKE {p}",
        ("test-machine:%",),
    ).fetchall()
    for row_id, raw in rows:
        try:
            document = json.loads(str(raw or "{}"))
        except ValueError:
            continue
        if not isinstance(document, dict) or document.get("os") != "windows":
            continue
        document["os"] = "wsl"
        conn.execute(
            f"UPDATE project_capabilities SET settings={p} WHERE id={p}",
            (json.dumps(document, separators=(",", ":"), sort_keys=True), row_id),
        )
