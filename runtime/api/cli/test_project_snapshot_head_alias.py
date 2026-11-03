"""Reusing integration content must still send the lane's HEAD identity."""

from yoke_cli.commands.adapters import project_snapshot_incremental as sync
from yoke_cli.project_snapshot.sync_refs import SyncPlan, SyncRef
from yoke_contracts.api.function_call import FunctionCallResponse


def test_same_commit_sync_records_head_before_aliasing_integration(tmp_path, monkeypatch):
    calls = []
    head = "a" * 40

    def record(**kwargs):
        ref = kwargs["ref"]
        calls.append(ref.label)
        return FunctionCallResponse(
            success=True, function="project.snapshot.sync", version="v1",
            result={"snapshots": [{"ref": ref.label, "commit_sha": head}]},
        )

    monkeypatch.setattr(sync, "_sync_ref", record)
    monkeypatch.setattr(sync, "active_transport_is_https", lambda: True)
    result = sync.sync_snapshots(
        project="external", plan=SyncPlan(tmp_path, SyncRef("HEAD", head), SyncRef("main", head)),
        contents=True, hook_mode=False, session_id=None, timeout_s=None,
    )

    assert result.success
    assert calls == ["HEAD"]
    assert [row["ref"] for row in result.result["snapshots"]] == ["HEAD", "main"]
