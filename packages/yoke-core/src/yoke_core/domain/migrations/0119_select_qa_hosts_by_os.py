"""Convert stored QA host names to OS selection, OS slots and any-of waits.

Test Machines of one kind are identical, so a case selects its host by
``method_config.os`` and ``capability_tags``, or lists ``test_machines`` as
OS slots. Open plan cases, open requirements and live executions' frozen
rosters still name hosts. Each pinned row gets its host's registered
``os``; a name list becomes OS slots with ``driver`` on the old
``test_machine``; ``test_machine_reason`` goes, ``platform`` folds into
``os`` and ``test-machine:*`` capability kinds are stripped. A Command
(``worktree_run``) ran on a host only when it named ``test_machine``, so a
Command with no name and no starting state loses ``os`` and ``platform``,
which selected nothing for it, and keeps running locally. Requirements and
roster entries share one conversion, so the roster a resume rebuilds
matches the stored digest. A rewritten execution's live waits without a
need become any-of needs on the registered hosts of that OS carrying the
case's tags, at the same queue place. A row naming an unregistered host,
or a pinned Command declaring no starting state, cannot be converted and is
left for ``test_machine_name_forbidden`` to refuse at begin. History
(retracted, superseded and waived rows, finished executions, ``qa_runs``)
is untouched, and a second run finds nothing to do.
"""

import hashlib
import json

from yoke_contracts.timestamps import temporal_wire
from yoke_core.domain.db_backend import connection_is_postgres

MINIMUM_SERVING_VERSION = "next-release"

_OPEN = (
    "retracted_at IS NULL AND superseded_by_requirement_id IS NULL "
    "AND waived_at IS NULL"
)
_LIVE_EXECUTIONS = "('active','waiting','walking','awaiting_walk_review')"
_LIVE_WAITS = "('waiting','reserved')"
_PAUSE_REASON = "qa-communication-outcome-unknown:"
_MACHINE_KIND = "test-machine:"
_LOCAL_KEYS = ("os", "platform", "test_machine_reason", "test_machines")
_WAIT_FIELDS = (
    "id", "test_machine", "session_id", "actor_id", "queued_at",
    "qa_plan_execution_id", "state", "resume_command", "rationale",
)


class _Unconvertible(Exception):
    """The row names a host that is not registered, so it stays as stored."""


def _canonical(value):
    return json.dumps(temporal_wire(value), sort_keys=True, separators=(",", ":"))


def _digest(roster):
    """``qa_plan_execution_store.roster_digest``, reproduced exactly."""
    return hashlib.sha256(_canonical(roster).encode("utf-8")).hexdigest()


def _decoded(raw, default, subject):
    if raw is None or raw == "":
        return default
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise ValueError(
            f"{subject} is unreadable JSON, so its Test Machine selection cannot "
            f"be converted: {exc}; repair the row, then rerun migration "
            "0119_select_qa_hosts_by_os"
        ) from exc


def _hosts(conn):
    """Registered host name -> (os, capability tags); unreadable settings refuse."""
    hosts = {}
    for name, settings in conn.execute("SELECT name,settings FROM test_machines").fetchall():
        payload = _decoded(settings, {}, f"Test Machine {name!r} settings")
        system = payload.get("os") if isinstance(payload, dict) else None
        if not isinstance(system, str) or not system:
            raise ValueError(
                f"Test Machine {name!r} settings name no os, so cases pinned to it "
                "cannot select it by OS; set its os with `yoke test-machine "
                "settings-replace`, then rerun migration 0119_select_qa_hosts_by_os"
            )
        tags = str(payload.get("capability_tags") or "")
        hosts[str(name)] = (system, {tag.strip() for tag in tags.split(",") if tag.strip()})
    return hosts


def _host_config(config, hosts):
    config = dict(config)
    pin = config.pop("test_machine", None)
    config.pop("test_machine_reason", None)
    platform = config.pop("platform", None)
    if platform and not config.get("os"):
        config["os"] = platform
    names = config.get("test_machines")
    if isinstance(names, list) and any(isinstance(name, str) for name in names):
        if pin not in names or any(name not in hosts for name in names):
            raise _Unconvertible
        config["test_machines"] = [
            {"os": hosts[name][0], **({"driver": True} if name == pin else {})}
            for name in names
        ]
        config.pop("os", None)
    elif pin is not None:
        if pin not in hosts:
            raise _Unconvertible
        config["os"] = hosts[pin][0]
    return config


