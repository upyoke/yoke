"""Candidate protection runs before source imports or child execution."""

import json
from unittest.mock import Mock

import pytest

from yoke_contracts.qa_case_environment import COMMAND_CASE_CANDIDATE_TREE_ENV
from yoke_core.tools import source_dev_run


@pytest.mark.parametrize("bound", [False, True], ids=["ordinary-lane", "same-root"])
def test_lane_execution_is_unchanged(monkeypatch, tmp_path, bound):
    monkeypatch.delenv(COMMAND_CASE_CANDIDATE_TREE_ENV, raising=False)
    if bound:
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        monkeypatch.setenv(
            COMMAND_CASE_CANDIDATE_TREE_ENV,
            json.dumps({"root": str(alias), "head_sha": "a" * 40}),
        )
    monkeypatch.setattr(source_dev_run, "_claimed_root", lambda: (tmp_path, None, None))
    monkeypatch.setattr(
        source_dev_run._source_pythonpath, "import_origins", lambda *a, **k: ({}, None)
    )
    child = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(source_dev_run.subprocess, "run", child)
    assert source_dev_run.run(["true"]) == 0
    assert child.call_args.kwargs["cwd"] == str(tmp_path)


@pytest.mark.parametrize(
    "binding",
    ["", "not-json", "null", "[]", "{}", '{"root": 3, "head_sha": "a"}'],
)
def test_malformed_binding_refuses_before_launch(
    monkeypatch, tmp_path, capsys, binding
):
    monkeypatch.setenv(COMMAND_CASE_CANDIDATE_TREE_ENV, binding)
    monkeypatch.setattr(source_dev_run, "_claimed_root", lambda: (tmp_path, None, None))
    child = Mock()
    monkeypatch.setattr(source_dev_run.subprocess, "run", child)
    assert source_dev_run.run(["true"]) == 1
    child.assert_not_called()
    assert "QA-CANDIDATE-BINDING REFUSAL" in capsys.readouterr().err


def test_different_root_refuses_before_imports(monkeypatch, tmp_path, capsys):
    candidate = tmp_path / "candidate"
    lane = tmp_path / "lane"
    monkeypatch.setenv(
        COMMAND_CASE_CANDIDATE_TREE_ENV,
        json.dumps({"root": str(candidate), "head_sha": "a" * 40}),
    )
    monkeypatch.setattr(source_dev_run, "_claimed_root", lambda: (lane, None, None))
    imports = Mock()
    monkeypatch.setattr(source_dev_run._source_pythonpath, "import_origins", imports)
    assert source_dev_run.run(["true"]) == 1
    imports.assert_not_called()
    error = capsys.readouterr().err
    assert "QA-CANDIDATE-SOURCE-REBIND REFUSAL" in error
    assert str(candidate) in error and str(lane) in error and "a" * 40 in error
    assert "Drop the" in error and "binds its own cwd" in error


@pytest.fixture(autouse=True)
def isolated_environment_probe(monkeypatch):
    import sys
    from yoke_core.domain.source_python_environment import SourcePythonEnvironment

    monkeypatch.setattr(
        source_dev_run.source_python_environment,
        "resolve",
        lambda root, env: SourcePythonEnvironment(sys.executable, dict(env), {}),
    )
