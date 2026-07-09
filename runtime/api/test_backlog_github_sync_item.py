"""Coverage for ``sync_item`` — single-issue and epic dispatch paths.

Covers AC-6 (create + reuse paths both use ``select_body_for_github``),
AC-7 (transitive ``ProjectGithubAuthError`` catch), AC-12 (create + reuse
regressions exercising the shared compact-mirror contract).

Tests mock the typed ``github_rest.create_issue`` / ``list_issues`` surfaces
directly (no argv shapes).
"""

from __future__ import annotations

import io
from unittest.mock import ANY, patch

from runtime.api.backlog_github_sync_test_helpers import (
    GH_PATCH,
    make_db as _make_db,
)
from runtime.api.conftest import insert_epic_task, insert_item
# Import the umbrella module FIRST so its transitive re-export chain
# completes before any sibling-specific submodule attempts to import it.
from yoke_core.domain import backlog_github_sync  # noqa: I001
from yoke_core.domain import (
    backlog_github_body_budget as body_budget,
    backlog_github_item_create as item_create,
    github_rest,
)
from yoke_core.domain.project_github_auth import (
    MissingToken,
    ProjectGithubAuth,
)


_DEDUP_PATCH = "yoke_core.domain.github_dedup.github_rest.list_issues"
_CREATE_PATCH = "yoke_core.domain.backlog_github_item_create.github_rest.create_issue"


def _ok_resolver(*args, **kwargs):
    proj = kwargs.get("project") or (args[0] if args else "buzz")
    return ProjectGithubAuth(
        project=proj, repo="org/buzz", token="ghs_fake",
        env={"GH_TOKEN": "ghs_fake"},
    )


def _fake_issue(number: int = 999, title: str = "title") -> github_rest.Issue:
    return github_rest.Issue(
        number=number, title=title, state="OPEN",
        html_url=f"https://github.com/org/buzz/issues/{number}",
    )


