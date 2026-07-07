"""Tests for the ``scratch.dispatch_inputs`` handler."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import project_scratch_dir as scratch
from yoke_core.domain.handlers.scratch_dispatch_inputs import (
    REGISTRATIONS,
    handle_dispatch_inputs,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


@pytest.fixture
def scoped_scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(scratch.ENV_KEY, str(tmp_path))
    return tmp_path


def _make_request(payload: dict, target_kind: str = "global") -> FunctionCallRequest:
    return FunctionCallRequest(
        function="scratch.dispatch_inputs",
        request_id="req-test",
        actor=ActorContext(session_id="sid"),
        target=TargetRef(kind=target_kind),
        payload=payload,
    )


def test_handler_returns_absolute_path(scoped_scratch: Path) -> None:
    request = _make_request(
        {"item_id": 1846, "session_id": "session-foo", "attempt": 1}
    )

    outcome = handle_dispatch_inputs(request)

    assert outcome.primary_success is True
    assert outcome.error is None
    path = Path(outcome.result_payload["path"])
    assert path.is_absolute()
    assert path.is_relative_to(scoped_scratch)
    assert "data/sessions" not in path.as_posix()
    assert path.name == "attempt-1"
    assert path.parent.name == "session-foo"
    assert path.parent.parent.name == "YOK-1846"


def test_handler_rejects_non_global_target(scoped_scratch: Path) -> None:
    request = _make_request(
        {"item_id": 42, "session_id": "s", "attempt": 1},
        target_kind="item",
    )
    request.target.item_id = 42

    outcome = handle_dispatch_inputs(request)

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "invalid_payload"


def test_handler_rejects_missing_fields(scoped_scratch: Path) -> None:
    request = _make_request({"item_id": 42, "session_id": "s"})

    outcome = handle_dispatch_inputs(request)

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "invalid_payload"


def test_handler_rejects_attempt_zero(scoped_scratch: Path) -> None:
    request = _make_request({"item_id": 42, "session_id": "s", "attempt": 0})

    outcome = handle_dispatch_inputs(request)

    assert outcome.primary_success is False


def test_registrations_metadata_matches_spec() -> None:
    assert len(REGISTRATIONS) == 1
    entry = REGISTRATIONS[0]
    assert entry["function_id"] == "scratch.dispatch_inputs"
    assert entry["target_kinds"] == ["global"]
    assert entry["claim_required_kind"] is None
    assert entry["adapter_status"] == "live"
    assert entry["side_effects"] == []
    assert entry["emitted_event_names"] == []
    assert entry["owner_module"] == "yoke_core.domain.project_scratch_dir"
