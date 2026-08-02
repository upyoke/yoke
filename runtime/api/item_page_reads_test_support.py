"""In-memory item read-model database fixture."""

from __future__ import annotations

import json
import sqlite3

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
          owner_kind TEXT,
          owner_item_id INTEGER,
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
          created_at TEXT,
          plan_id INTEGER,
          plan_case_key TEXT,
          method_id TEXT,
          workflow_transition_id TEXT,
          instructions TEXT,
          expected_outcome TEXT,
          host_baseline TEXT
        );
        CREATE TABLE qa_runs (
          id INTEGER PRIMARY KEY,
          qa_requirement_id INTEGER,
          verdict TEXT,
          execution_status TEXT,
          completed_at TEXT,
          case_outcome TEXT,
          capture_degraded_reason TEXT,
          raw_result TEXT
        );
        CREATE TABLE qa_plans (
          id INTEGER PRIMARY KEY,
          slug TEXT,
          name TEXT
        );
        CREATE TABLE qa_plan_cases (
          id INTEGER PRIMARY KEY,
          plan_id INTEGER,
          case_key TEXT
        );
        CREATE TABLE qa_plan_project_defaults (
          project_id INTEGER,
          workflow_id TEXT,
          transition_id TEXT,
          qa_phase TEXT,
          plan_id INTEGER,
          attached_at TEXT
        );
        CREATE TABLE qa_plan_item_attachments (
          item_id INTEGER,
          transition_id TEXT,
          qa_phase TEXT,
          plan_id INTEGER,
          attached_at TEXT
        );
        CREATE TABLE qa_methods (
          id TEXT PRIMARY KEY,
          name TEXT
        );
        CREATE TABLE qa_artifacts (
          id INTEGER PRIMARY KEY,
          qa_run_id INTEGER,
          artifact_type TEXT
        );
        CREATE TABLE ouroboros_entries (
          id INTEGER PRIMARY KEY,
          timestamp TEXT,
          agent TEXT,
          context TEXT,
          category TEXT,
          body TEXT,
          reviewed_at TEXT,
          project_id INTEGER
        );
        CREATE TABLE ouroboros_entry_dispositions (
          entry_id INTEGER PRIMARY KEY,
          disposition_kind TEXT,
          state TEXT,
          item_id INTEGER UNIQUE,
          title TEXT,
          instruction TEXT,
          updated_at TEXT
        );
        """
    )
    fixture = builtin_workflow_definition("dash")
    definition = fixture["definition"]
    conn.execute("INSERT INTO projects VALUES (7, 'acme', 'Acme', 'ACM')")
    conn.execute("INSERT INTO workflows VALUES ('dash', 'Dash')")
    conn.execute(
        "INSERT INTO workflow_versions VALUES (?, 'dash', ?, ?, ?)",
        (
            11,
            fixture["version"],
            json.dumps(definition),
            definition_digest(definition),
        ),
    )
    conn.execute(
        """
        INSERT INTO items VALUES (
          51, 'Fix the footer', 'reviewing-implementation', 'medium', 'Rae',
          0, '', '2026-07-25T12:00:00Z', '2026-07-26T12:00:00Z', NULL,
          '{"verification": true, "file_budget": true}',
          'Correct the footer and verify every link.

          ## File Budget
          - `packages/web/footer.js`', '', '', '', '', '', '',
          '', 7, 22, 'dash', 11
        )
        """
    )
    conn.execute("INSERT INTO actors VALUES (3, 'human', NULL)")
    conn.execute("INSERT INTO actor_labels VALUES (3, 'display', 'Codex')")
    conn.execute("INSERT INTO harness_sessions VALUES ('session-z', 3, 'codex')")
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
    conn.execute(
        "INSERT INTO path_claims "
        "(id, owner_kind, owner_item_id, state) "
        "VALUES (2, 'item', 51, 'planned')"
    )
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
        INSERT INTO qa_requirements (
          id, item_id, epic_id, qa_kind, qa_phase, blocking_mode,
          requirement_source, success_policy, waived_at, created_at,
          plan_id, plan_case_key, method_id, workflow_transition_id,
          instructions, expected_outcome
        ) VALUES (
          4, 51, NULL, 'browser-inspection', 'reviewing-implementation',
          'blocking', 'footer-renders', '{}', NULL,
          '2026-07-26T10:30:00Z',
          12, 'responsive-footer', 'browser-inspection',
          'reviewing-implementation',
          'Open the footer at desktop and mobile widths.',
          'Every footer link remains visible and reachable.'
        )
        """
    )
    conn.execute(
        "INSERT INTO qa_plans VALUES (12, 'browser-close', 'Browser closeout')"
    )
    conn.execute("INSERT INTO qa_plan_cases VALUES (31, 12, 'responsive-footer')")
    conn.execute(
        """
        INSERT INTO qa_plan_project_defaults VALUES (
          7, 'dash', 'reviewing-implementation', 'verification', 12,
          '2026-07-25T09:00:00Z'
        )
        """
    )
    conn.execute(
        "INSERT INTO qa_methods VALUES ('browser-inspection', 'Browser inspection')"
    )
    conn.execute(
        """
        INSERT INTO qa_runs (
          id, qa_requirement_id, verdict, execution_status, completed_at,
          case_outcome, capture_degraded_reason
        ) VALUES (
          8, 4, 'needs review', 'completed', 'now', 'needs_review', NULL
        )
        """
    )
    conn.execute("INSERT INTO qa_artifacts VALUES (22, 8, 'screenshot')")
    conn.commit()
    return conn