def _convert(runner, config, kinds, started, hosts):
    """The converted ``(method_config, kinds)``; raises when a row must stay.

    *started* is whether the row declares a starting state (a host baseline
    or ``inherit``). A Command ran on a host only when it named
    ``test_machine``, so one without a name or a starting state ran locally
    whatever ``os`` it declared. A pinned Command without a starting state
    stays as stored: as ``os`` alone it would read as a local Command, and
    begin refuses it either way.
    """
    if runner == "worktree_run" and not config.get("test_machine"):
        if not started:
            converted = {k: v for k, v in config.items() if k not in _LOCAL_KEYS}
            return converted, _stripped(kinds)
    elif runner == "worktree_run" and not started:
        raise _Unconvertible
    return _host_config(config, hosts), _stripped(kinds)


def _started(baselines, state):
    return bool(baselines) or state == "inherit"


def _stripped(kinds):
    return [kind for kind in kinds if not str(kind).startswith(_MACHINE_KIND)]


def _marker(conn):
    return "%s" if connection_is_postgres(conn) else "?"


def _plan_cases(conn, hosts):
    rows = conn.execute(
        "SELECT c.id,m.runner_id,c.method_config,c.host_baselines,c.starting_state "
        "FROM qa_plan_cases c JOIN qa_methods m ON m.id=c.method_id "
        "JOIN qa_plans p ON p.id=c.plan_id WHERE p.retired_at IS NULL ORDER BY c.id"
    ).fetchall()
    for case_id, runner, raw_config, raw_baselines, state in rows:
        config = _decoded(raw_config, {}, f"QA plan case {case_id} method_config")
        baselines = _decoded(raw_baselines, [], f"QA plan case {case_id} host_baselines")
        try:
            converted, _ = _convert(runner, config, [], _started(baselines, state), hosts)
        except _Unconvertible:
            continue
        if converted != config:
            yield case_id, converted


def _requirements(conn, hosts):
    rows = conn.execute(
        "SELECT id,runner_id,method_config,capability_requirements,host_baseline,"
        "starting_state "
        f"FROM qa_requirements WHERE {_OPEN} ORDER BY id"
    ).fetchall()
    for row_id, runner, raw_config, raw_kinds, baseline, state in rows:
        config = _decoded(raw_config, {}, f"QA requirement {row_id} method_config")
        kinds = _decoded(raw_kinds, [], f"QA requirement {row_id} capability_requirements")
        try:
            converted, stripped = _convert(
                runner, config, kinds, _started(baseline, state), hosts
            )
        except _Unconvertible:
            continue
        if converted != config or stripped != kinds:
            yield row_id, converted, stripped, raw_kinds is not None


def _converted_roster(roster, hosts):
    result = []
    for entry in roster:
        config = entry.get("method_config") or {}
        kinds = list(entry.get("required_capability_kinds") or [])
        try:
            started = _started(entry.get("host_baseline"), entry.get("starting_state"))
            converted, stripped = _convert(entry.get("runner_id"), config, kinds, started, hosts)
        except _Unconvertible:
            result.append(entry)
            continue
        entry = dict(entry, method_config=converted)
        if "required_capability_kinds" in entry:
            entry["required_capability_kinds"] = stripped
        result.append(entry)
    return result


def _executions(conn, hosts):
    rows = conn.execute(
        "SELECT id,roster_json,cursor_ordinal,session_id FROM qa_plan_executions "
        f"WHERE state IN {_LIVE_EXECUTIONS} ORDER BY id"
    ).fetchall()
    for execution_id, raw_roster, cursor, session_id in rows:
        roster = _decoded(raw_roster, [], f"QA plan execution {execution_id} roster_json")
        converted = _converted_roster(roster, hosts)
        if _canonical(converted) != _canonical(roster):
            yield {
                "id": str(execution_id), "roster": converted,
                "cursor": int(cursor or 0), "session_id": str(session_id),
            }


def _derived_id(*parts):
    value = hashlib.sha256("\0".join(map(str, parts)).encode("utf-8")).hexdigest()
    return f"{value[:8]}-{value[8:12]}-{value[12:16]}-{value[16:20]}-{value[20:32]}"


