"""migration_apply — live-verify failure recovery and profile gating.

Split out of ``test_migration_apply.py`` to keep authored files under the
350-line limit. Heavy fixture/helper code lives in
``migration_apply_test_helpers``.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.conftest import insert_item
from yoke_core.domain.migration_apply import (
    MigrationApplyError,
    ProfileNotApplyError,
    rehearse,
)
from runtime.api.domain.migration_apply_test_helpers import (  # noqa: F401 — fixtures
    _audit_row,
    _seed_apply_item,
    apply_env,
)
from runtime.api.test_backlog import _conn, tmp_db  # noqa: F401 — reused fixtures


class TestProfileGating:
    def test_state_none_profile_refused(self, apply_env) -> None:
        conn = _conn(apply_env["control_db"])
        try:
            insert_item(
                conn,
                id=5040,
                project="yoke",
                status="implementing",
                db_mutation_profile=json.dumps({"state": "none"}),
            )
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(ProfileNotApplyError):
            rehearse(
                5040,
                control_db_path=apply_env["control_db"],
                worktree_path=apply_env["worktree"],
            )


    def test_unknown_item_raises(self, apply_env) -> None:
        with pytest.raises(MigrationApplyError):
            rehearse(
                9999,
                control_db_path=apply_env["control_db"],
                worktree_path=apply_env["worktree"],
            )
