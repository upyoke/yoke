"""A refused real uninstall preserves host custody until the same owner's retry."""

import contextlib
import io
import subprocess
from types import SimpleNamespace

import pytest

from runtime.api.cli import test_project_uninstall_owned_cleanup as install_support
from runtime.api.cli import (
    test_project_uninstall_registration_only as registration_support,
)
from runtime.api.domain import test_qa_fixture_project_disposal as disposal_support
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from yoke_cli.commands.adapters.install import project_uninstall
from yoke_contracts.qa_mission_scratch import mission_scratch_path
from yoke_core.domain import (
    agent_mission_project_disposal,
    agent_mission_walk_cli,
    machine_qa_mission_walk,
    qa_composed_dispatch,
)
from yoke_core.domain.agent_mission_project_disposal import (
    FUNCTION_ID,
    handle_mission_project_disposal,
)
from yoke_core.domain.agent_mission_recording import handle_agent_mission_access
from yoke_core.domain.coordination_claims import get_claim
from yoke_core.domain.db_helpers import utc_now, instant_parameter
from yoke_core.domain.handlers.qa_artifact_add import handle_qa_artifact_add
from yoke_core.domain.qa_plan_execution_state import lock_plan_execution


installed = install_support.installed
registered = registration_support.registered


@pytest.fixture(params=["installed", "registered"])
def disposable_checkout(request):
    if request.param == "installed":
        return request.getfixturevalue("installed")
    root, config = request.getfixturevalue("registered")
    return root, None, config


walking_mission = disposal_support.walking_mission
removed_mission = disposal_support.removed_mission
item_close_shares_the_fixture_connection = (
    disposal_support.item_close_shares_the_fixture_connection
)


@pytest.mark.parametrize("receipt_failure", [False, True])
def test_active_walk_retry(
    test_db, disposable_checkout, walking_mission, monkeypatch, capsys, receipt_failure
):
    _assert_owned_retry(
        test_db,
        disposable_checkout,
        walking_mission,
        monkeypatch,
        capsys,
        receipt_failure,
        cleanup=False,
    )


@pytest.mark.parametrize("receipt_failure", [False, True])
@pytest.mark.parametrize(
    "removed_mission", ["removed", "failed", "cancelled"], indirect=True
)
def test_ended_deployment_cleanup_retry(
    test_db, disposable_checkout, removed_mission, monkeypatch, capsys, receipt_failure
):
    _assert_owned_retry(
        test_db,
        disposable_checkout,
        removed_mission,
        monkeypatch,
        capsys,
        receipt_failure,
        cleanup=True,
    )


