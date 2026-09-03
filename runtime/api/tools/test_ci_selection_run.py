"""The CI-side selection runner: selection from two commits, then pytest."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from yoke_core.tools import ci_selection_run as runner
from yoke_core.tools import impacted_tests
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
    """The remote runner selects from ``base_sha``; the local run from ``main``.

    Both must name the same test files for the same tree, or the remote run
    would test something other than what the developer asked about.
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

    by_name = impacted_tests.selection_for(root, "main", bounded=True)
    by_sha = impacted_tests.selection_for(root, base_sha, bounded=True)

    assert by_sha.files == by_name.files
    assert by_sha.bounded_deferral == by_name.bounded_deferral
    assert by_sha.fallback_rule == by_name.fallback_rule


def test_main_parses_shell_quoted_pytest_args(monkeypatch, tmp_path) -> None:
    seen: dict = {}

    def fake_run(root, **kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(runner, "run_selection", fake_run)
    code = runner.main([
        "--root", str(tmp_path), "--base-sha", "b" * 40, "--head-sha", "a" * 40,
        "--pytest-args", "-q -k 'x y'",
    ])
    assert code == 0
    assert seen == {
        "base_sha": "b" * 40, "expected_head_sha": "a" * 40, "passthrough": ["-q", "-k", "x y"],
    }
