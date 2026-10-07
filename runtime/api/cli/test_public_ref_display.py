"""Human and JSON receipts share the public response contract."""

import json

from yoke_cli.transport.public_ref_display import emit_response, prepare_human_response
from yoke_contracts.api.function_call import FunctionCallResponse


def response():
    return FunctionCallResponse(
        success=True,
        function="items.get.run",
        version="v1",
        result={
            "item_id": 99,
            "public_ref": "APP-7",
            "requirement_id": 11,
            "nested": {"owner_item_id": 99},
        },
    )


def test_old_server_receipt_omits_unavailable_optional_refs():
    assert prepare_human_response(response()).result == {
        "public_ref": "APP-7",
        "requirement_id": 11,
        "nested": {},
    }


def test_json_and_human_output_do_not_leak_internal_keys(capsys):
    for json_mode in (True, False):
        assert emit_response(response(), json_mode=json_mode) == 0
        output = capsys.readouterr().out
        parsed = json.loads(output)
        result = parsed["result"] if json_mode else parsed
        assert result == prepare_human_response(response()).result
