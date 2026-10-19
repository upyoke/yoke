"""`yoke task` refuses projects with a code repository and names `yoke dash`."""

from __future__ import annotations

import os
from io import StringIO
from unittest import mock

from runtime.api.backlog_mutations_test_helpers import (
    _conn,
    _patch_externals,
    tmp_db,  # noqa: F401 — re-exported pytest fixture
)
from yoke_cli.commands.adapters import task
from yoke_contracts.session_identity import AMBIENT_ENV_VARS


def remove_code_repository(db_path: str, slug: str = "yoke") -> None:
    """Make the fixture project folder-only: no registered code repository."""
    conn = _conn(db_path)
    try:
        conn.execute("UPDATE projects SET github_repo = NULL WHERE slug = %s", (slug,))
        conn.commit()
    finally:
        conn.close()


def _item_count(db_path: str) -> int:
    conn = _conn(db_path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM items").fetchone()[0])
    finally:
        conn.close()


def _file_task(db_path: str, monkeypatch) -> int:
    for name in AMBIENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("sys.stdin", StringIO("Edit the parser source and land it."))
    with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": db_path}):
        return task.task_file(
            [
                "--title",
                "Change the parser",
                "--stdin",
                "--project",
                "yoke",
                "--execution-instructions-considered",
            ]
        )


def test_task_refuses_a_project_with_a_code_repository(
    tmp_db,  # noqa: F811 — pytest injects the re-exported fixture
    monkeypatch,
    capsys,
):
    before = _item_count(tmp_db)

    assert _file_task(tmp_db, monkeypatch) == 1

    err = capsys.readouterr().err
    assert "task_workflow_code_project" in err
    assert "upyoke/yoke" in err
    assert "yoke dash --title TEXT --spec-file PATH --project yoke" in err
    assert _item_count(tmp_db) == before


def test_task_files_in_a_folder_only_project(
    tmp_db,  # noqa: F811 — pytest injects the re-exported fixture
    monkeypatch,
):
    remove_code_repository(tmp_db)

    assert _file_task(tmp_db, monkeypatch) == 0

    conn = _conn(tmp_db)
    try:
        (workflow_id,) = conn.execute(
            "SELECT workflow_id FROM items ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert workflow_id == "task"
