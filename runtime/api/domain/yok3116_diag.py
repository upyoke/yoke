"""TEMP DIAGNOSTIC (YOK-3116): shared client-side snapshot helper.

Instruments the CI-only, deterministic "project not found" failure in the
HTTPS-driver deploy pipeline tests. Prints only nonsecret project
existence/id and resolved database identity, tagged with the xdist worker
id, so a single instrumented remote run can distinguish wrong
database/tenant routing from a fixture-deletion or reset race. Remove this
module and its call sites once the root cause is fixed.
"""

from __future__ import annotations

import os
import sys


def diag(conn, label: str, project: str) -> None:
    worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
    db = conn.execute("SELECT current_database()").fetchone()
    row = conn.execute(
        "SELECT id, slug FROM projects WHERE slug=%s", (project,)
    ).fetchone()
    print(
        f"[YOK-3116-DIAG] {label} worker={worker} "
        f"db={db[0] if db else None!r} project_row={row}",
        file=sys.stderr,
    )


__all__ = ["diag"]
