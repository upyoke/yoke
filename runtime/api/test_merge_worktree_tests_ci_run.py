"""Merge-gate CI verification: what runs the candidate, and what it records."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from runtime.api.merge_worktree_tests_ci_helpers import (
    bind_candidate_tree,
    existing_run,
    never,
    record_ci_runs,
    run_verification,
    stub_lane,
)

from yoke_core.domain import qa_case_ci_covering_run as covering_run
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.domain.verification_tree_binding import TreeIdentity
from yoke_core.engines import merge_worktree_tests_ci


def test_run_ci_verification_success_records_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    head = "b" * 40
    push_calls = []
    bind_candidate_tree(monkeypatch, tmp_path, head)
    stub_lane(
        monkeypatch,
        dispatch=lambda **kwargs: "55",
        await_result=lambda **kwargs: (0, "success"),
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_lane.push_lane",
        lambda *a, **k: push_calls.append((a, k)),
    )
    recorded = []
    monkeypatch.setattr(
        merge_worktree_tests_ci,
        "_record_ci_run",
        lambda ctx, **kwargs: recorded.append(kwargs) or 901,
    )
    monkeypatch.setattr(
        merge_worktree_tests_ci,
        "_parent",
        lambda: SimpleNamespace(_print=print),
    )

    assert run_verification(tmp_path) is None
    assert push_calls, "candidate must be pushed before dispatch"
    assert recorded and recorded[0]["verdict"] == "pass"
    payload = json.loads(recorded[0]["raw_result"])
    assert payload["verification_tree"]["head_sha"] == head
    assert "actions/runs/55" in capsys.readouterr().out


def test_run_ci_verification_red_blocks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    head = "c" * 40
    bind_candidate_tree(monkeypatch, tmp_path, head)
    stub_lane(
        monkeypatch,
        dispatch=lambda **kwargs: "66",
        await_result=lambda **kwargs: (1, "failed:failure"),
    )
    monkeypatch.setattr(
        merge_worktree_tests_ci,
        "_record_ci_run",
        lambda *a, **k: 902,
    )
    assert run_verification(tmp_path, scope="quick") == (1, "tests failed")


def test_run_ci_verification_unreachable_named_failure_no_local_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    head = "d" * 40
    bind_candidate_tree(monkeypatch, tmp_path, head)

    def boom(**kwargs):
        raise QaCaseExecutionError("dispatch unavailable")

    stub_lane(
        monkeypatch,
        dispatch=boom,
        await_result=lambda **kwargs: (0, "success"),
    )
    recorded = []
    monkeypatch.setattr(
        merge_worktree_tests_ci,
        "_record_ci_run",
        lambda *a, **k: recorded.append(k) or 903,
    )
    assert run_verification(tmp_path) == (1, "ci unreachable")
    assert recorded and recorded[0]["verdict"] == "error"


def test_run_ci_verification_head_sha_mismatch_blocks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    head = "e" * 40
    monkeypatch.setattr(
        "yoke_core.domain.verification_tree_binding.resolve_tree_identity",
        lambda _p: TreeIdentity(root=str(tmp_path), head_sha=head),
    )
    stub_lane(
        monkeypatch,
        dispatch=lambda **kwargs: "77",
        await_result=lambda **kwargs: (0, "success"),
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_lane.run_head_sha",
        lambda **kwargs: "f" * 40,
    )
    monkeypatch.setattr(
        "yoke_core.engines.merge_worktree_tree_coverage._tree_object_id",
        lambda _cwd, rev: "tree-a" if rev == "HEAD" else "tree-b",
    )
    monkeypatch.setattr(
        merge_worktree_tests_ci,
        "_record_ci_run",
        lambda *a, **k: 904,
    )
    assert run_verification(tmp_path) == (1, "ci unreachable")


def test_a_concluded_run_on_the_candidate_is_adopted_without_a_second_suite(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    """The QA gate verified this exact commit minutes ago; that verdict stands."""
    head = "1" * 40
    bind_candidate_tree(monkeypatch, tmp_path, head)
    stub_lane(
        monkeypatch,
        dispatch=never("must not dispatch over a concluded run"),
        await_result=never("must not poll a concluded run"),
        covering=existing_run(head),
    )
    recorded = record_ci_runs(monkeypatch)

    assert run_verification(tmp_path) is None

    payload = json.loads(recorded[0]["raw_result"])
    assert recorded[0]["verdict"] == "pass"
    assert payload["ci_run_source"] == covering_run.ADOPTED
    assert payload["ci_run_id"] == "88"
    assert payload["ci_conclusion"] == "success"


def test_an_adopted_red_run_reports_its_own_conclusion_not_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    """A polled failure is parsed out of poll text; an adopted one is known."""
    head = "2" * 40
    bind_candidate_tree(monkeypatch, tmp_path, head)
    stub_lane(
        monkeypatch,
        dispatch=never("must not dispatch over a concluded run"),
        await_result=never("must not poll a concluded run"),
        covering=existing_run(head, conclusion="failure"),
    )
    recorded = record_ci_runs(monkeypatch)

    assert run_verification(tmp_path) == (1, "tests failed")

    assert recorded[0]["verdict"] == "fail"
    assert json.loads(recorded[0]["raw_result"])["ci_conclusion"] == "failure"


def test_a_run_still_in_flight_on_the_candidate_is_attached_to(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    head = "3" * 40
    awaited: list[str] = []
    bind_candidate_tree(monkeypatch, tmp_path, head)
    stub_lane(
        monkeypatch,
        dispatch=never("must not dispatch beside a live run"),
        await_result=lambda **k: (awaited.append(k["run_id"]), (0, "success"))[1],
        covering=existing_run(head, status="in_progress", conclusion="", run_id="99"),
    )
    recorded = record_ci_runs(monkeypatch)

    assert run_verification(tmp_path) is None

    assert awaited == ["99"]
    assert json.loads(recorded[0]["raw_result"])["ci_run_source"] == (
        covering_run.ATTACHED
    )


def test_a_run_on_another_commit_never_answers_for_this_candidate(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    """Exactness is the safety argument: a different commit is a different tree."""
    head = "4" * 40
    bind_candidate_tree(monkeypatch, tmp_path, head)
    stub_lane(
        monkeypatch,
        dispatch=lambda **_k: "111",
        await_result=lambda **_k: (0, "success"),
        covering=existing_run("9" * 40),
    )
    recorded = record_ci_runs(monkeypatch)

    assert run_verification(tmp_path) is None

    payload = json.loads(recorded[0]["raw_result"])
    assert payload["ci_run_source"] == covering_run.DISPATCHED
    assert payload["ci_run_id"] == "111"