def _case_tags(execution):
    roster = execution["roster"]
    if execution["cursor"] >= len(roster):
        return set()
    tags = (roster[execution["cursor"]].get("method_config") or {}).get("capability_tags")
    return {str(tag).strip() for tag in tags or []}


def _convert_waits(conn, execution, hosts):
    """Turn each NULL-need live wait on a registered host into an any-of need."""
    p = _marker(conn)
    rows = conn.execute(
        f"SELECT {','.join(_WAIT_FIELDS)} FROM qa_test_machine_waits "
        f"WHERE qa_plan_execution_id={p} AND need_id IS NULL AND state IN {_LIVE_WAITS} "
        "ORDER BY test_machine",
        (execution["id"],),
    ).fetchall()
    waits = [dict(zip(_WAIT_FIELDS, row)) for row in rows]
    waits = [wait for wait in waits if str(wait["test_machine"]) in hosts]
    if not waits:
        return
    taken = {
        str(row[0])
        for row in conn.execute(
            f"SELECT test_machine FROM qa_test_machine_waits WHERE session_id={p} "
            f"AND state IN {_LIVE_WAITS}",
            (execution["session_id"],),
        ).fetchall()
    }
    tags = _case_tags(execution)
    by_os = {}
    for wait in waits:
        by_os.setdefault(hosts[str(wait["test_machine"])][0], []).append(wait)
    for system, group in by_os.items():
        spare = [
            name for name in sorted(hosts)
            if hosts[name][0] == system and tags <= hosts[name][1] and name not in taken
        ]
        needs = [_derived_id("need", wait["id"]) for wait in group]
        for wait, need_id in zip(group, needs):
            # The original row stays one alternative unless its host lost a tag.
            settle = (
                "" if tags <= hosts[str(wait["test_machine"])][1]
                else ",state='cancelled',settled_at=CURRENT_TIMESTAMP"
            )
            conn.execute(
                f"UPDATE qa_test_machine_waits SET need_id={p}{settle} WHERE id={p}",
                (need_id, wait["id"]),
            )
        for index, name in enumerate(spare):
            wait = group[index % len(group)]
            conn.execute(
                "INSERT INTO qa_test_machine_waits(id,test_machine,session_id,actor_id,"
                "queued_at,qa_plan_execution_id,state,resume_command,rationale,need_id) "
                f"VALUES({p},{p},{p},{p},{p},{p},'waiting',{p},{p},{p})",
                (
                    _derived_id("wait", wait["id"], name), name, wait["session_id"],
                    wait["actor_id"], wait["queued_at"], wait["qa_plan_execution_id"],
                    wait["resume_command"], wait["rationale"], needs[index % len(group)],
                ),
            )
            taken.add(name)


def _pending(conn):
    hosts = _hosts(conn)
    return (
        hosts,
        list(_plan_cases(conn, hosts)),
        list(_requirements(conn, hosts)),
        list(_executions(conn, hosts)),
    )


def apply(conn):
    """Rewrite open cases, requirements, rosters and live waits in place."""
    p = _marker(conn)
    hosts, cases, requirements, executions = _pending(conn)
    for case_id, config in cases:
        conn.execute(
            f"UPDATE qa_plan_cases SET method_config={p},updated_at=CURRENT_TIMESTAMP "
            f"WHERE id={p}",
            (_canonical(config), case_id),
        )
    for row_id, config, kinds, had_kinds in requirements:
        conn.execute(
            f"UPDATE qa_requirements SET method_config={p},capability_requirements={p} "
            f"WHERE id={p}",
            (_canonical(config), json.dumps(kinds) if had_kinds else None, row_id),
        )
    for execution in executions:
        conn.execute(
            f"UPDATE qa_plan_executions SET roster_json={p},roster_digest={p} WHERE id={p}",
            (_canonical(execution["roster"]), _digest(execution["roster"]), execution["id"]),
        )
        _convert_waits(conn, execution, hosts)


def invariants(conn):
    """Only rows naming an unregistered host may still carry a host name."""
    _, cases, requirements, executions = _pending(conn)
    for table, rows in (
        ("qa_plan_cases", cases),
        ("qa_requirements", requirements),
        ("qa_plan_executions", executions),
    ):
        ids = [str(row["id"] if isinstance(row, dict) else row[0]) for row in rows]
        assert not ids, (
            f"open {table} rows {', '.join(ids)} still select Test Machines by "
            "name; rerun migration 0119_select_qa_hosts_by_os"
        )
