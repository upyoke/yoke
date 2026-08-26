"""The claim lookup behind the verification tree binding.

Covered separately from the decision logic because the decision tests
substitute the lookup wholesale — which is exactly how a lookup that
answered "no claims" on every https machine went unnoticed while every
test around it passed. These tests stand on the other side of that seam:
they let the real :func:`resolve_claim_worktrees` run and substitute only
the dispatcher underneath it.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from yoke_core.domain import verification_tree_binding
from yoke_core.domain.verification_tree_binding import resolve_claim_worktrees

LANE = "/repo/.worktrees/lane"
OTHER_LANE = "/repo/.worktrees/other"


def _holder(claim_id: int, lanes: list[str], item_id: int = 42) -> dict:
    return {
        "claim_id": claim_id, "session_id": "sess-1", "target_kind": "item",
        "scope": {"item_id": item_id}, "lane_worktrees": lanes,
    }


class _Error:
    def __init__(self, message: str) -> None:
        self.message = message


class _Response:
    def __init__(
        self,
        *,
        success: bool = True,
        result: Optional[dict] = None,
        error: Optional[_Error] = None,
    ) -> None:
        self.success = success
        self.result = result
        self.error = error


def _dispatch(monkeypatch: pytest.MonkeyPatch, outcome: Any) -> list[dict]:
    """Substitute the dispatcher; return the list of calls it received."""
    calls: list[dict] = []

    def _call(**kwargs):
        calls.append(kwargs)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    import yoke_core.api.service_client_structured_api_adapter as adapter

    monkeypatch.setattr(adapter, "call_dispatcher", _call)
    return calls


def test_empty_session_needs_no_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _dispatch(monkeypatch, _Response(result={"holders": []}))
    lookup = resolve_claim_worktrees("")
    assert lookup.worktrees == ()
    assert lookup.reachable is True
    assert calls == []


def test_lookup_goes_through_the_registered_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The whole point of the change: the claim view follows the active
    # connection instead of assuming the control plane is on this disk.
    calls = _dispatch(
        monkeypatch,
        _Response(
            result={
                "current_item_before_implementation": True,
                "holders": [
                    _holder(1, [LANE]),
                ]
            }
        ),
    )
    lookup = resolve_claim_worktrees("sess-1")
    assert lookup.worktrees == (LANE,)
    assert lookup.current_item_before_implementation is True
    assert lookup.reachable is True
    assert len(calls) == 1
    assert calls[0]["function_id"] == "claims.work.holder_list"
    assert calls[0]["payload"] == {"session_id": "sess-1"}


def test_lanes_from_several_claims_are_merged_without_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _dispatch(
        monkeypatch,
        _Response(
            result={
                "holders": [
                    _holder(1, [LANE, OTHER_LANE]),
                    _holder(2, [LANE], item_id=43),
                    _holder(3, [], item_id=44),
                ]
            }
        ),
    )
    assert resolve_claim_worktrees("sess-1").worktrees == (LANE, OTHER_LANE)


def test_claim_without_a_lane_contributes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A claim on an item that has no worktree authorises no tree, and
    # must not be mistaken for an unreachable lookup.
    _dispatch(
        monkeypatch,
        _Response(result={"holders": [_holder(1, [])]}),
    )
    lookup = resolve_claim_worktrees("sess-1")
    assert lookup.worktrees == ()
    assert lookup.reachable is True


def test_transport_failure_reports_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A machine whose control plane is remote and briefly unreachable
    # must not silently answer "this session holds no claims".
    _dispatch(monkeypatch, ConnectionError("connection refused"))
    lookup = resolve_claim_worktrees("sess-1")
    assert lookup.worktrees == ()
    assert lookup.reachable is False
    assert "connection refused" in lookup.detail


def test_refused_call_reports_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _dispatch(
        monkeypatch,
        _Response(success=False, error=_Error("permission denied")),
    )
    lookup = resolve_claim_worktrees("sess-1")
    assert lookup.reachable is False
    assert "permission denied" in lookup.detail


def test_refused_call_without_an_error_body_still_reports_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _dispatch(monkeypatch, _Response(success=False))
    lookup = resolve_claim_worktrees("sess-1")
    assert lookup.reachable is False
    assert lookup.detail


def test_unreachable_lookup_reaches_the_run_verdict_as_a_notice(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    # End to end through the real lookup: an unreachable control plane
    # lets the run proceed and says so, rather than passing silently.
    monkeypatch.setattr(
        verification_tree_binding, "_tree_is_free", lambda _tree: False,
    )
    monkeypatch.setattr(
        verification_tree_binding, "ambient_session_id", lambda: "sess-1",
    )
    _dispatch(monkeypatch, ConnectionError("no route to host"))
    verdict = verification_tree_binding.evaluate_run(
        surface="pytest", tree=str(tmp_path),
    )
    assert verdict.refusal is None
    assert verdict.notice is not None
    assert "no route to host" in verdict.notice


def test_free_path_tree_never_reaches_the_control_plane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A tree on the free-path allowlist passes whatever the claims say,
    # so the round trip is skipped rather than paid on every run under a
    # temp root.
    monkeypatch.setattr(
        verification_tree_binding, "ambient_session_id", lambda: "sess-1",
    )
    monkeypatch.setattr(
        verification_tree_binding, "_tree_is_free", lambda _tree: True,
    )
    calls = _dispatch(monkeypatch, _Response(result={"holders": []}))
    verdict = verification_tree_binding.evaluate_run(
        surface="pytest", tree="/tmp/anywhere",
    )
    assert verdict.refusal is None and verdict.notice is None
    assert calls == []


def test_reachable_lookup_with_a_lane_still_refuses_an_outside_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    # The path that was inert before: a real lookup that succeeds and
    # names a lane must produce a real refusal.
    monkeypatch.setattr(
        verification_tree_binding, "_tree_is_free", lambda _tree: False,
    )
    monkeypatch.setattr(
        verification_tree_binding, "ambient_session_id", lambda: "sess-1",
    )
    lane = tmp_path / ".worktrees" / "lane"
    lane.mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    _dispatch(
        monkeypatch,
        _Response(
            result={"holders": [_holder(1, [str(lane)])]}
        ),
    )
    verdict = verification_tree_binding.evaluate_run(
        surface="pytest", tree=str(outside),
    )
    assert verdict.refusal is not None
    assert str(lane) in verdict.refusal
