"""Label-sync coverage: ``sync_frozen_label`` and ``sync_labels``.

Tests mock the typed REST label surface (``_label_rest`` /
``backlog_github_label_sync._rest``) directly. No argv shapes.
"""

from __future__ import annotations

import io
from unittest.mock import patch

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
)
from runtime.api.backlog_github_sync_test_helpers import (
    GH_PATCH,
    make_db as _make_db,
)
from runtime.api.conftest import insert_item
from yoke_core.domain import (
    backlog_github_label_sync,
    backlog_github_state_sync,
    backlog_github_sync,
)
from yoke_core.domain.project_github_auth import ProjectGithubAuth


_LABEL_REST_STATE = "yoke_core.domain.backlog_github_state_sync._label_rest"
_LABEL_REST_LABELS = "yoke_core.domain.backlog_github_label_sync._rest"


def _ok_resolver(*args, **kwargs):
    proj = kwargs.get("project") or (args[0] if args else "buzz")
    return ProjectGithubAuth(
        project=proj, repo="org/buzz", token="ghs_fake",
    )


# ---------------------------------------------------------------------------
# sync_frozen_label
# ---------------------------------------------------------------------------


class TestSyncFrozenLabel:
    def test_missing_issue_is_silent(self):
        db = _make_db()
        insert_item(db, id=7, type="issue", status="implementing", project="buzz")
        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            f"{_LABEL_REST_STATE}.ensure_label",
        ) as ensure, patch(
            f"{_LABEL_REST_STATE}.add_labels",
        ) as add, patch(
            f"{_LABEL_REST_STATE}.remove_label",
        ) as remove:
            rc = backlog_github_sync.sync_frozen_label("7", "true", conn=db)
        assert rc == 0
        ensure.assert_not_called()
        add.assert_not_called()
        remove.assert_not_called()
        db.close()

    def test_adds_frozen_label_in_project_repo(self):
        db = _make_db()
        insert_item(
            db,
            id=7,
            type="issue",
            status="implementing",
            project="buzz",
            github_issue="#42",
        )
        stdout = io.StringIO()

        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo",
            autospec=True,
            return_value=True,
        ), patch.object(
            backlog_github_state_sync, "resolve_project_github_auth",
            side_effect=_ok_resolver,
        ) as resolve_auth, patch(f"{_LABEL_REST_STATE}.ensure_label") as ensure, patch(
            f"{_LABEL_REST_STATE}.add_labels",
        ) as add_labels:
            rc = backlog_github_sync.sync_frozen_label("7", "true", conn=db, stdout=stdout)

        assert rc == 0
        assert resolve_auth.call_args.kwargs == {
            "required_permissions": GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
        }
        ensure.assert_called_once()
        add_labels.assert_called_once_with(
            "org/buzz", 42, ["frozen"], token="ghs_fake",
        )
        assert "Frozen label added: BUZ-7 → #42" in stdout.getvalue()
        db.close()

    def test_removes_frozen_label_when_value_false(self):
        db = _make_db()
        insert_item(
            db, id=7, type="issue", status="implementing", project="buzz",
            github_issue="#42",
        )
        stdout = io.StringIO()

        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo", return_value=True,
        ), patch.object(
            backlog_github_state_sync, "resolve_project_github_auth",
            side_effect=_ok_resolver,
        ), patch(f"{_LABEL_REST_STATE}.ensure_label"), patch(
            f"{_LABEL_REST_STATE}.remove_label",
        ) as remove_label:
            rc = backlog_github_sync.sync_frozen_label("7", "false", conn=db, stdout=stdout)

        assert rc == 0
        remove_label.assert_called_once_with(
            "org/buzz", 42, "frozen", token="ghs_fake",
        )
        assert "Frozen label removed: BUZ-7 → #42" in stdout.getvalue()
        db.close()

    def test_issue_validation_failure_is_nonzero(self):
        db = _make_db()
        insert_item(
            db, id=8, type="issue", status="implementing",
            project="buzz", github_issue="#43",
        )
        stderr = io.StringIO()

        with patch(
            f"{GH_PATCH}._github_auth_available", return_value=True,
        ), patch(
            f"{GH_PATCH}._validate_issue_in_repo",
            autospec=True,
            return_value=False,
        ):
            rc = backlog_github_sync.sync_frozen_label(
                "8", "true", conn=db, stderr=stderr,
            )

        assert rc == 1
        assert "issue validation failed" in stderr.getvalue()
        assert "repo mismatch" not in stderr.getvalue()
        db.close()


