"""Architecture readers ignore inventory-less snapshots without hiding gaps."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_architecture_health import (
    _entry, _model, _write_model,
)
from runtime.api.path_context_test_helpers import init_minimal_schema, mint_target
from yoke_core.domain.architecture_context_data import iter_python_entries
from yoke_core.domain.architecture_health import compute_architecture_health
from yoke_core.domain.architecture_snapshot import ArchitectureSnapshotUnavailable
from yoke_core.domain.project_snapshot_head_refresh import latest_snapshot_commit
from yoke_core.engines.doctor_hc_architecture import (
    hc_architecture_cross_cutting_entrypoint,
    hc_architecture_forbidden_edge,
    hc_architecture_unclassified_path,
)
from yoke_core.engines.doctor_hc_architecture_items import hc_architecture_scan_error
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


@pytest.fixture
def conn(tmp_path):
    connection = init_minimal_schema(str(tmp_path / "snapshot.db"))
    yield connection
    connection.close()


def _snapshot(conn, commit):
    return int(conn.execute(
        "INSERT INTO path_snapshots (project_id, commit_sha, built_at) "
        "VALUES (1, %s, CURRENT_TIMESTAMP) RETURNING id", (commit,),
    ).fetchone()[0])


def _root_only(conn):
    snapshot = _snapshot(conn, "root-only")
    root = mint_target(conn, "yoke", "", kind="dir")
    conn.execute(
        "INSERT INTO path_snapshot_entries (snapshot_id, target_id) VALUES (%s, %s)",
        (snapshot, root),
    )


def test_all_readers_keep_content_when_newer_snapshots_have_no_files(conn):
    _write_model(conn, _model())
    selected = _snapshot(conn, "content")
    tid = mint_target(conn, "yoke", "src/broken.py")
    _entry(conn, selected, tid, "src.broken", [{"scan_error": "bad syntax"}])
    _root_only(conn)
    _snapshot(conn, "empty")
    conn.commit()

    health = compute_architecture_health(conn, "yoke")
    assert health["snapshot_id"] == selected
    assert health["snapshot_commit"] == "content"
    assert health["python_paths"] == 1
    assert health["unclassified"] == 1
    assert iter_python_entries(conn, 1)[0][0] == tid
    assert latest_snapshot_commit(conn, 1) == "content"
    from yoke_core.domain.architecture_map_survey import draft_architecture_map
    assert draft_architecture_map(conn, 1)["payload"]["domains"]
    rec = RecordCollector()
    hc_architecture_scan_error(conn, DoctorArgs(project="yoke"), rec)
    assert rec.results[-1].result == "WARN"
    assert "bad syntax" in rec.results[-1].detail


@pytest.mark.parametrize("root_only", [False, True])
def test_health_refuses_without_file_inventory(conn, root_only):
    _write_model(conn, _model())
    if root_only:
        _root_only(conn)
    with pytest.raises(ArchitectureSnapshotUnavailable, match="architecture_snapshot_unavailable") as exc:
        compute_architecture_health(conn, 1)
    assert "yoke project snapshot sync --project 1" in str(exc.value)
    assert latest_snapshot_commit(conn, 1) == ""


@pytest.mark.parametrize("check", [
    hc_architecture_unclassified_path,
    hc_architecture_forbidden_edge,
    hc_architecture_cross_cutting_entrypoint,
    hc_architecture_scan_error,
])
def test_doctor_fails_without_file_inventory(conn, check):
    _write_model(conn, _model())
    _root_only(conn)
    rec = RecordCollector()
    check(conn, DoctorArgs(project="yoke"), rec)
    assert rec.results[-1].result == "FAIL"
    assert "architecture_snapshot_unavailable" in rec.results[-1].detail
    assert "yoke project snapshot sync" in rec.results[-1].detail


def test_non_python_inventory_is_usable_and_newest_content_wins(conn):
    _write_model(conn, _model())
    old = _snapshot(conn, "older")
    tid = mint_target(conn, "yoke", "src/old.py")
    _entry(conn, old, tid, "src.old", [])
    selected = _snapshot(conn, "docs-only")
    doc = mint_target(conn, "yoke", "README.md")
    conn.execute(
        "INSERT INTO path_snapshot_entries (snapshot_id, target_id, language) "
        "VALUES (%s, %s, 'markdown')", (selected, doc),
    )
    conn.commit()
    health = compute_architecture_health(conn, 1)
    assert health["snapshot_id"] == selected
    assert health["python_paths"] == 0
    assert latest_snapshot_commit(conn, 1) == "docs-only"


def test_health_human_output_names_snapshot(monkeypatch):
    import io
    from types import SimpleNamespace
    from yoke_cli.commands.adapters import project_structure_read as adapter

    output = io.StringIO()

    def emit(**kwargs):
        kwargs["human_writer"](SimpleNamespace(result={"health": {
            "declared": True, "snapshot_id": 42, "snapshot_commit": "abc123",
        }}), output, io.StringIO())
        return 0

    monkeypatch.setattr(adapter, "dispatch_and_emit", emit)
    assert adapter.architecture_health_get(["--project", "sample"]) == 0
    assert "snapshot: 42 commit abc123" in output.getvalue()
