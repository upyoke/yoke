"""Frontier candidate delivery is scoped by landing and environment."""

import json
import sqlite3

from yoke_core.domain.deployment_run_item_delivery import candidate_delivery_items


def _snapshot(item_id, project_id, merge_sha):
    return json.dumps({
        "answers": [{
            "id": item_id, "project_id": project_id,
            "merge_sha": merge_sha, "state": "contained",
        }],
    })


def _run(run_id, environment, status, item_id, project_id, merge_sha):
    return {
        "id": run_id,
        "target_environment": environment,
        "status": status,
        "candidate_containment": _snapshot(item_id, project_id, merge_sha),
    }


def test_repeated_candidates_keep_one_delivery_per_landing_and_environment():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE environments (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE deployment_runs (
            id TEXT PRIMARY KEY, target_environment_id INTEGER,
            status TEXT, completed_at TEXT, candidate_containment TEXT
        );
        INSERT INTO environments VALUES (1, 'stage'), (2, 'prod');
    """)

    def record(run, completed_at=""):
        env_id = {"stage": 1, "prod": 2}[run["target_environment"]]
        conn.execute(
            "INSERT INTO deployment_runs VALUES (?, ?, ?, ?, ?)",
            (run["id"], env_id, run["status"], completed_at,
             run["candidate_containment"]),
        )

    first_stage = _run("stage-first", "stage", "succeeded", 51, 1, "landing-a")
    later_stage = _run("stage-later", "stage", "executing", 51, 1, "landing-a")
    production = _run("prod-first", "prod", "executing", 51, 1, "landing-a")
    record(first_stage, "2026-09-20T12:00:00Z")
    record(later_stage)
    record(production)
    shown = candidate_delivery_items(conn, [first_stage, later_stage, production])
    assert shown["stage-first"] == [{"id": 51, "project_id": 1}]
    assert shown["stage-later"] == []
    assert shown["prod-first"] == [{"id": 51, "project_id": 1}]

    # No QA or member rows are involved: a successful production candidate
    # alone settles this landing in production.
    production["status"] = "succeeded"
    conn.execute(
        "UPDATE deployment_runs SET status='succeeded', completed_at=? WHERE id=?",
        ("2026-09-21T12:00:00Z", "prod-first"),
    )
    later_prod = _run("prod-later", "prod", "executing", 51, 1, "landing-a")
    record(later_prod)
    assert candidate_delivery_items(conn, [later_prod])["prod-later"] == []

    # A new landing of the same item creates a fresh delivery obligation.
    remerged = _run("prod-remerged", "prod", "executing", 51, 1, "landing-b")
    record(remerged)
    assert candidate_delivery_items(conn, [remerged])["prod-remerged"] == [
        {"id": 51, "project_id": 1}
    ]

    # The same numeric item in a bound project is a different attribution.
    platform = _run("platform", "prod", "executing", 51, 2, "landing-a")
    record(platform)
    assert candidate_delivery_items(conn, [platform])["platform"] == [
        {"id": 51, "project_id": 2}
    ]


def test_failed_run_does_not_settle_a_retry():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE environments (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE deployment_runs (
            id TEXT PRIMARY KEY, target_environment_id INTEGER,
            status TEXT, completed_at TEXT, candidate_containment TEXT
        );
        INSERT INTO environments VALUES (1, 'stage');
    """)
    failed = _run("failed", "stage", "failed", 51, 1, "landing-a")
    retry = _run("retry", "stage", "executing", 51, 1, "landing-a")
    conn.execute(
        "INSERT INTO deployment_runs VALUES (?, 1, 'failed', ?, ?)",
        (failed["id"], "2026-09-20T12:00:00Z", failed["candidate_containment"]),
    )
    assert candidate_delivery_items(conn, [failed, retry]) == {
        "failed": [{"id": 51, "project_id": 1}],
        "retry": [{"id": 51, "project_id": 1}],
    }
