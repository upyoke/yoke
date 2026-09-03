"""Attach default human-approval addresses on SQL-seeded deployment flows.

Direct INSERT into ``deployment_flows`` bypasses write-time
``require_human_approval_addresses``. Evaluate-path tests call this after
seed so the gate has roles to consult. Do not use this in tests that
assert fail-closed missing approvers.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from yoke_core.domain import db_backend

DEFAULT_STAGE_APPROVALS = {"roles": ["owner", "operator"], "actors": []}


def attach_default_human_approval_addresses(conn: Any) -> None:
    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute("SELECT id, stages FROM deployment_flows").fetchall()
    for row in rows:
        raw = row["stages"]
        stages = json.loads(raw) if isinstance(raw, str) else list(raw)
        changed = False
        patched = []
        for stage in stages:
            entry = dict(stage)
            if (
                entry.get("step_runner") == "human-approval"
                and "approvals" not in entry
            ):
                entry["approvals"] = dict(DEFAULT_STAGE_APPROVALS)
                changed = True
            patched.append(entry)
        if changed:
            conn.execute(
                f"UPDATE deployment_flows SET stages = {placeholder} "
                f"WHERE id = {placeholder}",
                (json.dumps(patched), row["id"]),
            )
    conn.commit()


class OpenConnection:
    """Keep the fixture-owned connection open across runtime helper calls.

    The approval helpers open and close their own connection; a test driving
    them against a fixture connection must survive that ``close()``.
    """

    def __init__(self, conn: Any):
        self._conn = conn

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def close(self) -> None:
        return None


def yield_seeded_api_db_with_default_approvals() -> Iterator[dict[str, str]]:
    from runtime.api.api_items_test_helpers import make_test_db_fixture
    from runtime.api.fixtures.file_test_db import connect_test_db

    for db in make_test_db_fixture():
        conn = connect_test_db(db["db_path"])
        try:
            attach_default_human_approval_addresses(conn)
        finally:
            conn.close()
        yield db
