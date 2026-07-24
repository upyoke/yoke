"""Retired exceptions file folds into the project config on install."""

from __future__ import annotations

import pathlib

from yoke_cli.project_install.file_line_config_migration import (
    RETIRED_EXCEPTIONS_REL,
    migrate_file_line_exceptions,
)
from yoke_contracts.project_contract.file_line_policy import (
    project_exception_globs,
    project_limit,
)


def _write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_no_retired_file_is_a_no_op(tmp_path: pathlib.Path) -> None:
    result = migrate_file_line_exceptions(tmp_path)

    assert result["attempted"] is False
    assert result["status"] == "skipped"


def test_globs_move_into_project_config_and_retired_file_goes(
    tmp_path: pathlib.Path,
) -> None:
    """A project installed before the move keeps every glob it had."""
    _write(
        tmp_path / RETIRED_EXCEPTIONS_REL,
        "# a comment\ndocs/big.html\ndata/huge.txt\n",
    )
    _write(tmp_path / ".yoke" / "project.config", "# seeded\nfile_line_limit=400\n")

    result = migrate_file_line_exceptions(tmp_path)

    assert result["status"] == "ok"
    assert result["moved_globs"] == ["docs/big.html", "data/huge.txt"]
    assert not (tmp_path / RETIRED_EXCEPTIONS_REL).exists()

    globs = project_exception_globs(tmp_path)
    assert "docs/big.html" in globs
    assert "data/huge.txt" in globs
    # The pre-existing config content survives the append.
    assert project_limit(tmp_path) == 400


def test_migration_is_idempotent(tmp_path: pathlib.Path) -> None:
    _write(tmp_path / RETIRED_EXCEPTIONS_REL, "docs/big.html\n")
    _write(tmp_path / ".yoke" / "project.config", "")

    migrate_file_line_exceptions(tmp_path)
    after_first = project_exception_globs(tmp_path)

    assert migrate_file_line_exceptions(tmp_path)["attempted"] is False
    assert project_exception_globs(tmp_path) == after_first


def test_migration_creates_config_when_absent(tmp_path: pathlib.Path) -> None:
    _write(tmp_path / RETIRED_EXCEPTIONS_REL, "docs/big.html\n")

    migrate_file_line_exceptions(tmp_path)

    assert "docs/big.html" in project_exception_globs(tmp_path)
