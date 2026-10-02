"""Source export and drift detection for installed installer campaign plans."""

import copy
import json

from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
)
from yoke_core.tools.installer_campaign_plan import compare_plan, main
from runtime.api.domain.test_qa_release_channel_target import _target


def _plan(environment="prod"):
    target = _target(environment)
    return {
        "id": 42,
        "target_environment": environment,
        "execution_target": target,
        "cases": installer_campaign_cases_for_target(target),
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


def test_export_uses_bound_environment_and_check_refuses_drift(tmp_path, capsys):
    plan = _plan("stage")
    expected = copy.deepcopy(plan["cases"])
    plan["cases"][0]["instructions"] = "stale"
    snapshot = tmp_path / "plan.json"
    exported = tmp_path / "cases.json"
    snapshot.write_text(json.dumps({"success": True, "result": {"plan": plan}}))
    args = ["--plan-file", str(snapshot), "--cases-file", str(exported)]
    assert main(args + ["--check"]) == 1
    assert json.loads(exported.read_text()) == expected
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
