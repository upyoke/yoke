"""Signal derivation and latches for the Overview activation modules.

``overview.activation.get`` first latches the live machines' signals. The
wizard and harness steps answer for the viewer, using the earliest latch
across their live and retired machines. An unscoped local universe aggregates
every machine. The wizard can also complete on the viewer's durable host
machine fact when a registered machine has yet to supply a timestamp.

The wizard's recommended GitHub and hosting rows reflect current bindings
and capabilities. The harness list shows each live machine's connection
history and current hook health. Pending machines keep their own next step.

Only ``run_onboard`` latches for the universe. The project's first onboarding
item completing or a deployment superseding the run satisfies that step.
Dismissals are preferences scoped to the calling actor.
"""

from __future__ import annotations

from datetime import datetime

from typing import Any, Dict, List, Optional, Tuple

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.db_helpers import instant_parameter, utc_now
from yoke_core.domain.harness_machine_state import read_harness_machine_reports
from yoke_core.domain.overview_machine_activation import (
    machine_module_rows,
    read_owner_activations,
    read_registered_machines,
)
from yoke_core.domain.overview_onboard_progress import (
    read_onboard_progress,
    run_is_complete,
)
from yoke_core.domain.schema_common import _table_exists

MODULE_FINISH_INSTALLATION_WIZARD = "finish_installation_wizard"
MODULE_CONNECT_HARNESS = "connect_harness"
MODULE_RUN_ONBOARD = "run_onboard"

#: Stable module keys in activation order: a module renders its
#: next-action copy only when every earlier module is activated.
MODULE_KEYS: Tuple[str, ...] = (
    MODULE_FINISH_INSTALLATION_WIZARD,
    MODULE_CONNECT_HARNESS,
    MODULE_RUN_ONBOARD,
)

STATE_NOT_STARTED = "not_started"
STATE_IN_PROGRESS = "in_progress"
STATE_ACTIVATED = "activated"

#: ``actor_ui_preferences.pref_key`` prefix for per-module dismissals.
DISMISS_PREF_PREFIX = "overview.module.dismissed."


def _exists(conn: Any, sql: str, params: tuple = ()) -> bool:
    row = conn.execute(f"SELECT EXISTS({sql})", params).fetchone()
    return bool(row[0]) if row is not None else False


def _guarded_exists(conn: Any, table: str, sql: str) -> bool:
    """EXISTS over a table that may predate this universe's schema."""
    if not _table_exists(conn, table):
        return False
    return _exists(conn, sql)


def read_signals(conn: Any, actor_id: Optional[int] = None) -> Dict[str, Any]:
    """Read every engine-owned activation signal in one pass.

    ``actor_id`` scopes the machine reads to the viewer's own machines, so
    an organization member is never shown, or blocked by, another member's
    box (``None`` lists every machine).
    """
    machines = machine_module_rows(
        conn,
        read_registered_machines(
            conn,
            read_harness_machine_reports(conn),
            actor_id=actor_id,
        ),
    )
    return {
        "github_connected": _guarded_exists(
            conn,
            "project_github_repo_bindings",
            "SELECT 1 FROM project_github_repo_bindings WHERE status <> 'revoked'",
        ),
        "hosting_declared": _guarded_exists(
            conn,
            "project_capabilities",
            "SELECT 1 FROM project_capabilities WHERE type = 'aws-admin'",
        ),
        "machines": machines,
        "onboard_progress": read_onboard_progress(conn),
    }


def latch_run_onboard(conn: Any, satisfied: bool) -> Optional[datetime]:
    """Preserve and return the universe's first Run onboard completion."""
    select_latch = (
        "SELECT activated_at FROM overview_activation_facts "
        "WHERE module_key = 'run_onboard'"
    )
    row = conn.execute(select_latch).fetchone()
    if row is None and satisfied:
        conn.execute(
            "INSERT INTO overview_activation_facts (module_key, activated_at) "
            "VALUES ('run_onboard', %s) ON CONFLICT (module_key) DO NOTHING",
            (instant_parameter(conn, utc_now()),),
        )
        conn.commit()
        row = conn.execute(select_latch).fetchone()
    return parse_instant(row[0]) if row is not None else None


