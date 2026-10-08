"""Command execution preserves the verified environment and import binding."""

import sys
import pytest
from yoke_contracts.install_binding import SOURCE_DEV_RUN_ROOT_ENV
from yoke_core.tools import _source_pythonpath, source_dev_run
from yoke_core.domain.source_python_environment import SourcePythonEnvironment


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setattr(
        source_dev_run.source_python_environment,
        "resolve",
        lambda root, env: SourcePythonEnvironment(sys.executable, dict(env), {}),
    )


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            [sys.executable, "-m", "pytest", "runtime/api/test_example.py"],
            [sys.executable, "-m", "pytest", "runtime/api/test_example.py"],
        ),
        (
            ["python3", "-m", "yoke_core.tools.pg_testcluster", "status"],
            [sys.executable, "-m", "yoke_core.tools.pg_testcluster", "status"],
        ),
    ],
    ids=("focused-pytest", "ambient-python3"),
)
def test_run_binds_every_command_shape_to_claimed_lane(
    monkeypatch,
    tmp_path,
    command,
    expected,
):
    captured = {}
    monkeypatch.setattr(
        source_dev_run,
        "_claimed_root",
        lambda: (tmp_path, None, None),
    )
    monkeypatch.setattr(
        source_dev_run._source_pythonpath,
        "with_source_pythonpath",
        lambda _env, _root: {"PYTHONPATH": "lane-roots"},
    )
    monkeypatch.setattr(
        source_dev_run._source_pythonpath,
        "import_origins",
        lambda _root, env, python: (
            {"runtime": str(tmp_path / "runtime/__init__.py")},
            None,
        ),
    )

    def _run(args, *, cwd, env, check):
        captured.update(args=args, cwd=cwd, env=env, check=check)
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(source_dev_run.subprocess, "run", _run)

    assert source_dev_run.run(["--", *command]) == 0
    assert captured == {
        "args": expected,
        "cwd": str(tmp_path),
        "env": {
            "PYTHONPATH": "lane-roots",
            SOURCE_DEV_RUN_ROOT_ENV: str(tmp_path),
        },
        "check": False,
    }


def test_run_refuses_partial_main_tree_resolution(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        source_dev_run,
        "_claimed_root",
        lambda: (tmp_path, None, None),
    )
    monkeypatch.setattr(
        source_dev_run._source_pythonpath,
        "import_origins",
        lambda _root, env, python: (
            {"runtime": "outside-checkout/runtime/__init__.py"},
            "source import runtime resolved outside the claimed lane",
        ),
    )

    assert source_dev_run.run(["python3", "-c", "pass"]) == 1
    error = capsys.readouterr().err
    assert "runtime resolved outside" in error
    assert _source_pythonpath.SOURCE_RUN_RECIPE in error
