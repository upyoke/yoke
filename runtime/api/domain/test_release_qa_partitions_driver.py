from yoke_core.domain import qa_plan_execution, qa_plan_execution_dispatch
from yoke_core.domain.deploy_pipeline_qa_wait import dispatch_until_qa_resolves, AWAITING_SCOPED_QA
from yoke_core.domain.deployment_qa_pending_plans import QaDispatchResult


def test_driver_rechecks_after_fingerprint_change_and_only_runs_commands(monkeypatch):
    cursor = 0.0
    reads = []
    runs = []
    output = []

    def sleep(seconds):
        nonlocal cursor
        cursor += seconds

    def partitions(**scope):
        reads.append(scope)
        return [
            {"state": "free", "kind": "automatic", "key": "command-key"},
            {"state": "free", "kind": "walk", "key": "walk-key"},
            {"state": "free", "kind": "automatic", "key": "manual-command", "wake_path": "manual"},
            {"state": "free", "kind": "walk", "key": "manual-walk", "wake_path": "manual"},
        ]

    monkeypatch.setattr(qa_plan_execution_dispatch, "read_release_partitions", partitions)
    monkeypatch.setattr(
        qa_plan_execution, "execute_plan",
        lambda **scope: runs.append(scope) or {"state": "passed"},
    )
    result = dispatch_until_qa_resolves(
        lambda *args, **kwargs: QaDispatchResult(
            AWAITING_SCOPED_QA, "walk pending", [{"plan": "smoke", "project": "example"}],
        ),
        {"name": "qa"}, run_id="run-1", timeout_seconds=3.0, poll_interval_seconds=1.0,
        fingerprint=lambda: "changed" if cursor >= 2 else "original",
        monotonic=lambda: cursor, sleep=sleep, write=output.append,
    )
    assert result[0] == AWAITING_SCOPED_QA
    assert len(reads) >= 2
    assert [run["partition"] for run in runs] == ["command-key", "command-key"]
    assert sum("--partition walk-key" in line for line in output) == 2
    assert all("--partition manual" not in line for line in output)
