"""In-process integration coverage for the merge-engine internal ops.

Exercises the two ``merge.*`` internal handlers against a seeded Postgres
authority. Each handler is a thin wrapper over unchanged domain state;
these tests prove the wrapper reads/writes real DB rows server-side and
returns the verdict in its declared response shape. This is the local /
in-process leg of the ALL-MODES contract; the relay leg is covered by
``test_merge_worktree_post_transport``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import (
    insert_item,
    insert_item_worktree,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.handlers import merge_engine_internal_ops as ops


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _global_envelope(function, *, payload):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id="s-merge-engine"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _item_envelope(function, *, item_id, payload=None):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id="s-merge-engine"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload or {},
    )


class TestPruneAuthorityVerdict:
    def test_terminal_unclaimed_owner_is_prunable(self, db):
        item_id, branch = 9401, "codex/terminal-9401"
        conn = connect_test_db(db)
        try:
            insert_item(
                conn, id=item_id, status="done",
                source=str(seed_human_actor(conn)),
            )
            insert_item_worktree(
                conn, item_id=item_id, branch=branch, lane_role="worker"
            )
        finally:
            conn.close()
        outcome = ops.handle_prune_authority_verdict(
            _global_envelope(
                "merge.prune.authority_verdict", payload={"branch": branch}
            )
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["prunable"] is True
        assert outcome.result_payload["reason"] == "prunable"
        ops.PruneAuthorityResponse(**outcome.result_payload)

    def test_nonterminal_owner_is_not_prunable(self, db):
        item_id, branch = 9402, "codex/live-9402"
        conn = connect_test_db(db)
        try:
            insert_item(
                conn, id=item_id, status="implementing",
                source=str(seed_human_actor(conn)),
            )
            insert_item_worktree(
                conn, item_id=item_id, branch=branch, lane_role="worker"
            )
        finally:
            conn.close()
        outcome = ops.handle_prune_authority_verdict(
            _global_envelope(
                "merge.prune.authority_verdict", payload={"branch": branch}
            )
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["prunable"] is False
        assert outcome.result_payload["reason"] == "no_terminal_owner"

    def test_unknown_branch_has_no_terminal_owner(self, db):
        outcome = ops.handle_prune_authority_verdict(
            _global_envelope(
                "merge.prune.authority_verdict", payload={"branch": "nope/x"}
            )
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["prunable"] is False
        assert outcome.result_payload["reason"] == "no_terminal_owner"

    def test_missing_branch_is_payload_invalid(self, db):
        outcome = ops.handle_prune_authority_verdict(
            _global_envelope("merge.prune.authority_verdict", payload={})
        )
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "payload_invalid"


class TestPostRebaseRequirement:
    def test_registered_full_command_is_returned_without_attachment(self, db):
        item_id = 9411
        conn = connect_test_db(db)
        try:
            insert_item(conn, id=item_id, source=str(seed_human_actor(conn)))
            from yoke_core.domain.qa_command_plan_registration import (
                ensure_registered_command_plan,
            )

            ensure_registered_command_plan(
                conn,
                project_id=1,
                project="yoke",
                scope="full",
                command="python3 verify_tree.py",
            )
        finally:
            conn.close()
        outcome = ops.handle_post_rebase_requirement(
            _item_envelope(
                "merge.tests.post_rebase_requirement", item_id=item_id
            )
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload == {
            "requirement_id": None,
            "project": "yoke",
            "scope": "full",
            "command": "python3 verify_tree.py",
        }
        ops.PostRebaseRequirementResponse(**outcome.result_payload)

    def test_project_without_full_or_quick_command_is_rejected(self, db):
        item_id = 9412
        conn = connect_test_db(db)
        try:
            insert_item(conn, id=item_id, source=str(seed_human_actor(conn)))
            conn.execute(
                "UPDATE qa_plans SET retired_at='2026-01-01T00:00:00Z' "
                "WHERE project_id=1 AND slug IN ('registered-command-full', "
                "'registered-command-quick')"
            )
            conn.commit()
        finally:
            conn.close()

        outcome = ops.handle_post_rebase_requirement(
            _item_envelope(
                "merge.tests.post_rebase_requirement", item_id=item_id
            )
        )

        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "post_rebase_verification_missing"

    def test_quick_command_is_fallback_when_full_is_retired(self, db):
        item_id = 9413
        conn = connect_test_db(db)
        try:
            insert_item(conn, id=item_id, source=str(seed_human_actor(conn)))
            from yoke_core.domain.qa_command_plan_registration import (
                ensure_registered_command_plan,
            )

            ensure_registered_command_plan(
                conn,
                project_id=1,
                project="yoke",
                scope="quick",
                command="python3 quick_verify.py",
            )
            conn.execute(
                "UPDATE qa_plans SET retired_at='2026-01-01T00:00:00Z' "
                "WHERE project_id=1 AND slug='registered-command-full'"
            )
            conn.commit()
        finally:
            conn.close()

        outcome = ops.handle_post_rebase_requirement(
            _item_envelope(
                "merge.tests.post_rebase_requirement", item_id=item_id
            )
        )

        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["scope"] == "quick"
        assert outcome.result_payload["command"] == "python3 quick_verify.py"

    def test_attached_plan_materialization_failure_is_structured(
        self,
        db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        item_id = 9414
        conn = connect_test_db(db)
        try:
            insert_item(conn, id=item_id, source=str(seed_human_actor(conn)))
        finally:
            conn.close()
        from yoke_core.domain import qa_plan_attachments

        monkeypatch.setattr(
            qa_plan_attachments,
            "has_attached_plans",
            lambda *_args, **_kwargs: True,
        )

        def fail_materialization(*_args, **_kwargs):
            raise RuntimeError("snapshot write failed")

        monkeypatch.setattr(
            qa_plan_attachments,
            "materialize_for_item",
            fail_materialization,
        )

        outcome = ops.handle_post_rebase_requirement(
            _item_envelope(
                "merge.tests.post_rebase_requirement", item_id=item_id
            )
        )

        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "post_rebase_requirement_failed"
        assert "snapshot write failed" in outcome.error.message

    def test_missing_item_target_is_invalid(self, db):
        outcome = ops.handle_post_rebase_requirement(
            _global_envelope(
                "merge.tests.post_rebase_requirement", payload={}
            )
        )
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "target_invalid"
