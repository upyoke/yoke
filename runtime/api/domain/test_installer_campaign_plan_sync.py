"""Source export and drift detection for installed installer campaign plans."""

from runtime.api.domain.installer_campaign_plan_sync_test_support import (
    source_checkout as source_checkout,
)


import copy
import json
import subprocess

import pytest

from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
)
from yoke_core.tools import installer_campaign_plan as sync
from yoke_core.tools.installer_campaign_plan import compare_plan, main
from runtime.api.domain.qa_release_channel_target_test_support import _target


def _plan(environment="prod"):
    target = _target(environment)
    return {
        "id": 42,
        "slug": "installer-campaign",
        "target_environment": environment,
        "execution_target": target,
        "cases": installer_campaign_cases_for_target(
            target, primary_machine="primary-test", joining_machine="joining-test"
        ),
    }


def test_comparison_ignores_storage_and_history_fields():
    plan = _plan()
    for case in plan["cases"]:
        case.update(id=99, method_name="Display name", proofs=[{"run_id": 7}])
        case.setdefault("entry_surface", None)
        case.setdefault("required_completion", None)
    _, report = compare_plan(plan)
    assert report["matches_source"]
    assert report["differences"] == []


def test_comparison_reports_nested_drift_and_missing_and_extra_cases():
    plan = _plan()
    changed = plan["cases"][2]
    changed["method_config"]["obsolete_step"] = {"target_environment": "prod"}
    removed = plan["cases"].pop()
    plan["cases"].append({**removed, "case_key": "obsolete-case"})
    _, report = compare_plan(plan)
    assert not report["matches_source"]
    assert {"case_key": changed["case_key"], "fields": ["method_config"]} in report[
        "differences"
    ]
    assert {"case_key": removed["case_key"], "change": "added"} in report["differences"]
    assert {"case_key": "obsolete-case", "change": "removed"} in report["differences"]


def test_export_uses_bound_environment_and_check_refuses_drift(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr(sync, "export_source_revision", lambda: "a" * 40)
    plan = _plan("stage")
    expected = copy.deepcopy(plan["cases"])
    plan["cases"][0]["instructions"] = "stale"
    snapshot = tmp_path / "plan.json"
    exported = tmp_path / "cases.json"
    snapshot.write_text(json.dumps({"success": True, "result": {"plan": plan}}))
    args = ["--plan-file", str(snapshot), "--cases-file", str(exported)]
    assert main(args + ["--check"]) == 1
    assert json.loads(exported.read_text()) == {
        "source_revision": "a" * 40,
        "cases": expected,
    }
    assert "installer_campaign_plan_source_drift" in capsys.readouterr().err
    plan["cases"] = expected
    snapshot.write_text(json.dumps({"success": True, "result": {"plan": plan}}))
    assert main(["--plan-file", str(snapshot), "--check"]) == 0


def test_invalid_snapshot_teaches_recovery_without_traceback(tmp_path, capsys):
    snapshot = tmp_path / "plan.json"
    snapshot.write_text(json.dumps({"success": False}))
    assert main(["--plan-file", str(snapshot)]) == 2
    error = capsys.readouterr().err
    assert "installer_campaign_plan_snapshot_invalid" in error
    assert "yoke qa plan get" in error


def test_comparison_reads_a_stored_baseline_state_as_the_source_declares_it():
    plan = _plan()
    for case in plan["cases"]:
        if case["host_baselines"]:
            case["starting_state"] = "baseline"
    _, report = compare_plan(plan)
    assert report["differences"] == []
    plan["cases"][0]["starting_state"] = "as_is"
    _, report = compare_plan(plan)
    assert report["differences"] == [
        {"case_key": plan["cases"][0]["case_key"], "fields": ["starting_state"]}
    ]


def test_export_refuses_unmerged_commit_preserves_output_and_accepts_after_merge(
    source_checkout,
    tmp_path,
    capsys,
):
    root, git = source_checkout
    assert git(root, "checkout", "-b", "case-change").returncode == 0
    (root / "cases.json").write_text('["new"]\n')
    assert git(root, "commit", "-am", "Change cases").returncode == 0
    revision = git(root, "rev-parse", "HEAD").stdout.strip()
    snapshot, output = tmp_path / "plan.json", tmp_path / "export.json"
    snapshot.write_text(json.dumps({"success": True, "result": {"plan": _plan()}}))
    output.write_text("previous export\n")
    args = ["--plan-file", str(snapshot), "--cases-file", str(output)]
    assert main(args) == 2
    assert output.read_text() == "previous export\n"
    error = capsys.readouterr().err
    assert "qa_plan_source_unmerged_or_unverified" in error
    assert revision in error and "sync after merge" in error
    assert main(["--plan-file", str(snapshot), "--check"]) == 0
    capsys.readouterr()
    assert git(root, "push", "origin", "HEAD:stable").returncode == 0
    assert main(args) == 0
    assert json.loads(output.read_text()) == {
        "source_revision": revision,
        "cases": _plan()["cases"],
    }
    assert json.loads(capsys.readouterr().out)["source_revision"] == revision


def test_export_refuses_dirty_source_and_unreadable_remote(source_checkout):
    root, git = source_checkout
    (root / "cases.json").write_text("dirty\n")
    with pytest.raises(ValueError, match="uncommitted changes.*sync after merge"):
        sync.export_source_revision()
    assert git(root, "add", "cases.json").returncode == 0
    assert git(root, "commit", "-m", "Update cases").returncode == 0
    assert (
        git(root, "remote", "set-url", "origin", str(root / "missing")).returncode == 0
    )
    with pytest.raises(ValueError, match="unmerged_or_unverified.*sync after merge"):
        sync.export_source_revision()


def test_export_uses_remote_tracking_default_branch_when_several_are_configured(
    source_checkout, tmp_path, capsys
):
    root, git = source_checkout
    added = git(root, "remote", "add", "archive", str(root.parent / "archive"))
    assert added.returncode == 0
    revision = git(root, "rev-parse", "HEAD").stdout.strip()
    snapshot, output = tmp_path / "plan.json", tmp_path / "export.json"
    snapshot.write_text(json.dumps({"success": True, "result": {"plan": _plan()}}))
    assert main(["--plan-file", str(snapshot), "--cases-file", str(output)]) == 0
    exported = json.loads(output.read_text())
    assert exported["source_revision"] == revision
    assert exported["cases"] == _plan()["cases"]
    assert json.loads(capsys.readouterr().out)["source_revision"] == revision


def test_export_timeout_has_named_recovery(source_checkout, monkeypatch):
    def timeout(*args):
        raise subprocess.TimeoutExpired("git fetch", 30)

    monkeypatch.setattr(sync.source_git, "fetch_branch", timeout)
    with pytest.raises(sync.SourceSyncRefused, match="sync after merge"):
        sync.export_source_revision()
