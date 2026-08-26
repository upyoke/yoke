"""Tests for the compact item execution-status read model."""

from __future__ import annotations

import json
import subprocess

from runtime.api.domain.item_execution_status_test_support import (
    NOW,
    add_item as _add_item,
    core_db as core_db,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from yoke_core.domain import item_execution_status, yok_n_parser
from yoke_core.domain.item_execution_status import (
    build_projection,
    main,
    render_text,
)
from yoke_core.domain.item_execution_status_helpers import (
    DEFAULT_QA_TARGET,
    NEAR_CAP_THRESHOLD,
    age_seconds,
    latest_progress_entry,
    normalize_item_id,
    parse_iso,
)
from yoke_core.domain.workflow_registry_sql import marker as _p
from yoke_core.domain.work_claim_targets import make_item_target


_conn = connect_test_db


def test_helpers_handle_z_naive_garbage_and_clamp() -> None:
    assert parse_iso("2026-05-08T12:00:00Z").tzinfo is not None
    assert parse_iso("2026-05-08T12:00:00").tzinfo is not None
    assert parse_iso(None) is None
    assert parse_iso("garbage") is None
    assert age_seconds("2050-01-01T00:00:00Z", now=NOW) == 0
    assert age_seconds("2026-05-08T11:55:00Z", now=NOW) == 5 * 60
    assert age_seconds(None, now=NOW) is None


def test_normalize_item_id_delegates_to_canonical_parser(monkeypatch) -> None:
    seen = []
    monkeypatch.setattr(
        yok_n_parser,
        "parse_item_argument",
        lambda raw: seen.append(raw) or 7,
    )

    assert normalize_item_id("YOK-7") == 7
    assert seen == ["YOK-7"]


def test_latest_progress_entry_handles_no_headline_separator() -> None:
    headline, ts = latest_progress_entry("## 2026-05-08T11:00:00Z entry\nbody only\n")
    assert headline is None
    assert ts == "2026-05-08T11:00:00Z"


def test_unknown_item_returns_explicit_error(core_db) -> None:
    projection = build_projection(999, db_path=core_db, now=NOW)
    assert projection == {
        "ok": False,
        "error": "item not found: YOK-999",
        "item_id": 999,
    }


def test_no_claim_no_path_claims_no_progress_log(core_db, tmp_path) -> None:
    conn = _conn(core_db)
    p = _p(conn)
    try:
        _add_item(conn, 10, spec="")
        conn.execute(
            "INSERT INTO item_status_transitions"
            "(item_id, from_status, to_status, source, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p})",
            (10, "idea", "refining-idea", "backlog-registry", "2026-05-08T11:59:00Z"),
        )
        conn.commit()
    finally:
        conn.close()
    p = build_projection(10, db_path=core_db, repo_root=tmp_path, now=NOW)
    assert p["ok"] is True
    assert p["item"]["yok_id"] == "YOK-10"
    assert p["work_claim"] == {"state": "none"}
    assert p["path_claims"]["total"] == 0
    assert p["path_claims"]["state_counts"] == {}
    assert p["progress_log"]["state"] == "missing"
    assert "Progress Log section missing" in p["warnings"]
    assert p["worktree"]["state"] == "none"
    assert p["latest_transition"]["to_status"] == "refining-idea"
    assert p["latest_transition"]["from_status"] == "idea"
    assert p["health"]["state"] == "warning"


def test_active_claim_includes_holder_age_and_heartbeat(core_db) -> None:
    conn = _conn(core_db)
    p = _p(conn)
    try:
        _add_item(conn, 20)
        conn.execute(
            "INSERT INTO work_claims(session_id, target_kind, scope, "
            "claim_type, claimed_at, last_heartbeat) "
            f"VALUES ({p},{p},{p},{p},{p},{p})",
            (
                "session-A",
                "item",
                make_item_target(20).scope_json(),
                "exclusive",
                "2026-05-08T11:30:00Z",
                "2026-05-08T11:58:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    work = build_projection(20, db_path=core_db, now=NOW)["work_claim"]
    assert work["state"] == "active"
    assert work["holder_session_id"] == "session-A"
    assert work["claim_age_seconds"] == 30 * 60
    assert work["heartbeat_age_seconds"] == 2 * 60


def test_path_claims_counts_and_latest_blocker(core_db) -> None:
    conn = _conn(core_db)
    p = _p(conn)
    try:
        _add_item(conn, 30)
        for state, reason in [
            ("planned", None),
            ("active", None),
            ("released", None),
            ("blocked", "waiting on YOK-99"),
            ("blocked", "newer reason"),
        ]:
            conn.execute(
                "INSERT INTO path_claims(state, blocked_reason, owner_kind, "
                "owner_item_id) "
                f"VALUES ({p}, {p}, 'item', {p})",
                (state, reason, 30),
            )
        conn.commit()
    finally:
        conn.close()
    proj = build_projection(30, db_path=core_db, now=NOW)
    pc = proj["path_claims"]
    assert pc["total"] == 5
    assert pc["state_counts"] == {
        "planned": 1,
        "active": 1,
        "blocked": 2,
        "released": 1,
    }
    assert pc["latest_blocker_reason"] == "newer reason"
    assert any("blocked" in w for w in proj["warnings"])


def test_progress_log_present_with_latest_entry(core_db) -> None:
    log = (
        "## 2026-05-07T10:00:00Z entry — first headline\n"
        "body line 1\n\n"
        "## 2026-05-07T11:50:00Z entry — second headline\n"
        "body line 2\n"
    )
    conn = _conn(core_db)
    p = _p(conn)
    try:
        _add_item(conn, 40)
        conn.execute(
            "INSERT INTO item_sections(item_id, section_name, content, "
            f"updated_at) VALUES ({p}, {p}, {p}, {p})",
            (40, "Progress Log", log, "2026-05-08T11:50:00Z"),
        )
        conn.commit()
    finally:
        conn.close()
    pl = build_projection(40, db_path=core_db, now=NOW)["progress_log"]
    assert pl["state"] == "present"
    assert pl["latest_headline"] == "second headline"
    assert pl["latest_entry_at"] == "2026-05-07T11:50:00Z"
    assert pl["latest_entry_age_seconds"] == (24 * 60 + 10) * 60
    assert pl["is_stale"] is True


def test_file_budget_line_counts_and_near_cap_flags(core_db, tmp_path) -> None:
    spec_text = (
        "intro\n## File Budget\n- `src/big.py`\n- `src/medium.py`\n"
        "- `src/small.py`\n- `src/missing.py`\n## Other\n"
    )
    conn = _conn(core_db)
    try:
        _add_item(conn, 50, spec=spec_text)
    finally:
        conn.close()
    src = tmp_path / "src"
    src.mkdir()
    (src / "big.py").write_text("x\n" * 360)
    (src / "medium.py").write_text("x\n" * (NEAR_CAP_THRESHOLD + 1))
    (src / "small.py").write_text("x\n" * 100)
    proj = build_projection(50, db_path=core_db, repo_root=tmp_path, now=NOW)
    fb = proj["file_budget"]
    assert fb["total"] == 4
    by_path = {entry["path"]: entry for entry in fb["paths"]}
    assert by_path["src/big.py"]["over_cap"] is True
    assert by_path["src/medium.py"]["near_cap"] is True
    assert by_path["src/medium.py"]["over_cap"] is False
    assert by_path["src/small.py"]["near_cap"] is False
    assert by_path["src/missing.py"]["exists"] is False
    assert by_path["src/missing.py"]["line_count"] is None
    assert fb["over_cap_count"] == 1
    assert fb["near_cap_count"] == 2  # big.py is near AND over the cap
    assert fb["missing_count"] == 1
    assert any("over the" in w for w in proj["warnings"])


def test_file_budget_prefers_existing_worktree(core_db, tmp_path) -> None:
    spec_text = "## File Budget\n- `src/new.py`\n"
    conn = _conn(core_db)
    try:
        register_machine_checkout(tmp_path / "machine-config", tmp_path, 1)
        _add_item(conn, 60, worktree="YOK-60", spec=spec_text)
    finally:
        conn.close()
    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    wt_src = tmp_path / ".worktrees" / "YOK-60" / "src"
    wt_src.mkdir(parents=True)
    (wt_src / "new.py").write_text("x\n" * 12)
    proj = build_projection(60, db_path=core_db, repo_root=tmp_path, now=NOW)
    assert proj["worktree"]["state"] == "set"
    assert proj["worktree"]["exists"] is True
    assert proj["file_budget"]["paths"][0]["line_count"] == 12


_WRITABLE = (
    "items",
    "item_worktrees",
    "work_claims",
    "path_claims",
    "item_sections",
    "item_status_transitions",
)


def _row_counts(conn) -> dict:
    return {
        t: int(conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"])
        for t in _WRITABLE
    }


def test_projection_does_not_write_db(core_db) -> None:
    conn = _conn(core_db)
    try:
        _add_item(conn, 70)
    finally:
        conn.close()
    conn = connect_test_db(core_db)
    before = _row_counts(conn)
    try:
        build_projection(70, conn=conn, db_path=core_db, now=NOW)
        after = _row_counts(conn)
    finally:
        conn.close()
    assert after == before


def test_text_and_json_render_from_same_projection(core_db, tmp_path) -> None:
    conn = _conn(core_db)
    try:
        _add_item(conn, 80, title="Render parity")
    finally:
        conn.close()
    proj = build_projection(80, db_path=core_db, repo_root=tmp_path, now=NOW)
    text = render_text(proj)
    rebuilt = json.loads(json.dumps(proj))
    assert render_text(rebuilt) == text
    assert "YOK-80 [issue] — Render parity" in text


def test_main_unknown_item_returns_nonzero(core_db, monkeypatch, capsys):
    monkeypatch.setenv("YOKE_DB", core_db)
    monkeypatch.setattr(item_execution_status, "normalize_item_id", lambda _raw: 999)
    rc = main(["YOK-999", "--json"])
    captured = capsys.readouterr()
    assert rc == 1
    body = json.loads(captured.out)
    assert body["ok"] is False
    assert body["item_id"] == 999


def test_main_renders_text_for_present_item(core_db, tmp_path, monkeypatch, capsys):
    conn = _conn(core_db)
    try:
        _add_item(conn, 90, title="Live item")
    finally:
        conn.close()
    monkeypatch.setenv("YOKE_DB", core_db)
    rc = main(["YOK-90", "--repo-root", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "YOK-90 [issue] — Live item" in captured.out
    assert "missing" in captured.out


def test_qa_default_target_and_public_surface() -> None:
    assert DEFAULT_QA_TARGET == "reviewed-implementation"
    assert "build_projection" in item_execution_status.__all__
    assert "render_text" in item_execution_status.__all__
    assert "main" in item_execution_status.__all__
