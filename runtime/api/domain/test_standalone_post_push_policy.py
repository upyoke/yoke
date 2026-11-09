"""Declared CI gates close-out; undeclared push runs remain receipt evidence."""

import pytest

from yoke_core.domain import standalone_item_merge_post_push as post_push
from yoke_core.domain import standalone_post_push_policy as policy
from runtime.api.domain.test_standalone_item_merge_post_push_close_out import (
    _complete,
    _wire_complete,
)


@pytest.mark.parametrize("declaration", ["ci.yml", "", None])
def test_failed_push_uses_declared_ci_policy(monkeypatch, declaration):
    run = post_push.CheckRun(
        "suite", "completed", "failure", "https://runs/failed"
    )
    recorded = _wire_complete(
        monkeypatch, post_push.PostPushVerdict("failed", runs=(run,))
    )
    monkeypatch.setattr(post_push, "github_merge_enabled", lambda _p: True)

    def read_declaration(project):
        assert project == "yoke"
        if declaration is None:
            raise RuntimeError("capability read unavailable")
        return declaration

    monkeypatch.setattr(policy, "project_ci_workflow_file", read_declaration)
    monkeypatch.setattr(
        post_push, "read_check_runs", lambda *_a: ((run,), "")
    )
    if declaration == "":
        monkeypatch.setattr(
            post_push, "await_post_push_checks",
            lambda *_a: pytest.fail("undeclared CI must not wait for a gate"),
        )

    outcome = _complete()

    assert outcome.ok is (declaration == "")
    assert recorded[-1].check_runs == (run.evidence(),)
    if declaration == "":
        assert "do not gate close-out" in outcome.output
        assert any("https://runs/failed" in note for note in outcome.warnings)
    else:
        assert "https://runs/failed" in outcome.error
    if declaration is None:
        assert any("retaining the post-push CI gate" in note for note in outcome.warnings)


@pytest.mark.parametrize("kind", ["timed_out", "unreadable", "passed", "no_checks"])
def test_unreadable_declaration_preserves_existing_verdict(monkeypatch, kind):
    verdict = post_push.PostPushVerdict(kind, detail="provider diagnosis")
    monkeypatch.setattr(
        policy, "project_ci_workflow_file",
        lambda _p: (_ for _ in ()).throw(RuntimeError("read failed")),
    )
    monkeypatch.setattr(post_push, "await_post_push_checks", lambda *_a: verdict)
    notes = []
    observed, required = policy.observe_post_push_checks("project", "sha", "auth", notes)
    assert observed is verdict
    assert required
    assert notes and "read failed" in notes[0]


def test_undeclared_unreadable_checks_warn_without_gate(monkeypatch):
    monkeypatch.setattr(policy, "project_ci_workflow_file", lambda _p: "")
    monkeypatch.setattr(
        post_push, "read_check_runs", lambda *_a: (None, "Actions read denied")
    )
    notes = []
    observed, required = policy.observe_post_push_checks("project", "sha", "auth", notes)
    assert not required
    assert observed.evidence == ()
    assert "Actions read denied" in notes[0]
