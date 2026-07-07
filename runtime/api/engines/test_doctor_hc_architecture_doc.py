"""Tests for HC-architecture-model-doc-drift."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.engines.doctor_hc_architecture_doc import (
    hc_architecture_model_doc_drift,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from runtime.api.path_context_test_helpers import init_minimal_schema


@pytest.fixture
def conn(tmp_path: Path):
    db = str(tmp_path / "t.db")
    c = init_minimal_schema(db)
    yield c
    c.close()


def _seed_model(conn: Any, **overrides) -> None:
    payload = {
        "domains": [{"id": "claims", "path_roots": ["x"]}],
        "layers": [
            {"id": "domain_invariants", "may_depend_on": [],
             "forbidden_edges": []},
            {"id": "orchestration",
             "may_depend_on": ["domain_invariants"],
             "forbidden_edges": []},
        ],
        "cross_cutting_entrypoints": {
            "db_path": {"approved_modules": ["x"]},
            "events": {"approved_modules": ["y"]},
        },
    }
    payload.update(overrides)
    conn.execute(
        "INSERT INTO project_structure (project_id, family, "
        "attachment_kind, attachment_value, entry_key, payload, "
        "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (1, "architecture_model", "", "project", "",
         json.dumps(payload), iso8601_now(), iso8601_now()),
    )
    conn.commit()


class TestDocDriftHC:
    def test_missing_agents_md_skips(self, conn, tmp_path, monkeypatch):
        _seed_model(conn)
        monkeypatch.chdir(tmp_path)
        rec = RecordCollector()
        hc_architecture_model_doc_drift(
            conn, DoctorArgs(project="yoke"), rec,
        )
        assert rec.results[-1].result == "PASS"
        assert "AGENTS.md missing" in rec.results[-1].detail

    def test_missing_section_warns(self, conn, tmp_path, monkeypatch):
        _seed_model(conn)
        (tmp_path / "AGENTS.md").write_text("# Hello\n\nNo arch section.\n")
        monkeypatch.chdir(tmp_path)
        rec = RecordCollector()
        hc_architecture_model_doc_drift(
            conn, DoctorArgs(project="yoke"), rec,
        )
        assert rec.results[-1].result == "WARN"
        assert "Architecture Model" in rec.results[-1].detail

    def test_missing_layer_in_doc_warns(self, conn, tmp_path, monkeypatch):
        _seed_model(conn)
        # Doc has only one of two layers + only one of two entrypoints.
        doc = (
            "## Architecture Model\n\n"
            "Layer: domain_invariants. Entrypoint: db_path.\n"
        )
        (tmp_path / "AGENTS.md").write_text(doc)
        monkeypatch.chdir(tmp_path)
        rec = RecordCollector()
        hc_architecture_model_doc_drift(
            conn, DoctorArgs(project="yoke"), rec,
        )
        assert rec.results[-1].result == "WARN"
        assert "orchestration" in rec.results[-1].detail
        assert "events" in rec.results[-1].detail

    def test_complete_doc_passes(self, conn, tmp_path, monkeypatch):
        _seed_model(conn)
        doc = (
            "## Architecture Model\n\n"
            "Layers: domain_invariants, orchestration.\n"
            "Entrypoints: db_path, events.\n"
        )
        (tmp_path / "AGENTS.md").write_text(doc)
        monkeypatch.chdir(tmp_path)
        rec = RecordCollector()
        hc_architecture_model_doc_drift(
            conn, DoctorArgs(project="yoke"), rec,
        )
        assert rec.results[-1].result == "PASS"

    def test_missing_model_self_skips(self, conn):
        rec = RecordCollector()
        hc_architecture_model_doc_drift(
            conn, DoctorArgs(project="yoke"), rec,
        )
        assert rec.results[-1].result == "PASS"
        assert "not set" in rec.results[-1].detail
