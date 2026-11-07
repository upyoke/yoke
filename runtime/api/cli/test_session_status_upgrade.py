"""A new client refuses incomplete server projections, even empty pages."""

import pytest

from yoke_cli.commands.adapters.sessions_read import validate_session_status
from yoke_contracts.api.function_call import FunctionCallResponse


@pytest.mark.parametrize("missing", ["status", "active_at", "reason"])
def test_old_server_state_names_the_upgrade_instead_of_guessing(missing):
    state = {"status": "waiting", "active_at": None, "reason": "Waiting."}
    del state[missing]
    response = FunctionCallResponse(
        success=True, function="sessions.list", version="v1", request_id="test",
        result={"fields": ["status", "active_at", "reason"], "rows": [{"session_state": state}]},
    )
    refused = validate_session_status(response, None)
    assert not refused.success
    assert refused.error.code == "function_version_skew"
    assert "Refresh after the server upgrade" in refused.error.message


def test_an_empty_old_server_page_still_requires_the_new_fields():
    response = FunctionCallResponse(
        success=True, function="sessions.list", version="v1", request_id="test",
        result={"fields": ["presence", "activity", "intent"], "rows": []},
    )
    assert not validate_session_status(response, None).success
