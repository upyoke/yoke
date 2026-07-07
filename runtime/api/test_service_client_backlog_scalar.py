"""Tests for the scalar-flag CLI adapters (freeze/thaw/block/unblock).

Verifies that each CLI verb builds the right ``items.scalar.update``
envelope and dispatches it through the typed registry, mirroring the
adapter pattern in :mod:`service_client_backlog_update_dispatch`.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from yoke_core.api import service_client_backlog_scalar as scalar


class _FakeError:
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message


class _FakeResponse:
    def __init__(self, success: bool, error: _FakeError | None = None) -> None:
        self.success = success
        self.error = error
        self.warnings: List[Any] = []
        self.result: Dict[str, Any] = {}


def _ok() -> _FakeResponse:
    return _FakeResponse(success=True)


def _err(code: str = "invalid_payload", message: str = "boom") -> _FakeResponse:
    return _FakeResponse(success=False, error=_FakeError(code, message))


def _capture_envelopes() -> tuple[List[Dict[str, Any]], Any]:
    """Patch dispatch + register and capture every envelope dispatched."""
    seen: List[Dict[str, Any]] = []

    def fake_dispatch(envelope: Dict[str, Any]) -> _FakeResponse:
        seen.append(envelope)
        return _ok()

    return seen, fake_dispatch


@pytest.mark.parametrize("raw,expected", [
    ("1685", 1685),
    (" 42 ", 42),
])
def test_parse_item_id_accepts_variants(raw: str, expected: int) -> None:
    assert scalar._parse_item_id(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "YOK-x", "YOK-1685", "yok-1685", "YOK-05", None])
def test_parse_item_id_rejects_garbage(raw: Any) -> None:
    assert scalar._parse_item_id(raw) is None


def test_freeze_dispatches_frozen_true(capsys: pytest.CaptureFixture[str]) -> None:
    seen, fake = _capture_envelopes()
    with patch.object(scalar, "_dispatch_scalar", wraps=scalar._dispatch_scalar) as wrapped:
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch", side_effect=fake
        ), patch(
            "yoke_core.domain.handlers.__init_register__.register_all_handlers",
        ), patch(
            "yoke_core.api.service_client_shared_session_resolver.current_session_id", return_value="test-sid",
        ):
            rc = scalar.cmd_freeze(["1685"])
    assert rc == 0
    assert wrapped.call_count == 1
    assert len(seen) == 1
    envelope = seen[0]
    assert envelope["function"] == "items.scalar.update"
    assert envelope["target"] == {"kind": "item", "item_id": 1685}
    assert envelope["payload"] == {"field": "frozen", "value": True}
    assert envelope["intent"] == "freeze"
    assert envelope["actor"]["session_id"] == "test-sid"
    assert envelope["options"]["rebuild_board"] is True
    out = capsys.readouterr().out
    assert "YOK-1685: frozen" in out


def test_thaw_dispatches_frozen_false(capsys: pytest.CaptureFixture[str]) -> None:
    seen, fake = _capture_envelopes()
    with patch(
        "yoke_core.domain.yoke_function_dispatch.dispatch", side_effect=fake
    ), patch(
        "yoke_core.domain.handlers.__init_register__.register_all_handlers",
    ), patch(
        "yoke_core.api.service_client_shared_session_resolver.current_session_id", return_value="sid",
    ):
        rc = scalar.cmd_thaw(["42"])
    assert rc == 0
    assert seen[0]["payload"] == {"field": "frozen", "value": False}
    assert seen[0]["intent"] == "thaw"
    assert "YOK-42: thawed" in capsys.readouterr().out


def test_block_dispatches_two_writes_in_order(capsys: pytest.CaptureFixture[str]) -> None:
    seen, fake = _capture_envelopes()
    with patch(
        "yoke_core.domain.yoke_function_dispatch.dispatch", side_effect=fake
    ), patch(
        "yoke_core.domain.handlers.__init_register__.register_all_handlers",
    ), patch(
        "yoke_core.api.service_client_shared_session_resolver.current_session_id", return_value="sid",
    ):
        rc = scalar.cmd_block(["100", "needs design review"])
    assert rc == 0
    assert len(seen) == 2
    assert seen[0]["payload"] == {"field": "blocked", "value": True}
    assert seen[1]["payload"] == {"field": "blocked_reason", "value": "needs design review"}
    out = capsys.readouterr().out
    assert "YOK-100: blocked" in out
    assert "needs design review" in out


def test_unblock_dispatches_two_clears(capsys: pytest.CaptureFixture[str]) -> None:
    seen, fake = _capture_envelopes()
    with patch(
        "yoke_core.domain.yoke_function_dispatch.dispatch", side_effect=fake
    ), patch(
        "yoke_core.domain.handlers.__init_register__.register_all_handlers",
    ), patch(
        "yoke_core.api.service_client_shared_session_resolver.current_session_id", return_value="sid",
    ):
        rc = scalar.cmd_unblock(["7"])
    assert rc == 0
    assert len(seen) == 2
    assert seen[0]["payload"] == {"field": "blocked", "value": False}
    assert seen[1]["payload"] == {"field": "blocked_reason", "value": None}
    assert "YOK-7: unblocked" in capsys.readouterr().out


def test_freeze_reports_failure_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    fail = _err(code="frozen", message="already frozen")

    def fake_dispatch(_envelope: Dict[str, Any]) -> _FakeResponse:
        return fail

    with patch(
        "yoke_core.domain.yoke_function_dispatch.dispatch", side_effect=fake_dispatch
    ), patch(
        "yoke_core.domain.handlers.__init_register__.register_all_handlers",
    ), patch(
        "yoke_core.api.service_client_shared_session_resolver.current_session_id", return_value="sid",
    ):
        rc = scalar.cmd_freeze(["1"])
    assert rc == 1
    err_out = capsys.readouterr().err
    assert "FAILED" in err_out
    assert "frozen" in err_out
    assert "already frozen" in err_out


def test_block_partial_state_reports_recovery(capsys: pytest.CaptureFixture[str]) -> None:
    calls: List[Dict[str, Any]] = []

    def fake_dispatch(envelope: Dict[str, Any]) -> _FakeResponse:
        calls.append(envelope)
        if envelope["payload"]["field"] == "blocked_reason":
            return _err(code="validation_error", message="bad reason")
        return _ok()

    with patch(
        "yoke_core.domain.yoke_function_dispatch.dispatch", side_effect=fake_dispatch
    ), patch(
        "yoke_core.domain.handlers.__init_register__.register_all_handlers",
    ), patch(
        "yoke_core.api.service_client_shared_session_resolver.current_session_id", return_value="sid",
    ):
        rc = scalar.cmd_block(["99", "reason"])
    assert rc == 1
    err_out = capsys.readouterr().err
    assert "PARTIAL" in err_out
    assert "blocked=true set but reason write failed" in err_out
    assert "db_router items update 99 blocked_reason" in err_out


@pytest.mark.parametrize("verb,fn", [
    ("freeze", scalar.cmd_freeze),
    ("thaw", scalar.cmd_thaw),
    ("unblock", scalar.cmd_unblock),
])
def test_single_id_verbs_reject_wrong_arity(verb: str, fn: Any, capsys: pytest.CaptureFixture[str]) -> None:
    assert fn([]) == 2
    assert fn(["a", "b"]) == 2
    assert verb in capsys.readouterr().err


def test_block_rejects_wrong_arity(capsys: pytest.CaptureFixture[str]) -> None:
    assert scalar.cmd_block([]) == 2
    assert scalar.cmd_block(["1"]) == 2
    assert scalar.cmd_block(["1", "  "]) == 2
    err = capsys.readouterr().err
    assert "block" in err


def test_invalid_id_returns_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert scalar.cmd_freeze(["not-an-id"]) == 2
    assert "invalid item id" in capsys.readouterr().err
