"""Done-transition batched GitHub sync coverage.

Tests mock the typed REST surface used by ``sync_done_item``:
``backlog_github_done_sync.github_rest`` (get_issue, set_issue_state),
``backlog_github_done_sync._label_rest`` (add_labels, remove_label),
``backlog_github_done_sync._writer`` (update_issue_body_typed).
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
    backlog_github_body_budget as _budget,
    backlog_github_done_sync,
    backlog_github_sync,
    github_rest,
)
from yoke_core.domain.backlog_github_body_writer import BodyWriteResult
from yoke_core.domain.project_github_auth import ProjectGithubAuth


_DONE_GH_REST = "yoke_core.domain.backlog_github_done_sync.github_rest"
_DONE_LABEL_REST = "yoke_core.domain.backlog_github_done_sync._label_rest"
_DONE_WRITER = "yoke_core.domain.backlog_github_done_sync._writer"


def _ok_resolver(*args, **kwargs):
    proj = kwargs.get("project") or (args[0] if args else "externalwebapp")
    return ProjectGithubAuth(
        project=proj, repo="org/externalwebapp", token="ghs_fake",
    )


def _existing_issue(number: int, *, labels: tuple[str, ...], state: str = "OPEN"):
    return github_rest.Issue(
        number=number, title="t", state=state, labels=labels,
    )


def test_sync_done_item_batches_body_labels_and_close():
    db = _make_db()
    insert_item(
        db,
        id=70,
        type="issue",
        status="done",
        project="externalwebapp",
        github_issue="#700",
        source="ben",
        owner="ben",
    )
    stdout = io.StringIO()

    existing_labels = (
        "status:release", "priority:medium", "type:issue",
        "source:ben", "owner:ben",
    )

    with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
        f"{GH_PATCH}._validate_issue_in_repo",
        autospec=True,
        return_value=True,
    ), patch.object(
        backlog_github_done_sync, "resolve_project_github_auth",
        side_effect=_ok_resolver,
    ) as resolve_auth, patch(
        f"{_DONE_GH_REST}.get_issue",
        return_value=_existing_issue(700, labels=existing_labels),
    ), patch(
        f"{_DONE_WRITER}.update_issue_body_typed",
        return_value=BodyWriteResult(returncode=0, mode="full", stdout="", stderr=""),
    ) as update_body, patch(
        f"{_DONE_LABEL_REST}.add_labels",
    ) as add_labels, patch(
        f"{_DONE_LABEL_REST}.remove_label",
    ) as remove_label, patch(
        f"{_DONE_GH_REST}.set_issue_state",
    ) as set_state, patch(f"{GH_PATCH}._ensure_label"):
        rc = backlog_github_sync.sync_done_item(
            "70", "release", conn=db, stdout=stdout,
        )

    assert rc == 0
    assert resolve_auth.call_args_list[-1].kwargs == {
        "required_permissions": GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
    }
    assert "Done sync: EXT-70" in stdout.getvalue()
    update_body.assert_called_once()
    # Status label moves release → done.
    added_labels_flat = []
    for call in add_labels.call_args_list:
        # add_labels(target_repo, issue_num, labels, token=...)
        added_labels_flat.extend(call.args[2])
    assert "status:done" in added_labels_flat
    removed_labels = [call.args[2] for call in remove_label.call_args_list]
    assert "status:release" in removed_labels
    # Issue gets closed once with comment.
    set_state.assert_called_once()
    assert set_state.call_args.kwargs["state"] == "closed"
    assert "`release` -> `done`" in set_state.call_args.kwargs["comment"]
    db.close()


def test_sync_done_item_uses_compact_mirror_when_body_exceeds_budget():
    """EXT-1704-shape reproduction: an oversized rendered body must ship as
    the compact mirror, not the raw full body that triggers a REST body-
    size rejection on ``update_issue``.
    """
    db = _make_db()
    insert_item(
        db,
        id=72,
        type="issue",
        status="done",
        project="externalwebapp",
        github_issue="#4114",
        source="ben",
        owner="ben",
        title="Oversized body item",
        spec="x" * (_budget.GITHUB_BODY_BUDGET_BYTES + 500),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    captured_bodies: list[str] = []

    def fake_update(*, project, number, body, item_fields, conn, item_id, stderr=None):
        # update_issue_body_typed calls select_body_for_github under the hood;
        # mirror that selection here so the test exercises the same path the
        # writer takes.
        chosen, mode = _budget.select_body_for_github(
            body, item_fields=item_fields, conn=conn, item_id=item_id,
        )
        captured_bodies.append(chosen)
        return BodyWriteResult(returncode=0, mode=mode, stdout="", stderr="")

    with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
        f"{GH_PATCH}._validate_issue_in_repo", return_value=True,
    ), patch.object(
        backlog_github_done_sync, "resolve_project_github_auth",
        side_effect=_ok_resolver,
    ), patch(
        f"{_DONE_GH_REST}.get_issue",
        return_value=_existing_issue(
            4114,
            labels=("status:release", "priority:medium", "type:issue",
                    "source:ben", "owner:ben"),
        ),
    ), patch(
        f"{_DONE_WRITER}.update_issue_body_typed", side_effect=fake_update,
    ), patch(
        f"{_DONE_LABEL_REST}.add_labels",
    ), patch(
        f"{_DONE_LABEL_REST}.remove_label",
    ), patch(
        f"{_DONE_GH_REST}.set_issue_state",
    ), patch(f"{GH_PATCH}._ensure_label"):
        rc = backlog_github_sync.sync_done_item(
            "72", "release", conn=db, stdout=stdout, stderr=stderr,
        )

    assert rc == 0
    assert captured_bodies, "update_issue_body_typed was not called"
    chosen = captured_bodies[0]
    # Compact mirror is well under budget and references EXT-72.
    assert _budget.body_exceeds_budget(chosen) is False
    assert "EXT-72" in chosen
    assert "compact mirror" in stdout.getvalue()
    db.close()


def test_validate_issue_in_repo_no_false_mismatch_on_project_repo():
    """Regression: ``_validate_issue_in_repo`` must NOT fall through to the
    default-repo mismatch branch when the issue exists in the named repo.

    Mocks the typed REST transport (via the github_rest_issues surface,
    which itself wraps gh_rest_transport.request_with_retry) so no host
    ``gh`` is involved.
    """
    from unittest.mock import patch as _patch

    from yoke_core.domain import epic_task_sync_github
    from yoke_core.domain.github_rest import Target
    from yoke_core.domain.project_github_auth import ProjectGithubAuth

    item_ref = "1"
    issue_num = "1"
    project_repo = "owner-x/name-y"
    stderr = io.StringIO()

    _target = Target(
        project="yoke", owner="owner-x", repo="name-y",
        token="pat", repo_slug=project_repo,
    )
    project_auth = ProjectGithubAuth(project="yoke", repo=project_repo, token="pat")

    with _patch(
        "yoke_core.domain.epic_task_sync_github.resolve_project_github_auth",
        return_value=project_auth,
    ), _patch(
        "yoke_core.domain.github_rest_issues._target_for", return_value=_target,
    ), _patch(
        "yoke_core.domain.github_rest_issues.request_with_retry",
        return_value=type("R", (), {"body": {"number": 1, "title": "T",
                                              "state": "open"}})(),
    ):
        ok = epic_task_sync_github._validate_issue_in_repo(
            item_ref, issue_num, project="yoke", stderr=stderr,
        )

    assert ok is True
    assert "Repo mismatch" not in stderr.getvalue()
    assert "rate-limited" not in stderr.getvalue()
    assert "permission denied" not in stderr.getvalue()
