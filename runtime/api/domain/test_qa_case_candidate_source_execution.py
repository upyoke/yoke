"""Command cases execute source from their bound candidate checkout."""

import json
import shlex
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_contracts.qa_case_environment import COMMAND_CASE_CANDIDATE_TREE_ENV
from yoke_core.domain.qa_case_worktree_run import execute_worktree_case
from yoke_core.domain.verification_tree_binding import TreeBindingVerdict, TreeIdentity


@pytest.mark.parametrize("nested", [False, True], ids=["direct", "subprocess-argv"])
def test_candidate_command_executes_bound_source(tmp_path, monkeypatch, nested):
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    lane = tmp_path / "lane"
    lane.mkdir()
    # Replace only the live claim lookup in a launcher; execute the real source
    # runner, command environment, process stream and QA verdict calculation.
    launcher = tmp_path / "yoke"
    launcher.write_text(
        f"#!{sys.executable}\n"
        "import sys\nfrom pathlib import Path\n"
        "from yoke_core.tools import source_dev_run\n"
        f"source_dev_run._claimed_root = lambda: (Path({str(lane)!r}), None, None)\n"
        "from yoke_core.domain.source_python_environment import SourcePythonEnvironment\n"
        "source_dev_run.source_python_environment.resolve = lambda root, env: SourcePythonEnvironment(sys.executable, dict(env), {})\n"
        "source_dev_run._source_pythonpath.import_origins = lambda *a, **k: ({}, None)\n"
        "assert sys.argv[1:3] == ['dev', 'run']\n"
        "raise SystemExit(source_dev_run.main(sys.argv[3:]))\n"
    )
    launcher.chmod(0o755)
    argv = [
        str(launcher),
        "dev",
        "run",
        "--",
        "python3",
        "-c",
        "import os; print(os.getcwd())",
    ]
    if nested:
        script = f"import subprocess; raise SystemExit(subprocess.call({argv!r}))"
        command = f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"
    else:
        command = shlex.join(argv)
    head = "a" * 40
    case = {
        "project": "fixture",
        "project_id": 1,
        "requirement_id": 41,
        "item_id": None,
        "case_key": "candidate-source",
        "deployment_run_id": "test-run",
        "execution_target": {"deployment": {"release_lineage": head}},
        "method_config": {"command": command},
    }
    with (
        patch(
            "yoke_core.domain.qa_case_worktree_run.verification_tree_binding.resolve_tree_identity",
            return_value=TreeIdentity(root=str(candidate), head_sha=head),
        ),
        patch(
            "yoke_core.domain.qa_case_execution.record_command_run",
            return_value=(1, None),
        ) as record,
    ):
        result = execute_worktree_case(case, checkout_path=candidate)
    assert result["verdict"] == "pass" and result["exit_code"] == 0
    assert record.call_args.kwargs["verdict"] == "pass"
    raw = json.loads(record.call_args.kwargs["raw_result"])
    assert raw["verification_tree"]["head_sha"] == head
    assert f"source checkout: {candidate}" in raw["output_tail"]
    assert f"[output]\n{candidate}" in raw["output_tail"]
    assert str(lane) not in raw["output_tail"]


@pytest.mark.parametrize("lane_bound", [False, True], ids=["candidate", "lane"])
def test_command_environment_only_binds_candidate_cases(
    tmp_path, monkeypatch, lane_bound
):
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.delenv(COMMAND_CASE_CANDIDATE_TREE_ENV, raising=False)
    head = "b" * 40
    script = f"import os; print(os.environ.get({COMMAND_CASE_CANDIDATE_TREE_ENV!r}, 'absent'))"
    case = {
        "project": "fixture",
        "requirement_id": 42,
        "project_id": 1,
        "public_ref": f"ITEM-{9}" if lane_bound else None,
        "case_key": "candidate-environment",
        "execution_target": {"deployment": {"release_lineage": head}},
        "method_config": {
            "command": f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"
        },
    }
    with (
        patch(
            "yoke_core.domain.qa_case_worktree_run.verification_tree_binding.resolve_tree_identity",
            return_value=TreeIdentity(root=str(tmp_path), head_sha=head),
        ),
        patch(
            "yoke_core.domain.qa_case_worktree_run.verification_tree_binding.evaluate_run",
            return_value=TreeBindingVerdict(),
        ),
        patch(
            "yoke_core.domain.qa_case_execution.record_command_run",
            return_value=(1, None),
        ),
    ):
        result = execute_worktree_case(case, checkout_path=tmp_path)
    assert result["verdict"] == "pass"
    output = Path(result["output_capture"]).read_text()
    if lane_bound:
        assert "absent" in output
    else:
        assert (
            json.dumps(
                {"root": str(tmp_path.resolve()), "head_sha": head}, sort_keys=True
            )
            in output
        )
