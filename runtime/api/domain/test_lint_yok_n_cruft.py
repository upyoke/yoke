"""Tests for yoke_core.domain.lint_yok_n_cruft."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import db_backend, lint_yok_n_cruft
from runtime.api.fixtures.file_test_db import init_test_db


# ---------------------------------------------------------------------------
# Synthetic-tree fixtures
# ---------------------------------------------------------------------------


def _seed_lint_items_table() -> None:
    """``init_test_db`` ``apply_schema`` strategy for the cruft lint.

    Builds the tiny two-column ``items`` table the lint's ticket-status lookup
    reads (deliberately NOT the production ``items`` schema) and seeds rows with
    representative statuses. Resolves its own connection through the backend
    factory (``YOKE_DB`` on SQLite, the repointed per-test ``YOKE_PG_DSN`` on
    Postgres), so each test gets an isolated table that never collides with the
    ambient production ``items`` relation on Postgres. The lint's code-under-test
    reads the same disposable DB through ``db_helpers.connect`` (backend-aware).
    """
    conn = db_backend.connect()
    try:
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, status TEXT NOT NULL)"
        )
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        for row in [
            (100, "done"),
            (101, "done"),
            (200, "implementing"),
            (300, "refined-idea"),
            (400, "cancelled"),
        ]:
            conn.execute(f"INSERT INTO items (id, status) VALUES ({p}, {p})", row)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def db_path(tmp_path: Path):
    """Backend-appropriate DB with a tiny ``items`` table of representative
    statuses. SQLite: a real file under ``tmp_path``; Postgres: a disposable
    per-test database (dropped on teardown). The yielded token threads into
    ``scan(db_path=...)``; on Postgres the backend factory ignores it and
    resolves the repointed DSN."""
    with init_test_db(tmp_path, apply_schema=_seed_lint_items_table) as path:
        yield path


def _seed(repo_root: Path) -> None:
    (repo_root / "docs").mkdir()
    (repo_root / ".agents" / "skills" / "yoke").mkdir(parents=True)
    (repo_root / "docs" / "archive" / "decisions").mkdir(parents=True)


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------


def test_flags_done_ticket_in_prose(tmp_path: Path, db_path: str) -> None:
    _seed(tmp_path)
    (tmp_path / "docs" / "foo.md").write_text(
        "This note retains a (YOK-100) provenance tag.\n"
    )
    result = lint_yok_n_cruft.scan(tmp_path, db_path=db_path)
    assert len(result.hits) == 1
    assert result.hits[0].ticket == "YOK-100"
    assert result.hits[0].status == "done"


def test_ignores_open_ticket(tmp_path: Path, db_path: str) -> None:
    _seed(tmp_path)
    (tmp_path / "docs" / "foo.md").write_text(
        "Open bug under investigation: YOK-200.\n"
    )
    result = lint_yok_n_cruft.scan(tmp_path, db_path=db_path)
    assert result.hits == []


def test_ignores_refined_ticket(tmp_path: Path, db_path: str) -> None:
    _seed(tmp_path)
    (tmp_path / "docs" / "foo.md").write_text(
        "Refined for planning: YOK-300.\n"
    )
    result = lint_yok_n_cruft.scan(tmp_path, db_path=db_path)
    assert result.hits == []


def test_ignores_archive_path(tmp_path: Path, db_path: str) -> None:
    _seed(tmp_path)
    (tmp_path / "docs" / "archive" / "old.md").write_text(
        "Historical reference to YOK-100 that predates the rule.\n"
    )
    result = lint_yok_n_cruft.scan(tmp_path, db_path=db_path)
    assert result.hits == []


def test_ignores_archive_decisions_path(tmp_path: Path, db_path: str) -> None:
    """Decision records under ``docs/archive/decisions/`` carry YOK-N
    references deliberately; the ``archive`` segment exemption covers them."""
    _seed(tmp_path)
    (tmp_path / "docs" / "archive" / "decisions" / "100-thing.md").write_text(
        "Stable-slug decision doc that mentions YOK-100 deliberately.\n"
    )
    result = lint_yok_n_cruft.scan(tmp_path, db_path=db_path)
    assert result.hits == []


def test_ignores_ouroboros_path(tmp_path: Path, db_path: str) -> None:
    _seed(tmp_path)
    (tmp_path / "ouroboros").mkdir()
    (tmp_path / "ouroboros" / "patterns.md").write_text(
        "Knowledge-layer note about YOK-100.\n"
    )
    result = lint_yok_n_cruft.scan(tmp_path, db_path=db_path)
    assert result.hits == []


def test_ignores_strategy_path(tmp_path: Path, db_path: str) -> None:
    """.yoke/strategy/ is exempt: planning docs intentionally enumerate ticket IDs as
    inventory data, same category as ouroboros/."""
    _seed(tmp_path)
    (tmp_path / "strategy").mkdir()
    (tmp_path / "strategy" / "WISPS.md").write_text(
        "Inventory row: YOK-100 retired field — tracked for posterity.\n"
    )
    result = lint_yok_n_cruft.scan(tmp_path, db_path=db_path)
    assert result.hits == []


def test_default_scope_excludes_templates_and_projects(tmp_path: Path, db_path: str) -> None:
    """Default scan targets the cold-start prose surfaces only. Code templates
    and per-project surfaces are out of scope unless the caller passes them
    explicitly via extra_paths."""
    _seed(tmp_path)
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "webapp.md").write_text("sample with YOK-100\n")
    (tmp_path / "projects").mkdir()
    (tmp_path / "projects" / "externalwebapp.md").write_text("project note with YOK-100\n")
    result = lint_yok_n_cruft.scan(tmp_path, db_path=db_path)
    assert result.hits == []


def test_extra_paths_broaden_scan_beyond_default(tmp_path: Path, db_path: str) -> None:
    """Extra paths let a caller broaden the scan to surfaces like
    `runtime/`, `.yoke/strategy/`, or `projects/` on demand."""
    _seed(tmp_path)
    (tmp_path / "projects").mkdir()
    (tmp_path / "projects" / "externalwebapp.md").write_text("project note with YOK-100\n")
    result = lint_yok_n_cruft.scan(
        tmp_path,
        db_path=db_path,
        extra_paths=(tmp_path / "projects",),
    )
    assert any(h.ticket == "YOK-100" for h in result.hits)


def test_scans_python_comments_and_docstrings(tmp_path: Path, db_path: str) -> None:
    """Linter now scans Python source alongside Markdown prose.

    Comments and docstrings in ``.py`` are in scope for the cruft policy.
    Quoted ticket literals (``"YOK-N"``) and ``def test_sun_N_*``
    function names are exempted (separate tests cover those cases).
    """
    _seed(tmp_path)
    (tmp_path / "docs" / "foo.py").write_text(
        "# references YOK-100 in a Python comment.\n"
    )
    (tmp_path / "docs" / "foo.md").write_text("clean prose\n")
    result = lint_yok_n_cruft.scan(tmp_path, db_path=db_path)
    assert any(h.ticket == "YOK-100" for h in result.hits)


def test_records_unknown_tickets(tmp_path: Path, db_path: str) -> None:
    """Tickets that don't exist in the DB are recorded as 'unknown' and do NOT
    produce hits. The HC cannot distinguish a deleted-but-done ticket from a
    typo without more evidence, so it errs on the side of silence."""
    _seed(tmp_path)
    (tmp_path / "docs" / "foo.md").write_text("Prose about YOK-99999.\n")
    result = lint_yok_n_cruft.scan(tmp_path, db_path=db_path)
    assert result.hits == []
    assert "YOK-99999" in result.unknown_tickets


def test_multiple_tickets_per_line(tmp_path: Path, db_path: str) -> None:
    _seed(tmp_path)
    (tmp_path / "docs" / "foo.md").write_text(
        "Two done tags in one sentence (YOK-100, YOK-101) should both be flagged.\n"
    )
    result = lint_yok_n_cruft.scan(tmp_path, db_path=db_path)
    tickets = sorted(h.ticket for h in result.hits)
    assert tickets == ["YOK-100", "YOK-101"]


def test_agents_md_top_level_file(tmp_path: Path, db_path: str) -> None:
    """AGENTS.md at repo root is scanned even though it lives outside a
    subdirectory."""
    (tmp_path / "AGENTS.md").write_text(
        "Doctrine file mentioning retired (YOK-100) rule.\n"
    )
    _seed(tmp_path)
    result = lint_yok_n_cruft.scan(tmp_path, db_path=db_path)
    assert any(h.path.name == "AGENTS.md" for h in result.hits)


def test_dedupe_file_count(tmp_path: Path, db_path: str) -> None:
    """Multiple hits in one file count as one file in the summary."""
    _seed(tmp_path)
    (tmp_path / "docs" / "foo.md").write_text(
        "First mention of YOK-100.\n"
        "Second mention of YOK-100 on a later line.\n"
    )
    result = lint_yok_n_cruft.scan(tmp_path, db_path=db_path)
    assert len(result.hits) == 2
    assert len({h.path for h in result.hits}) == 1
