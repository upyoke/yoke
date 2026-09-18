"""Command-case BASE_URL and product-interpreter binding."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.domain.qa_case_command_stream import product_command_environment
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.domain.qa_case_worktree_run import execute_worktree_case
from yoke_core.domain.qa_method_config_validation import (
    COMMAND_SHELL_CONTRACT,
    QaMethodConfigError,
    validate_method_config,
)


RUN_ID = "run-20260918-004"
CANDIDATE = "a" * 40


def _repository(root: Path) -> str:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "--quiet")
    git("config", "user.email", "tester@example.test")
    git("config", "user.name", "Tester")
    (root / "probe.txt").write_text("ok\n", encoding="utf-8")
    git("add", "probe.txt")
    git("commit", "--quiet", "-m", "seed")
    return git("rev-parse", "HEAD")


def _run_attached_case(**overrides) -> dict:
    head = str(overrides.pop("candidate", CANDIDATE))
    case = {
        "requirement_id": 27930,
        "item_id": None,
        "project_id": 1,
        "project": "yoke",
        "case_key": "release-health",
        "deployment_run_id": RUN_ID,
        "deployment_stage": "item-qa",
        "method_config": {"command": "true"},
        "execution_target": {
            "deployment": {
                "run_id": RUN_ID,
                "stage": "item-qa",
                "release_lineage": head,
            },
            "endpoints": {"app_url": "https://app.example.test"},
        },
    }
    case.update(overrides)
    return case


def test_product_command_environment_prepends_runner_python() -> None:
    bound = product_command_environment({"PATH": "/usr/bin"})
    python_bin = str(Path(sys.executable).parent)
    assert bound["PATH"].split(os.pathsep)[0] == python_bin
    assert bound["YOKE_PYTHON"] == sys.executable


def test_product_command_environment_keeps_venv_bin_when_python_is_symlink(
    tmp_path: Path, monkeypatch
) -> None:
    """A venv python that symlinks onto a base interpreter must stay first.

    ``Path.resolve()`` would prepend the base bin, whose python3 has no
    product packages — the CI failure for Command-case ``import yoke_cli``.
    """
    base_bin = tmp_path / "base" / "bin"
    base_bin.mkdir(parents=True)
    (base_bin / "python3").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (base_bin / "python3").chmod(0o755)
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    venv_python = venv_bin / "python"
    venv_python.symlink_to(base_bin / "python3")
    monkeypatch.setattr(sys, "executable", str(venv_python))
    bound = product_command_environment({"PATH": str(base_bin)})
    assert bound["PATH"].split(os.pathsep)[0] == str(venv_bin)
    assert bound["YOKE_PYTHON"] == str(venv_python)
    assert Path(sys.executable).resolve().parent == base_bin


def test_run_attached_command_exports_passed_base_url_without_requires_flag(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    head = _repository(tmp_path)
    case = _run_attached_case(
        candidate=head,
        method_config={
            "command": "printf 'case-output:%s' \"$BASE_URL\"",
        },
    )

    with patch(
        "yoke_core.domain.qa_case_execution.record_command_run",
        return_value=(1, None),
    ):
        result = execute_worktree_case(
            case,
            base_url="https://preview.example",
            checkout_path=tmp_path,
        )

    assert result["verdict"] == "pass"
    capture = Path(result["output_capture"]).read_text(encoding="utf-8")
    assert "case-output:https://preview.example" in capture


def test_requires_base_url_still_refuses_when_the_flag_is_omitted(
    tmp_path: Path,
) -> None:
    head = _repository(tmp_path)
    case = _run_attached_case(
        candidate=head,
        method_config={
            "command": "true",
            "requires_base_url": True,
        },
    )

    with pytest.raises(QaCaseExecutionError) as refused:
        execute_worktree_case(case, checkout_path=tmp_path)

    message = str(refused.value)
    assert "this Command case requires --base-url" in message
    assert "yoke qa case run --requirement-id N --base-url URL" in message


def test_command_case_python3_imports_product_modules(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    head = _repository(tmp_path)
    case = _run_attached_case(
        candidate=head,
        method_config={
            "command": "python3 -c 'import yoke_cli; print(yoke_cli.__name__)'",
        },
    )

    with patch(
        "yoke_core.domain.qa_case_execution.record_command_run",
        return_value=(1, None),
    ):
        result = execute_worktree_case(case, checkout_path=tmp_path)

    assert result["verdict"] == "pass"
    capture = Path(result["output_capture"]).read_text(encoding="utf-8")
    assert "yoke_cli" in capture


def test_authoring_refuses_python_module_body_as_command() -> None:
    with pytest.raises(QaMethodConfigError, match="/bin/sh") as refused:
        validate_method_config(
            "command",
            {"command": "import urllib.request\nprint('hi')"},
        )
    assert "python3 -c" in str(refused.value)
    assert "import(1)" in str(refused.value)


def test_authoring_accepts_python3_c_wrapper() -> None:
    config = validate_method_config(
        "command",
        {"command": "python3 -c 'import urllib.request'"},
    )
    assert config["command"] == "python3 -c 'import urllib.request'"


def test_runner_refuses_python_module_body_before_shell() -> None:
    case = _run_attached_case(
        method_config={"command": "import urllib.request\nprint('hi')"},
    )
    with pytest.raises(QaCaseExecutionError) as refused:
        execute_worktree_case(case, checkout_path="/does-not-need-to-exist")
    assert str(refused.value) == COMMAND_SHELL_CONTRACT
