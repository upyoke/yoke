"""Integration tests for the shared GitHub dedup helper via
``epic_task_sync.sync_epic_tasks`` — both the epic-parent and the epic-task
call sites.

Helper unit tests and the ``sync_item`` integration tests live in the
sibling ``test_github_dedup.py`` module.

Tests mock the typed REST surfaces (``github_rest.list_issues`` /
``github_rest.create_issue``) directly. Yoke does NOT use the
``gh`` CLI.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime.api.conftest import insert_epic_task, insert_item
from yoke_core.domain import epic_task_sync, github_rest
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from runtime.api.fixtures.pg_testdb import test_database


def _issue(number: int, title: str) -> github_rest.Issue:
    return github_rest.Issue(
        number=number, title=title, state="OPEN",
        html_url=f"https://github.com/org/buzz/issues/{number}",
    )


@pytest.fixture
def epic_db():
    with test_database() as conn:
        conn.execute(
            "UPDATE projects SET github_repo = %s WHERE id = %s",
            ("org/buzz", SEED_PROJECT_IDS["buzz"]),
        )
        conn.execute(
            "INSERT INTO project_capabilities (project_id, type, settings) "
            "VALUES (%s, 'github', '{}') "
            "ON CONFLICT(project_id, type) DO NOTHING",
            (SEED_PROJECT_IDS["buzz"],),
        )
        conn.execute(
            "INSERT INTO capability_secrets (project_id, type, key, source, value) "
            "VALUES (%s, 'github', 'token', 'literal', %s)",
            (SEED_PROJECT_IDS["buzz"], "ghp_buzz_test"),
        )
        conn.commit()
        yield conn


@pytest.fixture(autouse=True)
def _mock_yoke_root():
    with patch(
        "yoke_core.domain.epic_task_sync._yoke_root",
        return_value=Path("/tmp/fake-yoke"),
    ):
        yield


@pytest.fixture(autouse=True)
def _mock_project_github_auth():
    auth = ProjectGithubAuth(
        project="buzz",
        repo="org/buzz",
        token="ghp_buzz_test",
        env={"GH_TOKEN": "ghp_buzz_test"},
    )
    with patch(
        "yoke_core.domain.epic_task_sync.resolve_project_github_auth",
        return_value=auth,
    ), patch(
        "yoke_core.domain.epic_task_sync_github_orchestrator.resolve_project_github_auth",
        return_value=auth,
    ), patch(
        "yoke_core.domain.epic_task_sync_github.resolve_project_github_auth",
        return_value=auth,
    ), patch(
        "yoke_core.domain.epic_task_sync_github_create.resolve_project_github_auth",
        return_value=auth,
    ):
        yield


@pytest.fixture(autouse=True)
def _stub_typed_rest_surfaces():
    """Stub the non-dedup typed surfaces so the orchestrator's pre-create
    label seeding and sub-issue fallback don't try real REST."""
    with patch(
        "yoke_core.domain.epic_task_sync_github._label_rest.ensure_label",
    ), patch(
        "yoke_core.domain.github_rest.add_sub_issue",
        side_effect=github_rest.RestTransportError("sub-issue not supported", status=404),
    ), patch(
        "yoke_core.domain.epic_task_sync_github_orchestrator_body."
        "append_task_list_to_epic_body",
    ), patch(
        "yoke_core.domain.backlog_github_label_sync_rest.add_labels",
    ):
        yield


def _patches(*, dedup_results, create_response=None):
    """Compose the dedup + create patches used by every test in this module.

    ``dedup_results`` is a list returned by ``github_rest.list_issues``;
    ``create_response`` is the Issue returned by ``create_issue`` (or
    ``None`` when the test expects no creation).
    """
    if create_response is None:
        def _create_side(*a, **kw):
            raise AssertionError("Should not create — dedup should find existing")
        create_kwargs = {"side_effect": _create_side}
    else:
        create_kwargs = {"return_value": create_response}

    return [
        patch(
            "yoke_core.domain.github_dedup.github_rest.list_issues",
            return_value=dedup_results,
        ),
        patch(
            "yoke_core.domain.epic_task_sync_github_create.github_rest.create_issue",
            **create_kwargs,
        ),
    ]


