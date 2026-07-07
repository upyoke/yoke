"""Dispatch tests for ``yoke_core.cli.db_router``.

Companion to ``test_db_router.py``. Covers the routing layer:

- raw-SQL ``query`` pass-through (with the ``-separator`` option)
- ``items`` read/write split (read goes to query; write to backlog CLI)
- ``merge`` pass-through to the merge engine
- generic domain dispatch (e.g. ``projects``, ``project-structure``)
- the ``main(None)`` smoke entry
"""

from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Iterator, Tuple

import pytest

from yoke_core.cli import db_router
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _reset_init_flag() -> None:
    os.environ.pop("YOKE_DB_INIT_DONE", None)


def _run(argv: list) -> Tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = db_router.main(argv)
    return rc, out.getvalue(), err.getvalue()


@pytest.fixture
def fresh_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    """Disposable per-test Postgres DB with schema applied per-test.

    See ``test_db_router.py``'s ``fresh_db`` for the rationale: the seed
    helpers connect through :func:`connect_test_db` and the code-under-test
    reads through ``db_backend.connect()``, so both must share the one
    database ``YOKE_PG_DSN`` is repointed at (isolated under ``-n 2``).
    ``YOKE_DB`` is pinned to the path-shaped compatibility token; the DSN
    is the connection target.
    """
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        monkeypatch.setenv("YOKE_DB_INIT_ALLOW", "1")
        monkeypatch.delenv("YOKE_DB_INIT_DONE", raising=False)
        yield Path(db_path)
        _reset_init_flag()


# ---------------------------------------------------------------------------
# Query (raw SQL) pass-through
# ---------------------------------------------------------------------------


class TestQueryDispatch:
    def test_query_default_separator(self, fresh_db: Path) -> None:
        _run(["help"])  # trigger init so schema exists
        conn = connect_test_db(str(fresh_db))
        try:
            conn.execute(
                "INSERT INTO items "
                "(id, title, status, type, project_id, project_sequence, "
                "created_at, updated_at) "
                "VALUES (42, 'test', 'idea', 'issue', 1, 42, "
                "'2026-01-01', '2026-01-01')"
            )
            conn.commit()
        finally:
            conn.close()

        rc, out, err = _run(["query", "SELECT id, title FROM items WHERE id=42"])
        assert rc == 0
        assert "42|test" in out

    def test_query_custom_separator(self, fresh_db: Path) -> None:
        _run(["help"])
        conn = connect_test_db(str(fresh_db))
        try:
            conn.execute(
                "INSERT INTO items "
                "(id, title, status, type, project_id, project_sequence, "
                "created_at, updated_at) "
                "VALUES (7, 'alpha', 'idea', 'issue', 1, 7, "
                "'2026-01-01', '2026-01-01')"
            )
            conn.commit()
        finally:
            conn.close()

        rc, out, err = _run(
            ["query", "-separator", ";", "SELECT id, title FROM items WHERE id=7"]
        )
        assert rc == 0
        assert "7;alpha" in out


# ---------------------------------------------------------------------------
# Items dispatch
# ---------------------------------------------------------------------------


