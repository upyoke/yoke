"""Dispatch-path tests for the ``yoke`` operations CLI.

Covers EXP-AC-1: every Tier-1 function id dispatches in-process through
:func:`yoke_function_dispatch.dispatch` from the matching CLI form.
Plus the error-shape regressions (missing required flag, bad YOK-N,
bad integer flag, dispatch failure exit code).
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import List
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)


_CAPTURED_REQUESTS: List[FunctionCallRequest] = []


def _stub_dispatch_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={"echo": True},
    )


def _stub_dispatch_fail(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=False,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        error=FunctionError(code="invalid_payload", message="stub failure"),
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run_with_dispatch(stub, *argv: str, session_id: str = "test-session") -> int:
    rc, _out, _err = _run_capture(stub, *argv, session_id=session_id)
    return rc


def _run_capture(
    stub, *argv: str, session_id: str = "test-session",
) -> tuple[int, str, str]:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": session_id}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=stub,
        ), patch(
            "yoke_cli.commands.adapters.claims.sync_local_snapshot_for_write"
        ), patch(
            "yoke_cli.commands.adapters.claims_path_flow.sync_local_snapshot_for_write"
        ), patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                buf = io.StringIO()
                err = io.StringIO()
                with redirect_stdout(buf), redirect_stderr(err):
                    rc = cli_main(list(argv))
                return rc, buf.getvalue(), err.getvalue()


class TestEveryTierOneFamilyDispatches:
    """EXP-AC-1: every Tier-1 function id dispatches through the new CLI."""

    def test_items_get_dispatches(self) -> None:
        rc = _run_with_dispatch(_stub_dispatch_ok, "items", "get", "1791", "spec")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "items.get.run"
        assert req.target.kind == "item"
        assert req.target.item_ref == "1791"
        assert req.target.item_id is None
        assert req.payload["fields"] == ["spec"]
        assert req.actor.session_id == "test-session"

    def test_items_get_field_projection_prints_raw_values(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={"item_id": 1791, "fields": {"status": "implemented"}},
            )

        rc, out, _err = _run_capture(
            stub, "items", "get", "1791", "status",
        )
        assert rc == 0
        assert out == "implemented\n"

    def test_items_progress_log_append_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "progress-log", "append", "1819",
            "--headline", "test", "--content", "body",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "items.progress_log.append"
        assert req.target.item_ref == "1819"
        assert req.payload["headline"] == "test"
        assert req.payload["content"] == "body"

    def test_items_structured_field_replace_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "structured-field", "replace", "1819",
            "--field", "spec", "--content", "hello",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "items.structured_field.replace"
        assert req.target.item_ref == "1819"
        assert req.payload == {
            "field": "spec", "content": "hello",
            "source": "", "force": False,
        }

    def test_items_github_sync_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "items", "github-sync", "YOK-1819",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "items.github_sync"
        assert req.target.kind == "item"
        assert req.target.item_ref == "YOK-1819"
        assert req.payload == {}

    def test_claims_work_acquire_dispatches_item(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "claims", "work", "acquire",
            "--item", "1819", "--reason", "polish pass",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "claims.work.acquire"
        assert req.target.kind == "item"
        assert req.target.item_ref == "1819"
        assert req.payload["target"]["kind"] == "item"
        assert "item_id" not in req.payload["target"]
        assert req.payload["reason"] == "polish pass"

    def test_claims_work_release_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "claims", "work", "release",
            "--claim-id", "42", "--reason", "done",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "claims.work.release"
        assert req.target.kind == "claim"
        assert req.payload == {"claim_id": 42, "reason": "done"}

    def test_claims_path_register_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "claims", "path", "register",
            "--item", "1819",
            "--paths", "runtime/api/cli/foo.py,runtime/api/cli/bar.py",
            "--allow-planned",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "claims.path.register"
        assert req.target.item_ref == "1819"
        assert req.payload["paths"] == [
            "runtime/api/cli/foo.py", "runtime/api/cli/bar.py",
        ]
        assert req.payload["allow_planned"] is True
        assert req.payload["mode"] == "exclusive"

    def test_claims_path_widen_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "claims", "path", "widen",
            "--claim-id", "273",
            "--add-paths", "runtime/api/cli/new.py",
            "--reason", "extend coverage",
            "--item", "1819",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "claims.path.widen"
        assert req.target.item_ref == "1819"
        assert req.payload == {
            "claim_id": 273,
            "add_paths": ["runtime/api/cli/new.py"],
            "reason": "extend coverage",
            "allow_planned": False,
        }

    def test_claims_path_widen_allow_planned_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "claims", "path", "widen",
            "--claim-id", "273",
            "--add-paths",
            "runtime/api/domain/new.py,runtime/api/domain/dir/",
            "--reason", "widen with planned coverage",
            "--item", "1819",
            "--allow-planned",
            "--directory-paths", "runtime/api/domain/dir/",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "claims.path.widen"
        assert req.target.item_ref == "1819"
        assert req.payload == {
            "claim_id": 273,
            "add_paths": [
                "runtime/api/domain/new.py",
                "runtime/api/domain/dir/",
            ],
            "reason": "widen with planned coverage",
            "allow_planned": True,
            "directory_paths": ["runtime/api/domain/dir/"],
        }

    def test_events_query_dispatches_global(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "events", "query",
            "--event-name", "ItemStatusChanged", "--limit", "10",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "events.query.run"
        assert req.target.kind == "global"
        assert req.payload == {"event_name": "ItemStatusChanged", "limit": 10}

    def test_events_query_dispatches_item_scoped(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "events", "query", "--item", "1819",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.target.kind == "item"
        assert req.target.item_ref == "1819"
        assert "item_id" not in req.payload

    def test_lifecycle_transition_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "lifecycle", "transition", "1819",
            "--to", "polishing-implementation",
            "--from", "implemented",
            "--reason", "expansion in flight",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "lifecycle.transition.execute"
        assert req.target.item_ref == "1819"
        assert req.payload == {
            "target_status": "polishing-implementation",
            "source_status": "implemented",
            "reason": "expansion in flight",
        }

    def test_ouroboros_field_note_append_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "ouroboros", "field-note", "append",
            "--kind", "failed",
            "--evidence", "recipe X did not work",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "ouroboros.field_note.append"
        assert req.target.kind == "global"
        assert req.payload == {
            "kind": "failed", "evidence": "recipe X did not work",
        }

    def test_field_note_accepts_observation_kind(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "ouroboros", "field-note", "append",
            "--kind", "observation",
            "--evidence", "test",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "ouroboros.field_note.append"
        assert req.payload["kind"] == "observation"


class TestErrorShapes:
    def test_missing_required_flag_returns_two(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "claims", "work", "release", "--claim-id", "42",  # missing --reason
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_bad_ref_relays_verbatim_for_server_resolution(self) -> None:
        # Relay contract: the client never validates item refs; the raw
        # token rides target.item_ref and the dispatcher owns rejection.
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "items", "get", "not-a-sun-id",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.target.item_ref == "not-a-sun-id"
        assert req.target.item_id is None

    def test_bad_integer_flag_returns_two(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "claims", "work", "release",
            "--claim-id", "not-int", "--reason", "x",
        )
        assert rc == 2

    def test_claims_work_acquire_requires_target_selector(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "claims", "work", "acquire", "--reason", "no target",
        )
        assert rc == 2

    def test_dispatch_failure_returns_one(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_fail, "items", "get", "1819",
        )
        assert rc == 1
