"""Tests for the advance implementation-entry orchestrator."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest import mock

import pytest

from yoke_contracts.api.function_call import (
    FunctionCallResponse, FunctionError,
)
from yoke_core.engines import advance_implementation_entry as orch


def _item(item_id=42, status="refined-idea", type_="issue",
          title="t", project="yoke"):
    return {"id": item_id, "type": type_, "status": status,
            "title": title, "project": project}


class _WtStub:
    """Stand-in for WorktreePreflightOutcome."""
    def __init__(self, *, ok=True, branch="YOK-42",
                 worktree_path="/tmp/yok-42", actions=None,
                 block_kind="", narrative=""):
        self.ok, self.branch = ok, branch
        self.worktree_path = worktree_path
        self.actions_taken = list(actions or ["worktree:created"])
        self.block_kind, self.narrative = block_kind, narrative


def _ok_response():
    return FunctionCallResponse(
        success=True, function="lifecycle.transition.execute", version="v1",
        result={"from_status": "refined-idea", "to_status": "implementing"},
    )


def _err_response():
    return FunctionCallResponse(
        success=False, function="lifecycle.transition.execute", version="v1",
        error=FunctionError(code="precondition_failed", message="refused"),
    )


class _CaptureEmits:
    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, event_name, **kwargs):
        if event_name == "AdvancePhaseCompleted":
            self.calls.append({"name": event_name, **kwargs})

    def phases(self):
        return [c["context"]["phase"] for c in self.calls]

    def outcomes(self):
        return {c["context"]["phase"]: c["context"]["outcome"]
                for c in self.calls}


@pytest.fixture
def emits(monkeypatch):
    cap = _CaptureEmits()
    monkeypatch.setattr(
        "yoke_core.engines.advance_implementation_entry.emit_event", cap,
    )
    return cap


@pytest.fixture
def gates_pass(monkeypatch):
    monkeypatch.setattr(orch, "_run_preflight_gates",
                        lambda _id, force: (True, ""))


@pytest.fixture
def env_skipped(monkeypatch):
    def _stub(item, sid, *, branch="", repo_root=""):
        return "skipped:no-capability", {"project": item.get("project")}
    monkeypatch.setattr(orch, "_run_environment_phase", _stub)


def _patch_run_preflight(monkeypatch, stub=None, capture=None):
    stub = stub or _WtStub()
    def fake(**kwargs):
        if capture is not None:
            capture.update(kwargs)
        return stub
    monkeypatch.setattr(
        "yoke_core.domain.worktree_preflight.run_preflight", fake,
    )


def _patch_dispatch(monkeypatch, response=None, calls=None):
    response = response if response is not None else _ok_response()
    def fake(req):
        if calls is not None:
            calls.append({"function": req.function,
                          "actor_id": req.actor.actor_id,
                          "target_status": req.payload.get("target_status"),
                          "source_status": req.payload.get("source_status")})
        return response
    monkeypatch.setattr(
        "yoke_core.domain.yoke_function_dispatch.dispatch", fake,
    )


@pytest.mark.parametrize("raw,expected", [
    ("YOK-42", 42), ("yok-42", 42), ("0042", 42), ("42", 42),
    (" YOK-007 ", 7), (1730, 1730),
])
def test_parse_item_id_normalises(raw, expected):
    assert orch._parse_item_id(raw) == expected


def test_parse_item_id_invalid_raises():
    with pytest.raises(ValueError):
        orch._parse_item_id("not-a-number")


def test_resolve_session_id_priority(monkeypatch):
    monkeypatch.setenv("YOKE_SESSION_ID", "env-id")
    assert orch._resolve_session_id("explicit") == "explicit"
    for var in ("YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", "codex-thread")
    assert orch._resolve_session_id(None) == "codex-thread"
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    assert orch._resolve_session_id(None) == ""


def test_preflight_force_skips_all():
    ok, narrative = orch._run_preflight_gates(42, force=True)
    assert ok is True and narrative == ""


@pytest.mark.parametrize("blockers,acs,coverage_missing,want_fragment", [
    (["BLOCKED|YOK-99|implementing|t|activation|merged"], (3, 0, "t"), [],
     "Blocked by dependencies"),
    ([], (0, 0, "t"), [], "acceptance criteria"),
    ([], (3, 0, "t"), ["runtime/api/x.py"], "File Budget"),
])
def test_preflight_blocks_for_each_gate(
    blockers, acs, coverage_missing, want_fragment,
):
    class _Cov:
        is_blocked = bool(coverage_missing)
        missing_paths = coverage_missing

    with mock.patch(
        "yoke_core.domain.check_hard_blocks.evaluate_blockers",
        return_value=blockers,
    ), mock.patch(
        "yoke_core.domain.check_ac_presence.evaluate_item",
        return_value=acs,
    ), mock.patch(
        "yoke_core.domain.path_claim_spec_coverage_gate.evaluate",
        return_value=_Cov(),
    ):
        ok, narrative = orch._run_preflight_gates(42, force=False)
    assert ok is False and want_fragment in narrative


@pytest.mark.parametrize("item_in,capability,want_outcome", [
    ({}, False, "skipped:no-project"),
    ({"project": "yoke"}, False, "skipped:no-capability"),
])
def test_environment_phase_skip_branches(item_in, capability, want_outcome):
    """Capable-project provisioning is exercised end-to-end in
    test_advance_implementation_entry_cross_project; here we only assert the
    two skip branches stay on the orchestrator shim."""
    with mock.patch(
        "yoke_core.domain.projects_crud.cmd_has_capability",
        return_value=capability,
    ):
        outcome, _ctx = orch._run_environment_phase(item_in, "sess")
    assert outcome == want_outcome


def test_run_happy_path_flips_status_in_one_call(
    monkeypatch, emits, env_skipped, gates_pass,
):
    """AC-2 / AC-9: status flip lands in the same invocation as worktree."""
    monkeypatch.setattr(orch, "_read_item", lambda _id: _item(item_id=99))
    _patch_run_preflight(monkeypatch, stub=_WtStub(
        branch="YOK-99", worktree_path="/tmp/yok-99",
        actions=["work-claim:acquired", "path-claim:no-op",
                 "worktree:created"]))
    dispatch_calls: List[Dict[str, Any]] = []
    _patch_dispatch(monkeypatch, calls=dispatch_calls)
    out = io.StringIO()
    assert orch.run("YOK-99", session_id="s1", out=out) == 0
    summary = json.loads(out.getvalue())
    assert summary["pre_status"] == "refined-idea"
    assert summary["post_status"] == "implementing"
    assert summary["worktree_path"] == "/tmp/yok-99"
    assert emits.phases() == ["preflight", "worktree", "environment",
                              "finalize"]
    outcomes = emits.outcomes()
    assert outcomes["preflight"] == "completed"
    assert outcomes["worktree"] == "completed"
    assert outcomes["finalize"] == "completed"
    assert dispatch_calls == [{
        "function": "lifecycle.transition.execute",
        "actor_id": None, "target_status": "implementing",
        "source_status": "refined-idea",
    }]


def test_run_preflight_failure_stops_before_worktree(monkeypatch, emits):
    """AC-4: no worktree event past the failed gate phase."""
    monkeypatch.setattr(orch, "_read_item", lambda _id: _item())
    monkeypatch.setattr(orch, "_run_preflight_gates",
                        lambda _id, force: (False, "missing ACs"))
    counter = {"n": 0}
    def fake(**_):
        counter["n"] += 1
        return _WtStub()
    monkeypatch.setattr(
        "yoke_core.domain.worktree_preflight.run_preflight", fake)
    assert orch.run("YOK-42", session_id="s1", out=io.StringIO()) == 1
    assert counter["n"] == 0
    assert emits.phases() == ["preflight"]
    assert emits.outcomes()["preflight"] == "blocked"


def test_run_worktree_create_failure_releases_claim(
    monkeypatch, emits, gates_pass,
):
    """AC-5: worktree-create-failed releases the claim with phase reason."""
    monkeypatch.setattr(orch, "_read_item", lambda _id: _item())
    _patch_run_preflight(monkeypatch, stub=_WtStub(
        ok=False, block_kind="worktree-create-failed",
        narrative="git worktree add failed"))
    release_calls: List[Dict[str, Any]] = []
    monkeypatch.setattr(orch, "_release_claim",
                        lambda item_id, sid, reason: release_calls.append(
                            {"item": item_id, "reason": reason, "session": sid}))
    assert orch.run("YOK-42", session_id="s1", out=io.StringIO()) == 1
    assert release_calls == [{
        "item": 42, "reason": orch.RELEASE_WORKTREE_CREATE_FAILED,
        "session": "s1",
    }]
    assert emits.phases() == ["preflight", "worktree"]
    assert emits.outcomes()["worktree"].startswith("blocked:")


def test_run_finalize_failure_keeps_claim(
    monkeypatch, emits, gates_pass, env_skipped,
):
    """Finalize refusal preserves the claim for idempotent re-entry."""
    monkeypatch.setattr(orch, "_read_item", lambda _id: _item())
    _patch_run_preflight(monkeypatch)
    _patch_dispatch(monkeypatch, response=_err_response())
    release_calls: List[Any] = []
    monkeypatch.setattr(orch, "_release_claim",
                        lambda *a, **kw: release_calls.append((a, kw)))
    assert orch.run("YOK-42", session_id="s1", out=io.StringIO()) == 1
    assert release_calls == []
    assert emits.outcomes()["finalize"].startswith("blocked:")


def test_run_reentry_skips_status_flip(
    monkeypatch, emits, gates_pass, env_skipped,
):
    """AC-6: rerun against implementing reuses claim/worktree, skips flip."""
    monkeypatch.setattr(orch, "_read_item",
                        lambda _id: _item(status="implementing"))
    _patch_run_preflight(monkeypatch, stub=_WtStub(
        actions=["work-claim:already-owned", "path-claim:no-op",
                 "worktree:reused"]))
    dispatch_calls: List[Any] = []
    def fake(req):
        dispatch_calls.append(req)
        return _ok_response()
    monkeypatch.setattr(
        "yoke_core.domain.yoke_function_dispatch.dispatch", fake)
    out = io.StringIO()
    assert orch.run("YOK-42", session_id="s1", out=out) == 0
    summary = json.loads(out.getvalue())
    assert summary["reentry"] is True
    assert summary["post_status"] == "implementing"
    assert dispatch_calls == []
    assert emits.outcomes()["finalize"] == "skipped:already-past-refined-idea"


def test_run_no_worktree_still_flips_status(
    monkeypatch, emits, gates_pass, env_skipped,
):
    """AC-8: --no-worktree honored — status flips but worktree skipped."""
    monkeypatch.setattr(orch, "_read_item", lambda _id: _item())
    captured: Dict[str, Any] = {}
    _patch_run_preflight(monkeypatch, stub=_WtStub(
        worktree_path="", branch="YOK-42", actions=["worktree:skipped"]),
        capture=captured)
    _patch_dispatch(monkeypatch)
    assert orch.run("YOK-42", no_worktree=True, session_id="s1",
                    out=io.StringIO()) == 0
    assert captured["no_worktree"] is True


def test_run_missing_item_returns_bad_input(monkeypatch, emits):
    monkeypatch.setattr(orch, "_read_item", lambda _id: None)
    assert orch.run("YOK-9999", session_id="s1", out=io.StringIO()) == 2
    assert emits.calls == []


def test_record_phase_fails_closed_when_event_not_written(monkeypatch):
    monkeypatch.setattr(orch, "emit_event",
                        lambda *a, **k: SimpleNamespace(ok=False, reason="x"))
    summary = {"phases": []}
    with pytest.raises(RuntimeError, match="AdvancePhaseCompleted"):
        orch._record_phase(summary, item_id=42, phase="preflight",
                           outcome="completed", duration_ms=1,
                           session_id="s1")
    assert summary["phases"] == []


def test_main_delegates_to_run(monkeypatch):
    calls: Dict[str, Any] = {}
    def fake_run(item_id, **kwargs):
        calls["item_id"] = item_id
        calls.update(kwargs)
        return 0
    monkeypatch.setattr(orch, "run", fake_run)
    assert orch.main(["--item", "YOK-42", "--no-worktree", "--force",
                      "--qa-bypass", "--session-id", "manual-id"]) == 0
    assert calls["item_id"] == "YOK-42"
    assert calls["no_worktree"] and calls["force"] and calls["qa_bypass"]
    assert calls["session_id"] == "manual-id"


def test_main_surfaces_unexpected_exception(monkeypatch, capsys):
    monkeypatch.setattr(
        orch, "run", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert orch.main(["--item", "YOK-1"]) == 1
    assert "orchestrator crashed" in capsys.readouterr().err
