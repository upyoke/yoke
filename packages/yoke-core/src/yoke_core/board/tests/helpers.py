"""Reusable board-test row inserters."""

from __future__ import annotations

import json

from yoke_core.board.db import BoardDB
from runtime.api.fixtures.file_test_db import connect_test_db


PROJECT_IDS = {"yoke": 1, "buzz": 2}


def project_id(project: object) -> int:
    text = str(project)
    return int(text) if text.isdigit() else PROJECT_IDS.get(text, 1)


def insert_zen_items(db_path: str, items: list) -> None:
    conn = connect_test_db(db_path)
    for item_id, title, project, status, created_at in items:
        conn.execute(
            "INSERT INTO items "
            "(id, title, project_id, project_sequence, status, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (item_id, title, project_id(project), item_id, status, created_at),
        )
    conn.commit()
    conn.close()


def insert_item(db: BoardDB, item_id: int, **kwargs) -> None:
    defaults = {
        "title": f"Item {item_id}",
        "type": "issue",
        "status": "idea",
        "priority": "medium",
        "frozen": 0,
        "worktree": "",
        "project": "yoke",
        "updated_at": "2024-01-01",
        "created_at": "2024-01-01",
    }
    defaults.update(kwargs)
    db.execute(
        "INSERT INTO items (id, title, type, status, priority, frozen,"
        " worktree, project_id, project_sequence, updated_at, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            item_id,
            defaults["title"],
            defaults["type"],
            defaults["status"],
            defaults["priority"],
            defaults["frozen"],
            defaults["worktree"],
            project_id(defaults["project"]),
            item_id,
            defaults["updated_at"],
            defaults["created_at"],
        ),
    )
    db.commit()


def insert_item_raw(db_path: str, items: list) -> None:
    conn = connect_test_db(db_path)
    for item_id, title, status, item_type, project, frozen, created_at, updated_at in items:
        conn.execute(
            "INSERT INTO items "
            "(id, title, status, type, project_id, project_sequence, "
            "frozen, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                item_id, title, status, item_type, project_id(project),
                item_id, frozen, created_at, updated_at,
            ),
        )
    conn.commit()
    conn.close()


def insert_task(
    db: BoardDB, epic_id: int, task_num: int, title: str,
    status: str = "implementing",
) -> None:
    db.execute(
        "INSERT INTO epic_tasks (epic_id, task_num, title, status) "
        "VALUES (%s, %s, %s, %s)",
        (epic_id, task_num, title, status),
    )
    db.commit()


def insert_activity_day(db_path: str, project: object, item_id: int, day: str) -> None:
    """Upsert one ``item_activity_days`` rollup row."""
    conn = connect_test_db(db_path)
    conn.execute(
        "INSERT INTO item_activity_days (project_id, item_id, day) "
        "VALUES (%s, %s, %s) "
        "ON CONFLICT (project_id, item_id, day) DO NOTHING",
        (project_id(project), int(item_id), day),
    )
    conn.commit()
    conn.close()


def insert_transition(
    db_path: str,
    project: object,
    item_id: int,
    to_status: str,
    created_at: str,
    *,
    task_num=None,
    from_status=None,
    source=None,
) -> None:
    """Insert one ``item_status_transitions`` history row."""
    conn = connect_test_db(db_path)
    conn.execute(
        "INSERT INTO item_status_transitions "
        "(item_id, task_num, from_status, to_status, source, project_id, "
        "created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            int(item_id), task_num, from_status, to_status, source,
            project_id(project), created_at,
        ),
    )
    conn.commit()
    conn.close()


def insert_event(
    db_path: str,
    event_name: str,
    project: object,
    created_at: str,
    context: dict,
) -> None:
    """Insert one ``events`` row with a JSON envelope carrying *context*."""
    conn = connect_test_db(db_path)
    envelope = json.dumps({"event_name": event_name, "context": context})
    conn.execute(
        "INSERT INTO events (event_name, project_id, envelope, created_at) "
        "VALUES (%s, %s, %s, %s)",
        (event_name, project_id(project), envelope, created_at),
    )
    conn.commit()
    conn.close()


def insert_projects(db_path: str, projects: list) -> None:
    conn = connect_test_db(db_path)
    for project, _checkout in projects:
        pid = project_id(project)
        slug = str(project) if not str(project).isdigit() else f"project-{project}"
        prefix = {"yoke": "YOK", "buzz": "BUZ"}.get(slug, slug.upper())
        conn.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET "
            "public_item_prefix = EXCLUDED.public_item_prefix",
            (pid, slug, slug.title(), prefix),
        )
    conn.commit()
    conn.close()


def insert_deployment_run(
    db_path: str, run_id: int, status: str = "running",
) -> None:
    conn = connect_test_db(db_path)
    conn.execute(
        "INSERT INTO deployment_runs (id, status) VALUES (%s, %s)",
        (run_id, status),
    )
    conn.commit()
    conn.close()


def insert_run_item(db_path: str, run_id: int, item_id: int) -> None:
    conn = connect_test_db(db_path)
    conn.execute(
        "INSERT INTO deployment_run_items (run_id, item_id) VALUES (%s, %s)",
        (run_id, item_id),
    )
    conn.commit()
    conn.close()
