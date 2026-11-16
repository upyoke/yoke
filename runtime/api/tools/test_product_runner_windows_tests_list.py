"""The Windows CI test list merges without conflicts and CI reads it order- and duplicate-free."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
LIST = "runtime/api/tools/product_runner_windows_tests.txt"
WORKFLOW = ROOT / ".github/workflows/windows-smoke.yml"
RUN_STEP = "Run the declared Windows tests"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _commit_list(repo: Path, lines: list[str], message: str) -> None:
    (repo / LIST).write_text("".join(f"{line}\n" for line in lines))
    assert _git(repo, "commit", "-qam", message).returncode == 0


def test_parallel_appends_to_the_list_merge_without_conflict(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / LIST).parent.mkdir(parents=True)
    shutil.copy(ROOT / ".gitattributes", repo / ".gitattributes")
    base = ["# header", "tests/test_base.py"]
    (repo / LIST).write_text("".join(f"{line}\n" for line in base))
    assert _git(repo, "init", "-q", "-b", "main").returncode == 0
    assert _git(repo, "add", ".").returncode == 0
    assert _git(repo, "commit", "-qm", "base").returncode == 0

    assert _git(repo, "checkout", "-qb", "lane-a").returncode == 0
    _commit_list(repo, [*base, "tests/test_a.py"], "lane a")
    assert _git(repo, "checkout", "-q", "main").returncode == 0
    _commit_list(repo, [*base, "tests/test_b.py"], "lane b")

    merged = _git(repo, "merge", "--no-edit", "lane-a")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    lines = (repo / LIST).read_text().splitlines()
    assert set(lines) == {*base, "tests/test_a.py", "tests/test_b.py"}

    assert _git(repo, "checkout", "-qb", "rebased", "lane-a~1").returncode == 0
    _commit_list(repo, [*base, "tests/test_c.py"], "lane c")
    rebased = _git(repo, "rebase", "main")
    assert rebased.returncode == 0, rebased.stdout + rebased.stderr
    assert "tests/test_c.py" in (repo / LIST).read_text().splitlines()


def _run_step_script() -> str:
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["windows-smoke"]["steps"]
    return next(step["run"] for step in steps if step.get("name") == RUN_STEP)


def test_ci_reader_ignores_comments_order_and_duplicates(tmp_path: Path) -> None:
    bash = shutil.which("bash")
    probe = subprocess.run([bash or "bash", "-c", "type mapfile"], capture_output=True, check=False)
    if bash is None or probe.returncode != 0:
        pytest.skip("the windows-smoke step needs bash 4+ (mapfile) on PATH")
    (tmp_path / LIST).parent.mkdir(parents=True)
    (tmp_path / LIST).write_text(
        "# comment\n\ntests/b.py  \ntests/a.py::t # why\ntests/b.py\ntests/a.py::t\n"
    )
    (tmp_path / "windows-smoke-evidence").mkdir()
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    args_file = tmp_path / "uv-args"
    (stub_bin / "uv").write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{args_file}"\n')
    (stub_bin / "uv").chmod(0o755)
    env = {**os.environ, "PATH": f"{stub_bin}{os.pathsep}{os.environ['PATH']}"}

    result = subprocess.run(
        [bash, "-e", "-c", _run_step_script()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    argv = args_file.read_text().splitlines()
    assert argv[-2:] == ["tests/b.py", "tests/a.py::t"]
    assert argv.count("tests/b.py") == 1
