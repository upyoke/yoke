from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.actor_permissions import PERM_ITEMS_WRITE
from yoke_core.domain.function_authz_scope import PROJECT, classify
from yoke_core.domain.handlers.test_machine_case import (
    _record_machine_case_result,
)
from yoke_core.domain.machine_qa_case_execution import (
    MachineCaseDispatchError,
    execute_materialized_machine_case,
)
from yoke_core.domain.machine_qa_execution import MachineCaseResult
from yoke_core.domain.migrations.installer_campaign_plan_rows import apply
from yoke_core.domain.qa_artifact_handle import local_handle, parse_handle
from yoke_core.domain.qa_case_execution_context import (
    get_case_execution_context,
)
from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
)
from yoke_core.domain.ssh_mac_terminal_capture import verify_terminal_bridge
from yoke_core.domain.ssh_mac_host_control import SshMacHostControl


def test_terminal_bridge_verification_exercises_all_control_surfaces() -> None:
    commands = []

    def run(command: str, **_kwargs):
        commands.append(command)
        stdout = (
            "yoke-terminal-bridge-ready"
            if command.startswith("tmux capture-pane")
            else ""
        )
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    ok, evidence, error_code = verify_terminal_bridge(run)

    assert ok is True
    assert error_code is None
    assert evidence == {
        "pty": True,
        "terminal_control": True,
        "screenshot_capture": True,
        "sample_artifact_retained": False,
    }
    assert any("/usr/bin/osascript" in command for command in commands)
    assert any("/usr/sbin/screencapture" in command for command in commands)
    assert any(command.startswith("rm -f ") for command in commands)
    assert any(command.startswith("tmux kill-session") for command in commands)


def test_required_terminal_completion_has_distinct_not_reached_outcome(
    tmp_path: Path,
    monkeypatch,
) -> None:
    control = SshMacHostControl.__new__(SshMacHostControl)
    control.material = SimpleNamespace(
        settings={"resource_name": "mac-mini-lab"},
    )
    control._run = lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0,
        stdout="",
        stderr="",
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_host_control.machine_config.yoke_home",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_host_control.wait_for_text",
        lambda *_args, **_kwargs: None,
    )

    result = control.run_terminal_case(
        entry_surface="yoke onboard",
        required_completion="review",
        steps=[{"key": "review", "expect": "Review"}],
        capture_checkpoints=[],
    )

    assert result.ok is False
    assert result.error_code == "terminal_completion_not_reached"


def test_machine_leaf_dispatches_only_the_targeted_requirement() -> None:
    case = {
        "requirement_id": 41,
        "executor_id": "host_control",
        "method_id": "machine-state-check",
        "project": "yoke",
        "method_config": {"assertions": [{"argv": ["/usr/bin/true"]}]},
        "entry_surface": None,
        "required_completion": None,
    }
    response = SimpleNamespace(
        success=True,
        result={
            "requirement_id": 41,
            "executor_id": "host_control",
            "verdict": "pass",
        },
        error=None,
    )
    with mock.patch(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        return_value=response,
    ) as dispatch:
        result = execute_materialized_machine_case(case)

    assert result["requirement_id"] == 41
    request = dispatch.call_args.kwargs
    assert request["function_id"] == "test_machine.case_execute"
    assert request["target"].qa_requirement_id == 41
    assert request["payload"] == {}


def test_machine_case_execution_is_project_write_authorized() -> None:
    spec = classify(
        "test_machine.case_execute",
        side_effects=True,
        project_permission=None,
    )
    assert (spec.scope, spec.permission_key) == (PROJECT, PERM_ITEMS_WRITE)


def test_machine_leaf_refuses_non_machine_executor() -> None:
    with mock.patch(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
    ) as dispatch:
        try:
            execute_materialized_machine_case({
                "requirement_id": 41,
                "executor_id": "worktree_run",
                "method_id": "command",
            })
        except MachineCaseDispatchError as exc:
            assert "not a registered Machine QA case" in str(exc)
        else:
            raise AssertionError("non-Machine executor was dispatched")
    dispatch.assert_not_called()


def test_machine_result_records_exact_outcome_and_canonical_artifacts(
    test_db,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    apply(test_db)
    insert_item(
        test_db,
        id=42,
        title="Verify installer campaign",
        workflow_id="issue",
        status="implementing",
    )
    plan_id = int(test_db.execute(
        "SELECT id FROM qa_plans WHERE slug='installer-campaign'"
    ).fetchone()[0])
    attach_plan_to_item(
        test_db,
        plan_id=plan_id,
        item_id=42,
        transition_id="reviewing-implementation",
    )
    materialized = materialize_for_item(
        test_db,
        item_id=42,
        transition_id="reviewing-implementation",
    )
    requirement_id = int(test_db.execute(
        "SELECT id FROM qa_requirements "
        "WHERE id=ANY(%s) AND plan_case_key='path-001'",
        (materialized["created_requirement_ids"],),
    ).fetchone()[0])
    case = get_case_execution_context(
        test_db,
        requirement_id=requirement_id,
    )
    screenshot = tmp_path / "welcome.png"
    screenshot.write_bytes(b"png-evidence")
    result = MachineCaseResult(
        case_outcome="needs_review",
        verdict="pending",
        capture_degraded_reason=None,
        evidence={
            "machine": "mac-mini-lab",
            "steps": [{
                "key": "welcome",
                "transcript": "Your operating system for software delivery",
                "artifact_handle": local_handle(
                    str(screenshot.resolve()),
                    "image/png",
                ),
            }],
        },
    )

    recorded = _record_machine_case_result(
        test_db,
        case=case,
        result=result,
        duration_ms=12,
    )

    run = test_db.execute(
        "SELECT verdict,case_outcome,raw_result FROM qa_runs WHERE id=%s",
        (recorded["run_id"],),
    ).fetchone()
    assert (run["verdict"], run["case_outcome"]) == (
        "inconclusive",
        "needs_review",
    )
    assert json.loads(run["raw_result"])["evidence"]["machine"] == "mac-mini-lab"
    artifacts = test_db.execute(
        "SELECT artifact_type,artifact_handle FROM qa_artifacts "
        "WHERE qa_run_id=%s ORDER BY artifact_type",
        (recorded["run_id"],),
    ).fetchall()
    assert [row["artifact_type"] for row in artifacts] == [
        "machine_evidence",
        "terminal_screenshot",
    ]
    handles = [parse_handle(row["artifact_handle"]) for row in artifacts]
    assert all(handle["backend"] == "local" for handle in handles)
    assert all(Path(handle["path"]).is_file() for handle in handles)
    assert screenshot.exists() is False
    assert recorded["evidence_count"] == 2
