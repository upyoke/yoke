"""Machine expiry disposal and later lifecycle delivery share one clock proof."""

import pytest

from yoke_core.domain import machine_approval_requests as approvals
from yoke_core.domain.decision_request_disposition import (
    dispose_ended_decision_requests,
)


@pytest.fixture()
def conn():
    from runtime.api.domain.decision_request_test_support import (
        decision_request_connection,
    )

    with decision_request_connection() as value:
        yield value


@pytest.mark.parametrize(
    ("context", "expect_converged"),
    (
        ({"expires_at": "2020-01-01T00:05:00Z"}, True),
        ({"ended_at": "2020-01-01T00:00:01Z"}, False),
    ),
)
def test_cleanup_then_delivery_converges_only_on_expiry_evidence(
    conn,
    context: dict,
    expect_converged: bool,
) -> None:
    approvals.apply_machine_approval_lifecycle(
        conn,
        auth_request_id="5b234860-c927-46ab-b19a-9fb36df056aa",
        org_id=1,
        state="pending",
        occurred_at="2020-01-01T00:00:00Z",
        actor_id=5,
        context=context,
    )
    assert dispose_ended_decision_requests(conn)["withdrawn_count"] == 1

    def deliver_expired():
        return approvals.apply_machine_approval_lifecycle(
            conn,
            auth_request_id="5b234860-c927-46ab-b19a-9fb36df056aa",
            org_id=1,
            state="expired",
            occurred_at="2020-01-01T00:06:00Z",
            actor_id=5,
            context={},
        )

    if expect_converged:
        delivered, created, applied = deliver_expired()
        assert (delivered["status"], created, applied) == ("withdrawn", False, False)
    else:
        with pytest.raises(ValueError, match="already withdrawn, not expired"):
            deliver_expired()
