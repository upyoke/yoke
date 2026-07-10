"""Epic / task GitHub sync body-budget regression coverage.

Verifies that the three migrated epic-task body paths —
``_resolve_or_create_epic_issue`` (epic issue create),
``_dedup_or_create_task_issue`` (task issue create), and
``sync_task_body`` (task body update) — route oversized bodies through
the compact-mirror budget guard. Each test mocks the typed REST surface
``github_rest.create_issue`` / ``github_rest.update_issue`` and asserts
that the body passed to the typed call is the compact mirror.
"""

from __future__ import annotations

import io

import pytest

from runtime.api.conftest import insert_item
from yoke_core.domain import (
    backlog_github_body_budget as _budget,
    epic_task_sync_github,
    github_rest,
)
from yoke_core.domain.epic_task_sync_github_create import (
    _dedup_or_create_task_issue,
    _resolve_or_create_epic_issue,
)
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)


_OVER_BUDGET = "x" * (_budget.GITHUB_BODY_BUDGET_BYTES + 500)


@pytest.fixture
def epic_conn(tmp_path):
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as db_path:
        conn = connect_test_db(db_path)
        insert_item(
            conn,
            id=4242,
            title="Big epic",
            status="planning",
            project="yoke",
            type="epic",
        )
        try:
            yield conn
        finally:
            conn.close()


def _record_create():
    """Build a fake ``create_issue`` that records each call's body kwarg
    and returns a valid typed Issue."""
    captured: list[dict] = []

    def fake_create(*, project, title, body, labels, **_):
        captured.append({
            "project": project,
            "title": title,
            "body": body,
            "labels": list(labels),
        })
        return github_rest.Issue(
            number=999, title=title, state="OPEN",
            html_url="https://github.com/owner/repo/issues/999",
        )

    return captured, fake_create


def _record_update():
    """Build a fake ``update_issue`` recording the body kwarg."""
    captured: list[dict] = []

    def fake_update(*, project, number, body=None, title=None, **_):
        captured.append({
            "project": project,
            "number": number,
            "body": body,
            "title": title,
        })
        return github_rest.Issue(number=number, title=title or "t", state="OPEN")

    return captured, fake_update


def test_resolve_or_create_epic_issue_compacts_oversized_body(monkeypatch, epic_conn):
    captured, fake_create = _record_create()
    monkeypatch.setattr(
        "yoke_core.domain.epic_task_sync_github_create.github_rest.create_issue",
        fake_create,
    )
    # Force the body builder used inside the create helper to return oversized content.
    monkeypatch.setattr(
        "yoke_core.domain.render_body.build_body",
        lambda conn, item_id: _OVER_BUDGET,
    )
    # Skip the existing-issue dedup branch.
    monkeypatch.setattr(
        "yoke_core.domain.epic_task_sync_github_create.search_existing_issue",
        lambda *a, **kw: None,
    )

    stdout = io.StringIO()
    stderr = io.StringIO()
    num = _resolve_or_create_epic_issue(
        epic_name="my-epic",
        backlog_id="YOK-4242",
        backlog_github_issue="",  # forces create branch
        parent_item_id="4242",
        gh_project="yoke",
        dry_run=False,
        conn=epic_conn,
        stdout=stdout, stderr=stderr,
    )

    assert num == "999"
    assert len(captured) == 1
    # The body the writer chose must be the compact mirror, not the raw oversized body.
    assert _budget.body_exceeds_budget(captured[0]["body"]) is False
    assert "YOK-4242" in captured[0]["body"]


def test_dedup_or_create_task_issue_compacts_oversized_body(monkeypatch):
    captured, fake_create = _record_create()
    monkeypatch.setattr(
        "yoke_core.domain.epic_task_sync_github_create.github_rest.create_issue",
        fake_create,
    )
    monkeypatch.setattr(
        "yoke_core.domain.epic_task_sync_github_create.search_existing_issue",
        lambda *a, **kw: None,
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    num = _dedup_or_create_task_issue(
        backlog_id="YOK-4242",
        task_num_str="007",
        task_title="oversized task",
        issue_title="[YOK-4242] 007 oversized task",
        task_body=_OVER_BUDGET,
        labels=["type:task", "status:planned"],
        gh_project="yoke",
        stdout=stdout, stderr=stderr,
        conn=None,
        epic_id="4242",
        task_num=7,
    )

    assert num == "999"
    assert len(captured) == 1
    assert _budget.body_exceeds_budget(captured[0]["body"]) is False
    assert "YOK-4242 task 7" in captured[0]["body"]
    assert "epic task-get-body 4242 7" in captured[0]["body"]
    assert "yoke conduct YOK-4242" in captured[0]["body"]


def test_sync_task_body_compacts_oversized_body(monkeypatch, epic_conn):
    captured, fake_update = _record_update()
    monkeypatch.setattr(
        "yoke_core.domain.github_rest.update_issue", fake_update,
    )
    monkeypatch.setattr(
        "yoke_core.domain.epic_task_sync_github._is_dry_run",
        lambda: False,
    )
    monkeypatch.setattr(
        "yoke_core.domain.epic_task_sync_github._validate_issue_in_repo",
        lambda *a, **kw: True,
    )
    monkeypatch.setattr(
        "yoke_core.domain.epic_task_sync_github._task_context",
        lambda *a, **kw: ("#777", "yoke", _OVER_BUDGET),
    )

    stdout = io.StringIO()
    stderr = io.StringIO()
    rc = epic_task_sync_github.sync_task_body(
        "4242", 7, conn=epic_conn, stdout=stdout, stderr=stderr,
    )

    assert rc == 0
    assert len(captured) == 1
    assert _budget.body_exceeds_budget(captured[0]["body"]) is False
    assert "YOK-4242 task 7" in captured[0]["body"]
    assert "epic task-get-body 4242 7" in captured[0]["body"]
    assert "compact mirror" in stdout.getvalue() or "compact mirror" in stderr.getvalue()


def test_dedup_or_create_task_issue_keeps_full_body_under_budget(monkeypatch):
    """Negative control: an under-budget body ships verbatim, not as a mirror."""
    captured, fake_create = _record_create()
    monkeypatch.setattr(
        "yoke_core.domain.epic_task_sync_github_create.github_rest.create_issue",
        fake_create,
    )
    monkeypatch.setattr(
        "yoke_core.domain.epic_task_sync_github_create.search_existing_issue",
        lambda *a, **kw: None,
    )
    body = "## Implementation\n\nSmall body content.\n"
    stdout = io.StringIO()
    stderr = io.StringIO()
    _dedup_or_create_task_issue(
        backlog_id="YOK-4242",
        task_num_str="001",
        task_title="small task",
        issue_title="[YOK-4242] 001 small task",
        task_body=body,
        labels=["type:task"],
        gh_project="yoke",
        stdout=stdout, stderr=stderr,
        conn=None,
        epic_id="4242",
        task_num=1,
    )

    assert len(captured) == 1
    assert captured[0]["body"] == body
