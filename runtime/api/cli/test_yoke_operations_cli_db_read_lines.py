"""Line-format coverage for the ``yoke db read`` adapter."""

from __future__ import annotations

import pytest

from runtime.api.cli.test_yoke_operations_cli_dispatch import (
    _CAPTURED_REQUESTS,
    _run_capture,
    _stub_dispatch_ok,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def test_db_read_lines_format_emits_shell_consumable_rows() -> None:
    def stub(request: FunctionCallRequest) -> FunctionCallResponse:
        _CAPTURED_REQUESTS.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={
                "columns": ["id", "title", "optional"],
                "rows": [
                    {"id": 1, "title": "Alpha", "optional": None},
                    [2, "Beta", "set"],
                ],
            },
        )

    rc, out, err = _run_capture(
        stub,
        "db",
        "read",
        "SELECT id, title FROM items",
        "--format",
        "lines",
    )

    assert rc == 0
    assert err == ""
    assert out == "1|Alpha|\n2|Beta|set\n"


def test_db_read_json_envelope_rejects_lines_format() -> None:
    rc, _out, err = _run_capture(
        _stub_dispatch_ok,
        "db",
        "read",
        "SELECT 1",
        "--format",
        "lines",
        "--json",
    )

    assert rc == 2
    assert "cannot be combined" in err
    assert not _CAPTURED_REQUESTS
