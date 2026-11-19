"""YOK-5407: release-run QA controller work runs on the run's candidate runtime."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain import qa_controller_candidate as candidate_mod
from yoke_core.domain import qa_controller_handoff_cli as handoff
from yoke_core.domain import qa_plan_execution
from yoke_core.domain.qa_controller_candidate import (
    QaControllerNotCandidate,
    controller_candidate,
    require_candidate_controller,
    stamp_submission,
)
from yoke_core.domain.qa_plan_execution_cli import _qualify_review_dispatch
from yoke_core.tools.qa_controller_runtime import (
    ControllerRuntime,
    ControllerRuntimeError,
)

CANDIDATE = "0de5f95e60de2a5231be4d8940a2d292764168fe"
STALE = "1" * 40
BASE = "https://api.stage.example.test"
VERSION = "0.2.0.202611171947"


def _execution(**endpoints):
    return {
        "execution_id": "exec-1",
        "deployment_run_id": "run-1",
        "deployment_stage": "item-qa",
        "requirements": [{"requirement_id": 7, "runner_id": "host_control"}],
        "execution_target": {
            "deployment": {"run_id": "run-1", "stage": "item-qa", "release_lineage": CANDIDATE},
            "endpoints": {
                "installer_base_url": BASE,
                "release_channel": "latest",
                **endpoints,
            },
        },
    }


@pytest.fixture
def served(monkeypatch):
    """The installer origin serves the candidate on its channel."""
    documents = {
        f"{BASE}/dist/channels/latest.json": {
            "version": VERSION,
            "migration_history": {"source_commit": CANDIDATE},
        },
        f"{BASE}/dist/releases/9.9.9/migration-history.json": {
            "artifact": {"source_commit": "2" * 40}
        },
    }
    from yoke_contracts import resilient_fetch

    def fetch(url, **_):
        if url not in documents:
            raise resilient_fetch.FetchError(f"HTTP 404 for {url}", url=url, attempts=1, retryable=False, status=404)
        return SimpleNamespace(body=json.dumps(documents[url]).encode())

    monkeypatch.setattr(resilient_fetch, "fetch_bytes", fetch)
    return documents


def _identity(monkeypatch, commit):
    monkeypatch.setattr(
        candidate_mod,
        "controller_runtime_identity",
        lambda: {"version": "0.2.0.202611171735", "source_commit": commit, "kind": "release"},
    )


def test_only_release_runs_with_an_installer_origin_owe_a_candidate(served):
    assert controller_candidate({"execution_target": {}}) is None
    no_origin = _execution(installer_base_url="")
    assert controller_candidate(no_origin) is None
    found = controller_candidate(_execution())
    assert (found.version, found.source_commit, found.installer_base_url) == (
        VERSION, CANDIDATE, BASE,
    )


def test_pinned_release_resolves_its_published_commit(served):
    found = controller_candidate(_execution(release_version="9.9.9"))
    assert (found.version, found.source_commit) == ("9.9.9", "2" * 40)


def test_channel_serving_another_build_refuses(served):
    served[f"{BASE}/dist/channels/latest.json"]["migration_history"]["source_commit"] = STALE
    with pytest.raises(QaControllerNotCandidate, match="qa_controller_not_candidate"):
        controller_candidate(_execution())


def test_unreachable_origin_refuses_with_recovery(served):
    with pytest.raises(QaControllerNotCandidate, match="Restore access"):
        controller_candidate(_execution(release_channel="missing"))


def test_candidate_controller_runs_in_process(monkeypatch, served):
    _identity(monkeypatch, CANDIDATE)
    assert require_candidate_controller(_execution(), adopted=False) is None


def test_stale_controller_is_handed_off_and_child_never_recurses(monkeypatch, served):
    _identity(monkeypatch, STALE)
    assert require_candidate_controller(_execution(), adopted=False).source_commit == CANDIDATE
    with pytest.raises(QaControllerNotCandidate, match="re-run"):
        require_candidate_controller(_execution(), adopted=True)


class _Plan:
    """Drive execute_plan against a stubbed control plane."""

    def __init__(self, monkeypatch):
        self.calls = []
        self.ran_in_process = False
        monkeypatch.setattr(qa_plan_execution, "_call_plan_function", self.call)
        monkeypatch.setattr(
            qa_plan_execution,
            "validate_begun_execution",
            lambda execution, **_: SimpleNamespace(requirements=execution["requirements"]),
        )
        monkeypatch.setattr(
            "yoke_core.domain.deployment_qa_start_identity.report_start_identity",
            lambda *a, **k: None,
        )
        monkeypatch.setattr(
            "yoke_core.domain.qa_standalone_command.preflight_standalone_runners",
            lambda *a, **k: None,
        )

        def in_process(**_):
            self.ran_in_process = True
            return {"state": "passed", "results": []}

        monkeypatch.setattr(
            "yoke_core.domain.qa_plan_execution_run.execute_begun_plan", in_process
        )

    def call(self, *, function_id, payload, **_):
        self.calls.append(function_id)
        if function_id == "qa.plan_execution.begin":
            return _execution()
        return {}

    def run(self):
        return qa_plan_execution.execute_plan(
            deployment_run_id="run-1",
            deployment_stage="item-qa",
            plan="P",
            project="yoke",
            actor=SimpleNamespace(session_id="sess-1", actor_id=None),
        )


def _runtime(tmp_path: Path) -> ControllerRuntime:
    root = tmp_path / "runtime"
    return ControllerRuntime(root, root / "bin/python", root / "bin/yoke", VERSION, CANDIDATE)


def test_stale_controller_hands_the_begun_execution_to_the_candidate(
    monkeypatch, served, tmp_path
):
    _identity(monkeypatch, STALE)
    plan = _Plan(monkeypatch)
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(handoff, "provision", lambda candidate: runtime)
    seen = {}

    def candidate_child(argv, *, env, check, stdout):
        request = json.loads(Path(argv[-2]).read_text())
        seen.update(argv=argv, env=env, request=request)
        Path(argv[-1]).write_text(
            json.dumps(
                {
                    "result": {
                        "state": "passed",
                        "controller_runtime": {"source_commit": CANDIDATE, "version": VERSION},
                    }
                }
            )
        )
        return subprocess.CompletedProcess(argv, 0)

    original = handoff.hand_off
    monkeypatch.setattr(
        handoff, "hand_off", lambda rt, **kw: original(rt, runner=candidate_child, **kw)
    )

    result = plan.run()

    assert not plan.ran_in_process
    assert "test_machine.plan_case.begin" not in plan.calls
    assert result["controller_runtime"] == {
        "source_commit": CANDIDATE,
        "version": VERSION,
        "executable": str(runtime.executable),
    }
    assert seen["argv"][:4] == [str(runtime.python), "-I", "-m", handoff.HANDOFF_MODULE]
    assert seen["env"][candidate_mod.CONTROLLER_RUNTIME_ENV] == str(runtime.root)
    assert seen["env"]["YOKE_SESSION_ID"] == "sess-1"
    assert seen["request"]["execution"]["execution_id"] == "exec-1"
    assert seen["request"]["plan_kwargs"]["deployment_run_id"] == "run-1"


def test_unprovisionable_runtime_refuses_before_any_lease(monkeypatch, served):
    _identity(monkeypatch, STALE)
    plan = _Plan(monkeypatch)

    def broken(**_):
        raise ControllerRuntimeError("could not install wheels: HTTP 404")

    monkeypatch.setattr(handoff, "ensure_controller_runtime", broken)
    with pytest.raises(Exception) as refused:
        plan.run()

    message = str(refused.value)
    assert "qa_controller_not_candidate" in message
    assert "0.2.0.202611171735" in message and VERSION in message
    assert "installed CLI and its channel were not changed" in message
    assert "qa.plan_execution.abort" in plan.calls
    assert "test_machine.plan_case.begin" not in plan.calls
    assert not plan.ran_in_process


def test_candidate_controller_runs_the_roster_itself(monkeypatch, served):
    _identity(monkeypatch, CANDIDATE)
    plan = _Plan(monkeypatch)
    monkeypatch.setattr(handoff, "provision", lambda c: pytest.fail("no handoff owed"))
    assert plan.run()["state"] == "passed"
    assert plan.ran_in_process


def test_adopted_execution_skips_a_second_begin(monkeypatch, served):
    _identity(monkeypatch, CANDIDATE)
    plan = _Plan(monkeypatch)
    qa_plan_execution.execute_plan.__wrapped__(
        deployment_run_id="run-1",
        deployment_stage="item-qa",
        plan="P",
        project="yoke",
        adopted_execution=_execution(),
        actor=SimpleNamespace(session_id="sess-1", actor_id=None),
    )
    assert plan.ran_in_process
    assert "qa.plan_execution.begin" not in plan.calls
    assert "qa.plan.materialize" not in plan.calls


def test_machine_evidence_records_the_controller_runtime(monkeypatch):
    _identity(monkeypatch, CANDIDATE)
    payload = {"results": [{"evidence": {"runner_id": "host_control"}}]}
    stamp_submission(payload)
    assert payload["results"][0]["evidence"]["controller_runtime"]["source_commit"] == CANDIDATE


def test_walker_commands_run_on_the_candidate_executable(monkeypatch):
    monkeypatch.setenv("YOKE_ENV", "prod")
    result = {
        "controller_runtime": {"executable": "/rt/bin/yoke"},
        "review_bundle": {
            "dispatch": {
                "authority": {"state": "bound"},
                "artifact_read_commands": ["yoke qa artifact get 1"],
                "walker_dispatches": [],
                "submit_command": "yoke qa plan review-submit --execution-id e",
                "prompt": "Review.",
            }
        },
    }
    _qualify_review_dispatch(result)
    dispatch = result["review_bundle"]["dispatch"]
    assert dispatch["submit_command"].startswith("/rt/bin/yoke --env prod qa plan")
    assert "candidate controller" in dispatch["prompt"]


def _moved(lineage):
    """Run run-2 took over an execution run-1 froze on ``lineage``."""
    moved = _execution()
    moved["deployment_run_id"] = "run-2"
    moved["execution_target"]["deployment"]["release_lineage"] = lineage
    return moved


def _begins(monkeypatch, plan, responses):
    """Each begin returns the next response; every call is recorded."""
    responses = iter(responses)

    def call(*, function_id, payload, **_):
        plan.calls.append(function_id)
        return next(responses) if function_id == "qa.plan_execution.begin" else {}

    monkeypatch.setattr(qa_plan_execution, "_call_plan_function", call)


def test_stale_refusal_names_the_frozen_run_with_its_own_build(served):
    with pytest.raises(candidate_mod.QaControllerStaleTarget) as refused:
        controller_candidate(_moved(STALE))
    message = str(refused.value)
    assert f"run run-1 stage item-qa delivered candidate {STALE[:12]}" in message
    assert "Run run-2 now owns this execution" in message
    assert "run run-2 stage item-qa delivered candidate" not in message


def test_stale_target_re_begins_in_place_instead_of_requeueing(monkeypatch, served):
    _identity(monkeypatch, CANDIDATE)
    plan = _Plan(monkeypatch)
    _begins(monkeypatch, plan, [_moved(STALE), {**_moved(CANDIDATE), "deployment_run_id": "run-1"}])
    monkeypatch.setattr(candidate_mod.time, "sleep", lambda _: None)
    assert plan.run()["state"] == "passed"
    assert plan.calls.count("qa.plan_execution.begin") == 2
    assert "qa.plan_execution.abort" not in plan.calls


def test_target_still_stale_after_retries_is_released(monkeypatch, served):
    _identity(monkeypatch, CANDIDATE)
    plan = _Plan(monkeypatch)
    _begins(monkeypatch, plan, [_moved(STALE)] * (candidate_mod.RETARGET_ATTEMPTS + 1))
    monkeypatch.setattr(candidate_mod.time, "sleep", lambda _: None)
    with pytest.raises(Exception, match="Run run-2 now owns.*has been released"):
        plan.run()
    assert plan.calls.count("qa.plan_execution.begin") == candidate_mod.RETARGET_ATTEMPTS + 1
    assert "qa.plan_execution.abort" in plan.calls
