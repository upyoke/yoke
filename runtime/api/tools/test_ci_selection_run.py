"""The CI-side selection runner: selection from two commits, then pytest."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import pytest

from yoke_core.domain.yaml_helper import load_document
from yoke_core.tools import ci_selection_run as runner
from yoke_core.tools._impacted_changed_paths import changed_paths
from yoke_core.tools._impacted_selection import Selection
from yoke_core.tools._source_pythonpath import repo_root
from yoke_core.tools._watch_pytest_args import NO_SELECTED_TESTS


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture()
def committed_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "one")
    return root


def test_pytest_command_uses_every_runner_core_unless_told_otherwise() -> None:
    assert runner.pytest_command(["a.py"], ["-q"]) == [
        sys.executable, "-m", "pytest", "a.py", "-q", "-n", runner.CI_WORKERS,
    ]
    assert runner.pytest_command([], ["-n", "0", "b.py"])[-3:] == ["-n", "0", "b.py"]


def test_has_positional_args_ignores_flag_values() -> None:
    assert runner.has_positional_args(["-k", "expr", "-q"]) is False
    assert runner.has_positional_args(["-q", "tests/test_a.py"]) is True
    assert runner.has_positional_args([]) is False


def test_wrong_checkout_is_refused(committed_repo: Path, capsys) -> None:
    code = runner.run_selection(
        committed_repo, base_sha="", expected_head_sha="f" * 40, passthrough=["test_ok.py"],
    )
    assert code == runner.EXIT_USAGE
    assert "the dispatch named ffffffffffff" in capsys.readouterr().out


def test_nothing_to_run_is_refused(committed_repo: Path, capsys) -> None:
    code = runner.run_selection(
        committed_repo, base_sha="", expected_head_sha="", passthrough=["-q"],
    )
    assert code == runner.EXIT_USAGE
    assert "nothing to run" in capsys.readouterr().out


def test_empty_selection_runs_nothing_and_passes(committed_repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(runner, "selection_paths", lambda root, base: None)
    code = runner.run_selection(
        committed_repo, base_sha="b" * 40, expected_head_sha="", passthrough=[],
    )
    assert code == 0
    assert NO_SELECTED_TESTS in capsys.readouterr().out


def test_explicit_paths_run_and_mirror_into_the_log(committed_repo: Path, tmp_path: Path) -> None:
    log = tmp_path / "out.txt"
    head = _git(committed_repo, "rev-parse", "HEAD")
    code = runner.run_selection(
        committed_repo,
        base_sha="",
        expected_head_sha=head,
        passthrough=["test_ok.py", "-n", "0", "-q", "-p", "no:cacheprovider"],
        log_path=log,
    )
    assert code == 0
    assert "1 passed" in log.read_text()


def test_selection_paths_is_bounded_and_prints_the_advisory(monkeypatch, capsys, tmp_path) -> None:
    seen: dict = {}

    def fake_selection(base, *, bounded=False, root=None):
        seen.update(base=base, bounded=bounded, root=root)
        return Selection(
            full_sweep=False, reason="unbounded", files=("runtime/api/test_a.py",),
            fallback_rule="test_tooling_module", trigger_paths=("x.py",),
            bounded_deferral=True,
        )

    monkeypatch.setattr(
        "yoke_core.tools.watch_pytest_project_python.impacted_selection", fake_selection,
    )
    paths = runner.selection_paths(tmp_path, "b" * 40)

    assert paths == ["runtime/api/test_a.py"]
    assert seen == {"base": "b" * 40, "bounded": True, "root": tmp_path}
    assert "selection would widen (rule=test_tooling_module" in capsys.readouterr().out


def test_selection_is_reproducible_from_the_merge_base_sha() -> None:
    """The remote runner measures from ``base_sha``; the local run from ``main``.

    Both must name the same changed paths for the same tree, or the remote
    run would select tests for something other than what the developer
    asked about. Selection is a pure function of those paths and the import
    index, so comparing the paths settles the selections without building
    the index twice — and without a working-tree edit between two long
    builds turning the equality into a coin flip.
    """
    root = repo_root(Path(__file__).resolve())
    merge_base = subprocess.run(
        ["git", "-C", str(root), "merge-base", "main", "HEAD"],
        capture_output=True, text=True,
    )
    if merge_base.returncode != 0:
        merge_base = subprocess.run(
            ["git", "-C", str(root), "merge-base", "origin/main", "HEAD"],
            capture_output=True, text=True,
        )
    if merge_base.returncode != 0:
        pytest.skip("no main to measure this tree against")
    base_sha = merge_base.stdout.strip()

    by_name = changed_paths(root, "main")
    by_sha = changed_paths(root, base_sha)

    assert by_sha == by_name


def test_main_parses_shell_quoted_pytest_args(monkeypatch, tmp_path) -> None:
    seen: dict = {}

    def fake_run(root, **kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(runner, "run_selection", fake_run)
    code = runner.main([
        "--root", str(tmp_path), "--base-sha=" + "b" * 40, "--head-sha=" + "a" * 40,
        "--pytest-args=-q -k 'x y'",
    ])
    assert code == 0
    assert seen == {
        "base_sha": "b" * 40, "expected_head_sha": "a" * 40, "passthrough": ["-q", "-k", "x y"],
    }


SELECTION_WORKFLOW = repo_root() / ".github" / "workflows" / "yoke-tests-selection.yml"

#: What the workflow step runs; the tests below swap it for an argv reporter.
MODULE_INVOCATION = "uv run python -m yoke_core.tools.ci_selection_run"


def _selection_run_block() -> str:
    """The shell the workflow step runs to hand its inputs to this module."""
    steps = load_document(SELECTION_WORKFLOW)["jobs"]["selection"]["steps"]
    run_blocks = [
        step["run"] for step in steps if MODULE_INVOCATION in step.get("run", "")
    ]
    assert len(run_blocks) == 1, "expected exactly one selection invocation"
    return run_blocks[0]


def _dispatched_argv(pytest_args: Sequence[str], tmp_path: Path) -> list[str]:
    """The argv that workflow step's own shell builds for *pytest_args*.

    The dispatcher writes ``shlex.join(pytest_args)`` into the workflow input,
    so the step's environment carries exactly this string.
    """
    reporter = tmp_path / "report_argv.py"
    reporter.write_text(
        "import json, sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8",
    )
    command = _selection_run_block().replace(
        MODULE_INVOCATION,
        f"{shlex.quote(sys.executable)} {shlex.quote(str(reporter))}",
    )
    completed = subprocess.run(
        ["/bin/sh", "-c", command],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "SELECTION_BASE_SHA": "b" * 40,
            "SELECTION_HEAD_SHA": "a" * 40,
            "SELECTION_PYTEST_ARGS": shlex.join(pytest_args),
        },
    )
    return json.loads(completed.stdout)


@pytest.mark.parametrize(
    "pytest_args",
    [
        pytest.param([], id="empty"),
        pytest.param(["-q"], id="single-option"),
        pytest.param(["-q", "-x"], id="multiple-options"),
        pytest.param(["-k", "test_a or test_b"], id="quoted-filter-value"),
    ],
)
def test_dispatched_pytest_args_survive_the_workflow_boundary(
    pytest_args: list[str], tmp_path: Path,
) -> None:
    """Every dispatch shape reaches pytest meaning exactly what was sent.

    A lone ``-q`` is the shape that used to die on argument parsing before
    pytest started: separated, argparse read it as another option.
    """
    parsed = runner.parse_args(_dispatched_argv(pytest_args, tmp_path))
    assert shlex.split(parsed.pytest_args) == pytest_args
    assert parsed.base_sha == "b" * 40
    assert parsed.head_sha == "a" * 40
