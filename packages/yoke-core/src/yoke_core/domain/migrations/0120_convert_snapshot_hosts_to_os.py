"""Convert host pins in frozen deployment QA snapshots to OS form.

0119 converted open plan cases, open requirements and live rosters but not
the frozen case copies in ``requirement_snapshot``. Stage materialization
digests every frozen case through the current validator, which refuses a
stored host name, so a pinned copy refused even when its requirement rows
were already OS-only and passed. This rewrites every copy that holds cases:
``deployment_runs`` ``selections[].cases[]`` and ``plan_groups{}.cases[]``
(every status, since takeover and retry read old runs) and
``deployment_run_items`` ``requirements[]``.

This is the first migration that loads a sibling: it reuses 0119's
``_hosts``, ``_convert``, ``_started``, ``_canonical`` and ``_pending`` by
loading that file through ``load_migration_module``, so a snapshot case and
its 0119-converted requirement convert identically and digest alike. That
includes ``_convert`` stripping ``os`` and ``platform`` from a local Command
with no starting state. 0119 and 0120 can therefore only be folded into the
baseline together; folding 0119 alone fails loudly when 0120 loads.

The obsolete member ``plans[]`` copy is cut, not converted: its ``plans``
key is deleted from every run-item snapshot. The failed runs composed from
that old model (or whose run-level shared-plan rows carry no ``group_id``)
cannot be retried through plan groups, so they move from ``failed`` to
``cancelled`` with a ``DeploymentRunTerminalized`` audit event, selected by
the query the removed retry guard used.

As in 0119, a case pinned to an unregistered host stays as stored and keeps
refusing at begin with ``test_machine_name_forbidden``; ``qa_runs`` and
finished executions are untouched. Only changed entries are replaced, a null
``method_config`` or kinds list stays null, and a second run finds nothing.
"""

import json
from pathlib import Path

from yoke_contracts.timestamps import utc_now
from yoke_core.domain.deployment_run_terminalization import (
    append_terminalization_event,
)
from yoke_core.domain.migration_history import load_migration_module

MINIMUM_SERVING_VERSION = "next-release"

_SIBLING = Path(__file__).with_name("0119_select_qa_hosts_by_os.py")
_HOSTS_BY_OS = load_migration_module(_SIBLING, _SIBLING.stem)
_NAME = "0120_convert_snapshot_hosts_to_os"
_CANCEL_REASON = "old QA model; retry impossible after 0120"
_OLD_MODEL_FAILED_RUNS = (
    "SELECT DISTINCT d.id FROM deployment_runs d WHERE d.status='failed' "
    "AND (EXISTS (SELECT 1 FROM deployment_run_items m WHERE m.run_id=d.id "
    "AND jsonb_array_length(COALESCE(NULLIF(m.requirement_snapshot,'')::jsonb->'plans',"
    "'[]'::jsonb))>0 AND EXISTS (SELECT 1 FROM qa_requirements q WHERE "
    "q.deployment_run_id=d.id AND q.deployment_member_item_id=m.item_id "
    "AND q.plan_id IN (SELECT (p->'plan'->>'id')::bigint FROM jsonb_array_elements("
    "NULLIF(m.requirement_snapshot,'')::jsonb->'plans') p))) "
    "OR EXISTS (SELECT 1 FROM qa_requirements s WHERE "
    "s.deployment_run_id=d.id AND s.deployment_member_item_id IS NULL AND s.plan_id IS NOT NULL "
    "AND jsonb_typeof(NULLIF(s.execution_target_json,'')::jsonb->'deployment'->'shared_plan')"
    "='object' AND NOT jsonb_exists(NULLIF(s.execution_target_json,'')::jsonb->'deployment'"
    "->'shared_plan','group_id'))) ORDER BY d.id"
)


def _entry(entry, hosts, *, kinds_key, baseline_key):
    """The converted copy of one frozen case, or ``None`` when it stays."""
    m = _HOSTS_BY_OS
    config = m._decoded(entry.get("method_config"), {}, "frozen case method_config")
    raw_kinds = entry.get(kinds_key)
    kinds = list(raw_kinds or [])
    started = m._started(entry.get(baseline_key), entry.get("starting_state"))
    try:
        converted, stripped = m._convert(
            entry.get("runner_id"), config, kinds, started, hosts
        )
    except m._Unconvertible:
        return None
    if converted == config and stripped == kinds:
        return None
    result = dict(entry, method_config=converted)
    if raw_kinds is not None:
        result[kinds_key] = stripped
    return result


