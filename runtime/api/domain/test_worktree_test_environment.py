"""A prepared lane proves it can run its tests, or preparation blocks.

The failure these cover is the one a lane used to hide: dependency
provisioning skipped itself, the lane reported ready, and the first test
command died on an import nobody could attribute to preparation.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from runtime.api.domain.test_worktree_create_multiworktree import _config_path
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import worktree_test_environment as env
from yoke_core.domain.worktree import create_worktree
from yoke_core.domain.worktree_provision import provision_worktree_test_environment
from yoke_core.domain.worktree_test_helpers import pin_test_item_workflow


def _uv_project(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (directory / "uv.lock").write_text("", encoding="utf-8")
    return directory


def _fake_uv(bin_dir: Path, *, sync_exit: int = 0, body: str = "") -> None:
    """Put a ``uv`` on PATH that records syncs and runs real pytest.

    ``uv run --frozen python3 -m pytest …`` becomes this interpreter
    running the same module, so the collection under test is a real
    pytest collection of a real tree — only the environment resolution
    is stood in for.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "uv"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "sync" ]; then\n'
        f'  echo "synced $PWD" >> "{bin_dir / "sync.log"}"\n'
        f"{body}"
        f"  exit {sync_exit}\n"
        "fi\n"
        'if [ "$1" = "run" ]; then\n'
        "  shift 3\n"
        f'  exec "{sys.executable}" "$@"\n'
        "fi\n"
        "exit 64\n",
        encoding="utf-8",
    )
    script.chmod(0o755)


def test_lane_root_project_is_the_whole_answer(tmp_path: Path) -> None:
    _uv_project(tmp_path)
    _uv_project(tmp_path / "services" / "svc")

    assert env.uv_projects(tmp_path) == [tmp_path]


def test_nested_project_beside_other_languages_is_found(tmp_path: Path) -> None:
    service = _uv_project(tmp_path / "services" / "platform-svc")
    (tmp_path / "webapp").mkdir()
    (tmp_path / "webapp" / "package.json").write_text("{}", encoding="utf-8")
    _uv_project(tmp_path / "node_modules" / "vendored")

    assert env.uv_projects(tmp_path) == [service]


def test_a_lockless_project_is_not_a_uv_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    assert env.uv_projects(tmp_path) == []


def test_a_pytest_surface_is_a_conftest_or_a_tests_directory(tmp_path: Path) -> None:
    assert env.runs_pytest(tmp_path) is False
    (tmp_path / "tests").mkdir()
    assert env.runs_pytest(tmp_path) is True
    (tmp_path / "conftest.py").write_text("", encoding="utf-8")
    assert env.runs_pytest(tmp_path) is True


def test_a_lane_with_no_uv_project_is_ready_and_untouched(tmp_path: Path) -> None:
    report = env.provision_test_environment(str(tmp_path))

    assert report.ready is True
    assert report.actions == ()


def test_missing_uv_names_the_install_recipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _uv_project(tmp_path)
    monkeypatch.setattr(env.shutil, "which", lambda _name: None)

    report = env.provision_test_environment(str(tmp_path))

    assert report.ready is False
    assert "not on PATH" in report.error
    assert "curl -LsSf https://astral.sh/uv/install.sh | sh" in report.error


def test_a_failed_sync_carries_its_output_and_the_repair_recipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _uv_project(tmp_path)
    _fake_uv(tmp_path / "bin", sync_exit=1, body='  echo "no solution found" >&2\n')
    monkeypatch.setenv("PATH", str(tmp_path / "bin") + os.pathsep + os.environ["PATH"])

    report = env.provision_test_environment(str(project))

    assert report.ready is False
    assert "no solution found" in report.error
    assert f"cd {project} && uv sync --frozen" in report.error


def test_a_ready_lane_records_its_sync_and_its_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lane = tmp_path / "lane"
    project = _uv_project(lane)
    (project / "conftest.py").write_text("", encoding="utf-8")
    _fake_uv(tmp_path / "bin")
    monkeypatch.setenv("PATH", str(tmp_path / "bin") + os.pathsep + os.environ["PATH"])

    report = env.provision_test_environment(str(lane))

    assert report.ready is True, report.error
    assert report.actions == ("environment:synced=.", "pytest:collected=.")
    assert not (project / env.PROOF_DIRECTORY_NAME).exists()


def test_a_conftest_that_cannot_import_blocks_the_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reported failure, reproduced: pytest runs, the tree will not import."""
    lane = tmp_path / "lane"
    project = _uv_project(lane)
    (project / "conftest.py").write_text(
        "import a_package_this_lane_never_installed\n", encoding="utf-8"
    )
    _fake_uv(tmp_path / "bin")
    monkeypatch.setenv("PATH", str(tmp_path / "bin") + os.pathsep + os.environ["PATH"])

    report = env.provision_test_environment(str(lane))

    assert report.ready is False
    assert "a_package_this_lane_never_installed" in report.error
    assert "yoke watch pytest -- <pytest args>" in report.error
    assert not (project / env.PROOF_DIRECTORY_NAME).exists()


def test_the_proof_runs_inside_the_project_it_is_proving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _uv_project(tmp_path)
    (project / "tests").mkdir()
    seen: list[tuple[tuple[str, ...], Path]] = []

    def _record(cmd, cwd, _timeout):
        seen.append((tuple(cmd), cwd))
        return subprocess.CompletedProcess(list(cmd), returncode=0, stdout="", stderr="")

    monkeypatch.setattr(env.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(env, "_run", _record)

    assert env.provision_test_environment(str(project)).ready is True

    assert [cwd for _cmd, cwd in seen] == [project, project]
    collected = seen[-1][0]
    assert collected[:4] == ("uv", "run", "--frozen", "python3")
    assert "--collect-only" in collected
    assert collected[-1] == f"{env.PROOF_DIRECTORY_NAME}/{env.PROOF_TEST_FILENAME}"


def test_the_provisioning_step_reports_actions_and_returns_the_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        env,
        "provision_test_environment",
        lambda _path: env.TestEnvironmentReport(("environment:synced=.",), "broken lane"),
    )

    assert provision_worktree_test_environment(str(tmp_path)) == "broken lane"
    assert "environment:synced=." in capsys.readouterr().err


def test_an_unprovable_lane_blocks_worktree_creation(
    git_repo,
    yoke_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = connect_test_db(yoke_db)
    conn.execute(
        "INSERT INTO items "
        "(id, title, status, project_id, project_sequence) "
        "VALUES (99320, 'lane needing a test environment', 'implementing', 1, 99320)",
    )
    pin_test_item_workflow(conn, 99320, "issue")
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        env,
        "provision_test_environment",
        lambda _path: env.TestEnvironmentReport((), "lane cannot run pytest"),
    )

    result = create_worktree(
        99320,
        repo_root=str(git_repo),
        config_path=_config_path(git_repo),
        db_path=yoke_db,
    )

    assert result.error == "lane cannot run pytest"
    assert result.failed_branch == "YOK-99320"
