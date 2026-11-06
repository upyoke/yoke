# ruff: noqa: E402, F401, F811
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
    local_human,
    seed_target,
)

from yoke_core.domain.path_claims import (
    activate,
    cancel,
    get_claim,
    register,
)

from yoke_core.domain.path_claims_item_hook_release import (
    release_claims_on_item_terminal,
)


def _seed_item(conn, *, item_id: int):
    conn.execute(
        "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 't', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    conn.commit()
    return item_id
