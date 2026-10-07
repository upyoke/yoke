"""Seed one Frontier dependency-graph state in the disposable render universe.

Run with `yoke dev run -- env YOKE_ENV=render-proof python3 -m
runtime.api.tools.frontier_graph_review STATE`, then serve_workbench_for_review
on that same connection and open /frontier. STATE is one of the six states in
runtime/api/frontier_dependency_states.mjs (today, busy, gates, stuck, wide,
empty), so the served page can be compared with the design those states came
from. These are presentation fixtures: items, dependency edges, holds, live
sessions holding claims, and delivery runs, all read back through the real
list readers. Fixture items use ids from 900000 and fixture keys start with
`fgr-`; seeding a state retires the previous state's fixture items and
sessions, so exactly one state is live at a time.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.api.tools.serve_workbench_for_review import prepare_review_database
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.work_claim_targets import make_item_target
from yoke_core.domain.workflow_registry import resolve_current_workflow_pin
from yoke_core.ui.served_universe_connection import serving_connection

STATES_MODULE = Path(__file__).resolve().parents[1] / "frontier_dependency_states.mjs"
FIXTURE_BASE = 900000
PROJECTS = {
    "YOK": (3, "yoke", "Yoke", 0),
    "PLAT": (11, "platform", "Platform", 10000),
    "BUZ": (12, "buzz", "Buzz", 20000),
}
EXECUTORS = {
    "codex": ("codex", "openai"),
    "claude": ("claude-code", "anthropic"),
    "cursor": ("cursor", "cursor"),
}
ENVIRONMENTS = ("stage", "prod")


def _states() -> dict:
    script = (
        f"import({json.dumps(STATES_MODULE.as_uri())})"
        ".then((m) => process.stdout.write(JSON.stringify(m.FRONTIER_STATES)))"
    )
    out = subprocess.run(
        ["node", "-e", script], check=True, capture_output=True, text=True
    )
    return {state["id"]: state for state in json.loads(out.stdout)}


def _stamp(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _project(ref: str) -> tuple:
    return PROJECTS[ref.split("-")[0]]


def _item_id(ref: str) -> int:
    return FIXTURE_BASE + _project(ref)[3] + int(ref.split("-")[1])


def _environment_id(project_id: int, name: str) -> int:
    return 9100 + project_id * 2 + ENVIRONMENTS.index(name)


def _seed_projects(conn, state_id: str) -> None:
    for prefix, (project_id, slug, name, _) in PROJECTS.items():
        conn.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix, created_at) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
            (project_id, slug, name, prefix, _stamp(days=30)),
        )
        conn.execute(
            "INSERT INTO sites (id, project_id, name, created_at) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (id) DO NOTHING",
            (9000 + project_id, project_id, f"{slug}-site", _stamp(days=30)),
        )
        for environment in ENVIRONMENTS:
            conn.execute(
                "INSERT INTO environments (id, site, project_id, name, created_at) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
                (
                    _environment_id(project_id, environment),
                    9000 + project_id,
                    project_id,
                    environment,
                    _stamp(days=30),
                ),
            )
            # In the stuck state no flow reaches prod: Platform's flow ends at stage.
            status = (
                "disabled"
                if state_id == "stuck" and environment == "prod"
                else "active"
            )
            conn.execute(
                "INSERT INTO deployment_flows (id, project_id, name, stages, status, "
                "target_tier, target_environment_id, takes_delivery_custody, created_at) "
                "VALUES (%s,%s,%s,'[{\"name\":\"deploy\"}]',%s,'persistent',%s,0,%s) "
                "ON CONFLICT (id) DO UPDATE SET status = excluded.status",
                (
                    f"fgr-{slug}-{environment}",
                    project_id,
                    f"{name} {environment}",
                    status,
                    _environment_id(project_id, environment),
                    _stamp(days=30),
                ),
            )


def _retire_fixtures(conn) -> None:
    now = _stamp()
    conn.execute(
        "UPDATE items SET status='cancelled', frozen=0, blocked=0 WHERE id >= %s",
        (FIXTURE_BASE,),
    )
    conn.execute(
        "UPDATE harness_sessions SET ended_at=%s "
        "WHERE session_id LIKE 'fgr-%%' AND ended_at IS NULL",
        (now,),
    )
    conn.execute(
        "UPDATE work_claims SET released_at=%s "
        "WHERE session_id LIKE 'fgr-%%' AND released_at IS NULL",
        (now,),
    )
    conn.execute(
        "DELETE FROM item_dependencies WHERE dependent_item_id >= %s", (FIXTURE_BASE,)
    )


def _seed_item(conn, node: dict, pin: tuple) -> None:
    ref, band = node["ref"], node["band"]
    project_id, slug = _project(ref)[0], _project(ref)[1]
    sequence = int(ref.split("-")[1])
    status = {
        "waiting": "idea",
        "ready": "idea",
        "release": "release",
        "done": "done",
    }.get(band, node["stage"].replace(" ", "-"))
    label, _, reason = (node.get("held") or "").partition(" — ")
    frozen = label.lower().startswith("frozen")
    blocked = label.lower().startswith("blocked")
    deploy = node.get("deploy") or ""
    reaches = node.get("envs") or []
    target = "prod" if "prod" in reaches or "prod not yet" in deploy else None
    target = target or ("stage" if reaches else None)
    conn.execute(
        "INSERT INTO items (id, title, status, priority, project_id, project_sequence, "
        "frozen, blocked, blocked_reason, created_at, updated_at, spec, workflow_id, "
        "workflow_version_id, deployment_flow) "
        "VALUES (%s,%s,%s,'medium',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (id) DO UPDATE SET title=excluded.title, status=excluded.status, "
        "frozen=excluded.frozen, blocked=excluded.blocked, "
        "blocked_reason=excluded.blocked_reason, created_at=excluded.created_at, "
        "updated_at=excluded.updated_at, deployment_flow=excluded.deployment_flow",
        (
            _item_id(ref),
            node["title"],
            status,
            project_id,
            sequence,
            int(frozen),
            int(blocked),
            reason or (label[len("Frozen") :].strip() if frozen else "") or None,
            _stamp(hours=sequence % 23 + 1),
            _stamp(minutes=sequence % 50 + 2),
            f"# {node['title']}\n\nFrontier dependency-graph review fixture.",
            *pin,
            f"fgr-{slug}-{target}" if target else None,
        ),
    )
    if band == "done":
        # Done dates a finish from the transition that put the item there.
        conn.execute(
            "INSERT INTO item_status_transitions (id, item_id, from_status, to_status, "
            "source, project_id, created_at) VALUES (%s,%s,'release','done','review fixture',%s,%s) "
            "ON CONFLICT (id) DO UPDATE SET created_at=excluded.created_at",
            (_item_id(ref), _item_id(ref), project_id, _stamp(hours=sequence % 9 + 1)),
        )
    # Active is earned by a live claim; an Active item with no named session gets one.
    claim = node.get("claim") or ("codex-cli · active" if band == "active" else None)
    if claim:
        surface, mode = claim.split(" · ")
        executor, provider = EXECUTORS[surface.split("-")[0]]
        session_id = f"fgr-{ref}"
        conn.execute(
            "INSERT INTO harness_sessions (session_id, executor, executor_surface, "
            "provider, workspace, project_id, offered_at, last_heartbeat, mode, "
            "current_item_id, ended_at) VALUES (%s,%s,%s,%s,'/tmp/fgr',%s,%s,%s,%s,%s,NULL) "
            "ON CONFLICT (session_id) DO UPDATE SET ended_at=NULL, "
            "last_heartbeat=excluded.last_heartbeat, mode=excluded.mode",
            (
                session_id,
                executor,
                surface,
                provider,
                project_id,
                _stamp(hours=2),
                _stamp(),
                mode,
                _item_id(ref),
            ),
        )
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, scope, claimed_at, "
            "last_heartbeat, reason) VALUES (%s,'item',%s,%s,%s,'review fixture')",
            (
                session_id,
                make_item_target(_item_id(ref)).scope_json(),
                _stamp(hours=2),
                _stamp(),
            ),
        )
    for index, part in enumerate(p for p in deploy.split(" · ") if p):
        environment, _, outcome = part.partition(" ")
        if outcome not in ("✓", "deploying"):
            continue
        run_id = f"fgr-run-{ref}-{environment}"
        conn.execute(
            "INSERT INTO deployment_runs (id, project_id, flow, status, target_tier, "
            "target_environment_id, created_at, started_at, completed_at, current_stage) "
            "VALUES (%s,%s,%s,%s,'persistent',%s,%s,%s,%s,'deploy') "
            "ON CONFLICT (id) DO UPDATE SET status=excluded.status, "
            "created_at=excluded.created_at, completed_at=excluded.completed_at",
            (
                run_id,
                project_id,
                f"fgr-{slug}-{environment}",
                "succeeded" if outcome == "✓" else "executing",
                _environment_id(project_id, environment),
                _stamp(minutes=40 - index * 10),
                _stamp(minutes=40 - index * 10),
                # A finished run is shown only once it records when it finished.
                _stamp(minutes=30 - index * 10) if outcome == "✓" else None,
            ),
        )
        conn.execute(
            "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
            "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            (run_id, _item_id(ref), _stamp(minutes=40)),
        )


def seed(state_id: str) -> str:
    state = _states()[state_id]
    with connect() as conn:
        _seed_projects(conn, state_id)
        _retire_fixtures(conn)
        pin = resolve_current_workflow_pin(conn, "dash")
        for values in state["nodes"]:
            node = dict(zip(("ref", "band", "stage", "title"), values[:4]))
            node.update(values[4] if len(values) > 4 else {})
            if node["band"] != "off" or node["stage"] != "not on this Frontier":
                _seed_item(conn, node, pin)
        for edge in state["edges"]:
            blocker, dependent = edge[0], edge[1]
            conn.execute(
                "INSERT INTO item_dependencies (dependent_item_id, blocking_item_id, "
                "gate_point, satisfaction, source, rationale, created_at) "
                "VALUES (%s,%s,%s,%s,'test',%s,%s)",
                (
                    _item_id(dependent),
                    _item_id(blocker),
                    edge[2] if len(edge) > 2 else "activation",
                    edge[3] if len(edge) > 3 else "fact:merged",
                    state.get("why", {}).get(f"{blocker}>{dependent}", ""),
                    _stamp(),
                ),
            )
    return f"{state_id}: {len(state['nodes'])} items, {len(state['edges'])} edges"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "state", choices=("today", "busy", "gates", "stuck", "wide", "empty")
    )
    arguments = parser.parse_args()
    environment, refusal = serving_connection()
    if environment != "render-proof" or refusal:
        raise SystemExit(
            "frontier_graph_review_requires_render_proof: select the disposable "
            "render-proof connection with YOKE_ENV=render-proof, then retry"
        )
    prepare_review_database()
    print(f"review fixture: {seed(arguments.state)} (render-proof only)")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        raise SystemExit(
            f"frontier_graph_review_seed_failed: {exc}; repair the render-proof "
            "fixture data and retry seeding before starting the review server"
        ) from None
