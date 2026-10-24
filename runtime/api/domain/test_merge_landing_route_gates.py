"""``merge item --check`` asks the landing route's gates through the merge's code."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_merge_landing_readiness import _item, _run, merge  # noqa: F401
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import merge_landing_readiness as readiness_gate
from yoke_core.domain import qa_plan_attachments
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.handlers import merge_engine_internal_ops as ops
from yoke_core.domain.merge_queue_route_selection import RouteAdmission
from yoke_core.engines import merge_worktree_tests

ITEM_ID = 9481
READY = ("--result", "r", "--verification", "v")


@pytest.fixture
def no_verification_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A project with no registered full or quick command, served by the real handler."""
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        conn = connect_test_db(db_path)
        try:
            insert_item(conn, id=ITEM_ID, source=str(seed_human_actor(conn)))
            conn.execute(
                "UPDATE qa_plans SET retired_at='2026-01-01T00:00:00Z' "
                "WHERE project_id=1 AND slug IN ('registered-command-full', "
                "'registered-command-quick')"
            )
            conn.commit()
        finally:
            conn.close()
        asked: list[bool] = []

        def resolve(_ref, transition_id, materialize=True):
            asked.append(materialize)
            outcome = ops.handle_post_rebase_requirement(
                FunctionCallRequest(
                    function="merge.tests.post_rebase_requirement",
                    actor=ActorContext(actor_id=None, session_id="s-1"),
                    target=TargetRef(kind="item", item_id=ITEM_ID),
                    payload={"transition_id": transition_id, "materialize": materialize},
                )
            )
            return SimpleNamespace(
                success=outcome.primary_success,
                error=outcome.error,
                result=outcome.result_payload,
            )

        monkeypatch.setattr(merge_worktree_tests, "_resolve_requirement", resolve)
        monkeypatch.setattr(
            merge_worktree_tests,
            "_post_rebase_transition_candidates",
            lambda _ref: ["release"],
        )
        monkeypatch.setattr(
            readiness_gate, "resolve_verification", merge_worktree_tests.resolve_verification
        )
        yield asked


def _ready(merge) -> None:  # noqa: F811
    merge["item"] = _item(status="reviewing-implementation", completion_flow="")


def test_check_reports_the_missing_verification_command_and_its_recovery(
    merge, no_verification_command, capsys  # noqa: F811
):
    _ready(merge)

    assert _run("--check", "--json", *READY) == 1

    report = json.loads(capsys.readouterr().out)
    [blocker] = report["blockers"]
    assert blocker["gate"] == "verification command"
    assert "(post_rebase_verification_missing)" in blocker["reason"]
    assert "yoke qa registered-command set --project yoke" in blocker["reason"]
    assert "yoke qa no-tests attest --project yoke" in blocker["reason"]
    assert no_verification_command == [False]
    assert merge["landed"] == 0


def test_the_merge_refuses_with_the_same_blocker_before_landing(
    merge, no_verification_command, capsys  # noqa: F811
):
    _ready(merge)
    assert _run("--check", "--json", *READY) == 1
    [checked] = json.loads(capsys.readouterr().out)["blockers"]

    assert _run(*READY) == 1

    err = capsys.readouterr().err
    assert f"[{checked['gate']}] {checked['reason']}" in err
    assert merge["landed"] == 0


def test_check_writes_no_qa_plan_snapshot(
    merge, no_verification_command, monkeypatch  # noqa: F811
):
    _ready(merge)
    monkeypatch.setattr(qa_plan_attachments, "has_attached_plans", lambda *_a, **_k: True)

    def refuse(*_a, **_k):
        raise AssertionError("--check materialized a QA plan")

    monkeypatch.setattr(qa_plan_attachments, "materialize_for_item", refuse)

    assert _run("--check", "--json", *READY) == 1


def test_a_route_refusal_is_a_blocker_and_skips_the_verification_question(
    merge, monkeypatch, capsys  # noqa: F811
):
    _ready(merge)
    monkeypatch.setattr(
        readiness_gate,
        "route_admission",
        lambda **_k: RouteAdmission("candidate review", "a person must review abc"),
    )
    monkeypatch.setattr(
        readiness_gate,
        "resolve_verification",
        lambda *_a, **_k: pytest.fail("verification asked after a route refusal"),
    )

    assert _run("--check", "--json", *READY) == 1

    report = json.loads(capsys.readouterr().out)
    assert report["blockers"] == [
        {"gate": "candidate review", "reason": "a person must review abc"}
    ]


def test_a_queue_landing_does_not_ask_the_local_verification_command(
    merge, monkeypatch, capsys  # noqa: F811
):
    _ready(merge)
    monkeypatch.setattr(
        readiness_gate,
        "route_admission",
        lambda **_k: RouteAdmission(declares_queue=True),
    )
    monkeypatch.setattr(
        readiness_gate,
        "resolve_verification",
        lambda *_a, **_k: pytest.fail("queue landing asked for a local command"),
    )

    assert _run("--check", *READY) == 0
    assert "ITEM-51: ready to land." in capsys.readouterr().out