class TestItemsDispatch:
    def test_items_read_subcmd_routes_to_query_items_cli(
        self, fresh_db: Path
    ) -> None:
        _run(["help"])
        conn = connect_test_db(str(fresh_db))
        try:
            conn.execute(
                "INSERT INTO items "
                "(id, title, status, type, project_id, project_sequence, "
                "created_at, updated_at) "
                "VALUES (5, 'hello', 'refined-idea', 'issue', 1, 5, "
                "'2026-01-01', '2026-01-01')"
            )
            conn.commit()
        finally:
            conn.close()

        rc, out, err = _run(["items", "get", "YOK-5", "title"])
        assert rc == 0
        assert out.strip() == "hello"

    def test_items_write_subcmd_dispatches_python_backlog_cli(
        self, fresh_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = {}

        def fake_dispatch(module_name, function_name, argv):
            captured["module_name"] = module_name
            captured["function_name"] = function_name
            captured["argv"] = argv
            return 0

        monkeypatch.setattr(db_router, "_dispatch_module_function", fake_dispatch)
        rc, out, err = _run(["items", "update", "42", "status", "active"])
        assert rc == 0
        assert captured["module_name"] == "yoke_core.api.service_client"
        assert captured["function_name"] == "cmd_backlog_cli"
        assert captured["argv"] == ["update", "42", "status", "active"]

    def test_items_no_subcmd_returns_usage_error(self, fresh_db: Path) -> None:
        rc, out, err = _run(["items"])
        assert rc == 2
        assert "items requires a subcommand" in err

    def test_items_unknown_subcmd_returns_usage_error(
        self, fresh_db: Path
    ) -> None:
        rc, out, err = _run(["items", "zoinks"])
        assert rc == 2
        assert "unknown items subcommand 'zoinks'" in err


# ---------------------------------------------------------------------------
# Merge pass-through
# ---------------------------------------------------------------------------


class TestMergeDispatch:
    def test_merge_run_dispatches_python_engine(
        self, fresh_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = {}

        def fake_dispatch(module_name, argv):
            captured["module"] = module_name
            captured["argv"] = argv
            return 0

        monkeypatch.setattr(db_router, "_dispatch_python_module", fake_dispatch)
        rc, out, err = _run(["merge", "run", "YOK-9999", "main"])
        assert rc == 0
        assert captured["module"] == "yoke_core.engines.merge_worktree"
        assert captured["argv"] == ["YOK-9999", "main"]

    def test_merge_without_run_returns_usage_error(self, fresh_db: Path) -> None:
        rc, out, err = _run(["merge"])
        assert rc == 2
        assert "merge requires 'run'" in err

    def test_merge_wrong_subcmd_returns_usage_error(self, fresh_db: Path) -> None:
        rc, out, err = _run(["merge", "noop"])
        assert rc == 2
        assert "merge requires 'run'" in err


# ---------------------------------------------------------------------------
# Domain dispatch to Python module
# ---------------------------------------------------------------------------


class TestDomainDispatch:
    def test_projects_list_returns_rows(self, fresh_db: Path) -> None:
        # Create a project via the projects domain CLI itself
        rc, _out, err = _run(["projects", "create", "testproj", "Test"])
        assert rc == 0, err
        rc, out, err = _run(["projects", "list"])
        assert rc == 0
        assert "testproj" in out

    def test_unknown_domain_shows_usage(self, fresh_db: Path) -> None:
        # AC-38 replaced the full 19-domain dump with a nearest-match
        # hint plus a `db_router help` pointer for the full inventory.
        rc, out, err = _run(["total-nonsense"])
        assert rc == 2
        assert "unknown domain 'total-nonsense'" in err
        assert "db_router help" in err

    def test_project_structure_dispatch_family_list(self, fresh_db: Path) -> None:
        """db_router must route ``project-structure`` to the domain module."""
        rc, out, err = _run(["project-structure", "family-list"])
        assert rc == 0, err
        data = json.loads(out)
        assert set(data) == {
            "net_new",
            "attachment_branches",
            "path_selector_kinds",
            "multiplicities",
        }
        assert "areas" in out
        assert "command_definitions" in out
        assert "context_routing" in out

    def test_project_structure_dispatch_get(self, fresh_db: Path) -> None:
        rc, _out, err = _run(["projects", "create", "fresh", "Fresh"])
        assert rc == 0, err
        rc, out, err = _run(["project-structure", "get", "fresh"])
        assert rc == 0, err
        assert '"project_id": "fresh"' in out


# ---------------------------------------------------------------------------
# Module invocation (smoke)
# ---------------------------------------------------------------------------


class TestModuleEntry:
    def test_main_accepts_none_argv(
        self, fresh_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(db_router.sys, "argv", ["db_router", "help"])
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = db_router.main()
        assert rc == 0
        assert "Domains:" in out.getvalue()


# ---------------------------------------------------------------------------
# items get --section dispatch (_dispatch_items_get_section)
# ---------------------------------------------------------------------------


_SECTION_SPEC = (
    "# Title\n\n## Problem\n\nGap text here.\n\n"
    "## File Budget\n\n- runtime/api/cli/db_router_init.py\n"
    "- runtime/api/domain/query_items_cli.py\n\n"
    "## Non-Goals\n\n- nothing else\n"
)


def _seed_section_item(db_path: Path, item_id: int, *, spec: str = "") -> None:
    conn = connect_test_db(str(db_path))
    try:
        conn.execute(
            "INSERT INTO items "
            "(id, title, status, type, project_id, project_sequence, spec, "
            "created_at, updated_at) VALUES (%s, 'fixture', 'refined-idea', "
            "'issue', 1, %s, %s, '2026-01-01', '2026-01-01')",
            (item_id, item_id, spec),
        )
        conn.commit()
    finally:
        conn.close()


class TestItemsGetSection:
    def test_spec_section_returns_matching_block(self, fresh_db: Path) -> None:
        _run(["help"])
        _seed_section_item(fresh_db, 42, spec=_SECTION_SPEC)
        rc, out, err = _run(["items", "get", "YOK-42", "spec",
                             "--section", "## File Budget"])
        assert rc == 0
        assert "runtime/api/cli/db_router_init.py" in out
        assert "runtime/api/domain/query_items_cli.py" in out
        assert "Gap text here" not in out and "Non-Goals" not in out

    def test_body_section_routes_through_body_renderer(self, fresh_db: Path) -> None:
        _run(["help"])
        _seed_section_item(fresh_db, 43, spec=_SECTION_SPEC)
        rc, out, err = _run(["items", "get", "YOK-43", "body",
                             "--section", "## File Budget"])
        assert rc == 0 and "runtime/api/cli/db_router_init.py" in out

    def test_missing_section_is_advisory(self, fresh_db: Path) -> None:
        _run(["help"])
        _seed_section_item(fresh_db, 45, spec=_SECTION_SPEC)
        rc, out, err = _run(["items", "get", "YOK-45", "spec",
                             "--section", "## Bogus"])
        assert rc == 0 and out == ""
        assert "Bogus" in err and "not found" in err

    @pytest.mark.parametrize("field,frag", [
        ("status", "scalar field 'status'"),
        ("nope_field", "unknown field 'nope_field'"),
    ])
    def test_invalid_field_rejected(self, fresh_db: Path, field: str, frag: str) -> None:
        _run(["help"])
        _seed_section_item(fresh_db, 47)
        rc, _, err = _run(["items", "get", "YOK-47", field,
                           "--section", "## File Budget"])
        assert rc == 2 and frag in err
