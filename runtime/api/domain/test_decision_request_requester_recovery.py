"""Invalid requesting sessions name concrete registration recovery commands."""

from unittest.mock import Mock

import pytest

from yoke_core.domain.decision_request_question_filing import validate_requester


@pytest.mark.parametrize("row", [None, (1, "ended", None), (1, None, "terminated")])
def test_unavailable_requester_names_registration_recovery(row):
    conn = Mock()
    conn.execute.return_value.fetchone.return_value = row

    with pytest.raises(ValueError, match="operator_question_invalid") as exc:
        validate_requester(conn, "worker", None, "worker:choose", {})

    message = str(exc.value)
    assert "requesting session must exist and be live" in message
    assert "`yoke sessions identity`" in message
    assert "`yoke sessions begin`" in message
    assert "--help" in message
    assert "retry `yoke decision-requests ask`" in message
    assert "`yoke doctor run --session`" in message
