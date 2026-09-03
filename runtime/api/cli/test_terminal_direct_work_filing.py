"""Plain-terminal filing contract for the direct-work CLI helpers."""

from __future__ import annotations

import os
from unittest import mock

import pytest

from runtime.api.backlog_mutations_test_helpers import (
    _conn,
    _patch_externals,
    tmp_db,  # noqa: F401 — re-exported pytest fixture
)
from yoke_cli.commands.adapters import dash_file, task
from yoke_contracts.session_identity import AMBIENT_ENV_VARS
from yoke_core.domain import backlog_create_op


def test_item_create_is_registered_for_sessionless_terminal_filing():
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_core.domain.yoke_function_registry import lookup

    register_all_handlers()
    entry = lookup("items.create")
    assert entry is not None
    assert entry.ambient_session_required is False


@pytest.mark.parametrize(
    ("file_command", "workflow"),
    ((dash_file.dash_file, "dash"), (task.task_file, "task")),
)
def test_direct_work_filing_without_harness_session(
    file_command,
    workflow,
    tmp_db,  # noqa: F811 — pytest injects the re-exported fixture
    monkeypatch,
):
    for name in AMBIENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("YOKE_ACTOR_ID", raising=False)
    real_resolver = backlog_create_op.resolve_item_source_actor

    with (
        _patch_externals(),
        mock.patch(
            "yoke_core.domain.backlog_create_op.resolve_item_source_actor",
            side_effect=real_resolver,
        ),
        mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}),
    ):
        result = file_command(
            [
                f"Terminal {workflow}",
                "File direct work from a plain terminal.",
                "--project",
                "yoke",
                "--execution-instructions-considered",
            ]
        )

    assert result == 0
    conn = _conn(tmp_db)
    try:
        item = conn.execute(
            "SELECT workflow_id, source FROM items ORDER BY id DESC LIMIT 1"
        ).fetchone()
        human = conn.execute(
            "SELECT id FROM actors WHERE kind = 'human' ORDER BY id LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert item["workflow_id"] == workflow
    assert int(item["source"]) == int(human["id"])