def _assert_owned_retry(
    test_db, installed, subject, monkeypatch, capsys, receipt_failure, *, cleanup
):
    if cleanup:
        subject, _, original = subject
        acquired = handle_agent_mission_access(subject)
        assert acquired.primary_success, acquired.error
        contract = acquired.result_payload["execution"]
    else:
        access = handle_agent_mission_access(
            subject.model_copy(update={"function": "test_machine.mission.access"})
        )
        assert access.primary_success, access.error
        contract = access.result_payload["execution"]
        original = contract
    root, _, config = installed
    disposal_support._project(
        test_db, 7, "cedar", instant_parameter(test_db, utc_now())
    )
    from yoke_core.domain.actor_role_grants import grant_actor_project_role

    grant_actor_project_role(
        test_db, actor_id=int(subject.actor.actor_id), project_id=7, role_name="owner"
    )
    test_db.commit()
    had_manifest = (root / ".yoke/install-manifest.json").exists()
    dirty = root / "uv.lock"
    dirty.write_text("mission-owned fixture\n")
    scratch = mission_scratch_path(subject.payload["execution_id"])
    host = FakeHostControl()
    host.existing_paths.add(scratch + "/staged-token")
    restored, uninstalls = [], []
    first_attempt = True

    class Host:
        home = host.home
        shell = host.shell
        xdg_bin_home = None

        def read_text(self, path):
            return config.read_text() if path.endswith("/.yoke/config.json") else None

        def run_command(self, argv, **kwargs):
            if argv[1:3] == ["project", "uninstall"]:
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = project_uninstall([*argv[3:], "--config", str(config)])
                uninstalls.append((code, out.getvalue(), err.getvalue()))
                return subprocess.CompletedProcess(
                    argv, code, out.getvalue(), err.getvalue()
                )
            if argv[0] == "/usr/bin/git":
                return subprocess.run(argv, capture_output=True, text=True, **kwargs)
            return host.run_command(argv, **kwargs)

    def restore(name):
        assert not dirty.exists()
        assert not (root / ".yoke/install-manifest.json").exists()
        assert str(root) not in config.read_text()
        assert test_db.execute("SELECT retired_at FROM projects WHERE id=7").fetchone()[
            0
        ]
        restored.append(name)
        return SimpleNamespace(ok=True, error_code=None, evidence={})

    monkeypatch.setattr(
        machine_qa_mission_walk,
        "_execution",
        lambda c: SimpleNamespace(
            control=Host(), material=SimpleNamespace(secrets={}), reach_baseline=restore
        ),
    )

    def resolve(parsed, *, prog):
        parsed.cleanup_lease = cleanup
        return contract

    monkeypatch.setattr(agent_mission_walk_cli, "resolve_mission_contract", resolve)
    handlers = {
        FUNCTION_ID: handle_mission_project_disposal,
        "test_machine.mission.access": handle_agent_mission_access,
        "qa.artifact.add": handle_qa_artifact_add,
    }
    sent = []
    record_receipt = agent_mission_project_disposal._record_receipt

    def record(*args, **kwargs):
        if first_attempt and receipt_failure:
            raise ValueError(
                "mission_project_disposal_unrecorded: receipt write failed"
            )
        return record_receipt(*args, **kwargs)

    monkeypatch.setattr(agent_mission_project_disposal, "_record_receipt", record)

    def dispatch(**kw):
        sent.append(kw)
        outcome = handlers[kw["function_id"]](
            subject.model_copy(
                update={
                    "function": kw["function_id"],
                    "payload": kw["payload"],
                    "target": kw["target"]
                    if kw["function_id"] == "qa.artifact.add"
                    else subject.target,
                }
            )
        )
        return SimpleNamespace(
            success=outcome.primary_success,
            result=outcome.result_payload,
            error=outcome.error,
        )

    monkeypatch.setattr(qa_composed_dispatch, "call_qa_function", dispatch)
    args = [
        "--execution-id",
        subject.payload["execution_id"],
        "--requirement-id",
        str(subject.payload["requirement_id"]),
        "--run-id",
        str(subject.payload["run_id"]),
    ]
    if not cleanup:
        args += ["--item", f"ITEM-{7861}"]

    assert agent_mission_walk_cli.run_end(args) == 3
    output = capsys.readouterr()
    assert "project_uninstall_dirty_tree" in output.out
    assert "uv.lock" in output.out
    assert "starting_state_restore" not in output.out
    assert dirty.exists()
    assert (root / ".yoke/install-manifest.json").exists() == had_manifest
    assert str(root) in config.read_text()
    assert not any(p.startswith(scratch) for p in host.existing_paths)
    assert not restored
    assert get_claim(test_db, original["lease_id"]).is_active
    current = lock_plan_execution(test_db, subject.payload["execution_id"])
    assert current["session_id"] == subject.actor.session_id
    assert current["state"] == "walking"
    assert not any(kw["payload"].get("cleanup") == "finish" for kw in sent)
    test_db.rollback()

    # Only this test-created cause is removed; uninstall must run again.
    dirty.unlink()
    first_attempt = False
    assert agent_mission_walk_cli.run_end(args) == 0
    assert any(code == 0 for code, _, _ in uninstalls)
    assert restored == ["fresh-host"]
    assert not (root / ".yoke/install-manifest.json").exists()
    assert str(root) not in config.read_text()
    assert test_db.execute("SELECT retired_at FROM projects WHERE id=7").fetchone()[0]
    if cleanup:
        assert not get_claim(test_db, original["lease_id"]).is_active
