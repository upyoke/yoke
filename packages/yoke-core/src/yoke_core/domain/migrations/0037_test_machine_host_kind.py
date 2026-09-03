"""Make every test machine declare the kind of host its operations drive."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.machine_config.test_machine import (
    MAC_SSH_HOST_KIND,
    TEST_MACHINE_CAPABILITY_PREFIX,
    TEST_MACHINE_HOST_KINDS,
)

from yoke_core.domain import db_backend
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists

# The settings contract refuses unknown keys, so a build written before this
# entry cannot read a document that carries `host_kind` -- it reports the whole
# capability invalid rather than ignoring one field. The floor says so instead
# of leaving a rolled-back container to discover it against a live fleet.
MINIMUM_SERVING_VERSION = NEXT_RELEASE

SETTING_KEY = "host_kind"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _rows(conn: Any) -> list[tuple[int, str, dict[str, Any]]]:
    marker = _p(conn)
    rows = conn.execute(
        "SELECT project_id,type,COALESCE(settings,'{}') "
        f"FROM project_capabilities WHERE type LIKE {marker} "
        "ORDER BY project_id,type",
        (TEST_MACHINE_CAPABILITY_PREFIX + "%",),
    ).fetchall()
    parsed: list[tuple[int, str, dict[str, Any]]] = []
    for raw in rows:
        capability_type = str(raw[1])
        try:
            settings = json.loads(str(raw[2] or "{}"))
        except ValueError as exc:
            raise ValueError(
                f"test-machine settings for {capability_type!r} are not valid "
                "JSON; repair the row before boot convergence"
            ) from exc
        if not isinstance(settings, dict):
            raise ValueError(
                f"test-machine settings for {capability_type!r} are not an "
                "object; repair the row before boot convergence"
            )
        parsed.append((int(raw[0]), capability_type, settings))
    return parsed


def apply(conn: Any) -> None:
    """Declare the one host kind every registered machine already is.

    Every machine registered before this entry is reached over SSH to a macOS
    host, because that is the only implementation the product has ever had.
    Writing it down is what lets a second kind arrive without every operation
    guessing.
    """
    if not _table_exists(conn, "project_capabilities"):
        return
    marker = _p(conn)
    for project_id, capability_type, settings in _rows(conn):
        declared = str(settings.get(SETTING_KEY) or "").strip()
        if declared in TEST_MACHINE_HOST_KINDS:
            continue
        if declared:
            raise ValueError(
                f"test-machine {capability_type!r} declares unknown "
                f"{SETTING_KEY} {declared!r}; reconcile the row before "
                "boot convergence"
            )
        settings[SETTING_KEY] = MAC_SSH_HOST_KIND
        conn.execute(
            "UPDATE project_capabilities SET settings="
            f"{marker} WHERE project_id={marker} AND type={marker}",
            (
                json.dumps(settings, separators=(",", ":"), sort_keys=True),
                project_id,
                capability_type,
            ),
        )


def invariants(conn: Any) -> None:
    if not _table_exists(conn, "project_capabilities"):
        return
    for _project_id, capability_type, settings in _rows(conn):
        assert settings.get(SETTING_KEY) in TEST_MACHINE_HOST_KINDS, (
            f"test machine {capability_type!r} must declare a registered {SETTING_KEY}"
        )


__all__ = [
    "MINIMUM_SERVING_VERSION",
    "SETTING_KEY",
    "apply",
    "invariants",
]
