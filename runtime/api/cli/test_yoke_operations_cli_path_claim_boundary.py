"""CLI coverage for local production and relayed recording of a boundary proof."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import FunctionCallResponse


def _response(function_id: str, result: dict) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function=function_id,
        version="v1",
        result=result,
    )


def test_boundary_prove_observes_recorded_lane_then_relays_proof(tmp_path):
    lane = tmp_path / "lane"
    lane.mkdir()
    context = {
        "item_id": 7777,
        "project": {"id": 1, "slug": "yoke"},
        "lane": {
            "id": 9,
            "item_id": 7777,
            "branch": "YOK-7777",
            "path": str(lane),
            "commit_sha": "a" * 40,
            "lane_role": "implementation",
            "state": "active",
        },
        "work_claim": {"claim_id": 3, "session_id": "session-1"},
        "claims": [{"claim_id": 8}],
    }
    calls = []

    def _dispatch(*, function_id, target, payload, actor, **_kwargs):
        calls.append((function_id, target, payload, actor))
        if function_id == "claims.path.boundary_context":
            return _response(function_id, {"context": context})
        return _response(
            function_id,
            {
                "item_id": 7777,
                "rung_id": "remote_integration_ref",
                "lane_commit_sha": "a" * 40,
            },
        )

    proof = {"kind": "path_claim_boundary_local_v1"}
    out, err = io.StringIO(), io.StringIO()
    with (
        patch.dict("os.environ", {"YOKE_SESSION_ID": "session-1"}),
        patch("yoke_cli.commands.adapters.claims_path_flow.ensure_handlers_loaded"),
        patch(
            "yoke_cli.commands.adapters.claims_path_flow.call_dispatcher",
            side_effect=_dispatch,
        ),
        patch(
            "yoke_cli.commands.adapters.claims_path_flow.sync_local_snapshot_for_write",
            return_value={"status": "ok"},
        ) as sync,
        patch(
            "yoke_core.domain.path_claim_boundary_gate_proof.build_local_boundary_proof",
            return_value=proof,
        ) as build,
        redirect_stdout(out),
        redirect_stderr(err),
    ):
        rc = cli_main(
            [
                "claims",
                "path",
                "boundary-prove",
                "--item",
                "YOK-7777",
            ]
        )
    assert rc == 0, err.getvalue()
    assert [call[0] for call in calls] == [
        "claims.path.boundary_context",
        "claims.path.boundary_context",
        "claims.path.boundary_prove",
    ]
    assert calls[-1][1].public_ref == "YOK-7777"
    assert calls[-1][2] == {"proof": proof}
    sync.assert_called_once_with(
        project="yoke",
        repo_root=str(lane),
        integration_target=None,
        session_id=None,
        head_only=True,
    )
    build.assert_called_once_with(context, str(lane))
    assert "boundary-proof-recorded|item|remote_integration_ref" in out.getvalue()