class TestSyncItem:
    def test_already_synced_updates_labels_and_body(self):
        db = _make_db()
        insert_item(db, id=20, type="issue", status="idea", project="buzz", github_issue="#100")
        stdout = io.StringIO()
        with patch.object(
            item_create, "resolve_project_github_auth", side_effect=_ok_resolver,
        ), patch(f"{GH_PATCH}.sync_labels", return_value=0) as mock_labels, patch(
            f"{GH_PATCH}.sync_body", return_value=0
        ) as mock_body:
            rc = backlog_github_sync.sync_item("20", conn=db, stdout=stdout)
        assert rc == 0
        mock_labels.assert_called_once()
        mock_body.assert_called_once()
        assert "already synced" in stdout.getvalue()
        db.close()

    def test_already_synced_epic_also_syncs_child_tasks(self):
        db = _make_db()
        insert_item(db, id=21, type="epic", status="implementing", project="buzz", github_issue="#100")
        insert_epic_task(db, epic_id=21, task_num=1, title="Task 1", status="planned")
        stdout = io.StringIO()
        with patch.object(
            item_create, "resolve_project_github_auth", side_effect=_ok_resolver,
        ), patch(f"{GH_PATCH}.sync_labels", return_value=0) as mock_labels, patch(
            f"{GH_PATCH}.sync_body", return_value=0
        ) as mock_body, patch(
            f"{GH_PATCH}.epic_task_sync.sync_epic_tasks", return_value=0
        ) as mock_task_sync:
            rc = backlog_github_sync.sync_item("21", conn=db, stdout=stdout)
        assert rc == 0
        mock_labels.assert_called_once()
        mock_body.assert_called_once()
        mock_task_sync.assert_called_once_with("BUZ-21", conn=db, stdout=stdout, stderr=ANY)
        db.close()

    def test_creates_new_issue(self):
        db = _make_db()
        insert_item(
            db,
            id=20,
            type="issue",
            status="idea",
            priority="high",
            project="buzz",
            spec="Test body content",
        )
        stdout = io.StringIO()

        with patch.object(
            item_create, "resolve_project_github_auth", side_effect=_ok_resolver,
        ), patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            _DEDUP_PATCH, return_value=[],
        ), patch(
            _CREATE_PATCH, return_value=_fake_issue(number=999),
        ), patch(
            "yoke_core.domain.backlog_github_item_create._regenerate_md",
        ), patch(
            "yoke_core.domain.backlog_github_item_create._ensure_label",
        ):
            rc = backlog_github_sync.sync_item("20", conn=db, stdout=stdout)

        assert rc == 0
        gh_issue = db.execute("SELECT github_issue FROM items WHERE id = 20").fetchone()[0]
        assert gh_issue == "#999"
        assert "Synced: BUZ-20 → GitHub issue #999" in stdout.getvalue()
        db.close()

    def test_creates_new_epic_issue_and_syncs_child_tasks(self):
        db = _make_db()
        insert_item(
            db,
            id=22,
            type="epic",
            status="planning",
            priority="high",
            project="buzz",
            spec="Epic body content",
        )
        insert_epic_task(db, epic_id=22, task_num=1, title="Task 1", status="planned")
        stdout = io.StringIO()

        with patch.object(
            item_create, "resolve_project_github_auth", side_effect=_ok_resolver,
        ), patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            _DEDUP_PATCH, return_value=[],
        ), patch(
            _CREATE_PATCH, return_value=_fake_issue(number=1001),
        ), patch(
            "yoke_core.domain.backlog_github_item_create._regenerate_md",
        ), patch(
            "yoke_core.domain.backlog_github_item_create._ensure_label",
        ), patch(
            f"{GH_PATCH}.epic_task_sync.sync_epic_tasks", return_value=0
        ) as mock_task_sync:
            rc = backlog_github_sync.sync_item("22", conn=db, stdout=stdout)

        assert rc == 0
        gh_issue = db.execute("SELECT github_issue FROM items WHERE id = 22").fetchone()[0]
        assert gh_issue == "#1001"
        mock_task_sync.assert_called_once_with("BUZ-22", conn=db, stdout=stdout, stderr=ANY)
        db.close()

    # Dedup behavior — exact-prefix reuse, fuzzy non-reuse, malformed-JSON
    # fallthrough — is exercised in runtime/api/test_github_dedup.py.

    def test_dry_run_skips(self):
        db = _make_db()
        insert_item(db, id=20, type="issue", status="idea", project="buzz")
        stdout = io.StringIO()
        with patch.object(
            item_create, "resolve_project_github_auth", side_effect=_ok_resolver,
        ), patch.object(backlog_github_sync, "_dry_run", return_value=True):
            rc = backlog_github_sync.sync_item("20", conn=db, stdout=stdout)
        assert rc == 0
        assert "DRY-RUN" in stdout.getvalue()
        db.close()

    def test_missing_item_returns_error(self):
        db = _make_db()
        stderr = io.StringIO()
        rc = backlog_github_sync.sync_item("999", conn=db, stderr=stderr)
        assert rc == 1
        assert "not found" in stderr.getvalue()
        db.close()

    def test_creates_new_issue_renders_owner_label(self):
        """Post-Slice 5b create: numeric source/owner pass through
        ``actor_label_or_passthrough`` and contribute ``source:`` and
        ``owner:`` labels to the create payload. The raw integer must
        not appear in any label argument."""
        from yoke_core.domain.actors import resolve_actor_by_label

        db = _make_db()
        local_human = resolve_actor_by_label(db, "ben")
        yoke_core = resolve_actor_by_label(db, "yoke-core")
        assert local_human is not None and yoke_core is not None

        insert_item(
            db,
            id=23,
            type="issue",
            status="idea",
            priority="medium",
            project="buzz",
            spec="Owner label test",
            source=str(local_human),
            owner=str(yoke_core),
        )
        stdout = io.StringIO()

        with patch.object(
            item_create, "resolve_project_github_auth", side_effect=_ok_resolver,
        ), patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            _DEDUP_PATCH, return_value=[],
        ), patch(
            _CREATE_PATCH, return_value=_fake_issue(number=777),
        ) as create_issue, patch(
            "yoke_core.domain.backlog_github_item_create._regenerate_md",
        ), patch(
            "yoke_core.domain.backlog_github_item_create._ensure_label",
        ):
            rc = backlog_github_sync.sync_item("23", conn=db, stdout=stdout)

        assert rc == 0
        create_issue.assert_called_once()
        labels = create_issue.call_args.kwargs["labels"]
        assert "source:ben" in labels
        assert "owner:yoke-core" in labels
        assert f"source:{local_human}" not in labels
        assert f"owner:{yoke_core}" not in labels
        db.close()


