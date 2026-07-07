"""Tests for HC-strategy-render-staleness (per-project, multi-checkout).

PASS on fresh renders across mapped checkouts, WARN naming stale,
missing, edited, orphan, or cross-checkout drifted docs, and SKIP
cleanly when the strategy_docs table is absent, no checkouts are
mapped, a mapped checkout is missing from disk, or a project has no
strategy rows yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import pytest

from yoke_core.domain import strategy_docs as sd
from yoke_core.domain.strategy_docs_paths import strategy_view_path
from yoke_core.engines import doctor_hc_strategy_render_staleness as hc_mod
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@dataclass
class _Rec:
    name: str
    desc: str
    status: str
    detail: str


class _Collector:
    def __init__(self) -> None:
        self.records: List[_Rec] = []

    def record(self, name: str, desc: str, status: str, detail: str) -> None:
        self.records.append(_Rec(name, desc, status, detail))


@dataclass
class _Args:
    verbose: bool = False
    quick: bool = True
    only: str = ""
    project: str = "yoke"


SEED_SLUGS = ("MISSION", "VISION", "MASTER-PLAN", "LANDSCAPE", "PAD", "WISPS")

SEED_CONTENT = {
    slug: f"# {slug}\n\nseeded body for {slug}.\n"
    for slug in SEED_SLUGS
}

PROJECT_A = 1
PROJECT_B = 2


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _seed(conn, project_id: int = PROJECT_A) -> None:
    for slug in SEED_SLUGS:
        conn.execute(
            f"INSERT INTO {sd.STRATEGY_DOCS_TABLE} "
            "(project_id, slug, content, updated_at) VALUES (%s, %s, %s, %s)",
            (project_id, slug, SEED_CONTENT[slug], "2026-06-10T00:00:00Z"),
        )
    conn.commit()


def _drop_table(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        conn.execute(f"DROP TABLE IF EXISTS {sd.STRATEGY_DOCS_TABLE}")
        conn.commit()
    finally:
        conn.close()


def _run_hc(tmp_db: str) -> _Rec:
    collector = _Collector()
    conn = connect_test_db(tmp_db)
    try:
        hc_mod.hc_strategy_render_staleness(conn, _Args(), collector)
    finally:
        conn.close()
    (rec,) = collector.records
    return rec


def _map_checkouts(monkeypatch: pytest.MonkeyPatch, *pairs) -> None:
    monkeypatch.setattr(
        hc_mod, "_mapped_checkouts",
        lambda: [(Path(root), pid) for root, pid in pairs],
    )


class TestSkip:
    def test_skips_when_table_missing(self, tmp_db: str) -> None:
        # Fresh init now creates strategy_docs; the skip path survives for
        # DBs predating the table (never re-inited envs) — construct that
        # condition explicitly and doctor must stay green.
        _drop_table(tmp_db)
        rec = _run_hc(tmp_db)
        assert rec.status == "SKIP"
        assert "strategy_docs table missing" in rec.detail

    def test_skips_when_no_checkouts_mapped(
        self, tmp_db: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = connect_test_db(tmp_db)
        try:
            _seed(conn)
        finally:
            conn.close()
        _map_checkouts(monkeypatch)
        rec = _run_hc(tmp_db)
        assert rec.status == "SKIP"
        assert "no checkout" in rec.detail

    def test_checkout_missing_on_disk_noted_not_warned(
        self, tmp_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = connect_test_db(tmp_db)
        try:
            _seed(conn)
        finally:
            conn.close()
        _map_checkouts(
            monkeypatch, (tmp_path / "not-checked-out-here", PROJECT_A),
        )
        rec = _run_hc(tmp_db)
        assert rec.status == "PASS"
        assert "not on disk" in rec.detail

    def test_unseeded_project_noted_not_warned(
        self, tmp_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = tmp_path / "checkout-b"
        root.mkdir()
        _map_checkouts(monkeypatch, (root, PROJECT_B))
        rec = _run_hc(tmp_db)
        assert rec.status == "PASS"
        assert "no strategy rows" in rec.detail


class TestPassAndWarn:
    @pytest.fixture
    def rendered_root(
        self, tmp_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> Path:
        conn = connect_test_db(tmp_db)
        try:
            _seed(conn)
        finally:
            conn.close()
        root = tmp_path / "checkout"
        sd.render_docs(target_root=root, project_id=PROJECT_A)
        _map_checkouts(monkeypatch, (root, PROJECT_A))
        return root

    def test_pass_on_fresh_renders(
        self, tmp_db: str, rendered_root: Path,
    ) -> None:
        rec = _run_hc(tmp_db)
        assert rec.status == "PASS"

    def test_warn_names_stale_doc_after_db_write(
        self, tmp_db: str, rendered_root: Path,
    ) -> None:
        conn = connect_test_db(tmp_db)
        try:
            conn.execute(
                f"UPDATE {sd.STRATEGY_DOCS_TABLE} "
                "SET content = %s, updated_at = %s "
                "WHERE project_id = %s AND slug = %s",
                ("# PAD\n\nnewer in DB\n", "2026-06-11T11:11:11Z",
                 PROJECT_A, "PAD"),
            )
            conn.commit()
        finally:
            conn.close()
        rec = _run_hc(tmp_db)
        assert rec.status == "WARN"
        assert "PAD" in rec.detail
        assert "stale" in rec.detail
        assert "MISSION" not in rec.detail

    def test_warn_names_missing_and_edited_files(
        self, tmp_db: str, rendered_root: Path,
    ) -> None:
        strategy_view_path(rendered_root, "WISPS").unlink()
        vision = strategy_view_path(rendered_root, "VISION")
        first_line, _, _ = vision.read_text(encoding="utf-8").partition("\n")
        vision.write_text(
            first_line + "\nedited without ingest\n", encoding="utf-8",
        )
        rec = _run_hc(tmp_db)
        assert rec.status == "WARN"
        assert "WISPS: rendered file missing" in rec.detail
        assert "VISION: file edited without write-back" in rec.detail
        assert "yoke strategy ingest VISION" in rec.detail

    def test_warn_names_headerless_file(
        self, tmp_db: str, rendered_root: Path,
    ) -> None:
        strategy_view_path(rendered_root, "PAD").write_text(
            "# PAD\n\nheaderless\n", encoding="utf-8",
        )
        rec = _run_hc(tmp_db)
        assert rec.status == "WARN"
        assert "PAD: render header missing" in rec.detail

    def test_warn_names_orphan_file_without_row(
        self, tmp_db: str, rendered_root: Path,
    ) -> None:
        strategy_view_path(rendered_root, "ROGUE").write_text(
            "# ROGUE\n\nno row backs this\n", encoding="utf-8",
        )
        rec = _run_hc(tmp_db)
        assert rec.status == "WARN"
        assert "ROGUE" in rec.detail
        assert "no strategy_docs row" in rec.detail

    def test_second_checkout_is_independently_checked(
        self, tmp_db: str, rendered_root: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = connect_test_db(tmp_db)
        try:
            conn.execute(
                f"INSERT INTO {sd.STRATEGY_DOCS_TABLE} "
                "(project_id, slug, content, updated_at) VALUES (%s, %s, %s, %s)",
                (PROJECT_B, "MISSION", "# B mission\n", "2026-06-10T00:00:00Z"),
            )
            conn.commit()
        finally:
            conn.close()
        root_b = tmp_path / "checkout-b"
        sd.render_docs(target_root=root_b, project_id=PROJECT_B)
        # B's render is fresh; then B's row moves on — only B warns.
        conn = connect_test_db(tmp_db)
        try:
            conn.execute(
                f"UPDATE {sd.STRATEGY_DOCS_TABLE} "
                "SET updated_at = %s WHERE project_id = %s AND slug = %s",
                ("2026-06-11T11:11:11Z", PROJECT_B, "MISSION"),
            )
            conn.commit()
        finally:
            conn.close()
        _map_checkouts(
            monkeypatch, (rendered_root, PROJECT_A), (root_b, PROJECT_B),
        )
        rec = _run_hc(tmp_db)
        assert rec.status == "WARN"
        assert f"project {PROJECT_B}" in rec.detail
        assert f"project {PROJECT_A}" not in rec.detail


def test_registered_in_health_checks() -> None:
    from yoke_core.engines.doctor_registry import HEALTH_CHECKS

    slugs = [check.slug for check in HEALTH_CHECKS]
    assert "strategy-render-staleness" in slugs
