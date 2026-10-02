"""A deployment Command case executes and records its candidate's imports."""

import json
import shlex
from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.domain.qa_case_worktree_run import execute_worktree_case
from yoke_core.domain.verification_tree_binding import TreeBindingVerdict, TreeIdentity
from yoke_core.tools._source_pythonpath import PACKAGE_SRC_RELS


def _candidate(root):
    for rel in PACKAGE_SRC_RELS:
        name = Path(rel).parent.name.replace("-", "_")
        package = root / rel / name
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("marker = 'candidate-only'\n")
    (root / "runtime").mkdir()
    (root / "runtime" / "__init__.py").write_text("")
    (root / "packages/yoke-cli/src/yoke_cli/main.py").write_text(
        "import yoke_core\nprint(yoke_core.marker, yoke_core.__file__)\n"
    )


def _execute(root, command, *, lane=False, endpoint_only=False):
    head = "c" * 40
    case = {
        "requirement_id": 41,
        "item_id": 9 if lane else None,
        "case_key": "candidate-imports",
        "deployment_run_id": "test-run",
        "execution_target": {"deployment": {"release_lineage": head}},
        "method_config": {"command": command},
    }
    with (
        patch(
            "yoke_core.domain.qa_case_worktree_run.verification_tree_binding.resolve_tree_identity",
            return_value=TreeIdentity(root=str(root), head_sha=head),
        ),
        patch(
            "yoke_core.domain.qa_case_worktree_run.verification_tree_binding.evaluate_run",
            return_value=TreeBindingVerdict(),
        ),
        patch(
            "yoke_core.domain.qa_case_execution.record_command_run",
            return_value=(1, None),
        ) as record,
    ):
        result = execute_worktree_case(
            case, checkout_path=root, allow_tree_mismatch=endpoint_only
        )
    return result, record.call_args.kwargs


@pytest.mark.parametrize("nested", [False, True], ids=["shell", "subprocess"])
def test_bare_python_and_yoke_import_candidate_instead_of_installed_source(
    tmp_path, monkeypatch, nested
):
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    root = tmp_path / "candidate"
    _candidate(root)
    probe = "import yoke_core; print(yoke_core.marker, yoke_core.__file__)"
    if nested:
        body = (
            "import subprocess; "
            f"subprocess.run(['python3', '-c', {probe!r}], check=True); "
            "subprocess.run(['yoke', 'probe'], check=True)"
        )
        command = "python3 -c " + shlex.quote(body)
    else:
        command = "python3 -c " + shlex.quote(probe) + " && yoke probe"
    result, record = _execute(root, command)
    assert result["verdict"] == "pass"
    output = Path(result["output_capture"]).read_text()
    assert output.count("candidate-only") == 2
    raw = json.loads(record["raw_result"])
    assert raw["candidate_source"] == result["candidate_source"]
    for moment in ("before", "after"):
        origins = raw["candidate_source"][moment]
        assert len(origins) == len(PACKAGE_SRC_RELS) + 1
        assert all(Path(origin).is_relative_to(root) for origin in origins.values())


def test_partial_candidate_records_refusal_instead_of_running_command(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    root = tmp_path / "candidate"
    _candidate(root)
    package = root / "packages/yoke-cli/src/yoke_cli"
    package.rename(package.with_name("unavailable"))
    result, record = _execute(root, "echo command-executed")
    assert result["verdict"] == record["verdict"] == "fail"
    assert result["exit_code"] == 1
    evidence = result["candidate_source"]
    assert not Path(evidence["before"]["yoke_cli"]).is_relative_to(root)
    assert "QA-CANDIDATE-IMPORT-ORIGIN REFUSAL" in evidence["refusal"]
    assert "Repair the candidate checkout" in record["output"]
    assert "[output]\ncommand-executed" not in record["output"]


def test_zero_exit_cannot_pass_when_candidate_origins_change_during_command(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    root = tmp_path / "candidate"
    _candidate(root)
    body = (
        "from pathlib import Path; "
        "p=Path('packages/yoke-cli/src/yoke_cli'); "
        "p.rename(p.with_name('unavailable'))"
    )
    result, record = _execute(root, "python3 -c " + shlex.quote(body))
    assert result["verdict"] == record["verdict"] == "fail"
    assert "after" in result["candidate_source"]
    assert "outside" in result["candidate_source"]["refusal"]


@pytest.mark.parametrize("scope", ["lane", "endpoint", "external"])
def test_other_command_scopes_keep_product_imports(tmp_path, monkeypatch, scope):
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    root = tmp_path / "checkout"
    root.mkdir()
    if scope != "external":
        _candidate(root)
    result, record = _execute(
        root,
        "python3 -c 'import yoke_core; print(yoke_core.__file__)'",
        lane=scope == "lane",
        endpoint_only=scope == "endpoint",
    )
    assert result["verdict"] == "pass"
    assert result["candidate_source"] is None
    output = Path(result["output_capture"]).read_text()
    assert str(root / "packages") not in output
    assert json.loads(record["raw_result"])["candidate_source"] is None