class TestSyncEpicTasksDedup:
    def test_task_path_reuses_exact_prefix_match(self, epic_db):
        """AC-5 (task path, exact reuse): typed list_issues whose title
        matches the new-format prefix ``[YOK-N] NNN <task title>`` is
        reused (no create call).
        """
        insert_item(
            epic_db, id=10, type="epic", status="implementing", project="buzz",
            spec="Epic body", github_issue="#99",
        )
        insert_epic_task(epic_db, epic_id="10", task_num=1, title="Some task",
                         status="planned", body="body")
        stdout = io.StringIO()

        patches = _patches(
            dedup_results=[_issue(555, "[YOK-10] 001 Some task")],
            create_response=None,
        )
        with patches[0], patches[1]:
            rc = epic_task_sync.sync_epic_tasks(
                "YOK-10", conn=epic_db, stdout=stdout,
            )

        assert rc == 0
        assert "reusing" in stdout.getvalue().lower()
        row = epic_db.execute(
            "SELECT github_issue FROM epic_tasks WHERE epic_id='10' AND task_num=1"
        ).fetchone()
        assert row[0] == "#555"

    def test_task_path_rejects_fuzzy_substring(self, epic_db):
        """AC-5 (task path, fuzzy non-reuse) + AC-3 regression at the task
        call site.
        """
        insert_item(
            epic_db, id=1500, type="epic", status="implementing", project="buzz",
            spec="Epic body", github_issue="#99",
        )
        insert_epic_task(epic_db, epic_id="1500", task_num=1, title="Decomp lower",
                         status="planned", body="body")
        stdout = io.StringIO()

        fuzzy = _issue(
            3543,
            "[YOK-1498] 350-line decomp: split runtime/api/test_*.py top-14 "
            "(1000-1500 lines)",
        )
        created = _issue(4001, "[YOK-1500] 001 Decomp lower")

        patches = _patches(dedup_results=[fuzzy], create_response=created)
        with patches[0], patches[1]:
            rc = epic_task_sync.sync_epic_tasks(
                "YOK-1500", conn=epic_db, stdout=stdout,
            )

        assert rc == 0
        row = epic_db.execute(
            "SELECT github_issue FROM epic_tasks WHERE epic_id='1500' AND task_num=1"
        ).fetchone()
        assert row[0] != "#3543"
        assert row[0] == "#4001"
        assert "found existing github issue" not in stdout.getvalue().lower()
        assert "#3543" not in stdout.getvalue()

    def test_parent_path_reuses_exact_prefix_match(self, epic_db):
        """AC-5 (epic parent path, exact reuse): when the parent epic has
        no github_issue, the parent dedup search reuses an issue whose
        title starts with the exact bracketed prefix ``[YOK-N]``.
        """
        insert_item(epic_db, id=10, type="epic", status="implementing",
                    project="buzz", spec="Epic body")
        insert_epic_task(epic_db, epic_id="10", task_num=1, title="First task",
                         status="planned", body="body")
        stdout = io.StringIO()

        # Two list_issues calls: parent dedup returns the exact match;
        # task dedup returns nothing so the task is created fresh.
        parent_match = _issue(808, "[YOK-10] Existing parent epic")
        task_created = _issue(9100, "[YOK-10] 001 First task")

        with patch(
            "yoke_core.domain.github_dedup.github_rest.list_issues",
            side_effect=[[parent_match], [], []],
        ), patch(
            "yoke_core.domain.epic_task_sync_github_create.github_rest.create_issue",
            return_value=task_created,
        ):
            rc = epic_task_sync.sync_epic_tasks(
                "YOK-10", conn=epic_db, stdout=stdout,
            )

        assert rc == 0
        parent = epic_db.execute("SELECT github_issue FROM items WHERE id = 10").fetchone()
        assert parent[0] == "#808"
        assert "reusing" in stdout.getvalue().lower()

    def test_parent_path_rejects_fuzzy_substring(self, epic_db):
        """AC-5 (epic parent path, fuzzy non-reuse) + AC-3 regression at
        the parent call site.
        """
        insert_item(epic_db, id=1500, type="epic", status="implementing",
                    project="buzz", spec="Epic body")
        insert_epic_task(epic_db, epic_id="1500", task_num=1, title="First task",
                         status="planned", body="body")
        stdout = io.StringIO()

        fuzzy = _issue(
            3543,
            "[YOK-1498] unrelated decomp ticket (1000-1500 lines)",
        )
        epic_created = _issue(9001, "[YOK-1500] Epic title")
        task_created = _issue(9002, "[YOK-1500] 001 First task")

        # Parent dedup returns fuzzy (rejected) → parent create returns
        # epic_created; task dedup returns nothing → task create returns
        # task_created.
        with patch(
            "yoke_core.domain.github_dedup.github_rest.list_issues",
            side_effect=[[fuzzy], [], []],
        ), patch(
            "yoke_core.domain.epic_task_sync_github_create.github_rest.create_issue",
            side_effect=[epic_created, task_created],
        ):
            rc = epic_task_sync.sync_epic_tasks(
                "YOK-1500", conn=epic_db, stdout=stdout,
            )

        assert rc == 0
        parent = epic_db.execute("SELECT github_issue FROM items WHERE id = 1500").fetchone()
        assert parent[0] != "#3543"
        assert parent[0] == "#9001"
