"""Resync engine: repair-mode tests.

Pytest fixtures (test_db, populated_db) are shared via
_resync_test_helpers (private module).

GitHub auth: tests below mock the canonical resolver
:func:`yoke_core.domain.project_github_auth.resolve_project_github_auth`
via the autouse ``_auth_resolver`` fixture so repair helpers calling
``_call_domain_sync`` (which now invokes the resolver directly) do not require
real ``project_capabilities`` rows.
"""

# Imported pytest fixtures intentionally share names with test parameters.
# ruff: noqa: F811

from __future__ import annotations

from unittest import mock as mock

import pytest

import yoke_core.engines.resync as resync_mod
from yoke_core.engines.resync import (
    DriftRecord as DriftRecord,
    PairedItem as PairedItem,
)
from yoke_core.domain.project_github_auth import ProjectGithubAuth

from runtime.api.engines._resync_test_helpers import (
    populated_db as populated_db,  # noqa: F401 — imported pytest fixture
    test_db,  # noqa: F401 — imported pytest fixture
)


def _fake_auth(token: str = "test-token", project: str = "yoke") -> ProjectGithubAuth:
    return ProjectGithubAuth(
        project=project,
        repo=f"org/{project}",
        token=token,
    )


@pytest.fixture(autouse=True)
def _auth_resolver():
    """Stub the canonical resolver so ``_call_domain_sync`` and
    ``_repair_local_orphan_backlog`` succeed in unit tests.

    Runtime and repair helpers resolve once before invoking domain sync helpers.
    """

    def resolver(project, **_):
        return _fake_auth(project=project or "yoke")

    with (
        mock.patch(
            "yoke_core.engines.resync_runtime.resolve_project_github_auth",
            side_effect=resolver,
        ),
        mock.patch(
            "yoke_core.engines.resync_repair.resolve_project_github_auth",
            side_effect=resolver,
        ),
    ):
        yield


class TestRepairHelpers:
    def test_repair_local_orphan_backlog_success_created(self):
        """sync_item creates a new issue → (True, False, None)."""

        def fake_sync_item(num, **kwargs):
            # Created-fresh path emits no reuse marker.
            print(f"Created issue for YOK-{num}", file=kwargs.get("stdout"))
            return 0

        with mock.patch(
            "yoke_core.engines.resync.backlog_github_sync.sync_item",
            side_effect=fake_sync_item,
        ) as sync_item:
            ok, reused, issue_num = resync_mod._repair_local_orphan_backlog(
                "YOK-9999",
                "yoke",
            )
        sync_item.assert_called_once()
        assert ok is True
        assert reused is False
        assert issue_num is None

    def test_repair_local_orphan_backlog_success_reused(self):
        """sync_item matches an existing issue by title → (True, True, '321')."""

        def fake_sync_item(num, **kwargs):
            out = kwargs.get("stdout")
            print(f"Found existing GitHub issue #321 for YOK-{num} — reusing", file=out)
            print(f"Synced: YOK-{num} → GitHub issue #321 (reused)", file=out)
            return 0

        with mock.patch(
            "yoke_core.engines.resync.backlog_github_sync.sync_item",
            side_effect=fake_sync_item,
        ):
            ok, reused, issue_num = resync_mod._repair_local_orphan_backlog(
                "YOK-9999",
                "yoke",
            )
        assert ok is True
        assert reused is True
        assert issue_num == "321"

    def test_repair_local_orphan_backlog_handles_exception(self):
        with mock.patch(
            "yoke_core.engines.resync.backlog_github_sync.sync_item",
            side_effect=RuntimeError("boom"),
        ):
            ok, reused, issue_num = resync_mod._repair_local_orphan_backlog(
                "YOK-9999",
                "yoke",
            )
        assert ok is False
        assert reused is False
        assert issue_num is None

    def test_repair_local_orphan_epic_task_returns_false_when_task_missing(
        self, test_db
    ):
        assert (
            resync_mod._repair_local_orphan_epic_task(
                "YOK-1246",
                999,
                "yoke",
                test_db,
            )
            is False
        )

    def test_repair_local_orphan_epic_task_dry_run_short_circuits(self, populated_db):
        with mock.patch("yoke_core.engines.resync._is_dry_run", return_value=True):
            assert (
                resync_mod._repair_local_orphan_epic_task(
                    "YOK-1246",
                    1,
                    "yoke",
                    populated_db,
                )
                is True
            )

    def test_repair_local_orphan_epic_task_success_creates_and_closes_terminal_issue(
        self, populated_db
    ):
        from yoke_core.domain.github_rest import Issue
        from runtime.api.fixtures.file_test_db import connect_test_db

        conn = connect_test_db(populated_db)
        conn.execute(
            "UPDATE epic_tasks SET status='done', body='' WHERE epic_id='1246' AND task_num=1"
        )
        conn.commit()
        conn.close()

        # The github_issue write-back relays through the connected transport
        # (advisory) — its routing is covered by test_resync_transport; here we
        # assert the GitHub create + terminal-close calls.
        created = Issue(number=321, title="t", state="OPEN")
        with (
            mock.patch("yoke_core.engines.resync._is_dry_run", return_value=False),
            mock.patch(
                "yoke_core.engines.resync_repair_epic_task_issue.github_rest.create_issue",
                return_value=created,
            ) as create_issue_mock,
            mock.patch(
                "yoke_core.engines.resync_repair_epic_task_issue.github_rest.set_issue_state",
                return_value=Issue(number=321, title="t", state="CLOSED"),
            ) as close_mock,
        ):
            ok = resync_mod._repair_local_orphan_epic_task(
                "YOK-1246",
                1,
                "externalwebapp",
                populated_db,
            )

        assert ok is True
        assert create_issue_mock.call_args.kwargs["project"] == "externalwebapp"
        assert close_mock.call_args.kwargs == {
            "project": "externalwebapp",
            "number": 321,
            "state": "closed",
        }

    def test_repair_local_orphan_epic_task_returns_false_when_issue_create_fails(
        self, populated_db
    ):
        from yoke_core.domain.gh_rest_transport import RestServerError

        with (
            mock.patch("yoke_core.engines.resync._is_dry_run", return_value=False),
            mock.patch(
                "yoke_core.engines.resync_repair_epic_task_issue.github_rest.create_issue",
                side_effect=RestServerError("HTTP 502: bad gateway", status=502),
            ),
        ):
            ok = resync_mod._repair_local_orphan_epic_task(
                "YOK-1246",
                1,
                "yoke",
                populated_db,
            )
        assert ok is False

    def test_repair_local_orphan_epic_task_returns_false_when_issue_number_missing(
        self, populated_db
    ):
        from yoke_core.domain.github_rest import Issue

        with (
            mock.patch("yoke_core.engines.resync._is_dry_run", return_value=False),
            mock.patch(
                "yoke_core.engines.resync_repair_epic_task_issue.github_rest.create_issue",
                return_value=Issue(number=0, title="t", state="OPEN"),
            ),
        ):
            ok = resync_mod._repair_local_orphan_epic_task(
                "YOK-1246",
                1,
                "yoke",
                populated_db,
            )
        assert ok is False
