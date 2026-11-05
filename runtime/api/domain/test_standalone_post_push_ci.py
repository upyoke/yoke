"""Push CI identity, pagination and descendant cancellation recovery."""

from types import SimpleNamespace

import pytest

from yoke_core.domain import standalone_post_push_ci as ci
from yoke_core.domain import standalone_item_merge_post_push as post_push
from yoke_core.domain.standalone_item_merge_publication_message import (
    publication_narration,
    refusal_message,
)
from runtime.api.domain.standalone_item_merge_post_push_test_support import Clock

OLD = "a" * 40
NEW = "b" * 40


def _workflow(sha=OLD, event="push", conclusion="success", suite=1, **extra):
    return {
        "id": suite,
        "check_suite_id": suite,
        "workflow_id": 17,
        "name": "CI",
        "event": event,
        "head_sha": sha,
        "head_branch": "main",
        "status": "completed" if conclusion else "in_progress",
        "conclusion": conclusion,
        "html_url": f"https://runs/{suite}",
        **extra,
    }


def _check(name="suite", conclusion="success"):
    return {
        "name": name,
        "status": "completed" if conclusion else "in_progress",
        "conclusion": conclusion,
        "html_url": f"https://checks/{name}",
    }


def _wire(monkeypatch, respond):
    seen = []
    monkeypatch.setattr(
        ci,
        "resolve_auth",
        lambda *_a, **_k: SimpleNamespace(repo="owner/repo", token="token"),
    )

    def request(req, **_kwargs):
        seen.append(req)
        return SimpleNamespace(body=respond(req))

    monkeypatch.setattr(ci, "request_with_retry", request)
    return seen


def _payload(key, rows):
    return {"total_count": len(rows), key: rows}


def test_passing_push_ignores_pending_dispatched_checks(monkeypatch):
    def respond(req):
        if req.path.endswith("actions/runs"):
            assert req.query["event"] == "push" and req.query["head_sha"] == OLD
            return _payload(
                "workflow_runs",
                [
                    _workflow(),
                    _workflow(event="workflow_dispatch", suite=2, conclusion=""),
                ],
            )
        assert req.path.endswith("check-suites/1/check-runs")
        return _payload("check_runs", [_check()])

    seen = _wire(monkeypatch, respond)
    clock = Clock()
    verdict = post_push.await_post_push_checks(
        "example", OLD, "installation", sleep=clock.sleep, monotonic=clock.monotonic
    )
    assert verdict.kind == "passed" and not clock.sleeps
    assert verdict.runs[-1].url == "https://checks/suite"
    assert len(seen) == 2
    assert OLD in verdict.evidence[0]["name"]


@pytest.mark.parametrize("conclusion", ["failure", ""])
def test_check_suite_pagination_retains_page_two(monkeypatch, conclusion):
    monkeypatch.setattr(ci, "PER_PAGE", 1)

    def respond(req):
        if req.path.endswith("actions/runs"):
            return _payload("workflow_runs", [_workflow()])
        page = req.query["page"]
        return {
            "total_count": 2,
            "check_runs": [
                _check(
                    "one" if page == "1" else "two",
                    "success" if page == "1" else conclusion,
                )
            ],
        }

    _wire(monkeypatch, respond)
    runs, error = post_push.read_check_runs("example", OLD, "installation")
    assert not error and runs[-1].conclusion == conclusion
    assert post_push._terminal_kind(runs) == ("failed" if conclusion else "pending")


def test_workflow_pagination_keeps_all_push_suites(monkeypatch):
    monkeypatch.setattr(ci, "PER_PAGE", 1)

    def respond(req):
        if req.path.endswith("actions/runs"):
            suite = int(req.query["page"])
            return {"total_count": 2, "workflow_runs": [_workflow(suite=suite)]}
        return _payload("check_runs", [_check(req.path)])

    _wire(monkeypatch, respond)
    runs, error = post_push.read_check_runs("example", OLD, "installation")
    assert not error and len(runs) == 4


@pytest.mark.parametrize(
    "payload", [{"workflow_runs": []}, {"total_count": 2, "workflow_runs": []}]
)
def test_incomplete_pagination_refuses_with_recovery(monkeypatch, payload):
    _wire(monkeypatch, lambda _req: payload)
    runs, error = post_push.read_check_runs("example", OLD, "installation")
    assert runs is None
    assert "pagination" in error and "retry merge close-out" in error


def test_empty_push_list_is_complete(monkeypatch):
    _wire(monkeypatch, lambda _req: _payload("workflow_runs", []))
    assert post_push.read_check_runs("example", OLD, "installation") == ((), "")


def test_queued_jobless_workflow_remains_pending(monkeypatch):
    def respond(req):
        return (
            _payload("workflow_runs", [_workflow(conclusion="", status="queued")])
            if req.path.endswith("actions/runs")
            else _payload("check_runs", [])
        )

    _wire(monkeypatch, respond)
    runs, error = post_push.read_check_runs("example", OLD, "installation")
    assert not error and post_push._terminal_kind(runs) == "pending"


