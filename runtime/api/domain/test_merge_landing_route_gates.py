"""``merge item --check`` asks the landing route's gates through the merge's code."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.domain.merge_landing_readiness_test_support import _item, _run, merge  # noqa: F401
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import merge_landing_readiness as readiness_gate
from yoke_core.domain import qa_plan_attachments
from yoke_core.domain import merge_queue_admission_gates as queue_gates
from yoke_core.domain.merge_github_discovery import BranchListing
from yoke_core.domain.merge_github_queue import QueueMember, PrLandingState
from yoke_core.domain.merge_github_train_run import TrainRunLookupFailure
from runtime.api.merge_queue_landing_test_helpers import dispatch_for
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.handlers import merge_engine_internal_ops as ops
from yoke_core.domain.merge_queue_route_selection import RouteAdmission
from yoke_core.domain import merge_verification as merge_worktree_tests

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
                    payload={
                        "transition_id": transition_id,
                        "materialize": materialize,
                    },
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
            readiness_gate,
            "resolve_verification",
            merge_worktree_tests.resolve_verification,
        )
        yield asked


def _ready(merge) -> None:  # noqa: F811
    merge["item"] = _item(status="reviewing-implementation", completion_flow="")


def test_check_reports_the_missing_verification_command_and_its_recovery(
    merge,  # noqa: F811
    no_verification_command,
    capsys,
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
    merge,  # noqa: F811
    no_verification_command,
    capsys,
):
    _ready(merge)
    assert _run("--check", "--json", *READY) == 1
    [checked] = json.loads(capsys.readouterr().out)["blockers"]

    assert _run(*READY) == 1

    err = capsys.readouterr().err
    assert f"[{checked['gate']}] {checked['reason']}" in err
    assert merge["landed"] == 0


def test_check_writes_no_qa_plan_snapshot(
    merge,  # noqa: F811
    no_verification_command,
    monkeypatch,
):
    _ready(merge)
    monkeypatch.setattr(
        qa_plan_attachments, "has_attached_plans", lambda *_a, **_k: True
    )

    def refuse(*_a, **_k):
        raise AssertionError("--check materialized a QA plan")

    monkeypatch.setattr(qa_plan_attachments, "materialize_for_item", refuse)

    assert _run("--check", "--json", *READY) == 1


def test_a_route_refusal_is_a_blocker_and_skips_the_verification_question(
    merge,  # noqa: F811
    monkeypatch,
    capsys,
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
    merge,  # noqa: F811
    monkeypatch,
    capsys,
    queue_reads,
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


@pytest.fixture
def queue_reads(monkeypatch):
    """Run the real admission logic over read-only in-process inputs."""
    candidate, predecessor = "ITEM-51", "ITEM-50"
    shapes = {candidate: {}, predecessor: {}}
    monkeypatch.setattr(
        queue_gates,
        "get_structured_dispatch",
        lambda: SimpleNamespace(call_dispatcher=dispatch_for(shapes)),
    )
    monkeypatch.setattr(
        queue_gates,
        "read_queue_members",
        lambda *_a, **_k: ([QueueMember(pr_num="9", head_ref=predecessor)], None),
    )
    monkeypatch.setattr(
        queue_gates, "list_branch_pull_requests", lambda *_a, **_k: BranchListing()
    )
    return shapes


def _queue_ready(merge, monkeypatch):  # noqa: F811
    _ready(merge)
    monkeypatch.setattr(
        readiness_gate,
        "route_admission",
        lambda **_k: RouteAdmission(declares_queue=True),
    )


def test_check_refuses_a_queued_serial_predecessor(
    merge, monkeypatch, queue_reads, capsys  # noqa: F811
):
    _queue_ready(merge, monkeypatch)
    queue_reads["ITEM-51"]["dependencies"] = [
        {
            "direction": "depends-on",
            "other_item": "ITEM-50",
            "gate_point": "integration",
        }
    ]

    assert _run("--check", "--json", *READY) == 1

    [blocker] = json.loads(capsys.readouterr().out)["blockers"]
    assert blocker["gate"] == "queue admission"
    assert "serial-ordering" in blocker["reason"]
    assert "ITEM-50" in blocker["reason"]
    assert merge["landed"] == 0


def test_check_refuses_unchanged_failed_train(merge, monkeypatch, queue_reads, capsys):  # noqa: F811
    from yoke_core.domain import merge_queue_failed_train as failed
    from yoke_core.domain.merge_github_train_run import TrainRun

    _queue_ready(merge, monkeypatch)
    monkeypatch.setattr(
        queue_gates,
        "list_branch_pull_requests",
        lambda *_a, **_k: BranchListing(rows=({"number": 42},)),
    )
    monkeypatch.setattr(
        queue_gates,
        "read_pr_landing_state",
        lambda *_a: (
            PrLandingState(merged=False, closed=False, auto_merge_active=False),
            None,
        ),
    )
    monkeypatch.setattr(
        queue_gates,
        "read_train_run",
        lambda *_a: (
            TrainRun(
                conclusion="failure", head_sha="combined", url="https://runs/failed"
            ),
            "",
        ),
    )
    monkeypatch.setattr(failed, "_commit_parents", lambda *_a: ["base", "head"])
    monkeypatch.setattr(failed, "_current_base_sha", lambda *_a: "base")
    report = readiness_gate.LandingReadiness(
        "ITEM-51", "ITEM-51", target="main", repo_root=Path("/repo")
    )

    readiness_gate._route_gates(report, merge["item"], SimpleNamespace(), "head")

    [blocker] = report.blockers
    assert blocker.gate == "failed train"
    assert "failed-train-unchanged" in blocker.reason
    assert "https://runs/failed" in blocker.reason


@pytest.mark.parametrize("source", ["queue", "pull request", "failed train"])
def test_check_defers_unreadable_queue_inputs(
    merge, monkeypatch, queue_reads, capsys, source  # noqa: F811
):
    _queue_ready(merge, monkeypatch)
    if source == "queue":
        monkeypatch.setattr(
            queue_gates,
            "read_queue_members",
            lambda *_a, **_k: (None, "queue read failed"),
        )
    elif source == "pull request":
        monkeypatch.setattr(
            queue_gates,
            "list_branch_pull_requests",
            lambda *_a, **_k: BranchListing(error="pull request read failed"),
        )

    else:
        monkeypatch.setattr(queue_gates, "list_branch_pull_requests", lambda *_a, **_k: BranchListing(rows=({"number": 42},)))
        monkeypatch.setattr(queue_gates, "read_pr_landing_state", lambda *_a: (None, None))
        failure = TrainRunLookupFailure("failed train read failed", "", retryable=True)
        monkeypatch.setattr(queue_gates, "read_train_run", lambda *_a: (None, failure))

    assert _run("--check", "--json", *READY) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["blockers"] == []
    assert any(f"{source} read failed" in note for note in report["merge_will"])
    if source == "failed train":
        assert any("train lookup unavailable for pull request 42" in note for note in report["merge_will"])
        assert not any("recheck failed train" in note for note in report["merge_will"])


def test_check_on_never_queued_pr_says_nothing_about_a_train(merge, monkeypatch, queue_reads, capsys):  # noqa: F811
    _queue_ready(merge, monkeypatch)
    absent = TrainRunLookupFailure("no merge_group workflow run identified", "operator decision", retryable=False, no_run_found=True)
    monkeypatch.setattr(queue_gates, "list_branch_pull_requests", lambda *_a, **_k: BranchListing(rows=({"number": 42, "state": "open"},)))
    monkeypatch.setattr(queue_gates, "read_pr_landing_state", lambda *_a: (PrLandingState(merged=False, closed=False, auto_merge_active=False), None))
    monkeypatch.setattr(queue_gates, "read_train_run", lambda *_a: (None, absent))
    assert _run("--check", "--json", *READY) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["blockers"] == []
    assert not any("train" in note or "merge_group" in note for note in report["merge_will"])


def test_check_without_pr_skips_failed_train_gate(merge, monkeypatch, queue_reads):  # noqa: F811
    _queue_ready(merge, monkeypatch)
    monkeypatch.setattr(
        queue_gates,
        "unchanged_failed_train_refusal",
        lambda *_a, **_k: pytest.fail("failed-train gate without PR"),
    )

    assert _run("--check", *READY) == 0


@pytest.mark.parametrize("merged,armed", [(True, False), (False, True)])
def test_check_skips_replay_for_landing_already_in_flight(
    merge, monkeypatch, queue_reads, merged, armed  # noqa: F811
):
    _queue_ready(merge, monkeypatch)
    monkeypatch.setattr(queue_gates, "list_branch_pull_requests", lambda *_a, **_k: BranchListing(rows=({"number": 42},)))
    monkeypatch.setattr(queue_gates, "read_pr_landing_state", lambda *_a: (PrLandingState(merged=merged, closed=merged, auto_merge_active=armed), None))
    monkeypatch.setattr(queue_gates, "read_train_run", lambda *_a: pytest.fail("replay gate for an armed or merged PR"))
    assert _run("--check", *READY) == 0
