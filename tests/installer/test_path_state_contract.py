"""Bash login-file selection in the resolved PATH state contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_cli.config.path_state_contract import resolve_path_state_contract


def _startup_file(home: Path) -> str:
    env = {"HOME": str(home), "SHELL": "/bin/bash"}
    return resolve_path_state_contract(env=env, home=home).startup_file


@pytest.mark.parametrize(
    ("present", "expected"),
    [
        ((".bash_profile", ".bash_login", ".profile"), ".bash_profile"),
        ((".bash_login", ".profile"), ".bash_login"),
        ((".profile",), ".profile"),
        ((), ".profile"),
    ],
)
def test_bash_startup_file_follows_login_read_order(tmp_path, present, expected):
    for name in present:
        (tmp_path / name).write_text("")
    assert _startup_file(tmp_path) == str(tmp_path / expected)
