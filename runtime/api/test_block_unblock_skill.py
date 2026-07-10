"""End-to-end behavior for /yoke block and /yoke unblock.

The skills are operator-facing markdown; what is testable in pytest is the
underlying contract they execute against ``items update``:

- Setting ``blocked=true`` flips ``items.blocked`` to 1, preserves the
  lifecycle ``status``, and (when GitHub mocks are wired) the
  ``backlog_update_op.execute_update`` side-effect path calls
  ``sync_blocked_label``.
- Setting ``blocked=false`` flips back to 0 and removes the label.
- Independent reason field round-trips intact.

These tests exercise the canonical update surface (the same path the
markdown skill bodies invoke) so the contract holds regardless of which
operator surface fires the field write.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from runtime.api.backlog_github_sync_test_helpers import GH_PATCH
from yoke_core.domain import backlog_github_state_sync, backlog_update_op, db_backend
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


_LABEL_REST_STATE = "yoke_core.domain.backlog_github_state_sync._label_rest"


def _ok_resolver(*args, **kwargs):
    proj = kwargs.get("project") or (args[0] if args else "yoke")
    return ProjectGithubAuth(
        project=proj, repo="upyoke/yoke", token="ghs_fake",
    )


@pytest.fixture(autouse=True)
def _patch_db_path(monkeypatch, tmp_path):
    """Backend-aware per-test DB for the block/unblock contract.

    backlog_update_op.execute_update opens its own connection through the
    backend factory; init_test_db points that factory at this per-test DB
    (YOKE_DB on SQLite, the repointed YOKE_PG_DSN on Postgres) for the
    test's lifetime so the update lands on the same row the test seeded.
    """
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", str(db_path))
        yield


def _setup_item(item_id=42, status="implementing"):
    # Schema is applied by the autouse init_test_db fixture; seed the row
    # through the backend-aware connection so it lands on the same DB
    # backlog_update_op opens (SQLite file or repointed PG database).
    conn = connect_test_db(os.environ["YOKE_DB"])
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "project_id, project_sequence, created_at, updated_at, source) "
        f"VALUES ({p}, 'test', 'issue', {p}, 'medium', "
        f"1, {p}, '2026-01-01T00:00:00Z', "
        "'2026-01-01T00:00:00Z', '2')",
        (item_id, status, item_id),
    )
    conn.commit()
    return conn


def test_block_sets_flag_and_preserves_status():
    db = _setup_item(item_id=42, status="implementing")
    with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
        f"{GH_PATCH}._validate_issue_in_repo", return_value=True,
    ), patch.object(
        backlog_github_state_sync, "resolve_project_github_auth",
        side_effect=_ok_resolver,
    ), patch(f"{_LABEL_REST_STATE}.ensure_label"), patch(
        f"{_LABEL_REST_STATE}.add_labels",
    ), patch(f"{_LABEL_REST_STATE}.remove_label"):
        result = backlog_update_op.execute_update(
            42, "blocked", "true", no_github=False, rebuild_board=False,
        )
    assert result["success"], result
    row = db.execute("SELECT blocked, status FROM items WHERE id=42").fetchone()
    assert row[0] == 1
    assert row[1] == "implementing"
    db.close()


def test_unblock_clears_flag_and_preserves_status():
    db = _setup_item(item_id=43, status="refined-idea")
    db.execute("UPDATE items SET blocked = 1 WHERE id = 43")
    db.commit()
    with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
        f"{GH_PATCH}._validate_issue_in_repo", return_value=True,
    ), patch.object(
        backlog_github_state_sync, "resolve_project_github_auth",
        side_effect=_ok_resolver,
    ), patch(f"{_LABEL_REST_STATE}.ensure_label"), patch(
        f"{_LABEL_REST_STATE}.add_labels",
    ), patch(f"{_LABEL_REST_STATE}.remove_label"):
        result = backlog_update_op.execute_update(
            43, "blocked", "false", no_github=False, rebuild_board=False,
        )
    assert result["success"], result
    row = db.execute("SELECT blocked, status FROM items WHERE id=43").fetchone()
    assert row[0] == 0
    assert row[1] == "refined-idea"
    db.close()


def test_blocked_reason_round_trips():
    db = _setup_item(item_id=44, status="implementing")
    result = backlog_update_op.execute_update(
        44, "blocked_reason", "Awaiting external sign-off",
        no_github=True, rebuild_board=False,
    )
    assert result["success"], result
    row = db.execute("SELECT blocked_reason FROM items WHERE id=44").fetchone()
    assert row[0] == "Awaiting external sign-off"
    db.close()


def test_block_rejects_invalid_value():
    _setup_item(item_id=45, status="implementing")
    result = backlog_update_op.execute_update(
        45, "blocked", "maybe", no_github=True, rebuild_board=False,
    )
    assert not result["success"]
    assert "blocked" in (result.get("error") or "").lower()
