"""Product-boundary fault injection for installed hook evaluation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from runtime.api.cli.product_boundary_test_support import (
    CLI_SRC,
    CONTRACTS_SRC,
    _assert_clean_client_boundary,
    _repo_pythonpath,
    _run_product_cli,
)


def _local_config() -> dict:
    return {
        "schema_version": 1,
        "active_env": "local",
        "connections": {
            "local": {
                "transport": "local-postgres",
                "credential_source": {"kind": "env", "name": "PG_DSN"},
            },
        },
    }


def _https_config(token_file: Path) -> dict:
    token_file.write_text("tok\n", encoding="utf-8")
    return {
        "schema_version": 1,
        "active_env": "stage",
        "connections": {
            "stage": {
                "transport": "https",
                "api_url": "http://127.0.0.1:9",
                "credential_source": {
                    "kind": "token_file",
                    "path": str(token_file),
                },
            },
        },
    }


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test User")
    repo.joinpath("base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-m", "base")
    return repo


def _payload(repo: Path, command: str) -> str:
    return json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(repo),
    })


def test_hook_evaluate_pretooluse_stays_inside_product_boundary(
    tmp_path: Path,
) -> None:
    run = _run_product_cli(
        tmp_path,
        ["hook", "evaluate", "PreToolUse"],
        config_payload=_local_config(),
    )

    assert run.returncode == 0
    assert run.stdout == ""
    assert run.stderr == ""
    _assert_clean_client_boundary(run)


def test_hook_evaluate_missing_harness_fails_open_for_live_event(
    tmp_path: Path,
) -> None:
    run = _run_product_cli(
        tmp_path,
        ["hook", "evaluate", "PreToolUse"],
        config_payload=_local_config(),
        include_harness=False,
    )

    assert run.returncode == 0
    assert run.stdout == ""
    assert "yoke-harness unavailable" in run.stderr
    assert "degraded to no-op allow" in run.stderr
    assert run.boundary["caught"] is None
    assert run.boundary["blocked_attempts"] == []
    assert run.boundary["forbidden_loaded"] == []
    assert _repo_pythonpath(run) == [str(CLI_SRC), str(CONTRACTS_SRC)]


def test_hook_evaluate_missing_harness_dry_run_reports_unavailable(
    tmp_path: Path,
) -> None:
    run = _run_product_cli(
        tmp_path,
        ["hook", "evaluate", "PreToolUse", "--dry-run"],
        include_harness=False,
    )

    assert run.returncode == 1
    assert run.stdout == ""
    assert "requires yoke-harness" in run.stderr
    assert run.boundary["caught"] is None
    assert run.boundary["blocked_attempts"] == []
    assert run.boundary["forbidden_loaded"] == []


def test_local_subset_denies_git_commit_on_main_without_authority_imports(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    repo.joinpath("impl.py").write_text("print('x')\n", encoding="utf-8")
    _git(repo, "add", "impl.py")

    run = _run_product_cli(
        tmp_path,
        ["hook", "evaluate", "PreToolUse"],
        config_payload=_local_config(),
        stdin_data=_payload(repo, "git commit -m impl"),
        client_cwd=repo,
    )

    assert run.returncode == 2
    assert "Implementation commit on main branch" in run.stdout
    assert "impl.py" in run.stdout
    assert run.stderr == ""
    _assert_clean_client_boundary(run)


def test_local_subset_honors_main_commit_bypass_without_authority_imports(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    repo.joinpath("impl.py").write_text("print('x')\n", encoding="utf-8")
    _git(repo, "add", "impl.py")

    run = _run_product_cli(
        tmp_path,
        ["hook", "evaluate", "PreToolUse"],
        config_payload=_local_config(),
        stdin_data=_payload(repo, "git commit -m impl # lint:no-main-check"),
        client_cwd=repo,
    )

    assert run.returncode == 0
    assert run.stdout == ""
    assert run.stderr == ""
    _assert_clean_client_boundary(run)


def test_https_relay_defers_main_commit_to_authority_without_imports(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    repo.joinpath("impl.py").write_text("print('x')\n", encoding="utf-8")
    _git(repo, "add", "impl.py")

    run = _run_product_cli(
        tmp_path,
        ["hook", "evaluate", "PreToolUse"],
        config_payload=_https_config(tmp_path / "token.txt"),
        stdin_data=_payload(repo, "git commit -m impl"),
        client_cwd=repo,
    )

    assert run.returncode == 0
    assert "Implementation commit on main branch" not in run.stdout
    assert "degraded to no-op allow" in run.stderr
    _assert_clean_client_boundary(run)


def test_local_subset_denies_destructive_git_without_authority_imports(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    repo.joinpath("base.txt").write_text("changed\n", encoding="utf-8")

    run = _run_product_cli(
        tmp_path,
        ["hook", "evaluate", "PreToolUse"],
        config_payload=_local_config(),
        stdin_data=_payload(repo, "git reset --hard"),
        client_cwd=repo,
    )

    assert run.returncode == 2
    assert "destructive git command" in run.stdout
    assert "base.txt" in run.stdout
    assert run.stderr == ""
    _assert_clean_client_boundary(run)


def test_relay_short_circuits_before_http_when_local_subset_denies(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    repo.joinpath("base.txt").write_text("changed\n", encoding="utf-8")

    run = _run_product_cli(
        tmp_path,
        ["hook", "evaluate", "PreToolUse"],
        config_payload=_https_config(tmp_path / "token.txt"),
        stdin_data=_payload(repo, "git reset --hard"),
        client_cwd=repo,
    )

    assert run.returncode == 2
    assert "destructive git command" in run.stdout
    assert "degraded to no-op allow" not in run.stderr
    _assert_clean_client_boundary(run)