# ---------------------------------------------------------------------------
# sync_labels
# ---------------------------------------------------------------------------


class TestSyncLabels:
    def test_noop_when_no_github_issue(self):
        db = _make_db()
        insert_item(db, id=10, type="issue", status="idea", project="buzz")
        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            f"{_LABEL_REST_LABELS}.fetch_issue_labels",
        ) as fetch:
            rc = backlog_github_sync.sync_labels("10", conn=db)
        assert rc == 0
        fetch.assert_not_called()
        db.close()

    def test_dry_run_skips(self):
        db = _make_db()
        insert_item(db, id=10, type="issue", status="idea", project="buzz", github_issue="#5")
        stdout = io.StringIO()
        with patch.object(backlog_github_sync, "_dry_run", return_value=True):
            rc = backlog_github_sync.sync_labels("10", conn=db, stdout=stdout)
        assert rc == 0
        assert "DRY-RUN" in stdout.getvalue()
        db.close()

    def test_syncs_labels_in_correct_repo(self):
        db = _make_db()
        insert_item(
            db,
            id=10,
            type="issue",
            status="implementing",
            priority="high",
            project="buzz",
            github_issue="#55",
            source="ben",
        )
        stdout = io.StringIO()

        added: list[tuple] = []
        removed: list[tuple] = []

        def fake_add_labels(repo, issue_num, labels, *, token):
            added.append((repo, issue_num, tuple(labels)))

        def fake_remove_label(repo, issue_num, label, *, token):
            removed.append((repo, issue_num, label))

        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo", return_value=True,
        ), patch.object(
            backlog_github_label_sync, "resolve_project_github_auth",
            side_effect=_ok_resolver,
        ), patch(
            f"{_LABEL_REST_LABELS}.fetch_issue_labels",
            return_value=["status:idea", "priority:low", "type:issue", "source:ben"],
        ), patch(f"{_LABEL_REST_LABELS}.ensure_label"), patch(
            f"{_LABEL_REST_LABELS}.add_labels", side_effect=fake_add_labels,
        ), patch(
            f"{_LABEL_REST_LABELS}.remove_label", side_effect=fake_remove_label,
        ):
            rc = backlog_github_sync.sync_labels("10", conn=db, stdout=stdout)

        assert rc == 0
        assert "Labels synced: BUZ-10 → #55" in stdout.getvalue()

        added_labels_flat = [label for _, _, labels in added for label in labels]
        removed_labels = [label for _, _, label in removed]
        assert "status:implementing" in added_labels_flat
        assert "priority:high" in added_labels_flat
        assert "status:idea" in removed_labels
        assert "priority:low" in removed_labels
        db.close()

    def test_issue_validation_failure_is_not_green(self):
        db = _make_db()
        insert_item(db, id=10, type="issue", status="idea", project="buzz", github_issue="#5")
        stderr = io.StringIO()
        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo",
            autospec=True,
            return_value=False,
        ):
            rc = backlog_github_sync.sync_labels("10", conn=db, stderr=stderr)
        assert rc == 1
        assert "issue validation failed" in stderr.getvalue()
        assert "repo mismatch" not in stderr.getvalue()
        db.close()

    def test_label_helpers_ignore_stale_repo_projection(self):
        with patch.object(
            backlog_github_label_sync,
            "resolve_project_github_auth",
            side_effect=_ok_resolver,
        ), patch(
            f"{_LABEL_REST_LABELS}.fetch_issue_labels",
            return_value=["status:idea"],
        ) as fetch_labels, patch(
            f"{_LABEL_REST_LABELS}.fetch_issue_state",
            return_value="OPEN",
        ) as fetch_state, patch(
            f"{_LABEL_REST_LABELS}.ensure_label",
        ) as ensure_label, patch(
            f"{_LABEL_REST_LABELS}.add_labels",
        ) as add_labels, patch(
            f"{_LABEL_REST_LABELS}.remove_label",
        ) as remove_label:
            labels = backlog_github_label_sync._get_issue_labels(
                "55", "org/stale", "buzz",
            )
            state = backlog_github_label_sync._get_issue_state(
                "55", "org/stale", "buzz",
            )
            backlog_github_label_sync._ensure_label(
                "status:implementing", "C5DEF5", "org/stale", "buzz",
            )
            backlog_github_label_sync._reconcile_category(
                "status:", "status:implementing", ["status:idea"],
                "55", "org/stale", "buzz", "C5DEF5",
            )

        assert labels == ["status:idea"]
        assert state == "OPEN"
        assert fetch_labels.call_args.args[0] == "org/buzz"
        assert fetch_state.call_args.args[0] == "org/buzz"
        assert all(call.args[2] == "org/buzz" for call in ensure_label.call_args_list)
        assert add_labels.call_args.args[0] == "org/buzz"
        assert remove_label.call_args.args[0] == "org/buzz"

    def test_renders_source_and_owner_via_actor_label(self):
        """Post-Slice 5b shape: numeric source/owner render to label tokens
        through ``actor_label_or_passthrough`` rather than leaking the
        raw integer."""
        from yoke_core.domain.actors import resolve_actor_by_label

        db = _make_db()
        local_human = resolve_actor_by_label(db, "ben")
        yoke_core = resolve_actor_by_label(db, "yoke-core")
        assert local_human is not None and yoke_core is not None

        insert_item(
            db,
            id=11,
            type="issue",
            status="implementing",
            priority="high",
            project="buzz",
            github_issue="#56",
            source=str(local_human),
            owner=str(yoke_core),
        )
        stdout = io.StringIO()

        added: list[tuple] = []

        def fake_add_labels(repo, issue_num, labels, *, token):
            added.append((repo, issue_num, tuple(labels)))

        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo", return_value=True,
        ), patch.object(
            backlog_github_label_sync, "resolve_project_github_auth",
            side_effect=_ok_resolver,
        ), patch(
            f"{_LABEL_REST_LABELS}.fetch_issue_labels", return_value=[],
        ), patch(f"{_LABEL_REST_LABELS}.ensure_label"), patch(
            f"{_LABEL_REST_LABELS}.add_labels", side_effect=fake_add_labels,
        ), patch(f"{_LABEL_REST_LABELS}.remove_label"):
            rc = backlog_github_sync.sync_labels("11", conn=db, stdout=stdout)

        assert rc == 0
        added_flat = [label for _, _, labels in added for label in labels]
        assert "source:ben" in added_flat
        assert "owner:yoke-core" in added_flat
        # The raw numeric ids must not leak into any label payload.
        assert f"source:{local_human}" not in added_flat
        assert f"owner:{yoke_core}" not in added_flat
        # Status line surfaces both rendered tokens.
        assert "source:ben" in stdout.getvalue()
        assert "owner:yoke-core" in stdout.getvalue()
        db.close()


