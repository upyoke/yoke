"""Cross-project regression coverage for the orchestrator.

Project routed into ``run_preflight``; structured error envelope (no
empty worktree_path/branch); capable-project env provisioning chain;
dirty-main evaluated against target repo
(orchestrator boundary; per-repo eval lives in ``worktree_preflight``).
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from yoke_core.engines import advance_implementation_entry as orch
from yoke_core.domain import worktree_preflight
from yoke_contracts.api.function_call import (
    FunctionCallResponse, FunctionError,
)


def _item(item_id=42, status="refined-idea", type_="issue",
          title="t", project="externalwebapp"):
    return {"id": item_id, "type": type_, "status": status,
            "title": title, "project": project}


class _WtStub:
    """Stand-in for WorktreePreflightOutcome."""
    def __init__(self, *, ok=True, branch="YOK-42",
                 worktree_path="/Users/dev/externalwebapp/.worktrees/YOK-42",
                 actions=None, block_kind="", narrative=""):
        self.ok, self.branch = ok, branch
        self.worktree_path = worktree_path
        self.actions_taken = list(actions or ["worktree:created"])
        self.block_kind, self.narrative = block_kind, narrative


def _ok_response():
    return FunctionCallResponse(
        success=True, function="lifecycle.transition.execute", version="v1",
        result={"from_status": "refined-idea", "to_status": "implementing"},
    )


def _err_response(code="dirty_tracked", msg="dirty tree"):
    return FunctionCallResponse(
        success=False, function="lifecycle.transition.execute", version="v1",
        error=FunctionError(code=code, message=msg),
    )


@pytest.fixture(autouse=True)
def ambient_session(monkeypatch):
    monkeypatch.setenv("YOKE_SESSION_ID", "s1")
    monkeypatch.setattr(orch, "_parse_item_argument", lambda _raw: 42)


@pytest.fixture
def silence_emits(monkeypatch):
    monkeypatch.setattr(orch, "emit_event", lambda *a, **kw: None)


@pytest.fixture
def gates_pass(monkeypatch):
    monkeypatch.setattr(orch, "_run_preflight_gates",
                        lambda _id, force: (True, ""))


@pytest.fixture
def env_noop(monkeypatch):
    """Bypass the env module so cross-project tests focus on routing."""
    def _stub(item, sid, *, branch="", repo_root=""):
        return "skipped:no-capability", {"project": item.get("project")}
    monkeypatch.setattr(orch, "_run_environment_phase", _stub)


def _patch_dispatch(monkeypatch, response=None):
    response = response if response is not None else _ok_response()
    monkeypatch.setattr(
        "yoke_core.domain.yoke_function_dispatch.dispatch",
        lambda req: response,
    )


# ---------------------------------------------------------------------------
# Project routed into worktree_preflight
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("project_in,want_project", [
    ("externalwebapp", "externalwebapp"),
    ("yoke", "yoke"),
])
def test_orchestrator_forwards_item_project_to_run_preflight(
    monkeypatch, silence_emits, gates_pass, env_noop,
    project_in, want_project,
):
    """The orchestrator MUST pass ``item.project`` to ``run_preflight`` so
    cross-project items resolve the target checkout from the machine mapping
    instead of falling through to Yoke cwd. Yoke (control plane) routes
    through the same project identity lookup."""
    monkeypatch.setattr(orch, "_read_item",
                        lambda _id: _item(project=project_in))
    captured: Dict[str, Any] = {}

    def fake_run_preflight(**kwargs):
        captured.update(kwargs)
        return _WtStub()

    monkeypatch.setattr(
        "yoke_core.domain.worktree_preflight.run_preflight",
        fake_run_preflight,
    )
    _patch_dispatch(monkeypatch)
    assert orch.run("YOK-42", session_id="s1", out=io.StringIO()) == 0
    assert captured["project"] == want_project


def test_worktree_preflight_resolves_project_checkout(monkeypatch):
    normalized: List[str] = []

    # Project-checkout resolution routes through the transport-aware relay
    # helper so it works over an https control plane, not a local connection.
    monkeypatch.setattr(
        "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
        lambda project, **_kw: Path("/tmp/externalwebapp-repo"),
    )
    monkeypatch.setattr(
        worktree_preflight, "_normalize_repo_root",
        lambda value: normalized.append(value) or value,
    )
    # Blocked-flag read is sourced from ``items.detail.get`` via the relay.
    from yoke_core.api import service_client_structured_api_adapter as facade

    monkeypatch.setattr(
        facade, "call_dispatcher",
        lambda **_k: FunctionCallResponse(
            success=True, function="items.detail.get", version="v1",
            result={"item": {"blocked": False}},
        ),
    )
    monkeypatch.setattr(
        worktree_preflight, "claim_work", lambda item_id: (True, "claimed"),
    )
    monkeypatch.setattr(
        worktree_preflight, "activate_path_claims",
        lambda item_id: (True, "", []),
    )

    result = worktree_preflight.run_preflight(item_id=42, project="externalwebapp",
                                              no_worktree=True)
    assert result.ok is True
    assert normalized == ["/tmp/externalwebapp-repo"]


# ---------------------------------------------------------------------------
# Structured error envelope on failure
# ---------------------------------------------------------------------------

def test_failure_envelope_drops_empty_fields_and_emits_error_payload(
    monkeypatch, silence_emits,
):
    """A blocked outcome must NOT carry empty ``worktree_path`` / ``branch``
    strings — those are structurally ambiguous. Instead, the envelope
    carries a top-level ``error`` payload that names the failing phase."""
    monkeypatch.setattr(orch, "_read_item", lambda _id: _item())
    monkeypatch.setattr(
        orch, "_run_preflight_gates",
        lambda _id, force: (False, "BLOCKED: missing AC presence"),
    )
    out = io.StringIO()
    assert orch.run("YOK-42", session_id="s1", out=out) == 1
    envelope = json.loads(out.getvalue())
    assert "worktree_path" not in envelope, (
        "blocked outcome must not include an empty worktree_path string"
    )
    assert "branch" not in envelope, (
        "blocked outcome must not include an empty branch string"
    )
    assert envelope["error"]["phase"] == "preflight"
    assert envelope["error"]["kind"] == "gate_blocked"
    assert "BLOCKED" in envelope["error"]["narrative"]


def test_worktree_block_envelope_carries_block_kind(
    monkeypatch, silence_emits, gates_pass,
):
    """A worktree-phase block returns a structured error naming the
    ``block_kind`` (for example ``dirty-tracked`` for a dirty target repo)."""
    monkeypatch.setattr(orch, "_read_item", lambda _id: _item())
    monkeypatch.setattr(
        "yoke_core.domain.worktree_preflight.run_preflight",
        lambda **kw: _WtStub(
            ok=False, block_kind="dirty-tracked",
            narrative="Cannot create worktree: main has tracked files.",
        ),
    )
    out = io.StringIO()
    assert orch.run("YOK-42", session_id="s1", out=out) == 1
    envelope = json.loads(out.getvalue())
    assert "worktree_path" not in envelope
    assert envelope["error"]["phase"] == "worktree"
    assert envelope["error"]["kind"] == "dirty-tracked"


def test_finalize_block_envelope_carries_error_code(
    monkeypatch, silence_emits, gates_pass, env_noop,
):
    """Finalize refusals (lifecycle gate denials) attach the gate code to
    the structured error so the operator sees which gate refused."""
    monkeypatch.setattr(orch, "_read_item", lambda _id: _item())
    monkeypatch.setattr(
        "yoke_core.domain.worktree_preflight.run_preflight",
        lambda **kw: _WtStub(),
    )
    _patch_dispatch(monkeypatch, _err_response("qa_block",
                                                "QA requirements not satisfied"))
    out = io.StringIO()
    assert orch.run("YOK-42", session_id="s1", out=out) == 1
    envelope = json.loads(out.getvalue())
    assert envelope["error"]["phase"] == "finalize"
    assert envelope["error"]["kind"] == "qa_block"
