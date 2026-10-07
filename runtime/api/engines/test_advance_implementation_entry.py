"""Tests for the advance implementation-entry orchestrator."""

from __future__ import annotations

import io
import json
from typing import Any, Dict, List

import pytest

from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)
from yoke_core.engines import advance_implementation_entry as orch


_FIXTURE_ITEM_REF = f"YOK-{42}"


def _item(item_id=42, status="refined-idea", type_="issue", title="t", project="yoke"):
    return {
        "public_ref": f"YOK-{item_id}",
        "type": type_,
        "status": status,
        "title": title,
        "project": project,
    }


class _WtStub:
    """Stand-in for WorktreePreflightOutcome."""

    def __init__(
        self,
        *,
        ok=True,
        branch=_FIXTURE_ITEM_REF,
        worktree_path="/tmp/yok-42",
        actions=None,
        block_kind="",
        narrative="",
        notes=None,
    ):
        self.ok, self.branch = ok, branch
        self.worktree_path = worktree_path
        self.actions_taken = list(actions or ["worktree:created"])
        self.block_kind, self.narrative = block_kind, narrative
        self.notes = list(notes or [])


def _ok_response():
    return FunctionCallResponse(
        success=True,
        function="lifecycle.transition.execute",
        version="v1",
        result={"from_status": "refined-idea", "to_status": "implementing"},
    )