# ---------------------------------------------------------------------------
# AC-12 regressions: create + reuse paths share compact-mirror contract
# ---------------------------------------------------------------------------


class TestSyncItemCompactMirror:
    def test_create_uses_compact_mirror_for_oversized(self):
        """AC-6 + AC-12: create path picks compact mirror when full body is
        oversized; the body string passed to ``create_issue`` fits under the
        budget."""
        db = _make_db()
        huge_spec = "a" * (body_budget.GITHUB_BODY_BUDGET_BYTES + 100)
        insert_item(
            db, id=30, type="issue", status="idea", project="buzz",
            priority="medium", spec=huge_spec,
        )
        stdout = io.StringIO()

        with patch.object(
            item_create, "resolve_project_github_auth", side_effect=_ok_resolver,
        ), patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            _DEDUP_PATCH, return_value=[],
        ), patch(
            _CREATE_PATCH, return_value=_fake_issue(number=901),
        ) as create_issue, patch(
            "yoke_core.domain.backlog_github_item_create._regenerate_md",
        ), patch(
            "yoke_core.domain.backlog_github_item_create._ensure_label",
        ):
            rc = backlog_github_sync.sync_item("30", conn=db, stdout=stdout)

        assert rc == 0
        create_issue.assert_called_once()
        body = create_issue.call_args.kwargs["body"]
        assert len(body.encode("utf-8")) <= body_budget.GITHUB_BODY_BUDGET_BYTES
        db.close()

    def test_reuse_inherits_compact_mirror(self):
        """AC-12: reuse path delegates body sync to ``sync_body`` which
        owns the same body-budget contract."""
        db = _make_db()
        huge_spec = "a" * (body_budget.GITHUB_BODY_BUDGET_BYTES + 100)
        insert_item(
            db, id=31, type="issue", status="idea", project="buzz",
            github_issue="#205", spec=huge_spec,
        )
        stdout = io.StringIO()
        # Mock sync_body so we only assert that the reuse path delegated
        # to it; the compact-mirror behavior of sync_body is exercised in
        # test_backlog_github_sync_body_title.
        with patch.object(
            item_create, "resolve_project_github_auth", side_effect=_ok_resolver,
        ), patch(f"{GH_PATCH}.sync_labels", return_value=0), patch(
            f"{GH_PATCH}.sync_body", return_value=0,
        ) as mock_body:
            rc = backlog_github_sync.sync_item("31", conn=db, stdout=stdout)

        assert rc == 0
        mock_body.assert_called_once()
        db.close()

    def test_auth_failure_short_circuits_create(self):
        """AC-9 mirror: ``sync_item`` short-circuits on resolver error
        before any dedup search, label seeding, or REST call."""
        db = _make_db()
        insert_item(
            db, id=32, type="issue", status="idea", project="buzz",
            spec="body",
        )
        stderr = io.StringIO()

        def raise_missing_token(*a, **kw):
            raise MissingToken("buzz", "no token")

        with patch.object(
            item_create, "resolve_project_github_auth",
            side_effect=raise_missing_token,
        ), patch(_DEDUP_PATCH) as dedup, patch(_CREATE_PATCH) as create_issue:
            rc = backlog_github_sync.sync_item("32", conn=db, stderr=stderr)

        assert rc == 1
        dedup.assert_not_called()
        create_issue.assert_not_called()
        assert "MissingToken" in stderr.getvalue()
        db.close()
