"""items.create on a bound project with GitHub issue-sync disabled.

A repo binding is for code delivery; ``github_sync_mode=disabled`` means the
backlog stays DB-only. Create must record that skip as unmirrored, not as a
successful sync that then warns to run ``yoke resync --fix``.
"""

from __future__ import annotations

import os
from unittest import mock

from runtime.api.backlog_mutations_test_helpers import (
    _conn,
    _item_field,
    _patch_externals,
    tmp_db,  # noqa: F401 — re-exported pytest fixture
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import backlog_github_mirror_state as mirror
from yoke_core.domain import backlog_rendering
from yoke_core.domain.backlog_rendering import _sync_item as live_sync_item
from yoke_core.domain.handlers.items_create import handle_item_create
from yoke_core.domain.item_entry_surface import ITEM_ENTRY_SURFACE_ENV
from yoke_core.domain.projects_github_sync_mode import (
    GITHUB_SYNC_DISABLED,
    github_sync_disabled_notice,
)


def _request(payload):
    return FunctionCallRequest(
        function="items.create",
        actor=ActorContext(session_id="items-create-disabled-sync"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _bind_yoke_repo(path) -> None:
    conn = _conn(path)
    try:
        conn.execute(
            "UPDATE projects SET github_sync_mode = %s WHERE slug = %s",
            (GITHUB_SYNC_DISABLED, "yoke"),
        )
        conn.execute(
            "INSERT INTO project_github_repo_bindings "
            "(project_id, installation_id, repository_id, github_repo, "
            "created_at, updated_at) "
            "VALUES (1, 'inst-1', 'repo-1', 'upyoke/yoke', "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
        )
        conn.commit()
    finally:
        conn.close()


def test_items_create_skip_on_bound_disabled_project_is_unmirrored(
    tmp_db, monkeypatch,  # noqa: F811
):
    _bind_yoke_repo(tmp_db)
    monkeypatch.delenv(ITEM_ENTRY_SURFACE_ENV, raising=False)
    with (
        _patch_externals() as patches,
        mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}),
        mock.patch(
            "yoke_core.domain.backlog_github_item_create.github_rest.create_issue",
            side_effect=AssertionError("issue created for disabled project"),
        ),
    ):
        monkeypatch.setattr(backlog_rendering, "_sync_item", live_sync_item)
        outcome = handle_item_create(
            _request(
                {
                    "title": "Skip must not look synced",
                    "instruction": "Create a task against a sync-disabled project.",
                    "workflow": "task",
                    "project": "yoke",
                    "entry_surface": "cli",
                    "execution_instructions_considered": True,
                }
            )
        )

    assert outcome.primary_success is True, outcome.error
    log = outcome.result_payload.get("log") or ""
    assert github_sync_disabled_notice("yoke", "sync-item") in log
    assert "resync --fix" not in log
    assert "unmirrored" in log
    assert "skipped" in log
    item_id = outcome.result_payload["item_id"]
    assert _item_field(tmp_db, item_id, "github_issue") in (None, "", "null")
    emit = patches["_emit_event"]
    absence = [
        call
        for call in emit.call_args_list
        if call.args and call.args[0] == mirror.UNMIRRORED_EVENT_NAME
    ]
    assert absence, emit.call_args_list
    context = absence[0].args[2]
    assert context["attempt"] == mirror.MIRROR_ATTEMPT_SKIPPED
    assert context["mirror_state"] == mirror.MIRROR_STATE_UNMIRRORED
    assert context["github_app_bound"] is True
