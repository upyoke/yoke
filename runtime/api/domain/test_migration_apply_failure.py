# ruff: noqa: F811

"""migration_apply — live-verify failure recovery and profile gating.

Split out of ``test_migration_apply.py`` to keep authored files under the
350-line limit. Heavy fixture/helper code lives in
``migration_apply_test_helpers``.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.conftest import insert_item
from yoke_core.domain import migration_apply
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
from yoke_contracts.migration_rehearsal_teaching import CONNECTION_READER


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


class TestUnresolvableItemReference:
    """An unresolvable ref is a wrong-universe signal, not a redacted crash."""

    def test_cli_reports_the_selected_universe_and_how_to_change_it(
        self, monkeypatch, capsys
    ) -> None:
        monkeypatch.setattr(
            migration_apply,
            "_parse_item_id",
            lambda _raw: (_ for _ in ()).throw(
                ValueError("item ref 'YOK-2218' not found")
            ),
        )

        assert migration_apply.main(["rehearse", "YOK-2218"]) == 1

        reported = capsys.readouterr().err
        assert "item ref 'YOK-2218' not found" in reported
        assert CONNECTION_READER in reported

    def test_rehearsal_never_runs_when_the_reference_cannot_resolve(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            migration_apply,
            "_parse_item_id",
            lambda _raw: (_ for _ in ()).throw(ValueError("unresolvable")),
        )
        monkeypatch.setattr(
            migration_apply,
            "rehearse",
            lambda *_a, **_k: pytest.fail("rehearsed an unresolved reference"),
        )

        assert migration_apply.main(["rehearse", "YOK-2218"]) == 1
