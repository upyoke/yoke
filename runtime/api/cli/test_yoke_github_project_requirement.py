"""GitHub adapters require an explicit project instead of guessing one."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

import pytest

from yoke_cli.main import main as cli_main


@pytest.mark.parametrize(
    "argv",
    [
        ("github-actions", "check-ci", "o/r", "ci.yml"),
        ("github-actions", "wait-run", "o/r", "123"),
        ("github-actions", "runners", "status", "o/r"),
        ("github-actions", "secret", "set", "o/r", "NAME", "value"),
        ("github-actions", "variable", "get", "o/r", "NAME"),
        (
            "github-actions", "variable", "set", "o/r", "NAME",
            "--value", "value",
        ),
        ("github", "pr", "create", "--title", "T", "--head", "branch"),
    ],
)
def test_github_adapter_rejects_missing_project(argv: tuple[str, ...]) -> None:
    with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
        rc = cli_main(list(argv))

    assert rc == 2
    assert out.getvalue() == ""
    assert "--project" in err.getvalue()
