"""The local hold runtime: authority read first, mutation local, clear proven.

Ownership and resolution come from reads, so these pin that a server older
than this change is never asked for vocabulary it lacks: the registered
hold is called only after a readback already showed the candidate clear,
and never as a way to discover whether acting is allowed.

That registered hold is itself a mutation against a live pull request, so
these also pin that its result is read back — a candidate that lands or
re-arms around it is reported as that, not as the held verdict this
runtime had already proven a moment earlier.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from yoke_cli.commands import merge_queue_hold_local_runtime as runtime

ITEM = "PRJ-9"
SESSION = "session-holding-the-item"
PR = "1206"


class _Plane:
    """Records every registered call and serves scripted read results."""

    def __init__(self, *, holder_session: str | None = SESSION, readbacks=None):
        self.calls: List[str] = []
        self._holder_session = holder_session
        self._readbacks = list(readbacks or [])
        self.hold_refused = False

    def __call__(self, *, function_id, target, payload, actor=None):
        self.calls.append(function_id)
        if function_id == runtime._CLAIM_HOLDER_FUNCTION:
            holder = (
                {"session_id": self._holder_session} if self._holder_session else None
            )
            return _ok({"holder": holder})
        if function_id == runtime._READINESS_FUNCTION:
            if not self._readbacks:
                return _fail("no further readback scripted")
            nxt = self._readbacks.pop(0)
            return _fail(nxt) if isinstance(nxt, str) else _ok(nxt)
        if function_id == runtime._HOLD_FUNCTION:
            if self.hold_refused:
                return _fail("older server does not know this outcome")
            return _ok({"outcome": "already_clear"})
        raise AssertionError(f"unexpected function {function_id}")


def _ok(result: Dict[str, Any]):
    return SimpleNamespace(success=True, result=result, error=None)


def _fail(message: str):
    return SimpleNamespace(
        success=False, result=None, error=SimpleNamespace(message=message)
    )


def _readback(*, armed=False, entry=False, merged=False) -> Dict[str, Any]:
    return {
        "pr_number": PR,
        "target": "main",
        "project": "prj",
        "merged": merged,
        "queue_entry_state": "present" if entry else "absent",
        "merge_when_ready": "armed" if armed else "cleared",
        "narrative": "scripted readback",
    }


@pytest.fixture()
def plane(monkeypatch):
    def _install(**kwargs):
        recorder = _Plane(**kwargs)
        monkeypatch.setattr(runtime, "call_dispatcher", recorder)
        monkeypatch.setattr(
            runtime, "build_actor", lambda: SimpleNamespace(session_id=SESSION)
        )
        monkeypatch.setattr(runtime, "machine_github_user_authority", _noop)
        monkeypatch.setattr(runtime, "same_universe_control_plane_authority", _noop)
        return recorder

    return _install


def _noop():
    from contextlib import nullcontext

    return nullcontext()


def _local_hold(actions=("disarm merge-when-ready: ok",)):
    return lambda _readiness: SimpleNamespace(actions=tuple(actions))


class TestOwnershipIsReadBeforeAnythingElse:
    def test_a_session_without_the_claim_is_refused(self, plane) -> None:
        recorder = plane(holder_session="another-session")

        with pytest.raises(runtime.HoldRefused, match="not this"):
            runtime.run([ITEM])

        # Refused on ownership alone: no readiness read, no mutation.
        assert recorder.calls == [runtime._CLAIM_HOLDER_FUNCTION]

    def test_an_unclaimed_item_is_refused(self, plane) -> None:
        recorder = plane(holder_session=None)

        with pytest.raises(runtime.HoldRefused, match="no live work claim"):
            runtime.run([ITEM])

        assert recorder.calls == [runtime._CLAIM_HOLDER_FUNCTION]


class TestTheHoldFunctionIsNeverAnAuthorizationProbe:
    def test_nothing_is_recorded_until_a_readback_shows_it_clear(
        self, plane, monkeypatch
    ) -> None:
        recorder = plane(
            readbacks=[
                _readback(armed=True, entry=True),
                _readback(),
                _readback(),
            ]
        )
        monkeypatch.setattr(runtime, "_hold_locally", _local_hold())

        assert runtime.run([ITEM]) == 0

        # Claim, readback, local mutation, confirming readback, record, and
        # the final read that decides the verdict.
        assert recorder.calls == [
            runtime._CLAIM_HOLDER_FUNCTION,
            runtime._READINESS_FUNCTION,
            runtime._READINESS_FUNCTION,
            runtime._HOLD_FUNCTION,
            runtime._READINESS_FUNCTION,
        ]

    def test_a_still_live_candidate_is_not_held_and_records_nothing(
        self, plane, monkeypatch
    ) -> None:
        recorder = plane(
            readbacks=[_readback(armed=True, entry=True), _readback(entry=True)]
        )
        monkeypatch.setattr(runtime, "_hold_locally", _local_hold())

        assert runtime.run([ITEM]) == 1

        assert runtime._HOLD_FUNCTION not in recorder.calls

    def test_an_older_server_refusing_the_record_still_reports_held(
        self, plane, monkeypatch
    ) -> None:
        """A refused record is noted; the final read is what decides."""
        recorder = plane(readbacks=[_readback(armed=True), _readback(), _readback()])
        recorder.hold_refused = True
        monkeypatch.setattr(runtime, "_hold_locally", _local_hold())

        assert runtime.run([ITEM]) == 0


class TestTheRecordingMutationIsItselfReadBack:
    """It mutates a live pull request, so it can be overtaken."""

    def test_a_candidate_that_lands_during_the_record_reports_the_landing(
        self, plane, monkeypatch
    ) -> None:
        plane(
            readbacks=[
                _readback(armed=True),
                _readback(),
                _readback(merged=True),
            ]
        )
        monkeypatch.setattr(runtime, "_hold_locally", _local_hold())

        assert runtime.run([ITEM, "--json"]) == 1

    def test_a_candidate_live_again_after_the_record_is_not_held(
        self, plane, monkeypatch, capsys
    ) -> None:
        plane(
            readbacks=[
                _readback(armed=True),
                _readback(),
                _readback(armed=True),
            ]
        )
        monkeypatch.setattr(runtime, "_hold_locally", _local_hold())

        assert runtime.run([ITEM, "--json"]) == 1

        printed = capsys.readouterr().out
        assert '"outcome": "not_held"' in printed
        assert "do not push" in printed

    def test_a_failed_final_read_after_the_record_is_unverified(
        self, plane, monkeypatch, capsys
    ) -> None:
        plane(
            readbacks=[
                _readback(armed=True),
                _readback(),
                "control plane unreachable",
            ]
        )
        monkeypatch.setattr(runtime, "_hold_locally", _local_hold())

        assert runtime.run([ITEM, "--json"]) == 1

        printed = capsys.readouterr().out
        assert '"outcome": "unverified"' in printed
        assert "final readback failed" in printed
        assert "do not push" in printed

    def test_a_final_read_about_a_different_candidate_is_unverified(
        self, plane, monkeypatch, capsys
    ) -> None:
        """A readback naming another pull request proves nothing about this one."""
        moved = _readback()
        moved["pr_number"] = "9999"
        plane(readbacks=[_readback(armed=True), _readback(), moved])
        monkeypatch.setattr(runtime, "_hold_locally", _local_hold())

        assert runtime.run([ITEM, "--json"]) == 1

        printed = capsys.readouterr().out
        assert '"outcome": "unverified"' in printed
        assert "different candidate" in printed


class TestUnconfirmedLocalActionsAreNeverReportedHeld:
    def test_a_failed_confirming_readback_reports_unverified(
        self, plane, monkeypatch, capsys
    ) -> None:
        plane(readbacks=[_readback(armed=True), "control plane unreachable"])
        monkeypatch.setattr(runtime, "_hold_locally", _local_hold())

        assert runtime.run([ITEM, "--json"]) == 1

        printed = capsys.readouterr().out
        assert '"outcome": "unverified"' in printed
        assert '"held": false' in printed
        # The local actions are retained, and the caller is told not to push.
        assert "disarm merge-when-ready: ok" in printed
        assert "do not push" in printed


class TestReadbackOnlyOutcomesNeedNoMutation:
    def test_an_already_clear_candidate_is_held_without_acting(self, plane) -> None:
        recorder = plane(readbacks=[_readback()])

        assert runtime.run([ITEM]) == 0

        assert runtime._HOLD_FUNCTION not in recorder.calls

    def test_a_merged_candidate_reports_the_landing(self, plane) -> None:
        recorder = plane(readbacks=[_readback(merged=True)])

        assert runtime.run([ITEM]) == 1

        assert runtime._HOLD_FUNCTION not in recorder.calls
