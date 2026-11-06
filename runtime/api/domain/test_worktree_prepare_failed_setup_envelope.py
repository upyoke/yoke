"""Preparation receipts retain setup results when a later lane proof fails."""

from types import SimpleNamespace

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain import worktree_create, worktree_preflight as preflight
from yoke_core.domain.worktree_create import CreateWorktreeResult


def test_failed_lane_preparation_preserves_setup_result(monkeypatch, tmp_path):
    setup = {"status": "failed", "command": "./setup"}
    monkeypatch.setattr(preflight, "resolve_item_branch_and_lane", lambda *_: ("YOK-7", str(tmp_path)))
    monkeypatch.setattr(preflight, "_normalize_repo_root", lambda value: value)
    monkeypatch.setattr(preflight, "claim_work", lambda *_: (True, "held"))
    monkeypatch.setattr(preflight, "activate_path_claims", lambda *_: (True, "", []))
    monkeypatch.setattr(
        preflight, "gate_upstream_for_preparation",
        lambda *_args, **_kwargs: SimpleNamespace(freshness=None, block_kind="", narrative=""),
    )
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        lambda **kwargs: FunctionCallResponse(
            success=True, function=kwargs["function_id"], version="v1",
            result={"item": {"public_ref": "YOK-7", "project": {"slug": "sample"}}},
        ),
    )
    monkeypatch.setattr(
        worktree_create, "create_worktree",
        lambda **_kwargs: CreateWorktreeResult(
            path=str(tmp_path), branch="YOK-7", created=True,
            error="test environment proof failed", setup_command=setup,
        ),
    )

    outcome = preflight.run_preflight(item_id="YOK-7", repo_root=str(tmp_path))

    assert not outcome.ok
    assert outcome.block_kind == "worktree-create-failed"
    assert outcome.setup_command == setup
    assert outcome.to_envelope()["setup_command"] == setup