def _converted(entries, hosts, **keys):
    """Replace changed entries in place; whether any changed."""
    changed = False
    for index, entry in enumerate(entries if isinstance(entries, list) else []):
        if isinstance(entry, dict):
            converted = _entry(entry, hosts, **keys)
            if converted is not None:
                entries[index] = converted
                changed = True
    return changed


_CASE = {"kinds_key": "required_capability_kinds", "baseline_key": "host_baselines"}
_REQUIREMENT = {"kinds_key": "capability_requirements", "baseline_key": "host_baseline"}


def _run_snapshot(snapshot, hosts):
    changed = False
    for selection in snapshot.get("selections") or []:
        if isinstance(selection, dict):
            changed |= _converted(selection.get("cases"), hosts, **_CASE)
    groups = snapshot.get("plan_groups")
    for group in (groups.values() if isinstance(groups, dict) else []):
        if isinstance(group, dict):
            changed |= _converted(group.get("cases"), hosts, **_CASE)
    return changed


def _item_snapshot(snapshot, hosts):
    changed = _converted(snapshot.get("requirements"), hosts, **_REQUIREMENT)
    if "plans" in snapshot:
        del snapshot["plans"]
        changed = True
    return changed


def _snapshots(conn, sql, subject, rewrite, hosts):
    """Each ``(key, canonical snapshot)`` whose stored copy *rewrite* changes."""
    for *key, raw in conn.execute(sql).fetchall():
        name = f"{subject} {'/'.join(map(str, key))} requirement_snapshot"
        snapshot = _HOSTS_BY_OS._decoded(raw, None, name)
        if isinstance(snapshot, dict) and rewrite(snapshot, hosts):
            yield tuple(key), _HOSTS_BY_OS._canonical(snapshot)


def _pending(conn):
    hosts, cases, requirements, executions = _HOSTS_BY_OS._pending(conn)
    runs = list(_snapshots(
        conn, "SELECT id,requirement_snapshot FROM deployment_runs ORDER BY id",
        "deployment run", _run_snapshot, hosts,
    ))
    items = list(_snapshots(
        conn,
        "SELECT run_id,item_id,requirement_snapshot FROM deployment_run_items "
        "ORDER BY run_id,item_id",
        "deployment run item", _item_snapshot, hosts,
    ))
    return (cases, requirements, executions), runs, items


def _cancel_old_model_runs(conn):
    """Close failed runs no current plan-group retry can resume."""
    for (run_id,) in conn.execute(_OLD_MODEL_FAILED_RUNS).fetchall():
        project_id, project, stage = conn.execute(
            "SELECT d.project_id,p.slug,COALESCE(d.current_stage,'') FROM deployment_runs d "
            "JOIN projects p ON p.id=d.project_id WHERE d.id=%s",
            (run_id,),
        ).fetchone()
        conn.execute(
            "UPDATE deployment_runs SET status='cancelled' WHERE id=%s", (run_id,)
        )
        append_terminalization_event(
            conn, run_id=str(run_id), project=str(project), project_id=int(project_id),
            prior_status="failed", final_status="cancelled", current_stage=str(stage),
            reason=_CANCEL_REASON, actor_id=None, session_id=f"migration:{_NAME}",
            terminalized_at=utc_now(),
        )


def apply(conn):
    """Cancel old-model failed runs, then rewrite every changed snapshot."""
    _cancel_old_model_runs(conn)
    _, runs, items = _pending(conn)
    for (run_id,), snapshot in runs:
        conn.execute(
            "UPDATE deployment_runs SET requirement_snapshot=%s WHERE id=%s",
            (snapshot, run_id),
        )
    for (run_id, item_id), snapshot in items:
        conn.execute(
            "UPDATE deployment_run_items SET requirement_snapshot=%s "
            "WHERE run_id=%s AND item_id=%s",
            (snapshot, run_id, item_id),
        )


def invariants(conn):
    """No stored copy holds a convertible pin, and no member keeps ``plans``."""
    stores, runs, items = _pending(conn)
    named = [
        (table, [str(row["id"] if isinstance(row, dict) else row[0]) for row in rows])
        for table, rows in zip(
            ("qa_plan_cases", "qa_requirements", "qa_plan_executions"), stores
        )
    ]
    named.append(("deployment_runs", [key[0] for key, _ in runs]))
    named.append(("deployment_run_items", ["/".join(map(str, key)) for key, _ in items]))
    for table, ids in named:
        assert not ids, (
            f"{table} rows {', '.join(ids)} still hold a convertible Test Machine "
            f"name or an obsolete member plans copy; rerun migration {_NAME}"
        )