def read_dismissed_modules(conn: Any, actor_id: Optional[int]) -> set:
    if actor_id is None:
        return set()
    rows = conn.execute(
        "SELECT pref_key FROM actor_ui_preferences "
        "WHERE actor_id = %s AND pref_key LIKE %s",
        (actor_id, DISMISS_PREF_PREFIX + "%"),
    ).fetchall()
    keys = {str(row[0])[len(DISMISS_PREF_PREFIX) :] for row in rows}
    return {key for key in keys if key in MODULE_KEYS}


def _wizard_submodules(
    signals: Dict[str, Any],
    machine_connected: Optional[bool],
) -> List[Dict[str, Any]]:
    """The installation-wizard checklist rows, in wizard order."""
    machines = signals["machines"]
    machine_detail = (
        None
        if machine_connected is not None or machines
        else "no host machine fact supplied"
    )
    return [
        {
            "key": "machine_universe",
            "label_key": "machine_universe",
            "done": machine_connected is True or bool(machines),
            "detail": machine_detail,
            "machines": [
                {
                    "machine_id": row["machine_id"],
                    "name": row["name"],
                    "connected_at": row["connected_at"],
                }
                for row in machines
            ],
        },
        {
            "key": "github",
            "label_key": "github",
            "done": signals["github_connected"],
            "detail": None,
        },
        {
            "key": "hosting",
            "label_key": "hosting",
            "done": signals["hosting_declared"],
            "detail": None,
        },
    ]


def _harness_machines(machines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The harness module's per-machine rows, each with its own state."""
    return [
        {
            "machine_id": row["machine_id"],
            "name": row["name"],
            "surfaces": row["surfaces"],
            "relay_state": row["relay_state"],
            "last_seen_at": row["last_seen_at"],
            "state": (
                STATE_ACTIVATED if row["harness_activated_at"] else STATE_IN_PROGRESS
            ),
            "activated_at": row["harness_activated_at"],
            "connected": row["connected"],
            "harnesses": row["harnesses"],
            "targets": row["targets"],
        }
        for row in machines
    ]


def compute_activation(
    conn: Any,
    machine_connected: Optional[bool],
    actor_id: Optional[int],
) -> Dict[str, Any]:
    """Derive the full activation-module payload, latching as a side effect."""
    signals = read_signals(conn, actor_id)
    submodules = _wizard_submodules(signals, machine_connected)
    latched: Dict[str, Optional[datetime]] = dict(read_owner_activations(conn, actor_id))
    if submodules[0]["done"]:
        latched.setdefault(MODULE_FINISH_INSTALLATION_WIZARD, None)
    onboard_at = latch_run_onboard(conn, run_is_complete(signals["onboard_progress"]))
    if onboard_at is not None:
        latched[MODULE_RUN_ONBOARD] = onboard_at
    dismissed = read_dismissed_modules(conn, actor_id)

    modules: List[Dict[str, Any]] = []
    earlier_all_activated = True
    for key in MODULE_KEYS:
        activated = key in latched
        state = (
            STATE_ACTIVATED
            if activated
            else STATE_IN_PROGRESS
            if earlier_all_activated
            else STATE_NOT_STARTED
        )
        module: Dict[str, Any] = {
            "key": key,
            "state": state,
            "activated_at": latched.get(key),
            "dismissed": key in dismissed,
            "submodules": [],
        }
        if key == MODULE_FINISH_INSTALLATION_WIZARD:
            module["submodules"] = submodules
            module["fully_complete"] = all(row["done"] for row in submodules)
        if key == MODULE_RUN_ONBOARD:
            module["onboard"] = signals["onboard_progress"]
        if key == MODULE_CONNECT_HARNESS:
            module["machines"] = _harness_machines(signals["machines"])
        modules.append(module)
        earlier_all_activated = earlier_all_activated and activated
    return {
        "modules": modules,
        "dismiss_available": actor_id is not None,
    }


__all__ = [
    "DISMISS_PREF_PREFIX",
    "MODULE_CONNECT_HARNESS",
    "MODULE_FINISH_INSTALLATION_WIZARD",
    "MODULE_KEYS",
    "MODULE_RUN_ONBOARD",
    "STATE_ACTIVATED",
    "STATE_IN_PROGRESS",
    "STATE_NOT_STARTED",
    "compute_activation",
    "latch_run_onboard",
    "read_dismissed_modules",
    "read_signals",
]
