"""CLI dispatch coverage for path-claim coordination evidence."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import FunctionCallResponse


def test_claims_path_coordination_decision_build_dispatches() -> None:
    captured = {}

    def _stub_dispatch(request):
        captured["request"] = request
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={"echo": True},
        )

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}), patch(
        "yoke_core.domain.yoke_function_dispatch.dispatch",
        side_effect=_stub_dispatch,
    ), patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = cli_main([
                "claims", "path", "coordination-decision-build",
                "--item", "YOK-1819",
                "--conflicting-claim", "273",
                "--paths", "runtime/api/cli/foo.py,runtime/api/cli/bar.py",
            ])

    assert rc == 0
    req = captured["request"]
    assert req.function == "claims.path.coordination_decision_build"
    assert req.target.kind == "item"
    assert req.target.item_ref == "YOK-1819"
    assert "candidate_item_id" not in req.payload
    assert req.payload == {
        "conflicting_claim_id": 273,
        "shared_paths": [
            "runtime/api/cli/foo.py", "runtime/api/cli/bar.py",
        ],
    }