# ---------------------------------------------------------------------------
# Source / owner mutations trigger _sync_labels via LABEL_SYNC_FIELDS
# ---------------------------------------------------------------------------


class TestLabelSyncFieldsCoverage:
    """Pin the frozenset membership that wires the trigger.

    The label-sync trigger in ``backlog_update_op.execute_update`` is a
    one-line ``if field in LABEL_SYNC_FIELDS`` check. Pre-AC-1, ``source``
    and ``owner`` were absent from the set and silently bypassed
    ``_sync_labels`` on every mutation — that produced 1962 label-owner
    plus 434 label-source drift rows. The unsupported-field bridge owns
    ``source`` / ``owner`` writes today, so the trigger is pinned both by
    set membership and by an ``execute_update`` regression below."""

    def test_label_sync_fields_includes_source_and_owner(self):
        from yoke_core.domain.backlog_queries import LABEL_SYNC_FIELDS

        assert "source" in LABEL_SYNC_FIELDS
        assert "owner" in LABEL_SYNC_FIELDS

    def test_label_sync_fields_retains_previous_members(self):
        """Defense in depth: don't accidentally drop the prior set."""
        from yoke_core.domain.backlog_queries import LABEL_SYNC_FIELDS

        for prior in ("status", "priority", "type", "worktree"):
            assert prior in LABEL_SYNC_FIELDS
