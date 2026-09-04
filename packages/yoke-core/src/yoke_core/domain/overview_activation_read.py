"""Signal derivation and monotone latch for the Overview activation modules.

The read behind ``overview.activation.get``: one pass over the universe's
own tables derives every activation module's state server-side, latches
newly satisfied modules into ``overview_activation_facts``, and reads the
calling actor's dismissal preferences.

Module signals (all engine-owned reads; the one host-supplied fact is the
hosted machine connection, forwarded verbatim in ``host_facts``):

* ``finish_installation_wizard`` — required pair is a connected machine
  plus a first ``projects`` row. A machine is connected when the universe
  lists a registered machine
  (:mod:`yoke_core.domain.overview_machine_activation`) or the host says so;
  the checklist row counts and names the registered machines. GitHub
  (``project_github_repo_bindings`` with a non-revoked status) and hosting
  (an ``aws-admin`` ``project_capabilities`` row — declared, no verifier
  writes ``verified_at`` today) are the recommended tail.
* ``connect_harness`` — answered per registered machine, never for the
  universe: each machine lists the harnesses that ran from it and its own
  hook health, latched per ``(machine, module)``. The module reads
  activated only when every listed machine has connected a harness, so a
  machine that registered a relay and ran nothing stays "next up" on its
  own account instead of inheriting another machine's history.
* ``run_onboard`` — an onboarding checklist run with no open rows, or one
  its project's deployments superseded
  (:mod:`yoke_core.domain.overview_onboard_progress`).
* ``first_deploy`` — any ``deployment_runs`` row with status succeeded.

Latched activation is monotone: once a module's signal has been observed
satisfied, the fact row keeps it activated even if the signal later
disappears. Missing optional tables read as "no signal", never an error,
so the derivation works against a universe born before those surfaces.

The harness module's per-target hook health is deliberately NOT latched —
it is a live sub-signal derived beside the latch by
:mod:`yoke_core.domain.overview_harness_hook_health`, because a harness
whose hook approval was re-keyed stops firing hooks again and the operator
needs to see that.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.harness_machine_state import read_harness_machine_reports
from yoke_core.domain.overview_machine_activation import (
    every_machine_has_harness,
    machine_module_rows,
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
MODULE_FIRST_DEPLOY = "first_deploy"

#: Stable module keys in activation order: a module renders its
#: next-action copy only when every earlier module is activated.
MODULE_KEYS: Tuple[str, ...] = (
    MODULE_FINISH_INSTALLATION_WIZARD,
    MODULE_CONNECT_HARNESS,
    MODULE_RUN_ONBOARD,
    MODULE_FIRST_DEPLOY,
)

#: Modules latched once for the universe. The harness module is latched
#: per machine instead and derives its state from those rows.
UNIVERSE_LATCH_KEYS: Tuple[str, ...] = (
    MODULE_FINISH_INSTALLATION_WIZARD,
    MODULE_RUN_ONBOARD,
    MODULE_FIRST_DEPLOY,
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
            conn, read_harness_machine_reports(conn), actor_id=actor_id,
        ),
    )
    directories = [
        {"slug": str(row[0]), "workspace": row[1]}
        for row in conn.execute(
            "SELECT p.slug, s.workspace FROM projects p "
            "LEFT JOIN LATERAL ("
            "  SELECT workspace FROM harness_sessions h "
            "  WHERE h.project_id = p.id "
            "  ORDER BY h.last_heartbeat DESC LIMIT 1"
            ") s ON TRUE ORDER BY p.id"
        ).fetchall()
    ]
    return {
        "projects_exist": bool(directories),
        "github_connected": _guarded_exists(
            conn, "project_github_repo_bindings",
            "SELECT 1 FROM project_github_repo_bindings "
            "WHERE status <> 'revoked'",
        ),
        "hosting_declared": _guarded_exists(
            conn, "project_capabilities",
            "SELECT 1 FROM project_capabilities WHERE type = 'aws-admin'",
        ),
        "machines": machines,
        "project_directories": directories,
        "onboard_progress": read_onboard_progress(conn),
        "deploy_succeeded": _guarded_exists(
            conn, "deployment_runs",
            "SELECT 1 FROM deployment_runs WHERE status = 'succeeded'",
        ),
    }


def latch_activations(
    conn: Any, satisfied: Dict[str, bool],
) -> Dict[str, str]:
    """Latch newly satisfied universe modules; return ``{module_key: activated_at}``.

    Monotone and idempotent: an existing fact row is never touched, a
    satisfied module missing its row gains one, and nothing is deleted.
    Only universe-latched keys are read back, so a row written for a key
    that has since moved to the per-machine latch is inert.
    """
    latched = {
        str(row[0]): row[1]
        for row in conn.execute(
            "SELECT module_key, activated_at FROM overview_activation_facts"
        ).fetchall()
        if str(row[0]) in UNIVERSE_LATCH_KEYS
    }
    now = iso8601_now()
    missing = [
        key for key in UNIVERSE_LATCH_KEYS
        if satisfied.get(key) and key not in latched
    ]
    for key in missing:
        conn.execute(
            "INSERT INTO overview_activation_facts (module_key, activated_at) "
            "VALUES (%s, %s) ON CONFLICT (module_key) DO NOTHING",
            (key, now),
        )
        latched[key] = now
    if missing:
        conn.commit()
    return latched


def read_dismissed_modules(conn: Any, actor_id: Optional[int]) -> set:
    if actor_id is None:
        return set()
    rows = conn.execute(
        "SELECT pref_key FROM actor_ui_preferences "
        "WHERE actor_id = %s AND pref_key LIKE %s",
        (actor_id, DISMISS_PREF_PREFIX + "%"),
    ).fetchall()
    keys = {str(row[0])[len(DISMISS_PREF_PREFIX):] for row in rows}
    return {key for key in keys if key in MODULE_KEYS}


def _wizard_submodules(
    signals: Dict[str, Any], machine_connected: Optional[bool],
) -> List[Dict[str, Any]]:
    """The installation-wizard checklist rows, in wizard order."""
    machines = signals["machines"]
    machine_detail = (
        None if machine_connected is not None or machines
        else "no host machine fact supplied"
    )
    return [
        {
            "key": "machine_universe", "label_key": "machine_universe",
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
            "key": "github", "label_key": "github",
            "done": signals["github_connected"], "detail": None,
        },
        {
            "key": "first_project", "label_key": "first_project",
            "done": signals["projects_exist"], "detail": None,
        },
        {
            "key": "hosting", "label_key": "hosting",
            "done": signals["hosting_declared"], "detail": None,
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
    satisfied = {
        MODULE_FINISH_INSTALLATION_WIZARD: (
            submodules[0]["done"] and signals["projects_exist"]
        ),
        MODULE_RUN_ONBOARD: run_is_complete(signals["onboard_progress"]),
        MODULE_FIRST_DEPLOY: signals["deploy_succeeded"],
    }
    latched = latch_activations(conn, satisfied)
    if every_machine_has_harness(signals["machines"]):
        latched[MODULE_CONNECT_HARNESS] = max(
            str(row["harness_activated_at"]) for row in signals["machines"]
        )
    dismissed = read_dismissed_modules(conn, actor_id)

    modules: List[Dict[str, Any]] = []
    earlier_all_activated = True
    for key in MODULE_KEYS:
        activated = key in latched
        state = (
            STATE_ACTIVATED if activated
            else STATE_IN_PROGRESS if earlier_all_activated
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
            module["fully_complete"] = all(
                row["done"] for row in submodules
            )
        if key == MODULE_RUN_ONBOARD:
            module["onboard"] = signals["onboard_progress"]
        if key == MODULE_CONNECT_HARNESS:
            module["machines"] = _harness_machines(signals["machines"])
            module["projects"] = signals["project_directories"]
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
    "MODULE_FIRST_DEPLOY",
    "MODULE_KEYS",
    "MODULE_RUN_ONBOARD",
    "STATE_ACTIVATED",
    "STATE_IN_PROGRESS",
    "STATE_NOT_STARTED",
    "UNIVERSE_LATCH_KEYS",
    "compute_activation",
    "latch_activations",
    "read_dismissed_modules",
    "read_signals",
]