def _supersession(monkeypatch, *, status="ahead", newer=None):
    def respond(req):
        if req.path.endswith("actions/runs"):
            rows = (
                [_workflow(conclusion="cancelled")]
                if req.query["head_sha"] == OLD
                else ([_workflow(sha=NEW)] if newer is None else newer)
            )
            return _payload("workflow_runs", rows)
        if "/commits/" in req.path:
            return {"sha": NEW}
        assert req.path.endswith(f"compare/{OLD}...{NEW}")
        return {"status": status}

    return _wire(monkeypatch, respond)


def test_supersession_requires_containment_and_same_workflow(monkeypatch):
    _supersession(monkeypatch)
    assert ci.superseding_push_sha("example", OLD, "installation") == (NEW, "")


@pytest.mark.parametrize("status", ["diverged", "behind", "identical"])
def test_unrelated_new_head_never_supplies_ci_proof(monkeypatch, status):
    _supersession(monkeypatch, status=status)
    assert ci.superseding_push_sha("example", OLD, "installation") == ("", "")


@pytest.mark.parametrize(
    "newer",
    [
        [],
        [_workflow(sha=NEW, workflow_id=99)],
        [_workflow(sha=NEW, event="workflow_dispatch")],
        [_workflow(sha=NEW, head_branch="other")],
    ],
)
def test_missing_replacement_push_cannot_turn_cancellation_green(monkeypatch, newer):
    _supersession(monkeypatch, newer=newer)
    assert ci.superseding_push_sha("example", OLD, "installation") == ("", "")


def _wait(monkeypatch, read, supersede, timeout=900):
    clock = Clock()
    monkeypatch.setattr(
        post_push,
        "_setting_seconds",
        lambda key: 90 if key == post_push.DISCOVERY_TIMEOUT_KEY else timeout,
    )
    verdict = post_push.await_post_push_checks(
        "example",
        OLD,
        "installation",
        read=read,
        supersede=supersede,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    return verdict, clock


def test_cancelled_push_reports_and_follows_newer_push(monkeypatch, capsys):
    seen = []

    def read(_project, sha, _authority):
        seen.append(sha)
        return (
            post_push.CheckRun(
                "push", "completed", "cancelled" if sha == OLD else "success"
            ),
        ), ""

    verdict, clock = _wait(monkeypatch, read, lambda *_a: (NEW, ""))
    assert verdict.kind == "passed" and seen == [OLD, NEW]
    assert not clock.sleeps
    assert f"superseded by {NEW}" in capsys.readouterr().out
    assert f"superseded by {NEW}" in publication_narration(
        pushed=True, push_warning="", verdict=verdict
    )


def test_superseding_pending_push_keeps_original_deadline(monkeypatch):
    count = 0

    def read(_project, sha, _authority):
        nonlocal count
        count += 1
        conclusion = "cancelled" if sha == OLD and count > 1 else ""
        return (
            post_push.CheckRun(
                "push", "completed" if conclusion else "in_progress", conclusion
            ),
        ), ""

    verdict, clock = _wait(monkeypatch, read, lambda *_a: (NEW, ""), timeout=150)
    assert verdict.kind == "timed_out" and clock.now == 150
    assert f"superseded by {NEW}" in refusal_message(
        verdict, merge_sha=OLD, resume_command="yoke merge item EX-1"
    )


def test_cancelled_without_descendant_is_failure_not_timeout(monkeypatch):
    verdict, clock = _wait(
        monkeypatch,
        lambda *_a: ((post_push.CheckRun("push", "completed", "cancelled"),), ""),
        lambda *_a: ("", ""),
    )
    assert verdict.kind == "failed" and not clock.sleeps


def test_red_check_is_not_overridden_by_a_cancelled_workflow(monkeypatch):
    verdict, clock = _wait(
        monkeypatch,
        lambda *_a: (
            (
                post_push.CheckRun("red", "completed", "failure"),
                post_push.CheckRun("push", "completed", "cancelled"),
            ),
            "",
        ),
        lambda *_a: pytest.fail("must not hide red CI"),
    )
    assert verdict.kind == "failed" and not clock.sleeps


def test_unreadable_supersession_preserves_reason(monkeypatch):
    verdict, _ = _wait(
        monkeypatch,
        lambda *_a: ((post_push.CheckRun("push", "completed", "cancelled"),), ""),
        lambda *_a: ("", "post_push_ci_unreadable: provider refused; retry"),
    )
    assert verdict.kind == "unreadable" and "provider refused" in verdict.detail


def test_observed_checks_disappearing_cannot_pass(monkeypatch):
    readings = [((post_push.CheckRun("push", "in_progress"),), ""), ((), "")]
    verdict, _ = _wait(monkeypatch, lambda *_a: readings.pop(0), lambda *_a: ("", ""))
    assert verdict.kind == "unreadable" and "disappeared" in verdict.detail


def test_missing_workflow_identity_refuses(monkeypatch):
    _wire(monkeypatch, lambda _req: _payload("workflow_runs", [{"head_sha": OLD}]))
    runs, error = post_push.read_check_runs("example", OLD, "installation")
    assert runs is None and "omitted event" in error
