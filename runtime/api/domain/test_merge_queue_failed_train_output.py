"""Failed-train diagnosis survives the merge CLI and watcher boundaries."""

import json

import pytest

from runtime.api.merge_queue_landing_test_helpers import LANE_SHA, ctx
from yoke_core.domain import standalone_item_merge_cli as cli
from yoke_core.domain.merge_queue_failed_train import unchanged_failed_train_refusal
from yoke_core.domain.merge_queue_landing_outcome import QueueLandingOutcome
from yoke_core.engines.merge_worktree_pr_train_run import TrainRun
from yoke_core.tools.watch_merge import classify_merge_line
from yoke_core.tools._watch_throttle import LineClass


@pytest.mark.parametrize("as_json", [False, True])
def test_cli_and_watcher_keep_failed_run_and_recovery(
    monkeypatch, capsys, tmp_path, as_json
):
    public_ref = f"ITEM-{42}"
    train_sha, base_sha = "4" * 40, "3" * 40
    url = "https://github.com/example/project/actions/runs/123"
    refusal = unchanged_failed_train_refusal(
        ctx(),
        "42",
        lane_head=LANE_SHA,
        base_branch="main",
        train=TrainRun(conclusion="failure", head_sha=train_sha, url=url),
        parents=[base_sha, LANE_SHA],
        base_sha=base_sha,
    )
    monkeypatch.setattr(
        cli,
        "_resolve_item",
        lambda *_a: (
            {
                "public_ref": public_ref,
                "status": "reviewing-implementation",
                "workflow": {"id": "dash"},
                "project": {"slug": "example"},
            },
            "",
        ),
    )
    monkeypatch.setattr(cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(cli, "_resolve_checkout", lambda *_a: (tmp_path, "main"))
    monkeypatch.setattr(cli, "_ensure_usable_cwd", lambda *_a: None)
    monkeypatch.setattr(cli.stale_lane, "stale_unlanded_work", lambda **_k: "")
    monkeypatch.setattr(cli.landed, "landed_lane", lambda **_k: None)
    monkeypatch.setattr(cli.recovery, "branch_needs_receipt", lambda *_a: False)
    monkeypatch.setattr(
        cli.verify,
        "verify_and_land",
        lambda *_a, **_k: (
            QueueLandingOutcome(ok=False, exit_code=1, pr_num="42", error=refusal),
            "",
        ),
    )
    args = [public_ref, "--result", "diagnostic", "--verification", "fixture"]
    assert cli.run(args + (["--json"] if as_json else [])) == 1
    output = capsys.readouterr()
    if as_json:
        assert json.loads(output.out)["error"] == f"{public_ref}: {refusal}"
    else:
        line = output.err.splitlines()[0]
        assert line == f"Error: {public_ref}: {refusal}"
        assert classify_merge_line(line).cls == LineClass.URGENT
    assert all(value in output.err for value in (url, train_sha, LANE_SHA, base_sha))
    assert "correct the actual cause" in output.err