def _err_response():
    return FunctionCallResponse(
        success=False,
        function="lifecycle.transition.execute",
        version="v1",
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
        return {c["context"]["phase"]: c["context"]["outcome"] for c in self.calls}


@pytest.fixture
def emits(monkeypatch):
    cap = _CaptureEmits()
    monkeypatch.setattr(
        "yoke_core.engines.advance_implementation_entry.emit_event",
        cap,
    )
    return cap


@pytest.fixture(autouse=True)
def ambient_session(monkeypatch):
    monkeypatch.setenv("YOKE_SESSION_ID", "s1")


@pytest.fixture
def gates_pass(monkeypatch):
    monkeypatch.setattr(orch, "_run_preflight_gates", lambda _id, force: (True, ""))


@pytest.fixture
def env_skipped(monkeypatch):
    def _stub(item, sid, *, branch="", repo_root=""):
        return "skipped:no-capability", {"project": item.get("project")}

    monkeypatch.setattr(orch, "_run_environment_phase", _stub)
    # When the environment phase is stubbed its repo_root argument is
    # unused; stub the resolver too so its transport-aware projects.get
    # relay does not add an incidental dispatch to focused dispatch-capture
    # assertions.
    monkeypatch.setattr(orch, "_resolve_env_repo_root", lambda *_a, **_k: "")


def _patch_run_preflight(monkeypatch, stub=None, capture=None):
    stub = stub or _WtStub()

    def fake(**kwargs):
        if capture is not None:
            capture.update(kwargs)
        return stub

    monkeypatch.setattr(
        "yoke_core.domain.worktree_preflight.run_preflight",
        fake,
    )


def _patch_dispatch(monkeypatch, response=None, calls=None):
    response = response if response is not None else _ok_response()

    def fake(req):
        if calls is not None:
            calls.append(
                {
                    "function": req.function,
                    "actor_id": req.actor.actor_id,
                    "target_status": req.payload.get("target_status"),
                    "source_status": req.payload.get("source_status"),
                }
            )
        return response

    monkeypatch.setattr(
        "yoke_core.domain.yoke_function_dispatch.dispatch",
        fake,
    )


def test_run_happy_path_flips_status_in_one_call(
    monkeypatch,
    emits,
    env_skipped,
    gates_pass,
):
    """Status flip lands in the same invocation as worktree."""
    monkeypatch.setattr(orch, "_read_item", lambda _id: _item(item_id=99))
    _patch_run_preflight(
        monkeypatch,
        stub=_WtStub(
            branch="YOK-99",
            worktree_path="/tmp/yok-99",
            actions=[
                "work-claim:acquired",
                "path-claim:no-op",
                "upstream:fast_forwarded",
                "worktree:created",
            ],
            notes=["upstream freshness: trunk fast-forwarded 2 commit(s)"],
        ),
    )
    dispatch_calls: List[Dict[str, Any]] = []
    _patch_dispatch(monkeypatch, calls=dispatch_calls)
    out = io.StringIO()
    assert orch.run("YOK-99", session_id="s1", out=out) == 0
    summary = json.loads(out.getvalue())
    assert summary["pre_status"] == "refined-idea"
    assert summary["post_status"] == "implementing"
    assert summary["worktree_path"] == "/tmp/yok-99"
    # The preflight's advisories — upstream freshness among them — are only
    # visible to an operator if the orchestrator carries them out.
    assert summary["notes"] == ["upstream freshness: trunk fast-forwarded 2 commit(s)"]
    assert emits.phases() == ["preflight", "worktree", "environment", "finalize"]
    outcomes = emits.outcomes()
    assert outcomes["preflight"] == "completed"
    assert outcomes["worktree"] == "completed"
    assert outcomes["finalize"] == "completed"
    assert dispatch_calls == [
        {
            "function": "lifecycle.transition.execute",
            "actor_id": None,
            "target_status": "implementing",
            "source_status": "refined-idea",
        }
    ]


def test_run_preflight_failure_stops_before_worktree(monkeypatch, emits):
    """No worktree event past the failed gate phase."""
    monkeypatch.setattr(orch, "_read_item", lambda _id: _item())
    monkeypatch.setattr(
        orch, "_run_preflight_gates", lambda _id, force: (False, "missing ACs")
    )
    counter = {"n": 0}

    def fake(**_):
        counter["n"] += 1
        return _WtStub()

    monkeypatch.setattr("yoke_core.domain.worktree_preflight.run_preflight", fake)
    assert orch.run(_FIXTURE_ITEM_REF, session_id="s1", out=io.StringIO()) == 1
    assert counter["n"] == 0
    assert emits.phases() == ["preflight"]
    assert emits.outcomes()["preflight"] == "blocked"


def test_run_worktree_create_failure_releases_claim(
    monkeypatch,
    emits,
    gates_pass,
):
    """Worktree-create-failed releases the claim with phase reason."""
    monkeypatch.setattr(orch, "_read_item", lambda _id: _item())
    _patch_run_preflight(
        monkeypatch,
        stub=_WtStub(
            ok=False,
            block_kind="worktree-create-failed",
            narrative="git worktree add failed",
        ),
    )
    release_calls: List[Dict[str, Any]] = []
    monkeypatch.setattr(
        orch,
        "_release_claim",
        lambda item_id, sid, reason: release_calls.append(
            {"item": item_id, "reason": reason, "session": sid}
        ),
    )
    assert orch.run(_FIXTURE_ITEM_REF, session_id="s1", out=io.StringIO()) == 1
    assert release_calls == [
        {
            "item": _FIXTURE_ITEM_REF,
            "reason": orch.RELEASE_WORKTREE_CREATE_FAILED,
            "session": "s1",
        }
    ]
    assert emits.phases() == ["preflight", "worktree"]
    assert emits.outcomes()["worktree"].startswith("blocked:")


def test_run_finalize_failure_keeps_claim(
    monkeypatch,
    emits,
    gates_pass,
    env_skipped,
):
    """Finalize refusal preserves the claim for idempotent re-entry."""
    monkeypatch.setattr(orch, "_read_item", lambda _id: _item())
    _patch_run_preflight(monkeypatch)
    _patch_dispatch(monkeypatch, response=_err_response())
    release_calls: List[Any] = []
    monkeypatch.setattr(
        orch, "_release_claim", lambda *a, **kw: release_calls.append((a, kw))
    )
    assert orch.run(_FIXTURE_ITEM_REF, session_id="s1", out=io.StringIO()) == 1
    assert release_calls == []
    assert emits.outcomes()["finalize"].startswith("blocked:")


def test_run_reentry_skips_status_flip(
    monkeypatch,
    emits,
    gates_pass,
    env_skipped,
):
    """Rerun against implementing reuses claim/worktree, skips flip."""
    monkeypatch.setattr(orch, "_read_item", lambda _id: _item(status="implementing"))
    _patch_run_preflight(
        monkeypatch,
        stub=_WtStub(
            actions=["work-claim:already-owned", "path-claim:no-op", "worktree:reused"]
        ),
    )
    dispatch_calls: List[Any] = []

    def fake(req):
        dispatch_calls.append(req)
        return _ok_response()

    monkeypatch.setattr("yoke_core.domain.yoke_function_dispatch.dispatch", fake)
    out = io.StringIO()
    assert orch.run(_FIXTURE_ITEM_REF, session_id="s1", out=out) == 0
    summary = json.loads(out.getvalue())
    assert summary["reentry"] is True
    assert summary["post_status"] == "implementing"
    assert dispatch_calls == []
    assert emits.outcomes()["finalize"] == "skipped:already-past-refined-idea"


def test_run_no_worktree_still_flips_status(
    monkeypatch,
    emits,
    gates_pass,
    env_skipped,
):
    """--no-worktree honored — status flips but worktree skipped."""
    monkeypatch.setattr(orch, "_read_item", lambda _id: _item())
    captured: Dict[str, Any] = {}
    _patch_run_preflight(
        monkeypatch,
        stub=_WtStub(
            worktree_path="", branch=_FIXTURE_ITEM_REF, actions=["worktree:skipped"]
        ),
        capture=captured,
    )
    _patch_dispatch(monkeypatch)
    assert (
        orch.run(
            _FIXTURE_ITEM_REF, no_worktree=True, session_id="s1", out=io.StringIO()
        )
        == 0
    )
    assert captured["no_worktree"] is True


def test_run_missing_item_returns_bad_input(monkeypatch, emits):
    monkeypatch.setattr(orch, "_read_item", lambda _id: None)
    assert orch.run("YOK-9999", session_id="s1", out=io.StringIO()) == 2
    assert emits.calls == []
