"""A case run binds its authority at start and carries it to every leg.

The begin leg is where the dispatcher verifies the session's item claim,
so that is where the claim is pinned onto the contract. Every recording
leg the run fires afterwards presents it, because by then — an hour of
suite later — the live claim may be gone.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import qa_case_execution
from yoke_core.domain.handlers import qa_case_execution as case_handlers
from yoke_core.domain.qa_start_bound_authority import PAYLOAD_KEY

_CLAIM = 7695
_ITEM = 1981
_REQUIREMENT = 41
_SESSION = "s-run"

_RECORDING_LEGS = ("qa.run.add", "qa.artifact.add", "qa.run.complete")


def _case(bound_claim_id: int | None) -> dict:
    case = {
        "requirement_id": _REQUIREMENT,
        "item_id": _ITEM,
        "plan_id": 5,
        "case_key": "registered",
        "method_id": "command",
        "executor_id": "worktree_run",
        "method_config": {"command": "printf 'case-output'"},
        "project_id": 1,
        "project": "yoke",
        "lane_branch": None,
    }
    if bound_claim_id is not None:
        case[PAYLOAD_KEY] = bound_claim_id
    return case


def _run_case(tmp_path: Path, case: dict) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []

    def dispatch(function_id, requirement_id, payload, *, actor=None):
        calls.append((function_id, payload))
        if function_id == "qa.artifact.add":
            return {"qa_artifact_id": 88}
        return {"qa_run_id": 77}

    with (
        mock.patch.object(
            qa_case_execution, "fetch_case_execution_context", return_value=case
        ),
        mock.patch.object(
            qa_case_execution, "_execution_checkout", return_value=tmp_path
        ),
        mock.patch.object(qa_case_execution, "_dispatch", side_effect=dispatch),
    ):
        qa_case_execution.execute_case(
            _REQUIREMENT, actor=ActorContext(actor_id="7", session_id=_SESSION)
        )
    return calls


def test_every_recording_leg_carries_the_bound_claim(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    calls = _run_case(tmp_path, _case(_CLAIM))

    assert [function_id for function_id, _ in calls] == list(_RECORDING_LEGS)
    for _function_id, payload in calls:
        assert payload[PAYLOAD_KEY] == _CLAIM


def test_an_unclaimed_case_carries_no_authority(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    calls = _run_case(tmp_path, _case(None))

    for _function_id, payload in calls:
        assert PAYLOAD_KEY not in payload


def test_begin_pins_the_sessions_claim_onto_the_contract() -> None:
    @contextmanager
    def _connect():
        yield mock.Mock(name="conn")

    request = FunctionCallRequest(
        function="qa.case_execution.begin",
        actor=ActorContext(actor_id="7", session_id=_SESSION),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=_REQUIREMENT),
    )
    with (
        mock.patch("yoke_core.domain.db_helpers.connect", _connect),
        mock.patch(
            "yoke_core.domain.qa_case_execution_context.get_case_execution_context",
            return_value=_case(None),
        ),
        mock.patch(
            "yoke_core.domain.qa_start_bound_authority.resolve_start_bound_claim_id",
            return_value=_CLAIM,
        ) as resolve,
    ):
        outcome = case_handlers.handle_case_execution_begin(request)

    assert outcome.primary_success
    assert outcome.result_payload["case"][PAYLOAD_KEY] == _CLAIM
    assert resolve.call_args.kwargs["item_id"] == _ITEM
    assert resolve.call_args.kwargs["session_id"] == _SESSION
