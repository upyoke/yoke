"""A project that attested no test suite merges with no verification command."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.handlers import merge_engine_internal_ops as ops
from yoke_core.domain.project_verification_posture import attest_no_tests
from yoke_core.engines import merge_worktree_tests as mod

ITEM_ID = 9431
REASON = "documentation-only project"


@pytest.fixture
def attested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        conn = connect_test_db(db_path)
        try:
            insert_item(conn, id=ITEM_ID, source=str(seed_human_actor(conn)))
            attest_no_tests(conn, project_id=1, project="yoke", reason=REASON)
        finally:
            conn.close()
        yield db_path


def _requirement():
    return ops.handle_post_rebase_requirement(
        FunctionCallRequest(
            function="merge.tests.post_rebase_requirement",
            actor=ActorContext(actor_id=None, session_id="s-no-tests"),
            target=TargetRef(kind="item", item_id=ITEM_ID),
            payload={},
        )
    )


def test_attested_project_resolves_without_a_command(attested) -> None:
    outcome = _requirement()

    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["no_tests_reason"] == REASON
    assert outcome.result_payload["command"] == ""
    ops.PostRebaseRequirementResponse(**outcome.result_payload)


def test_merge_after_attestation_runs_no_suite(
    attested,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def dispatch(**kwargs):
        if kwargs["function_id"] == "items.detail.get":
            return SimpleNamespace(
                success=True, result={"item": {"status": "release"}}, error=None
            )
        outcome = _requirement()
        return SimpleNamespace(
            success=outcome.primary_success,
            result=outcome.result_payload,
            error=outcome.error,
        )

    monkeypatch.setattr(mod, "call_dispatcher", dispatch)
    # A package.json must not pull an attested project into legacy detection.
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    ctx = SimpleNamespace(item_id=f"YOK-{ITEM_ID}", worktree_path=str(tmp_path))

    assert mod.run_tests(ctx) is None
    out = capsys.readouterr().out
    assert f"project attested no test suite ({REASON})" in out
    assert "npm test" not in out
