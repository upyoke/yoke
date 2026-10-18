"""Epic sync runs one GitHub issue search for the parent and all child tasks.

The Search API's low rate limit turns per-child searches into backoff waits,
so ``sync_epic_tasks`` shares one ``IssueSearchCache`` across its creates and
matches each child against the shared results locally.
"""

from __future__ import annotations

import io
from unittest.mock import patch

import pytest

from runtime.api.conftest import insert_epic_task, insert_item
from runtime.api.epic_task_sync_orchestrator_test_support import (
    _mock_yoke_root as _mock_yoke_root,
    _stub_project_github_auth as _stub_project_github_auth,
    _stub_typed_rest_surfaces as _stub_typed_rest_surfaces,
    db as db,
    declare_no_file_tasks,
)
from runtime.api.task_files_touched_test_support import files_touched_body
from yoke_core.domain import epic_task_sync, github_rest
from yoke_core.domain.project_identity import render_item_ref

_SEARCH = "yoke_core.domain.github_dedup.github_rest.list_issues"
_CREATE = "yoke_core.domain.epic_task_sync_github_create.github_rest.create_issue"


@pytest.fixture(autouse=True)
def _stub_parent_label():
    """A reused parent issue gets its workflow label without real REST."""
    with patch("yoke_core.domain.backlog_github_label_sync_rest.add_labels"):
        yield


def _seed_epic(conn, *, task_count: int, parent_issue: str = "") -> str:
    insert_item(
        conn,
        id=10,
        workflow_id="epic",
        status="implementing",
        project="externalwebapp",
        spec="Epic body",
        github_issue=parent_issue,
    )
    for task_num in range(1, task_count + 1):
        insert_epic_task(
            conn,
            epic_id="10",
            task_num=task_num,
            title=f"Task {task_num}",
            status="planned",
            body=f"body {task_num}",
        )
    declare_no_file_tasks(conn, 10)
    return render_item_ref(conn, 10)


def _task_issues(conn) -> dict[int, str]:
    rows = conn.execute(
        "SELECT task_num, github_issue FROM epic_tasks WHERE epic_id='10' "
        "ORDER BY task_num"
    ).fetchall()
    return {int(row[0]): str(row[1] or "") for row in rows}


def _created(number: int):
    return github_rest.Issue(number, "Created", "OPEN")


def test_parent_and_children_share_one_search_and_adopt_existing_child(db):
    ref = _seed_epic(db, task_count=3)
    existing = github_rest.Issue(
        555, f"[{ref}] 002 Task 2", "OPEN", body=files_touched_body([], "body 2")
    )
    stdout = io.StringIO()

    with (
        patch(_SEARCH, return_value=[existing]) as search,
        patch(
            _CREATE, side_effect=[_created(100), _created(201), _created(203)]
        ) as create,
    ):
        rc = epic_task_sync.sync_epic_tasks(10, conn=db, stdout=stdout)

    assert rc == 0
    assert search.call_count == 1
    assert search.call_args.kwargs["search"] == f"[{ref}] in:title is:issue"
    assert [call.kwargs["title"] for call in create.call_args_list][1:] == [
        f"[{ref}] 001 Task 1",
        f"[{ref}] 003 Task 3",
    ]
    assert _task_issues(db) == {1: "#201", 2: "#555", 3: "#203"}
    assert f"Found existing GitHub issue #555 for [{ref}] 002 Task 2" in (
        stdout.getvalue()
    )


def test_failed_search_is_reported_once_and_not_retried_per_child(db):
    _seed_epic(db, task_count=3, parent_issue="#99")
    stderr = io.StringIO()

    with (
        patch(
            _SEARCH,
            side_effect=github_rest.RestTransportError("rate limited", status=403),
        ) as search,
        patch(
            _CREATE, side_effect=[_created(201), _created(202), _created(203)]
        ) as create,
    ):
        rc = epic_task_sync.sync_epic_tasks(10, conn=db, stderr=stderr)

    assert rc == 0
    assert search.call_count == 1
    assert create.call_count == 3
    assert stderr.getvalue().count("github_dedup_search_failed") == 1
    assert _task_issues(db) == {1: "#201", 2: "#202", 3: "#203"}


def test_fully_synced_epic_makes_no_search(db):
    _seed_epic(db, task_count=2, parent_issue="#99")
    db.execute("UPDATE epic_tasks SET github_issue = '#300' WHERE epic_id = '10'")
    db.commit()

    with patch(_SEARCH) as search, patch(_CREATE) as create:
        rc = epic_task_sync.sync_epic_tasks(10, conn=db)

    assert rc == 0
    search.assert_not_called()
    create.assert_not_called()
