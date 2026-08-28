"""Remove the organization override for repeated message injection."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _column_exists, _table_exists


MINIMUM_SERVING_VERSION = NEXT_RELEASE
_RETIRED_FLEET_KEY = "reinject_until_acknowledged"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _document(raw: Any, *, org_id: int) -> dict[str, Any]:
    try:
        document = json.loads(str(raw or "{}"))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"organization {org_id} settings are not valid JSON; repair the row "
            "before boot convergence"
        ) from exc
    if not isinstance(document, dict):
        raise ValueError(
            f"organization {org_id} settings must be an object before convergence"
        )
    return document


def _without_reinjection_override(document: dict[str, Any]) -> bool:
    fleet = document.get("fleet")
    if not isinstance(fleet, dict) or _RETIRED_FLEET_KEY not in fleet:
        return False
    del fleet[_RETIRED_FLEET_KEY]
    if not fleet:
        del document["fleet"]
    return True


def apply(conn: Any) -> None:
    if not _table_exists(conn, "organizations") or not _column_exists(
        conn, "organizations", "settings"
    ):
        return
    marker = _p(conn)
    rows = conn.execute("SELECT id,settings FROM organizations ORDER BY id").fetchall()
    for row in rows:
        org_id = int(row[0])
        document = _document(row[1], org_id=org_id)
        if _without_reinjection_override(document):
            conn.execute(
                f"UPDATE organizations SET settings={marker} WHERE id={marker}",
                (json.dumps(document, sort_keys=True), org_id),
            )


def invariants(conn: Any) -> None:
    if not _table_exists(conn, "organizations") or not _column_exists(
        conn, "organizations", "settings"
    ):
        return
    rows = conn.execute("SELECT id,settings FROM organizations ORDER BY id").fetchall()
    for row in rows:
        document = _document(row[1], org_id=int(row[0]))
        fleet = document.get("fleet")
        assert not isinstance(fleet, dict) or _RETIRED_FLEET_KEY not in fleet, (
            "organization message reinjection overrides must be removed"
        )


__all__ = ["MINIMUM_SERVING_VERSION", "apply", "invariants"]
