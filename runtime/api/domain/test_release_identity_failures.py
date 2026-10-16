"""Refused release records and immutable consumer proof stay visible."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

from runtime.api.tools import require_platform_consumer_compatibility as gate
from runtime.api.tools.platform_consumer_dispatch_ref import bound_dispatch_ref
from yoke_core.domain.deployment_failure_trace import (
    FailedJob,
    RunSnapshot,
    github_run_ref,
    walk_failure_chain,
)


def test_bridge_exits_with_the_named_record_refusal(tmp_path):
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load(
        (root / ".github/workflows/platform-release-bridge.yml").read_text()
    )
    step = next(
        step
        for step in workflow["jobs"]["dispatch-platform-release"]["steps"]
        if step.get("name") == "Record the pin commit this release produced"
    )
    runner = tmp_path / "python3"
    runner.write_text(
        "#!/bin/sh\nprintf '%s\\n' 'commit_attributed_to_item: record refused' >&2\nexit 7\n"
    )
    runner.chmod(0o755)
    env = dict(
        os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}", RUNNER_TEMP=str(tmp_path)
    )
    result = subprocess.run(
        ["bash", "-e", "-c", step["run"]], env=env, text=True, capture_output=True
    )
    assert result.returncode == 7
    assert "commit_attributed_to_item" in result.stderr
    assert "Do not repeat deployment" in result.stdout


def test_stale_pair_stops_at_the_refusal_instead_of_following_green_proof():
    origin = github_run_ref("owner/product", "1")
    diagnostic = "stale pair: main moved past the bound commit — https://github.com/owner/consumer/actions/runs/2 proved another commit"
    inspected = []

    def inspect(ref):
        inspected.append(ref)
        assert ref == origin
        return RunSnapshot(
            ref,
            (
                FailedJob(
                    "3",
                    "consumer proof",
                    diagnostic + "\n##[error]Process completed with exit code 1.",
                ),
            ),
        )

    result = walk_failure_chain(
        origin, inspect_run=inspect, resolve_job=lambda *_a: pytest.fail("no relay")
    )
    assert result["complete"]
    assert result["terminal_error"] == diagnostic
    assert inspected == [origin]


@pytest.mark.parametrize(
    "receipt", ["unreadable", '{"success":true,"result":{"sha":"wrong"}}']
)
def test_unverified_dispatch_tag_never_dispatches(monkeypatch, receipt):
    calls = []

    def run(argv, **_kwargs):
        calls.append(argv)
        return 0, receipt, ""

    ref, error = bound_dispatch_ref(
        run, repo="owner/consumer", project="consumer", sha="b" * 40, timeout=1
    )
    assert not ref and "consumer_dispatch_ref_unverified" in error
    assert len(calls) == 1 and calls[0][1:3] == ["dispatch-tag", "ensure"]


def test_moved_trunk_cannot_change_the_consumer_workflow_commit(monkeypatch):
    consumer = "b" * 40
    refs = {}
    calls = []

    def run(argv, **_kwargs):
        calls.append(argv)
        if argv[1:3] == ["dispatch-tag", "ensure"]:
            refs[argv[4]] = argv[5]
            refs["main"] = "c" * 40
            result = {"repo": argv[3], "tag": argv[4], "sha": argv[5]}
            return 0, json.dumps({"success": True, "result": result}), ""
        ref = argv[argv.index("--ref") + 1]
        assert refs[ref] == consumer
        return 0, "42\n", ""

    monkeypatch.setattr(gate, "_yoke", run)
    assert gate.dispatch("a" * 40, consumer) == ("42", "")
    assert len(calls) == 2


def test_refused_dispatch_tag_names_recovery_and_never_dispatches(monkeypatch):
    calls = []

    def run(argv, **_kwargs):
        calls.append(argv)
        return 1, "", "function_version_skew: next-release"

    monkeypatch.setattr(gate, "_yoke", run)
    run_id, error = gate.dispatch("a" * 40, "b" * 40)
    assert not run_id and "consumer_dispatch_ref_unavailable" in error
    assert "function_version_skew" in error and "retry this exact pair" in error
    assert len(calls) == 1


def test_dispatch_tag_refusal_preserves_the_server_reason():
    ref, error = bound_dispatch_ref(
        lambda *_a, **_k: (1, "", "dispatch_tag_conflict: tag names another commit"),
        repo="owner/consumer",
        project="consumer",
        sha="b" * 40,
        timeout=1,
    )
    assert not ref and "dispatch_tag_conflict" in error
    assert "retry this exact pair" in error


def test_landing_git_execution_failure_names_the_recovery(monkeypatch):
    from yoke_core.domain import merge_landing_proof as proof

    def unreadable(*_args):
        raise OSError("checkout unavailable")

    monkeypatch.setattr(proof.git, "ancestry", unreadable)
    with pytest.raises(
        proof.LandingUnverified,
        match="merge_landing_git_failed.*governed merge command",
    ):
        proof.verified_landing_identity("/repo", "c" * 40, "a" * 40, "b" * 40)


def test_reported_pr_merge_outside_target_refuses(monkeypatch):
    from yoke_core.domain import merge_landing_proof as proof

    readings = iter(((True, ""), (False, "")))
    monkeypatch.setattr(proof.git, "ancestry", lambda *_a: next(readings))
    with pytest.raises(
        proof.LandingUnverified, match="merge_landing_identity_mismatch"
    ):
        proof.verified_landing_identity("/repo", "c" * 40, "a" * 40, "b" * 40)
