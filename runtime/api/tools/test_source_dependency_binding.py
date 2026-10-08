"""Reproduce a missing Hypothesis dependency with an offline locked wheel.

The wheel is an equivalent deterministic dependency fixture, not the actual
Hypothesis implementation. It proves environment/import identity through the
registered import-check and nested watcher command shapes without an index.
"""

import json
import os
import subprocess
import zipfile
from pathlib import Path

from runtime.api.tools.test_source_dev_run_cli_child_binding import _stub_source_tree
from yoke_core.domain import source_python_environment as environment
from yoke_core.domain.qa_environment_declaration import TestEnvironmentDeclaration
from yoke_core.tools import (
    _source_pythonpath,
    source_dev_run,
    watch_pytest_project_python,
)


def _locked_dependency(root):
    wheel = root / "hypothesis-0.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("hypothesis/__init__.py", "__version__='locked-fixture'\n")
        archive.writestr(
            "hypothesis-0.0.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: hypothesis\nVersion: 0.0.0\n",
        )
        archive.writestr(
            "hypothesis-0.0.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr("hypothesis-0.0.0.dist-info/RECORD", "")
    project = root / "pyproject.toml"
    project.write_text(
        project.read_text() + '[dependency-groups]\nchecks=["hypothesis==0.0.0"]\n'
        '[tool.uv.sources]\nhypothesis={path="' + wheel.name + '"}\n'
    )
    for args in (
        ["lock", "--offline"],
        ["sync", "--frozen", "--offline", "--group", "checks"],
    ):
        subprocess.run(
            ["uv", *args], cwd=root, capture_output=True, text=True, check=True
        )
    return root


PROBE = """import hypothesis,json,sys
print(json.dumps({'dependency':hypothesis.__file__,'version':hypothesis.__version__,
                  'python':sys.executable,'prefix':sys.prefix}))
"""


def test_import_check_and_nested_local_watcher_see_locked_lane_dependency(
    tmp_path, monkeypatch, capfd
):
    root = _locked_dependency(_stub_source_tree(tmp_path / "candidate"))
    monkeypatch.setattr(
        environment,
        "load_declaration",
        lambda **_kwargs: TestEnvironmentDeclaration(
            project="fixture", groups=("checks",)
        ),
    )
    monkeypatch.setattr(
        source_dev_run, "_claimed_root", lambda *_args: (root, None, None)
    )
    # The original path binds candidate packages but keeps invoking dependencies.
    invoking = _stub_source_tree(tmp_path / "invoking") / ".venv/bin/python3"
    before = subprocess.run(
        [str(invoking), "-c", PROBE],
        cwd=root,
        env=_source_pythonpath.with_source_pythonpath(os.environ, root),
        capture_output=True,
        text=True,
    )
    assert before.returncode and "No module named 'hypothesis'" in before.stderr
    # A minimal CLI fixture preserves the registered command shapes.
    cli = root / "packages/yoke-cli/src/yoke_cli/main.py"
    cli.write_text(
        "import runpy,sys,subprocess\n"
        "if sys.argv[1:3] == ['dev','import-check']:\n"
        "    exec(" + repr(PROBE) + ")\n"
        "else:\n"
        "    assert sys.argv[1:4] == ['watch','pytest','--local']\n"
        "    print('nested-local-watcher', sys.executable)\n"
        "    subprocess.run(['python3','-m','pytest'],check=True)\n"
    )
    # Locked fixture workload proves imports and Python identity, without pytest's own deps.
    binding = environment.resolve(root, os.environ)
    site = next((root / ".venv/lib").glob("python*/site-packages"))
    (site / "pytest").mkdir()
    (site / "pytest/__init__.py").touch()
    (site / "pytest/__main__.py").write_text(
        PROBE
        + "\nimport subprocess\nsubprocess.run(['python3', '-c', "
        + repr(PROBE)
        + "], check=True)\n"
    )
    assert source_dev_run.run(["yoke", "dev", "import-check", "hypothesis"]) == 0
    assert (
        source_dev_run.run(["yoke", "watch", "pytest", "--local", "--", "fixture.py"])
        == 0
    )
    argv = watch_pytest_project_python.pytest_argv([], cwd=root)
    assert argv[0] == binding.python
    captured = capfd.readouterr()
    identities = [
        json.loads(line) for line in captured.out.splitlines() if line.startswith("{")
    ]
    assert len(identities) == 3
    for facts in identities:
        assert Path(facts["dependency"]).is_relative_to(root / ".venv")
        assert facts["python"] == binding.python
        assert facts["version"] == "locked-fixture"
    assert "source environment:" in captured.err


def test_ambient_main_only_dependency_cannot_rescue_candidate(
    tmp_path, monkeypatch, capfd
):
    root = _stub_source_tree(tmp_path / "candidate")
    ambient = tmp_path / "main-site"
    ambient.mkdir()
    (ambient / "main_only_dependency.py").write_text("value=True\n")
    monkeypatch.setenv("PYTHONPATH", str(ambient))
    monkeypatch.setattr(
        environment,
        "load_declaration",
        lambda **_kwargs: TestEnvironmentDeclaration(project="fixture"),
    )
    monkeypatch.setattr(
        source_dev_run, "_claimed_root", lambda *_args: (root, None, None)
    )
    assert source_dev_run.run(["python3", "-c", "import main_only_dependency"]) != 0
    assert "No module named 'main_only_dependency'" in capfd.readouterr().err
