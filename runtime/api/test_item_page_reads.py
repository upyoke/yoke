from __future__ import annotations

import json
import sqlite3

from yoke_core.domain import item_detail_read, item_overview_read
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.workflow_registry import definition_digest


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE projects (
          id INTEGER PRIMARY KEY,
          slug TEXT,
          name TEXT,
          public_item_prefix TEXT
        );
        CREATE TABLE workflows (
          id TEXT PRIMARY KEY,
          name TEXT
        );
        CREATE TABLE workflow_versions (
          id INTEGER PRIMARY KEY,
          workflow_id TEXT,
          version INTEGER,
          definition_json TEXT,
          definition_digest TEXT
        );
        CREATE TABLE items (
          id INTEGER PRIMARY KEY,
          title TEXT,
          status TEXT,
          priority TEXT,
          owner TEXT,
          blocked INTEGER,
          blocked_reason TEXT,
          created_at TEXT,
          updated_at TEXT,
          deployment_flow TEXT,
          workflow_posture TEXT,
          spec TEXT,
          design_spec TEXT,
          technical_plan TEXT,
          worktree_plan TEXT,
          shepherd_log TEXT,
          shepherd_caveats TEXT,
          test_results TEXT,
          deploy_log TEXT,
          project_id INTEGER,
          project_sequence INTEGER,
          workflow_id TEXT,
          workflow_version_id INTEGER
        );
        CREATE TABLE work_claims (
          id INTEGER PRIMARY KEY,
          item_id INTEGER,
          session_id TEXT,
          target_kind TEXT,
          claim_type TEXT,
          claimed_at TEXT,
          released_at TEXT
        );
        CREATE TABLE harness_sessions (
          session_id TEXT PRIMARY KEY,
          actor_id INTEGER,
          executor TEXT
        );
        CREATE TABLE actors (
          id INTEGER PRIMARY KEY,
          kind TEXT,
          system_component TEXT
        );
        CREATE TABLE actor_labels (
          actor_id INTEGER,
          surface TEXT,
          label TEXT
        );
        CREATE TABLE item_worktrees (
          id INTEGER PRIMARY KEY,
          item_id INTEGER,
          session_id TEXT,
          branch TEXT,
          path TEXT,
          lane_role TEXT,
          state TEXT,
          created_at TEXT,
          updated_at TEXT,
          released_at TEXT
        );
        CREATE TABLE path_claims (
          id INTEGER PRIMARY KEY,
          item_id INTEGER,
          state TEXT
        );
        CREATE TABLE item_sections (
          item_id INTEGER,
          section_name TEXT,
          content TEXT,
          ordering INTEGER,
          source TEXT,
          created_at TEXT,
          updated_at TEXT
        );
        CREATE TABLE qa_requirements (
          id INTEGER PRIMARY KEY,
          item_id INTEGER,
          epic_id INTEGER,
          qa_kind TEXT,
          qa_phase TEXT,
          blocking_mode TEXT,
          requirement_source TEXT,
          success_policy TEXT,
          waived_at TEXT,
          created_at TEXT
        );
        CREATE TABLE qa_runs (
          id INTEGER PRIMARY KEY,
          qa_requirement_id INTEGER,
          verdict TEXT,
          execution_status TEXT,
          completed_at TEXT
        );
        """
    )
    fixture = builtin_workflow_definition("dash")
    definition = fixture["definition"]
    conn.execute(
        "INSERT INTO projects VALUES (7, 'acme', 'Acme', 'ACM')"
    )
    conn.execute("INSERT INTO workflows VALUES ('dash', 'Dash')")
    conn.execute(
        "INSERT INTO workflow_versions VALUES (?, 'dash', 1, ?, ?)",
        (11, json.dumps(definition), definition_digest(definition)),
    )
    conn.execute(
        """
        INSERT INTO items VALUES (
          51, 'Fix the footer', 'reviewing-implementation', 'medium', 'Rae',
          0, '', '2026-07-25T12:00:00Z', '2026-07-26T12:00:00Z', NULL,
          '{"verification": true}',
          'Correct the footer and verify every link.', '', '', '', '', '', '',
          '', 7, 22, 'dash', 11
        )
        """
    )
    conn.execute("INSERT INTO actors VALUES (3, 'human', NULL)")
    conn.execute(
        "INSERT INTO actor_labels VALUES (3, 'display', 'Codex')"
    )
    conn.execute(
        "INSERT INTO harness_sessions VALUES ('session-z', 3, 'codex')"
    )
    conn.execute(
        """
        INSERT INTO work_claims VALUES (
          9, 51, 'session-z', 'item', 'exclusive',
          '2026-07-26T10:00:00Z', NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO item_worktrees VALUES (
          1, 51, 'session-z', 'codex/footer', '/tmp/footer',
          'implementation', 'active', 'now', 'now', NULL
        )
        """
    )
    conn.execute("INSERT INTO path_claims VALUES (2, 51, 'planned')")
    conn.execute(
        """
        INSERT INTO item_sections VALUES (
          51, 'Progress Log', '## 2026-07-26 entry — built', 200,
          'test', 'now', 'now'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO qa_requirements VALUES (
          4, 51, NULL, 'browser-inspection', 'reviewing-implementation',
          'blocking', 'footer-renders', '{}', NULL, 'now'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO qa_runs VALUES (
          8, 4, 'needs review', 'completed', 'now'
        )
        """
    )
    conn.commit()
    return conn


def test_overview_enrichment_keeps_owner_and_live_claim_distinct(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(
        item_overview_read.db_helpers, "connect", lambda: conn,
    )
    rows = item_overview_read.enrich_item_overview_rows([{
        "id": "51",
        "title": "Fix the footer",
        "workflow_id": "dash",
        "workflow_version_id": "11",
        "status": "reviewing-implementation",
        "project": "acme",
    }])

    assert rows[0]["public_ref"] == "ACM-22"
    assert rows[0]["project_name"] == "Acme"
    assert rows[0]["owner"] == "Rae"
    assert rows[0]["claimed_by"]["actor_label"] == "Codex"
    assert rows[0]["claimed_by"]["session_id"] == "session-z"


def test_detail_read_assembles_real_workflow_lanes_and_proof(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(item_detail_read.db_helpers, "connect", lambda: conn)
    item = item_detail_read.get_item_detail(51)

    assert item["public_ref"] == "ACM-22"
    assert item["title"] == "Fix the footer"
    assert item["workflow"]["id"] == "dash"
    assert item["workflow"]["version"] == 1
    assert item["workflow"]["stage_label"] == "Reviewing implementation"
    assert item["workflow"]["executor_id"] == "dash"
    assert item["workflow"]["next_executor_id"] is None
    assert item["workflow"]["item_posture"] == {"verification": True}
    assert item["claim"]["actor_label"] == "Codex"
    assert item["worktrees"][0]["branch"] == "codex/footer"
    assert item["path_claims"] == {"total": 1, "states": {"planned": 1}}
    assert item["progress_log"]["content"].endswith("built")
    assert item["qa_requirements"][0]["requirement_source"] == "footer-renders"
    assert item["qa_requirements"][0]["verdict"] == "needs review"
    assert "Correct the footer" in item["narrative"]["spec"]


def test_detail_read_preserves_engine_wait_state_without_executor(monkeypatch):
    conn = _connection()
    conn.execute(
        "UPDATE items SET status = 'blocked', blocked = 1 WHERE id = 51"
    )
    conn.commit()
    monkeypatch.setattr(item_detail_read.db_helpers, "connect", lambda: conn)

    item = item_detail_read.get_item_detail(51)

    assert item["workflow"]["stage_id"] == "blocked"
    assert item["workflow"]["stage_label"] == "Blocked"
    assert item["workflow"]["executor_id"] is None
    assert item["workflow"]["next_executor_id"] is None
