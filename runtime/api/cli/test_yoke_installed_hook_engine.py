"""Installed-wheel proof for the complete local hook engine."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from yoke_core.domain import db_backend
from yoke_core.tools.build_release import create_seeded_pip_venv


def test_installed_hooks_register_emit_and_deny(
    tmp_path: Path,
    product_wheelhouse: Path,
    test_db,
) -> None:
    venv = _install_product(tmp_path, product_wheelhouse)
    repo = _git_repo(tmp_path)
    env = _installed_env(tmp_path, venv, repo)
    yoke = venv / "bin" / "yoke"
    session_id = "installed-hook-session"

    opened = _hook(
        yoke,
        repo,
        env,
        "UserPromptSubmit",
        {
            "session_id": session_id,
            "cwd": str(repo),
            "prompt": "exercise the installed hook engine",
        },
    )
    assert opened.returncode == 0, _format(opened)

    row = test_db.execute(
        "SELECT session_id, tool_call_count FROM harness_sessions "
        "WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    assert row is not None
    assert row["tool_call_count"] == 0

    completed = _hook(
        yoke,
        repo,
        env,
        "PostToolUse",
        {
            "session_id": session_id,
            "cwd": str(repo),
            "tool_name": "Bash",
            "tool_input": {"command": "git status --short"},
            "tool_response": {"stdout": "", "stderr": "", "exit_code": 0},
        },
    )
    assert completed.returncode == 0, _format(completed)
    row = test_db.execute(
        "SELECT tool_call_count FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    assert row is not None
    assert row["tool_call_count"] >= 1

    repo.joinpath("base.txt").write_text("threatened\n", encoding="utf-8")
    denied = _hook(
        yoke,
        repo,
        env,
        "PreToolUse",
        {
            "session_id": session_id,
            "cwd": str(repo),
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard HEAD~5"},
        },
    )
    assert denied.returncode == 2, _format(denied)
    assert "destructive git command" in denied.stdout
    assert "base.txt" in denied.stdout


def test_installed_hook_chain_imports_and_missing_member_is_loud(
    tmp_path: Path,
    product_wheelhouse: Path,
    test_db,
) -> None:
    venv = _install_product(tmp_path, product_wheelhouse)
    repo = _git_repo(tmp_path)
    env = _installed_env(tmp_path, venv, repo)
    python = venv / "bin" / "python"
    script = """
import importlib
import importlib.util
import json

from yoke_contracts.hook_runner.hook_ordering import HOOK_ORDERING

assert importlib.util.find_spec("runtime") is None
modules = {
    module
    for matchers in HOOK_ORDERING.values()
    for chain in matchers.values()
    for module in chain
}
for module in sorted(modules):
    importlib.import_module(module)

from yoke_core.hooks import runner
from yoke_core.hooks.local_entry import evaluate_local_hook

runner.chain_for = lambda *_args, **_kwargs: ["missing_package.guard"]
payload = json.dumps({
    "session_id": "installed-missing-guard",
    "cwd": __import__("os").getcwd(),
    "tool_name": "Bash",
    "tool_input": {"command": "git status --short"},
})
raise SystemExit(evaluate_local_hook("PreToolUse", payload))
"""
    result = _run(
        [str(python), "-c", script],
        cwd=repo,
        env=env,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, _format(result)
    assert "YOKE_HOOK_GUARD_FAILURE" in result.stderr
    assert "missing_package.guard" in result.stderr
    assert "ModuleNotFoundError" in result.stderr


def _install_product(tmp_path: Path, wheelhouse: Path) -> Path:
    venv = tmp_path / "venv"
    create_seeded_pip_venv(venv)
    _run(
        [
            str(venv / "bin" / "python"),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(wheelhouse),
            "yoke-cli",
            "yoke-harness",
            "yoke-core",
        ],
        cwd=tmp_path,
        timeout=300,
    )
    return venv


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    _run(["git", "init", "-b", "main", str(repo)], cwd=tmp_path)
    _run(["git", "config", "user.email", "test@example.invalid"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    repo.joinpath("base.txt").write_text("base\n", encoding="utf-8")
    _run(["git", "add", "base.txt"], cwd=repo)
    _run(["git", "commit", "-m", "base"], cwd=repo)
    return repo


def _installed_env(
    tmp_path: Path,
    venv: Path,
    repo: Path,
) -> dict[str, str]:
    machine_home = tmp_path / "home" / ".yoke"
    machine_home.mkdir(parents=True)
    config = machine_home / "config.json"
    config.write_text(
        json.dumps({
            "schema_version": 1,
            "active_env": "local",
            "connections": {
                "local": {
                    "transport": "local-postgres",
                    "credential_source": {
                        "kind": "env",
                        "name": db_backend.PG_DSN_ENV,
                    },
                },
            },
            "projects": [{
                "checkout": str(repo.resolve()),
                "project_id": 1,
                "env": "local",
            }],
        }) + "\n",
        encoding="utf-8",
    )
    dsn = os.environ[db_backend.PG_DSN_ENV]
    return {
        "HOME": str(machine_home.parent),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "PATH": f"{venv / 'bin'}:{os.defpath}",
        "PYTHONNOUSERSITE": "1",
        "YOKE_EXECUTOR": "claude-code",
        "YOKE_MACHINE_CONFIG_FILE": str(config),
        "YOKE_MACHINE_HOME": str(machine_home),
        "YOKE_REPO_ROOT": str(repo),
        db_backend.PG_DSN_ENV: dsn,
    }


def _hook(
    yoke: Path,
    repo: Path,
    env: dict[str, str],
    event_name: str,
    payload: dict,
) -> subprocess.CompletedProcess[str]:
    return _run(
        [str(yoke), "hook", "evaluate", event_name],
        cwd=repo,
        env=env,
        input_text=json.dumps(payload),
        check=False,
        timeout=120,
    )


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    check: bool = True,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    run_env = dict(env) if env is not None else os.environ.copy()
    run_env.pop("PYTHONPATH", None)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=run_env,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(_format(result))
    return result


def _format(result: subprocess.CompletedProcess[str]) -> str:
    return (
        f"command failed with {result.returncode}: {result.args!r}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
