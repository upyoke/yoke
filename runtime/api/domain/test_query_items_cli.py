from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.query_items_cli import main
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def test_missing_subcommand_shows_usage(capsys) -> None:
    rc = main([])
    assert rc == 2
    err = capsys.readouterr().err
    assert "subcommand required" in err
    assert "db_router items list" in err


def test_unknown_subcommand_shows_usage(capsys) -> None:
    rc = main(["bogus"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "unknown subcommand 'bogus'" in err
    assert "db_router items list" in err


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Backend-aware per-test DB: SQLite file or disposable PG database
    # with the production schema applied. On Postgres init_test_db repoints
    # YOKE_PG_DSN for the context; YOKE_DB is set for the SQLite read path.
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", str(db_path))
        yield Path(db_path)


def _seed_item(
    db_path: Path,
    item_id: int,
    *,
    title: str = "fixture",
    status: str = "refined-idea",
    spec: str = "",
) -> None:
    conn = connect_test_db(str(db_path))
    try:
        conn.execute(
            "INSERT INTO items "
            "(id, project_id, project_sequence, title, status, type, spec, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                item_id, 1, item_id, title, status, "issue", spec,
                "2026-01-01", "2026-01-01",
            ),
        )
        conn.commit()
    finally:
        conn.close()


class TestMultiFieldGet:
    """``items get`` with N>1 fields (Gap 2)."""

    def test_three_scalar_fields_emit_one_value_per_line(
        self, fresh_db: Path, capsys: pytest.CaptureFixture
    ) -> None:
        _seed_item(fresh_db, 51, title="hello", status="implementing")
        rc = main(["get", "YOK-51", "status", "title", "type"])
        out = capsys.readouterr().out
        lines = out.splitlines()
        assert rc == 0
        assert lines == ["implementing", "hello", "issue"]

    def test_single_field_get_still_works(
        self, fresh_db: Path, capsys: pytest.CaptureFixture
    ) -> None:
        _seed_item(fresh_db, 52, title="solo")
        rc = main(["get", "YOK-52", "title"])
        out = capsys.readouterr().out
        assert rc == 0
        assert out.strip() == "solo"

    def test_multi_field_with_large_text_field(
        self, fresh_db: Path, capsys: pytest.CaptureFixture
    ) -> None:
        # Large text fields stream via the temp-file path in
        # multi-field invocations. Spec is a structured large-text field.
        spec = "# Title\n\n## Problem\n\nbody-text\n"
        _seed_item(fresh_db, 53, title="hello", spec=spec)
        rc = main(["get", "YOK-53", "status", "spec", "type"])
        out = capsys.readouterr().out
        assert rc == 0
        # All three values appear in argument order.
        assert "refined-idea" in out
        assert "# Title" in out
        assert "body-text" in out
        # ``issue`` is the type value; appears AFTER the spec content.
        assert out.index("body-text") < out.index("issue")

    def test_unknown_field_in_multi_field_returns_error(
        self, fresh_db: Path, capsys: pytest.CaptureFixture
    ) -> None:
        _seed_item(fresh_db, 54)
        rc = main(["get", "YOK-54", "status", "nope_field"])
        captured = capsys.readouterr()
        assert rc == 2
        assert captured.out == ""
        assert "unknown field 'nope_field'" in captured.err

    def test_json_flag_keeps_legacy_plain_text_output(
        self, fresh_db: Path, capsys: pytest.CaptureFixture
    ) -> None:
        _seed_item(fresh_db, 55, title="compat", status="implementing")
        rc = main(["get", "YOK-55", "status", "title", "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        assert out.splitlines() == ["implementing", "compat"]

    def test_missing_item_propagates_not_found(
        self, fresh_db: Path, capsys: pytest.CaptureFixture
    ) -> None:
        # No seed — item-not-found = exit 1 per single-field semantics.
        rc = main(["get", "YOK-9999", "status", "title"])
        assert rc == 1
