"""New read fields refuse with a named serving floor on an older server."""

from yoke_cli.commands.adapters.deployment_reads import _require_projection
from yoke_cli.commands.adapters.session_control_launch_list import (
    _item_filter_floor,
)
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError


def _refused(code: str, message: str) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function="f",
        version="v1",
        error=FunctionError(code=code, message=message),
    )


def test_older_server_refusing_member_fields_names_the_floor() -> None:
    validate = _require_projection(None, requested=["member_items"])
    response = validate(_refused("invalid_field", "invalid field 'member_items'"), None)
    assert response.error.code == "deployment_run_read_projection_unavailable"
    assert "member_items" in response.error.message
    assert "Serving floor" in response.error.message


def test_ordinary_invalid_field_keeps_its_own_refusal() -> None:
    validate = _require_projection(None, requested=["nonesuch"])
    refused = _refused("invalid_field", "invalid field 'nonesuch'")
    assert validate(refused, None) is refused


def test_older_server_refusing_item_filter_names_the_floor() -> None:
    response = _item_filter_floor(
        _refused("payload_invalid", "item\n  Extra inputs are not permitted"), None
    )
    assert response.error.code == "launch_item_filter_unavailable"
    assert "Serving floor" in response.error.message
