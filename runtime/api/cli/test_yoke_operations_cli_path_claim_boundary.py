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

    proof = {"kind": "path_claim_boundary_local_v1"}

    def _dispatch(*, function_id, target, payload, actor, **kwargs):
        calls.append((function_id, target, payload, actor, kwargs))
        if function_id == "claims.path.boundary_context":
            return _response(function_id, {"context": context})
        if function_id == "claims.path.boundary_observe":
            return _response(function_id, {"proof": proof})
        return _response(
            function_id,
            {
                "item_id": 7777,
                "rung_id": "remote_integration_ref",
                "lane_commit_sha": "a" * 40,
            },
        )

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
        "claims.path.boundary_observe",
        "claims.path.boundary_prove",
    ]
    assert calls[-2][1].kind == "global"
    assert calls[-2][2] == {"context": context, "repo_path": str(lane)}
    assert calls[-2][4] == {"local_only": True}
    assert calls[-1][1].public_ref == "YOK-7777"
    assert calls[-1][2] == {"proof": proof}
    sync.assert_called_once_with(
        project="yoke",
        repo_root=str(lane),
        integration_target=None,
        session_id=None,
        head_only=True,
        timeout_s=None,
        retry_command="yoke claims path boundary-prove --item YOK-7777",
    )
    assert "boundary-proof-recorded|item|remote_integration_ref" in out.getvalue()


def test_boundary_prove_timeout_retries_original_command(tmp_path):
    from yoke_cli.commands.adapters.project_snapshot import HOOK_WRITE_TIMEOUT_S
    from yoke_contracts.api.function_call import FunctionError
    from runtime.api.cli.project_snapshot_cli_test_helpers import make_repo

    lane = make_repo(tmp_path)
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
    snapshot_calls = []

    def _flow_dispatch(*, function_id, target, payload, actor, **kwargs):
        if function_id == "claims.path.boundary_context":
            return _response(function_id, {"context": context})
        raise AssertionError(f"unexpected flow dispatch {function_id}")

    def _snapshot_dispatch(**kwargs):
        snapshot_calls.append(kwargs)
        return FunctionCallResponse(
            success=False,
            function="project.snapshot.sync",
            version="v1",
            error=FunctionError(
                code="https_transport_failed",
                message="HTTPS function relay response exceeded the time limit",
            ),
        )

    out, err = io.StringIO(), io.StringIO()
    with (
        patch.dict("os.environ", {"YOKE_SESSION_ID": "session-1"}),
        patch("yoke_cli.commands.adapters.claims_path_flow.ensure_handlers_loaded"),
        patch(
            "yoke_cli.commands.adapters.project_snapshot.ensure_handlers_loaded",
        ),
        patch(
            "yoke_cli.commands.adapters.claims_path_flow.call_dispatcher",
            side_effect=_flow_dispatch,
        ),
        patch(
            "yoke_cli.commands.adapters.project_snapshot.call_dispatcher",
            side_effect=_snapshot_dispatch,
        ),
        redirect_stdout(out),
        redirect_stderr(err),
    ):
        rc = cli_main(["claims", "path", "boundary-prove", "--item", "YOK-7777"])
    assert rc == 1
    assert snapshot_calls
    assert snapshot_calls[0]["timeout_s"] is None
    assert snapshot_calls[0]["timeout_s"] is not HOOK_WRITE_TIMEOUT_S
    refusal = err.getvalue()
    assert "exceeded the time limit" in refusal
    assert "yoke claims path boundary-prove --item YOK-7777" in refusal
    assert "yoke project snapshot sync" not in refusal
