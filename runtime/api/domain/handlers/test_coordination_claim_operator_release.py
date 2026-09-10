"""Hosted operator and ordinary-holder coordination-claim release tests."""

from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest

from runtime.api.domain.coordination_claim_test_support import seed_session
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.coordination_claim_record import CoordinationClaim
from yoke_core.domain.coordination_claims import acquire, active_claim
from yoke_core.domain.coordination_claims_operator import (
    CoordinationClaimChangedError,
    operator_release,
)
from yoke_core.domain.handlers.claims_coordination_claim import handle_release
from yoke_core.domain.handlers.claims_coordination_claim_operator import (
    handle_operator_release,
)
from yoke_core.domain.work_claim_targets import make_deploy_serialization_target


def _request(
    function: str,
    payload: dict,
    *,
    actor_id: str = "2",
    session_id: str = "",
):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=actor_id, session_id=session_id),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _claim(*, session_id: str = "holder", released_at: str | None = None):
    return CoordinationClaim(
        id=42,
        target=make_deploy_serialization_target(1, "yoke"),
        session_id=session_id,
        claimed_at="2026-09-10T00:00:00Z",
        released_at=released_at,
    )


def _operator_payload() -> dict:
    return {
        "project_id": "yoke",
        "key": "DEPLOY:yoke",
        "claim_id": 42,
        "holder_session_id": "holder",
        "reason": "driver exited after the deployment settled",
    }


@pytest.mark.parametrize(
    "session_id",
    ("manual-agent", "launched-agent"),
)
def test_agent_session_cannot_invoke_operator_release(session_id: str) -> None:
    conn = MagicMock()
    with (
        patch("yoke_core.domain.db_helpers.connect", return_value=nullcontext(conn)),
        patch(
            "yoke_core.domain.coordination_claims_operator.operator_release"
        ) as release,
    ):
        outcome = handle_operator_release(
            _request(
                "claims.coordination_claim.operator_release",
                _operator_payload(),
                session_id=session_id,
            )
        )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "human_operator_required"
    release.assert_not_called()


def test_non_human_actor_cannot_invoke_operator_release() -> None:
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = ("system",)
    with (
        patch(
            "yoke_core.domain.db_helpers.connect", return_value=nullcontext(conn)
        ),
        patch(
            "yoke_core.domain.coordination_claims_operator.operator_release"
        ) as release,
    ):
        outcome = handle_operator_release(
            _request(
                "claims.coordination_claim.operator_release", _operator_payload()
            )
        )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "human_operator_required"
    release.assert_not_called()


def test_operator_release_passes_exact_reviewed_claim_to_domain() -> None:
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = ("human",)
    result = {
        "released": True,
        "claim_id": 42,
        "project_id": 1,
        "key": "DEPLOY:yoke",
        "prior_session_id": "holder",
        "operator_actor_id": 2,
        "operator_reason": "driver exited after the deployment settled",
        "released_at": "2026-09-10T01:00:00Z",
    }
    with (
        patch("yoke_core.domain.db_helpers.connect", return_value=nullcontext(conn)),
        patch(
            "yoke_core.domain.coordination_claims_operator.operator_release",
            return_value=result,
        ) as release,
    ):
        outcome = handle_operator_release(
            _request("claims.coordination_claim.operator_release", _operator_payload())
        )

    assert outcome.primary_success is True
    assert outcome.result_payload == result
    assert release.call_args.kwargs["expected_claim_id"] == 42
    assert release.call_args.kwargs["expected_holder_session_id"] == "holder"
    assert release.call_args.kwargs["operator_actor_id"] == 2


def test_ordinary_release_refuses_a_foreign_holder() -> None:
    with (
        patch(
            "yoke_core.domain.handlers.claims_coordination_claim._connect_rw",
            return_value=nullcontext(MagicMock()),
        ),
        patch(
            "yoke_core.domain.coordination_claims.get_claim",
            return_value=_claim(session_id="holder"),
        ),
        patch("yoke_core.domain.coordination_claims.release") as release,
    ):
        outcome = handle_release(
            _request(
                "claims.coordination_claim.release",
                {"claim_id": 42, "reason": "not mine"},
                session_id="other",
            )
        )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "claim_not_held"
    assert "authenticated human terminal outside any harness session" in (
        outcome.error.message
    )
    assert "authorized operator session" not in outcome.error.message
    release.assert_not_called()


def test_ordinary_holder_can_release_its_own_claim() -> None:
    released = _claim(session_id="holder", released_at="2026-09-10T01:00:00Z")
    with (
        patch(
            "yoke_core.domain.handlers.claims_coordination_claim._connect_rw",
            return_value=nullcontext(MagicMock()),
        ),
        patch(
            "yoke_core.domain.coordination_claims.get_claim",
            return_value=_claim(session_id="holder"),
        ),
        patch(
            "yoke_core.domain.coordination_claims.release", return_value=released
        ) as release,
    ):
        outcome = handle_release(
            _request(
                "claims.coordination_claim.release",
                {"claim_id": 42, "reason": "release pair complete"},
                session_id="holder",
            )
        )

    assert outcome.primary_success is True
    assert outcome.result_payload["claim"]["released_at"] is not None
    assert release.call_args.kwargs["released_by_session_id"] == "holder"


def test_operator_release_refuses_when_reviewed_holder_changed(test_db) -> None:
    seed_session(test_db, "new-holder", 1)
    target = make_deploy_serialization_target(1, "yoke")
    claim = acquire(test_db, target, "new-holder")

    with pytest.raises(CoordinationClaimChangedError, match="changed after review"):
        operator_release(
            test_db,
            project_id="yoke",
            key="DEPLOY:yoke",
            operator_reason="old driver is gone",
            expected_claim_id=claim.id - 1,
            expected_holder_session_id="old-holder",
            operator_actor_id=2,
        )

    current = active_claim(test_db, target)
    assert current is not None
    assert current.id == claim.id
    assert current.session_id == "new-holder"
