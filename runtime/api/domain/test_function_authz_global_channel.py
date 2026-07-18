"""Authorization coverage for the global field-note channel."""

from __future__ import annotations

import pytest

from yoke_core.domain.yoke_function_permissions import check_dispatch_permission
from runtime.api.domain.test_function_authz_scope_routing import (
    _entry,
    _new_actor,
    _request,
    conn as _source_conn,
)


@pytest.fixture
def conn():
    yield from _source_conn.__wrapped__()


@pytest.mark.parametrize(
    ("function_id", "side_effects"),
    (
        ("ouroboros.field_note.append", True),
        ("ouroboros.field_note.list", False),
        ("ouroboros.field_note.get", False),
    ),
)
def test_global_field_note_channel_needs_no_project_target(
    conn, function_id: str, side_effects: bool,
) -> None:
    actor_id = _new_actor(conn)
    permission = check_dispatch_permission(
        conn,
        _entry(function_id, side_effects=side_effects),
        _request(actor_id, function_id),
    )

    assert permission.error is None
    assert permission.permission_key is None
    assert permission.project_id is None
    assert permission.project_slug is None
